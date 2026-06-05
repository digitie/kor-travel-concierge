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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MatchStatus, ExtractedPlaceCandidate, TravelPlace

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
