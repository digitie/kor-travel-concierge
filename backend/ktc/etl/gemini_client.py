"""Gemini `generateContent` 공용 호출 헬퍼.

여러 ETL 모듈이 동일한 `generateContent` 엔드포인트를 호출하므로, 전송과 일시적
오류 재시도(타임아웃·연결오류·429·5xx 지수 백오프)를 한 곳으로 모은다. 비재시도
오류(그 외 4xx 등)는 즉시 전파한다. Gemini가 과부하 시 반환하는 503은 이 재시도로
완화한다(이슈 대응).
"""

from __future__ import annotations

import random
import re
import time
from collections.abc import Callable
from concurrent.futures import CancelledError as ThreadCancelledError
from typing import Any

import requests

from ktc.core.config import get_settings

GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# Gemini가 일시적으로 반환하는 상태코드(과부하/속도제한). 지수 백오프로 재시도한다.
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


def human_like_retry_delay(
    attempt: int,
    *,
    base_delay_seconds: float,
    max_delay_seconds: float,
    jitter: float,
    rng: Callable[[], float] = random.random,
) -> float:
    """사람과 유사한 느낌의 재시도 대기 시간(초)을 계산한다.

    지수 백오프(`base * 2**attempt`)에 상한(`max_delay`)을 두고 ±`jitter` 비율의
    무작위 흔들림을 더한다. 너무 빠른(2·4·8초) 재시도 대신 충분히 늦은 대기를 준다.
    """
    delay = min(base_delay_seconds * (2**attempt), max_delay_seconds)
    delay *= 1.0 + jitter * (2.0 * rng() - 1.0)
    return max(0.0, delay)


class GeminiRequestError(RuntimeError):
    """Gemini 호출이 재시도 후에도 실패한 경우(상태코드/모델 포함)."""

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

    `X-goog-api-key` 헤더는 URL에 없지만, provider 오류 응답 메시지가 요청 컨텍스트를
    반향할 가능성에 대비해 `youtube_client._mask_api_key`와 동일하게 방어한다.
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


def _gemini_error_detail(response: Any) -> str | None:
    """Gemini 표준 오류 응답(`{"error": {"message": ...}}`)에서 message를 추출한다."""
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


def post_generate_content(
    *,
    api_key: str,
    model: str,
    body: dict[str, Any],
    timeout_seconds: float = 120.0,
    max_attempts: int | None = None,
    base_delay_seconds: float | None = None,
    max_delay_seconds: float | None = None,
    jitter: float | None = None,
    sleep: Callable[[float], None] = time.sleep,
    rng: Callable[[], float] = random.random,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """`generateContent`를 호출하고 JSON 응답(dict)을 반환한다.

    일시적 오류(타임아웃/연결오류/429/5xx)는 사람과 유사한 느린 지수 백오프(+jitter)로
    최대 `max_attempts`회 재시도한다. 그 외 HTTP 오류(4xx 등)는 즉시
    `GeminiRequestError`로 던진다. 재시도 파라미터를 주지 않으면 `Settings`의
    `LLM_RETRY_*` 값을 쓴다. `sleep`/`rng`은 테스트에서 주입 가능하다.
    """
    if not api_key:
        raise ValueError("GEMINI_API_KEY가 필요하다")
    settings = get_settings()
    if max_attempts is None:
        max_attempts = settings.LLM_RETRY_MAX_ATTEMPTS
    if base_delay_seconds is None:
        base_delay_seconds = settings.LLM_RETRY_BASE_DELAY_SECONDS
    if max_delay_seconds is None:
        max_delay_seconds = settings.LLM_RETRY_MAX_DELAY_SECONDS
    if jitter is None:
        jitter = settings.LLM_RETRY_JITTER
    url = f"{GEMINI_API_BASE_URL}/models/{model}:generateContent"
    headers = {"Content-Type": "application/json", "X-goog-api-key": api_key}
    last_status: int | None = None
    last_exc: Exception | None = None
    last_detail: str | None = None
    for attempt in range(max_attempts):
        if cancelled is not None and cancelled():
            raise ThreadCancelledError("실행 종료로 LLM 재시도를 중단합니다.")
        retryable = False
        try:
            response = requests.post(url, headers=headers, json=body, timeout=timeout_seconds)
        except _NON_RETRYABLE_REQUEST_EXC as exc:
            # URL/스키마 설정 오류는 재시도해도 항상 같은 방식으로 실패한다 — 사람 유사
            # 백오프로 수십 초를 태우지 말고 즉시 실패시킨다.
            raise GeminiRequestError(
                f"Gemini 호출 실패(요청 구성 오류, model={model}, "
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
                last_detail = _gemini_error_detail(response)
                retryable = True
            elif not 200 <= status < 300:
                detail = _gemini_error_detail(response)
                message = f"Gemini 호출 실패(status={status}, model={model}"
                if detail:
                    message += f", message={_mask_secret(detail, api_key)}"
                message += ")"
                raise GeminiRequestError(message, status_code=status, model=model)
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
    raise GeminiRequestError(
        f"Gemini 호출 실패(일시 오류 재시도 소진, status={last_status}, model={model}{detail_suffix})",
        status_code=last_status,
        model=model,
    ) from last_exc
