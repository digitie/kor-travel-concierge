"""worker lane 분리 (T-163, 로드맵 PR-04/§10 B6).

- `crawl_runs.lane` VARCHAR(16) NOT NULL DEFAULT 'batch' + CHECK + `(lane, state, id)`
  인덱스: claim/실행을 대화형(interactive)·배치(batch) 2레인으로 분리해 배치 작업이
  대화형 작업을 굶기지 않게 한다. lane은 enqueue 지점 기준으로 지정한다(job_type 아님).
  기존 행은 server_default 'batch'로 백필된다(스케줄러 발원이 다수라 안전한 기본).
- 체인: 0017(soft delete) → 0018(stage events/restart/attention) → 0019(본 migration).

Revision ID: 20260713_0019
Revises: 20260713_0018
Create Date: 2026-07-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260713_0019"
down_revision = "20260713_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crawl_runs",
        sa.Column(
            "lane",
            sa.String(length=16),
            nullable=False,
            server_default="batch",
        ),
    )
    op.create_check_constraint(
        "ck_crawl_runs_lane_valid",
        "crawl_runs",
        "lane IN ('interactive', 'batch')",
    )
    op.create_index(
        "ix_crawl_runs_lane_claim",
        "crawl_runs",
        ["lane", "state", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_crawl_runs_lane_claim", table_name="crawl_runs")
    op.drop_constraint("ck_crawl_runs_lane_valid", "crawl_runs", type_="check")
    op.drop_column("crawl_runs", "lane")
