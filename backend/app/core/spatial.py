"""PostGIS 공간 helper."""

from __future__ import annotations

from sqlalchemy import text


async def ensure_postgis_extension(conn) -> None:
    """현재 DB에 PostGIS 확장을 멱등 준비한다."""
    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))


async def sync_place_geometry(conn, place_id: int, lat: float, lng: float) -> None:
    """단일 장소의 PostGIS geom을 lat/lng로부터 동기화한다.

    좌표는 EPSG:4326 경도/위도 순서(always_xy)로 `ST_MakePoint`에 전달한다.
    """
    await conn.execute(
        text(
            "UPDATE travel_places "
            "SET geom = ST_SetSRID(ST_MakePoint(:lng, :lat), 4326) "
            "WHERE place_id = :pid;"
        ),
        {"lng": lng, "lat": lat, "pid": place_id},
    )
