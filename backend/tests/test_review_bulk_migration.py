"""T-185 durable 일괄 검수 schema/migration 회귀."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import CheckConstraint, Index, text

from ktc.models import (
    ReviewBulkOperation,
    ReviewBulkOperationItem,
    ReviewBulkOperationReceipt,
)


_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_PATH = (
    _ROOT
    / "backend"
    / "alembic"
    / "versions"
    / "20260714_0028_review_bulk_operations.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "test_review_bulk_migration_0028",
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


def test_review_bulk_model_has_count_state_and_pending_scan_constraints() -> None:
    operation_table = ReviewBulkOperation.__table__
    item_table = ReviewBulkOperationItem.__table__
    receipt_table = ReviewBulkOperationReceipt.__table__
    operation_checks = {
        constraint.name
        for constraint in operation_table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    item_checks = {
        constraint.name
        for constraint in item_table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    receipt_checks = {
        constraint.name
        for constraint in receipt_table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_review_bulk_operations_action",
        "ck_review_bulk_operations_scope_kind",
        "ck_review_bulk_operations_status",
        "ck_review_bulk_operations_counts",
        "ck_review_bulk_operations_scope_json_object",
    } <= operation_checks
    assert {
        "ck_review_bulk_operation_items_revision_positive",
        "ck_review_bulk_operation_items_review_state",
        "ck_review_bulk_operation_items_status",
        "ck_review_bulk_operation_items_attempt_count",
        "ck_review_bulk_operation_items_place_revision_pair",
    } <= item_checks
    assert "ck_review_bulk_operation_receipts_response_object" in receipt_checks
    assert set(receipt_table.primary_key.columns.keys()) == {
        "operation_id",
        "request_id",
    }
    assert receipt_table.c.request_cursor.nullable is True
    assert receipt_table.c.response_json.nullable is False
    assert {
        "last_request_id",
        "last_request_cursor",
        "last_response_json",
    }.isdisjoint(operation_table.c.keys())
    pending_index = next(
        index
        for index in item_table.indexes
        if index.name == "ix_review_bulk_operation_items_pending"
    )
    assert isinstance(pending_index, Index)
    assert pending_index.dialect_options["postgresql"]["where"] is not None
    operation_fk = next(iter(item_table.c.operation_id.foreign_keys))
    candidate_fk = next(iter(item_table.c.candidate_id.foreign_keys))
    receipt_operation_fk = next(iter(receipt_table.c.operation_id.foreign_keys))
    assert operation_fk.ondelete == "CASCADE"
    assert candidate_fk.ondelete == "NO ACTION"
    assert receipt_operation_fk.ondelete == "CASCADE"


async def test_review_bulk_migration_round_trip_and_real_indexes(engine) -> None:
    migration = _load_migration()
    assert migration.revision == "20260714_0028"
    assert migration.down_revision == "20260713_0027"

    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: _run_migration(
                sync_connection,
                migration,
                "downgrade",
            )
        )
        tables_after_down = set(
            (
                await connection.execute(
                    text(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = current_schema()
                          AND table_name LIKE 'review_bulk_operation%'
                        """
                    )
                )
            ).scalars()
        )
        assert tables_after_down == set()

        await connection.run_sync(
            lambda sync_connection: _run_migration(
                sync_connection,
                migration,
                "upgrade",
            )
        )
        tables_after_up = set(
            (
                await connection.execute(
                    text(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = current_schema()
                          AND table_name LIKE 'review_bulk_operation%'
                        """
                    )
                )
            ).scalars()
        )
        assert tables_after_up == {
            "review_bulk_operations",
            "review_bulk_operation_items",
            "review_bulk_operation_receipts",
        }
        indexes = set(
            (
                await connection.execute(
                    text(
                        """
                        SELECT indexname
                        FROM pg_indexes
                        WHERE schemaname = current_schema()
                          AND tablename IN (
                              'review_bulk_operations',
                              'review_bulk_operation_items',
                              'review_bulk_operation_receipts'
                          )
                        """
                    )
                )
            ).scalars()
        )
        assert {
            "ix_review_bulk_operations_status_created",
            "ix_review_bulk_operation_items_pending",
            "ix_review_bulk_operation_items_candidate_id",
            "review_bulk_operation_receipts_pkey",
        } <= indexes

        await connection.run_sync(
            lambda sync_connection: _run_migration(
                sync_connection,
                migration,
                "downgrade",
            )
        )
        await connection.run_sync(
            lambda sync_connection: _run_migration(
                sync_connection,
                migration,
                "upgrade",
            )
        )
