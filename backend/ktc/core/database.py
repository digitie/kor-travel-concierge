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
    """PostGIS 확장과 ORM 테이블을 준비한다.

    운영 schema 이력은 Alembic이 단독 소유한다. `create_all`은 비멱등 마이그레이션과
    충돌할 수 있다(create_all이 먼저 테이블을 만들면 이후 `alembic upgrade`의
    `op.create_table`이 "relation already exists"로 실패). 따라서 빈 DB를 바로 띄우는
    bootstrap 용도로 local/test/e2e에서만 `create_all`을 실행하고, 비-local(운영)에서는
    PostGIS 확장만 보장한 뒤 스키마 생성·이력은 Alembic에 위임한다.
    """
    import logging

    # 등록된 모든 모델 메타데이터를 로드한다.
    from ktc.core.spatial import ensure_postgis_extension
    from ktc.models import Base  # 지연 import로 순환 의존 회피

    settings = get_settings()
    async with engine.begin() as conn:
        await ensure_postgis_extension(conn)
        if settings.is_local_env:
            await conn.run_sync(Base.metadata.create_all)
        else:
            logging.getLogger(__name__).info(
                "비-local 환경(APP_ENV=%s): create_all을 건너뛴다. 운영 schema는 "
                "Alembic 마이그레이션이 소유한다.",
                settings.APP_ENV,
            )
