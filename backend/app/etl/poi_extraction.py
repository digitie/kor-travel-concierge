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

from pydantic import BaseModel, Field, ValidationError

# llm 시그니처: (prompt) -> JSON 문자열
LlmCallable = Callable[[str], str]


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
    """POI 추출 프롬프트를 구성한다."""
    return (
        "다음은 여행 YouTube 영상의 타임스탬프 자막과 영상 설명 원문이다. "
        "장소(POI)를 추출하고, 영상 설명의 오탈자·문맥을 보정하라. "
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
