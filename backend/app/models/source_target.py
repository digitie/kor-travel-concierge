"""`source_targets` 모델.

수집 대상(키워드/채널/재생목록)과 다음 크롤 예정 시각을 관리한다.
(`docs/architecture.md` 6.2)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class TargetType(str, Enum):
    KEYWORD = "keyword"
    CHANNEL = "channel"
    PLAYLIST = "playlist"


class SourceTarget(TimestampMixin, Base):
    __tablename__ = "source_targets"
    __table_args__ = (
        UniqueConstraint(
            "target_type",
            "source_value",
            name="uq_source_targets_target_type_source_value",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_value: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_crawled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_crawl_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
