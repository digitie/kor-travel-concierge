"""DB 재시도에서 일시 오류, 영구 오류, 종료 요청을 구분한다."""

import asyncio
import errno

import pytest
from sqlalchemy.exc import OperationalError

from scheduler.db_retry import is_transient_database_error, retry_database, retry_delay


def error(code=None):
    original = RuntimeError("접속 정보가 포함된 원문")
    if code:
        original.sqlstate = code
    return OperationalError(None, None, original)


@pytest.mark.parametrize("code", ["08006", "57P03", "40001", "40P01", None])
def test_transient_database_errors(code):
    assert is_transient_database_error(error(code))


@pytest.mark.parametrize("code", ["28P01", "3D000", "42501", "23505", "42601"])
def test_permanent_database_errors(code):
    assert not is_transient_database_error(error(code))


def test_network_errors_but_not_unrelated_errors():
    assert is_transient_database_error(ConnectionRefusedError())
    assert is_transient_database_error(OSError(errno.ENETUNREACH, "network"))
    assert not is_transient_database_error(OSError(errno.ENOSPC, "disk"))
    assert not is_transient_database_error(
        TimeoutError()
    )  # 일반 handler 시간 초과는 제외
    assert not is_transient_database_error(ValueError())
    assert not is_transient_database_error(RuntimeError())


def test_backoff_is_bounded():
    assert [retry_delay(n) for n in range(1, 7)] == [2, 4, 8, 16, 30, 30]
    assert retry_delay(10000) == 30


async def test_retry_recovers_without_logging_sensitive_error(monkeypatch, caplog):
    monkeypatch.setattr("scheduler.db_retry.retry_delay", lambda attempt: 0)
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise error("57P03")
        return 42

    assert await retry_database(operation, context="검증", max_retries=3) == 42
    assert calls == 3
    assert "접속 정보가 포함된 원문" not in caplog.text


async def test_exhaustion_and_permanent_error_do_not_loop(monkeypatch):
    monkeypatch.setattr("scheduler.db_retry.retry_delay", lambda attempt: 0)
    for code, expected in [("08006", 4), ("28P01", 1)]:
        calls = 0

        async def operation():
            nonlocal calls
            calls += 1
            raise error(code)

        with pytest.raises(OperationalError):
            await retry_database(operation, context="검증", max_retries=3)
        assert calls == expected


async def test_stop_interrupts_backoff(monkeypatch):
    monkeypatch.setattr("scheduler.db_retry.retry_delay", lambda attempt: 30)
    stop = asyncio.Event()
    attempted = asyncio.Event()

    async def operation():
        attempted.set()
        raise error()

    task = asyncio.create_task(retry_database(operation, context="검증", stop=stop))
    await asyncio.wait_for(attempted.wait(), 1)
    stop.set()
    assert await asyncio.wait_for(task, 1) is None


async def test_cancel_interrupts_backoff(monkeypatch):
    monkeypatch.setattr("scheduler.db_retry.retry_delay", lambda attempt: 30)
    attempted = asyncio.Event()

    async def operation():
        attempted.set()
        raise error()

    task = asyncio.create_task(retry_database(operation, context="검증"))
    await asyncio.wait_for(attempted.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_main_recovers_database_startup(monkeypatch):
    from scheduler import worker

    monkeypatch.setattr("scheduler.db_retry.retry_delay", lambda attempt: 0)
    monkeypatch.setattr(worker.get_settings(), "SCHEDULER_ENABLED", True)
    calls = 0
    entered = False

    async def init_db():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise error("57P03")

    async def worker_loop(*, stop_event):
        nonlocal entered
        entered = True

    monkeypatch.setattr(worker, "init_db", init_db)
    monkeypatch.setattr(worker, "worker_loop", worker_loop)
    await worker.amain()
    assert calls == 3
    assert entered


async def test_partial_registration_does_not_dispatch_until_recovered(monkeypatch):
    from scheduler import worker

    monkeypatch.setattr("scheduler.db_retry.retry_delay", lambda attempt: 0.02)
    monkeypatch.setattr(worker.get_settings(), "SOURCE_SCAN_ENABLED", False)
    monkeypatch.setattr(
        worker.get_settings(), "FEATURE_EXPORT_RECONCILE_ENABLED", False
    )
    stop = asyncio.Event()
    registrations = 0
    executions = 0
    original = worker.register_worker_jobs

    def register(scheduler, **kwargs):
        nonlocal registrations
        registrations += 1
        original(scheduler, **kwargs)
        if registrations == 1:
            raise error()

    async def tick(**kwargs):
        nonlocal executions
        assert registrations == 2
        executions += 1
        if executions == 2:
            stop.set()

    monkeypatch.setattr(worker, "register_worker_jobs", register)
    monkeypatch.setattr(worker, "run_once", tick)
    await asyncio.wait_for(
        worker.worker_loop(session_factory=object(), handlers={}, stop_event=stop), 5
    )
    assert registrations == 2
    assert executions == 2


def test_legacy_job_removal_database_error_is_not_ignored():
    from scheduler import worker

    class Broken:
        def remove_job(self, job_id):
            raise error()

    with pytest.raises(OperationalError):
        worker.register_worker_jobs(
            Broken(),
            session_factory=object(),
            handlers={},
            use_persistent_jobstore=False,
            settings=worker.get_settings(),
        )


async def test_database_operation_connection_timeout_is_retried(monkeypatch):
    monkeypatch.setattr("scheduler.db_retry.retry_delay", lambda attempt: 0)
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError()
        return "connected"

    assert (
        await retry_database(operation, context="DB 연결", max_retries=3) == "connected"
    )
    assert calls == 2
