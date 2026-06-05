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


async def _collect_video_ids(
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


async def run_harvest(
    session: AsyncSession,
    client: YouTubeClient,
    *,
    seed_keyword: str,
    max_videos: int = 20,
    now: datetime | None = None,
    generator: KeywordGenerator | None = None,
) -> dict[str, Any]:
    """시드 키워드 기준 수집을 실행하고 요약을 반환한다."""
    now = now or ingest_service.utcnow()
    season = ranking.current_season(now.date())

    derived = generate_derived_keywords(seed_keyword, season, generator=generator)
    await ingest_service.persist_derived_keywords(
        session, seed=seed_keyword, derived=derived, season=season
    )

    queries = [seed_keyword, *derived]
    video_ids = await _collect_video_ids(client, queries, max_videos=max_videos)

    candidates: list[dict[str, Any]] = []
    if video_ids:
        details = await client.videos_list(video_ids)
        candidates = [
            build_candidate(item, seed=seed_keyword, now=now)
            for item in details.get("items", [])
        ]
        # 우선순위 점수 내림차순 정렬 후 상한 적용
        candidates.sort(key=lambda c: c["priority_score"], reverse=True)
        candidates = candidates[:max_videos]

    summary = await ingest_service.ingest_candidates(session, candidates)
    summary.update(
        {
            "seed_keyword": seed_keyword,
            "season": season,
            "derived_keywords": derived,
            "quota_used": client.quota_used,
        }
    )
    return summary
