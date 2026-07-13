"""`crawl_run_stage_events` durable 단계 이벤트 테이블 (T-162, 로드맵 PR-34/C7).

`status_log_json`은 UI 요약용 4필드(timestamp/level/message/progress)만 보존하고
최근 80건으로 절단되므로(C7), 단계별 구조화 측정(stage/provider/elapsed_ms/outcome)은
이 별도 테이블에 durable하게 저장한다.

**이 계측의 역할**: §7 "poi_batch 단계별 소요" 지표와 T-172 게이트("자막 fetch가
배치 시간 30%+")의 데이터 원천이다. 단계 소요(elapsed_ms)와 성공/실패/보류/건너뜀
집계가 목적이다.

**G7(provider별 시도 관측)은 이 계측의 범위가 아니다**: transcript_fetch 이벤트는
성공 provider 1개(transcript_api|yt-dlp|whisper)만 남기고 실패 시 provider=None이라,
"각 provider 시도·latency·outcome"(어느 provider가 몇 번 시도돼 실패/성공했는지)은
재구성할 수 없다. G7의 provider별 시도 관측은 별도 `transcript_attempts` 테이블
(T-164) 소관이다.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ktc.models.base import Base


class StageOutcome(str, Enum):
    """단계 실행 결과."""

    SUCCESS = "success"
    FAILURE = "failure"
    # 저장본 재사용 등으로 실행 자체를 건너뛴 경우.
    SKIPPED = "skipped"
    # 일일 쿼터 등으로 보류(추후 재처리)된 경우 — 비성공 done 구분 표시(T-180)의 원천.
    DEFERRED = "deferred"


class CrawlRunStageEvent(Base):
    __tablename__ = "crawl_run_stage_events"
    __table_args__ = (
        # run 단위 조회는 항상 `run_id` + `id` 오름차순(발생 순서)이다. 복합 인덱스의
        # 선두 컬럼이 run_id라 run_id 단독 조회도 이 인덱스로 커버된다(별도 단일
        # 인덱스 불필요).
        Index("ix_crawl_run_stage_events_run_id_id", "run_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 작업 삭제 시 이벤트도 함께 삭제한다(이벤트는 run에 종속된 측정치).
    run_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("crawl_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 예: transcript_fetch | correction | poi_extract | geocode |
    #     harvest_search | harvest_ingest
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    # 자막 provider(canonical: youtube_transcript_api|yt_dlp|whisper, T-164에서
    # transcript_attempts와 조인 위해 통일) 또는 LLM 모델명.
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 같은 단계의 재시도/부분 실행 순번(예: poi_extract sub-batch 순번, 1부터).
    attempt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 영상 단위 단계의 대상 식별자(video_id 등).
    item_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # monotonic clock 기반 실측 소요(밀리초). §7 지표·T-172 게이트가 이 값을 쓴다.
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - 디버깅 편의
        return (
            f"<CrawlRunStageEvent id={self.id} run={self.run_id} "
            f"stage={self.stage} outcome={self.outcome}>"
        )
