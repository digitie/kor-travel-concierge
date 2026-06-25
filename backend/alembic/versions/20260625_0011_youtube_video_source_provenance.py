"""YouTube 영상 수집 source provenance 컬럼 추가.

Revision ID: 20260625_0011
Revises: 20260623_0010
Create Date: 2026-06-25

feature export가 채널명·재생목록명·보정 검색어명을 source title로 노출할 수 있도록
영상 discovery target의 최소 provenance를 저장한다.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260625_0011"
down_revision = "20260623_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "youtube_videos",
        sa.Column("source_target_type", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "youtube_videos",
        sa.Column("source_target_value", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "youtube_videos",
        sa.Column("source_search_query", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("youtube_videos", "source_search_query")
    op.drop_column("youtube_videos", "source_target_value")
    op.drop_column("youtube_videos", "source_target_type")
