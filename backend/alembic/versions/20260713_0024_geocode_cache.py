"""provider별 지오코딩 응답 캐시 테이블 (T-170, S7).

같은 장소가 여러 영상에 반복 등장할 때 지오코딩 provider(정책상 캐시 허용은 Kakao뿐)를
매번 재호출하지 않도록 결과를 공유 DB 캐시에 저장한다. API/scheduler 2프로세스가 같은
캐시를 공유해야 하므로 프로세스 로컬이 아니라 테이블로 둔다. 만료 정리는 lazy(조회 시 TTL
초과 행 무시·덮어쓰기)이며 별도 정리 스케줄러는 두지 않는다.

이 migration은 origin/main의 현재 head(`20260713_0022`) 위에 체인한다. `0023`은 병렬
작업(T-183 audit idempotency)이 예약한 번호라 중복 revision id 충돌을 피하려고 `0024`를
쓰되 down_revision은 실제 head인 `0022`로 둔다(번호 gap은 alembic 그래프상 무해).

Revision ID: 20260713_0024
Revises: 20260713_0022
Create Date: 2026-07-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260713_0024"
down_revision = "20260713_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geocode_cache",
        sa.Column("query_hash", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("response_class", sa.String(length=16), nullable=False),
        sa.Column(
            "results_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("query_hash"),
    )


def downgrade() -> None:
    op.drop_table("geocode_cache")
