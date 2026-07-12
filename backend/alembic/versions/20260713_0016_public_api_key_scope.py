"""공개 API 키 read/admin scope 추가.

Revision ID: 20260713_0016
Revises: 20260710_0015
Create Date: 2026-07-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260713_0016"
down_revision = "20260710_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 상수 default로 기존 공개 키도 read로 백필한다. static API_KEYS는 DB 행이 아니며
    # 애플리케이션에서 BFF/operator용 admin으로 분류한다. T-176에서는 consumer와
    # 공유하던 static entry만 제거하고 BFF/operator entry는 유지한다.
    op.add_column(
        "public_api_keys",
        sa.Column(
            "scope",
            sa.String(length=16),
            server_default=sa.text("'read'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_public_api_keys_scope",
        "public_api_keys",
        "scope IN ('read', 'admin')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_public_api_keys_scope",
        "public_api_keys",
        type_="check",
    )
    op.drop_column("public_api_keys", "scope")
