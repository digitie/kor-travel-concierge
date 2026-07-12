"""candidate soft delete 상태 모델 (T-160, 로드맵 B1).

- `extracted_place_candidates`에 `deleted_at`/`deletion_reason`/`deleted_by`를 추가한다.
  후보 삭제·영상 제외는 이제 행을 물리 삭제하지 않고 soft delete 하며, 같은
  트랜잭션에서 export ledger(`feature_exports`)를 tombstone으로 전환한다
  (ledger 선삭제가 tombstone 발행을 원천 차단하던 문제 해소).
- CHECK `ck_epc_deleted_requires_reason`: 삭제 시 사유가 필수다.
- 인덱스 대체 근거: 검수 큐 access path(`list_unmatched_candidates` —
  `match_status='needs_review'` [+ channel/playlist] + `ORDER BY id DESC`)는 T-160
  이후 **항상** `deleted_at IS NULL` 조건을 포함한다. 그 외에 이 3종 인덱스를 쓸 수
  있던 조회는 운영 지표 `match_status` group-by(전수 집계라 인덱스 이득 없음)와
  `video_id` 기반 조회(별도 `video_id` 인덱스 사용)뿐이므로, 전체 인덱스와 partial
  인덱스를 두 벌 유지할 이유가 없다. T-154의 복합 인덱스 3종을 같은 이름의
  `WHERE deleted_at IS NULL` partial index로 **대체**한다(기존 행은 전부
  `deleted_at IS NULL`이라 커버리지 동일, 쓰기 비용은 동일 이하).

Revision ID: 20260713_0016
Revises: 20260710_0015
Create Date: 2026-07-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260713_0016"
down_revision = "20260710_0015"
branch_labels = None
depends_on = None

_REVIEW_QUEUE_INDEXES: list[tuple[str, list[str]]] = [
    ("ix_epc_review_queue_status_id", ["match_status", "id"]),
    (
        "ix_epc_review_queue_channel_status_id",
        ["source_channel_id", "match_status", "id"],
    ),
    (
        "ix_epc_review_queue_playlist_status_id",
        ["source_playlist_id", "match_status", "id"],
    ),
]


def upgrade() -> None:
    op.add_column(
        "extracted_place_candidates",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "extracted_place_candidates",
        sa.Column("deletion_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "extracted_place_candidates",
        sa.Column("deleted_by", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        "ck_epc_deleted_requires_reason",
        "extracted_place_candidates",
        "deleted_at IS NULL OR deletion_reason IS NOT NULL",
    )
    for name, columns in _REVIEW_QUEUE_INDEXES:
        op.drop_index(name, table_name="extracted_place_candidates")
        op.create_index(
            name,
            "extracted_place_candidates",
            columns,
            postgresql_where=sa.text("deleted_at IS NULL"),
        )


def downgrade() -> None:
    for name, columns in reversed(_REVIEW_QUEUE_INDEXES):
        op.drop_index(name, table_name="extracted_place_candidates")
        op.create_index(name, "extracted_place_candidates", columns)
    op.drop_constraint(
        "ck_epc_deleted_requires_reason",
        "extracted_place_candidates",
        type_="check",
    )
    op.drop_column("extracted_place_candidates", "deleted_by")
    op.drop_column("extracted_place_candidates", "deletion_reason")
    op.drop_column("extracted_place_candidates", "deleted_at")
