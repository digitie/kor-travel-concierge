"""장소 조회 및 근접 중복 후보 탐색 서비스 (저장소 계층).

공간 함수 호출을 이 계층에 캡슐화해, SpatiaLite → PostGIS 전환 시 호출부를
바꾸지 않아도 되게 한다(ADR-12·ADR-17).

근접 탐색은 두 단계로 한다.
    1. lat/lng 인덱스에 푸시다운하는 경위도 bounding box로 후보를 좁힌다.
    2. Haversine 거리로 정밀 필터링한다.
SpatiaLite/PostGIS 환경에서는 동일 인터페이스를 `ST_DWithin`/`PtDistWithin`으로
대체할 수 있다.
"""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.spatial import sync_place_geometry
from app.models import (
    MatchStatus,
    ExtractedPlaceCandidate,
    MediaAsset,
    TravelPlace,
    VideoPlaceMapping,
    YoutubeVideo,
    utcnow,
)

EARTH_RADIUS_M = 6_371_000.0
_DEG_LAT_METERS = 111_320.0  # 위도 1도당 미터(근사)


def haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 좌표(EPSG:4326) 간 Haversine 거리(미터)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _bounding_box(lat: float, lng: float, radius_m: float) -> tuple[float, float, float, float]:
    """반경을 포함하는 경위도 bounding box (min_lat, max_lat, min_lng, max_lng)."""
    dlat = radius_m / _DEG_LAT_METERS
    # 고위도에서 경도 1도의 거리가 줄어드는 것을 보정한다.
    cos_lat = max(math.cos(math.radians(lat)), 1e-6)
    dlng = radius_m / (_DEG_LAT_METERS * cos_lat)
    return lat - dlat, lat + dlat, lng - dlng, lng + dlng


async def find_places_within_radius(
    session: AsyncSession,
    *,
    lat: float,
    lng: float,
    radius_meters: float,
    limit: int = 20,
) -> list[tuple[TravelPlace, float]]:
    """반경 내 장소를 거리 오름차순으로 반환한다. `(place, distance_m)` 튜플."""
    min_lat, max_lat, min_lng, max_lng = _bounding_box(lat, lng, radius_meters)
    stmt = select(TravelPlace).where(
        TravelPlace.is_geocoded.is_(True),
        TravelPlace.latitude >= min_lat,
        TravelPlace.latitude <= max_lat,
        TravelPlace.longitude >= min_lng,
        TravelPlace.longitude <= max_lng,
    )
    result = await session.execute(stmt)
    scored: list[tuple[TravelPlace, float]] = []
    for place in result.scalars().all():
        dist = haversine_meters(lat, lng, place.latitude, place.longitude)
        if dist <= radius_meters:
            scored.append((place, dist))
    scored.sort(key=lambda item: item[1])
    return scored[:limit]


async def find_duplicate_candidates(
    session: AsyncSession,
    *,
    lat: float,
    lng: float,
    radius_meters: float = 100.0,
    limit: int = 5,
) -> list[tuple[TravelPlace, float]]:
    """좌표 근접성 기반 중복 의심 장소를 반환한다.

    신규 후보를 확정 장소로 승격하기 전, 같은 좌표 근방의 기존 장소를 찾아 중복
    생성을 방지하는 용도다.
    """
    return await find_places_within_radius(
        session, lat=lat, lng=lng, radius_meters=radius_meters, limit=limit
    )


async def list_places(session: AsyncSession, *, limit: int = 100) -> list[TravelPlace]:
    """확정 장소 목록을 최신순으로 조회한다."""
    stmt = select(TravelPlace).order_by(TravelPlace.place_id.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def search_places(
    session: AsyncSession,
    *,
    query: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    radius_meters: float | None = None,
    category: str | None = None,
    limit: int = 20,
) -> list[tuple[TravelPlace, float | None]]:
    """검색어·카테고리·반경 조건으로 장소를 조회한다."""
    if radius_meters is not None:
        if lat is None or lng is None:
            raise ValueError("반경 검색에는 lat/lng가 모두 필요하다")
        radius_results = await find_places_within_radius(
            session, lat=lat, lng=lng, radius_meters=radius_meters, limit=max(limit, 100)
        )
        filtered: list[tuple[TravelPlace, float | None]] = []
        needle = query.strip() if query else None
        for place, distance in radius_results:
            if category and place.category != category:
                continue
            if needle and needle not in _place_search_text(place):
                continue
            filtered.append((place, distance))
            if len(filtered) >= limit:
                break
        return filtered

    stmt = select(TravelPlace).order_by(TravelPlace.place_id.desc()).limit(limit)
    if query:
        pattern = f"%{query.strip()}%"
        stmt = stmt.where(
            or_(
                TravelPlace.name.like(pattern),
                TravelPlace.official_address.like(pattern),
                TravelPlace.road_address.like(pattern),
                TravelPlace.description.like(pattern),
            )
        )
    if category:
        stmt = stmt.where(TravelPlace.category == category)
    result = await session.execute(stmt)
    return [(place, None) for place in result.scalars().all()]


def _place_search_text(place: TravelPlace) -> str:
    return " ".join(
        value
        for value in (
            place.name,
            place.official_address,
            place.road_address,
            place.description,
            place.gemini_enriched_description,
        )
        if value
    )


async def get_place(session: AsyncSession, place_id: int) -> TravelPlace | None:
    """확정 장소 1건을 조회한다."""
    return await session.get(TravelPlace, place_id)


async def get_place_video_mappings(
    session: AsyncSession, *, place_id: int
) -> list[VideoPlaceMapping]:
    """장소와 연결된 영상 매핑을 최신순으로 조회한다."""
    stmt = (
        select(VideoPlaceMapping)
        .where(VideoPlaceMapping.place_id == place_id)
        .order_by(VideoPlaceMapping.id.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_videos_by_ids(
    session: AsyncSession, video_ids: list[str]
) -> dict[str, YoutubeVideo]:
    """video_id 목록을 영상 객체 dict로 반환한다."""
    if not video_ids:
        return {}
    stmt = select(YoutubeVideo).where(YoutubeVideo.video_id.in_(video_ids))
    result = await session.execute(stmt)
    return {video.video_id: video for video in result.scalars().all()}


async def list_candidates_for_place(
    session: AsyncSession, *, place_id: int
) -> list[ExtractedPlaceCandidate]:
    """확정 장소에 연결된 추출 후보를 조회한다."""
    stmt = (
        select(ExtractedPlaceCandidate)
        .where(ExtractedPlaceCandidate.matched_place_id == place_id)
        .order_by(ExtractedPlaceCandidate.id.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def correct_place(
    session: AsyncSession,
    *,
    place_id: int,
    updates: dict[str, Any],
    commit: bool = True,
) -> TravelPlace:
    """장소명·주소·좌표·카테고리·설명을 수동 보정한다."""
    place = await session.get(TravelPlace, place_id)
    if place is None:
        raise ValueError(f"place not found: {place_id}")

    allowed = {
        "name",
        "description",
        "gemini_enriched_description",
        "description_review_status",
        "official_address",
        "road_address",
        "latitude",
        "longitude",
        "api_source",
        "category",
        "is_geocoded",
    }
    applied = {key: value for key, value in updates.items() if key in allowed}
    if not applied:
        raise ValueError("보정할 필드가 필요하다")
    for key, value in applied.items():
        setattr(place, key, value)
    if ("latitude" in applied or "longitude" in applied) and "is_geocoded" not in applied:
        place.is_geocoded = True
    if ("latitude" in applied or "longitude" in applied) and place.is_geocoded:
        await sync_place_geometry(session, place.place_id, place.latitude, place.longitude)
    place.last_reviewed_at = utcnow()
    if commit:
        await session.commit()
        await session.refresh(place)
    return place


async def merge_places(
    session: AsyncSession,
    *,
    source_place_id: int,
    target_place_id: int,
    commit: bool = True,
) -> TravelPlace:
    """중복 장소를 병합하고 source 장소를 삭제한다."""
    if source_place_id == target_place_id:
        raise ValueError("source_place_id와 target_place_id는 달라야 한다")

    source = await session.get(TravelPlace, source_place_id)
    target = await session.get(TravelPlace, target_place_id)
    if source is None:
        raise ValueError(f"source place not found: {source_place_id}")
    if target is None:
        raise ValueError(f"target place not found: {target_place_id}")

    mapping_result = await session.execute(
        select(VideoPlaceMapping).where(VideoPlaceMapping.place_id == source_place_id)
    )
    moved_mappings = list(mapping_result.scalars().all())
    for mapping in moved_mappings:
        mapping.place_id = target_place_id

    candidate_result = await session.execute(
        select(ExtractedPlaceCandidate).where(
            ExtractedPlaceCandidate.matched_place_id == source_place_id
        )
    )
    moved_candidates = list(candidate_result.scalars().all())
    for candidate in moved_candidates:
        candidate.matched_place_id = target_place_id

    asset_result = await session.execute(
        select(MediaAsset).where(MediaAsset.place_id == source_place_id)
    )
    moved_assets = list(asset_result.scalars().all())
    for asset in moved_assets:
        asset.place_id = target_place_id

    for field in (
        "description",
        "gemini_enriched_description",
        "official_address",
        "road_address",
        "api_source",
        "category",
        "detailed_research_content",
    ):
        if not getattr(target, field) and getattr(source, field):
            setattr(target, field, getattr(source, field))
    target.last_reviewed_at = utcnow()
    await session.delete(source)
    if commit:
        await session.commit()
        await session.refresh(target)
    return target


async def review_candidate(
    session: AsyncSession,
    *,
    candidate_id: int,
    reviewed_by: str,
    review_note: str | None = None,
    commit: bool = True,
) -> ExtractedPlaceCandidate:
    """매칭 검수 후보에 검수 메타데이터를 남긴다."""
    candidate = await session.get(ExtractedPlaceCandidate, candidate_id)
    if candidate is None:
        raise ValueError(f"candidate not found: {candidate_id}")
    candidate.reviewed_by = reviewed_by
    candidate.reviewed_at = utcnow()
    candidate.review_note = review_note
    if commit:
        await session.commit()
        await session.refresh(candidate)
    return candidate


async def resolve_candidate(
    session: AsyncSession,
    *,
    candidate_id: int,
    action: str,
    reviewed_by: str,
    review_note: str | None = None,
    place_id: int | None = None,
    place_data: dict[str, Any] | None = None,
    commit: bool = True,
) -> tuple[ExtractedPlaceCandidate, TravelPlace | None, VideoPlaceMapping | None]:
    """매칭 실패 후보를 기존 장소, 신규 장소, 제외 중 하나로 해결한다."""
    candidate = await session.get(ExtractedPlaceCandidate, candidate_id)
    if candidate is None:
        raise ValueError(f"candidate not found: {candidate_id}")

    place: TravelPlace | None = None
    mapping: VideoPlaceMapping | None = None
    if action == "ignore":
        candidate.match_status = MatchStatus.IGNORED
    elif action == "match_existing":
        if place_id is None:
            raise ValueError("기존 장소 매칭에는 place_id가 필요하다")
        place = await session.get(TravelPlace, place_id)
        if place is None:
            raise ValueError(f"place not found: {place_id}")
        candidate.match_status = MatchStatus.USER_CORRECTED
        candidate.matched_place_id = place.place_id
        mapping = await _ensure_candidate_mapping(session, candidate, place)
    elif action == "create_place":
        data = place_data or {}
        required = ("name", "latitude", "longitude")
        missing = [key for key in required if data.get(key) is None]
        if missing:
            raise ValueError(f"신규 장소 생성에는 {', '.join(missing)} 값이 필요하다")
        place = TravelPlace(
            name=data["name"],
            description=data.get("description"),
            gemini_enriched_description=data.get("gemini_enriched_description"),
            official_address=data.get("official_address"),
            road_address=data.get("road_address"),
            latitude=data["latitude"],
            longitude=data["longitude"],
            api_source=data.get("api_source") or "manual",
            category=data.get("category") or candidate.candidate_category,
            is_geocoded=True,
            last_reviewed_at=utcnow(),
        )
        session.add(place)
        await session.flush()
        await sync_place_geometry(session, place.place_id, place.latitude, place.longitude)
        candidate.match_status = MatchStatus.USER_CORRECTED
        candidate.matched_place_id = place.place_id
        mapping = await _ensure_candidate_mapping(session, candidate, place)
    else:
        raise ValueError(f"지원하지 않는 후보 해결 action: {action}")

    candidate.reviewed_by = reviewed_by
    candidate.reviewed_at = utcnow()
    candidate.review_note = review_note
    if commit:
        await session.commit()
        await session.refresh(candidate)
        if place is not None:
            await session.refresh(place)
        if mapping is not None:
            await session.refresh(mapping)
    return candidate, place, mapping


async def _ensure_candidate_mapping(
    session: AsyncSession,
    candidate: ExtractedPlaceCandidate,
    place: TravelPlace,
) -> VideoPlaceMapping:
    stmt = select(VideoPlaceMapping).where(
        VideoPlaceMapping.video_id == candidate.video_id,
        VideoPlaceMapping.place_candidate_id == candidate.id,
    )
    result = await session.execute(stmt)
    mapping = result.scalars().first()
    if mapping is None:
        mapping = VideoPlaceMapping(
            video_id=candidate.video_id,
            place_id=place.place_id,
            place_candidate_id=candidate.id,
            ai_summary=candidate.source_text,
            speaker_note=candidate.speaker_note,
            timestamp_start=candidate.timestamp_start,
            timestamp_end=candidate.timestamp_end,
        )
        session.add(mapping)
        await session.flush()
    else:
        mapping.place_id = place.place_id
    return mapping


async def list_unmatched_candidates(
    session: AsyncSession, *, limit: int = 100
) -> list[ExtractedPlaceCandidate]:
    """`needs_review` 상태의 매칭 실패 후보를 조회한다."""
    stmt = (
        select(ExtractedPlaceCandidate)
        .where(ExtractedPlaceCandidate.match_status == MatchStatus.NEEDS_REVIEW)
        .order_by(ExtractedPlaceCandidate.id.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
