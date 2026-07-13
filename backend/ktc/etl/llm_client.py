"""LLM 비동기 게이트웨이 — provider 디스패치(Gemini / DeepSeek) + 사전 프롬프트 (T-161).

모든 ETL AI 호출은 이 모듈의 단일 진입점(`complete_json`/`complete_text`/
`generate_multimodal`, 공통 코어 `generate`)을 통해 선택된 엔진으로 나간다.
게이트웨이가 **한 계약으로** 처리하는 것:

- **quota reservation**: Gemini 경로는 호출 직전 `gemini_rate_limiter.acquire()`로
  키 전역 슬롯을 예약한다(과거 우회 지점 — deep research·키워드 확장·검수 의견·
  카테고리 제안·video analysis — 포함, C6 해소). DeepSeek는 별도 쿼터라 비적용.
  토큰 추정은 기존 `gemini_rate_limiter.estimate_tokens` 추정식을 그대로 쓴다.
- **비동기 격리**: 동기 SDK(requests) 호출은 게이트웨이 안에서 `asyncio.to_thread`로
  실행해 이벤트 루프/워커를 막지 않는다(T-101/105/111/121-E 계열 사고의 구조적 근절).
  호출부는 개별 `to_thread`를 두지 않는다.
- **timeout·retry**: per-call `timeout_seconds`/`max_attempts`로 호출부 의도를 보존한다
  (대화형 단발 호출 `max_attempts=1`, 기본은 `LLM_RETRY_*` 사람-유사 백오프).
- **usage 실측**: 응답의 실측 토큰(Gemini `usageMetadata`, DeepSeek `usage`)을 구조화
  로그(`llm_usage ...`)로 남기고 결과 객체(`LlmResult`)에 provider·model·outcome·
  elapsed와 함께 포함한다. PR-05 통합: 이 로그가 `estimate_tokens` 추정식
  (`chars//2+2048`)의 한국어 실측 계수 보정의 데이터 원천이다.
- **결과 상태**: 성공은 `LlmResult(outcome="ok")`, 일시 오류 재시도 소진·비재시도
  오류는 `LlmRequestError`, 일일 쿼터 거부는 `gemini_rate_limiter.GeminiQuotaExceeded`
  전파로 구분한다(기존 예외 클래스 유지).

엔진 문자열이 `deepseek-*`이면 DeepSeek(OpenAI 호환)으로, 그 외(`gemini-*`)는 Gemini로
보낸다. 사용자 사전 프롬프트(`runtime.preprompt`)는 모든 프롬프트 앞에 prepend한다
(전용 `system_instruction`이 있는 호출은 제외 — 기존 계약 유지). 응답 JSON 스키마는
Gemini는 `responseSchema`로 강제하고, DeepSeek는 스키마를 프롬프트에 덧붙이고
`response_format=json_object`로 JSON 출력을 강제한다.

공개 YouTube URL(`file_data.file_uri`)·이미지 등 멀티모달 입력은 Gemini 전용이며
`generate_multimodal`(parts pass-through)로 같은 게이트웨이 계약을 탄다.

direct SDK guard: 이 모듈·`gemini_client`·`deepseek_client`·`gemini_rate_limiter` 밖에서
provider HTTP 헬퍼나 `gemini_rate_limiter.acquire`를 직접 호출하면
`tests/test_llm_gateway_guard.py`가 실패한다.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from ktc.core.config import get_settings, is_deepseek_model
from ktc.etl import deepseek_client, gemini_client, gemini_rate_limiter

logger = logging.getLogger(__name__)

# 게이트웨이 결과 상태 계약의 일부로 재노출 — 호출부는 llm_client만 import해도
# 일일 쿼터 거부(GeminiQuotaExceeded)를 구분 처리할 수 있다.
GeminiQuotaExceeded = gemini_rate_limiter.GeminiQuotaExceeded

# 멀티모달(media) part 1개당 보수적 고정 가산 토큰 (quota reservation 용).
#
# 근거: `file_data`(YouTube URL 영상 등)·이미지 입력의 토큰은 Gemini가 서버 측에서
# 산정하므로(영상 ≈ 263 tokens/s 기본 해상도) 프롬프트 문자 수 기반 추정식으로는
# 계산할 수 없다. 텍스트 추정값에 media part당 고정 가산을 더해 TPM 안전 마진을
# 확보하되, 무료 티어 TPM 기본값(250k)보다 충분히 작게 잡아 호출 자체가 즉시
# 보류되지는 않게 한다(≈ 기본 해상도 영상 4분 분량). 정밀값은 PR-05 usage 실측
# 로그(`llm_usage`)가 쌓인 뒤 보정한다.
MULTIMODAL_MEDIA_TOKEN_SURCHARGE = 65_536


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
class LlmUsage:
    """provider가 보고한 실측 토큰 사용량(없으면 None 필드)."""

    prompt_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class LlmResult:
    """게이트웨이 호출 결과 — 텍스트 + provider/model/outcome/elapsed/usage.

    `usage`는 추정식 보정(PR-05)의 데이터 원천이고, `estimated_tokens`는 Gemini
    quota reservation에 실제로 쓴 추정값이다(DeepSeek는 None).
    """

    text: str
    provider: str
    model: str
    outcome: str
    elapsed_seconds: float
    usage: LlmUsage | None = None
    estimated_tokens: int | None = None


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


async def maybe_await(value: Any) -> Any:
    """주입형 llm 콜러블의 반환값을 흡수한다 — 동기 값·awaitable 모두 지원.

    production 콜러블은 게이트웨이 경유 async지만, 테스트 fake는 동기 함수로
    주입할 수 있게 서비스 계층이 이 헬퍼로 결과를 받는다.
    """
    if inspect.isawaitable(value):
        return await value
    return value


def compose_prompt(preprompt: str, prompt: str) -> str:
    """사전 프롬프트를 본 프롬프트 앞에 붙인다(비어 있으면 그대로)."""
    pre = (preprompt or "").strip()
    if not pre:
        return prompt
    return f"{pre}\n\n---\n\n{prompt}"


def _gemini_body_from_parts(
    parts: list[dict[str, Any]],
    response_schema: dict[str, Any] | None,
    *,
    system_instruction: str | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    """Gemini `generateContent` 요청 body(parts 기반)."""
    body: dict[str, Any] = {"contents": [{"parts": parts}]}
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


def build_gemini_body(
    prompt: str,
    response_schema: dict[str, Any] | None,
    *,
    system_instruction: str | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    """Gemini `generateContent` 요청 body. responseSchema·systemInstruction·temperature 지원."""
    return _gemini_body_from_parts(
        [{"text": prompt}],
        response_schema,
        system_instruction=system_instruction,
        temperature=temperature,
    )


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


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _usage_from_gemini(payload: dict[str, Any]) -> LlmUsage | None:
    meta = payload.get("usageMetadata")
    if not isinstance(meta, dict):
        return None
    return LlmUsage(
        prompt_tokens=_int_or_none(meta.get("promptTokenCount")),
        output_tokens=_int_or_none(meta.get("candidatesTokenCount")),
        total_tokens=_int_or_none(meta.get("totalTokenCount")),
    )


def _usage_from_deepseek(payload: dict[str, Any]) -> LlmUsage | None:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    return LlmUsage(
        prompt_tokens=_int_or_none(usage.get("prompt_tokens")),
        output_tokens=_int_or_none(usage.get("completion_tokens")),
        total_tokens=_int_or_none(usage.get("total_tokens")),
    )


def _log_usage(
    *,
    provider: str,
    model: str,
    outcome: str,
    elapsed_seconds: float,
    usage: LlmUsage | None,
    estimated_tokens: int | None,
) -> None:
    """호출 1건의 usage 실측을 구조화 로그로 남긴다.

    PR-05 통합분: 이 로그가 `gemini_rate_limiter.estimate_tokens` 추정식
    (`chars//2+2048`)의 실측 보정 데이터 원천이다 — 2주 이상 쌓인 뒤
    prompt_tokens 분포와 estimated_tokens를 비교해 계수를 조정한다.
    """
    logger.info(
        "llm_usage provider=%s model=%s outcome=%s elapsed_ms=%.0f "
        "prompt_tokens=%s output_tokens=%s total_tokens=%s estimated_tokens=%s",
        provider,
        model,
        outcome,
        elapsed_seconds * 1000.0,
        usage.prompt_tokens if usage else None,
        usage.output_tokens if usage else None,
        usage.total_tokens if usage else None,
        estimated_tokens,
    )


def _resolve_gemini_parts(
    runtime: LlmRuntime,
    *,
    prompt: str | None,
    parts: list[dict[str, Any]] | None,
    system_instruction: str | None,
) -> list[dict[str, Any]]:
    """Gemini 요청 parts를 확정한다(사전 프롬프트 prepend 포함).

    - 텍스트 호출: `system_instruction`이 없으면 사전 프롬프트를 prompt 앞에 붙인다
      (전용 지시문이 있으면 붙이지 않는다 — 기존 계약).
    - 멀티모달(parts): 첫 번째 `text` part에만 같은 규칙으로 사전 프롬프트를
      prepend한다(기존 video_analysis 동작과 동일). media part는 그대로 pass-through.
    """
    if parts is None:
        assert prompt is not None
        if system_instruction is None:
            return [{"text": compose_prompt(runtime.preprompt, prompt)}]
        return [{"text": prompt}]
    if system_instruction is not None or not (runtime.preprompt or "").strip():
        return list(parts)
    resolved: list[dict[str, Any]] = []
    composed = False
    for part in parts:
        if not composed and isinstance(part, dict) and isinstance(part.get("text"), str):
            resolved.append({**part, "text": compose_prompt(runtime.preprompt, part["text"])})
            composed = True
        else:
            resolved.append(part)
    return resolved


def _estimate_gemini_tokens(
    parts: list[dict[str, Any]], system_instruction: str | None
) -> int:
    """quota reservation용 추정 토큰 — 기존 추정식 재사용(변경 금지).

    텍스트는 `gemini_rate_limiter.estimate_tokens`(chars//2+2048) 그대로,
    media part(file_data 등)는 part당 `MULTIMODAL_MEDIA_TOKEN_SURCHARGE`를 더한다.
    """
    texts = [system_instruction or ""]
    media_parts = 0
    for part in parts:
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            texts.append(part["text"])
        else:
            media_parts += 1
    return (
        gemini_rate_limiter.estimate_tokens(*texts)
        + media_parts * MULTIMODAL_MEDIA_TOKEN_SURCHARGE
    )


async def generate(
    runtime: LlmRuntime,
    prompt: str | None = None,
    *,
    parts: list[dict[str, Any]] | None = None,
    response_schema: dict[str, Any] | None = None,
    system_instruction: str | None = None,
    temperature: float | None = None,
    timeout_seconds: float = 120.0,
    max_attempts: int | None = None,
) -> LlmResult:
    """게이트웨이 코어 — 선택된 엔진으로 호출하고 `LlmResult`를 반환한다.

    `prompt`(텍스트)와 `parts`(Gemini 멀티모달 pass-through) 중 정확히 하나를 받는다.
    Gemini 경로는 호출 직전 rate limiter 슬롯을 예약하고, 동기 HTTP 호출은
    `asyncio.to_thread`로 격리한다. 실패는 provider 무관 `LlmRequestError`,
    일일 쿼터 거부는 `GeminiQuotaExceeded`로 전파된다(호출부가 자기 에러로 감싼다).
    `max_attempts`를 주면 provider의 느린 사람-유사 재시도 횟수를 덮어쓴다(대화형은 1).
    """
    if (prompt is None) == (parts is None):
        raise ValueError("prompt와 parts 중 정확히 하나를 지정해야 한다")
    if parts is not None and runtime.is_deepseek:
        raise ValueError("멀티모달(parts) 입력은 Gemini 전용이다")

    provider = "deepseek" if runtime.is_deepseek else "gemini"
    started = time.monotonic()
    estimated_tokens: int | None = None
    try:
        if runtime.is_deepseek:
            if system_instruction is None:
                full = compose_prompt(runtime.preprompt, prompt or "")
            else:
                full = prompt or ""
            payload = await asyncio.to_thread(
                deepseek_client.post_chat_completion_payload,
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
            text = deepseek_client.extract_message_content(payload, model=runtime.model)
            usage = _usage_from_deepseek(payload)
        else:
            resolved_parts = _resolve_gemini_parts(
                runtime,
                prompt=prompt,
                parts=parts,
                system_instruction=system_instruction,
            )
            # quota reservation — DeepSeek는 별도 쿼터라 비적용(기존 계약 유지).
            estimated_tokens = _estimate_gemini_tokens(resolved_parts, system_instruction)
            await gemini_rate_limiter.acquire(estimated_tokens=estimated_tokens)
            data = await asyncio.to_thread(
                gemini_client.post_generate_content,
                api_key=runtime.gemini_api_key,
                model=runtime.model,
                body=_gemini_body_from_parts(
                    resolved_parts,
                    response_schema,
                    system_instruction=system_instruction,
                    temperature=temperature,
                ),
                timeout_seconds=timeout_seconds,
                max_attempts=max_attempts,
            )
            text = extract_gemini_text(data, model=runtime.model)
            usage = _usage_from_gemini(data)
    except gemini_rate_limiter.GeminiQuotaExceeded:
        _log_usage(
            provider=provider,
            model=runtime.model,
            outcome="quota_rejected",
            elapsed_seconds=time.monotonic() - started,
            usage=None,
            estimated_tokens=estimated_tokens,
        )
        raise
    except deepseek_client.DeepSeekRequestError as exc:
        _log_usage(
            provider=provider,
            model=runtime.model,
            outcome="request_error",
            elapsed_seconds=time.monotonic() - started,
            usage=None,
            estimated_tokens=estimated_tokens,
        )
        raise LlmRequestError(
            f"DeepSeek 호출 실패(status={exc.status_code}, model={runtime.model})",
            status_code=exc.status_code,
            model=runtime.model,
        ) from exc
    except gemini_client.GeminiRequestError as exc:
        _log_usage(
            provider=provider,
            model=runtime.model,
            outcome="request_error",
            elapsed_seconds=time.monotonic() - started,
            usage=None,
            estimated_tokens=estimated_tokens,
        )
        raise LlmRequestError(
            f"Gemini 호출 실패(status={exc.status_code}, model={runtime.model})",
            status_code=exc.status_code,
            model=runtime.model,
        ) from exc
    except LlmRequestError:
        # 응답 형식 오류(extract 실패) — provider 호출 자체는 끝났다.
        _log_usage(
            provider=provider,
            model=runtime.model,
            outcome="invalid_response",
            elapsed_seconds=time.monotonic() - started,
            usage=None,
            estimated_tokens=estimated_tokens,
        )
        raise
    elapsed = time.monotonic() - started
    _log_usage(
        provider=provider,
        model=runtime.model,
        outcome="ok",
        elapsed_seconds=elapsed,
        usage=usage,
        estimated_tokens=estimated_tokens,
    )
    return LlmResult(
        text=text,
        provider=provider,
        model=runtime.model,
        outcome="ok",
        elapsed_seconds=elapsed,
        usage=usage,
        estimated_tokens=estimated_tokens,
    )


async def complete_json(
    runtime: LlmRuntime,
    prompt: str,
    *,
    response_schema: dict[str, Any] | None = None,
    system_instruction: str | None = None,
    temperature: float | None = None,
    timeout_seconds: float = 120.0,
    max_attempts: int | None = None,
) -> str:
    """선택된 엔진으로 prompt를 보내고 문자열 응답을 반환한다(게이트웨이 경유).

    실패 시 provider 무관 `LlmRequestError`를 던진다(호출부가 자기 에러로 감싼다).
    `max_attempts`를 주면 provider의 느린 사람-유사 재시도 횟수를 덮어쓴다(대화형은 1).
    `system_instruction`을 주면 사전 프롬프트 대신 그것을 시스템 지시로 쓰고 prepend하지
    않는다(자막 교정·POI 배치처럼 전용 지시문이 있는 경우). `response_schema=None`이면
    JSON 강제 없이 평문 응답을 받는다. `temperature`로 무작위성을 낮출 수 있다(교정 0.1).
    """
    result = await generate(
        runtime,
        prompt,
        response_schema=response_schema,
        system_instruction=system_instruction,
        temperature=temperature,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
    )
    return result.text


async def complete_text(
    runtime: LlmRuntime,
    prompt: str,
    *,
    system_instruction: str | None = None,
    temperature: float | None = None,
    timeout_seconds: float = 120.0,
    max_attempts: int | None = None,
) -> str:
    """평문(텍스트) 응답 — JSON 강제 없음. 자막 교정 등에 쓴다(의미적 별칭)."""
    return await complete_json(
        runtime,
        prompt,
        response_schema=None,
        system_instruction=system_instruction,
        temperature=temperature,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
    )


async def generate_multimodal(
    runtime: LlmRuntime,
    parts: list[dict[str, Any]],
    *,
    response_schema: dict[str, Any] | None = None,
    system_instruction: str | None = None,
    temperature: float | None = None,
    timeout_seconds: float = 120.0,
    max_attempts: int | None = None,
) -> str:
    """Gemini 멀티모달(parts/file_data pass-through) 호출 — video/이미지 입력용.

    `parts`는 Gemini `contents[0].parts` 형식 그대로 전달한다
    (예: `[{"file_data": {"file_uri": url}}, {"text": prompt}]`). 현재 소비자는
    video_analysis(YouTube URL 직접 분석)이며, quota reservation은 텍스트 추정 +
    media part당 고정 가산(`MULTIMODAL_MEDIA_TOKEN_SURCHARGE`)으로 보수적으로 잡는다.
    DeepSeek 엔진에서는 `ValueError`를 던진다(Gemini 전용).
    """
    result = await generate(
        runtime,
        parts=parts,
        response_schema=response_schema,
        system_instruction=system_instruction,
        temperature=temperature,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
    )
    return result.text
