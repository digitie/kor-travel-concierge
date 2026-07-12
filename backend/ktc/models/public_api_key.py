"""외부 공개 API 키 모델.

Web UI에서 생성한 VWorld 호환 `key` 값을 평문으로 저장하지 않고 SHA-256 해시와
마지막 6자리 힌트만 보관한다.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ktc.models.base import Base, TimestampMixin


class PublicApiKey(TimestampMixin, Base):
    __tablename__ = "public_api_keys"
    __table_args__ = (
        CheckConstraint(
            "scope IN ('read', 'admin')",
            name="ck_public_api_keys_scope",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    key_hint: Mapped[str] = mapped_column(String(12), nullable=False)
    scope: Mapped[str] = mapped_column(
        String(16), nullable=False, default="read", server_default="read"
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
