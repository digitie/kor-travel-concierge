"""백엔드 pytest 공용 픽스처."""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from geoalchemy2.elements import WKTElement
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from app.core.spatial import ensure_postgis_extension
from app.models import Base, TravelPlace, YoutubeChannel, YoutubeVideo


def _has_identity_or_row(session, model, key) -> bool:
    pk_name = model.__mapper__.primary_key[0].key
    for obj in list(session.new) + list(session.identity_map.values()):
        if isinstance(obj, model) and getattr(obj, pk_name) == key:
            return True
    with session.no_autoflush:
        return session.get(model, key) is not None


@event.listens_for(Session, "before_flush")
def _ensure_postgis_test_stubs(session, flush_context, instances):
    """직접 시드한 테스트 row를 실제 PostGIS/FK 계약에 맞춘다."""
    for obj in session.new:
        if (
            isinstance(obj, TravelPlace)
            and obj.geom is None
            and obj.latitude is not None
            and obj.longitude is not None
        ):
            obj.geom = WKTElement(f"POINT({obj.longitude} {obj.latitude})", srid=4326)

    missing: dict[str, str] = {}
    for obj in session.new:
        if isinstance(obj, YoutubeVideo) and obj.channel_id:
            missing[obj.channel_id] = obj.channel_name or obj.channel_id
    if not missing:
        return
    for channel_id, title in missing.items():
        if not _has_identity_or_row(session, YoutubeChannel, channel_id):
            session.add(YoutubeChannel(channel_id=channel_id, title=title))


@pytest_asyncio.fixture
async def engine():
    """테스트용 disposable PostgreSQL/PostGIS 엔진."""
    dsn = os.getenv("TRIPMATE_AGENT_TEST_PG_DSN")
    if not dsn:
        pytest.skip("TRIPMATE_AGENT_TEST_PG_DSN이 없어 PostGIS DB 테스트를 건너뜁니다.")
    eng = create_async_engine(dsn, pool_pre_ping=True)
    async with eng.begin() as conn:
        await ensure_postgis_extension(conn)
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def session(session_factory):
    async with session_factory() as s:
        yield s
