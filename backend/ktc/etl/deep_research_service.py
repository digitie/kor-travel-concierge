"""장소 단위 Gemini Deep Research 실행 서비스.

`trigger_deep_research`가 만든 `deep_research` 작업을 scheduler가 실제로 처리할 수
있도록, 장소 상세 조사 프롬프트 구성, Gemini 호출, 결과 파싱, DB 반영을 한 곳에
모은다. 테스트에서는 `llm`을 주입해 외부 API 없이 검증한다.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ktc.core.config import get_settings
from ktc.etl.gemini_client import GeminiRequestError, post_generate_content
from ktc.models import TravelPlace
from ktc.services import settings_service

LlmCallable = Callable[[str], str]
StatusReporter = Callable[[str, float | None], Awaitable[None]]
GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class DeepResearchError(RuntimeError):
    """Deep Research 결과를 생성하거나 파싱하지 못한 경우."""


class DeepResearchResult(BaseModel):
    """Gemini Deep Research 구조화 결과."""

    detailed_research_content: str = ""
    gemini_enriched_description: str | None = None
    source_notes: list[str] = Field(default_factory=list)


RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "detailed_research_content": {"type": "string"},
        "gemini_enriched_description": {"type": "string"},
        "source_notes": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["detailed_research_content"],
}


async def _report(
    status_reporter: StatusReporter | None,
    message: str,
    progress: float | None = None,
) -> None:
    if status_reporter is not None:
        await status_reporter(message, progress)


def _compact(value: str | None) -> str:
    return " ".join(value.split()) if value else ""


def build_prompt(
    place: TravelPlace,
    *,
    prompt: str | None,
    max_sources: int,
) -> str:
    """장소 상세 조사를 위한 Gemini 프롬프트를 구성한다."""
    context = {
        "name": place.name,
        "category": place.category,
        "official_address": place.official_address,
        "road_address": place.road_address,
        "latitude": place.latitude,
        "longitude": place.longitude,
        "description": place.description,
        "gemini_enriched_description": place.gemini_enriched_description,
    }
    return (
        "다음 여행지 정보를 바탕으로 사용자가 여행 계획에 바로 활용할 수 있는 "
        "심층 소개를 한국어로 작성하라. 과장된 단정은 피하고, 근거가 불확실한 "
        "내용은 source_notes에 주의점으로 남겨라. "
        "반드시 주어진 JSON Schema에 맞는 JSON만 출력하라.\n\n"
        f"[장소 정보]\n{json.dumps(context, ensure_ascii=False)}\n\n"
        f"[사용자 추가 지시]\n{_compact(prompt) or '추가 지시 없음'}\n\n"
        f"[참고 출처 상한]\n최대 {max_sources}개 관점으로 정리\n"
    )


def parse_deep_research(payload: str) -> DeepResearchResult:
    """LLM JSON 문자열을 파싱·검증한다."""
    try:
        data = json.loads(payload)
        result = DeepResearchResult.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise DeepResearchError(f"Deep Research 결과 파싱 실패: {exc}") from exc
    if not result.detailed_research_content.strip():
        raise DeepResearchError("Deep Research 결과가 비어 있다")
    return result


def make_gemini_llm(
    *,
    api_key: str | None = None,
    model: str | None = None,
    timeout_seconds: float = 60.0,
) -> LlmCallable:
    """Gemini REST API를 호출하는 production `LlmCallable`을 만든다."""
    settings = get_settings()
    resolved_key = api_key or settings.GEMINI_API_KEY
    resolved_model = model or settings.GEMINI_ENGINE_VERSION
    if not resolved_key:
        raise ValueError("GEMINI_API_KEY가 필요하다")

    def call(prompt: str) -> str:
        try:
            data = post_generate_content(
                api_key=resolved_key,
                model=resolved_model,
                body={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "responseSchema": RESPONSE_JSON_SCHEMA,
                    },
                },
                timeout_seconds=timeout_seconds,
            )
        except GeminiRequestError as exc:
            raise DeepResearchError(
                "Gemini Deep Research 호출 실패"
                f"(status={exc.status_code}, model={resolved_model})"
            ) from exc
        return _extract_gemini_text(data)

    return call


def _extract_gemini_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise DeepResearchError("Gemini 응답에 candidates가 없다")
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        raise DeepResearchError("Gemini 응답에 content.parts가 없다")
    texts = [
        part.get("text")
        for part in parts
        if isinstance(part, dict) and part.get("text")
    ]
    if not texts:
        raise DeepResearchError("Gemini 응답 text가 비어 있다")
    return "\n".join(str(text) for text in texts)


async def research_place(
    session: AsyncSession,
    place: TravelPlace,
    *,
    prompt: str | None = None,
    max_sources: int = 8,
    llm: LlmCallable | None = None,
    status_reporter: StatusReporter | None = None,
) -> dict[str, Any]:
    """장소 1건의 Deep Research를 실행하고 결과를 DB에 저장한다."""
    await _report(
        status_reporter,
        f"{place.name} Deep Research 프롬프트를 구성했습니다.",
        0.25,
    )
    gemini_model = await settings_service.get_gemini_engine_version(session)
    resolved_llm = llm or make_gemini_llm(model=gemini_model)
    request_prompt = build_prompt(place, prompt=prompt, max_sources=max_sources)

    await _report(
        status_reporter,
        f"Gemini에서 {place.name} 상세 조사를 실행 중입니다.",
        0.45,
    )
    raw_result = await asyncio.to_thread(resolved_llm, request_prompt)
    result = parse_deep_research(raw_result)

    place.detailed_research_content = result.detailed_research_content
    if result.gemini_enriched_description:
        place.gemini_enriched_description = result.gemini_enriched_description
    place.last_reviewed_at = datetime.now(timezone.utc)
    await session.commit()

    await _report(
        status_reporter,
        f"{place.name} Deep Research 결과를 저장했습니다.",
        0.8,
    )
    return {
        "place_id": place.place_id,
        "place_name": place.name,
        "status": "researched",
        "detailed_research_content": result.detailed_research_content,
        "gemini_enriched_description": result.gemini_enriched_description,
        "source_notes": result.source_notes,
    }
