"""검수 후보 일괄 처리의 durable preview·실행 상태(T-185).

필터 전체 작업은 목록 cursor만으로 멤버십을 고정할 수 없다. preview 시점의 후보 ID와
revision을 item 행으로 물리화하고, 짧은 수명의 confirmation token은 평문 대신 hash만
operation 행에 저장한다. 실행 receipt는 별도 ledger 행에 남겨 응답 유실 뒤 과거 어느
request든 멱등 재생한다.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from ktc.models.base import Base, utcnow


class ReviewBulkAction(str, Enum):
    IGNORE = "ignore"
    DELETE = "delete"
    REOPEN = "reopen"


class ReviewBulkOperationStatus(str, Enum):
    PREVIEWED = "previewed"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"


class ReviewBulkItemStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    CONFLICT = "conflict"
    FAILED = "failed"


class ReviewBulkOperation(Base):
    __tablename__ = "review_bulk_operations"
    __table_args__ = (
        CheckConstraint(
            "action IN ('ignore', 'delete', 'reopen')",
            name="ck_review_bulk_operations_action",
        ),
        CheckConstraint(
            "scope_kind IN ('selection', 'filter')",
            name="ck_review_bulk_operations_scope_kind",
        ),
        CheckConstraint(
            "status IN ('previewed', 'running', 'completed', "
            "'completed_with_errors')",
            name="ck_review_bulk_operations_status",
        ),
        CheckConstraint(
            "total_count >= 0 AND processed_count >= 0 "
            "AND succeeded_count >= 0 AND conflict_count >= 0 "
            "AND failed_count >= 0 AND processed_count <= total_count "
            "AND processed_count = succeeded_count + conflict_count + failed_count",
            name="ck_review_bulk_operations_counts",
        ),
        CheckConstraint(
            "jsonb_typeof(scope_json) = 'object'",
            name="ck_review_bulk_operations_scope_json_object",
        ),
        Index("ix_review_bulk_operations_status_created", "status", "created_at"),
    )

    operation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    scope_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ReviewBulkOperationStatus.PREVIEWED.value
    )
    confirmation_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmation_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    succeeded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conflict_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_cursor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ReviewBulkOperationReceipt(Base):
    __tablename__ = "review_bulk_operation_receipts"
    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(response_json) = 'object'",
            name="ck_review_bulk_operation_receipts_response_object",
        ),
    )

    operation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("review_bulk_operations.operation_id", ondelete="CASCADE"),
        primary_key=True,
    )
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    request_cursor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class ReviewBulkOperationItem(Base):
    __tablename__ = "review_bulk_operation_items"
    __table_args__ = (
        CheckConstraint(
            "snapshot_revision > 0",
            name="ck_review_bulk_operation_items_revision_positive",
        ),
        CheckConstraint(
            "snapshot_review_state IN "
            "('needs_review', 'ignored', 'deleted', 'matched', 'user_corrected')",
            name="ck_review_bulk_operation_items_review_state",
        ),
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'conflict', 'failed')",
            name="ck_review_bulk_operation_items_status",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_review_bulk_operation_items_attempt_count",
        ),
        CheckConstraint(
            "(snapshot_matched_place_id IS NULL AND "
            "snapshot_matched_place_revision IS NULL) OR "
            "(snapshot_matched_place_id IS NOT NULL AND "
            "snapshot_matched_place_revision IS NOT NULL)",
            name="ck_review_bulk_operation_items_place_revision_pair",
        ),
        Index(
            "ix_review_bulk_operation_items_pending",
            "operation_id",
            "status",
            "candidate_id",
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_review_bulk_operation_items_candidate_id", "candidate_id"),
    )

    operation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("review_bulk_operations.operation_id", ondelete="CASCADE"),
        primary_key=True,
    )
    candidate_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("extracted_place_candidates.id", ondelete="NO ACTION"),
        primary_key=True,
    )
    snapshot_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    snapshot_review_state: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot_matched_place_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    snapshot_matched_place_revision: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    reopen_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ReviewBulkItemStatus.PENDING.value
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
