"""후보·장소 revision과 후보 생성 장소 생명주기 추적(T-184).

검수 reopen이 사용자가 확정한 장소만 안전하게 정리하려면 장소가 특정 후보의 확정
과정에서 만들어졌는지 영구적으로 구분해야 한다. 기존 장소는 생성 경로를 추정하지 않고
``legacy_unknown``으로 보존하며, migration 이후 일반 생성의 DB 기본값은
``persistent``로 둔다. 후보 생성 장소만 ``origin_candidate_id``를 갖는다.

후보와 장소의 모든 UPDATE는 PostgreSQL BEFORE UPDATE trigger가 ``state_revision``을
정확히 1 증가시킨다. ORM이나 service가 revision을 직접 증가시키지 않도록 DB를 단일
소유자로 둔다.

Revision ID: 20260713_0026
Revises: 20260713_0025
Create Date: 2026-07-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260713_0026"
down_revision = "20260713_0025"
branch_labels = None
depends_on = None

_CANDIDATE_REVISION_CHECK = "ck_epc_state_revision_positive"
_PLACE_LIFECYCLE_CHECK = "ck_travel_places_lifecycle_origin"
_PLACE_ORIGIN_CHECK = "ck_travel_places_origin_candidate_consistency"
_PLACE_REVISION_CHECK = "ck_travel_places_state_revision_positive"
_PLACE_ORIGIN_FK = "fk_travel_places_origin_candidate_id_epc"
_PLACE_ORIGIN_INDEX = "ix_travel_places_origin_candidate_id"
_REVISION_FUNCTION = "ktc_0026_bump_state_revision"
_CANDIDATE_REVISION_TRIGGER = "trg_epc_bump_state_revision"
_PLACE_REVISION_TRIGGER = "trg_travel_places_bump_state_revision"


def upgrade() -> None:
    op.add_column(
        "extracted_place_candidates",
        sa.Column(
            "state_revision",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.create_check_constraint(
        _CANDIDATE_REVISION_CHECK,
        "extracted_place_candidates",
        "state_revision > 0",
    )

    # 기존 장소의 생성 경로는 신뢰성 있게 복원할 수 없다. nullable 상태에서 명시적으로
    # backfill한 뒤 신규 insert에만 persistent 기본값이 적용되도록 순서대로 고정한다.
    op.add_column(
        "travel_places",
        sa.Column("lifecycle_origin", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "travel_places",
        sa.Column("origin_candidate_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "travel_places",
        sa.Column(
            "state_revision",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.execute(
        "UPDATE travel_places "
        "SET lifecycle_origin = 'legacy_unknown' "
        "WHERE lifecycle_origin IS NULL"
    )
    op.alter_column(
        "travel_places",
        "lifecycle_origin",
        existing_type=sa.String(length=32),
        nullable=False,
        server_default=sa.text("'persistent'"),
    )

    op.create_foreign_key(
        _PLACE_ORIGIN_FK,
        "travel_places",
        "extracted_place_candidates",
        ["origin_candidate_id"],
        ["id"],
        ondelete="NO ACTION",
    )
    # reopen 뒤 같은 후보에서 새 장소를 다시 만들 수 있으므로 고유 인덱스가 아니다.
    op.create_index(
        _PLACE_ORIGIN_INDEX,
        "travel_places",
        ["origin_candidate_id"],
        unique=False,
    )
    op.create_check_constraint(
        _PLACE_LIFECYCLE_CHECK,
        "travel_places",
        "lifecycle_origin IN "
        "('candidate_created', 'persistent', 'legacy_unknown')",
    )
    op.create_check_constraint(
        _PLACE_ORIGIN_CHECK,
        "travel_places",
        "(lifecycle_origin = 'candidate_created' "
        "AND origin_candidate_id IS NOT NULL) OR "
        "(lifecycle_origin IN ('persistent', 'legacy_unknown') "
        "AND origin_candidate_id IS NULL)",
    )
    op.create_check_constraint(
        _PLACE_REVISION_CHECK,
        "travel_places",
        "state_revision > 0",
    )

    # revision 함수명은 migration 전용으로 격리한다. 재upgrade 시에도 함수 본문을
    # 확실히 복구하고, trigger는 각 테이블의 모든 UPDATE에 한 번만 실행한다.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_REVISION_FUNCTION}()
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
    op.execute(
        f"""
        CREATE TRIGGER {_CANDIDATE_REVISION_TRIGGER}
        BEFORE UPDATE ON extracted_place_candidates
        FOR EACH ROW
        EXECUTE FUNCTION {_REVISION_FUNCTION}()
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_PLACE_REVISION_TRIGGER}
        BEFORE UPDATE ON travel_places
        FOR EACH ROW
        EXECUTE FUNCTION {_REVISION_FUNCTION}()
        """
    )


def downgrade() -> None:
    # trigger를 먼저 제거해야 revision 컬럼과 함수를 안전하게 내릴 수 있다.
    op.execute(
        f"DROP TRIGGER IF EXISTS {_CANDIDATE_REVISION_TRIGGER} "
        "ON extracted_place_candidates"
    )
    op.execute(
        f"DROP TRIGGER IF EXISTS {_PLACE_REVISION_TRIGGER} ON travel_places"
    )
    op.execute(f"DROP FUNCTION IF EXISTS {_REVISION_FUNCTION}()")

    op.drop_constraint(
        _PLACE_REVISION_CHECK,
        "travel_places",
        type_="check",
    )
    op.drop_constraint(
        _PLACE_ORIGIN_CHECK,
        "travel_places",
        type_="check",
    )
    op.drop_constraint(
        _PLACE_LIFECYCLE_CHECK,
        "travel_places",
        type_="check",
    )
    op.drop_index(_PLACE_ORIGIN_INDEX, table_name="travel_places")
    op.drop_constraint(
        _PLACE_ORIGIN_FK,
        "travel_places",
        type_="foreignkey",
    )
    op.drop_column("travel_places", "state_revision")
    op.drop_column("travel_places", "origin_candidate_id")
    op.drop_column("travel_places", "lifecycle_origin")

    op.drop_constraint(
        _CANDIDATE_REVISION_CHECK,
        "extracted_place_candidates",
        type_="check",
    )
    op.drop_column("extracted_place_candidates", "state_revision")
