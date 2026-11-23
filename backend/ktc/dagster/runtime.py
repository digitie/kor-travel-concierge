"""도메인 소유권·metadata 인계. 센서는 payload와 heavy provider를 적재하지 않는다."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, timedelta

import httpx
from kortravelcommon.dagster import PROJECT_TAG, RecoveryPolicy
from kortravelcommon.deadline import call_with_deadline
from sqlalchemy import func, select, update
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from dagster import DagsterRunStatus, Failure, RunsFilter
from ktc.core.config import get_settings
from ktc.models import (
    CrawlRun,
    RunState,
    VideoAnalysisRunState,
    YoutubeVideoAnalysisRun,
    utcnow,
)
from ktc.services import crawl_run_service
from ktc.services.scheduler_control import admitted, read_control
from scheduler.db_retry import is_transient_database_error

PROJECT = "concierge"
REPOSITORY = "__repository__"
ROW_TAG = "concierge/crawl_run_id"
RETRY_TAG = "concierge/retry_count"
ATTEMPT_TAG = "concierge/attempt"
CONTROL_TAG = "concierge/control_generation"
DISPATCH_TAG = "concierge/dispatch_sensor"
PREDECESSOR_TAG = "concierge/dispatch_predecessor"
DISPATCH_NAME = "concierge_dispatch"
LANE_JOBS = {"interactive": "concierge_interactive", "batch": "concierge_batch"}
PAGE_SIZE = 10
# claim 전에 끝난 발화(launch 실패·claim 전 일시 오류)의 유한 재시도 예산.
# 실패 n회 뒤 다음 발화는 base·2^(n-1)(상한 cap)의 [1/2, 1] 구간 jitter만큼 늦춘다.
# 6회면 대기(60·120·240·480·900초)의 합이 약 15~30분이라 짧은 launch 장애는 넘기고,
# 긴 장애는 유한하게 종결한다.
MAX_DISPATCH_RUNS = 6
DISPATCH_BACKOFF_BASE_SECONDS = 60
DISPATCH_BACKOFF_MAX_SECONDS = 900
# 도메인 공용 분류(연결 단절·복구 대기·직렬화 충돌·lock timeout)에 더해, 재실행해도
# 부작용이 없는 claim 전·유지보수 경로에서는 statement timeout과 서버 자원 부족도 일시 오류다.
TRANSIENT_SQLSTATES = frozenset({"57014"})


def backoff_seconds(failures, *, key, base, cap):
    """failures회 실패 뒤 대기 시간. key가 같으면 같은 값이라 sensor tick마다 흔들리지 않는다."""
    delay = min(cap, base * 2 ** min(max(failures - 1, 0), 16))
    digest = hashlib.sha256(f"{key}:{failures}".encode()).digest()
    fraction = int.from_bytes(digest[:8], "big") / 2**64
    # equal jitter: 같은 시각에 실패한 행들이 한꺼번에 다시 발화하지 않게 흩는다.
    return delay / 2 + fraction * delay / 2


def dispatch_delay(row, failures):
    return backoff_seconds(
        failures,
        key=f"{row.id}:{row.retry}:{row.attempt}",
        base=DISPATCH_BACKOFF_BASE_SECONDS,
        cap=DISPATCH_BACKOFF_MAX_SECONDS,
    )


# 같은 입력이면 몇 번을 다시 해도 같은 결과인 DB 오류 class: 데이터(22)·제약(23)·
# 문법/schema(42)·미지원(0A). 분류하지 못한 오류는 결정적이라 단정하지 않고 backoff 예산에 맡긴다.
DETERMINISTIC_SQLSTATE_CLASSES = frozenset({"22", "23", "42", "0A"})


def is_deterministic_error(exc):
    current = exc
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if code:
            return str(code)[:2] in DETERMINISTIC_SQLSTATE_CLASSES
        current = getattr(current, "orig", None) or current.__cause__
    return False


def finished_at(record):
    """종료된 native 실행의 종료 시각(epoch 초). launch 실패도 종료 시각이 남는다."""
    if record.end_time is not None:
        return float(record.end_time)
    updated = record.update_timestamp
    if updated.tzinfo is None:
        # Dagster storage의 naive 시각은 UTC다. 실행 환경 TZ로 해석하지 않는다.
        updated = updated.replace(tzinfo=UTC)
    return updated.timestamp()


def is_transient_error(exc):
    """다시 시도하면 나아질 수 있는 오류만 True. 그 밖은 결정적 오류로 반복하지 않는다."""
    if isinstance(exc, (TimeoutError, httpx.TransportError, PoolTimeoutError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    current = exc
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        # 53xxx(자원 부족: 연결 수·메모리·디스크)·58xxx(시스템 I/O)는 서버 상태라 지나간다.
        if code and (code in TRANSIENT_SQLSTATES or str(code)[:2] in {"53", "58"}):
            return True
        current = getattr(current, "orig", None) or current.__cause__
    return is_transient_database_error(exc)


def location():
    return get_settings().KTC_DAGSTER_LOCATION


def job_tags(name):
    return RecoveryPolicy(
        max_runtime_seconds=get_settings().KTC_DAGSTER_MAX_RUNTIME_SECONDS
    ).tags(project=PROJECT, job_name=name)


@asynccontextmanager
async def database():
    # execution advisory connection·handler·watcher를 수용한다. 루프 간 pool 재사용 금지.
    engine = create_async_engine(
        get_settings().DATABASE_URL,
        pool_size=4,
        max_overflow=0,
        pool_pre_ping=True,
        pool_timeout=5,
        connect_args={
            "timeout": 5,
            "command_timeout": 30,
            "server_settings": {"statement_timeout": "30000", "lock_timeout": "2000"},
        },
    )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@dataclass(frozen=True)
class Lease:
    id: int
    lane: str
    retry: int
    attempt: int
    owner: str | None
    state: str
    heartbeat: object
    started: object
    updated: object
    cancel_requested: bool = False


def lease(row):
    return Lease(
        row.id,
        row.lane,
        row.retry_count,
        row.orchestrator_attempt,
        row.orchestrator_run_id,
        row.state,
        row.heartbeat_at,
        row.started_at,
        row.orchestrator_claimed_at or row.created_at,
        row.cancel_requested,
    )


async def page(factory, *, after=0, lane=None, owned=False):
    async with factory() as s:
        stmt = select(CrawlRun).where(CrawlRun.id > after)
        if owned:
            stmt = stmt.where(
                CrawlRun.orchestrator_run_id.is_not(None),
                CrawlRun.state.in_([RunState.PENDING, RunState.RUNNING]),
            )
        else:
            stmt = stmt.where(
                CrawlRun.state == RunState.PENDING,
                CrawlRun.orchestrator_run_id.is_(None),
                CrawlRun.lane == lane,
            )
        # 큰 payload는 sensor에 필요 없다. row 필드만 읽는다.
        from sqlalchemy.orm import load_only

        stmt = stmt.options(
            load_only(
                CrawlRun.id,
                CrawlRun.lane,
                CrawlRun.retry_count,
                CrawlRun.orchestrator_attempt,
                CrawlRun.orchestrator_run_id,
                CrawlRun.state,
                CrawlRun.heartbeat_at,
                CrawlRun.started_at,
                CrawlRun.orchestrator_claimed_at,
                CrawlRun.created_at,
                CrawlRun.cancel_requested,
            )
        )
        rows = list(
            (await s.scalars(stmt.order_by(CrawlRun.id).limit(PAGE_SIZE))).all()
        )
        return [lease(row) for row in rows]


def owned_native(run, job_name):
    if run.job_name != job_name or run.tags.get(PROJECT_TAG) != PROJECT:
        return False
    origin = run.remote_job_origin
    if origin:
        return (
            origin.repository_origin.code_location_origin.location_name == location()
            and origin.repository_origin.repository_name == REPOSITORY
            and origin.job_name == job_name
        )
    return run.tags.get("dagster/code_location") == location()


def metadata(instance, owner):
    return call_with_deadline(lambda: instance.get_run_by_id(owner), timeout_seconds=5)


def history(instance, row, generation):
    tags = {
        PROJECT_TAG: PROJECT,
        "dagster/code_location": location(),
        ROW_TAG: str(row.id),
        RETRY_TAG: str(row.retry),
        ATTEMPT_TAG: str(row.attempt),
        DISPATCH_TAG: DISPATCH_NAME,
        CONTROL_TAG: str(generation),
    }
    # 최신순 run record. 종료 시각이 있어야 claim 전 실패 뒤 backoff를 계산한다.
    records = call_with_deadline(
        lambda: instance.get_run_records(
            filters=RunsFilter(job_name=LANE_JOBS[row.lane], tags=tags),
            limit=MAX_DISPATCH_RUNS,
        ),
        timeout_seconds=5,
    )
    if any(
        not owned_native(record.dagster_run, LANE_JOBS[row.lane]) for record in records
    ):
        raise RuntimeError("Dagster 실행 identity가 일치하지 않습니다")
    return records


def run_key(row, predecessor):
    return f"concierge:{row.id}:{row.retry}:{row.attempt}:{predecessor}"


def dispatch_tags(row, generation, predecessor):
    return {
        **job_tags(LANE_JOBS[row.lane]),
        "dagster/code_location": location(),
        ROW_TAG: str(row.id),
        RETRY_TAG: str(row.retry),
        ATTEMPT_TAG: str(row.attempt),
        CONTROL_TAG: str(generation),
        DISPATCH_TAG: DISPATCH_NAME,
        PREDECESSOR_TAG: predecessor,
    }


async def claim(factory, row_id, lane, retry, attempt, generation, native_id):
    async with factory() as s:
        if not await admitted(s, "dagster", generation):
            return None
        row = await s.scalar(
            select(CrawlRun)
            .where(
                CrawlRun.id == row_id,
                CrawlRun.lane == lane,
                CrawlRun.state == RunState.PENDING,
                CrawlRun.retry_count == retry,
                CrawlRun.orchestrator_attempt == attempt,
                CrawlRun.orchestrator_run_id.is_(None),
                CrawlRun.cancel_requested.is_(False),
            )
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return None
        row.orchestrator_run_id = native_id
        row.orchestrator_claimed_at = utcnow()
        row.state = RunState.RUNNING
        row.started_at = row.heartbeat_at = utcnow()
        await crawl_run_service.append_status_log(
            s, row.id, "Dagster 실행자가 작업을 시작했습니다.", progress=0.05
        )
        await s.refresh(row)
        return row


async def reset_analysis(s, row, *, cancelled=False):
    await s.execute(
        update(YoutubeVideoAnalysisRun)
        .where(
            YoutubeVideoAnalysisRun.owner_crawl_run_id == row.id,
            YoutubeVideoAnalysisRun.owner_retry_count == row.retry_count,
            YoutubeVideoAnalysisRun.state == VideoAnalysisRunState.RUNNING,
        )
        .values(
            state=VideoAnalysisRunState.FAILED
            if cancelled
            else VideoAnalysisRunState.PENDING,
            started_at=None,
            finished_at=None,
            owner_crawl_run_id=None,
            owner_retry_count=None,
            claim_token=None,
            last_error="dagster_cancelled" if cancelled else "dagster_worker_recovery",
        )
    )


async def reconcile_one(factory, before, native):
    settings = get_settings()
    now = utcnow()
    if native is not None:
        if not owned_native(native, LANE_JOBS[before.lane]):
            raise RuntimeError("다른 코드 위치의 실행은 회수하지 않습니다")
        if not native.is_finished:
            return False
    else:
        anchor = before.started or before.updated
        if anchor is None or now - anchor < timedelta(
            seconds=settings.KTC_DAGSTER_MISSING_GRACE_SECONDS
        ):
            return False
    async with factory() as s:
        await s.execute(select(func.pg_advisory_xact_lock_shared(1960030)))
        row = await s.scalar(
            select(CrawlRun)
            .where(
                CrawlRun.id == before.id,
                CrawlRun.orchestrator_run_id == before.owner,
                CrawlRun.orchestrator_attempt == before.attempt,
                CrawlRun.retry_count == before.retry,
                CrawlRun.state == before.state,
                CrawlRun.heartbeat_at == before.heartbeat,
            )
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return False
        # 예전 handler의 물리 execution lease가 남으면 외부 부작용을 반복하지 않는다.
        acquired = await s.scalar(
            select(
                func.pg_try_advisory_xact_lock(
                    func.hashtextextended(
                        crawl_run_service.crawl_run_execution_lock_name(row.id), 0
                    )
                )
            )
        )
        if not acquired:
            return False
        cancelled = row.cancel_requested or (
            native is not None and native.status == DagsterRunStatus.CANCELED
        )
        if not cancelled and row.state == RunState.RUNNING:
            heartbeat = row.heartbeat_at or row.started_at
            if heartbeat and now - heartbeat < timedelta(
                seconds=settings.SCHEDULER_STALE_THRESHOLD_SECONDS
            ):
                return False
        await reset_analysis(s, row, cancelled=cancelled)
        if cancelled:
            await crawl_run_service.mark_cancelled(s, row.id)
        elif (
            native is not None
            and native.status == DagsterRunStatus.SUCCESS
            and row.state == RunState.RUNNING
        ):
            await crawl_run_service.mark_failed(
                s,
                row.id,
                error="Dagster 성공 뒤 도메인 결과가 없어 운영 확인이 필요합니다",
            )
        elif (
            row.state == RunState.RUNNING
            and row.retry_count >= settings.SCHEDULER_MAX_RETRIES
        ):
            await crawl_run_service.mark_failed(
                s, row.id, error="Dagster 중단 복구 재시도 한도 초과"
            )
        else:
            if row.state == RunState.RUNNING:
                row.retry_count += 1
            row.orchestrator_attempt += 1
            row.orchestrator_run_id = None
            await crawl_run_service.requeue_interrupted(s, row)
        return True


async def exhaust_dispatch(factory, before, generation, last=None):
    # 원인은 Dagster run에 남는다. 운영자가 바로 찾도록 마지막 run을 함께 적는다.
    detail = f", 마지막 run {last.run_id[:8]} {last.status.value}" if last else ""
    return await fail_unclaimed(
        factory,
        before.id,
        before.retry,
        before.attempt,
        generation,
        f"claim 이전 Dagster 발화 실패 한도 초과({MAX_DISPATCH_RUNS}회{detail})",
    )


async def fail_unclaimed(factory, row_id, retry, attempt, generation, error):
    """아직 claim되지 않은 같은 attempt만 실패로 종결한다(늦은 발화는 건드리지 않는다)."""
    async with factory() as s:
        if not await admitted(s, "dagster", generation):
            return False
        row = await s.scalar(
            select(CrawlRun)
            .where(
                CrawlRun.id == row_id,
                CrawlRun.state == RunState.PENDING,
                CrawlRun.retry_count == retry,
                CrawlRun.orchestrator_attempt == attempt,
                CrawlRun.orchestrator_run_id.is_(None),
            )
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return False
        if not await s.scalar(
            select(
                func.pg_try_advisory_xact_lock(
                    func.hashtextextended(
                        crawl_run_service.crawl_run_execution_lock_name(row.id), 0
                    )
                )
            )
        ):
            return False
        await crawl_run_service.mark_failed(s, row.id, error=error)
        return True


def native_runtime_expired(instance, native):
    # monitor는 CANCELING 뒤 FAILURE를 기록하므로 종료 순간 status만으로
    # 명시적 취소와 timeout을 구분할 수 없다. 실제 시작 시각·tag로 판별한다.
    record = call_with_deadline(
        lambda: instance.get_run_record_by_id(native.run_id), timeout_seconds=5
    )
    if record is None or record.start_time is None:
        raise RuntimeError("native 시작 시각을 확인하지 못했습니다")
    cap = int(native.tags["dagster/max_runtime"])
    if not 0 < cap <= 86400:
        raise ValueError("native 시간 상한이 올바르지 않습니다")
    return utcnow().timestamp() - record.start_time >= cap


async def finish_interrupt(factory, row, native, *, timed_out=False):
    # native 조회는 호출자가 transaction 밖에서 완료한다. UNKNOWN은 연결을 보존한다.
    if native is None or not owned_native(native, LANE_JOBS[row.lane]):
        return
    async with factory() as s:
        current = await s.scalar(
            select(CrawlRun)
            .where(
                CrawlRun.id == row.id,
                CrawlRun.orchestrator_run_id == row.orchestrator_run_id,
                CrawlRun.orchestrator_attempt == row.orchestrator_attempt,
            )
            .with_for_update()
        )
        if current is None or current.state not in (RunState.PENDING, RunState.RUNNING):
            return
        if timed_out:
            # 정리 완료 뒤에도 lease를 유지해 terminal/stale/물리 실행 lock을
            # 확인하는 공용 recovery가 유한 재시도 예산을 소모하게 한다.
            return
        cancel = current.cancel_requested or native.status in (
            DagsterRunStatus.CANCELING,
            DagsterRunStatus.CANCELED,
        )
        if cancel:
            await reset_analysis(s, current, cancelled=True)
            await crawl_run_service.mark_cancelled(s, current.id)
        elif (
            native.status == DagsterRunStatus.STARTED
            and current.state in (RunState.PENDING, RunState.RUNNING)
        ):
            await reset_analysis(s, current, cancelled=False)
            current.orchestrator_run_id = None
            current.orchestrator_attempt += 1
            await crawl_run_service.requeue_interrupted(s, current)


async def execute_claimed(
    factory,
    *,
    row_id,
    lane,
    retry,
    attempt,
    generation,
    native_id,
    instance,
    handlers=None,
):
    from scheduler.worker import _worker_memory_mb, execute_run

    if _worker_memory_mb() >= get_settings().SCHEDULER_MEMORY_HIGH_WATER_MB:
        # 일시 상태다. 행은 pending으로 남고 발화 sensor가 backoff 뒤 다시 발화한다.
        raise Failure(
            "메모리 high-water: 새 작업 claim을 보류했습니다", allow_retries=False
        )
    try:
        row = await claim(factory, row_id, lane, retry, attempt, generation, native_id)
    except Exception as exc:
        kind = type(exc).__name__
        if is_transient_error(exc) or not is_deterministic_error(exc):
            raise Failure(
                f"claim 전 오류({kind}): 발화 sensor가 backoff 뒤 다시 시도합니다",
                allow_retries=False,
            ) from exc
        # 데이터·제약·schema 같은 결정적 오류는 남은 발화 예산을 쓰며 반복해도 같은 결과다. 즉시 종결한다.
        # 종결 저장마저 실패하면 행은 pending으로 남고 sensor의 유한 예산이 처리한다.
        try:
            await fail_unclaimed(
                factory,
                row_id,
                retry,
                attempt,
                generation,
                f"claim 전 결정적 오류({kind}): 재시도하지 않습니다",
            )
        except Exception as mark_error:  # noqa: BLE001 - 원래 오류를 우선 전달한다
            logging.getLogger(__name__).warning(
                "claim 전 결정적 오류 종결 실패(row=%s, %s)",
                row_id,
                type(mark_error).__name__,
            )
        raise Failure(
            f"claim 전 결정적 오류({kind}): 재시도하지 않습니다", allow_retries=False
        ) from exc
    if row is None:
        return {"state": "skipped", "crawl_run_id": row_id}
    try:
        await execute_run(factory, row, handlers=handlers)
    except asyncio.CancelledError:
        try:
            native = metadata(instance, native_id)
            if native is not None:
                timed_out = native_runtime_expired(instance, native)
                await finish_interrupt(factory, row, native, timed_out=timed_out)
        except Exception as exc:  # noqa: BLE001 - 종료 중 UNKNOWN은 다음 회수가 소유한다
            logging.getLogger(__name__).warning(
                "종료 인계 확인 실패(%s): lease 보존", type(exc).__name__
            )
        raise
    async with factory() as s:
        current = await s.scalar(
            select(CrawlRun).where(CrawlRun.id == row.id).with_for_update()
        )
        if current is None or current.orchestrator_run_id != native_id:
            raise Failure(
                "작업 소유권이 변경되어 현재 결과를 종결하지 않습니다",
                allow_retries=False,
            )
        if current.state == RunState.DONE:
            return {"state": "done", "crawl_run_id": row.id}
        if current.state == RunState.PENDING:
            current.orchestrator_run_id = None
            current.orchestrator_attempt += 1
            await s.commit()
            raise Failure(
                "DB 재투입: 다음 도메인 attempt에서 재개합니다", allow_retries=False
            )
        raise Failure(
            f"도메인 작업 {current.state}: 작업 화면에서 상세·재시작을 확인하세요",
            allow_retries=False,
        )


async def control_snapshot():
    async with database() as factory, factory() as s:
        return await read_control(s)


async def cancel_pending(factory, before, generation, *, native_cancel=False):
    async with factory() as s:
        if not await admitted(s, "dagster", generation):
            return False
        row = await s.scalar(
            select(CrawlRun)
            .where(
                CrawlRun.id == before.id,
                CrawlRun.state == RunState.PENDING,
                CrawlRun.retry_count == before.retry,
                CrawlRun.orchestrator_attempt == before.attempt,
                CrawlRun.orchestrator_run_id.is_(None),
                True if native_cancel else CrawlRun.cancel_requested.is_(True),
            )
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return False
        await crawl_run_service.mark_cancelled(s, row.id)
        return True
