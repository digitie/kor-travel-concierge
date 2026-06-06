"""`youtube_videos` 모델.

영상 설명 원문(`description_raw`)과 Gemini가 오탈자·문맥을 보정한 설명
(`description_gemini_corrected`)을 분리 저장한다. Gemini 결과는 원문을 덮어쓰지
않는다. (`docs/architecture.md` 4.4·6.3, ADR-16)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class CrawlStatus(str, Enum):
    DISCOVERED = "discovered"
    SUMMARIZED = "summarized"
    GEOCODED = "geocoded"
    DONE = "done"
    FAILED = "failed"


class YoutubeVideo(Base):
    __tablename__ = "youtube_videos"

    video_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    channel_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    view_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    like_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engagement_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 영상 설명: 원문과 Gemini 보정본을 분리 저장한다.
    description_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_gemini_corrected: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_gemini_corrected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    description_gemini_model: Mapped[str | None] = mapped_column(String(64), nullable=True)

    crawl_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=CrawlStatus.DISCOVERED
    )
    crawled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
