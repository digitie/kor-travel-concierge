"""Gemini API 키 전역 rate limiter (DB 단일 행, 순차).

API·scheduler 두 프로세스가 같은 Gemini 키를 공유하므로, 분당 요청(RPM)·분당 토큰(TPM)·
일일 요청(RPD, PT 자정 리셋)을 DB 단일 행에 `FOR UPDATE`로 기록해 강제한다. 병렬은 쓰지
않으며(순차), 한도 초과 시 분 윈도우가 풀릴 때까지 대기(RPM/TPM)하고, 일일 한도면
`GeminiQuotaExceeded`를 던져 작업을 보류시킨다. DeepSeek 등 비-Gemini 콜은 대상이 아니다.

사용: 동기 Gemini 호출을 `asyncio.to_thread`로 감싸기 **직전**에 `await acquire(...)`로 슬롯을
예약한다. 모든 Gemini 호출부(파이프라인·검수 의견·deep research)가 같은 카운터를 공유한다.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ktc.core.config import get_settings
from ktc.core.database import async_session_factory
from ktc.models import GeminiRateState

_PT = ZoneInfo("America/Los_Angeles")
_RATE_STATE_ID = 1
_MAX_WAIT_LOOPS = 120  # 분 윈도우 대기 안전장치(최대 ~2시간)


class GeminiQuotaExceeded(RuntimeError):
    """일일 쿼터(RPD) 소진 — 작업을 다음 PT 일자로 보류한다."""


def estimate_tokens(*parts: str) -> int:
    """프롬프트 토큰 대략 추정(한국어 혼합, 보수적). 출력 여유분 포함.

    정확한 토큰화 대신 문자 수 기반 근사다. TPM 한도를 넘지 않도록 다소 보수적으로
    잡고 출력 버퍼를 더한다. 실제 사용량과 다를 수 있으나 윈도우 한도의 안전 마진 용도다.
    """
    chars = sum(len(p or "") for p in parts)
    return chars // 2 + 2048


async def _ensure_row() -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                pg_insert(GeminiRateState)
                .values(
                    id=_RATE_STATE_ID,
                    minute_window_start=datetime.now(timezone.utc),
                    minute_count=0,
                    minute_tokens=0,
                    day_date="",
                    day_count=0,
                )
                .on_conflict_do_nothing(index_elements=["id"])
            )


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


async def acquire(*, estimated_tokens: int) -> None:
    """Gemini 콜 1건 전에 호출한다.

    RPM/TPM 초과면 분 윈도우가 풀릴 때까지 대기, RPD 초과면 `GeminiQuotaExceeded`.
    키 전역(DB 단일 행 `FOR UPDATE`)으로 순차 직렬화한다.
    """
    settings = get_settings()
    rpm, rpd, tpm = (
        settings.GEMINI_RATE_RPM,
        settings.GEMINI_RATE_RPD,
        settings.GEMINI_RATE_TPM,
    )
    # 단일 호출 추정 토큰이 분당 한도를 넘으면 어떤 윈도우에서도 들어맞지 않는다 →
    # 무한 대기 대신 즉시 보류(입력 절단은 호출부 책임).
    if estimated_tokens > tpm:
        raise GeminiQuotaExceeded(
            f"단일 호출 추정 토큰({estimated_tokens})이 분당 한도(TPM={tpm})를 초과한다."
        )
    await _ensure_row()
    for _ in range(_MAX_WAIT_LOOPS):
        wait_seconds = 0.0
        async with async_session_factory() as session:
            async with session.begin():
                state = (
                    await session.execute(
                        select(GeminiRateState)
                        .where(GeminiRateState.id == _RATE_STATE_ID)
                        .with_for_update()
                    )
                ).scalar_one()
                now = datetime.now(timezone.utc)
                pt_today = datetime.now(_PT).strftime("%Y-%m-%d")
                if state.day_date != pt_today:
                    state.day_date = pt_today
                    state.day_count = 0
                window_age = (now - _as_utc(state.minute_window_start)).total_seconds()
                if window_age >= 60.0:
                    state.minute_window_start = now
                    state.minute_count = 0
                    state.minute_tokens = 0
                    window_age = 0.0
                if state.day_count >= rpd:
                    raise GeminiQuotaExceeded(
                        f"Gemini 일일 한도({rpd}) 소진 — PT {pt_today}"
                    )
                fits = (
                    state.minute_count < rpm
                    and state.minute_tokens + estimated_tokens <= tpm
                )
                if fits:
                    state.minute_count += 1
                    state.minute_tokens += estimated_tokens
                    state.day_count += 1
                    return  # 컨텍스트 종료 시 commit(예약 확정)
                wait_seconds = max(1.0, 60.0 - window_age + 0.5)
        await asyncio.sleep(wait_seconds)
    raise GeminiQuotaExceeded("Gemini rate limit 대기 한도를 초과했습니다.")
