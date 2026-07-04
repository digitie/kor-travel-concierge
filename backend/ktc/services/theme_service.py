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

from sqlalchemy.ext.asyncio import AsyncSession

from ktc.models import YoutubeVideo
from ktc.services import place_service

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


async def list_themes(session: AsyncSession) -> dict[str, Any]:
    """공급 가능한 테마 목록(유튜버/재생목록/보정 검색어)과 각 테마의 확정 POI 수."""
    facets = await place_service.list_place_facets(session)
    return {
        "channels": [
            {"value": item["id"], "title": item["title"], "poi_count": item["place_count"]}
            for item in facets.get("channels", [])
        ],
        "playlists": [
            {"value": item["id"], "title": item["title"], "poi_count": item["place_count"]}
            for item in facets.get("playlists", [])
        ],
        "keywords": [
            {"value": item["value"], "title": item["value"], "poi_count": item["place_count"]}
            for item in facets.get("keywords", [])
        ],
    }


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
