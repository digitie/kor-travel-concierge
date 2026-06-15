"""Gemini `generateContent` 공용 호출 헬퍼.

여러 ETL 모듈이 동일한 `generateContent` 엔드포인트를 호출하므로, 전송과 일시적
오류 재시도(타임아웃·연결오류·429·5xx 지수 백오프)를 한 곳으로 모은다. 비재시도
오류(그 외 4xx 등)는 즉시 전파한다. Gemini가 과부하 시 반환하는 503은 이 재시도로
완화한다(이슈 대응).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import requests

GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# Gemini가 일시적으로 반환하는 상태코드(과부하/속도제한). 지수 백오프로 재시도한다.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


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


def post_generate_content(
    *,
    api_key: str,
    model: str,
    body: dict[str, Any],
    timeout_seconds: float = 60.0,
    max_attempts: int = 4,
    base_delay_seconds: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """`generateContent`를 호출하고 JSON 응답(dict)을 반환한다.

    일시적 오류(타임아웃/연결오류/429/5xx)는 지수 백오프로 최대 `max_attempts`회
    재시도한다. 그 외 HTTP 오류(4xx 등)는 즉시 `GeminiRequestError`로 던진다.
    `sleep`은 테스트에서 주입 가능하다.
    """
    if not api_key:
        raise ValueError("GEMINI_API_KEY가 필요하다")
    url = f"{GEMINI_API_BASE_URL}/models/{model}:generateContent"
    headers = {"Content-Type": "application/json", "X-goog-api-key": api_key}
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
                raise GeminiRequestError(
                    f"Gemini 호출 실패(status={status}, model={model})",
                    status_code=status,
                    model=model,
                )
            else:
                return response.json()
        if not retryable or attempt == max_attempts - 1:
            break
        sleep(base_delay_seconds * (2**attempt))
    raise GeminiRequestError(
        f"Gemini 호출 실패(일시 오류 재시도 소진, status={last_status}, model={model})",
        status_code=last_status,
        model=model,
    ) from last_exc
