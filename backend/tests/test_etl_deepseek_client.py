"""DeepSeek chat/completions 재시도 헬퍼 테스트 (gemini_client와 동일 계약)."""

from __future__ import annotations

import pytest

from ktc.etl import deepseek_client
from ktc.etl.deepseek_client import DeepSeekRequestError, post_chat_completion_payload


class _Resp:
    def __init__(self, status_code: int, json_data: dict | None = None) -> None:
        self.status_code = status_code
        self._json = json_data or {}
        self.ok = 200 <= status_code < 300

    def json(self) -> dict:
        return self._json


def test_retries_transient_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            return _Resp(503)
        return _Resp(200, {"choices": [{"message": {"content": "ok"}}]})

    slept: list[float] = []
    monkeypatch.setattr(deepseek_client.requests, "post", fake_post)
    data = post_chat_completion_payload(
        api_key="k", model="m", prompt="p", base_delay_seconds=0.0, sleep=slept.append
    )
    assert calls["n"] == 3
    assert len(slept) == 2
    assert data["choices"][0]["message"]["content"] == "ok"


def test_non_retryable_status_raises_immediately(monkeypatch):
    calls = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        return _Resp(400)

    monkeypatch.setattr(deepseek_client.requests, "post", fake_post)
    with pytest.raises(DeepSeekRequestError) as exc:
        post_chat_completion_payload(api_key="k", model="m", prompt="p", sleep=lambda _s: None)
    assert calls["n"] == 1
    assert exc.value.status_code == 400


def test_non_retryable_status_includes_response_message_detail(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        return _Resp(401, {"error": {"message": "Authentication Fails"}})

    monkeypatch.setattr(deepseek_client.requests, "post", fake_post)
    with pytest.raises(DeepSeekRequestError) as exc:
        post_chat_completion_payload(api_key="k", model="m", prompt="p", sleep=lambda _s: None)
    assert exc.value.status_code == 401
    assert "Authentication Fails" in str(exc.value)


def test_exhausts_retries_on_persistent_503(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        return _Resp(503)

    monkeypatch.setattr(deepseek_client.requests, "post", fake_post)
    with pytest.raises(DeepSeekRequestError) as exc:
        post_chat_completion_payload(
            api_key="k", model="m", prompt="p", max_attempts=3, sleep=lambda _s: None
        )
    assert exc.value.status_code == 503


def test_retries_chunked_encoding_error_then_succeeds(monkeypatch):
    """`ChunkedEncodingError`는 (Timeout, ConnectionError) 하위가 아니라 예전에는
    재시도 없이 그대로 전파됐다(실제 운영에서 "Response ended prematurely" last_error로
    관측됨) — 넓힌 `RequestException` 캐치로 재시도돼야 한다."""
    calls = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 2:
            raise deepseek_client.requests.exceptions.ChunkedEncodingError(
                "Response ended prematurely"
            )
        return _Resp(200, {"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(deepseek_client.requests, "post", fake_post)
    data = post_chat_completion_payload(
        api_key="k", model="m", prompt="p", base_delay_seconds=0.0, sleep=lambda _s: None
    )
    assert calls["n"] == 2
    assert data["choices"][0]["message"]["content"] == "ok"


def test_exhausted_network_retries_include_exception_detail(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        raise deepseek_client.requests.exceptions.ChunkedEncodingError(
            "Response ended prematurely"
        )

    monkeypatch.setattr(deepseek_client.requests, "post", fake_post)
    with pytest.raises(DeepSeekRequestError) as exc:
        post_chat_completion_payload(
            api_key="k", model="m", prompt="p", max_attempts=2, base_delay_seconds=0.0,
            sleep=lambda _s: None,
        )
    assert exc.value.status_code is None
    assert "Response ended prematurely" in str(exc.value)
    assert "ChunkedEncodingError" in str(exc.value)


def test_requires_api_key():
    with pytest.raises(ValueError):
        post_chat_completion_payload(api_key="", model="m", prompt="p")


def test_invalid_url_fails_fast_without_retry(monkeypatch):
    """URL/스키마 설정 오류(MissingSchema 등)는 재시도해도 항상 같은 방식으로 실패하므로
    사람 유사 백오프로 수십 초를 태우지 않고 즉시 실패해야 한다."""
    calls = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        raise deepseek_client.requests.exceptions.MissingSchema("Invalid URL")

    slept: list[float] = []
    monkeypatch.setattr(deepseek_client.requests, "post", fake_post)
    with pytest.raises(DeepSeekRequestError) as exc:
        post_chat_completion_payload(
            api_key="k", model="m", prompt="p", max_attempts=5, sleep=slept.append
        )
    assert calls["n"] == 1
    assert slept == []
    assert "MissingSchema" in str(exc.value)


def test_response_message_detail_masks_api_key(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        return _Resp(401, {"error": {"message": "invalid Authorization: Bearer secret-key-123"}})

    monkeypatch.setattr(deepseek_client.requests, "post", fake_post)
    with pytest.raises(DeepSeekRequestError) as exc:
        post_chat_completion_payload(
            api_key="secret-key-123", model="m", prompt="p", sleep=lambda _s: None
        )
    assert "secret-key-123" not in str(exc.value)


def test_exhausted_network_retry_detail_masks_api_key(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        raise deepseek_client.requests.exceptions.ChunkedEncodingError(
            "broken pipe while sending Authorization: Bearer secret-key-123"
        )

    monkeypatch.setattr(deepseek_client.requests, "post", fake_post)
    with pytest.raises(DeepSeekRequestError) as exc:
        post_chat_completion_payload(
            api_key="secret-key-123", model="m", prompt="p", max_attempts=1,
            base_delay_seconds=0.0, sleep=lambda _s: None,
        )
    assert "secret-key-123" not in str(exc.value)
