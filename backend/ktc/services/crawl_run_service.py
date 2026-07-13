"""`crawl_runs` 작업 도메인 서비스.

REST/MCP는 작업 생성만 하고, scheduler 단일 실행자가 claim·heartbeat·완료를
처리한다(ADR-13). 모든 상태 전이를 한 곳에 모아 API/MCP/scheduler가 동일한
경로를 공유하게 한다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ktc.models import (
    TERMINAL_RUN_STATES,
    CrawlRun,
    CrawlRunStageEvent,
    RunAttention,
    RunState,
    utcnow,
)
from ktc.services.list_pagination import (
    MAX_DB_INTEGER_ID,
    ListPage,
    decode_cursor,
    encode_cursor,
    ensure_repeatable_read,
    filter_fingerprint,
)

logger = logging.getLogger(__name__)

# stale 판단 기본 임계값(초). heartbeat가 이 시간 이상 갱신되지 않으면 재투입 대상.
DEFAULT_STALE_THRESHOLD_SECONDS = 300
# 최대 재시도 횟수. 초과 시 failed로 격리한다.
DEFAULT_MAX_RETRIES = 3
# 작업별 상세 로그는 UI 표시용이므로 최근 항목만 보존한다.
MAX_STATUS_LOGS = 80
# stage event detail 상한(비대 방지 — 상세 로그가 아니라 측정치 주석이다).
_MAX_STAGE_DETAIL_CHARS = 2_000

# handler/ETL 서비스에 주입하는 단계 이벤트 콜백 계약(키워드 인자):
# (stage, *, outcome, provider=None, attempt=None, item_ref=None,
#  started_at=None, finished_at=None, elapsed_ms=None, detail=None)
StageReporter = Callable[..., Awaitable[None]]


def _clamp_progress(progress: float) -> float:
    return max(0.0, min(1.0, progress))


def load_status_logs(run: CrawlRun) -> list[dict[str, Any]]:
    """작업 상태 로그 JSON을 UI가 쓰기 쉬운 list로 파싱한다."""
    if not run.status_log_json:
        return []
    try:
        parsed = json.loads(run.status_log_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    logs: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict) or not isinstance(item.get("message"), str):
            continue
        progress = item.get("progress")
        logs.append(
            {
                "timestamp": item.get("timestamp")
                if isinstance(item.get("timestamp"), str)
                else "",
                "level": item.get("level") if isinstance(item.get("level"), str) else "info",
                "message": item["message"],
                "progress": progress if isinstance(progress, (int, float)) else None,
            }
        )
    return logs


def _append_log_to_run(
    run: CrawlRun,
    message: str,
    *,
    progress: float | None = None,
    level: str = "info",
    touch_heartbeat: bool = True,
) -> None:
    now = utcnow()
    if progress is not None:
        run.progress = _clamp_progress(progress)
    if touch_heartbeat:
        run.heartbeat_at = now
    run.current_message = message
    logs = load_status_logs(run)
    logs.append(
        {
            "timestamp": now.isoformat(),
            "level": level,
            "message": message,
            "progress": run.progress,
        }
    )
    run.status_log_json = json.dumps(logs[-MAX_STATUS_LOGS:], ensure_ascii=False)


def _clip(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    return value[:limit]


async def record_stage_event(
    session: AsyncSession,
    run_id: int,
    *,
    stage: str,
    outcome: str,
    provider: str | None = None,
    attempt: int | None = None,
    item_ref: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    elapsed_ms: int | None = None,
    detail: str | None = None,
) -> None:
    """durable 단계 이벤트 1건을 best-effort로 기록한다(T-162, PR-34).

    호출자 세션이 아니라 같은 엔진의 **짧은 독립 세션**에서 즉시 commit한다. 근거:
    (a) 실패 경로가 가장 중요한 측정 대상인데, 호출자 세션에 얹으면 handler 예외 시
        rollback으로 이벤트가 함께 유실된다.
    (b) 호출자 세션에서 임의 시점 commit하면 handler의 미완 도메인 변경이 부분
        커밋된다(트랜잭션 경계 오염).
    기록 실패는 경고 로그만 남기고 삼킨다 — 관측 실패가 본 작업을 죽여서는 안 된다.
    """
    try:
        now = utcnow()
        if finished_at is None:
            finished_at = now
        if started_at is None:
            # elapsed_ms가 있으면 역산해 시작 시각을 보존한다.
            started_at = (
                finished_at - timedelta(milliseconds=elapsed_ms)
                if elapsed_ms is not None
                else finished_at
            )
        if elapsed_ms is None:
            elapsed_ms = max(
                0, int((finished_at - started_at).total_seconds() * 1000)
            )
        event = CrawlRunStageEvent(
            run_id=run_id,
            stage=_clip(stage, 32) or "unknown",
            provider=_clip(provider, 32),
            attempt=attempt,
            item_ref=_clip(item_ref, 64),
            started_at=started_at,
            finished_at=finished_at,
            elapsed_ms=elapsed_ms,
            outcome=_clip(outcome, 16) or "unknown",
            detail=_clip(detail, _MAX_STAGE_DETAIL_CHARS),
        )
        factory = async_sessionmaker(session.bind, expire_on_commit=False)
        async with factory() as event_session:
            event_session.add(event)
            await event_session.commit()
    except Exception as exc:  # noqa: BLE001 - best-effort 관측 기록
        logger.warning(
            "crawl_run stage event 기록 실패(run_id=%s, stage=%s): %s",
            run_id,
            stage,
            exc,
        )


def make_stage_reporter(session: AsyncSession, run_id: int) -> StageReporter:
    """run에 바인딩된 단계 이벤트 콜백을 만든다(ETL 서비스 주입용)."""

    async def _report_stage(stage: str, **kwargs: Any) -> None:
        await record_stage_event(session, run_id, stage=stage, **kwargs)

    return _report_stage


async def list_stage_events(
    session: AsyncSession, run_id: int
) -> list[CrawlRunStageEvent]:
    """작업의 단계 이벤트를 발생 순서로 조회한다."""
    result = await session.execute(
        select(CrawlRunStageEvent)
        .where(CrawlRunStageEvent.run_id == run_id)
        .order_by(CrawlRunStageEvent.id.asc())
    )
    return list(result.scalars().all())


async def create_run(
    session: AsyncSession,
    *,
    job_type: str,
    source: str,
    target_type: str | None = None,
    target_id: str | None = None,
    payload: dict[str, Any] | None = None,
    restart_of_run_id: int | None = None,
    commit: bool = True,
) -> CrawlRun:
    """새 작업을 `pending` 상태로 생성한다."""
    initial_message = "작업이 대기열에 등록되었습니다."
    run = CrawlRun(
        job_type=job_type,
        source=source,
        target_type=target_type,
        target_id=target_id,
        state=RunState.PENDING,
        progress=0.0,
        payload_json=json.dumps(payload, ensure_ascii=False) if payload else None,
        restart_of_run_id=restart_of_run_id,
    )
    _append_log_to_run(run, initial_message, progress=0.0, touch_heartbeat=False)
    session.add(run)
    await session.flush()
    if commit:
        await session.commit()
        await session.refresh(run)
    return run


async def get_run(session: AsyncSession, run_id: int) -> CrawlRun | None:
    """작업 1건을 조회한다."""
    return await session.get(CrawlRun, run_id)


async def list_runs(
    session: AsyncSession,
    *,
    state: str | None = None,
    limit: int = 50,
    job_types: list[str] | None = None,
) -> list[CrawlRun]:
    """작업 목록을 최신순으로 조회한다.

    `job_types`가 주어지면 해당 job_type만 필터링한다(예: 내부 `source_scan`을
    숨기고 사용자 작업만 보기). 비어 있으면 전체.
    """
    stmt = select(CrawlRun).order_by(CrawlRun.id.desc()).limit(limit)
    if state is not None:
        stmt = stmt.where(CrawlRun.state == state)
    if job_types:
        stmt = stmt.where(CrawlRun.job_type.in_(job_types))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_runs_page(
    session: AsyncSession,
    *,
    state: str | None = None,
    limit: int = 50,
    job_types: list[str] | None = None,
    cursor: str | None = None,
    newer_than_id: int | None = None,
) -> ListPage[CrawlRun]:
    """작업 목록을 최신 ID 기준의 안정적인 keyset page로 반환한다."""
    await ensure_repeatable_read(session)
    normalized_job_types = sorted(set(job_types or []))
    fingerprint = filter_fingerprint(
        scope="runs-v1",
        sort="latest",
        filters={"state": state, "job_types": normalized_job_types},
    )
    decoded = (
        decode_cursor(cursor, fingerprint=fingerprint, key_count=1)
        if cursor
        else None
    )
    if decoded is not None and (
        not isinstance(decoded.keys[0], int)
        or isinstance(decoded.keys[0], bool)
        or decoded.keys[0] < 1
        or decoded.keys[0] > MAX_DB_INTEGER_ID
        or decoded.keys[0] > decoded.snapshot_id
    ):
        raise ValueError("유효하지 않은 작업 목록 cursor입니다")

    conditions = []
    if state is not None:
        conditions.append(CrawlRun.state == state)
    if normalized_job_types:
        conditions.append(CrawlRun.job_type.in_(normalized_job_types))

    if decoded is None:
        newest_id = await session.scalar(select(func.max(CrawlRun.id)).where(*conditions))
        snapshot_id = int(newest_id or 0)
    else:
        snapshot_id = decoded.snapshot_id

    snapshot_conditions = [*conditions, CrawlRun.id <= snapshot_id]
    total = int(
        await session.scalar(
            select(func.count(CrawlRun.id)).where(*snapshot_conditions)
        )
        or 0
    )
    newer_than = 0
    if newer_than_id is not None:
        newer_than = int(
            await session.scalar(
                select(func.count(CrawlRun.id)).where(
                    *conditions, CrawlRun.id > newer_than_id
                )
            )
            or 0
        )

    page_conditions = list(snapshot_conditions)
    if decoded is not None:
        page_conditions.append(CrawlRun.id < decoded.keys[0])
    rows = list(
        (
            await session.execute(
                select(CrawlRun)
                .where(*page_conditions)
                .order_by(CrawlRun.id.desc())
                .limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = (
        encode_cursor(
            fingerprint=fingerprint,
            snapshot_id=snapshot_id,
            keys=(items[-1].id,),
        )
        if has_more and items
        else None
    )
    return ListPage(
        items=items,
        next_cursor=next_cursor,
        has_more=has_more,
        total=total,
        newest_id=snapshot_id or None,
        newer_than=newer_than,
    )


async def claim_next_pending(session: AsyncSession) -> CrawlRun | None:
    """가장 오래된 `pending` 작업 1건을 claim해 `running`으로 전이한다.

    PostgreSQL `FOR UPDATE SKIP LOCKED`로 후보를 잠근 뒤 전이한다.
    """
    stmt = (
        select(CrawlRun)
        .where(CrawlRun.state == RunState.PENDING)
        .order_by(CrawlRun.id.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    result = await session.execute(stmt)
    run = result.scalars().first()
    if run is None:
        return None

    now = utcnow()
    run.state = RunState.RUNNING
    run.started_at = now
    run.heartbeat_at = now
    _append_log_to_run(run, "작업 실행자가 작업을 시작했습니다.", progress=0.05)
    await session.commit()
    await session.refresh(run)
    return run


async def heartbeat(
    session: AsyncSession,
    run_id: int,
    *,
    progress: float | None = None,
    current_message: str | None = None,
) -> None:
    """실행 중 작업의 heartbeat와 진행률을 갱신한다."""
    values: dict[str, Any] = {"heartbeat_at": utcnow()}
    if progress is not None:
        values["progress"] = _clamp_progress(progress)
    if current_message is not None:
        values["current_message"] = current_message
    await session.execute(
        update(CrawlRun).where(CrawlRun.id == run_id).values(**values)
    )
    await session.commit()


async def append_status_log(
    session: AsyncSession,
    run_id: int,
    message: str,
    *,
    progress: float | None = None,
    level: str = "info",
) -> None:
    """작업의 현재 문구와 상세 로그를 갱신한다."""
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return
    _append_log_to_run(run, message, progress=progress, level=level)
    await session.commit()


async def mark_done(
    session: AsyncSession,
    run_id: int,
    *,
    result: dict[str, Any] | None = None,
    final_message: str = "작업을 완료했습니다.",
    final_level: str = "success",
) -> None:
    """작업을 완료 처리한다(보류 등 비-성공 종료는 final_message/level로 명시)."""
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return
    run.state = RunState.DONE
    run.progress = 1.0
    run.finished_at = utcnow()
    run.result_json = json.dumps(result, ensure_ascii=False) if result else None
    _append_log_to_run(run, final_message, progress=1.0, level=final_level)
    # 재시작 run이 done으로 완료되면 원본의 attention을 resolved로 승격한다
    # (superseded여도 승격 — lineage 추적, T-162). 원본에 attention이 없던
    # 경우(성공 run의 단순 재실행)는 해소할 실패가 없으므로 그대로 둔다.
    # 직속 부모(restart_of_run_id)만 resolve한다 — 재시작 체인의 심층 원본은
    # 이미 superseded(배지 비표시)라 무해하며, leaf attempt 기준(B6) 최신 상태만
    # 관리하면 충분하다.
    if run.restart_of_run_id is not None:
        origin = await session.get(CrawlRun, run.restart_of_run_id)
        if origin is not None and origin.attention is not None:
            origin.attention = RunAttention.RESOLVED
    await session.commit()


async def mark_failed(session: AsyncSession, run_id: int, *, error: str) -> None:
    """작업을 실패 처리하고 `last_error`를 기록한다. attention은 open으로 전이한다."""
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return
    run.state = RunState.FAILED
    run.finished_at = utcnow()
    run.last_error = error
    run.attention = RunAttention.OPEN
    _append_log_to_run(run, f"작업이 실패했습니다: {error}", level="error")
    await session.commit()


async def create_restart_run(
    session: AsyncSession,
    origin_id: int,
    *,
    source: str,
) -> tuple[CrawlRun | None, bool]:
    """terminal 상태 원본 run을 같은 입력으로 재시작한다(T-162, G6).

    반환은 `(run, created)`. 원본이 없으면 `(None, False)`, 원본이 terminal이 아니면
    `ValueError`. **멱등**: 같은 원본에 대해 pending/running 재시작 run이 이미 있으면
    새로 만들지 않고 그 run을 `(run, False)`로 반환한다(중복 클릭 UX — 409 아님).
    원본 행을 `FOR UPDATE`로 잠가 동시 중복 클릭도 직렬화한다.
    원본의 open/acknowledged attention은 superseded로 전이한다(최신 attempt 이관).

    "원본당 active 재시작 1"은 앱 로직으로 보장한다(단일 실행자 + 이 함수가 유일한
    재시작 생성 경로 + 원본 행 FOR UPDATE 직렬화). DB partial-unique index는 두지
    않는다 — 위 보장으로 충분하고, 인덱스는 과잉이다.
    """
    # 멱등성 판정을 직렬화하기 위해 원본 행을 잠근다(identity map 무시하고 재조회).
    origin = await session.get(CrawlRun, origin_id, with_for_update=True)
    if origin is None:
        return None, False
    if origin.state not in TERMINAL_RUN_STATES:
        raise ValueError("terminal 상태(done/failed/cancelled)의 작업만 재시작할 수 있습니다")

    existing = (
        await session.execute(
            select(CrawlRun)
            .where(
                CrawlRun.restart_of_run_id == origin.id,
                CrawlRun.state.in_([RunState.PENDING, RunState.RUNNING]),
            )
            .order_by(CrawlRun.id.desc())
            .limit(1)
        )
    ).scalars().first()
    if existing is not None:
        # 잠금만 잡고 변경 없이 반환한다(조용한 멱등).
        await session.commit()
        return existing, False

    payload = json.loads(origin.payload_json) if origin.payload_json else None
    run = await create_run(
        session,
        job_type=origin.job_type,
        source=source,
        target_type=origin.target_type,
        target_id=origin.target_id,
        payload=payload,
        restart_of_run_id=origin.id,
        commit=False,
    )
    # T-163: lane 컬럼 도입 시 여기서 원본 lane을 복사한다(현재 lane 컬럼 없음 —
    # 기본값으로 두면 대화형 재시작이 배치 레인으로 떨어지는 문제, 로드맵 PR-04).
    if origin.attention in (RunAttention.OPEN, RunAttention.ACKNOWLEDGED):
        origin.attention = RunAttention.SUPERSEDED
    await session.commit()
    await session.refresh(run)
    return run, True


async def acknowledge_attention(session: AsyncSession, run_id: int) -> CrawlRun | None:
    """open attention을 acknowledged로 전이한다(T-162 acknowledge API).

    run이 없으면 None. 이미 acknowledged면 그대로 반환(멱등). attention이 없거나
    superseded/resolved면 확인할 대상이 없으므로 `ValueError`.
    """
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return None
    if run.attention == RunAttention.ACKNOWLEDGED:
        return run
    if run.attention != RunAttention.OPEN:
        raise ValueError("확인할 실패 알림(open attention)이 없습니다")
    run.attention = RunAttention.ACKNOWLEDGED
    await session.commit()
    return run


async def cancel_pending(session: AsyncSession, run_id: int) -> CrawlRun | None:
    """아직 claim되지 않은 `pending` 작업을 즉시 취소한다."""
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return None
    run.state = RunState.CANCELLED
    run.finished_at = utcnow()
    _append_log_to_run(
        run, "사용자 요청으로 대기 중 작업을 취소했습니다.", level="warning"
    )
    await session.commit()
    return run


async def request_cancel(session: AsyncSession, run_id: int) -> CrawlRun | None:
    """실행 중 작업에 협조적 중지 신호(`cancel_requested`)를 건다."""
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return None
    run.cancel_requested = True
    _append_log_to_run(
        run,
        "사용자 요청으로 작업 중지를 요청했습니다. 곧 중지됩니다.",
        level="warning",
    )
    await session.commit()
    return run


async def is_cancel_requested(session: AsyncSession, run_id: int) -> bool:
    """실행자가 폴링하는 협조적 중지 신호 여부."""
    result = await session.execute(
        select(CrawlRun.cancel_requested).where(CrawlRun.id == run_id)
    )
    return bool(result.scalar())


async def mark_cancelled(
    session: AsyncSession,
    run_id: int,
    *,
    message: str = "사용자 요청으로 작업을 중지했습니다.",
) -> None:
    """실행 중 협조적 취소된 작업을 `cancelled`로 마감한다(실패 아님)."""
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return
    run.state = RunState.CANCELLED
    run.finished_at = utcnow()
    _append_log_to_run(run, message, level="warning")
    await session.commit()


async def requeue_stale(
    session: AsyncSession,
    *,
    threshold_seconds: int = DEFAULT_STALE_THRESHOLD_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> int:
    """heartbeat가 만료된 `running` 작업을 재투입하거나 격리한다.

    재시도 여유가 있으면 `pending`으로 되돌리고 `retry_count`를 증가시킨다.
    최대 재시도를 초과하면 `failed`로 격리한다. 처리한 작업 수를 반환한다.
    """
    cutoff = utcnow() - timedelta(seconds=threshold_seconds)
    stmt = select(CrawlRun).where(
        CrawlRun.state == RunState.RUNNING,
        CrawlRun.heartbeat_at.is_not(None),
        CrawlRun.heartbeat_at < cutoff,
    )
    result = await session.execute(stmt)
    stale_runs = list(result.scalars().all())

    for run in stale_runs:
        if run.retry_count >= max_retries:
            run.state = RunState.FAILED
            run.finished_at = utcnow()
            run.last_error = "max retries exceeded (stale)"
            # mark_failed와 동일한 실패 경로 — attention도 open으로 전이한다(T-162).
            run.attention = RunAttention.OPEN
            _append_log_to_run(
                run,
                "heartbeat가 만료되어 최대 재시도 횟수를 초과했습니다.",
                level="error",
            )
        else:
            run.retry_count += 1
            run.state = RunState.PENDING
            run.started_at = None
            run.heartbeat_at = None
            _append_log_to_run(
                run,
                "heartbeat가 만료되어 작업을 재시도 대기열로 되돌렸습니다.",
                level="warning",
                touch_heartbeat=False,
            )

    if stale_runs:
        await session.commit()
    return len(stale_runs)
