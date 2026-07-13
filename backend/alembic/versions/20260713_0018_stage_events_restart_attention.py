"""durable stage events + restart lineage·attention (T-162, 로드맵 PR-34/§10 B6).

- `crawl_run_stage_events` 신설: `status_log_json`은 UI 요약용 4필드·최근 80건
  절단(C7)이라 단계별 구조화 측정(stage/provider/attempt/elapsed_ms/outcome)을
  durable하게 담지 못한다. 이 테이블이 §7 "poi_batch 단계별 소요" 지표와 T-172
  자막 fetch 병렬화 게이트의 유일한 데이터 원천이다. 인덱스는 `(run_id, id)`
  복합 1개 — 선두 컬럼이 run_id라 run_id 단독 조회도 커버한다.
- `crawl_runs.restart_of_run_id` self FK + index: 재시작 lineage. 같은 원본의
  active(pending/running) 재시작 run은 1개만 허용한다(중복 클릭 멱등, G6).
- `crawl_runs.attention` VARCHAR(16) NULL + CHECK + partial index:
  open|acknowledged|superseded|resolved (NULL=none). 실패→open, 재시작 생성→
  superseded, 재시작 done→resolved, acknowledge API로 open→acknowledged.
- 체인(main #182 선형화 이후): 0016(scope) → 0017(soft delete) → 0018(본 migration).

Revision ID: 20260713_0018
Revises: 20260713_0017
Create Date: 2026-07-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260713_0018"
down_revision = "20260713_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crawl_run_stage_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=True),
        sa.Column("item_ref", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["run_id"], ["crawl_runs.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_crawl_run_stage_events_run_id_id",
        "crawl_run_stage_events",
        ["run_id", "id"],
    )

    op.add_column(
        "crawl_runs",
        sa.Column("restart_of_run_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_crawl_runs_restart_of_run_id",
        "crawl_runs",
        "crawl_runs",
        ["restart_of_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_crawl_runs_restart_of_run_id", "crawl_runs", ["restart_of_run_id"]
    )

    op.add_column(
        "crawl_runs",
        sa.Column("attention", sa.String(length=16), nullable=True),
    )
    op.create_check_constraint(
        "ck_crawl_runs_attention_valid",
        "crawl_runs",
        "attention IN ('open', 'acknowledged', 'superseded', 'resolved')",
    )
    op.create_index(
        "ix_crawl_runs_attention",
        "crawl_runs",
        ["attention"],
        postgresql_where=sa.text("attention IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_crawl_runs_attention", table_name="crawl_runs")
    op.drop_constraint(
        "ck_crawl_runs_attention_valid", "crawl_runs", type_="check"
    )
    op.drop_column("crawl_runs", "attention")

    op.drop_index("ix_crawl_runs_restart_of_run_id", table_name="crawl_runs")
    op.drop_constraint(
        "fk_crawl_runs_restart_of_run_id", "crawl_runs", type_="foreignkey"
    )
    op.drop_column("crawl_runs", "restart_of_run_id")

    op.drop_index(
        "ix_crawl_run_stage_events_run_id_id",
        table_name="crawl_run_stage_events",
    )
    op.drop_table("crawl_run_stage_events")
