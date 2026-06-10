"""feature export ledger table.

범용 feature 수집 API(`/api/v1/features/snapshot`·`/api/v1/features/changes`)의
full/incremental cursor와 reject/tombstone 재전송을 위한 `feature_exports` ledger와
증가 cursor용 sequence를 추가한다. (T-066, ADR-26)

Revision ID: 20260610_0005
Revises: 20260610_0004
Create Date: 2026-06-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260610_0005"
down_revision = "20260610_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS feature_export_sequence")
    op.create_table(
        "feature_exports",
        sa.Column("export_id", sa.String(length=64), nullable=False),
        sa.Column(
            "sequence",
            sa.BigInteger(),
            server_default=sa.text("nextval('feature_export_sequence')"),
            nullable=False,
        ),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("export_state", sa.String(length=16), nullable=False),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("payload_hash", sa.String(length=80), nullable=False),
        sa.Column("last_exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["extracted_place_candidates.id"],
            name="fk_feature_exports_candidate",
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint("export_id"),
    )
    op.execute(
        "ALTER SEQUENCE feature_export_sequence OWNED BY feature_exports.sequence"
    )
    op.create_index(
        "ix_feature_exports_sequence",
        "feature_exports",
        ["sequence"],
        unique=True,
    )
    op.create_index(
        "ix_feature_exports_candidate_id",
        "feature_exports",
        ["candidate_id"],
        unique=True,
    )
    op.create_index(
        "ix_feature_exports_state_updated",
        "feature_exports",
        ["export_state", "updated_at", "export_id"],
    )
    op.create_index(
        "ix_feature_exports_payload_json_gin",
        "feature_exports",
        ["payload_json"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_feature_exports_payload_json_gin", table_name="feature_exports")
    op.drop_index("ix_feature_exports_state_updated", table_name="feature_exports")
    op.drop_index("ix_feature_exports_candidate_id", table_name="feature_exports")
    op.drop_index("ix_feature_exports_sequence", table_name="feature_exports")
    op.drop_table("feature_exports")
    op.execute("DROP SEQUENCE IF EXISTS feature_export_sequence")
