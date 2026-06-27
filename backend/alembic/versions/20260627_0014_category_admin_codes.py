"""기본 카테고리와 행정코드 컬럼 추가.

Revision ID: 20260627_0014
Revises: 20260626_0013
Create Date: 2026-06-27
"""

from __future__ import annotations

import json
from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision = "20260627_0014"
down_revision = "20260626_0013"
branch_labels = None
depends_on = None

UNKNOWN_CATEGORY_CODE = "0"
UNKNOWN_CATEGORY_LABEL = "unknown"
UNCLASSIFIED_CODE = "00000000"


def _category_codes() -> tuple[str, ...]:
    path = (
        Path(__file__).resolve().parents[2]
        / "ktc"
        / "data"
        / "place_category_codes.json"
    )
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    codes = [
        str(row["code"])
        for row in data["categories"]
        if row.get("is_active", True) and row["code"] != UNCLASSIFIED_CODE
    ]
    return tuple([UNKNOWN_CATEGORY_CODE, *codes])


def upgrade() -> None:
    op.add_column(
        "source_targets",
        sa.Column("default_category_code", sa.String(length=16), nullable=True),
    )
    op.create_index(
        "ix_source_targets_default_category_code",
        "source_targets",
        ["default_category_code"],
    )

    op.add_column(
        "travel_places",
        sa.Column("legal_dong_code", sa.String(length=10), nullable=True),
    )
    op.add_column(
        "travel_places",
        sa.Column("legal_dong_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "travel_places",
        sa.Column("sigungu_code", sa.String(length=5), nullable=True),
    )
    op.add_column(
        "travel_places",
        sa.Column("sigungu_name", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "travel_places",
        sa.Column("admin_code_source", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "travel_places",
        sa.Column("admin_code_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_travel_places_legal_dong_code", "travel_places", ["legal_dong_code"])
    op.create_index("ix_travel_places_sigungu_code", "travel_places", ["sigungu_code"])

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
UPDATE travel_places
   SET category = :unknown_label
 WHERE category IS NULL OR btrim(category) = ''
"""
        ),
        {"unknown_label": UNKNOWN_CATEGORY_LABEL},
    )
    conn.execute(
        sa.text(
            """
UPDATE travel_places
   SET category_code_suggestion = :unknown_code
 WHERE category_code_suggestion IS NULL
    OR btrim(category_code_suggestion) = ''
    OR category_code_suggestion NOT IN :codes
"""
        ).bindparams(sa.bindparam("codes", expanding=True)),
        {"unknown_code": UNKNOWN_CATEGORY_CODE, "codes": _category_codes()},
    )
    op.alter_column(
        "travel_places",
        "category",
        existing_type=sa.String(length=64),
        nullable=False,
        server_default=UNKNOWN_CATEGORY_LABEL,
    )
    op.alter_column(
        "travel_places",
        "category_code_suggestion",
        existing_type=sa.String(length=16),
        nullable=False,
        server_default=UNKNOWN_CATEGORY_CODE,
    )


def downgrade() -> None:
    op.alter_column(
        "travel_places",
        "category_code_suggestion",
        existing_type=sa.String(length=16),
        nullable=True,
        server_default=None,
    )
    op.alter_column(
        "travel_places",
        "category",
        existing_type=sa.String(length=64),
        nullable=True,
        server_default=None,
    )
    op.drop_index("ix_travel_places_sigungu_code", table_name="travel_places")
    op.drop_index("ix_travel_places_legal_dong_code", table_name="travel_places")
    op.drop_column("travel_places", "admin_code_updated_at")
    op.drop_column("travel_places", "admin_code_source")
    op.drop_column("travel_places", "sigungu_name")
    op.drop_column("travel_places", "sigungu_code")
    op.drop_column("travel_places", "legal_dong_name")
    op.drop_column("travel_places", "legal_dong_code")

    op.drop_index("ix_source_targets_default_category_code", table_name="source_targets")
    op.drop_column("source_targets", "default_category_code")
