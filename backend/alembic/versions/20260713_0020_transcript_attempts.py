"""transcript_attempts durable 관측 + 요약 캐시 컬럼 (T-164, 로드맵 PR-11 개정판, G7).

- `transcript_attempts` 신설: provider별 **모든** 시도(성공 전 실패 포함)를 순서·
  시각·소요·outcome·language·tool version과 함께 durable하게 보존한다. stage
  events(T-162)는 성공 provider 1개만 남겨 provider별 실패 사유를 재구성할 수 없으므로
  별도 테이블이 필요하다(G7). 인덱스는 `(video_id, id)` 복합 1개 — 선두 컬럼이
  video_id라 video_id 단독 조회도 커버한다.
- `youtube_videos.transcript_source`/`transcript_failure_code`: 시도들에서 파생한
  요약 캐시. PR-17/18/19가 "자막 비활성 확정 영상"을 SQL로 선별하고 §7 수율 지표를
  집계하는 원천이다(로그만으로는 불가).
- 체인: 0019(worker lanes) → 0020(본 migration).

Revision ID: 20260713_0020
Revises: 20260713_0019
Create Date: 2026-07-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260713_0020"
down_revision = "20260713_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transcript_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("video_id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("tool_version", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["video_id"], ["youtube_videos.video_id"], ondelete="NO ACTION"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["crawl_runs.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_transcript_attempts_video_id_id",
        "transcript_attempts",
        ["video_id", "id"],
    )

    op.add_column(
        "youtube_videos",
        sa.Column("transcript_source", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "youtube_videos",
        sa.Column("transcript_failure_code", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("youtube_videos", "transcript_failure_code")
    op.drop_column("youtube_videos", "transcript_source")

    op.drop_index(
        "ix_transcript_attempts_video_id_id",
        table_name="transcript_attempts",
    )
    op.drop_table("transcript_attempts")
