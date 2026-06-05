"""ingest_service 멱등 upsert/워터마크 테스트."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.etl import ingest_service
from app.models import YoutubeVideo


def test_parse_published_at():
    dt = ingest_service.parse_published_at("2026-05-01T12:00:00Z")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.year == 2026 and dt.month == 5
    assert ingest_service.parse_published_at(None) is None
    assert ingest_service.parse_published_at("garbage") is None


async def test_upsert_video_idempotent(session):
    candidate = {
        "video_id": "vid1",
        "title": "제주 여행",
        "channel_id": "UC1",
        "view_count": 100,
        "like_count": 10,
        "description_raw": "원문",
    }
    video, created = await ingest_service.upsert_video(session, candidate)
    assert created is True
    assert video.title == "제주 여행"

    # 같은 video_id 재적재는 갱신(insert 아님)
    candidate["view_count"] = 200
    video2, created2 = await ingest_service.upsert_video(session, candidate)
    assert created2 is False
    assert video2.view_count == 200

    # 행이 하나만 존재
    count = len((await session.execute(select(YoutubeVideo))).scalars().all())
    assert count == 1


async def test_upsert_preserves_gemini_corrected(session):
    await ingest_service.upsert_video(session, {"video_id": "v", "channel_id": "c"})
    v = await session.get(YoutubeVideo, "v")
    v.description_gemini_corrected = "보정본"
    await session.commit()

    # 재수집 시 Gemini 보정 필드는 유지된다.
    await ingest_service.upsert_video(session, {"video_id": "v", "channel_id": "c", "title": "새 제목"})
    refreshed = await session.get(YoutubeVideo, "v")
    assert refreshed.description_gemini_corrected == "보정본"
    assert refreshed.title == "새 제목"


async def test_channel_watermark(session):
    assert await ingest_service.get_channel_watermark(session, "UC1") is None
    await ingest_service.upsert_video(
        session,
        {
            "video_id": "a",
            "channel_id": "UC1",
            "published_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        },
    )
    await ingest_service.upsert_video(
        session,
        {
            "video_id": "b",
            "channel_id": "UC1",
            "published_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
        },
    )
    wm = await ingest_service.get_channel_watermark(session, "UC1")
    assert wm is not None
    assert wm.month == 5


async def test_ingest_candidates_summary(session):
    cands = [
        {"video_id": "x", "channel_id": "c"},
        {"video_id": "y", "channel_id": "c"},
        {"video_id": "x", "channel_id": "c"},  # 중복 -> 갱신
    ]
    summary = await ingest_service.ingest_candidates(session, cands)
    assert summary == {"discovered": 3, "inserted": 2, "updated": 1}
