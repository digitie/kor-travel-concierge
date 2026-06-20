"""`video_place_mappings` 모델.

영상과 확정 장소의 N:M 관계 및 등장 구간·대표 프레임을 연결한다.
(`docs/architecture.md` 6.6)
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, validates

from ktc.models.base import Base, TimestampMixin
from ktc.models.feature_evidence import EvidenceSourceKind, FeatureExportStatus

# Gemini 타임스탬프 컬럼 길이(16자 제한 truncation 버그 대응, 라이브 E2E 발견).
TIMESTAMP_FIELD_LEN = 64


class VideoPlaceMapping(TimestampMixin, Base):
    __tablename__ = "video_place_mappings"

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
    place_id: Mapped[int] = mapped_column(
        ForeignKey("travel_places.place_id", ondelete="NO ACTION"),
        nullable=False,
        index=True,
    )
    place_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("extracted_place_candidates.id", ondelete="NO ACTION"),
        nullable=True,
        index=True,
    )
    ai_summary: Mapped[str] = mapped_column(Text, nullable=False)
    speaker_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp_start: Mapped[str | None] = mapped_column(
        String(TIMESTAMP_FIELD_LEN), nullable=True
    )
    timestamp_end: Mapped[str | None] = mapped_column(
        String(TIMESTAMP_FIELD_LEN), nullable=True
    )
    provider_evidence_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    feature_export_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=FeatureExportStatus.PENDING.value,
        index=True,
    )
    frame_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="NO ACTION"),
        nullable=True,
        index=True,
    )

    @validates("timestamp_start", "timestamp_end")
    def _clip_timestamp(self, _key: str, value: str | None) -> str | None:
        """비정상적으로 긴 Gemini 타임스탬프를 컬럼 길이로 방어적 클립한다."""
        if value is not None and len(value) > TIMESTAMP_FIELD_LEN:
            return value[:TIMESTAMP_FIELD_LEN]
        return value
