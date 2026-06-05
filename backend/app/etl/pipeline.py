"""YouTube 수집 파이프라인 오케스트레이션 (1단계).

파생 키워드 생성 → 공식 API 검색 → 상세 조회 → 정규화·점수 → 멱등 적재까지
연결한다. 네트워크 호출은 주입형 `YouTubeClient`로 격리해 테스트에서 mock한다.
실제 ETL 실행 주체는 scheduler 단일 실행자다(ADR-13, T-010에서 연결).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.etl import ingest_service, ranking
from app.etl.keyword_expansion import KeywordGenerator, generate_derived_keywords
from app.etl.youtube_client import YouTubeClient


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_candidate(item: dict[str, Any], *, seed: str, now: datetime) -> dict[str, Any]:
    """`videos.list` 항목을 점수가 매겨진 후보 dict로 변환한다."""
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    video_id = item["id"]
    title = snippet.get("title", "")
    published_at = ingest_service.parse_published_at(snippet.get("publishedAt"))
    view_count = _to_int(stats.get("viewCount"))
    like_count = _to_int(stats.get("likeCount"))

    similarity = ranking.keyword_similarity(seed, title)
    engagement = ranking.engagement_score(view_count, like_count)
    recency = ranking.recency_score(published_at, now)
    score = ranking.composite_score(
        similarity=similarity, engagement=engagement, recency=recency
    )

    return {
        "video_id": video_id,
        "title": title,
        "url": f"https://youtu.be/{video_id}",
        "channel_id": snippet.get("channelId", ""),
        "channel_name": snippet.get("channelTitle"),
        "published_at": published_at,
        "view_count": view_count,
        "like_count": like_count,
        "description_raw": snippet.get("description"),
        "engagement_score": engagement,
        "priority_score": score,
    }


async def _collect_keyword_video_ids(
    client: YouTubeClient, queries: list[str], *, max_videos: int
) -> list[str]:
    """여러 검색어로 검색해 중복 없는 video_id를 모은다."""
    ids: list[str] = []
    seen: set[str] = set()
    for query in queries:
        if len(ids) >= max_videos:
            break
        data = await client.search_list(query=query, max_results=max_videos)
        for item in data.get("items", []):
            vid = item.get("id", {}).get("videoId")
            if vid and vid not in seen:
                seen.add(vid)
                ids.append(vid)
    return ids[:max_videos]


def _video_id_from_playlist_item(item: dict[str, Any]) -> str | None:
    content_details = item.get("contentDetails", {})
    video_id = content_details.get("videoId")
    if video_id:
        return video_id
    resource = item.get("snippet", {}).get("resourceId", {})
    return resource.get("videoId")


async def _collect_playlist_video_ids(
    client: YouTubeClient, playlist_id: str, *, max_videos: int
) -> list[str]:
    """재생목록 항목에서 중복 없는 video_id를 모은다."""
    ids: list[str] = []
    seen: set[str] = set()
    page_token: str | None = None
    while len(ids) < max_videos:
        data = await client.playlist_items_list(
            playlist_id,
            max_results=min(50, max_videos - len(ids)),
            page_token=page_token,
        )
        for item in data.get("items", []):
            video_id = _video_id_from_playlist_item(item)
            if video_id and video_id not in seen:
                seen.add(video_id)
                ids.append(video_id)
                if len(ids) >= max_videos:
                    break
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return ids[:max_videos]


async def _collect_channel_video_ids(
    client: YouTubeClient, channel_id: str, *, max_videos: int
) -> tuple[list[str], str | None]:
    """채널 업로드 재생목록을 찾아 video_id를 모은다."""
    uploads_playlist_id = await client.uploads_playlist_id(channel_id)
    if not uploads_playlist_id:
        return [], None
    ids = await _collect_playlist_video_ids(
        client, uploads_playlist_id, max_videos=max_videos
    )
    return ids, uploads_playlist_id


async def run_harvest(
    session: AsyncSession,
    client: YouTubeClient,
    *,
    seed_keyword: str | None = None,
    channel_id: str | None = None,
    playlist_id: str | None = None,
    max_videos: int = 20,
    now: datetime | None = None,
    generator: KeywordGenerator | None = None,
) -> dict[str, Any]:
    """키워드·채널·재생목록 기준 수집을 실행하고 요약을 반환한다."""
    now = now or ingest_service.utcnow()
    season = ranking.current_season(now.date())

    target_type = "keyword"
    target_id = seed_keyword
    derived: list[str] = []
    uploads_playlist_id: str | None = None

    if playlist_id:
        target_type = "playlist"
        target_id = playlist_id
        video_ids = await _collect_playlist_video_ids(
            client, playlist_id, max_videos=max_videos
        )
    elif channel_id:
        target_type = "channel"
        target_id = channel_id
        video_ids, uploads_playlist_id = await _collect_channel_video_ids(
            client, channel_id, max_videos=max_videos
        )
    else:
        if not seed_keyword:
            raise ValueError("run_harvest에는 seed_keyword, channel_id, playlist_id 중 하나가 필요하다")
        derived = generate_derived_keywords(seed_keyword, season, generator=generator)
        await ingest_service.persist_derived_keywords(
            session, seed=seed_keyword, derived=derived, season=season
        )
        queries = [seed_keyword, *derived]
        video_ids = await _collect_keyword_video_ids(
            client, queries, max_videos=max_videos
        )

    candidates: list[dict[str, Any]] = []
    if video_ids:
        details = await client.videos_list(video_ids)
        candidates = [
            build_candidate(item, seed=seed_keyword or "", now=now)
            for item in details.get("items", [])
        ]
        # 우선순위 점수 내림차순 정렬 후 상한 적용
        candidates.sort(key=lambda c: c["priority_score"], reverse=True)
        candidates = candidates[:max_videos]

    summary = await ingest_service.ingest_candidates(session, candidates)
    summary.update(
        {
            "target_type": target_type,
            "target_id": target_id,
            "seed_keyword": seed_keyword,
            "channel_id": channel_id,
            "playlist_id": playlist_id,
            "uploads_playlist_id": uploads_playlist_id,
            "season": season,
            "derived_keywords": derived,
            "quota_used": client.quota_used,
        }
    )
    return summary
