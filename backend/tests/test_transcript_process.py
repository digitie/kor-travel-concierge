"""자막 프로세스의 동시성·메모리 한도·취소 회수를 실제 자식으로 검증한다."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from ktc.etl import transcript, transcript_process


@pytest.fixture
def settings(monkeypatch, tmp_path):
    value = SimpleNamespace(
        CRAWL_MAX_CONCURRENT_VIDEOS=3,
        KTC_TRANSCRIPT_SLOT_DIR=str(tmp_path / "slots"),
        WHISPER_MAX_MEMORY_MB=1024,
        WHISPER_TIMEOUT_SECONDS=10,
    )
    monkeypatch.setattr(transcript_process, "get_settings", lambda: value)
    monkeypatch.setattr(transcript_process, "_whisper_slots", asyncio.Semaphore(1))
    monkeypatch.setattr(transcript_process, "_caption_slots", None)
    return value


@pytest.mark.asyncio
async def test_two_lanes_share_one_whisper_process_and_decode_result(
    monkeypatch, settings
):
    original = asyncio.create_subprocess_exec
    active = maximum = 0
    attempt = {
        "provider": "whisper",
        "outcome": "success",
        "result": {
            "video_id": "video",
            "source": "whisper",
            "language": "ko",
            "segments": [{"start": 1.0, "text": "서울"}],
        },
    }

    async def spawn(*args, **kwargs):
        nonlocal active, maximum
        # 기존 프로세스가 종료되기 전에 두 번째 spawn이 호출되면 실패한다.
        active += 1
        maximum = max(maximum, active)
        script = (
            "import time,pathlib; time.sleep(.1); pathlib.Path("
            + repr(args[12])
            + ").write_text("
            + repr(json.dumps(attempt))
            + ")"
        )
        process = await original(*args[:7], sys.executable, "-c", script, **kwargs)

        async def count():
            nonlocal active
            await process.wait()
            active -= 1

        asyncio.create_task(count())
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    results = await asyncio.gather(
        transcript_process.run_provider_process("whisper", "video"),
        transcript_process.run_provider_process("whisper", "video"),
    )
    assert maximum == 1
    assert all(result.result.text == "서울" for result in results)


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["memory", "timeout", "cancel"])
async def test_limit_or_cancel_reaps_process_group_and_temp_files(
    tmp_path, monkeypatch, settings, reason
):
    original = asyncio.create_subprocess_exec
    ready = tmp_path / "ready"
    processes = []
    directories = []
    if reason == "memory":
        settings.WHISPER_MAX_MEMORY_MB = 128
    if reason == "timeout":
        settings.WHISPER_TIMEOUT_SECONDS = 0.3

    async def spawn(*args, **kwargs):
        directories.append(Path(kwargs["env"]["TMPDIR"]))
        script = """
import subprocess, sys, pathlib, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
pathlib.Path(sys.argv[1]).write_text(str(child.pid))
payload = bytearray(160 * 1024 * 1024)
time.sleep(60)
"""
        process = await original(
            *args[:7], sys.executable, "-c", script, str(ready), **kwargs
        )
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(
        transcript_process.run_provider_process("whisper", "video")
    )
    for _ in range(100):
        if ready.exists():
            break
        await asyncio.sleep(0.01)
    assert ready.exists()
    if reason == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises((RuntimeError, TimeoutError), match="한도 초과"):
            await task
    assert processes[0].returncode is not None
    child_status = Path("/proc") / ready.read_text() / "status"
    if child_status.exists():
        assert "State:\tZ" in child_status.read_text()
    assert all(not directory.exists() for directory in directories)


@pytest.mark.asyncio
async def test_async_chain_preserves_provider_order_and_failure_fallback(monkeypatch):
    calls = []

    async def attempt(provider, video_id, **kwargs):
        calls.append(provider)
        return transcript.TranscriptAttempt(provider=provider, outcome="blocked")

    monkeypatch.setattr(transcript_process, "run_provider_process", attempt)
    monkeypatch.setenv("TRANSCRIPT_WHISPER_ENABLED", "true")
    monkeypatch.setattr(
        transcript,
        "_resolve_provider_chain",
        lambda: (
            transcript.transcribe_via_whisper,
            transcript.fetch_via_ytdlp,
            transcript.fetch_via_transcript_api,
        ),
    )
    outcome = await transcript.fetch_transcript_async("video")
    assert calls == ["whisper", "yt_dlp", "youtube_transcript_api"]
    assert [a.sequence for a in outcome.attempts] == [1, 2, 3]
    assert not outcome.succeeded
