"""`crawl_runs` 작업 테이블 모델.

Web REST, MCP, scheduler가 공유하는 단일 작업 테이블이다(ADR-13).
REST/MCP는 작업을 생성만 하고, scheduler 단일 실행자가 `pending` 작업을 claim해
실행한다. (`docs/architecture.md` 5장·6.8)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class RunState(str, Enum):
    """작업 상태."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class RunSource(str, Enum):
    """작업 생성 주체."""

    WEB = "web"
    MCP = "mcp"
    SCHEDULER = "scheduler"


class CrawlRun(TimestampMixin, Base):
    __tablename__ = "crawl_runs"
    __table_args__ = (
        Index("ix_crawl_runs_claim_pending", "state", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=RunState.PENDING, index=True
    )
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    current_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_log_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 작업 입력 파라미터(query/channel_id/playlist_id/max_videos 등) 직렬화
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 완료 요약 직렬화
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - 디버깅 편의
        return f"<CrawlRun id={self.id} job={self.job_type} state={self.state}>"
