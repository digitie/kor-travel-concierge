"""Gemini JSON Schema 기반 POI 추출.

타임스탬프가 포함된 자막을 Gemini에 전달하고 자유 텍스트가 아니라 JSON Schema
출력을 요구한다(`docs/architecture.md` 4.4). Gemini 결과는 영상 설명 원문을
덮어쓰지 않으며, 보정 설명·장소 보강 설명을 별도 필드로 반환한다(ADR-16).

실제 Gemini 호출은 주입형 `llm` 콜러블(prompt -> JSON 문자열)로 분리해, 키 없이도
파싱·검증·재시도 로직을 테스트할 수 있게 한다. 파싱 실패 시 재시도한다.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from ktc.etl import llm_client

# llm 시그니처: (prompt) -> JSON 문자열
LlmCallable = Callable[[str], str]
GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class ExtractedPOI(BaseModel):
    """자막에서 추출한 장소 후보."""

    name: str
    speaker_note: str | None = None
    gemini_enriched_description: str | None = None
    location_hint: str | None = None
    timestamp_start: str | None = None
    timestamp_end: str | None = None
    category: str | None = None


class POIExtractionResult(BaseModel):
    """Gemini POI 추출 결과 (JSON Schema 대응)."""

    summary: str = ""
    description_gemini_corrected: str | None = None
    places: list[ExtractedPOI] = Field(default_factory=list)


# Gemini `response_schema`에 전달할 JSON Schema (응답을 구조화 강제)
RESPONSE_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "description_gemini_corrected": {"type": "string"},
        "places": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "speaker_note": {"type": "string"},
                    "gemini_enriched_description": {"type": "string"},
                    "location_hint": {"type": "string"},
                    "timestamp_start": {"type": "string"},
                    "timestamp_end": {"type": "string"},
                    "category": {"type": "string"},
                },
                "required": ["name"],
            },
        },
    },
    "required": ["summary", "places"],
}


def build_prompt(*, timestamped_transcript: str, description_raw: str | None) -> str:
    """POI 추출 프롬프트를 구성한다.

    장소(POI)는 타임스탬프 자막뿐 아니라 영상 설명 원문에서도 추출한다. 영상 설명에는
    음성/자막에 나오지 않는 장소명·주소·링크가 적혀 있는 경우가 많으므로 두 출처를 모두
    근거로 삼는다. 동시에 영상 설명 원문은 보정 결과(`description_gemini_corrected`)에만
    반영하고 원문 자체는 덮어쓰지 않는다(ADR-16).
    """
    return (
        "다음은 여행 YouTube 영상의 타임스탬프 자막과 영상 설명 원문이다. "
        "타임스탬프 자막과 영상 설명 원문 양쪽에 등장하는 장소(POI)를 모두 추출하라. "
        "영상 설명에만 적혀 있고 자막에는 없는 장소도 빠짐없이 추출하라. "
        "그리고 영상 설명의 오탈자·문맥을 보정하라. "
        "반드시 주어진 JSON Schema에 맞는 JSON만 출력하라.\n\n"
        f"[영상 설명 원문]\n{description_raw or ''}\n\n"
        f"[타임스탬프 자막]\n{timestamped_transcript}\n"
    )


class POIExtractionError(RuntimeError):
    """재시도 후에도 유효한 결과를 얻지 못한 경우."""


def parse_extraction(payload: str) -> POIExtractionResult:
    """LLM JSON 문자열을 파싱·검증한다. 실패 시 예외."""
    data = json.loads(payload)  # JSONDecodeError 가능
    return POIExtractionResult.model_validate(data)  # ValidationError 가능


def extract_pois(
    *,
    timestamped_transcript: str,
    description_raw: str | None,
    llm: LlmCallable,
    max_retries: int = 2,
) -> POIExtractionResult:
    """Gemini로 POI를 추출한다. 파싱/검증 실패 시 재시도한다.

    `max_retries`회까지 재시도하며, 모두 실패하면 `POIExtractionError`를 던진다.
    """
    prompt = build_prompt(
        timestamped_transcript=timestamped_transcript, description_raw=description_raw
    )
    last_error: Exception | None = None
    for _ in range(max_retries + 1):
        try:
            payload = llm(prompt)
            return parse_extraction(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
            continue
    raise POIExtractionError(f"POI 추출 파싱 실패: {last_error}")


def make_llm(runtime: llm_client.LlmRuntime) -> LlmCallable:
    """선택된 엔진(Gemini/DeepSeek) + 사전 프롬프트로 POI 추출 `LlmCallable`을 만든다."""

    def call(prompt: str) -> str:
        try:
            return llm_client.complete_json(
                runtime, prompt, response_schema=RESPONSE_JSON_SCHEMA
            )
        except llm_client.LlmRequestError as exc:
            raise POIExtractionError(
                f"POI 추출 호출 실패(status={exc.status_code}, model={runtime.model})"
            ) from exc

    return call


def make_gemini_llm(
    *,
    api_key: str | None = None,
    model: str | None = None,
    timeout_seconds: float = 60.0,
) -> LlmCallable:
    """`.env`/인자 기반 production `LlmCallable` (BACK-COMPAT shim → make_llm)."""
    runtime = llm_client.LlmRuntime.from_settings(model=model)
    if api_key:
        runtime = replace(runtime, gemini_api_key=api_key)
    if not (runtime.gemini_api_key or runtime.is_deepseek):
        raise ValueError("GEMINI_API_KEY가 필요하다")
    return make_llm(runtime)


def _extract_gemini_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise POIExtractionError("Gemini 응답에 candidates가 없다")
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        raise POIExtractionError("Gemini 응답에 content.parts가 없다")
    texts = [part.get("text") for part in parts if isinstance(part, dict) and part.get("text")]
    if not texts:
        raise POIExtractionError("Gemini 응답 text가 비어 있다")
    return "\n".join(str(text) for text in texts)
