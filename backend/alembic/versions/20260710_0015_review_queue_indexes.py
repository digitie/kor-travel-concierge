"""검수 큐 조회 인덱스 추가.

Revision ID: 20260710_0015
Revises: 20260627_0014
Create Date: 2026-07-10
"""

from __future__ import annotations

from alembic import op

revision = "20260710_0015"
down_revision = "20260627_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_epc_review_queue_status_id",
        "extracted_place_candidates",
        ["match_status", "id"],
    )
    op.create_index(
        "ix_epc_review_queue_channel_status_id",
        "extracted_place_candidates",
        ["source_channel_id", "match_status", "id"],
    )
    op.create_index(
        "ix_epc_review_queue_playlist_status_id",
        "extracted_place_candidates",
        ["source_playlist_id", "match_status", "id"],
    )
    op.create_index(
        "ix_youtube_videos_source_search_query",
        "youtube_videos",
        ["source_search_query"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_youtube_videos_source_search_query",
        table_name="youtube_videos",
    )
    op.drop_index(
        "ix_epc_review_queue_playlist_status_id",
        table_name="extracted_place_candidates",
    )
    op.drop_index(
        "ix_epc_review_queue_channel_status_id",
        table_name="extracted_place_candidates",
    )
    op.drop_index(
        "ix_epc_review_queue_status_id",
        table_name="extracted_place_candidates",
    )
