"""행정구역 데이터셋 시도 토큰과 재해결 대상 인덱스.
Revision ID: 20261013_0031
Revises: 20261006_0030
"""

import sqlalchemy as sa
from alembic import op

revision = "20261013_0031"
down_revision = "20261006_0030"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "travel_places",
        sa.Column("admin_code_geo_data_token", sa.String(40), nullable=True),
    )
    op.create_index(
        "ix_travel_places_admin_geo_token",
        "travel_places",
        ["admin_code_geo_data_token"],
        postgresql_where=sa.text("is_geocoded"),
    )


def downgrade():
    op.drop_index("ix_travel_places_admin_geo_token", table_name="travel_places")
    op.drop_column("travel_places", "admin_code_geo_data_token")
