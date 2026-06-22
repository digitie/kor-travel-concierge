"""provider-agnostic LLM 호출 디스패치 (Gemini / DeepSeek) + 사전 프롬프트.

모든 ETL AI 호출은 이 모듈의 `complete_json`을 통해 선택된 엔진으로 분기한다.

- 엔진 문자열이 `deepseek-*`이면 DeepSeek(OpenAI 호환)으로, 그 외(`gemini-*`)는 Gemini로 보낸다.
- 사용자 사전 프롬프트(`runtime.preprompt`)를 모든 프롬프트 앞에 prepend한다.
- 응답 JSON 스키마는 Gemini는 `responseSchema`로 강제하고, DeepSeek는 스키마를
  프롬프트에 덧붙이고 `response_format=json_object`로 JSON 출력을 강제한다.

장소 후보 추출·키워드 정제·요약 등 텍스트 기반 호출은 두 provider 모두 지원한다.
공개 YouTube URL을 Gemini가 직접 분석하는 경로(`file_data.file_uri`)는 Gemini 전용이라
이 디스패처를 쓰지 않는다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ktc.core.config import get_settings, is_deepseek_model
from ktc.etl import deepseek_client, gemini_client


class LlmRequestError(RuntimeError):
    """provider 호출이 재시도 후에도 실패한 경우(상태코드/모델 포함)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        model: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.model = model


@dataclass(frozen=True)
class LlmRuntime:
    """선택된 엔진과 provider별 키/사전 프롬프트 묶음.

    DB 오버라이드가 가능한 값들(`settings_service.get_llm_runtime`)을 한 번에 모아
    호출부 closure에 캡처한다.
    """

    model: str
    gemini_api_key: str = ""
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    preprompt: str = ""

    @classmethod
    def from_settings(cls, *, model: str | None = None, preprompt: str | None = None) -> "LlmRuntime":
        """`.env` 기반 런타임(DB 오버라이드 없이). 세션이 없는 경로에서 쓴다."""
        settings = get_settings()
        return cls(
            model=model or settings.GEMINI_ENGINE_VERSION,
            gemini_api_key=settings.GEMINI_API_KEY,
            deepseek_api_key=settings.DEEPSEEK_API_KEY,
            deepseek_base_url=settings.DEEPSEEK_BASE_URL,
            preprompt=settings.AI_PREPROMPT if preprompt is None else preprompt,
        )

    @property
    def is_deepseek(self) -> bool:
        return is_deepseek_model(self.model)


def compose_prompt(preprompt: str, prompt: str) -> str:
    """사전 프롬프트를 본 프롬프트 앞에 붙인다(비어 있으면 그대로)."""
    pre = (preprompt or "").strip()
    if not pre:
        return prompt
    return f"{pre}\n\n---\n\n{prompt}"


def build_gemini_body(
    prompt: str,
    response_schema: dict[str, Any] | None,
    *,
    system_instruction: str | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    """Gemini `generateContent` 요청 body. responseSchema·systemInstruction·temperature 지원."""
    body: dict[str, Any] = {"contents": [{"parts": [{"text": prompt}]}]}
    generation_config: dict[str, Any] = {}
    if response_schema is not None:
        generation_config["responseMimeType"] = "application/json"
        generation_config["responseSchema"] = response_schema
    if temperature is not None:
        generation_config["temperature"] = temperature
    if generation_config:
        body["generationConfig"] = generation_config
    if system_instruction:
        body["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    return body


def extract_gemini_text(payload: dict[str, Any], *, model: str | None = None) -> str:
    """Gemini 응답에서 candidates[0].content.parts[*].text를 모아 반환한다."""
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise LlmRequestError("Gemini 응답에 candidates가 없다", model=model)
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        raise LlmRequestError("Gemini 응답에 content.parts가 없다", model=model)
    texts = [part.get("text") for part in parts if isinstance(part, dict) and part.get("text")]
    if not texts:
        raise LlmRequestError("Gemini 응답 text가 비어 있다", model=model)
    return "\n".join(str(text) for text in texts)


def _deepseek_prompt_with_schema(prompt: str, response_schema: dict[str, Any] | None) -> str:
    if response_schema is None:
        return prompt
    schema_text = json.dumps(response_schema, ensure_ascii=False)
    return (
        f"{prompt}\n\n[출력 JSON Schema]\n{schema_text}\n"
        "위 스키마에 정확히 맞는 JSON 객체 하나만 반환하라. 코드펜스(```)나 설명 문장은 붙이지 마라."
    )


def complete_json(
    runtime: LlmRuntime,
    prompt: str,
    *,
    response_schema: dict[str, Any] | None = None,
    system_instruction: str | None = None,
    temperature: float | None = None,
    timeout_seconds: float = 120.0,
    max_attempts: int | None = None,
) -> str:
    """선택된 엔진으로 prompt를 보내고 문자열 응답을 반환한다.

    실패 시 provider 무관 `LlmRequestError`를 던진다(호출부가 자기 에러로 감싼다).
    `max_attempts`를 주면 provider의 느린 사람-유사 재시도 횟수를 덮어쓴다(대화형은 1).
    `system_instruction`을 주면 사전 프롬프트 대신 그것을 시스템 지시로 쓰고 prepend하지
    않는다(자막 교정·POI 배치처럼 전용 지시문이 있는 경우). `response_schema=None`이면
    JSON 강제 없이 평문 응답을 받는다. `temperature`로 무작위성을 낮출 수 있다(교정 0.1).
    """
    if system_instruction is None:
        full = compose_prompt(runtime.preprompt, prompt)
    else:
        full = prompt
    if runtime.is_deepseek:
        try:
            return deepseek_client.post_chat_completion(
                api_key=runtime.deepseek_api_key,
                model=runtime.model,
                prompt=_deepseek_prompt_with_schema(full, response_schema),
                json_mode=response_schema is not None,
                system_instruction=system_instruction,
                base_url=runtime.deepseek_base_url,
                timeout_seconds=timeout_seconds,
                temperature=temperature,
                max_attempts=max_attempts,
            )
        except deepseek_client.DeepSeekRequestError as exc:
            raise LlmRequestError(
                f"DeepSeek 호출 실패(status={exc.status_code}, model={runtime.model})",
                status_code=exc.status_code,
                model=runtime.model,
            ) from exc
    try:
        data = gemini_client.post_generate_content(
            api_key=runtime.gemini_api_key,
            model=runtime.model,
            body=build_gemini_body(
                full,
                response_schema,
                system_instruction=system_instruction,
                temperature=temperature,
            ),
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
        )
    except gemini_client.GeminiRequestError as exc:
        raise LlmRequestError(
            f"Gemini 호출 실패(status={exc.status_code}, model={runtime.model})",
            status_code=exc.status_code,
            model=runtime.model,
        ) from exc
    return extract_gemini_text(data, model=runtime.model)


def complete_text(
    runtime: LlmRuntime,
    prompt: str,
    *,
    system_instruction: str | None = None,
    temperature: float | None = None,
    timeout_seconds: float = 120.0,
    max_attempts: int | None = None,
) -> str:
    """평문(텍스트) 응답 — JSON 강제 없음. 자막 교정 등에 쓴다(의미적 별칭)."""
    return complete_json(
        runtime,
        prompt,
        response_schema=None,
        system_instruction=system_instruction,
        temperature=temperature,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
    )
