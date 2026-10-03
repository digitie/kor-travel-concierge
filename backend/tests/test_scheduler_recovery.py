"""DB 장애 뒤 APScheduler 타이머 자동 복구 회귀 테스트."""

import asyncio
from datetime import datetime, timezone

import pytest
from apscheduler.jobstores.memory import MemoryJobStore
from sqlalchemy.exc import OperationalError

from scheduler.recovering_scheduler import RecoveringAsyncIOScheduler


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["update_job", "remove_job", "get_next_run_time"])
async def test_jobstore_write_failure_keeps_timer_running(operation, monkeypatch):
    store = MemoryJobStore()
    scheduler = RecoveringAsyncIOScheduler(
        jobstores={"default": store},
        jobstore_retry_interval=0.02,
        timezone=timezone.utc,
    )
    original = getattr(store, operation)
    failures = 0
    executions = 0
    recovered = asyncio.Event()

    def fail_then_recover(*args, **kwargs):
        nonlocal failures
        if failures < 2:
            failures += 1
            raise OperationalError(None, None, RuntimeError("DB connection lost"))
        return original(*args, **kwargs)

    async def tick():
        nonlocal executions
        executions += 1
        if failures == 2 and executions >= 3:
            recovered.set()

    scheduler.start(paused=True)
    initial_run_time = datetime.now(timezone.utc)
    scheduler.add_job(
        tick,
        "interval",
        seconds=0.03,
        next_run_time=initial_run_time,
        id="worker",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=None,
    )
    if operation == "remove_job":
        scheduler.add_job(
            tick, "date", run_date=datetime.now(timezone.utc), id="one-shot"
        )
    monkeypatch.setattr(store, operation, fail_then_recover)
    scheduler.resume()
    try:
        await asyncio.wait_for(recovered.wait(), timeout=5)
        assert failures == 2
        assert scheduler.get_job("worker").next_run_time > initial_run_time
    finally:
        scheduler.shutdown(wait=False)
        await asyncio.sleep(0)


def test_unexpected_scheduler_error_is_not_swallowed(monkeypatch):
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    def broken(self):
        raise ValueError("invalid job")

    monkeypatch.setattr(AsyncIOScheduler, "_process_jobs", broken)
    scheduler = RecoveringAsyncIOScheduler()
    with pytest.raises(ValueError, match="invalid job"):
        scheduler._process_jobs()


@pytest.mark.asyncio
async def test_delayed_worker_and_maintenance_ticks_still_execute(monkeypatch):
    from types import SimpleNamespace

    from scheduler import worker

    scheduler = RecoveringAsyncIOScheduler(timezone=timezone.utc)
    completed = asyncio.Event()
    executions = 0

    async def tick(**kwargs):
        nonlocal executions
        executions += 1
        if executions == 4:
            completed.set()

    monkeypatch.setattr(worker, "run_once", tick)
    monkeypatch.setattr(worker, "enqueue_source_scan_once", tick)
    monkeypatch.setattr(worker, "reconcile_feature_exports_once", tick)
    scheduler.start(paused=True)
    worker.register_worker_jobs(
        scheduler,
        session_factory=object(),
        handlers={},
        use_persistent_jobstore=False,
        settings=SimpleNamespace(
            SCHEDULER_POLL_INTERVAL_SECONDS=5,
            SOURCE_SCAN_ENABLED=True,
            SOURCE_SCAN_INTERVAL_SECONDS=300,
            FEATURE_EXPORT_RECONCILE_ENABLED=True,
            FEATURE_EXPORT_RECONCILE_INTERVAL_SECONDS=3600,
        ),
    )
    from datetime import timedelta

    for job in scheduler.get_jobs():
        scheduler.modify_job(
            job.id, next_run_time=datetime.now(timezone.utc) - timedelta(seconds=2)
        )
    scheduler.resume()
    try:
        await asyncio.wait_for(completed.wait(), timeout=5)
        assert executions == 4
    finally:
        scheduler.shutdown(wait=False)
        await asyncio.sleep(0)
