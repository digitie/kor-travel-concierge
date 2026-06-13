"""YouTube 재생목록 정규 테이블."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ktc.models.base import Base, TimestampMixin


class YoutubePlaylist(TimestampMixin, Base):
    __tablename__ = "youtube_playlists"

    playlist_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    channel_id: Mapped[str] = mapped_column(
        ForeignKey("youtube_channels.channel_id", ondelete="NO ACTION"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    item_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_crawled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_item_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
