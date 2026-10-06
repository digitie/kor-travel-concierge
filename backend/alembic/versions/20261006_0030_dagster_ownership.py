"""Dagster 실행 소유권과 안전한 backend 전환 정본.
Revision ID: 20261006_0030
Revises: 20260901_0029
"""

import sqlalchemy as sa
from alembic import op

revision = "20261006_0030"
down_revision = "20260901_0029"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "crawl_runs", sa.Column("orchestrator_run_id", sa.String(64), nullable=True)
    )
    op.add_column(
        "crawl_runs",
        sa.Column(
            "orchestrator_attempt", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "crawl_runs",
        sa.Column("orchestrator_claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_crawl_runs_orchestrator_run_id", "crawl_runs", ["orchestrator_run_id"]
    )
    table = op.create_table(
        "scheduler_control",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("backend", sa.String(16), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_scheduler_control_singleton"),
        sa.CheckConstraint(
            "backend IN ('legacy', 'dagster')", name="ck_scheduler_control_backend"
        ),
        sa.CheckConstraint("generation >= 0", name="ck_scheduler_control_generation"),
    )
    op.bulk_insert(table, [{"id": 1, "backend": "legacy", "generation": 0}])


def downgrade():
    # 활성 native 소유권을 지우는 downgrade는 허용하지 않는다.
    count = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM crawl_runs WHERE orchestrator_run_id IS NOT NULL AND state IN ('pending', 'running')"
        )
    )
    if count:
        raise RuntimeError("Dagster 소유 작업을 drain한 뒤 downgrade하세요")
    op.drop_table("scheduler_control")
    op.drop_index("ix_crawl_runs_orchestrator_run_id", table_name="crawl_runs")
    op.drop_column("crawl_runs", "orchestrator_claimed_at")
    op.drop_column("crawl_runs", "orchestrator_attempt")
    op.drop_column("crawl_runs", "orchestrator_run_id")
