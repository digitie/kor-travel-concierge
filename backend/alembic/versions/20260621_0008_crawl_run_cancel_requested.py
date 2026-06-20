"""crawl_runs.cancel_requested 컬럼 추가.

실행 중 작업에 대한 협조적 중지 신호. 실행자(heartbeat watcher)가 폴링해 작업을
`cancelled`로 마감한다(작업 중지/재시작 기능). 새 DB는 `init_db` create_all로 생성된다.

Revision ID: 20260621_0008
Revises: 20260620_0007
Create Date: 2026-06-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260621_0008"
down_revision = "20260620_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crawl_runs",
        sa.Column(
            "cancel_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("crawl_runs", "cancel_requested")
