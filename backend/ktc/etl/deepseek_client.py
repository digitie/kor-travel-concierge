"""DeepSeek V4 (OpenAI 호환) chat completion 호출 헬퍼.

DeepSeek API는 `https://api.deepseek.com`의 OpenAI 호환 `/chat/completions`를 쓴다.
`deepseek-v4-flash`/`deepseek-v4-pro` 모두 JSON 출력(`response_format={"type":"json_object"}`)을
지원한다. 재시도(타임아웃/연결오류/429/5xx)는 Gemini와 동일한 사람 유사 백오프를 공유한다.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any

import requests

from ktc.core.config import get_settings
from ktc.etl.gemini_client import human_like_retry_delay

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


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
    for attempt in range(max_attempts):
        retryable = False
        try:
            response = requests.post(url, headers=headers, json=body, timeout=timeout_seconds)
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exc = exc
            retryable = True
        else:
            status = response.status_code
            if status in RETRYABLE_STATUS:
                last_status = status
                retryable = True
            elif not 200 <= status < 300:
                raise DeepSeekRequestError(
                    f"DeepSeek 호출 실패(status={status}, model={model})",
                    status_code=status,
                    model=model,
                )
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
    raise DeepSeekRequestError(
        f"DeepSeek 호출 실패(일시 오류 재시도 소진, status={last_status}, model={model})",
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
