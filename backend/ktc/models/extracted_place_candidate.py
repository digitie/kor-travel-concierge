"""`extracted_place_candidates` 모델.

Gemini가 영상에서 추출했지만 아직 확정 장소와 매칭되지 않았거나, 사람이 검수해야
하는 후보를 저장한다. 지오코딩 실패·모호 결과는 자동 확정하지 않고
`match_status = needs_review`로 남긴다. (`docs/architecture.md` 4.5·6.5, ADR-16)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, validates

from ktc.models.base import Base, TimestampMixin
from ktc.models.feature_evidence import (
    EvidenceSourceKind,
    FeatureExportStatus,
    GroundingStatus,
)

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
    __table_args__ = (
        # soft delete 시 사유를 강제한다(T-160, 로드맵 B1 절차 5).
        CheckConstraint(
            "deleted_at IS NULL OR deletion_reason IS NOT NULL",
            name="ck_epc_deleted_requires_reason",
        ),
        # 검수 큐 access path는 항상 `deleted_at IS NULL`을 포함하므로(T-160)
        # T-154의 복합 인덱스 3종을 같은 이름의 partial index로 대체한다.
        Index(
            "ix_epc_review_queue_status_id",
            "match_status",
            "id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_epc_review_queue_channel_status_id",
            "source_channel_id",
            "match_status",
            "id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_epc_review_queue_playlist_status_id",
            "source_playlist_id",
            "match_status",
            "id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

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
    # 근거(evidence)가 원문 소스에 실존하는지의 기계 검증 상태(T-165, 로드맵 B3·G4).
    # transcript 후보는 `verified_raw`가 아니면 자동확정·export를 차단한다(표시가 아닌
    # 상태 전이 게이트). 신규 ORM insert 기본값은 `missing`(근거 미확인 fail-safe)이며,
    # 이 게이트 도입 전 기존 행은 migration이 `legacy_unknown`으로 backfill한다.
    # 향후 비-transcript producer(description=T-168, visual=T-173)는 각자의 grounding
    # 규칙을 적용하거나, 규칙 도입 전까지 생성 시 `not_applicable`을 명시 세팅한다
    # (현재 게이트는 transcript 전용이라 비-transcript의 `missing` 기본값은 무해).
    grounding_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=GroundingStatus.MISSING.value,
        server_default=GroundingStatus.LEGACY_UNKNOWN.value,
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
    # POI 추출 LLM이 판정한 국내 여부. None=미판정, True=대한민국, False=해외(검수만, 미확정).
    is_domestic: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    provider_evidence_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    feature_export_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=FeatureExportStatus.PENDING.value,
        index=True,
    )
    # soft delete 상태(T-160, 로드맵 B1). 후보는 감사 가능한 도메인 기록이므로 물리
    # 삭제하지 않는다. `deleted_at IS NOT NULL`이면 삭제된 것으로 보고 검수 큐·dedup·
    # 자동 처리·export 스캔에서 제외한다. reopen은 세 필드를 모두 clear 한다.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deletion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
