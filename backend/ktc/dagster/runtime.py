"""도메인 소유권·metadata 인계. 센서는 payload와 heavy provider를 적재하지 않는다."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta

from kortravelcommon.dagster import PROJECT_TAG, RecoveryPolicy
from kortravelcommon.deadline import call_with_deadline
from sqlalchemy import func, select, update
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
MAX_DISPATCH_RUNS = 4


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
    runs = call_with_deadline(
        lambda: instance.get_runs(
            filters=RunsFilter(job_name=LANE_JOBS[row.lane], tags=tags),
            limit=MAX_DISPATCH_RUNS,
        ),
        timeout_seconds=5,
    )
    if any(not owned_native(run, LANE_JOBS[row.lane]) for run in runs):
        raise RuntimeError("Dagster 실행 identity가 일치하지 않습니다")
    return runs


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


async def exhaust_dispatch(factory, before, generation):
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
        await crawl_run_service.mark_failed(
            s, row.id, error="claim 이전 Dagster 발화 실패 한도 초과(4회)"
        )
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
        raise Failure(
            "메모리 high-water: 새 작업 claim을 보류했습니다", allow_retries=False
        )
    row = await claim(factory, row_id, lane, retry, attempt, generation, native_id)
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
