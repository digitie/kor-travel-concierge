"""geocode_cache 테이블 migration(20260713_0024) round-trip 회귀."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_PATH = (
    _ROOT / "backend" / "alembic" / "versions" / "20260713_0024_geocode_cache.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "test_geocode_cache_migration_0024", _MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_migration(sync_connection, module: ModuleType, direction: str) -> None:
    operations = Operations(MigrationContext.configure(sync_connection))
    original_op = module.op
    module.op = operations
    try:
        getattr(module, direction)()
    finally:
        module.op = original_op


async def _table_exists(connection) -> bool:
    return bool(
        (
            await connection.execute(
                text(
                    """
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = current_schema()
                      AND table_name = 'geocode_cache'
                    """
                )
            )
        ).scalar()
    )


async def test_geocode_cache_migration_round_trip(engine):
    migration = _load_migration()
    async with engine.begin() as connection:
        # 테스트 metadata는 최신 head라 테이블이 이미 있다. 먼저 내려 legacy schema 재현.
        await connection.run_sync(
            lambda sc: _run_migration(sc, migration, "downgrade")
        )
        assert await _table_exists(connection) is False

        # upgrade가 테이블과 기대 컬럼을 생성한다.
        await connection.run_sync(lambda sc: _run_migration(sc, migration, "upgrade"))
        assert await _table_exists(connection) is True

        columns = {
            row.column_name: row.data_type
            for row in await connection.execute(
                text(
                    """
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'geocode_cache'
                    """
                )
            )
        }
        assert set(columns) == {
            "query_hash",
            "provider",
            "response_class",
            "results_json",
            "created_at",
        }
        assert columns["results_json"] == "jsonb"
        assert columns["created_at"] == "timestamp with time zone"

        pk_columns = {
            row.column_name
            for row in await connection.execute(
                text(
                    """
                    SELECT kcu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                     AND tc.table_schema = kcu.table_schema
                    WHERE tc.table_schema = current_schema()
                      AND tc.table_name = 'geocode_cache'
                      AND tc.constraint_type = 'PRIMARY KEY'
                    """
                )
            )
        }
        assert pk_columns == {"query_hash"}

        # downgrade로 다시 제거된다.
        await connection.run_sync(
            lambda sc: _run_migration(sc, migration, "downgrade")
        )
        assert await _table_exists(connection) is False
