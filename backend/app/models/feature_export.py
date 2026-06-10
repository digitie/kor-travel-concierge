"""`feature_exports` 모델.

범용 feature 수집 API(`/api/v1/features/snapshot`·`/api/v1/features/changes`)가
downstream consumer에게 안정적인 full/incremental cursor와 tombstone을 제공하기
위한 export ledger다. 후보 테이블의 `updated_at`만 직접 노출하면 reject/tombstone
재전송과 payload checksum 비교가 어려우므로 별도 테이블로 둔다. `python-krtour-map`은
이 범용 API를 가져가는 첫 consumer다. (ADR-26, `docs/youtube-feature-pipeline-plan.md` 4.1)

`sequence`는 증가 cursor로 쓰는 bigint이며, payload가 의미 있게 바뀔 때마다 전용
PostgreSQL sequence에서 새 값을 받아 갱신한다. cursor는 opaque string으로 노출하고
consumer는 내용을 해석하지 않는다.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Sequence,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class FeatureExportOperation(str, Enum):
    """증분 응답이 알리는 변경 종류."""

    UPSERT = "upsert"
    REJECT = "reject"
    TOMBSTONE = "tombstone"


# full/incremental cursor용 단조 증가 sequence. payload가 바뀔 때마다 nextval로
# 새 값을 받아 row의 `sequence`를 갱신한다. 컬럼에 묶어 두면 `create_all`이 함께
# 생성하고, Alembic은 migration에서 명시 생성한다.
feature_export_sequence = Sequence("feature_export_sequence")


class FeatureExport(Base):
    __tablename__ = "feature_exports"
    __table_args__ = (
        Index(
            "ix_feature_exports_state_updated",
            "export_state",
            "updated_at",
            "export_id",
        ),
        Index(
            "ix_feature_exports_payload_json_gin",
            "payload_json",
            postgresql_using="gin",
        ),
    )

    export_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sequence: Mapped[int] = mapped_column(
        BigInteger,
        feature_export_sequence,
        nullable=False,
        unique=True,
        index=True,
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("extracted_place_candidates.id", ondelete="NO ACTION"),
        nullable=False,
        unique=True,
        index=True,
    )
    operation: Mapped[str] = mapped_column(
        String(16), nullable=False, default=FeatureExportOperation.UPSERT.value
    )
    export_state: Mapped[str] = mapped_column(String(16), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    last_exported_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
