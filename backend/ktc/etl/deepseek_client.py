"""DeepSeek V4 (OpenAI 호환) chat completion 호출 헬퍼.

DeepSeek API는 `https://api.deepseek.com`의 OpenAI 호환 `/chat/completions`를 쓴다.
`deepseek-flash`(DeepSeek-V4.1-Flash)/`deepseek-v4-pro` 모두 JSON 출력
(`response_format={"type":"json_object"}`)을 지원한다(`config.DEEPSEEK_ENGINE_OPTIONS`).
재시도(타임아웃/연결오류/응답 중 끊김/429/5xx)는 Gemini와 동일한 사람 유사 백오프를 공유한다.
"""

from __future__ import annotations

import random
import re
import time
from collections.abc import Callable
from typing import Any

import requests

from ktc.core.config import get_settings
from ktc.etl.gemini_client import human_like_retry_delay

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

# URL/스키마 오류 등 재시도해도 절대 성공하지 않는 예외(설정 버그) — 넓힌 RequestException
# 캐치에서 이들만 제외해 즉시 실패시킨다(그 외 ChunkedEncodingError 등 네트워크성 예외는
# 재시도 대상으로 남긴다).
_NON_RETRYABLE_REQUEST_EXC: tuple[type[Exception], ...] = (
    requests.exceptions.MissingSchema,
    requests.exceptions.InvalidSchema,
    requests.exceptions.InvalidURL,
    requests.exceptions.InvalidHeader,
    requests.exceptions.URLRequired,
    requests.exceptions.TooManyRedirects,
)


class DeepSeekRequestError(RuntimeError):
    """DeepSeek 호출이 재시도 후에도 실패한 경우(상태코드/모델 포함)."""

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


def _clip(value: Any, limit: int = 240) -> str:
    """외부 provider 오류를 진단 로그/last_error에 남길 짧은 한 줄로 정리한다."""
    return " ".join(str(value).split())[:limit]


def _mask_secret(value: str, api_key: str) -> str:
    """`last_error`(DB·운영 콘솔에 노출)에 API 키가 그대로 남지 않도록 가린다.

    DeepSeek 키는 `Authorization: Bearer` 헤더로 전달되며 URL에는 없지만, provider
    오류 응답 메시지가 요청 컨텍스트를 반향할 가능성에 대비해 `youtube_client._mask_api_key`와
    동일하게 방어한다.
    """
    if api_key:
        value = value.replace(api_key, "***")
    value = re.sub(
        r"(?i)((?:x-goog-api-key|api[_-]?key|[?&]key)\s*[:=])[^\s&;,]+",
        r"\1***",
        value,
    )
    value = re.sub(
        r"(?i)(authorization\s*:\s*(?:bearer\s+)?)\S+",
        r"\1***",
        value,
    )
    return value


def _deepseek_error_detail(response: Any) -> str | None:
    """OpenAI 호환 오류 응답(`{"error": {"message": ...}}`)에서 message를 추출한다."""
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if isinstance(error, str):
        return _clip(error)
    if not isinstance(error, dict):
        return None
    message = error.get("message")
    return _clip(message) if message is not None else None


def post_chat_completion(
    *,
    api_key: str,
    model: str,
    prompt: str,
    json_mode: bool = False,
    system_instruction: str | None = None,
    base_url: str | None = None,
    timeout_seconds: float = 120.0,
    temperature: float | None = None,
    max_attempts: int | None = None,
    base_delay_seconds: float | None = None,
    max_delay_seconds: float | None = None,
    jitter: float | None = None,
    sleep: Callable[[float], None] = time.sleep,
    rng: Callable[[], float] = random.random,
) -> str:
    """`/chat/completions`를 호출하고 첫 choice의 message content(문자열)를 반환한다.

    `post_chat_completion_payload`의 편의 wrapper. usage 실측이 필요한 게이트웨이
    (`llm_client`)는 payload 변형을 직접 쓴다.
    """
    payload = post_chat_completion_payload(
        api_key=api_key,
        model=model,
        prompt=prompt,
        json_mode=json_mode,
        system_instruction=system_instruction,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        temperature=temperature,
        max_attempts=max_attempts,
        base_delay_seconds=base_delay_seconds,
        max_delay_seconds=max_delay_seconds,
        jitter=jitter,
        sleep=sleep,
        rng=rng,
    )
    return extract_message_content(payload, model=model)


def post_chat_completion_payload(
    *,
    api_key: str,
    model: str,
    prompt: str,
    json_mode: bool = False,
    system_instruction: str | None = None,
    base_url: str | None = None,
    timeout_seconds: float = 120.0,
    temperature: float | None = None,
    max_attempts: int | None = None,
    base_delay_seconds: float | None = None,
    max_delay_seconds: float | None = None,
    jitter: float | None = None,
    sleep: Callable[[float], None] = time.sleep,
    rng: Callable[[], float] = random.random,
) -> dict[str, Any]:
    """`/chat/completions`를 호출하고 응답 JSON 전체(dict)를 반환한다(usage 포함).

    `json_mode=True`이면 `response_format={"type":"json_object"}`로 JSON 출력을 강제한다
    (DeepSeek 요구사항상 프롬프트에 "json"이라는 단어가 포함되어야 한다 — 본 프로젝트
    프롬프트는 모두 JSON 출력을 명시한다). 일시 오류는 사람 유사 백오프로 재시도한다.
    """
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY가 필요하다")
    settings = get_settings()
    base = (base_url or settings.DEEPSEEK_BASE_URL).rstrip("/")
    if max_attempts is None:
        max_attempts = settings.LLM_RETRY_MAX_ATTEMPTS
    if base_delay_seconds is None:
        base_delay_seconds = settings.LLM_RETRY_BASE_DELAY_SECONDS
    if max_delay_seconds is None:
        max_delay_seconds = settings.LLM_RETRY_MAX_DELAY_SECONDS
    if jitter is None:
        jitter = settings.LLM_RETRY_JITTER

    url = f"{base}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    messages: list[dict[str, str]] = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if temperature is not None:
        body["temperature"] = temperature

    last_status: int | None = None
    last_exc: Exception | None = None
    last_detail: str | None = None
    for attempt in range(max_attempts):
        retryable = False
        try:
            response = requests.post(url, headers=headers, json=body, timeout=timeout_seconds)
        except _NON_RETRYABLE_REQUEST_EXC as exc:
            # URL/스키마 설정 오류는 재시도해도 항상 같은 방식으로 실패한다 — 사람 유사
            # 백오프로 수십 초를 태우지 말고 즉시 실패시킨다.
            raise DeepSeekRequestError(
                f"DeepSeek 호출 실패(요청 구성 오류, model={model}, "
                f"error={type(exc).__name__}: {_mask_secret(_clip(exc), api_key)})",
                model=model,
            ) from exc
        except requests.exceptions.RequestException as exc:
            # Timeout/ConnectionError뿐 아니라 ChunkedEncodingError 등 응답 중 끊김도
            # RequestException 하위라 여기서 함께 재시도 대상으로 잡는다(이전에는 좁은
            # (Timeout, ConnectionError)만 잡아 이런 예외가 재시도 없이 그대로 전파됐다).
            last_exc = exc
            retryable = True
        else:
            status = response.status_code
            if status in RETRYABLE_STATUS:
                last_status = status
                last_detail = _deepseek_error_detail(response)
                retryable = True
            elif not 200 <= status < 300:
                detail = _deepseek_error_detail(response)
                message = f"DeepSeek 호출 실패(status={status}, model={model}"
                if detail:
                    message += f", message={_mask_secret(detail, api_key)}"
                message += ")"
                raise DeepSeekRequestError(message, status_code=status, model=model)
            else:
                return response.json()
        if not retryable or attempt == max_attempts - 1:
            break
        sleep(
            human_like_retry_delay(
                attempt,
                base_delay_seconds=base_delay_seconds,
                max_delay_seconds=max_delay_seconds,
                jitter=jitter,
                rng=rng,
            )
        )
    detail_suffix = ""
    if last_exc is not None:
        detail_suffix = f", error={type(last_exc).__name__}: {_mask_secret(_clip(last_exc), api_key)}"
    elif last_detail:
        detail_suffix = f", message={_mask_secret(last_detail, api_key)}"
    raise DeepSeekRequestError(
        f"DeepSeek 호출 실패(일시 오류 재시도 소진, status={last_status}, model={model}{detail_suffix})",
        status_code=last_status,
        model=model,
    ) from last_exc


def extract_message_content(payload: dict[str, Any], *, model: str) -> str:
    """응답 payload에서 첫 choice의 message content(문자열)를 꺼낸다."""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise DeepSeekRequestError("DeepSeek 응답에 choices가 없다", model=model)
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise DeepSeekRequestError("DeepSeek 응답 content가 비어 있다", model=model)
    return content
