"""Gemini API 키 전역 rate limit 상태(단일 행).

API·scheduler 두 프로세스가 같은 Gemini 키를 공유하므로, 분당 요청(RPM)·분당 토큰(TPM)·
일일 요청(RPD, PT 자정 리셋)을 DB 단일 행(id=1)에 기록하고 `FOR UPDATE`로 프로세스 간
직렬화한다(`ktc.etl.gemini_rate_limiter`). DeepSeek 등 비-Gemini 콜은 별도 쿼터라 대상 아님.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ktc.models.base import Base, utcnow


class GeminiRateState(Base):
    __tablename__ = "gemini_rate_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    # 현재 분 윈도우 시작 시각(UTC). now-start>=60s면 분 카운터를 리셋한다.
    minute_window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    minute_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    minute_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    # 일일 카운터(PT 자정 리셋). day_date는 PT 기준 "YYYY-MM-DD".
    day_date: Mapped[str] = mapped_column(String(10), default="", nullable=False)
    day_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
