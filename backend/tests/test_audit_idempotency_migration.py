"""감사 로그 멱등 전용 컬럼 migration 회귀."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_PATH = (
    _ROOT
    / "backend"
    / "alembic"
    / "versions"
    / "20260713_0023_audit_idempotency_columns.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "test_audit_idempotency_migration_0023",
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


async def _insert_legacy_audit(connection, payload_json: str) -> int:
    return (
        await connection.execute(
            text(
                """
                INSERT INTO audit_logs (
                    actor_type,
                    action,
                    target_type,
                    target_id,
                    payload_json,
                    created_at
                )
                VALUES (
                    'mcp',
                    'place.correct',
                    'travel_place',
                    '1',
                    :payload_json,
                    now()
                )
                RETURNING id
                """
            ),
            {"payload_json": payload_json},
        )
    ).scalar_one()


async def test_audit_idempotency_migration_backfills_safely_and_downgrades(
    engine,
):
    migration = _load_migration()
    async with engine.begin() as connection:
        # 테스트 metadata는 최신 head이므로 먼저 0023만 내려 legacy schema를 만든다.
        await connection.run_sync(
            lambda sync_connection: _run_migration(
                sync_connection,
                migration,
                "downgrade",
            )
        )

        duplicate_old_id = await _insert_legacy_audit(
            connection,
            json.dumps(
                {
                    "idempotency_key": "duplicate-key",
                    # state가 없는 legacy 완료 행은 final 후보지만 최신 중복에 밀린다.
                    "request": {"place_id": 1},
                    "result": {"ok": True},
                }
            ),
        )
        duplicate_new_id = await _insert_legacy_audit(
            connection,
            json.dumps(
                {
                    "idempotency_key": "duplicate-key",
                    "idempotency_state": "pending",
                }
            ),
        )
        legacy_final_id = await _insert_legacy_audit(
            connection,
            json.dumps({"idempotency_key": "legacy-final-key"}),
        )
        corrupt_id = await _insert_legacy_audit(connection, "{")
        non_object_id = await _insert_legacy_audit(connection, "[]")
        stale_valid_id = await _insert_legacy_audit(
            connection,
            json.dumps(
                {
                    "idempotency_key": "invalid-state-key",
                    "idempotency_state": "final",
                }
            ),
        )
        invalid_state_id = await _insert_legacy_audit(
            connection,
            json.dumps(
                {
                    "idempotency_key": "invalid-state-key",
                    "idempotency_state": "unknown",
                }
            ),
        )
        oversized_key_id = await _insert_legacy_audit(
            connection,
            json.dumps({"idempotency_key": "k" * 256}),
        )

        await connection.run_sync(
            lambda sync_connection: _run_migration(
                sync_connection,
                migration,
                "upgrade",
            )
        )

        rows = {
            row.id: (row.idempotency_key, row.idempotency_state)
            for row in (
                await connection.execute(
                    text(
                        """
                        SELECT id, idempotency_key, idempotency_state
                        FROM audit_logs
                        ORDER BY id
                        """
                    )
                )
            )
        }
        assert rows[duplicate_old_id] == (None, None)
        assert rows[duplicate_new_id] == ("duplicate-key", "pending")
        assert rows[legacy_final_id] == ("legacy-final-key", "final")
        for skipped_id in (
            corrupt_id,
            non_object_id,
            stale_valid_id,
            invalid_state_id,
            oversized_key_id,
        ):
            assert rows[skipped_id] == (None, None)

        index_definition = (
            await connection.execute(
                text(
                    """
                    SELECT indexdef
                    FROM pg_indexes
                    WHERE schemaname = current_schema()
                      AND indexname = 'uq_audit_logs_actor_action_idempotency_key'
                    """
                )
            )
        ).scalar_one()
        assert "UNIQUE INDEX" in index_definition
        assert "idempotency_key IS NOT NULL" in index_definition

        with pytest.raises(IntegrityError):
            async with connection.begin_nested():
                await connection.execute(
                    text(
                        """
                        INSERT INTO audit_logs (
                            actor_type, action, target_type, idempotency_key,
                            idempotency_state, created_at
                        )
                        VALUES (
                            'mcp', 'place.correct', 'travel_place',
                            'duplicate-key', 'final', now()
                        )
                        """
                    )
                )
        with pytest.raises(IntegrityError):
            async with connection.begin_nested():
                await connection.execute(
                    text(
                        """
                        INSERT INTO audit_logs (
                            actor_type, action, target_type, idempotency_key,
                            idempotency_state, created_at
                        )
                        VALUES (
                            'mcp', 'place.correct', 'travel_place',
                            'key-without-state', NULL, now()
                        )
                        """
                    )
                )
        with pytest.raises(IntegrityError):
            async with connection.begin_nested():
                await connection.execute(
                    text(
                        """
                        INSERT INTO audit_logs (
                            actor_type, action, target_type, idempotency_key,
                            idempotency_state, created_at
                        )
                        VALUES (
                            'mcp', 'place.correct', 'travel_place',
                            NULL, 'pending', now()
                        )
                        """
                    )
                )

        # pending payload를 구 runtime이 완료 응답으로 오인하지 않도록, 전용 state가
        # 하나라도 pending이면 index/constraint/column을 건드리기 전에 중단한다.
        with pytest.raises(RuntimeError, match="pending 멱등 작업"):
            await connection.run_sync(
                lambda sync_connection: _run_migration(
                    sync_connection,
                    migration,
                    "downgrade",
                )
            )
        pending_row = (
            await connection.execute(
                text(
                    """
                    SELECT idempotency_state, payload_json
                    FROM audit_logs
                    WHERE id = :audit_log_id
                    """
                ),
                {"audit_log_id": duplicate_new_id},
            )
        ).one()
        assert pending_row.idempotency_state == "pending"
        assert json.loads(pending_row.payload_json)["idempotency_state"] == "pending"
        remaining_index = (
            await connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM pg_indexes
                    WHERE schemaname = current_schema()
                      AND indexname =
                          'uq_audit_logs_actor_action_idempotency_key'
                    """
                )
            )
        ).scalar_one()
        assert remaining_index == 1

        finalized_payload = json.loads(pending_row.payload_json)
        finalized_payload["idempotency_state"] = "final"
        await connection.execute(
            text(
                """
                UPDATE audit_logs
                SET idempotency_state = 'final', payload_json = :payload_json
                WHERE id = :audit_log_id
                """
            ),
            {
                "audit_log_id": duplicate_new_id,
                "payload_json": json.dumps(finalized_payload),
            },
        )
        finalized_row = (
            await connection.execute(
                text(
                    """
                    SELECT idempotency_state, payload_json
                    FROM audit_logs
                    WHERE id = :audit_log_id
                    """
                ),
                {"audit_log_id": duplicate_new_id},
            )
        ).one()
        assert finalized_row.idempotency_state == "final"
        assert json.loads(finalized_row.payload_json)["idempotency_state"] == "final"

        await connection.run_sync(
            lambda sync_connection: _run_migration(
                sync_connection,
                migration,
                "downgrade",
            )
        )
        columns = set(
            (
                await connection.execute(
                    text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = 'audit_logs'
                        """
                    )
                )
            ).scalars()
        )
        assert "idempotency_key" not in columns
        assert "idempotency_state" not in columns
        remaining_payloads = (
            await connection.execute(
                text("SELECT count(*) FROM audit_logs WHERE payload_json IS NOT NULL")
            )
        ).scalar_one()
        assert remaining_payloads == 8
