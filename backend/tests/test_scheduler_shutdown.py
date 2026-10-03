"""실제 종료 신호와 APScheduler 진행 중 작업 정리를 검증한다."""

import asyncio
import os
import signal
import sys

import pytest

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from scheduler.draining_executor import DrainingAsyncIOExecutor


@pytest.mark.asyncio
@pytest.mark.parametrize("finishes", [True, False])
async def test_drain_completes_short_job_and_cleans_cancelled_job(finishes):
    executor = DrainingAsyncIOExecutor()
    scheduler = AsyncIOScheduler(executors={"default": executor})
    started = asyncio.Event()
    cleaned = asyncio.Event()
    finished = False

    async def job():
        nonlocal finished
        started.set()
        try:
            await asyncio.sleep(0.01 if finishes else 30)
            finished = True
        finally:
            await asyncio.sleep(0.01)
            cleaned.set()

    scheduler.start()
    scheduler.add_job(job)
    await asyncio.wait_for(started.wait(), 5)
    scheduler.pause()
    await executor.drain(0.1 if finishes else 0)
    assert cleaned.is_set()
    assert finished is finishes
    assert all(task.done() for task in executor._pending_futures)
    scheduler.shutdown()
    await asyncio.sleep(0)


@pytest.mark.asyncio
@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT])
async def test_real_worker_exits_zero_after_signal_and_handler_cleanup(
    tmp_path, signum
):
    script = """
import asyncio, sys
from pathlib import Path
from scheduler import worker
root = Path(sys.argv[1])
async def tick(**kwargs):
    lane = kwargs["lane"]
    (root / (lane + ".started")).touch()
    try:
        await asyncio.sleep(3600)
    finally:
        await asyncio.sleep(0.01)
        (root / (lane + ".cleaned")).touch()
worker.run_once = tick
asyncio.run(worker.worker_loop(session_factory=object(), handlers={}))
"""
    env = dict(
        os.environ,
        SCHEDULER_SHUTDOWN_GRACE_SECONDS="0",
        SOURCE_SCAN_ENABLED="false",
        FEATURE_EXPORT_RECONCILE_ENABLED="false",
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        script,
        str(tmp_path),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        for _ in range(600):
            if len(list(tmp_path.glob("*.started"))) == 2:
                break
            await asyncio.sleep(0.05)
        assert len(list(tmp_path.glob("*.started"))) == 2
        process.send_signal(signum)
        stdout, stderr = await asyncio.wait_for(process.communicate(), 15)
        assert process.returncode == 0, (stdout + stderr).decode()
        assert len(list(tmp_path.glob("*.cleaned"))) == 2
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


@pytest.mark.asyncio
async def test_sigterm_during_database_startup_still_exits_cleanly(tmp_path):
    script = """
import asyncio, sys
from pathlib import Path
from scheduler import worker
root = Path(sys.argv[1])
async def init():
    (root / "started").touch()
    try:
        await asyncio.sleep(3600)
    finally:
        (root / "cleaned").touch()
worker.init_db = init
asyncio.run(worker.amain())
"""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        script,
        str(tmp_path),
        env=dict(os.environ, SCHEDULER_ENABLED="true"),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        for _ in range(600):
            if (tmp_path / "started").exists():
                break
            await asyncio.sleep(0.05)
        if not (tmp_path / "started").exists() and process.returncode is not None:
            stdout, stderr = await process.communicate()
            pytest.fail((stdout + stderr).decode())
        assert (tmp_path / "started").exists()
        process.send_signal(signal.SIGTERM)
        stdout, stderr = await asyncio.wait_for(process.communicate(), 15)
        assert process.returncode == 0, (stdout + stderr).decode()
        assert (tmp_path / "cleaned").exists()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
