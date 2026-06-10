"""YouTube 재생목록-영상 연결 테이블."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class YoutubePlaylistVideo(Base):
    __tablename__ = "youtube_playlist_videos"

    playlist_id: Mapped[str] = mapped_column(
        ForeignKey("youtube_playlists.playlist_id", ondelete="NO ACTION"),
        primary_key=True,
    )
    video_id: Mapped[str] = mapped_column(
        ForeignKey("youtube_videos.video_id", ondelete="NO ACTION"),
        primary_key=True,
    )
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    playlist_item_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    added_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
