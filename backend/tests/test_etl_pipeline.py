"""수집 파이프라인 통합 테스트 (httpx MockTransport)."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest_asyncio
from sqlalchemy import select

from app.etl import pipeline
from app.etl.youtube_client import (
    YouTubeApiError,
    YouTubeClient,
    YouTubeQuotaExceededError,
)
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
    assert "key" not in request.url.params
    assert request.headers.get("x-goog-api-key") == "test-key"
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


async def test_run_harvest_reports_detailed_status(session, yt_client):
    reported: list[tuple[str, float | None]] = []

    async def reporter(message: str, progress: float | None = None) -> None:
        reported.append((message, progress))

    await pipeline.run_harvest(
        session,
        yt_client,
        seed_keyword="제주도 맛집",
        max_videos=2,
        now=NOW,
        status_reporter=reporter,
    )

    messages = [message for message, _ in reported]
    assert any("Gemini에서 검색어" in message for message in messages)
    assert any("YouTube에서" in message and "검색을 실행 중" in message for message in messages)
    assert any("동영상 적재를 완료했습니다" in message for message in messages)


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


async def test_channel_harvest_stops_at_existing_watermark(session):
    seen_paths: list[str] = []

    await session.merge(
        YoutubeVideo(
            video_id="old",
            title="이전 영상",
            url="https://youtu.be/old",
            channel_id="UC1",
            published_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
        )
    )
    await session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.url.path.endswith("/channels"):
            return httpx.Response(200, json=_CHANNEL_RESPONSE)
        if request.url.path.endswith("/playlistItems"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "contentDetails": {
                                "videoId": "v-new",
                                "videoPublishedAt": "2026-06-01T00:00:00Z",
                            }
                        },
                        {
                            "contentDetails": {
                                "videoId": "old",
                                "videoPublishedAt": "2026-05-20T00:00:00Z",
                            }
                        },
                    ],
                    "nextPageToken": "SHOULD_NOT_FETCH",
                },
            )
        if request.url.path.endswith("/videos"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "v-new",
                            "snippet": {
                                "title": "새 영상",
                                "channelId": "UC1",
                                "channelTitle": "여행채널",
                                "publishedAt": "2026-06-01T00:00:00Z",
                            },
                            "statistics": {},
                        }
                    ]
                },
            )
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = YouTubeClient(api_key="test-key", http_client=http)
        summary = await pipeline.run_harvest(
            session,
            client,
            channel_id="UC1",
            max_videos=10,
            now=NOW,
        )

    assert summary["discovered"] == 1
    assert seen_paths.count("/youtube/v3/playlistItems") == 1
    videos = (await session.execute(select(YoutubeVideo))).scalars().all()
    assert {v.video_id for v in videos} == {"old", "v-new"}


async def test_build_candidate_scoring():
    item = _VIDEOS_RESPONSE["items"][0]
    cand = pipeline.build_candidate(item, seed="제주도 맛집", now=NOW)
    assert cand["video_id"] == "v1"
    assert cand["view_count"] == 10000
    assert cand["like_count"] == 1000
    assert 0 < cand["engagement_score"] <= 1
    assert cand["priority_score"] > 0


async def test_youtube_client_masks_api_key_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "key" not in request.url.params
        assert request.headers.get("x-goog-api-key") == "secret-key"
        return httpx.Response(403, json={"error": "quota"}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = YouTubeClient(api_key="secret-key", http_client=http, max_retries=0)
        try:
            await client.search_list(query="제주")
        except YouTubeApiError as exc:
            message = str(exc)
        else:  # pragma: no cover - 실패해야 하는 경로
            raise AssertionError("YouTubeApiError가 발생해야 한다")

    assert "secret-key" not in message
    assert "status=403" in message


async def test_youtube_client_enforces_quota_budget():
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as http:
        client = YouTubeClient(
            api_key="test-key",
            http_client=http,
            quota_budget_units=99,
        )
        try:
            await client.search_list(query="제주")
        except YouTubeQuotaExceededError as exc:
            message = str(exc)
        else:  # pragma: no cover - 실패해야 하는 경로
            raise AssertionError("YouTubeQuotaExceededError가 발생해야 한다")

    assert "budget=99" in message


async def test_videos_list_chunks_more_than_fifty_ids():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        ids = request.url.params.get("id", "")
        calls.append(ids)
        return httpx.Response(
            200,
            json={"items": [{"id": video_id} for video_id in ids.split(",") if video_id]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = YouTubeClient(api_key="test-key", http_client=http)
        data = await client.videos_list([f"v{i}" for i in range(55)])

    assert len(calls) == 2
    assert len(calls[0].split(",")) == 50
    assert len(data["items"]) == 55
