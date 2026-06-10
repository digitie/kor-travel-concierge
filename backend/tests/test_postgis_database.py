"""PostgreSQL/PostGIS bootstrap 테스트."""

from __future__ import annotations

from sqlalchemy import text

from app.core.spatial import ensure_postgis_extension, sync_place_geometry
from app.models import TravelPlace


def test_travel_place_declares_postgis_geometry():
    geom_type = TravelPlace.__table__.c.geom.type

    assert geom_type.geometry_type == "POINT"
    assert geom_type.srid == 4326


async def test_postgis_extension_and_geometry_sync(engine, session_factory):
    async with engine.begin() as conn:
        await ensure_postgis_extension(conn)

    async with session_factory() as session:
        place = TravelPlace(
            name="월정리 해변",
            latitude=33.5563,
            longitude=126.7958,
            is_geocoded=True,
        )
        session.add(place)
        await session.flush()
        await sync_place_geometry(session, place.place_id, place.latitude, place.longitude)
        await session.commit()

        result = await session.execute(
            text(
                """
                SELECT
                    ST_SRID(geom) AS srid,
                    round(ST_X(geom)::numeric, 4) AS lng,
                    round(ST_Y(geom)::numeric, 4) AS lat
                FROM travel_places
                WHERE place_id = :place_id
                """
            ),
            {"place_id": place.place_id},
        )
        row = result.one()

    assert row.srid == 4326
    assert float(row.lng) == 126.7958
    assert float(row.lat) == 33.5563
