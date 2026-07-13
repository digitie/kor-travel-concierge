"""PostgreSQL/PostGIS 비동기 데이터베이스 세션 관리."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncConnection,
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
DATABASE_BOOTSTRAP_ADVISORY_LOCK_ID = 176


async def ensure_candidate_place_revision_triggers(
    connection: AsyncConnection,
) -> None:
    """`create_all` bootstrap DB에도 0026 revision trigger 계약을 설치한다.

    운영 DB는 Alembic 0026이 같은 이름의 함수·trigger를 소유한다. local/test/e2e의 빈
    DB는 `create_all`로 테이블을 만들기 때문에, 그 뒤 이 helper를 실행해야 실제 실행과
    테스트에서도 모든 candidate/place UPDATE가 DB 소유 revision을 정확히 1 올린다.
    """
    await connection.exec_driver_sql(
        f"SELECT pg_advisory_xact_lock({DATABASE_BOOTSTRAP_ADVISORY_LOCK_ID})"
    )
    candidate_revision_exists = bool(
        (
            await connection.exec_driver_sql(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'extracted_place_candidates'
                      AND column_name = 'state_revision'
                )
                """
            )
        ).scalar()
    )
    place_revision_exists = bool(
        (
            await connection.exec_driver_sql(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'travel_places'
                      AND column_name = 'state_revision'
                )
                """
            )
        ).scalar()
    )
    if not candidate_revision_exists or not place_revision_exists:
        raise RuntimeError(
            "candidate/place state_revision 컬럼이 없습니다. 0026 downgrade schema는 "
            "create_all로 복구할 수 없으므로 DB를 재생성하거나 Alembic head로 "
            "upgrade해야 합니다."
        )
    await connection.exec_driver_sql(
        """
        CREATE OR REPLACE FUNCTION ktc_0026_bump_state_revision()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.state_revision := OLD.state_revision + 1;
            RETURN NEW;
        END;
        $$
        """
    )
    await connection.exec_driver_sql(
        "DROP TRIGGER IF EXISTS trg_epc_bump_state_revision "
        "ON extracted_place_candidates"
    )
    await connection.exec_driver_sql(
        """
        CREATE TRIGGER trg_epc_bump_state_revision
        BEFORE UPDATE ON extracted_place_candidates
        FOR EACH ROW
        EXECUTE FUNCTION ktc_0026_bump_state_revision()
        """
    )
    await connection.exec_driver_sql(
        "DROP TRIGGER IF EXISTS trg_travel_places_bump_state_revision "
        "ON travel_places"
    )
    await connection.exec_driver_sql(
        """
        CREATE TRIGGER trg_travel_places_bump_state_revision
        BEFORE UPDATE ON travel_places
        FOR EACH ROW
        EXECUTE FUNCTION ktc_0026_bump_state_revision()
        """
    )


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 의존성으로 사용할 async 세션 제너레이터."""
    async with async_session_factory() as session:
        yield session


async def get_repeatable_read_session() -> AsyncIterator[AsyncSession]:
    """여러 SELECT로 한 목록 envelope를 만드는 전용 읽기 session.

    인증 dependency의 `get_session`과 callable을 분리해 FastAPI request cache가 같은
    session을 공유하지 않게 한다. 따라서 공개 API key cache가 DB를 먼저 읽더라도 목록
    transaction은 항상 첫 statement 전 `REPEATABLE READ`로 시작한다.
    """
    async with async_session_factory() as session:
        await session.connection(
            execution_options={"isolation_level": "REPEATABLE READ"}
        )
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
        # backend와 MCP가 같은 빈 local DB에서 동시에 기동해 create_all/trigger DDL을
        # 경합하지 않도록 bootstrap 전체를 transaction advisory lock으로 직렬화한다.
        await conn.exec_driver_sql(
            f"SELECT pg_advisory_xact_lock({DATABASE_BOOTSTRAP_ADVISORY_LOCK_ID})"
        )
        await ensure_postgis_extension(conn)
        if settings.is_local_env:
            await conn.run_sync(Base.metadata.create_all)
            await ensure_candidate_place_revision_triggers(conn)
        else:
            logging.getLogger(__name__).info(
                "비-local 환경(APP_ENV=%s): create_all을 건너뛴다. 운영 schema는 "
                "Alembic 마이그레이션이 소유한다.",
                settings.APP_ENV,
            )
