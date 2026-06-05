"""`media_assets` 모델.

RustFS에 저장한 원본 동영상·자막·전사 결과·대표 프레임의 메타데이터를 저장한다.
대용량 바이너리는 DB에 넣지 않고 객체 URI·체크섬·크기만 기록한다. 보존 정책은
무기한이다. (`docs/architecture.md` 4.7·6.7, ADR-15)
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class AssetType(StrEnum):
    RAW_VIDEO = "raw_video"
    SUBTITLE = "subtitle"
    TRANSCRIPT = "transcript"
    FRAME = "frame"


class MediaAsset(TimestampMixin, Base):
    __tablename__ = "media_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    video_id: Mapped[str | None] = mapped_column(
        ForeignKey("youtube_videos.video_id"), nullable=True, index=True
    )
    place_id: Mapped[int | None] = mapped_column(
        ForeignKey("travel_places.place_id"), nullable=True
    )
    storage_provider: Mapped[str] = mapped_column(
        String(16), nullable=False, default="rustfs"
    )
    bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    object_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retention_policy: Mapped[str] = mapped_column(
        String(16), nullable=False, default="infinite"
    )
