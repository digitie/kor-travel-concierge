"""자막·전사를 격리 실행하고 취소 시 다운로드·FFmpeg까지 회수한다."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from ktc.core.config import get_settings

# 두 worker lane 및 harvest/poi_batch가 동일한 상한을 공유한다.
_whisper_slots = asyncio.Semaphore(1)
_caption_slots: asyncio.Semaphore | None = None


def _group_rss_mb(group_id: int) -> float:
    """Linux 프로세스 그룹의 RSS 합계. FFmpeg 등 자식도 같은 그룹에 속한다."""
    total = 0
    for entry in Path("/proc").glob("[0-9]*"):
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            if int(fields[2]) != group_id:
                continue
            for line in (entry / "status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    total += int(line.split()[1])
                    break
        except (OSError, ValueError, IndexError):
            # 자식이 조회 도중 종료되면 해당 항목만 건너뛴다.
            continue
    return total / 1024


async def _stop_group(process: asyncio.subprocess.Process) -> None:
    """정상 종료 신호를 먼저 보내고 응답하지 않는 자식만 회수한다."""
    # 종료된 group ID는 재사용될 수 있다. 남은 손자는 살아 있는 supervisor가 회수한다.
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(process.wait(), timeout=3)
    except asyncio.TimeoutError:
        pass
    # supervisor가 종료되면 자체 pidfd 회수/PDEATHSIG가 자식을 정리한다.
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    await process.wait()


async def run_provider_process(
    provider: str,
    video_id: str,
    *,
    force: bool = False,
    model_size: str | None = None,
):
    """provider 결과만 작은 JSON으로 전달하고 모델 메모리는 프로세스와 함께 반환한다."""
    from ktc.etl.transcript import (
        TranscriptAttempt,
        TranscriptResult,
        TranscriptSegment,
    )

    global _caption_slots
    settings = get_settings()
    whisper = provider == "whisper"
    if _caption_slots is None:
        _caption_slots = asyncio.Semaphore(
            min(3, max(1, settings.CRAWL_MAX_CONCURRENT_VIDEOS))
        )
    slots = _whisper_slots if whisper else _caption_slots
    memory_mb = settings.WHISPER_MAX_MEMORY_MB if whisper else 256
    timeout = settings.WHISPER_TIMEOUT_SECONDS if whisper else 120

    from ktc.etl.process_slots import reserve

    async with (
        slots,
        reserve(
            settings.KTC_TRANSCRIPT_SLOT_DIR,
            whisper=whisper,
            memory_mb=memory_mb,
            caption_limit=settings.CRAWL_MAX_CONCURRENT_VIDEOS,
        ) as slot_fds,
    ):
        with tempfile.TemporaryDirectory(prefix="ktc-transcript-") as work_dir:
            output = Path(work_dir) / "result.json"
            env = dict(os.environ, TMPDIR=work_dir)
            read_fd, write_fd = os.pipe2(os.O_CLOEXEC)
            try:
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "ktc.process_guard",
                    str(read_fd),
                    ",".join(map(str, slot_fds)),
                    str(memory_mb),
                    str(timeout),
                    sys.executable,
                    "-m",
                    "ktc.etl.transcript_process",
                    provider,
                    video_id,
                    str(output),
                    "1" if force else "0",
                    model_size or "",
                    env=env,
                    pass_fds=(read_fd, *slot_fds),
                    start_new_session=True,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            except BaseException:
                os.close(write_fd)
                raise
            finally:
                os.close(read_fd)
            started = asyncio.get_running_loop().time()
            try:
                while process.returncode is None:
                    if _group_rss_mb(process.pid) > memory_mb:
                        raise RuntimeError(
                            f"자막 처리 메모리 한도 초과({memory_mb}MiB)"
                        )
                    if asyncio.get_running_loop().time() - started > timeout:
                        raise TimeoutError(f"자막 처리 시간 한도 초과({timeout}초)")
                    try:
                        await asyncio.wait_for(process.wait(), timeout=0.25)
                    except asyncio.TimeoutError:
                        pass
                if process.returncode == 124:
                    raise TimeoutError(f"자막 처리 시간 한도 초과({timeout}초)")
                if process.returncode == 137:
                    raise RuntimeError(f"자막 처리 메모리 한도 초과({memory_mb}MiB)")
                if process.returncode != 0:
                    raise RuntimeError(
                        f"자막 처리 자식 종료(code={process.returncode})"
                    )
                if output.stat().st_size > 8 * 1024 * 1024:
                    raise RuntimeError("자막 결과 크기 한도 초과(8MiB)")
                data = json.loads(output.read_text())
                result = data.pop("result")
                if result is not None:
                    result["segments"] = [
                        TranscriptSegment(**segment) for segment in result["segments"]
                    ]
                    result = TranscriptResult(**result)
                return TranscriptAttempt(**data, result=result)
            finally:
                os.close(write_fd)
                await _stop_group(process)


def main() -> None:
    """신뢰한 내부 provider만 실행하는 자식 프로세스 진입점."""
    from ktc.process_guard import protect_provider

    protect_provider()
    from ktc.etl.transcript import (
        fetch_via_transcript_api,
        fetch_via_ytdlp,
        transcribe_via_whisper,
    )

    provider, video_id, output, force, model_size = sys.argv[1:]
    if provider == "whisper":
        attempt = transcribe_via_whisper(
            video_id, force=force == "1", model_size=model_size or None
        )
    else:
        attempt = {
            "youtube_transcript_api": fetch_via_transcript_api,
            "yt_dlp": fetch_via_ytdlp,
        }[provider](video_id)
    Path(output).write_text(json.dumps(asdict(attempt), ensure_ascii=False))


if __name__ == "__main__":
    main()
