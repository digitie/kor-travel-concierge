"""유튜브 STT 자막 교정(영상 단위, Gemini/DeepSeek 평문).

`config.TRANSCRIPT_CORRECTION_SYSTEM_INSTRUCTION`을 system instruction으로 쓰고, 영상 설명을
표기 근거로 함께 넣어 자막의 오탈자·고유명사·띄어쓰기를 교정한다. temperature는 낮게(0.1).
rate limiter 예약·thread 격리는 게이트웨이(`llm_client`)가 처리한다(T-161).
"""

from __future__ import annotations

from ktc.core.config import TRANSCRIPT_CORRECTION_SYSTEM_INSTRUCTION
from ktc.etl import llm_client

CORRECTION_TEMPERATURE = 0.1


def build_correction_prompt(*, transcript: str, description: str | None) -> str:
    """교정 user 프롬프트 — 영상 설명(표기 근거) + 교정 대상 자막."""
    desc = (description or "").strip() or "(없음)"
    return f"[영상 설명]\n{desc}\n\n[교정할 자막]\n{transcript}"


async def correct_transcript(
    runtime: llm_client.LlmRuntime,
    *,
    transcript: str,
    description: str | None,
    temperature: float = CORRECTION_TEMPERATURE,
) -> str:
    """자막을 교정해 평문(교정 자막)으로 반환한다. 실패 시 `LlmRequestError`."""
    prompt = build_correction_prompt(transcript=transcript, description=description)
    return await llm_client.complete_text(
        runtime,
        prompt,
        system_instruction=TRANSCRIPT_CORRECTION_SYSTEM_INSTRUCTION,
        temperature=temperature,
        # 단발 호출(rate limiter가 분당 한도를 강제하므로 429는 일일 쿼터 소진 신호 →
        # 느린 사람-유사 재시도로 묶음 작업이 ~1시간 멈추는 것을 막는다, best-effort).
        max_attempts=1,
    )
