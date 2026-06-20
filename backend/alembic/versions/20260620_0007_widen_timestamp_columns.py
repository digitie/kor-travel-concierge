"""widen POI 타임스탬프 컬럼 VARCHAR(16) -> VARCHAR(64).

`extracted_place_candidates`와 `video_place_mappings`의 `timestamp_start/end`가
VARCHAR(16)이라, Gemini가 16자 초과 타임스탬프(예: "00:22:00 - 00:35:00")를 반환하면
적재 시 StringDataRightTruncationError로 harvest 작업 전체가 롤백·실패했다(라이브 E2E 발견).
컬럼을 VARCHAR(64)로 넓힌다. 모델에는 추가로 방어적 클립(@validates)을 둔다. (T-089)

Revision ID: 20260620_0007
Revises: 20260610_0006
Create Date: 2026-06-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260620_0007"
down_revision = "20260610_0006"
branch_labels = None
depends_on = None

_TABLES = ("extracted_place_candidates", "video_place_mappings")


def upgrade() -> None:
    for table in _TABLES:
        for col in ("timestamp_start", "timestamp_end"):
            op.alter_column(
                table,
                col,
                existing_type=sa.String(length=16),
                type_=sa.String(length=64),
                existing_nullable=True,
            )


def downgrade() -> None:
    for table in _TABLES:
        for col in ("timestamp_start", "timestamp_end"):
            op.alter_column(
                table,
                col,
                existing_type=sa.String(length=64),
                type_=sa.String(length=16),
                existing_nullable=True,
            )
