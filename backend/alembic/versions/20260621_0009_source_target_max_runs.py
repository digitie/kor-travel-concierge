"""source_targets.max_runs / run_count 컬럼 추가.

반복 수집 횟수 제한(`max_runs`, 0=무한)과 그동안 enqueue된 누적 횟수(`run_count`).
스캔이 enqueue할 때마다 `run_count`를 올리고 상한 도달 시 비활성화한다(반복 수정 기능).
새 DB는 `init_db` create_all로 생성된다.

Revision ID: 20260621_0009
Revises: 20260621_0008
Create Date: 2026-06-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260621_0009"
down_revision = "20260621_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_targets",
        sa.Column(
            "max_runs", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "source_targets",
        sa.Column(
            "run_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )


def downgrade() -> None:
    op.drop_column("source_targets", "run_count")
    op.drop_column("source_targets", "max_runs")
