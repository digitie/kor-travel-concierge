"""`youtube_videos` 모델.

영상 설명 원문(`description_raw`)과 Gemini가 오탈자·문맥을 보정한 설명
(`description_gemini_corrected`)을 분리 저장한다. Gemini 결과는 원문을 덮어쓰지
않는다. (`docs/architecture.md` 4.4·6.3, ADR-16)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ktc.models.base import Base, utcnow


class CrawlStatus(str, Enum):
    DISCOVERED = "discovered"
    SUMMARIZED = "summarized"
    GEOCODED = "geocoded"
    DONE = "done"
    FAILED = "failed"


class YoutubeVideo(Base):
    __tablename__ = "youtube_videos"
    __table_args__ = (
        Index("ix_youtube_videos_source_search_query", "source_search_query"),
    )

    # 영상은 생성 시각보다 마지막 수집 시각이 도메인 상태라 `crawled_at`을 별도 유지한다.
    video_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    channel_id: Mapped[str] = mapped_column(
        ForeignKey("youtube_channels.channel_id", ondelete="NO ACTION"),
        nullable=False,
        index=True,
    )
    channel_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    canonical_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    default_language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tags_json: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    source_target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_target_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_search_query: Mapped[str | None] = mapped_column(String(255), nullable=True)
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
    gemini_url_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    gemini_url_summary_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    gemini_url_summary_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gemini_url_summary_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    transcript_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    reconciled_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    reconciled_summary_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    reconciled_summary_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    crawl_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=CrawlStatus.DISCOVERED
    )
    crawled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    # 검수에서 사용자가 제외(블록리스트)한 영상. 이후 수집 시 다시 받지 않고 스킵한다.
    is_excluded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    exclusion_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # 자막 확보 요약 캐시(T-164, PR-11). `transcript_attempts`에서 파생 갱신한다:
    # - transcript_source: 성공 provider(youtube_transcript_api|yt_dlp|whisper), 실패 시 None.
    # - transcript_failure_code: 최종 실패 대표 코드(no_captions|blocked|...), 성공 시 None.
    # 로그만으로는 SQL 선별이 불가하므로 컬럼으로 둔다 — T-168/169가 "자막 비활성 확정
    # 영상"을 선별하고 §7 수율 지표를 집계하는 원천이다.
    transcript_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    transcript_failure_code: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
