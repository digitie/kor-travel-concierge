"""`crawl_runs` 작업 도메인 서비스.

REST/MCP는 작업 생성만 하고, scheduler 단일 실행자가 claim·heartbeat·완료를
처리한다(ADR-13). 모든 상태 전이를 한 곳에 모아 API/MCP/scheduler가 동일한
경로를 공유하게 한다.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CrawlRun, RunState, utcnow

# stale 판단 기본 임계값(초). heartbeat가 이 시간 이상 갱신되지 않으면 재투입 대상.
DEFAULT_STALE_THRESHOLD_SECONDS = 300
# 최대 재시도 횟수. 초과 시 failed로 격리한다.
DEFAULT_MAX_RETRIES = 3
# 작업별 상세 로그는 UI 표시용이므로 최근 항목만 보존한다.
MAX_STATUS_LOGS = 80


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


async def create_run(
    session: AsyncSession,
    *,
    job_type: str,
    source: str,
    target_type: str | None = None,
    target_id: str | None = None,
    payload: dict[str, Any] | None = None,
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
    session: AsyncSession, *, state: str | None = None, limit: int = 50
) -> list[CrawlRun]:
    """작업 목록을 최신순으로 조회한다."""
    stmt = select(CrawlRun).order_by(CrawlRun.id.desc()).limit(limit)
    if state is not None:
        stmt = stmt.where(CrawlRun.state == state)
    result = await session.execute(stmt)
    return list(result.scalars().all())


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
    session: AsyncSession, run_id: int, *, result: dict[str, Any] | None = None
) -> None:
    """작업을 완료 처리한다."""
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return
    run.state = RunState.DONE
    run.progress = 1.0
    run.finished_at = utcnow()
    run.result_json = json.dumps(result, ensure_ascii=False) if result else None
    _append_log_to_run(run, "작업을 완료했습니다.", progress=1.0, level="success")
    await session.commit()


async def mark_failed(session: AsyncSession, run_id: int, *, error: str) -> None:
    """작업을 실패 처리하고 `last_error`를 기록한다."""
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return
    run.state = RunState.FAILED
    run.finished_at = utcnow()
    run.last_error = error
    _append_log_to_run(run, f"작업이 실패했습니다: {error}", level="error")
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
