"""테마 중심 POI 공급 서비스.

외부 소비자가 "특정 테마를 중심으로 POI를 가져가려는" 목적에 맞춘 공급 계약이다.
테마는 두 종류다:

1. 유튜버(channel) / 재생목록(playlist) / 보정 검색어(keyword) — 그 출처에서 수집·확정된
   POI 전체를 테마로 묶는다.
2. 특정 동영상(video) — 그 동영상이 언급해 확정된 POI를 테마로 묶는다. 단, 매치되거나
   검수 완료된 POI가 `VIDEO_THEME_MIN_POIS`개 이상일 때에만 목록을 공개한다(사용자 정책).

확정 POI와 출처 근거 계산은 `place_service.list_place_summaries`를 재사용한다(결과 보기의
출처 필터와 같은 규칙: `video_place_mappings` ↔ `youtube_videos` 조인).
"""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ktc.models import (
    VideoPlaceMapping,
    YoutubeChannel,
    YoutubePlaylist,
    YoutubeVideo,
)
from ktc.services import place_service
from ktc.services.list_pagination import (
    ListPage,
    MAX_DB_INTEGER_ID,
    decode_cursor,
    encode_cursor,
    ensure_repeatable_read,
    filter_fingerprint,
)

# 동영상 테마 공개 최소 POI 수. 매치/검수 완료(=확정) POI가 이 값 이상일 때만 목록을 준다.
VIDEO_THEME_MIN_POIS = 5

ThemeKind = Literal["channel", "playlist", "keyword"]


def _theme_place_payload(summary: place_service.PlaceSummary) -> dict[str, Any]:
    """테마 POI 항목. 확정 장소 + 좌표/주소/카테고리 + 출처 동영상 근거."""
    place = summary.place
    return {
        "place_id": place.place_id,
        "name": place.name,
        "category": place.category,
        # Gemini가 고른 8자리 카테고리 제안(미확정이면 '0'). `feature_id` 확정은 consumer 책임.
        "category_code_suggestion": place.category_code_suggestion,
        "latitude": place.latitude,
        "longitude": place.longitude,
        "is_geocoded": place.is_geocoded,
        "address": {
            "official_address": place.official_address,
            "road_address": place.road_address,
            "sigungu_code": place.sigungu_code,
            "sigungu_name": place.sigungu_name,
            "legal_dong_code": place.legal_dong_code,
            "legal_dong_name": place.legal_dong_name,
        },
        # 이 POI가 (모든 출처 통틀어) 언급된 고유 영상 수/유튜버 수.
        "mention_count": summary.mention_count,
        "source_channel_count": summary.source_channel_count,
        "source_videos": [
            {
                "video_id": mention.video_id,
                "video_title": mention.video_title,
                "video_url": mention.video_url,
                "channel_id": mention.channel_id,
                "channel_title": mention.channel_name,
                "timestamp_start": mention.timestamp_start,
                "timestamp_end": mention.timestamp_end,
            }
            for mention in summary.source_videos
        ],
    }


_THEME_KIND_ORDER = {"channel": 0, "playlist": 1, "keyword": 2}


def _theme_sort_key(item: dict[str, Any]) -> tuple[int, int, str, str]:
    return (
        _THEME_KIND_ORDER[item["kind"]],
        -int(item["poi_count"]),
        str(item["title"]),
        str(item["value"]),
    )


async def _theme_items(
    session: AsyncSession, *, max_mapping_id: int | None = None
) -> list[dict[str, Any]]:
    """세 종류의 파생 테마를 동일한 flat item으로 집계한다."""
    place_count = func.count(distinct(VideoPlaceMapping.place_id))
    first_mapping_id = func.min(VideoPlaceMapping.id)
    latest_mapping_id = func.max(VideoPlaceMapping.id)
    mapping_limit = (
        [VideoPlaceMapping.id <= max_mapping_id]
        if max_mapping_id is not None
        else []
    )

    channel_stmt = (
        select(
            YoutubeVideo.channel_id,
            YoutubeChannel.title,
            place_count,
            first_mapping_id,
            latest_mapping_id,
        )
        .select_from(VideoPlaceMapping)
        .join(YoutubeVideo, VideoPlaceMapping.video_id == YoutubeVideo.video_id)
        .join(
            YoutubeChannel,
            YoutubeVideo.channel_id == YoutubeChannel.channel_id,
            isouter=True,
        )
        .where(YoutubeVideo.channel_id.isnot(None), *mapping_limit)
        .group_by(YoutubeVideo.channel_id, YoutubeChannel.title)
    )
    playlist_stmt = (
        select(
            VideoPlaceMapping.source_playlist_id,
            YoutubePlaylist.title,
            place_count,
            first_mapping_id,
            latest_mapping_id,
        )
        .select_from(VideoPlaceMapping)
        .join(
            YoutubePlaylist,
            VideoPlaceMapping.source_playlist_id == YoutubePlaylist.playlist_id,
            isouter=True,
        )
        .where(VideoPlaceMapping.source_playlist_id.isnot(None), *mapping_limit)
        .group_by(VideoPlaceMapping.source_playlist_id, YoutubePlaylist.title)
    )
    keyword_stmt = (
        select(
            YoutubeVideo.source_search_query,
            place_count,
            first_mapping_id,
            latest_mapping_id,
        )
        .select_from(VideoPlaceMapping)
        .join(YoutubeVideo, VideoPlaceMapping.video_id == YoutubeVideo.video_id)
        .where(YoutubeVideo.source_search_query.isnot(None), *mapping_limit)
        .group_by(YoutubeVideo.source_search_query)
    )

    items: list[dict[str, Any]] = []
    for value, title, count, first_id, latest_id in (
        await session.execute(channel_stmt)
    ).all():
        items.append(
            {
                "kind": "channel",
                "value": value,
                "title": title or value,
                "poi_count": int(count),
                "first_mapping_id": int(first_id),
                "latest_mapping_id": int(latest_id),
            }
        )
    for value, title, count, first_id, latest_id in (
        await session.execute(playlist_stmt)
    ).all():
        items.append(
            {
                "kind": "playlist",
                "value": value,
                "title": title or value,
                "poi_count": int(count),
                "first_mapping_id": int(first_id),
                "latest_mapping_id": int(latest_id),
            }
        )
    for value, count, first_id, latest_id in (
        await session.execute(keyword_stmt)
    ).all():
        items.append(
            {
                "kind": "keyword",
                "value": value,
                "title": value,
                "poi_count": int(count),
                "first_mapping_id": int(first_id),
                "latest_mapping_id": int(latest_id),
            }
        )
    items.sort(key=_theme_sort_key)
    return items


async def list_theme_summaries_page(
    session: AsyncSession,
    *,
    limit: int = 100,
    cursor: str | None = None,
    newer_than_id: int | None = None,
) -> ListPage[dict[str, Any]]:
    """파생 테마 catalog를 mapping watermark 기준의 안정적인 page로 반환한다."""
    await ensure_repeatable_read(session)
    fingerprint = filter_fingerprint(scope="themes-v1", sort="default", filters={})
    decoded = (
        decode_cursor(cursor, fingerprint=fingerprint, key_count=4)
        if cursor
        else None
    )
    if decoded is not None and not (
        1 <= decoded.snapshot_id <= MAX_DB_INTEGER_ID
        and type(decoded.keys[0]) is int
        and decoded.keys[0] in _THEME_KIND_ORDER.values()
        and type(decoded.keys[1]) is int
        and -MAX_DB_INTEGER_ID <= decoded.keys[1] <= -1
        and isinstance(decoded.keys[2], str)
        and len(decoded.keys[2]) <= 512
        and isinstance(decoded.keys[3], str)
        and len(decoded.keys[3]) <= 512
    ):
        raise ValueError("유효하지 않은 테마 목록 cursor입니다")

    if decoded is None:
        snapshot_id = int(
            await session.scalar(
                select(func.max(VideoPlaceMapping.id))
                .select_from(VideoPlaceMapping)
                .join(
                    YoutubeVideo,
                    VideoPlaceMapping.video_id == YoutubeVideo.video_id,
                    isouter=True,
                )
                .where(
                    or_(
                        YoutubeVideo.channel_id.isnot(None),
                        YoutubeVideo.source_search_query.isnot(None),
                        VideoPlaceMapping.source_playlist_id.isnot(None),
                    )
                )
            )
            or 0
        )
        items = await _theme_items(session, max_mapping_id=snapshot_id)
    else:
        snapshot_id = decoded.snapshot_id
        items = await _theme_items(session, max_mapping_id=snapshot_id)

    newer_than = 0
    if newer_than_id is not None:
        current_items = await _theme_items(session)
        newer_than = sum(
            1
            for item in current_items
            if int(item["first_mapping_id"]) > newer_than_id
        )
    total = len(items)
    if decoded is not None:
        items = [item for item in items if _theme_sort_key(item) > decoded.keys]
    page_rows = items[: limit + 1]
    has_more = len(page_rows) > limit
    page_items = page_rows[:limit]
    next_cursor = (
        encode_cursor(
            fingerprint=fingerprint,
            snapshot_id=snapshot_id,
            keys=_theme_sort_key(page_items[-1]),
        )
        if has_more and page_items
        else None
    )
    return ListPage(
        items=page_items,
        next_cursor=next_cursor,
        has_more=has_more,
        total=total,
        newest_id=snapshot_id or None,
        newer_than=newer_than,
    )


async def get_theme_places(
    session: AsyncSession, *, kind: ThemeKind, value: str
) -> dict[str, Any]:
    """테마(유튜버/재생목록/보정 검색어) 하나의 확정 POI 목록."""
    filters: dict[str, str] = {}
    if kind == "channel":
        filters["channel_id"] = value
    elif kind == "playlist":
        filters["playlist_id"] = value
    elif kind == "keyword":
        filters["keyword"] = value
    else:  # pragma: no cover - 라우터 pattern이 먼저 막는다.
        raise ValueError(f"지원하지 않는 테마 종류: {kind}")

    summaries = await place_service.list_place_summaries(
        session, sort="mention_count", limit=None, **filters
    )
    return {
        "theme": {
            "kind": kind,
            "value": value,
            "poi_count": len(summaries),
        },
        "places": [_theme_place_payload(summary) for summary in summaries],
    }


async def get_video_theme_places(
    session: AsyncSession, *, video_id: str
) -> dict[str, Any]:
    """특정 동영상을 테마로 한 확정 POI 목록.

    매치/검수 완료된 POI가 `VIDEO_THEME_MIN_POIS`개 이상일 때에만 `places`를 채운다.
    미만이면 `sufficient=false`와 함께 빈 목록을 반환한다(정책상 미공개, 이유 노출).
    """
    summaries = await place_service.list_place_summaries(
        session, sort="mention_count", limit=None, video_id=video_id
    )
    poi_count = len(summaries)
    sufficient = poi_count >= VIDEO_THEME_MIN_POIS
    video = await session.get(YoutubeVideo, video_id)
    return {
        "theme": {
            "kind": "video",
            "value": video_id,
            "title": video.title if video is not None else None,
            "poi_count": poi_count,
        },
        "min_required": VIDEO_THEME_MIN_POIS,
        "sufficient": sufficient,
        "places": (
            [_theme_place_payload(summary) for summary in summaries]
            if sufficient
            else []
        ),
    }
