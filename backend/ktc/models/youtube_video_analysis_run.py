"""YouTube 영상 분석 실행 이력."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ktc.models.base import Base, TimestampMixin


class VideoAnalysisRunType(str, Enum):
    TRANSCRIPT_EXTRACT = "transcript_extract"
    URL_SUMMARY = "url_summary"
    RECONCILE = "reconcile"


class VideoAnalysisRunState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class YoutubeVideoAnalysisRun(TimestampMixin, Base):
    __tablename__ = "youtube_video_analysis_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(
        ForeignKey("youtube_videos.video_id", ondelete="NO ACTION"),
        nullable=False,
        index=True,
    )
    run_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    state: Mapped[str] = mapped_column(
        String(32), nullable=False, default=VideoAnalysisRunState.PENDING, index=True
    )
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="NO ACTION"),
        nullable=True,
        index=True,
    )
    summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
