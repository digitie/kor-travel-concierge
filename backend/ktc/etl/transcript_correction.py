"""유튜브 STT 자막 교정(영상 단위, Gemini/DeepSeek 평문).

`config.TRANSCRIPT_CORRECTION_SYSTEM_INSTRUCTION`을 system instruction으로 쓰고, 영상 설명을
표기 근거로 함께 넣어 자막의 오탈자·고유명사·띄어쓰기를 교정한다. temperature는 낮게(0.1).
Gemini로 가는 경우 키 전역 rate limiter를 통과한 뒤 호출한다(DeepSeek는 별도 쿼터라 제외).
"""

from __future__ import annotations

import asyncio

from ktc.core.config import TRANSCRIPT_CORRECTION_SYSTEM_INSTRUCTION
from ktc.etl import gemini_rate_limiter, llm_client

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
    if not runtime.is_deepseek:
        await gemini_rate_limiter.acquire(
            estimated_tokens=gemini_rate_limiter.estimate_tokens(
                TRANSCRIPT_CORRECTION_SYSTEM_INSTRUCTION, prompt
            )
        )
    return await asyncio.to_thread(
        llm_client.complete_text,
        runtime,
        prompt,
        system_instruction=TRANSCRIPT_CORRECTION_SYSTEM_INSTRUCTION,
        temperature=temperature,
    )
