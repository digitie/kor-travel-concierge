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
    if hasattr(dbapi_connection, "run_async"):
        dbapi_connection.run_async(lambda conn: conn.enable_load_extension(True))
        try:
            dbapi_connection.run_async(
                lambda conn: conn.load_extension(settings.SPATIALITE_EXTENSION_PATH)
            )
        except Exception:
            # 개발 환경에 mod_spatialite가 없을 수 있으므로 graceful하게 건너뛴다.
            pass
        finally:
            dbapi_connection.run_async(lambda conn: conn.enable_load_extension(False))
    else:
        dbapi_connection.enable_load_extension(True)
        try:
            dbapi_connection.load_extension(settings.SPATIALITE_EXTENSION_PATH)
        except Exception:
            # 개발 환경에 mod_spatialite가 없을 수 있으므로 graceful하게 건너뛴다.
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


async def init_spatial_metadata(conn) -> None:
    """SpatiaLite 메타데이터 테이블을 초기화한다 (최초 1회, 멱등).

    `mod_spatialite`가 로드되지 않은 환경(개발용 일부 OS)에서는 조용히 건너뛴다.
    공간 컬럼/인덱스 구성은 T-005에서 보강한다.
    """
    try:
        existing = await conn.execute(
            text(
                "SELECT count(*) FROM sqlite_master "
                "WHERE type = 'table' AND name = 'spatial_ref_sys';"
            )
        )
        if existing.scalar_one() > 0:
            return
        await conn.execute(text("SELECT InitSpatialMetaData(1);"))
    except Exception:
        # 확장 미로드 환경에서는 공간 메타데이터 초기화를 건너뛴다.
        pass


async def init_db() -> None:
    """모든 ORM 테이블을 생성한다 (없을 때만).

    애플리케이션 lifespan 시작 시 호출한다. SQLite + SpatiaLite 기준으로 공통
    작업/감사/설정 테이블을 만들고, SpatiaLite 메타데이터를 초기화한다.
    """
    # 등록된 모든 모델 메타데이터를 로드한다.
    from app.core.spatial import ensure_geometry_columns
    from app.models import Base  # 지연 import로 순환 의존 회피

    async with engine.begin() as conn:
        await init_spatial_metadata(conn)
        await conn.run_sync(Base.metadata.create_all)
        # travel_places.geom Point(4326)와 R-Tree 인덱스 구성 (SpatiaLite 가용 시)
        await ensure_geometry_columns(conn)
