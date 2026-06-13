"""PostgreSQL/PostGIS 비동기 데이터베이스 세션 관리."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ktc.core.config import get_settings


def create_engine() -> AsyncEngine:
    """설정 기반 async 엔진을 생성한다."""
    settings = get_settings()
    return create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        future=True,
        pool_pre_ping=True,
    )


engine: AsyncEngine = create_engine()
async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 의존성으로 사용할 async 세션 제너레이터."""
    async with async_session_factory() as session:
        yield session


async def init_db() -> None:
    """PostGIS 확장과 ORM 테이블을 멱등 준비한다.

    운영 schema 이력은 Alembic이 소유한다. 이 함수는 로컬/테스트 초기 구동 시 빈
    DB를 바로 띄울 수 있게 하는 최소 bootstrap이다.
    """
    # 등록된 모든 모델 메타데이터를 로드한다.
    from ktc.core.spatial import ensure_postgis_extension
    from ktc.models import Base  # 지연 import로 순환 의존 회피

    async with engine.begin() as conn:
        await ensure_postgis_extension(conn)
        await conn.run_sync(Base.metadata.create_all)
