"""`audit_logs` 모델.

웹/MCP/scheduler의 쓰기 작업을 감사 추적한다. 모든 MCP 쓰기 도구와 수동 보정은
이 테이블에 기록한다. (`docs/architecture.md` 6.10)
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from ktc.models.base import Base, TimestampMixin


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint(
            "(idempotency_key IS NULL AND idempotency_state IS NULL) OR "
            "(idempotency_key IS NOT NULL AND idempotency_key <> '' AND "
            "idempotency_state IS NOT NULL AND "
            "idempotency_state IN ('pending', 'final'))",
            name="ck_audit_logs_idempotency_pair",
        ),
        Index(
            "uq_audit_logs_actor_action_idempotency_key",
            "actor_type",
            "action",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
