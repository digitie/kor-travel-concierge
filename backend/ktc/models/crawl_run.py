"""`crawl_runs` 작업 테이블 모델.

Web REST, MCP, scheduler가 공유하는 단일 작업 테이블이다(ADR-13).
REST/MCP는 작업을 생성만 하고, scheduler 단일 실행자가 `pending` 작업을 claim해
실행한다. (`docs/architecture.md` 5장·6.8)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

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
from sqlalchemy.orm import Mapped, mapped_column

from ktc.models.base import Base, TimestampMixin


class RunState(str, Enum):
    """작업 상태."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    # 사용자 요청으로 중지된 작업. pending이면 claim 전에, running이면 협조적 취소로 전이한다.
    CANCELLED = "cancelled"


# 재시작 허용·attention 판단 기준이 되는 종료 상태 집합(T-162).
TERMINAL_RUN_STATES: tuple[RunState, ...] = (
    RunState.DONE,
    RunState.FAILED,
    RunState.CANCELLED,
)


class RunAttention(str, Enum):
    """실패 작업 주의(attention) 상태 (T-162, 로드맵 B6). NULL이면 해당 없음(none).

    - open: 실패 직후, 사용자 확인 전.
    - acknowledged: 사용자가 확인(acknowledge API).
    - superseded: 재시작 run이 생성되어 최신 attempt가 아니게 됨.
    - resolved: 재시작 run이 done으로 완료되어 해소됨(superseded에서도 승격).
    """

    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    SUPERSEDED = "superseded"
    RESOLVED = "resolved"


class RunSource(str, Enum):
    """작업 생성 주체."""

    WEB = "web"
    MCP = "mcp"
    SCHEDULER = "scheduler"


class CrawlRun(TimestampMixin, Base):
    __tablename__ = "crawl_runs"
    __table_args__ = (
        Index("ix_crawl_runs_claim_pending", "state", "id"),
        # attention 배지/필터 조회용(T-181). 대부분의 행은 NULL이므로 partial index.
        Index(
            "ix_crawl_runs_attention",
            "attention",
            postgresql_where=text("attention IS NOT NULL"),
        ),
        CheckConstraint(
            "attention IN ('open', 'acknowledged', 'superseded', 'resolved')",
            name="ck_crawl_runs_attention_valid",
        ),
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
    # 실행 중 작업에 대한 협조적 중지 신호. 실행자(heartbeat watcher)가 폴링해 작업을 취소한다.
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # 재시작 lineage: 이 run이 어느 run의 재시작인지(self FK, T-162). 같은 원본의
    # active(pending/running) 재시작은 1개만 허용한다(중복 클릭 멱등).
    # 원본 lane 복사는 T-163 소관(lane 컬럼 도입 시 create_restart_run에서 처리).
    restart_of_run_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("crawl_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # 실패 attention 상태(RunAttention). NULL=해당 없음. 전이는 crawl_run_service가
    # 단독 소유한다(mark_failed→open, 재시작 생성→superseded, 재시작 done→resolved).
    attention: Mapped[str | None] = mapped_column(String(16), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - 디버깅 편의
        return f"<CrawlRun id={self.id} job={self.job_type} state={self.state}>"
