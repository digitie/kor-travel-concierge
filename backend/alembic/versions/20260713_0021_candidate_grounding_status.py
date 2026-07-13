"""후보 raw grounding 상태 컬럼 (T-165, 로드맵 PR-13 개정판, B3·G4).

- `extracted_place_candidates.grounding_status`: 후보 근거(evidence_quote)가 원문
  소스에 실존하는지의 기계 검증 상태. transcript 후보는 `verified_raw`가 아니면
  지오코딩 자동확정과 feature export를 차단한다(표시가 아닌 상태 전이 게이트).
- **기존 행 backfill**: 이 게이트 도입 전 후보는 raw grounding을 확인한 적이 없으므로
  자동으로 신뢰하지 않는다 — `server_default='legacy_unknown'`으로 backfill해 재처리
  또는 사람 검수를 요구한다(NULL로 두지 않는다: 게이트 판정이 fail-open 되지 않도록).
- 신규 ORM insert는 모델 Python 기본값 `missing`(근거 미확인 fail-safe)을 쓰고,
  batch POI 추출 경로가 raw segment 대조 결과로 명시 세팅한다.
- 체인: 0020(transcript_attempts) → 0021(본 migration).

Revision ID: 20260713_0021
Revises: 20260713_0020
Create Date: 2026-07-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260713_0021"
down_revision = "20260713_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "extracted_place_candidates",
        sa.Column(
            "grounding_status",
            sa.String(length=32),
            nullable=False,
            server_default="legacy_unknown",
        ),
    )


def downgrade() -> None:
    op.drop_column("extracted_place_candidates", "grounding_status")
