"""`extracted_place_candidates` 모델.

Gemini가 영상에서 추출했지만 아직 확정 장소와 매칭되지 않았거나, 사람이 검수해야
하는 후보를 저장한다. 지오코딩 실패·모호 결과는 자동 확정하지 않고
`match_status = needs_review`로 남긴다. (`docs/architecture.md` 4.5·6.5, ADR-16)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, validates

from ktc.models.base import Base, TimestampMixin
from ktc.models.feature_evidence import EvidenceSourceKind, FeatureExportStatus

# Gemini가 반환하는 타임스탬프 문자열 컬럼 길이. 과거 16자 제한이 16자 초과 타임스탬프
# (예: "00:22:00 - 00:35:00")에서 truncation 오류를 냈다(라이브 E2E 발견). 넉넉히 64자로 둔다.
TIMESTAMP_FIELD_LEN = 64


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
    source_channel_id: Mapped[str | None] = mapped_column(
        ForeignKey("youtube_channels.channel_id", ondelete="NO ACTION"),
        nullable=True,
        index=True,
    )
    source_playlist_id: Mapped[str | None] = mapped_column(
        ForeignKey("youtube_playlists.playlist_id", ondelete="NO ACTION"),
        nullable=True,
        index=True,
    )
    analysis_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("youtube_video_analysis_runs.id", ondelete="NO ACTION"),
        nullable=True,
        index=True,
    )
    source_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default=EvidenceSourceKind.TRANSCRIPT.value
    )
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    ai_place_name: Mapped[str] = mapped_column(String(255), nullable=False)
    speaker_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp_start: Mapped[str | None] = mapped_column(
        String(TIMESTAMP_FIELD_LEN), nullable=True
    )
    timestamp_end: Mapped[str | None] = mapped_column(
        String(TIMESTAMP_FIELD_LEN), nullable=True
    )
    candidate_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    match_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=MatchStatus.NEEDS_REVIEW, index=True
    )
    matched_place_id: Mapped[int | None] = mapped_column(
        ForeignKey("travel_places.place_id", ondelete="NO ACTION"),
        nullable=True,
        index=True,
    )
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider_evidence_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    feature_export_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=FeatureExportStatus.PENDING.value,
        index=True,
    )
    # 검수 메타데이터
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    @validates("timestamp_start", "timestamp_end")
    def _clip_timestamp(self, _key: str, value: str | None) -> str | None:
        """비정상적으로 긴 Gemini 타임스탬프를 컬럼 길이로 방어적 클립한다."""
        if value is not None and len(value) > TIMESTAMP_FIELD_LEN:
            return value[:TIMESTAMP_FIELD_LEN]
        return value
