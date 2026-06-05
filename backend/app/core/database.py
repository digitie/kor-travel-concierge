"""비동기 데이터베이스 세션 및 SpatiaLite 초기화 (스캐폴드).

SQLAlchemy 2.0 + `aiosqlite` 기반 async 엔진을 구성하고, SpatiaLite 확장 로드와
WAL 모드 설정 지점을 정의한다. 실제 모델 메타데이터 생성과 공간 인덱스 구성은
T-004/T-005에서 채운다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


def _enable_spatialite(dbapi_connection, _connection_record) -> None:
    """SQLite 연결마다 SpatiaLite 확장과 WAL 모드를 적용한다.

    `aiosqlite` 동기 핸들에 직접 접근하므로 blocking 호출이다. SQLAlchemy
    `connect` 이벤트 안에서만 실행되며, 일반 쿼리 경로는 async를 유지한다.
    """
    settings = get_settings()
    dbapi_connection.enable_load_extension(True)
    try:
        dbapi_connection.load_extension(settings.SPATIALITE_EXTENSION_PATH)
    except Exception:
        # 개발 환경에 mod_spatialite가 없을 수 있으므로 스캐폴드 단계에서는 무시한다.
        # T-005에서 확장 부재를 명시적 오류로 승격한다.
        pass
    finally:
        dbapi_connection.enable_load_extension(False)
    if settings.SQLITE_WAL_ENABLED:
        dbapi_connection.execute("PRAGMA journal_mode=WAL;")


def create_engine() -> AsyncEngine:
    """설정 기반 async 엔진을 생성한다."""
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False, future=True)
    # async 엔진의 sync 코어에 connect 리스너를 등록한다.
    event.listen(engine.sync_engine, "connect", _enable_spatialite)
    return engine


engine: AsyncEngine = create_engine()
async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 의존성으로 사용할 async 세션 제너레이터."""
    async with async_session_factory() as session:
        yield session


async def init_spatial_metadata() -> None:
    """SpatiaLite 메타데이터 테이블을 초기화한다 (최초 1회).

    실제 호출은 T-005 모델 구현 이후 애플리케이션 lifespan에서 수행한다.
    """
    async with engine.begin() as conn:
        await conn.execute(text("SELECT InitSpatialMetaData(1);"))
