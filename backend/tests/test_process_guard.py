"""실제 Linux 부모/guardian hard kill·손자·OFD 예약을 검증한다. provider 과금 없음."""

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from ktc.etl.process_slots import reserve


async def test_atomic_memory_reservation_and_cancel(tmp_path):
    async with reserve(tmp_path / "slots", whisper=False, memory_mb=256):
        with pytest.raises(TimeoutError):
            async with reserve(
                tmp_path / "slots", whisper=True, memory_mb=1024, wait_seconds=0.1
            ):
                pytest.fail("캡션과 Whisper는 같이 예약할 수 없다")
        waiting = asyncio.create_task(
            reserve(tmp_path / "slots", whisper=True, memory_mb=1024).__aenter__()
        )
        await asyncio.sleep(0.06)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
    async with reserve(
        tmp_path / "slots", whisper=True, memory_mb=1024, wait_seconds=0.2
    ) as fds:
        assert len(fds) == 5
    with pytest.raises(ValueError, match="1024"):
        async with reserve(tmp_path / "slots", whisper=True, memory_mb=2048):
            pass


def live(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False


def wait_for(check, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.03)
    raise AssertionError("프로세스 수명 검증 시간 초과")


@pytest.mark.parametrize(
    "target,busy_c", [("worker", False), ("guardian", False), ("guardian", True)]
)
def test_hard_exit_reaps_descendants_and_preserves_other_group(
    tmp_path, target, busy_c
):
    provider = tmp_path / "provider.py"
    provider.write_text("""
import json, os, subprocess, sys, time
from pathlib import Path
from ktc.process_guard import protect_provider
protect_provider()
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(90)'])
Path(sys.argv[1]).write_text(json.dumps({'provider': os.getpid(), 'grandchild': child.pid}))
if len(sys.argv) > 2 and sys.argv[2] == 'busy':
    import hashlib
    hashlib.pbkdf2_hmac('sha256', b'test', b'salt', 100_000_000)
time.sleep(90)
""")
    ready = tmp_path / "ready.json"
    guardian_file = tmp_path / "guardian.json"
    worker_code = """
import asyncio, json, os, sys
from pathlib import Path
from ktc.etl.process_slots import reserve
async def run():
    async with reserve(sys.argv[1], whisper=True, memory_mb=1024) as fds:
        read, write = os.pipe2(os.O_CLOEXEC)
        child = await asyncio.create_subprocess_exec(sys.executable, '-m', 'ktc.process_guard',
            str(read), ','.join(map(str, fds)), '1024', '90', sys.executable, sys.argv[2], sys.argv[3], sys.argv[5],
            pass_fds=(read, *fds), start_new_session=True)
        os.close(read)
        Path(sys.argv[4]).write_text(json.dumps({'guardian': child.pid}))
        try:
            await child.wait()
        finally:
            os.close(write)
asyncio.run(run())
"""
    other = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(90)"], start_new_session=True
    )
    parent = subprocess.Popen(
        [
            sys.executable,
            "-c",
            worker_code,
            str(tmp_path / "slots"),
            str(provider),
            str(ready),
            str(guardian_file),
            "busy" if busy_c else "idle",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    children = None
    try:
        wait_for(lambda: ready.exists() and guardian_file.exists())
        children = {
            **json.loads(ready.read_text()),
            **json.loads(guardian_file.read_text()),
        }
        if busy_c:
            time.sleep(0.2)
        os.kill(
            parent.pid if target == "worker" else children["guardian"], signal.SIGKILL
        )
        wait_for(
            lambda: not live(children["provider"]) and not live(children["grandchild"])
        )

        async def check_slot():
            async with reserve(
                tmp_path / "slots", whisper=True, memory_mb=1024, wait_seconds=3
            ) as fds:
                assert len(fds) == 5

        asyncio.run(check_slot())
        assert other.poll() is None
    finally:
        if parent.poll() is None:
            parent.kill()
        parent.communicate(timeout=5)
        if children and live(children["guardian"]):
            os.kill(children["guardian"], signal.SIGTERM)
        other.terminate()
        other.wait(timeout=5)


async def test_lock_path_rejects_symlink(tmp_path):
    directory = tmp_path / "slots"
    directory.mkdir(mode=0o700)
    (directory / "admission.lock").symlink_to(tmp_path / "foreign")
    with pytest.raises(OSError):
        async with reserve(directory, whisper=True, memory_mb=1024):
            pass
    assert not (tmp_path / "foreign").exists()


async def test_lower_whisper_guard_cap_still_excludes_caption_bootstrap(tmp_path):
    async with reserve(tmp_path / "slots", whisper=True, memory_mb=128):
        with pytest.raises(TimeoutError):
            async with reserve(
                tmp_path / "slots", whisper=False, memory_mb=256, wait_seconds=0.1
            ):
                pytest.fail(
                    "Whisper guard 설정을 낮춰도 caption bootstrap과 겹치면 안 된다"
                )
    async with reserve(
        tmp_path / "slots", whisper=False, memory_mb=256, wait_seconds=0.2
    ):
        pass
