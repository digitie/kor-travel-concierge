"""`source_targets` 모델.

수집 대상(키워드/채널/재생목록/영상)과 다음 크롤 예정 시각을 관리한다.
(`docs/architecture.md` 6.2)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ktc.models.base import Base, TimestampMixin


class TargetType(str, Enum):
    KEYWORD = "keyword"
    CHANNEL = "channel"
    PLAYLIST = "playlist"
    VIDEO = "video"


class SourceTarget(TimestampMixin, Base):
    __tablename__ = "source_targets"
    __table_args__ = (
        UniqueConstraint(
            "target_type",
            "source_value",
            name="uq_source_targets_target_type_source_value",
        ),
        Index("ix_source_targets_active_next_crawl", "is_active", "next_crawl_at", "id"),
        Index(
            "ix_source_targets_budget_next_crawl",
            "api_budget_group",
            "is_active",
            "next_crawl_at",
            "id",
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
    scan_interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_seen_cursor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_seen_video_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    api_budget_group: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scan_failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_scan_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_scan_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
