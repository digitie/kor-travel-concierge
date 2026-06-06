"""SpatiaLite 공간 컬럼·인덱스 관리 (ORM 밖 DDL).

geoalchemy2를 도입하지 않고, `travel_places.geom`(Point 4326)과 R-Tree 공간
인덱스를 SpatiaLite DDL로 직접 관리한다(ADR-17). `mod_spatialite`가 로드되지
않은 환경에서는 모든 함수가 graceful하게 건너뛴다.

PostGIS 전환 시 이 모듈의 `ensure_geometry_columns`/`sync_place_geometry`만
교체하면 되도록 공간 함수 호출 지점을 한곳에 모은다.
"""

from __future__ import annotations

from sqlalchemy import text


async def spatialite_available(conn) -> bool:
    """현재 연결에서 SpatiaLite 함수가 사용 가능한지 확인한다."""
    try:
        await conn.execute(text("SELECT spatialite_version();"))
        return True
    except Exception:
        return False


async def ensure_geometry_columns(conn) -> bool:
    """`travel_places.geom` Point(4326)와 R-Tree 공간 인덱스를 멱등 구성한다.

    SpatiaLite 미가용 환경에서는 False를 반환하고 아무 것도 하지 않는다.
    """
    if not await spatialite_available(conn):
        return False

    # 이미 등록되어 있으면 건너뛴다.
    existing = await conn.execute(
        text(
            "SELECT count(*) FROM geometry_columns "
            "WHERE f_table_name = 'travel_places' AND f_geometry_column = 'geom';"
        )
    )
    if existing.scalar_one() > 0:
        return True

    try:
        await conn.execute(
            text(
                "SELECT AddGeometryColumn('travel_places', 'geom', 4326, 'POINT', 'XY');"
            )
        )
        await conn.execute(
            text("SELECT CreateSpatialIndex('travel_places', 'geom');")
        )
        return True
    except Exception:
        return False


async def sync_place_geometry(conn, place_id: int, lat: float, lng: float) -> None:
    """단일 장소의 geom을 lat/lng로부터 동기화한다 (SpatiaLite 가용 시).

    좌표는 EPSG:4326 경도/위도 순서(always_xy)로 MakePoint한다.
    """
    if not await spatialite_available(conn):
        return
    await conn.execute(
        text(
            "UPDATE travel_places SET geom = MakePoint(:lng, :lat, 4326) "
            "WHERE place_id = :pid;"
        ),
        {"lng": lng, "lat": lat, "pid": place_id},
    )
