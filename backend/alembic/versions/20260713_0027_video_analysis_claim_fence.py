"""영상 분석 worker claim 소유권 fence(T-184).

영상 분석 실행은 parent crawl run, retry generation, 무작위 claim token을 함께
저장한다. stale parent가 재투입된 뒤 이전 worker가 늦게 돌아와도 최신 owner의 분석
row와 canonical 영상 결과를 덮지 못한다.

Revision ID: 20260713_0027
Revises: 20260713_0026
Create Date: 2026-07-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260713_0027"
down_revision = "20260713_0026"
branch_labels = None
depends_on = None

_ANALYSIS_OWNER_FK = "fk_youtube_video_analysis_runs_owner_crawl_run_id"
_ANALYSIS_OWNER_INDEX = "ix_youtube_video_analysis_runs_owner_crawl_run_id"


def upgrade() -> None:
    op.add_column(
        "youtube_video_analysis_runs",
        sa.Column("owner_crawl_run_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "youtube_video_analysis_runs",
        sa.Column("owner_retry_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "youtube_video_analysis_runs",
        sa.Column("claim_token", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        _ANALYSIS_OWNER_FK,
        "youtube_video_analysis_runs",
        "crawl_runs",
        ["owner_crawl_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        _ANALYSIS_OWNER_INDEX,
        "youtube_video_analysis_runs",
        ["owner_crawl_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        _ANALYSIS_OWNER_INDEX,
        table_name="youtube_video_analysis_runs",
    )
    op.drop_constraint(
        _ANALYSIS_OWNER_FK,
        "youtube_video_analysis_runs",
        type_="foreignkey",
    )
    op.drop_column("youtube_video_analysis_runs", "claim_token")
    op.drop_column("youtube_video_analysis_runs", "owner_retry_count")
    op.drop_column("youtube_video_analysis_runs", "owner_crawl_run_id")
