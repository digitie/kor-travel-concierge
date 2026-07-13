"""T-169 수동 whisper 강제 재전사 경로 테스트.

auto 전사 게이트(`TRANSCRIPT_WHISPER_ENABLED`)는 건드리지 않고, 운영자의 명시적 force
경로만 검증한다: (a) duration 초과 → 400, (b) force 시 batch 레인 enqueue,
(c) force가 env 게이트와 독립(env off여도 우회), (d) force 아닐 때 기본 동작 불변,
(e) model_size 인자가 whisper까지 전달.

실제 faster-whisper/yt-dlp STT는 돌리지 않고 sys.modules 주입으로 모사한다.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from ktc.core.database import get_repeatable_read_session, get_session
from ktc.etl import postprocess_service, transcript
from ktc.models import YoutubeVideo
from main import app


# --- whisper/yt-dlp 모사 -----------------------------------------------------


class _FakeSeg:
    def __init__(self, start: float, text: str) -> None:
        self.start = start
        self.text = text


class _FakeInfo:
    language = "ko"


def _install_fake_whisper(monkeypatch, captured: dict) -> None:
    """yt_dlp(오디오 다운로드) + faster_whisper(WhisperModel)를 sys.modules로 주입한다."""

    class _FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def download(self, urls):
            out_dir = Path(self.opts["outtmpl"]).parent
            (out_dir / "audio.mp3").write_bytes(b"fake-audio")

    ydl_mod = types.ModuleType("yt_dlp")
    ydl_mod.YoutubeDL = _FakeYDL
    monkeypatch.setitem(sys.modules, "yt_dlp", ydl_mod)

    class _FakeWhisperModel:
        def __init__(self, model_size, device=None, compute_type=None):
            captured["model_size"] = model_size

        def transcribe(self, path):
            return ([_FakeSeg(0.0, "안녕하세요"), _FakeSeg(5.0, "여기는 제주")], _FakeInfo())

    fw_mod = types.ModuleType("faster_whisper")
    fw_mod.WhisperModel = _FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fw_mod)


# --- (d) force 아닐 때 기본 동작 불변 ----------------------------------------


def test_whisper_disabled_when_env_off_and_not_forced(monkeypatch):
    monkeypatch.delenv("TRANSCRIPT_WHISPER_ENABLED", raising=False)
    attempt = transcript.transcribe_via_whisper("vid")
    assert attempt.outcome == transcript.TranscriptOutcomeCode.DISABLED.value


# --- (c)+(e) force가 env 게이트를 우회하고 model_size를 전달 ------------------


def test_force_bypasses_env_gate_and_passes_model(monkeypatch):
    monkeypatch.delenv("TRANSCRIPT_WHISPER_ENABLED", raising=False)
    captured: dict = {}
    _install_fake_whisper(monkeypatch, captured)

    attempt = transcript.transcribe_via_whisper(
        "vid", force=True, model_size="small"
    )
    assert attempt.outcome == transcript.TranscriptOutcomeCode.SUCCESS.value
    assert attempt.provider == "whisper"
    assert captured["model_size"] == "small"  # env 기본 "base" 아님
    assert attempt.result is not None
    assert attempt.result.segments[0].text == "안녕하세요"


def test_forced_chain_runs_whisper_even_when_env_off(monkeypatch):
    monkeypatch.delenv("TRANSCRIPT_WHISPER_ENABLED", raising=False)
    captured: dict = {}
    _install_fake_whisper(monkeypatch, captured)

    chain = transcript.whisper_forced_chain("medium")
    outcome = transcript.fetch_transcript("vid", providers=chain)
    assert outcome.result is not None
    assert outcome.success_provider == "whisper"
    assert captured["model_size"] == "medium"


async def test_forced_fetcher_factory_injects_model(monkeypatch):
    monkeypatch.delenv("TRANSCRIPT_WHISPER_ENABLED", raising=False)
    captured: dict = {}
    _install_fake_whisper(monkeypatch, captured)

    fetcher = postprocess_service._whisper_forced_transcript_fetcher("medium")
    outcome = await fetcher("vid")
    assert outcome.result is not None
    assert outcome.success_provider == "whisper"
    assert captured["model_size"] == "medium"


# --- API 트리거: (a) duration cap, (b) batch 레인, (d) 기본 interactive ------


@pytest_asyncio.fixture
async def client(session_factory):
    async def override_get_session():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_repeatable_read_session] = override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _seed_video(session_factory, video_id: str, duration: int | None) -> None:
    async with session_factory() as s:
        s.add(
            YoutubeVideo(
                video_id=video_id,
                title=video_id,
                url=f"https://youtu.be/{video_id}",
                channel_id="chan-1",
                channel_name="chan-1",
                duration_seconds=duration,
            )
        )
        await s.commit()


async def test_reprocess_force_whisper_uses_batch_lane(client, session_factory):
    await _seed_video(session_factory, "w-short", 600)
    resp = await client.post(
        "/api/v1/destinations/reprocess",
        json={"video_ids": ["w-short"], "force_whisper": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["force_whisper"] is True
    assert body["start_stage"] == "transcript"
    job_id = body["job_ids"][0]

    view = (await client.get(f"/api/v1/runs/{job_id}")).json()
    # 수동 whisper 재전사는 대화형이 아니라 배치 레인이어야 한다.
    assert view["lane"] == "batch"

    # payload에 whisper 강제 파라미터가 실린다(기본 모델은 config WHISPER_MANUAL_MODEL_SIZE).
    from ktc.core.config import get_settings
    from ktc.models import CrawlRun
    from sqlalchemy import select
    import json as _json

    async with session_factory() as s:
        run = (
            await s.execute(select(CrawlRun).where(CrawlRun.id == int(job_id)))
        ).scalar_one()
        payload = _json.loads(run.payload_json)
    assert payload["force_whisper"] is True
    assert payload["start_stage"] == "transcript"
    assert payload["whisper_model"] == get_settings().WHISPER_MANUAL_MODEL_SIZE


async def test_reprocess_force_whisper_rejects_over_duration(client, session_factory):
    await _seed_video(session_factory, "w-long", 2000)
    resp = await client.post(
        "/api/v1/destinations/reprocess",
        json={"video_ids": ["w-long"], "force_whisper": True},
    )
    assert resp.status_code == 400
    assert "w-long" in resp.json()["detail"]


async def test_reprocess_force_whisper_custom_model_passes_through(
    client, session_factory
):
    await _seed_video(session_factory, "w-model", 300)
    resp = await client.post(
        "/api/v1/destinations/reprocess",
        json={
            "video_ids": ["w-model"],
            "force_whisper": True,
            "whisper_model": "medium",
        },
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_ids"][0]

    from ktc.models import CrawlRun
    from sqlalchemy import select
    import json as _json

    async with session_factory() as s:
        run = (
            await s.execute(select(CrawlRun).where(CrawlRun.id == int(job_id)))
        ).scalar_one()
        payload = _json.loads(run.payload_json)
    assert payload["whisper_model"] == "medium"


async def test_reprocess_without_force_whisper_stays_interactive(
    client, session_factory
):
    await _seed_video(session_factory, "no-whisper", 300)
    resp = await client.post(
        "/api/v1/destinations/reprocess",
        json={"video_ids": ["no-whisper"], "start_stage": "transcript"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["force_whisper"] is False
    job_id = body["job_ids"][0]
    view = (await client.get(f"/api/v1/runs/{job_id}")).json()
    # 기본 재처리는 종전 계약대로 대화형 레인이며 whisper 강제 파라미터가 없다.
    assert view["lane"] == "interactive"

    from ktc.models import CrawlRun
    from sqlalchemy import select
    import json as _json

    async with session_factory() as s:
        run = (
            await s.execute(select(CrawlRun).where(CrawlRun.id == int(job_id)))
        ).scalar_one()
        payload = _json.loads(run.payload_json)
    assert "force_whisper" not in payload
