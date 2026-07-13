"""feature export durable dirty outbox 테이블 (T-171, S6/A2).

export payload에 영향을 주는 후보 변경을 변경과 같은 트랜잭션에서 이 outbox에 기록하고,
공급 GET(`/features/snapshot|changes`)은 outbox에 실린 후보만 동기화(consume)한다. API와
scheduler가 별도 프로세스라 프로세스-로컬 스로틀/워터마크/플래그가 정본이 될 수 없어 DB
durable 테이블로 둔다(로드맵 PR-22 개정 2026-07-13, §10.4).

origin/main head(`20260713_0024`) 위에 단일 head로 체인한다.

Revision ID: 20260713_0025
Revises: 20260713_0024
Create Date: 2026-07-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260713_0025"
down_revision = "20260713_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "export_dirty_outbox",
        sa.Column("candidate_id", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "marked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["extracted_place_candidates.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("candidate_id"),
    )


def downgrade() -> None:
    op.drop_table("export_dirty_outbox")
