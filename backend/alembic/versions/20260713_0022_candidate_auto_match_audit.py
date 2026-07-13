"""후보 auto-match audit 표본 컬럼·인덱스 (T-167, 로드맵 PR-14 개정판, G9).

자동확정(MATCHED, reviewer="system") 후보는 검수 큐에서 사라져 자동확정 정밀도(뒤집힘
비율)를 잴 표본이 없다(§7 지표). 일정 비율을 audit 표본으로 표시해 사람이 사후에
정확/오확정을 기록하고 오확정률을 집계할 수 있게 한다. 표본 표시·기록은 상태 전이가
아니라 사후 관측이므로 MATCHED·export 상태는 그대로 둔다.

- `audit_status`: NULL=표본 아님. `pending`|`accurate`|`misconfirmed`. nullable로 두고
  기존 행은 backfill하지 않는다(과거 자동확정을 소급 표본화하지 않음 — 신규 자동확정만 표본).
- `audit_reviewed_by`/`audit_reviewed_at`/`audit_note`: 사람 검토 메타데이터.
- 부분 인덱스 `ix_epc_audit_sample`(audit_status, id) WHERE audit_status IS NOT NULL:
  표본은 소수라 표본 큐 조회·오확정률 집계를 좁게 스캔한다.
- 체인: 0021(grounding_status) → 0022(본 migration).

Revision ID: 20260713_0022
Revises: 20260713_0021
Create Date: 2026-07-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260713_0022"
down_revision = "20260713_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "extracted_place_candidates",
        sa.Column("audit_status", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "extracted_place_candidates",
        sa.Column("audit_reviewed_by", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "extracted_place_candidates",
        sa.Column(
            "audit_reviewed_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "extracted_place_candidates",
        sa.Column("audit_note", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_epc_audit_sample",
        "extracted_place_candidates",
        ["audit_status", "id"],
        unique=False,
        postgresql_where=sa.text("audit_status IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_epc_audit_sample", table_name="extracted_place_candidates")
    op.drop_column("extracted_place_candidates", "audit_note")
    op.drop_column("extracted_place_candidates", "audit_reviewed_at")
    op.drop_column("extracted_place_candidates", "audit_reviewed_by")
    op.drop_column("extracted_place_candidates", "audit_status")
