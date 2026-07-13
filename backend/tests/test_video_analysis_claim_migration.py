"""T-184 영상 분석 claim 소유권 migration 회귀."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Integer, String, text

from ktc.models.youtube_video_analysis_run import YoutubeVideoAnalysisRun


_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_PATH = (
    _ROOT
    / "backend"
    / "alembic"
    / "versions"
    / "20260713_0027_video_analysis_claim_fence.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "test_video_analysis_claim_migration_0027",
        _MIGRATION_PATH,
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


async def _column_names(connection) -> set[str]:
    return set(
        (
            await connection.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'youtube_video_analysis_runs'
                    """
                )
            )
        ).scalars()
    )


def test_video_analysis_claim_model_contract() -> None:
    table = YoutubeVideoAnalysisRun.__table__
    owner = table.c.owner_crawl_run_id
    assert isinstance(owner.type, Integer)
    assert owner.nullable is True
    owner_fk = next(iter(owner.foreign_keys))
    assert owner_fk.target_fullname == "crawl_runs.id"
    assert owner_fk.ondelete == "SET NULL"
    assert isinstance(table.c.owner_retry_count.type, Integer)
    assert table.c.owner_retry_count.nullable is True
    assert isinstance(table.c.claim_token.type, String)
    assert table.c.claim_token.type.length == 36
    assert table.c.claim_token.nullable is True


async def test_video_analysis_claim_migration_round_trip(engine) -> None:
    migration = _load_migration()
    assert migration.revision == "20260713_0027"
    assert migration.down_revision == "20260713_0026"
    claim_columns = {
        "owner_crawl_run_id",
        "owner_retry_count",
        "claim_token",
    }

    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: _run_migration(
                sync_connection,
                migration,
                "downgrade",
            )
        )
        assert claim_columns.isdisjoint(await _column_names(connection))

        await connection.run_sync(
            lambda sync_connection: _run_migration(
                sync_connection,
                migration,
                "upgrade",
            )
        )
        assert claim_columns <= await _column_names(connection)

        delete_rule = (
            await connection.execute(
                text(
                    """
                    SELECT delete_rule
                    FROM information_schema.referential_constraints
                    WHERE constraint_schema = current_schema()
                      AND constraint_name =
                          'fk_youtube_video_analysis_runs_owner_crawl_run_id'
                    """
                )
            )
        ).scalar_one()
        assert delete_rule == "SET NULL"
        index_definition = (
            await connection.execute(
                text(
                    """
                    SELECT indexdef
                    FROM pg_indexes
                    WHERE schemaname = current_schema()
                      AND tablename = 'youtube_video_analysis_runs'
                      AND indexname =
                          'ix_youtube_video_analysis_runs_owner_crawl_run_id'
                    """
                )
            )
        ).scalar_one()
        assert "(owner_crawl_run_id)" in index_definition

        await connection.run_sync(
            lambda sync_connection: _run_migration(
                sync_connection,
                migration,
                "downgrade",
            )
        )
        assert claim_columns.isdisjoint(await _column_names(connection))
        await connection.run_sync(
            lambda sync_connection: _run_migration(
                sync_connection,
                migration,
                "upgrade",
            )
        )
