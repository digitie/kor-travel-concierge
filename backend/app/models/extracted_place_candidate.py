"""`extracted_place_candidates` 모델.

Gemini가 영상에서 추출했지만 아직 확정 장소와 매칭되지 않았거나, 사람이 검수해야
하는 후보를 저장한다. 지오코딩 실패·모호 결과는 자동 확정하지 않고
`match_status = needs_review`로 남긴다. (`docs/architecture.md` 4.5·6.5, ADR-16)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class MatchStatus(str, Enum):
    MATCHED = "matched"
    NEEDS_REVIEW = "needs_review"
    USER_CORRECTED = "user_corrected"
    IGNORED = "ignored"


class ExtractedPlaceCandidate(TimestampMixin, Base):
    __tablename__ = "extracted_place_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(
        ForeignKey("youtube_videos.video_id", ondelete="NO ACTION"),
        nullable=False,
        index=True,
    )
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    ai_place_name: Mapped[str] = mapped_column(String(255), nullable=False)
    speaker_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp_start: Mapped[str | None] = mapped_column(String(16), nullable=True)
    timestamp_end: Mapped[str | None] = mapped_column(String(16), nullable=True)
    candidate_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    match_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=MatchStatus.NEEDS_REVIEW, index=True
    )
    matched_place_id: Mapped[int | None] = mapped_column(
        ForeignKey("travel_places.place_id", ondelete="NO ACTION"), nullable=True
    )
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 검수 메타데이터
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
