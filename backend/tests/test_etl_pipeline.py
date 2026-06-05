"""수집 파이프라인 통합 테스트 (httpx MockTransport)."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest_asyncio
from sqlalchemy import select

from app.etl import pipeline
from app.etl.youtube_client import YouTubeClient
from app.models import SearchKeyword, YoutubeVideo

NOW = datetime(2026, 6, 5, tzinfo=timezone.utc)

_SEARCH_RESPONSE = {
    "items": [
        {"id": {"videoId": "v1"}},
        {"id": {"videoId": "v2"}},
        {"id": {"videoId": "v3"}},
    ]
}

_VIDEOS_RESPONSE = {
    "items": [
        {
            "id": "v1",
            "snippet": {
                "title": "제주도 맛집 투어",
                "channelId": "UC1",
                "channelTitle": "여행채널",
                "publishedAt": "2026-06-01T00:00:00Z",
                "description": "제주 맛집 설명",
            },
            "statistics": {"viewCount": "10000", "likeCount": "1000"},
        },
        {
            "id": "v2",
            "snippet": {
                "title": "서울 카페",
                "channelId": "UC2",
                "channelTitle": "카페채널",
                "publishedAt": "2026-01-01T00:00:00Z",
                "description": "오래된 영상",
            },
            "statistics": {"viewCount": "5000", "likeCount": "50"},
        },
        {
            "id": "v3",
            "snippet": {
                "title": "제주도 핫플레이스",
                "channelId": "UC1",
                "channelTitle": "여행채널",
                "publishedAt": "2026-05-20T00:00:00Z",
                "description": "제주 핫플",
            },
            "statistics": {"viewCount": "8000", "likeCount": "400"},
        },
    ]
}

_CHANNEL_RESPONSE = {
    "items": [
        {
            "contentDetails": {
                "relatedPlaylists": {
                    "uploads": "PL_UPLOADS",
                }
            }
        }
    ]
}

_PLAYLIST_PAGE_1 = {
    "items": [
        {"contentDetails": {"videoId": "v1"}},
        {"snippet": {"resourceId": {"videoId": "v2"}}},
    ],
    "nextPageToken": "NEXT",
}

_PLAYLIST_PAGE_2 = {
    "items": [
        {"contentDetails": {"videoId": "v3"}},
    ]
}


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/search"):
        return httpx.Response(200, json=_SEARCH_RESPONSE)
    if path.endswith("/channels"):
        return httpx.Response(200, json=_CHANNEL_RESPONSE)
    if path.endswith("/playlistItems"):
        if request.url.params.get("pageToken") == "NEXT":
            return httpx.Response(200, json=_PLAYLIST_PAGE_2)
        return httpx.Response(200, json=_PLAYLIST_PAGE_1)
    if path.endswith("/videos"):
        requested = set((request.url.params.get("id") or "").split(","))
        return httpx.Response(
            200,
            json={
                "items": [
                    item for item in _VIDEOS_RESPONSE["items"] if item["id"] in requested
                ]
            },
        )
    return httpx.Response(404, json={"error": "unexpected"})


@pytest_asyncio.fixture
async def yt_client():
    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as http:
        yield YouTubeClient(api_key="test-key", http_client=http)


async def test_run_harvest_persists_and_scores(session, yt_client):
    summary = await pipeline.run_harvest(
        session, yt_client, seed_keyword="제주도 맛집", max_videos=10, now=NOW
    )
    assert summary["discovered"] == 3
    assert summary["inserted"] == 3
    assert summary["season"] == "summer"
    assert len(summary["derived_keywords"]) == 3
    # search(100) x4 쿼리 + videos(1) = 401, 단 dedup으로 첫 검색 후 채워지면 일부만 호출
    assert summary["quota_used"] >= 100

    videos = (await session.execute(select(YoutubeVideo))).scalars().all()
    assert {v.video_id for v in videos} == {"v1", "v2", "v3"}

    # 파생 키워드가 저장된다.
    kws = (await session.execute(select(SearchKeyword))).scalars().all()
    assert all(k.seed_keyword == "제주도 맛집" for k in kws)
    assert all(k.season_context == "summer" for k in kws)


async def test_run_harvest_idempotent_rerun(session, yt_client):
    await pipeline.run_harvest(session, yt_client, seed_keyword="제주도 맛집", now=NOW)
    summary2 = await pipeline.run_harvest(
        session, yt_client, seed_keyword="제주도 맛집", now=NOW
    )
    # 2회차는 모두 갱신(insert 0)
    assert summary2["inserted"] == 0
    assert summary2["updated"] == 3

    videos = (await session.execute(select(YoutubeVideo))).scalars().all()
    assert len(videos) == 3


async def test_run_harvest_playlist_reuses_ingest_path(session, yt_client):
    summary = await pipeline.run_harvest(
        session,
        yt_client,
        playlist_id="PL_DIRECT",
        max_videos=2,
        now=NOW,
    )
    assert summary["target_type"] == "playlist"
    assert summary["target_id"] == "PL_DIRECT"
    assert summary["playlist_id"] == "PL_DIRECT"
    assert summary["derived_keywords"] == []
    assert summary["discovered"] == 2
    assert summary["inserted"] == 2
    # playlistItems(1) + videos(1)
    assert summary["quota_used"] == 2

    videos = (await session.execute(select(YoutubeVideo))).scalars().all()
    assert {v.video_id for v in videos} == {"v1", "v2"}


async def test_run_harvest_channel_uses_uploads_playlist(session, yt_client):
    summary = await pipeline.run_harvest(
        session,
        yt_client,
        channel_id="UC1",
        max_videos=3,
        now=NOW,
    )
    assert summary["target_type"] == "channel"
    assert summary["target_id"] == "UC1"
    assert summary["channel_id"] == "UC1"
    assert summary["uploads_playlist_id"] == "PL_UPLOADS"
    assert summary["discovered"] == 3
    assert summary["inserted"] == 3
    # channels(1) + playlistItems(1) + playlistItems(1) + videos(1)
    assert summary["quota_used"] == 4

    videos = (await session.execute(select(YoutubeVideo))).scalars().all()
    assert {v.video_id for v in videos} == {"v1", "v2", "v3"}


async def test_build_candidate_scoring():
    item = _VIDEOS_RESPONSE["items"][0]
    cand = pipeline.build_candidate(item, seed="제주도 맛집", now=NOW)
    assert cand["video_id"] == "v1"
    assert cand["view_count"] == 10000
    assert cand["like_count"] == 1000
    assert 0 < cand["engagement_score"] <= 1
    assert cand["priority_score"] > 0
