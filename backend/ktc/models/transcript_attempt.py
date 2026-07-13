"""`transcript_attempts` durable 관측 테이블 (T-164, 로드맵 PR-11 개정판, G7).

`crawl_run_stage_events`(T-162)의 `transcript_fetch` 이벤트는 성공 provider 1개만
남기고 실패 시 provider=None이라 "각 provider가 몇 번 시도돼 어떤 사유로 실패/성공
했는지"(G7)는 재구성할 수 없다. 이 테이블은 provider별 **모든** 시도(성공 전 실패
포함)를 순서·시각·소요·outcome·language·tool version과 함께 durable하게 보존한다.

역할 분리:
- stage events(T-162): 단계 소요 요약 1건(성공 provider만).
- transcript_attempts(본 테이블): provider별 시도 상세(실패 사유 코드 분류 포함).

`youtube_videos.transcript_source`/`transcript_failure_code`는 이 시도들에서 파생한
요약 캐시로, PR-17/18/19가 "자막 비활성 확정 영상"을 SQL로 선별하는 원천이다.

outcome enum(`TranscriptOutcomeCode`, `ktc.etl.transcript`):
    success | no_captions | blocked | rate_limited | download_error |
    parse_error | disabled | not_configured
provider enum(`TranscriptProviderName`, `ktc.etl.transcript`):
    youtube_transcript_api | yt_dlp | whisper
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ktc.models.base import Base


class TranscriptAttemptRecord(Base):
    __tablename__ = "transcript_attempts"
    __table_args__ = (
        # 영상 단위 조회는 항상 `video_id` + `id` 오름차순(시도 순서). 복합 인덱스의
        # 선두 컬럼이 video_id라 video_id 단독 조회도 이 인덱스로 커버된다.
        Index("ix_transcript_attempts_video_id_id", "video_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 시도 대상 영상. 관측 row는 영상에 종속되지만 삭제 정책은 다른 provenance FK와
    # 동일하게 NO ACTION(수동/명시 삭제 시에만 정리).
    video_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("youtube_videos.video_id", ondelete="NO ACTION"),
        nullable=False,
    )
    # 이 시도를 유발한 작업(있으면). 작업 삭제 시 관측 이력은 남긴다(SET NULL).
    run_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("crawl_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    # youtube_transcript_api | yt_dlp | whisper
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    # 체인 내 시도 순서(1부터). 실제 시도된 provider 순서를 그대로 보존한다.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 시도 소요(밀리초, monotonic 실측).
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # success | no_captions | blocked | rate_limited | download_error |
    # parse_error | disabled | not_configured
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    # 성공 시 확보 언어, yt-dlp 폴백 시 실제 트랙 언어(D7 수정).
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 실패 원문/예외 요약 등(분류 후에도 원 정보를 보존해 진단 가능).
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # provider 라이브러리 버전(수율 회귀를 라이브러리 변경과 연결).
    tool_version: Mapped[str | None] = mapped_column(String(32), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - 디버깅 편의
        return (
            f"<TranscriptAttemptRecord id={self.id} video={self.video_id} "
            f"provider={self.provider} outcome={self.outcome}>"
        )
