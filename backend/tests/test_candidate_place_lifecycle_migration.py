"""T-184 후보·장소 생명주기 및 DB revision migration 회귀."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import BigInteger, CheckConstraint, FetchedValue, text
from sqlalchemy.exc import IntegrityError

from ktc.core.database import ensure_candidate_place_revision_triggers
from ktc.models.extracted_place_candidate import ExtractedPlaceCandidate
from ktc.models.travel_place import PlaceLifecycleOrigin, TravelPlace


_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_PATH = (
    _ROOT
    / "backend"
    / "alembic"
    / "versions"
    / "20260713_0026_candidate_place_lifecycle_revisions.py"
)
_OMIT = object()


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "test_candidate_place_lifecycle_migration_0026",
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


async def _column_names(connection, table_name: str) -> set[str]:
    return set(
        (
            await connection.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = :table_name
                    """
                ),
                {"table_name": table_name},
            )
        ).scalars()
    )


async def _seed_video(connection, suffix: str) -> str:
    channel_id = f"channel-{suffix}"
    video_id = f"video-{suffix}"
    await connection.execute(
        text(
            """
            INSERT INTO youtube_channels (channel_id, title, created_at)
            VALUES (:channel_id, :title, now())
            """
        ),
        {"channel_id": channel_id, "title": f"채널 {suffix}"},
    )
    await connection.execute(
        text(
            """
            INSERT INTO youtube_videos (
                video_id,
                title,
                url,
                channel_id,
                crawl_status,
                crawled_at
            )
            VALUES (
                :video_id,
                :title,
                :url,
                :channel_id,
                'discovered',
                now()
            )
            """
        ),
        {
            "video_id": video_id,
            "title": f"영상 {suffix}",
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "channel_id": channel_id,
        },
    )
    return video_id


async def _insert_candidate(
    connection,
    video_id: str,
    name: str,
    *,
    state_revision: int | object = _OMIT,
) -> int:
    columns = [
        "video_id",
        "source_kind",
        "source_text",
        "ai_place_name",
        "match_status",
        "feature_export_status",
        "created_at",
    ]
    values = [
        ":video_id",
        "'transcript'",
        ":source_text",
        ":name",
        "'needs_review'",
        "'pending'",
        "now()",
    ]
    parameters: dict[str, Any] = {
        "video_id": video_id,
        "source_text": f"{name} 방문",
        "name": name,
    }
    if state_revision is not _OMIT:
        columns.append("state_revision")
        values.append(":state_revision")
        parameters["state_revision"] = state_revision

    return (
        await connection.execute(
            text(
                "INSERT INTO extracted_place_candidates "
                f"({', '.join(columns)}) VALUES ({', '.join(values)}) "
                "RETURNING id"
            ),
            parameters,
        )
    ).scalar_one()


async def _insert_place(
    connection,
    name: str,
    *,
    lifecycle_origin: str | None | object = _OMIT,
    origin_candidate_id: int | None | object = _OMIT,
    state_revision: int | object = _OMIT,
) -> int:
    columns = [
        "name",
        "description_review_status",
        "latitude",
        "longitude",
        "is_geocoded",
        "created_at",
    ]
    values = [":name", "'ai_generated'", "37.5", "127.0", "false", "now()"]
    parameters: dict[str, Any] = {"name": name}
    if lifecycle_origin is not _OMIT:
        columns.append("lifecycle_origin")
        values.append(":lifecycle_origin")
        parameters["lifecycle_origin"] = lifecycle_origin
    if origin_candidate_id is not _OMIT:
        columns.append("origin_candidate_id")
        values.append(":origin_candidate_id")
        parameters["origin_candidate_id"] = origin_candidate_id
    if state_revision is not _OMIT:
        columns.append("state_revision")
        values.append(":state_revision")
        parameters["state_revision"] = state_revision

    return (
        await connection.execute(
            text(
                "INSERT INTO travel_places "
                f"({', '.join(columns)}) VALUES ({', '.join(values)}) "
                "RETURNING place_id"
            ),
            parameters,
        )
    ).scalar_one()


async def _assert_place_insert_fails(connection, **kwargs: Any) -> None:
    with pytest.raises(IntegrityError):
        async with connection.begin_nested():
            await _insert_place(connection, "제약 위반 장소", **kwargs)


async def _drop_runtime_objects(connection, migration: ModuleType) -> None:
    """metadata에 표현되지 않는 trigger/function을 테스트 DB에 남기지 않는다."""
    await connection.execute(
        text(
            f"DROP TRIGGER IF EXISTS {migration._CANDIDATE_REVISION_TRIGGER} "
            "ON extracted_place_candidates"
        )
    )
    await connection.execute(
        text(
            f"DROP TRIGGER IF EXISTS {migration._PLACE_REVISION_TRIGGER} "
            "ON travel_places"
        )
    )
    await connection.execute(
        text(f"DROP FUNCTION IF EXISTS {migration._REVISION_FUNCTION}()")
    )


def test_candidate_place_lifecycle_model_contract() -> None:
    assert {origin.value for origin in PlaceLifecycleOrigin} == {
        "candidate_created",
        "persistent",
        "legacy_unknown",
    }

    place_table = TravelPlace.__table__
    candidate_table = ExtractedPlaceCandidate.__table__
    assert TravelPlace.__mapper__.version_id_col is None
    assert ExtractedPlaceCandidate.__mapper__.version_id_col is None

    for table in (place_table, candidate_table):
        revision = table.c.state_revision
        assert isinstance(revision.type, BigInteger)
        assert revision.nullable is False
        assert revision.default is not None
        assert revision.default.arg == 1
        assert revision.server_default is not None
        assert isinstance(revision.server_onupdate, FetchedValue)

    lifecycle = place_table.c.lifecycle_origin
    assert lifecycle.nullable is False
    assert lifecycle.default is not None
    assert lifecycle.default.arg == PlaceLifecycleOrigin.PERSISTENT.value
    assert lifecycle.server_default is not None
    assert str(lifecycle.server_default.arg) == PlaceLifecycleOrigin.PERSISTENT.value

    origin = place_table.c.origin_candidate_id
    assert origin.nullable is True
    origin_fk = next(iter(origin.foreign_keys))
    assert origin_fk.target_fullname == "extracted_place_candidates.id"
    assert origin_fk.ondelete == "NO ACTION"
    assert origin_fk.constraint.name == "fk_travel_places_origin_candidate_id_epc"
    assert origin_fk.constraint.use_alter is True

    origin_index = next(
        index
        for index in place_table.indexes
        if index.name == "ix_travel_places_origin_candidate_id"
    )
    assert origin_index.unique is not True
    assert [column.name for column in origin_index.columns] == ["origin_candidate_id"]

    place_checks = {
        constraint.name
        for constraint in place_table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_travel_places_lifecycle_origin",
        "ck_travel_places_origin_candidate_consistency",
        "ck_travel_places_state_revision_positive",
    } <= place_checks
    candidate_checks = {
        constraint.name
        for constraint in candidate_table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_epc_state_revision_positive" in candidate_checks


async def test_candidate_place_lifecycle_migration_fresh_contract(engine) -> None:
    migration = _load_migration()
    assert migration.revision == "20260713_0026"
    assert migration.down_revision == "20260713_0025"

    async with engine.begin() as connection:
        # runtime trigger까지 설치한 최신 create_all schema를 legacy 형태로 내린 뒤,
        # 빈 DB upgrade 경로를 재현한다. downgrade는 runtime 객체도 안전하게 제거한다.
        await connection.run_sync(
            lambda sync_connection: _run_migration(
                sync_connection,
                migration,
                "downgrade",
            )
        )
        assert "state_revision" not in await _column_names(
            connection, "extracted_place_candidates"
        )
        assert {
            "lifecycle_origin",
            "origin_candidate_id",
            "state_revision",
        }.isdisjoint(await _column_names(connection, "travel_places"))
        with pytest.raises(RuntimeError, match="Alembic head"):
            await ensure_candidate_place_revision_triggers(connection)

        await connection.run_sync(
            lambda sync_connection: _run_migration(
                sync_connection,
                migration,
                "upgrade",
            )
        )
        # Alembic head 위 local/test/e2e bootstrap 재호출은 같은 이름의 DB 객체를
        # 중복 없이 복원하는 멱등 연산이다.
        await ensure_candidate_place_revision_triggers(connection)
        await ensure_candidate_place_revision_triggers(connection)
        trigger_count = int(
            (
                await connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM pg_trigger
                        WHERE NOT tgisinternal
                          AND tgname IN (
                              'trg_epc_bump_state_revision',
                              'trg_travel_places_bump_state_revision'
                          )
                        """
                    )
                )
            ).scalar_one()
        )
        assert trigger_count == 2

        columns = {
            row.column_name: row
            for row in (
                await connection.execute(
                    text(
                        """
                        SELECT
                            column_name,
                            data_type,
                            is_nullable,
                            column_default
                        FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = 'travel_places'
                          AND column_name IN (
                              'lifecycle_origin',
                              'origin_candidate_id',
                              'state_revision'
                          )
                        """
                    )
                )
            )
        }
        assert set(columns) == {
            "lifecycle_origin",
            "origin_candidate_id",
            "state_revision",
        }
        assert columns["lifecycle_origin"].is_nullable == "NO"
        assert "persistent" in columns["lifecycle_origin"].column_default
        assert columns["origin_candidate_id"].is_nullable == "YES"
        assert columns["state_revision"].data_type == "bigint"
        assert columns["state_revision"].is_nullable == "NO"
        assert "1" in columns["state_revision"].column_default

        candidate_revision_column = (
            await connection.execute(
                text(
                    """
                    SELECT data_type, is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'extracted_place_candidates'
                      AND column_name = 'state_revision'
                    """
                )
            )
        ).one()
        assert candidate_revision_column.data_type == "bigint"
        assert candidate_revision_column.is_nullable == "NO"
        assert "1" in candidate_revision_column.column_default

        checks = set(
            (
                await connection.execute(
                    text(
                        """
                        SELECT con.conname
                        FROM pg_constraint AS con
                        JOIN pg_class AS relation ON relation.oid = con.conrelid
                        JOIN pg_namespace AS namespace
                          ON namespace.oid = relation.relnamespace
                        WHERE namespace.nspname = current_schema()
                          AND relation.relname IN (
                              'travel_places',
                              'extracted_place_candidates'
                          )
                          AND con.contype = 'c'
                        """
                    )
                )
            ).scalars()
        )
        assert {
            "ck_epc_state_revision_positive",
            "ck_travel_places_lifecycle_origin",
            "ck_travel_places_origin_candidate_consistency",
            "ck_travel_places_state_revision_positive",
        } <= checks

        delete_rule = (
            await connection.execute(
                text(
                    """
                    SELECT delete_rule
                    FROM information_schema.referential_constraints
                    WHERE constraint_schema = current_schema()
                      AND constraint_name =
                          'fk_travel_places_origin_candidate_id_epc'
                    """
                )
            )
        ).scalar_one()
        assert delete_rule == "NO ACTION"

        origin_index_unique = (
            await connection.execute(
                text(
                    """
                    SELECT idx.indisunique
                    FROM pg_index AS idx
                    JOIN pg_class AS index_relation
                      ON index_relation.oid = idx.indexrelid
                    JOIN pg_class AS table_relation
                      ON table_relation.oid = idx.indrelid
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = table_relation.relnamespace
                    WHERE namespace.nspname = current_schema()
                      AND table_relation.relname = 'travel_places'
                      AND index_relation.relname =
                          'ix_travel_places_origin_candidate_id'
                    """
                )
            )
        ).scalar_one()
        assert origin_index_unique is False

        trigger_rows = {
            (row.event_object_table, row.trigger_name): (
                row.action_timing,
                row.event_manipulation,
            )
            for row in await connection.execute(
                text(
                    """
                    SELECT
                        event_object_table,
                        trigger_name,
                        action_timing,
                        event_manipulation
                    FROM information_schema.triggers
                    WHERE trigger_schema = current_schema()
                      AND trigger_name IN (
                          'trg_epc_bump_state_revision',
                          'trg_travel_places_bump_state_revision'
                      )
                    """
                )
            )
        }
        assert trigger_rows == {
            (
                "extracted_place_candidates",
                "trg_epc_bump_state_revision",
            ): ("BEFORE", "UPDATE"),
            (
                "travel_places",
                "trg_travel_places_bump_state_revision",
            ): ("BEFORE", "UPDATE"),
        }

        video_id = await _seed_video(connection, "fresh")
        candidate_id = await _insert_candidate(connection, video_id, "기원 후보")
        persistent_place_id = await _insert_place(connection, "독립 장소")
        first_origin_place_id = await _insert_place(
            connection,
            "후보 생성 장소 1",
            lifecycle_origin="candidate_created",
            origin_candidate_id=candidate_id,
        )
        second_origin_place_id = await _insert_place(
            connection,
            "후보 생성 장소 2",
            lifecycle_origin="candidate_created",
            origin_candidate_id=candidate_id,
        )

        persistent_row = (
            await connection.execute(
                text(
                    """
                    SELECT lifecycle_origin, origin_candidate_id, state_revision
                    FROM travel_places
                    WHERE place_id = :place_id
                    """
                ),
                {"place_id": persistent_place_id},
            )
        ).one()
        assert persistent_row == ("persistent", None, 1)
        assert first_origin_place_id != second_origin_place_id
        origin_count = (
            await connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM travel_places
                    WHERE origin_candidate_id = :candidate_id
                    """
                ),
                {"candidate_id": candidate_id},
            )
        ).scalar_one()
        # 후보 하나는 reopen 이후 새 장소를 만들 수 있으므로 여러 장소의 기원일 수 있다.
        assert origin_count == 2

        await _assert_place_insert_fails(
            connection,
            lifecycle_origin="candidate_created",
            origin_candidate_id=None,
        )
        await _assert_place_insert_fails(
            connection,
            lifecycle_origin="persistent",
            origin_candidate_id=candidate_id,
        )
        await _assert_place_insert_fails(
            connection,
            lifecycle_origin="invalid",
        )
        await _assert_place_insert_fails(
            connection,
            lifecycle_origin="candidate_created",
            origin_candidate_id=2_147_483_647,
        )
        await _assert_place_insert_fails(connection, state_revision=0)
        with pytest.raises(IntegrityError):
            async with connection.begin_nested():
                await _insert_candidate(
                    connection,
                    video_id,
                    "잘못된 revision 후보",
                    state_revision=0,
                )
        with pytest.raises(IntegrityError):
            async with connection.begin_nested():
                await connection.execute(
                    text(
                        "DELETE FROM extracted_place_candidates "
                        "WHERE id = :candidate_id"
                    ),
                    {"candidate_id": candidate_id},
                )

        candidate_revision = (
            await connection.execute(
                text(
                    """
                    UPDATE extracted_place_candidates
                    SET review_note = '첫 수정'
                    WHERE id = :candidate_id
                    RETURNING state_revision
                    """
                ),
                {"candidate_id": candidate_id},
            )
        ).scalar_one()
        assert candidate_revision == 2
        candidate_noop_revision = (
            await connection.execute(
                text(
                    """
                    UPDATE extracted_place_candidates
                    SET review_note = review_note
                    WHERE id = :candidate_id
                    RETURNING state_revision
                    """
                ),
                {"candidate_id": candidate_id},
            )
        ).scalar_one()
        assert candidate_noop_revision == 3

        place_revision = (
            await connection.execute(
                text(
                    """
                    UPDATE travel_places
                    SET name = '독립 장소 수정'
                    WHERE place_id = :place_id
                    RETURNING state_revision
                    """
                ),
                {"place_id": persistent_place_id},
            )
        ).scalar_one()
        assert place_revision == 2
        overridden_revision = (
            await connection.execute(
                text(
                    """
                    UPDATE travel_places
                    SET state_revision = 100
                    WHERE place_id = :place_id
                    RETURNING state_revision
                    """
                ),
                {"place_id": persistent_place_id},
            )
        ).scalar_one()
        # 직접 대입도 trigger가 OLD+1로 덮어써 DB 단독 소유 계약을 지킨다.
        assert overridden_revision == 3

        await _drop_runtime_objects(connection, migration)


async def test_create_all_revision_trigger_bootstrap_is_concurrent_and_idempotent(
    engine,
) -> None:
    async def install() -> None:
        async with engine.begin() as connection:
            await ensure_candidate_place_revision_triggers(connection)

    await asyncio.wait_for(asyncio.gather(install(), install()), timeout=10)
    async with engine.connect() as connection:
        trigger_count = int(
            (
                await connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM pg_trigger
                        WHERE NOT tgisinternal
                          AND tgname IN (
                              'trg_epc_bump_state_revision',
                              'trg_travel_places_bump_state_revision'
                          )
                        """
                    )
                )
            ).scalar_one()
        )
    assert trigger_count == 2


async def test_candidate_place_lifecycle_migration_backfill_round_trip(engine) -> None:
    migration = _load_migration()
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: _run_migration(
                sync_connection,
                migration,
                "downgrade",
            )
        )
        video_id = await _seed_video(connection, "legacy")
        legacy_candidate_id = await _insert_candidate(
            connection,
            video_id,
            "기존 후보",
        )
        legacy_place_id = await _insert_place(connection, "기존 장소")

        await connection.run_sync(
            lambda sync_connection: _run_migration(
                sync_connection,
                migration,
                "upgrade",
            )
        )
        legacy_place = (
            await connection.execute(
                text(
                    """
                    SELECT lifecycle_origin, origin_candidate_id, state_revision
                    FROM travel_places
                    WHERE place_id = :place_id
                    """
                ),
                {"place_id": legacy_place_id},
            )
        ).one()
        assert legacy_place == ("legacy_unknown", None, 1)
        legacy_candidate_revision = (
            await connection.execute(
                text(
                    """
                    SELECT state_revision
                    FROM extracted_place_candidates
                    WHERE id = :candidate_id
                    """
                ),
                {"candidate_id": legacy_candidate_id},
            )
        ).scalar_one()
        assert legacy_candidate_revision == 1

        post_upgrade_place_id = await _insert_place(connection, "신규 독립 장소")
        post_upgrade_origin = (
            await connection.execute(
                text(
                    """
                    SELECT lifecycle_origin
                    FROM travel_places
                    WHERE place_id = :place_id
                    """
                ),
                {"place_id": post_upgrade_place_id},
            )
        ).scalar_one()
        assert post_upgrade_origin == "persistent"

        await connection.run_sync(
            lambda sync_connection: _run_migration(
                sync_connection,
                migration,
                "downgrade",
            )
        )
        assert "state_revision" not in await _column_names(
            connection, "extracted_place_candidates"
        )
        assert {
            "lifecycle_origin",
            "origin_candidate_id",
            "state_revision",
        }.isdisjoint(await _column_names(connection, "travel_places"))

        remaining_triggers = (
            await connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM information_schema.triggers
                    WHERE trigger_schema = current_schema()
                      AND trigger_name IN (
                          'trg_epc_bump_state_revision',
                          'trg_travel_places_bump_state_revision'
                      )
                    """
                )
            )
        ).scalar_one()
        assert remaining_triggers == 0
        remaining_function = (
            await connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM pg_proc AS proc
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = proc.pronamespace
                    WHERE namespace.nspname = current_schema()
                      AND proc.proname = 'ktc_0026_bump_state_revision'
                    """
                )
            )
        ).scalar_one()
        assert remaining_function == 0

        await connection.run_sync(
            lambda sync_connection: _run_migration(
                sync_connection,
                migration,
                "upgrade",
            )
        )
        reupgraded_places = {
            row.place_id: (
                row.lifecycle_origin,
                row.origin_candidate_id,
                row.state_revision,
            )
            for row in await connection.execute(
                text(
                    """
                    SELECT
                        place_id,
                        lifecycle_origin,
                        origin_candidate_id,
                        state_revision
                    FROM travel_places
                    WHERE place_id IN (:legacy_place_id, :post_upgrade_place_id)
                    """
                ),
                {
                    "legacy_place_id": legacy_place_id,
                    "post_upgrade_place_id": post_upgrade_place_id,
                },
            )
        }
        # downgrade는 새 컬럼의 provenance를 소실하므로 reupgrade는 모든 당시 기존 장소를
        # 다시 보수적인 legacy_unknown으로 분류한다.
        assert reupgraded_places == {
            legacy_place_id: ("legacy_unknown", None, 1),
            post_upgrade_place_id: ("legacy_unknown", None, 1),
        }
        reupgraded_revision = (
            await connection.execute(
                text(
                    """
                    UPDATE extracted_place_candidates
                    SET review_note = 'reupgrade 확인'
                    WHERE id = :candidate_id
                    RETURNING state_revision
                    """
                ),
                {"candidate_id": legacy_candidate_id},
            )
        ).scalar_one()
        assert reupgraded_revision == 2

        await _drop_runtime_objects(connection, migration)
