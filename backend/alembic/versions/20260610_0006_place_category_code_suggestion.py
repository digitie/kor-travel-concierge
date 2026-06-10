"""travel_places category_code_suggestion column.

feature export `category_code_suggestion`을 채우기 위해 확정 장소에 Gemini가 고른
`python-krtour-map` 8자리 category 코드 제안값을 저장하는 컬럼을 추가한다.
(T-070)

Revision ID: 20260610_0006
Revises: 20260610_0005
Create Date: 2026-06-11
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260610_0006"
down_revision = "20260610_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "travel_places",
        sa.Column("category_code_suggestion", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("travel_places", "category_code_suggestion")
