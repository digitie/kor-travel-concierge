"""`video_place_mappings` 모델.

영상과 확정 장소의 N:M 관계 및 등장 구간·대표 프레임을 연결한다.
(`docs/architecture.md` 6.6)
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class VideoPlaceMapping(TimestampMixin, Base):
    __tablename__ = "video_place_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(
        ForeignKey("youtube_videos.video_id", ondelete="NO ACTION"),
        nullable=False,
        index=True,
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
    timestamp_start: Mapped[str | None] = mapped_column(String(16), nullable=True)
    timestamp_end: Mapped[str | None] = mapped_column(String(16), nullable=True)
    frame_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="NO ACTION"),
        nullable=True,
        index=True,
    )
