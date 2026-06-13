"""ingest_service 멱등 upsert/워터마크 테스트."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from ktc.etl import ingest_service
from ktc.models import YoutubeChannel, YoutubePlaylist, YoutubePlaylistVideo, YoutubeVideo


def test_parse_published_at():
    dt = ingest_service.parse_published_at("2026-05-01T12:00:00Z")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.year == 2026 and dt.month == 5
    assert ingest_service.parse_published_at(None) is None
    assert ingest_service.parse_published_at("garbage") is None


def test_parse_duration_seconds():
    assert ingest_service.parse_duration_seconds("PT1H2M3S") == 3723
    assert ingest_service.parse_duration_seconds("PT15M") == 900
    assert ingest_service.parse_duration_seconds("P1DT2S") == 86402
    assert ingest_service.parse_duration_seconds(None) is None
    assert ingest_service.parse_duration_seconds("garbage") is None


def test_build_youtube_source_metadata():
    now = datetime(2026, 6, 10, tzinfo=timezone.utc)
    channel = ingest_service.build_channel_metadata(
        {
            "id": "UC1",
            "snippet": {
                "title": "여행채널",
                "customUrl": "@travel",
                "publishedAt": "2020-01-01T00:00:00Z",
                "thumbnails": {
                    "default": {"url": "small.jpg"},
                    "high": {"url": "large.jpg"},
                },
            },
            "statistics": {"subscriberCount": "1234", "videoCount": "56"},
        },
        now=now,
    )
    assert channel["channel_id"] == "UC1"
    assert channel["thumbnail_url"] == "large.jpg"
    assert channel["subscriber_count"] == 1234

    playlist = ingest_service.build_playlist_metadata(
        {
            "id": "PL1",
            "snippet": {"channelId": "UC1", "title": "서울 맛집"},
            "contentDetails": {"itemCount": "7"},
        },
        now=now,
    )
    assert playlist["playlist_id"] == "PL1"
    assert playlist["channel_id"] == "UC1"
    assert playlist["item_count"] == 7

    link = ingest_service.build_playlist_video_link(
        {
            "id": "PLI1",
            "snippet": {
                "position": 3,
                "publishedAt": "2026-06-01T00:00:00Z",
                "resourceId": {"videoId": "v1"},
            },
        },
        playlist_id="PL1",
        now=now,
    )
    assert link is not None
    assert link["playlist_id"] == "PL1"
    assert link["video_id"] == "v1"
    assert link["position"] == 3


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


async def test_upsert_ignores_empty_metadata_values(session):
    await ingest_service.upsert_video(
        session,
        {
            "video_id": "v-empty",
            "channel_id": "UC1",
            "title": "원래 제목",
            "description_raw": "원래 설명",
        },
    )

    await ingest_service.upsert_video(
        session,
        {
            "video_id": "v-empty",
            "channel_id": "",
            "title": "",
            "description_raw": "",
        },
    )

    refreshed = await session.get(YoutubeVideo, "v-empty")
    assert refreshed.channel_id == "UC1"
    assert refreshed.title == "원래 제목"
    assert refreshed.description_raw == "원래 설명"


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
    assert summary["discovered"] == 3
    assert summary["inserted"] == 2
    assert summary["updated"] == 1


async def test_ingest_candidates_upserts_youtube_source_links(session):
    now = datetime(2026, 6, 10, tzinfo=timezone.utc)
    summary = await ingest_service.ingest_candidates(
        session,
        [
            {
                "video_id": "v1",
                "channel_id": "UC1",
                "channel_name": "여행채널",
                "canonical_url": "https://www.youtube.com/watch?v=v1",
                "duration_seconds": 123,
                "thumbnail_url": "https://i.ytimg.com/vi/v1/maxresdefault.jpg",
                "default_language": "ko",
                "tags_json": ["서울", "맛집"],
            }
        ],
        channels=[
            {
                "channel_id": "UC1",
                "title": "여행채널",
                "handle": "@travel",
                "last_seen_at": now,
            }
        ],
        playlists=[
            {
                "playlist_id": "PL1",
                "channel_id": "UC1",
                "title": "서울 맛집",
                "last_crawled_at": now,
            }
        ],
        playlist_links=[
            {
                "playlist_id": "PL1",
                "video_id": "v1",
                "position": 0,
                "playlist_item_id": "PLI1",
                "first_seen_at": now,
                "last_seen_at": now,
            }
        ],
    )

    assert summary["channels_inserted"] == 1
    assert summary["playlists_inserted"] == 1
    assert summary["playlist_links_inserted"] == 1

    channel = await session.get(YoutubeChannel, "UC1")
    video = await session.get(YoutubeVideo, "v1")
    playlist = await session.get(YoutubePlaylist, "PL1")
    link = await session.get(YoutubePlaylistVideo, ("PL1", "v1"))
    assert channel is not None and channel.handle == "@travel"
    assert video is not None and video.duration_seconds == 123
    assert video.tags_json == ["서울", "맛집"]
    assert playlist is not None and playlist.channel_id == "UC1"
    assert link is not None and link.position == 0
