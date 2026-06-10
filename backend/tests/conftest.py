"""백엔드 pytest 공용 픽스처."""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.spatial import ensure_postgis_extension
from app.models import Base


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
