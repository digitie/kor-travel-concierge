"""source_targets에 max_videos 컬럼 추가(반복 수집 1회당 영상 수, 편집 가능).

Revision ID: 20260626_0012
Revises: 20260625_0011
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260626_0012"
down_revision = "20260625_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_targets",
        sa.Column("max_videos", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("source_targets", "max_videos")
