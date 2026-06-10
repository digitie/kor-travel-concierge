"""source_scan target scheduling fields.

Revision ID: 20260610_0003
Revises: 20260610_0002
Create Date: 2026-06-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260610_0003"
down_revision = "20260610_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_targets",
        sa.Column("scan_interval_minutes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "source_targets",
        sa.Column("last_seen_cursor", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "source_targets",
        sa.Column("last_seen_video_published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "source_targets",
        sa.Column("api_budget_group", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "source_targets",
        sa.Column(
            "scan_failure_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "source_targets",
        sa.Column("last_scan_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "source_targets",
        sa.Column("last_scan_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column("source_targets", "scan_failure_count", server_default=None)
    op.create_index(
        "ix_source_targets_budget_next_crawl",
        "source_targets",
        ["api_budget_group", "is_active", "next_crawl_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_source_targets_budget_next_crawl", table_name="source_targets")
    op.drop_column("source_targets", "last_scan_at")
    op.drop_column("source_targets", "last_scan_error")
    op.drop_column("source_targets", "scan_failure_count")
    op.drop_column("source_targets", "api_budget_group")
    op.drop_column("source_targets", "last_seen_video_published_at")
    op.drop_column("source_targets", "last_seen_cursor")
    op.drop_column("source_targets", "scan_interval_minutes")
