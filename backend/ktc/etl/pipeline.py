"""YouTube 수집 파이프라인 오케스트레이션 (1단계).

파생 키워드 생성 → 공식 API 검색 → 상세 조회 → 정규화·점수 → 멱등 적재까지
연결한다. 네트워크 호출은 주입형 `YouTubeClient`로 격리해 테스트에서 mock한다.
실제 ETL 실행 주체는 scheduler 단일 실행자다(ADR-13, T-010에서 연결).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ktc.etl import ingest_service, ranking
from ktc.etl.keyword_expansion import (
    KeywordGenerator,
    default_keyword_generator,
    generate_derived_keywords,
)
from ktc.etl.youtube_client import YouTubeClient

StatusReporter = Callable[[str, float | None], Awaitable[None]]


async def _report(
    status_reporter: StatusReporter | None,
    message: str,
    progress: float | None = None,
) -> None:
    if status_reporter is not None:
        await status_reporter(message, progress)


def _quoted_list(values: list[str], *, limit: int = 3) -> str:
    visible = values[:limit]
    quoted = ", ".join(f'"{value}"' for value in visible)
    if len(values) > limit:
        return f"{quoted} 외 {len(values) - limit}개"
    return quoted or "-"


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _best_thumbnail_url(thumbnails: dict[str, Any] | None) -> str | None:
    return ingest_service.best_thumbnail_url(thumbnails)


def build_candidate(item: dict[str, Any], *, seed: str, now: datetime) -> dict[str, Any]:
    """`videos.list` 항목을 점수가 매겨진 후보 dict로 변환한다."""
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    content_details = item.get("contentDetails", {})
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
        "canonical_url": f"https://www.youtube.com/watch?v={video_id}",
        "channel_id": snippet.get("channelId", ""),
        "channel_name": snippet.get("channelTitle"),
        "published_at": published_at,
        "duration_seconds": ingest_service.parse_duration_seconds(
            content_details.get("duration")
        ),
        "thumbnail_url": _best_thumbnail_url(snippet.get("thumbnails")),
        "default_language": snippet.get("defaultAudioLanguage")
        or snippet.get("defaultLanguage"),
        "tags_json": snippet.get("tags") if isinstance(snippet.get("tags"), list) else None,
        "view_count": view_count,
        "like_count": like_count,
        "description_raw": snippet.get("description"),
        "engagement_score": engagement,
        "priority_score": score,
    }


async def _collect_keyword_video_ids(
    client: YouTubeClient,
    queries: list[str],
    *,
    max_videos: int,
    published_after: datetime | None = None,
    status_reporter: StatusReporter | None = None,
) -> list[str]:
    """여러 검색어로 검색해 중복 없는 video_id를 모은다."""
    ids: list[str] = []
    seen: set[str] = set()
    total = max(1, len(queries))
    for index, query in enumerate(queries):
        if len(ids) >= max_videos:
            break
        await _report(
            status_reporter,
            f'YouTube에서 "{query}" 검색을 실행 중입니다.',
            0.28 + (0.22 * index / total),
        )
        data = await client.search_list(
            query=query,
            max_results=max_videos,
            published_after=_youtube_datetime(published_after),
        )
        found_in_query = 0
        for item in data.get("items", []):
            vid = item.get("id", {}).get("videoId")
            if vid and vid not in seen:
                seen.add(vid)
                ids.append(vid)
                found_in_query += 1
        await _report(
            status_reporter,
            f'YouTube에서 검색어 "{query}"의 새 동영상 후보 {found_in_query}개를 찾았습니다.',
            0.32 + (0.22 * (index + 1) / total),
        )
    await _report(
        status_reporter,
        f"YouTube에서 총 {len(ids[:max_videos])}개의 중복 없는 동영상을 찾았습니다.",
        0.55,
    )
    return ids[:max_videos]


def _video_id_from_playlist_item(item: dict[str, Any]) -> str | None:
    content_details = item.get("contentDetails", {})
    video_id = content_details.get("videoId")
    if video_id:
        return video_id
    resource = item.get("snippet", {}).get("resourceId", {})
    return resource.get("videoId")


def _published_at_from_playlist_item(item: dict[str, Any]) -> datetime | None:
    content_details = item.get("contentDetails", {})
    value = content_details.get("videoPublishedAt")
    if not value:
        value = item.get("snippet", {}).get("publishedAt")
    return ingest_service.parse_published_at(value)


def _as_utc_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _youtube_datetime(value: datetime | None) -> str | None:
    value = _as_utc_aware(value)
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


async def _collect_playlist_video_ids(
    client: YouTubeClient,
    playlist_id: str,
    *,
    max_videos: int,
    stop_at_or_before: datetime | None = None,
    status_reporter: StatusReporter | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    """재생목록 항목에서 중복 없는 video_id를 모은다."""
    ids: list[str] = []
    links: list[dict[str, Any]] = []
    seen: set[str] = set()
    page_token: str | None = None
    stop_pagination = False
    await _report(
        status_reporter,
        f"YouTube 재생목록 {playlist_id}에서 동영상을 찾는 중입니다.",
        0.25,
    )
    while len(ids) < max_videos and not stop_pagination:
        data = await client.playlist_items_list(
            playlist_id,
            max_results=min(50, max_videos - len(ids)),
            page_token=page_token,
        )
        for item in data.get("items", []):
            published_at = _as_utc_aware(_published_at_from_playlist_item(item))
            if (
                stop_at_or_before is not None
                and published_at is not None
                and published_at <= stop_at_or_before
            ):
                stop_pagination = True
                break
            video_id = _video_id_from_playlist_item(item)
            if video_id and video_id not in seen:
                seen.add(video_id)
                ids.append(video_id)
                link = ingest_service.build_playlist_video_link(
                    item,
                    playlist_id=playlist_id,
                    now=ingest_service.utcnow(),
                )
                if link is not None:
                    links.append(link)
                if len(ids) >= max_videos:
                    break
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    await _report(
        status_reporter,
        f"YouTube 재생목록 {playlist_id}에서 {len(ids[:max_videos])}개의 동영상을 찾았습니다.",
        0.55,
    )
    return ids[:max_videos], links[:max_videos]


async def _collect_channel_video_ids(
    client: YouTubeClient,
    channel_id: str,
    *,
    uploads_playlist_id: str | None = None,
    max_videos: int,
    stop_at_or_before: datetime | None = None,
    status_reporter: StatusReporter | None = None,
) -> tuple[list[str], str | None, list[dict[str, Any]]]:
    """채널 업로드 재생목록을 찾아 video_id를 모은다."""
    await _report(
        status_reporter,
        f"YouTube 채널 {channel_id}의 업로드 재생목록을 확인 중입니다.",
        0.2,
    )
    if uploads_playlist_id is None:
        uploads_playlist_id = await client.uploads_playlist_id(channel_id)
    if not uploads_playlist_id:
        await _report(
            status_reporter,
            f"YouTube 채널 {channel_id}에서 업로드 재생목록을 찾지 못했습니다.",
            0.4,
        )
        return [], None, []
    ids, links = await _collect_playlist_video_ids(
        client,
        uploads_playlist_id,
        max_videos=max_videos,
        stop_at_or_before=stop_at_or_before,
        status_reporter=status_reporter,
    )
    return ids, uploads_playlist_id, links


def _metadata_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = data.get("items", [])
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _uploads_playlist_id_from_channels(data: dict[str, Any]) -> str | None:
    for item in _metadata_items(data):
        uploads = (
            item.get("contentDetails", {})
            .get("relatedPlaylists", {})
            .get("uploads")
        )
        if uploads:
            return str(uploads)
    return None


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
    status_reporter: StatusReporter | None = None,
) -> dict[str, Any]:
    """키워드·채널·재생목록 기준 수집을 실행하고 요약을 반환한다."""
    now = now or ingest_service.utcnow()
    season = ranking.current_season(now.date())
    await _report(status_reporter, "수집 대상과 계절 맥락을 확인 중입니다.", 0.12)

    target_type = "keyword"
    target_id = seed_keyword
    derived: list[str] = []
    uploads_playlist_id: str | None = None
    channel_metadata: list[dict[str, Any]] = []
    playlist_metadata: list[dict[str, Any]] = []
    playlist_links: list[dict[str, Any]] = []

    if playlist_id:
        target_type = "playlist"
        target_id = playlist_id
        playlist_details = await client.playlists_list(playlist_id)
        playlist_metadata = [
            ingest_service.build_playlist_metadata(item, now=now)
            for item in _metadata_items(playlist_details)
        ]
        watermark = _as_utc_aware(
            await ingest_service.get_source_target_watermark(
                session, target_type=target_type, source_value=playlist_id
            )
        )
        video_ids, playlist_links = await _collect_playlist_video_ids(
            client,
            playlist_id,
            max_videos=max_videos,
            stop_at_or_before=watermark,
            status_reporter=status_reporter,
        )
    elif channel_id:
        target_type = "channel"
        target_id = channel_id
        channel_details = await client.channels_list(channel_id)
        channel_metadata = [
            ingest_service.build_channel_metadata(item, now=now)
            for item in _metadata_items(channel_details)
        ]
        watermark = _as_utc_aware(await ingest_service.get_channel_watermark(session, channel_id))
        uploads_playlist_id = _uploads_playlist_id_from_channels(channel_details)
        video_ids, uploads_playlist_id, playlist_links = await _collect_channel_video_ids(
            client,
            channel_id,
            uploads_playlist_id=uploads_playlist_id,
            max_videos=max_videos,
            stop_at_or_before=watermark,
            status_reporter=status_reporter,
        )
        if uploads_playlist_id:
            playlist_details = await client.playlists_list(uploads_playlist_id)
            playlist_metadata = [
                ingest_service.build_playlist_metadata(item, now=now)
                for item in _metadata_items(playlist_details)
            ]
    else:
        if not seed_keyword:
            raise ValueError("run_harvest에는 seed_keyword, channel_id, playlist_id 중 하나가 필요하다")
        await _report(
            status_reporter,
            f'Gemini에서 검색어 "{seed_keyword}"를 보정 중입니다.',
            0.18,
        )
        keyword_generator = generator or default_keyword_generator()
        derived = generate_derived_keywords(
            seed_keyword, season, generator=keyword_generator
        )
        await ingest_service.persist_derived_keywords(
            session, seed=seed_keyword, derived=derived, season=season
        )
        await _report(
            status_reporter,
            f"Gemini에서 검색어를 보정했습니다. 보정 결과는 {_quoted_list(derived)} 입니다.",
            0.24,
        )
        queries = [seed_keyword, *derived]
        watermark = _as_utc_aware(
            await ingest_service.get_source_target_watermark(
                session, target_type=target_type, source_value=seed_keyword
            )
        )
        video_ids = await _collect_keyword_video_ids(
            client,
            queries,
            max_videos=max_videos,
            published_after=watermark,
            status_reporter=status_reporter,
        )

    candidates: list[dict[str, Any]] = []
    if video_ids:
        await _report(
            status_reporter,
            f"YouTube 동영상 {len(video_ids)}개의 상세 정보를 조회 중입니다.",
            0.62,
        )
        details = await client.videos_list(video_ids)
        candidates = [
            build_candidate(item, seed=seed_keyword or "", now=now)
            for item in details.get("items", [])
        ]
        candidate_channel_ids = sorted(
            {
                str(candidate.get("channel_id"))
                for candidate in candidates
                if candidate.get("channel_id")
            }
        )
        if candidate_channel_ids:
            channel_details = await client.channels_list(candidate_channel_ids)
            channel_metadata_by_id = {
                payload["channel_id"]: payload
                for payload in channel_metadata
                if payload.get("channel_id")
            }
            for item in _metadata_items(channel_details):
                payload = ingest_service.build_channel_metadata(item, now=now)
                channel_metadata_by_id[payload["channel_id"]] = payload
            channel_metadata = list(channel_metadata_by_id.values())
        # 우선순위 점수 내림차순 정렬 후 상한 적용
        candidates.sort(key=lambda c: c["priority_score"], reverse=True)
        candidates = candidates[:max_videos]
        candidate_video_ids = {str(candidate["video_id"]) for candidate in candidates}
        playlist_links = [
            link
            for link in playlist_links
            if str(link.get("video_id") or "") in candidate_video_ids
        ]
        titles = [str(candidate.get("title") or candidate["video_id"]) for candidate in candidates]
        await _report(
            status_reporter,
            f"YouTube 동영상 상세 정보를 조회했습니다. 후보는 {_quoted_list(titles)} 입니다.",
            0.72,
        )
    else:
        await _report(status_reporter, "YouTube에서 처리할 새 동영상을 찾지 못했습니다.", 0.72)

    await _report(
        status_reporter,
        f"동영상 후보 {len(candidates)}개를 데이터베이스에 저장 중입니다.",
        0.78,
    )
    summary = await ingest_service.ingest_candidates(
        session,
        candidates,
        channels=channel_metadata,
        playlists=playlist_metadata,
        playlist_links=playlist_links,
    )
    if target_id:
        await ingest_service.mark_source_target_crawled(
            session,
            target_type=target_type,
            source_value=target_id,
            crawled_at=now,
        )
    await _report(
        status_reporter,
        f"동영상 적재를 완료했습니다. 신규 {summary['inserted']}개, 갱신 {summary['updated']}개입니다.",
        0.86,
    )
    summary.update(
        {
            "video_ids": [str(candidate["video_id"]) for candidate in candidates],
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
