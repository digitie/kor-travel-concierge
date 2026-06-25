"""해외/제외 블록리스트 컬럼 추가.

youtube_videos.is_excluded/exclusion_reason(영상 제외 블록리스트),
extracted_place_candidates.is_domestic(POI 추출 LLM의 국내 여부 판정).

Revision ID: 20260626_0013
Revises: 20260626_0012
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260626_0013"
down_revision = "20260626_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "youtube_videos",
        sa.Column(
            "is_excluded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "youtube_videos",
        sa.Column("exclusion_reason", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "extracted_place_candidates",
        sa.Column("is_domestic", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("extracted_place_candidates", "is_domestic")
    op.drop_column("youtube_videos", "exclusion_reason")
    op.drop_column("youtube_videos", "is_excluded")
