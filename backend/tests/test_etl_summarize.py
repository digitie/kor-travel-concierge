"""media_store + summarize_service 통합 테스트."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.etl import media_store, summarize_service
from app.etl.media_store import InMemoryMediaStore, store_and_record
from app.etl.transcript import TranscriptResult, TranscriptSegment
from app.models import (
    AssetType,
    CrawlStatus,
    ExtractedPlaceCandidate,
    MatchStatus,
    MediaAsset,
    YoutubeVideo,
)


@pytest.fixture(autouse=True)
def rustfs_test_settings(monkeypatch):
    monkeypatch.setenv("RUSTFS_BUCKET_RAW_VIDEOS", "tripmate-raw-videos")
    monkeypatch.setenv("RUSTFS_BUCKET_SUBTITLES", "tripmate-subtitles")
    monkeypatch.setenv("RUSTFS_BUCKET_FRAMES", "tripmate-frames")
    monkeypatch.setenv("RUSTFS_OBJECT_PREFIX", "")
    monkeypatch.setenv("RUSTFS_PUBLIC_BASE_URL", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


_LLM_JSON = json.dumps(
    {
        "summary": "요약",
        "description_gemini_corrected": "보정된 설명",
        "places": [
            {"name": "월정리 카페", "location_hint": "제주 월정리", "category": "카페"},
            {"name": "성산일출봉", "category": "관광지"},
        ],
    },
    ensure_ascii=False,
)


def test_bucket_routing():
    assert media_store.bucket_for(AssetType.TRANSCRIPT) == "tripmate-subtitles"
    assert media_store.bucket_for(AssetType.SUBTITLE) == "tripmate-subtitles"
    assert media_store.bucket_for(AssetType.FRAME) == "tripmate-frames"
    assert media_store.bucket_for(AssetType.RAW_VIDEO) == "tripmate-raw-videos"


async def test_store_and_record(session):
    await _make_video(session)
    store = InMemoryMediaStore()
    asset = await store_and_record(
        session,
        store,
        asset_type=AssetType.SUBTITLE,
        object_key="v1/sub.txt",
        data=b"hello",
        content_type="text/plain",
        video_id="v1",
    )
    assert asset.id is not None
    assert asset.bucket == "tripmate-subtitles"
    assert asset.size_bytes == 5
    assert asset.sha256 == media_store.sha256_hex(b"hello")
    assert asset.retention_policy == "infinite"
    assert ("tripmate-subtitles", "v1/sub.txt") in store.objects

    reused = await store_and_record(
        session,
        store,
        asset_type=AssetType.SUBTITLE,
        object_key="v1/sub.txt",
        data=b"changed",
        content_type="text/plain",
        video_id="v1",
    )
    assert reused.id == asset.id


async def test_store_and_record_applies_configured_prefix(session, monkeypatch):
    await _make_video(session)
    monkeypatch.setenv("RUSTFS_BUCKET_SUBTITLES", "krtour-map")
    monkeypatch.setenv("RUSTFS_OBJECT_PREFIX", "features")
    get_settings.cache_clear()

    store = InMemoryMediaStore()
    asset = await store_and_record(
        session,
        store,
        asset_type=AssetType.TRANSCRIPT,
        object_key="v1/transcript.txt",
        data=b"hello",
        content_type="text/plain",
        video_id="v1",
    )

    assert asset.bucket == "krtour-map"
    assert asset.object_key == "features/v1/transcript.txt"
    assert ("krtour-map", "features/v1/transcript.txt") in store.objects


async def _make_video(session):
    v = YoutubeVideo(
        video_id="v1", title="제주", url="u", channel_id="c", description_raw="원문 설명"
    )
    session.add(v)
    await session.commit()
    await session.refresh(v)
    return v


async def test_summarize_video_full_flow(session):
    video = await _make_video(session)
    store = InMemoryMediaStore()
    reported: list[str] = []

    async def reporter(message: str, progress: float | None = None) -> None:
        reported.append(message)

    transcript = TranscriptResult(
        video_id="v1",
        source="transcript_api",
        segments=[TranscriptSegment(30.0, "월정리 카페 소개"), TranscriptSegment(90.0, "성산일출봉")],
    )

    summary = await summarize_service.summarize_video(
        session,
        store,
        video=video,
        transcript=transcript,
        llm=lambda _: _LLM_JSON,
        status_reporter=reporter,
    )
    assert summary["status"] == "summarized"
    assert summary["candidates"] == 2

    # 영상 설명 원문은 보존, 보정본은 별도 저장
    refreshed = await session.get(YoutubeVideo, "v1")
    assert refreshed.description_raw == "원문 설명"
    assert refreshed.description_gemini_corrected == "보정된 설명"
    assert refreshed.description_gemini_model is not None
    assert refreshed.crawl_status == CrawlStatus.SUMMARIZED

    # 후보는 needs_review로 생성
    cands = (await session.execute(select(ExtractedPlaceCandidate))).scalars().all()
    assert len(cands) == 2
    assert all(c.match_status == MatchStatus.NEEDS_REVIEW for c in cands)

    # 전사 결과가 RustFS+media_assets에 기록
    assets = (await session.execute(select(MediaAsset))).scalars().all()
    assert len(assets) == 1
    assert assets[0].asset_type == AssetType.TRANSCRIPT
    assert any("자막을 RustFS에 저장했습니다" in message for message in reported)
    assert any("Gemini에서 영상 설명을 보정했습니다" in message for message in reported)


async def test_summarize_video_no_transcript(session):
    video = await _make_video(session)
    store = InMemoryMediaStore()
    summary = await summarize_service.summarize_video(
        session, store, video=video, transcript=None, llm=lambda _: _LLM_JSON
    )
    assert summary["status"] == "no_transcript"
    assert summary["candidates"] == 0
    refreshed = await session.get(YoutubeVideo, "v1")
    assert refreshed.crawl_status == CrawlStatus.FAILED


async def test_summarize_video_marks_failed_when_poi_extraction_fails(session):
    video = await _make_video(session)
    store = InMemoryMediaStore()
    transcript = TranscriptResult(
        video_id="v1",
        source="transcript_api",
        segments=[TranscriptSegment(30.0, "월정리 카페 소개")],
    )

    summary = await summarize_service.summarize_video(
        session,
        store,
        video=video,
        transcript=transcript,
        llm=lambda _: "not-json",
        max_retries=0,
    )

    assert summary["status"] == "poi_extraction_failed"
    assert summary["candidates"] == 0
    refreshed = await session.get(YoutubeVideo, "v1")
    assert refreshed.crawl_status == CrawlStatus.FAILED
