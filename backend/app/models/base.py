"""ORM 공통 베이스와 믹스인.

`docs/architecture.md` 6장 엔티티 구조를 SQLAlchemy 2.0 선언형으로 구현하기 위한
공통 기반을 제공한다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """타임존 인식 UTC 현재 시각."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """모든 ORM 모델의 공통 베이스."""


class TimestampMixin:
    """`created_at` 컬럼을 부여하는 믹스인."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
