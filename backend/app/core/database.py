"""비동기 데이터베이스 세션 및 SpatiaLite 초기화 (스캐폴드).

SQLAlchemy 2.0 + `aiosqlite` 기반 async 엔진을 구성하고, SpatiaLite 확장 로드와
WAL 모드 설정 지점을 정의한다. 실제 모델 메타데이터 생성과 공간 인덱스 구성은
T-004/T-005에서 채운다.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

logger = logging.getLogger(__name__)
SchemaMigration = tuple[str, Callable[[Any], Awaitable[None]]]


def _enable_spatialite(dbapi_connection, _connection_record) -> None:
    """SQLite 연결마다 SpatiaLite 확장과 WAL 모드를 적용한다.

    `aiosqlite` 동기 핸들에 직접 접근하므로 blocking 호출이다. SQLAlchemy
    `connect` 이벤트 안에서만 실행되며, 일반 쿼리 경로는 async를 유지한다.
    """
    settings = get_settings()
    dbapi_connection.execute("PRAGMA foreign_keys=ON;")
    dbapi_connection.execute("PRAGMA busy_timeout=5000;")
    if hasattr(dbapi_connection, "run_async"):
        dbapi_connection.run_async(lambda conn: conn.enable_load_extension(True))
        try:
            dbapi_connection.run_async(
                lambda conn: conn.load_extension(settings.SPATIALITE_EXTENSION_PATH)
            )
        except Exception as exc:
            # 개발 환경에 mod_spatialite가 없을 수 있으므로 graceful하게 건너뛴다.
            logger.debug("SpatiaLite 확장을 로드하지 못해 공간 DDL을 건너뜁니다: %s", exc)
        finally:
            dbapi_connection.run_async(lambda conn: conn.enable_load_extension(False))
    else:
        dbapi_connection.enable_load_extension(True)
        try:
            dbapi_connection.load_extension(settings.SPATIALITE_EXTENSION_PATH)
        except Exception as exc:
            # 개발 환경에 mod_spatialite가 없을 수 있으므로 graceful하게 건너뛴다.
            logger.debug("SpatiaLite 확장을 로드하지 못해 공간 DDL을 건너뜁니다: %s", exc)
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
    except Exception as exc:
        # 확장 미로드 환경에서는 공간 메타데이터 초기화를 건너뛴다.
        logger.debug("SpatiaLite 메타데이터 초기화를 건너뜁니다: %s", exc)


async def ensure_crawl_run_status_columns(conn) -> None:
    """기존 SQLite DB에 작업 상태 메시지·로그 컬럼을 보강한다."""
    result = await conn.execute(text("PRAGMA table_info(crawl_runs);"))
    existing_columns = {row[1] for row in result.fetchall()}
    if not existing_columns:
        return
    if "current_message" not in existing_columns:
        await conn.execute(text("ALTER TABLE crawl_runs ADD COLUMN current_message TEXT;"))
    if "status_log_json" not in existing_columns:
        await conn.execute(text("ALTER TABLE crawl_runs ADD COLUMN status_log_json TEXT;"))


async def ensure_video_place_mapping_repeatable(conn) -> None:
    """기존 SQLite DB에 남은 영상-장소 unique 제약을 제거한다.

    T-028에서 같은 영상의 같은 장소가 여러 구간에 반복 등장하는 것을 보존하도록
    모델 제약을 제거했다. 기존 DB가 table-level UNIQUE constraint로 생성된
    경우 SQLite는 autoindex를 직접 DROP할 수 없으므로 현재 스키마로 테이블을
    재생성한다.
    """
    table_result = await conn.execute(
        text(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'video_place_mappings';"
        )
    )
    table_sql = table_result.scalar_one_or_none()
    if not table_sql:
        return

    # 일부 개발 DB는 UniqueConstraint가 아니라 명시 index 형태로 남아 있을 수 있다.
    await conn.execute(text("DROP INDEX IF EXISTS uq_video_place_mappings_video_place;"))

    normalized_sql = " ".join(str(table_sql).split()).lower()
    has_legacy_constraint = (
        "uq_video_place_mappings_video_place" in normalized_sql
        or "unique (video_id, place_id)" in normalized_sql
        or "unique(video_id, place_id)" in normalized_sql
    )
    if not has_legacy_constraint:
        return

    await conn.execute(
        text("ALTER TABLE video_place_mappings RENAME TO video_place_mappings_legacy;")
    )
    await conn.execute(
        text(
            """
            CREATE TABLE video_place_mappings (
                id INTEGER NOT NULL,
                video_id VARCHAR(32) NOT NULL,
                place_id INTEGER NOT NULL,
                place_candidate_id INTEGER,
                ai_summary TEXT NOT NULL,
                speaker_note TEXT,
                timestamp_start VARCHAR(16),
                timestamp_end VARCHAR(16),
                frame_asset_id INTEGER,
                created_at DATETIME NOT NULL,
                PRIMARY KEY (id),
                FOREIGN KEY(video_id) REFERENCES youtube_videos (video_id),
                FOREIGN KEY(place_id) REFERENCES travel_places (place_id),
                FOREIGN KEY(place_candidate_id) REFERENCES extracted_place_candidates (id),
                FOREIGN KEY(frame_asset_id) REFERENCES media_assets (id)
            );
            """
        )
    )
    await conn.execute(
        text(
            """
            INSERT INTO video_place_mappings (
                id,
                video_id,
                place_id,
                place_candidate_id,
                ai_summary,
                speaker_note,
                timestamp_start,
                timestamp_end,
                frame_asset_id,
                created_at
            )
            SELECT
                id,
                video_id,
                place_id,
                place_candidate_id,
                ai_summary,
                speaker_note,
                timestamp_start,
                timestamp_end,
                frame_asset_id,
                created_at
            FROM video_place_mappings_legacy;
            """
        )
    )
    await conn.execute(text("DROP TABLE video_place_mappings_legacy;"))
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_video_place_mappings_video_id "
            "ON video_place_mappings (video_id);"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_video_place_mappings_place_id "
            "ON video_place_mappings (place_id);"
        )
    )


async def ensure_schema_migrations_table(conn) -> None:
    """적용한 경량 schema migration id를 기록할 테이블을 만든다."""
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id TEXT PRIMARY KEY,
                applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
    )


SCHEMA_MIGRATIONS: tuple[SchemaMigration, ...] = (
    ("20260608_001_crawl_run_status_columns", ensure_crawl_run_status_columns),
    ("20260608_002_video_place_mapping_repeatable", ensure_video_place_mapping_repeatable),
)


async def run_schema_migrations(
    conn,
    *,
    migrations: Sequence[SchemaMigration] = SCHEMA_MIGRATIONS,
) -> None:
    """기존 SQLite DB 보정 migration을 한 번씩 적용한다."""
    await ensure_schema_migrations_table(conn)
    result = await conn.execute(text("SELECT id FROM schema_migrations;"))
    applied = {row[0] for row in result.fetchall()}
    for migration_id, migration in migrations:
        if migration_id in applied:
            continue
        await migration(conn)
        await conn.execute(
            text("INSERT INTO schema_migrations (id) VALUES (:migration_id);"),
            {"migration_id": migration_id},
        )
        applied.add(migration_id)


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
        await run_schema_migrations(conn)
        # travel_places.geom Point(4326)와 R-Tree 인덱스 구성 (SpatiaLite 가용 시)
        await ensure_geometry_columns(conn)
