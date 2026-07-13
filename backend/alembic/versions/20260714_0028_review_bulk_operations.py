"""검수 후보 일괄 처리 preview·item snapshot·receipt ledger(T-185).

Revision ID: 20260714_0028
Revises: 20260713_0027
Create Date: 2026-07-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260714_0028"
down_revision = "20260713_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_bulk_operations",
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("scope_kind", sa.String(length=16), nullable=False),
        sa.Column(
            "scope_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("scope_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("confirmation_token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "confirmation_expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False),
        sa.Column("succeeded_count", sa.Integer(), nullable=False),
        sa.Column("conflict_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("next_cursor", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "action IN ('ignore', 'delete', 'reopen')",
            name="ck_review_bulk_operations_action",
        ),
        sa.CheckConstraint(
            "scope_kind IN ('selection', 'filter')",
            name="ck_review_bulk_operations_scope_kind",
        ),
        sa.CheckConstraint(
            "status IN ('previewed', 'running', 'completed', 'completed_with_errors')",
            name="ck_review_bulk_operations_status",
        ),
        sa.CheckConstraint(
            "total_count >= 0 AND processed_count >= 0 "
            "AND succeeded_count >= 0 AND conflict_count >= 0 "
            "AND failed_count >= 0 AND processed_count <= total_count "
            "AND processed_count = succeeded_count + conflict_count + failed_count",
            name="ck_review_bulk_operations_counts",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(scope_json) = 'object'",
            name="ck_review_bulk_operations_scope_json_object",
        ),
        sa.PrimaryKeyConstraint("operation_id"),
    )
    op.create_index(
        "ix_review_bulk_operations_status_created",
        "review_bulk_operations",
        ["status", "created_at"],
        unique=False,
    )

    op.create_table(
        "review_bulk_operation_receipts",
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_cursor", sa.String(length=255), nullable=True),
        sa.Column(
            "response_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "jsonb_typeof(response_json) = 'object'",
            name="ck_review_bulk_operation_receipts_response_object",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["review_bulk_operations.operation_id"],
            name="fk_review_bulk_receipts_operation_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("operation_id", "request_id"),
    )

    op.create_table(
        "review_bulk_operation_items",
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_revision", sa.BigInteger(), nullable=False),
        sa.Column("snapshot_review_state", sa.String(length=32), nullable=False),
        sa.Column("snapshot_matched_place_id", sa.Integer(), nullable=True),
        sa.Column("snapshot_matched_place_revision", sa.BigInteger(), nullable=True),
        sa.Column("reopen_token", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "snapshot_revision > 0",
            name="ck_review_bulk_operation_items_revision_positive",
        ),
        sa.CheckConstraint(
            "snapshot_review_state IN "
            "('needs_review', 'ignored', 'deleted', 'matched', 'user_corrected')",
            name="ck_review_bulk_operation_items_review_state",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'conflict', 'failed')",
            name="ck_review_bulk_operation_items_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_review_bulk_operation_items_attempt_count",
        ),
        sa.CheckConstraint(
            "(snapshot_matched_place_id IS NULL AND "
            "snapshot_matched_place_revision IS NULL) OR "
            "(snapshot_matched_place_id IS NOT NULL AND "
            "snapshot_matched_place_revision IS NOT NULL)",
            name="ck_review_bulk_operation_items_place_revision_pair",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["review_bulk_operations.operation_id"],
            name="fk_review_bulk_items_operation_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["extracted_place_candidates.id"],
            name="fk_review_bulk_items_candidate_id",
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint("operation_id", "candidate_id"),
    )
    op.create_index(
        "ix_review_bulk_operation_items_pending",
        "review_bulk_operation_items",
        ["operation_id", "status", "candidate_id"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_review_bulk_operation_items_candidate_id",
        "review_bulk_operation_items",
        ["candidate_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_review_bulk_operation_items_candidate_id",
        table_name="review_bulk_operation_items",
    )
    op.drop_index(
        "ix_review_bulk_operation_items_pending",
        table_name="review_bulk_operation_items",
    )
    op.drop_table("review_bulk_operation_items")
    op.drop_table("review_bulk_operation_receipts")
    op.drop_index(
        "ix_review_bulk_operations_status_created",
        table_name="review_bulk_operations",
    )
    op.drop_table("review_bulk_operations")
