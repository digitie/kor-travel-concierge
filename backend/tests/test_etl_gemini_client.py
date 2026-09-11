"""Gemini generateContent 재시도 헬퍼 테스트."""

from __future__ import annotations

import pytest

from ktc.etl import gemini_client
from ktc.etl.gemini_client import GeminiRequestError, post_generate_content


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
        return _Resp(200, {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    slept: list[float] = []
    monkeypatch.setattr(gemini_client.requests, "post", fake_post)
    data = post_generate_content(
        api_key="k", model="m", body={}, base_delay_seconds=0.0, sleep=slept.append
    )
    assert calls["n"] == 3
    assert len(slept) == 2
    assert data["candidates"][0]["content"]["parts"][0]["text"] == "ok"


def test_non_retryable_status_raises_immediately(monkeypatch):
    calls = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        return _Resp(400)

    monkeypatch.setattr(gemini_client.requests, "post", fake_post)
    with pytest.raises(GeminiRequestError) as exc:
        post_generate_content(api_key="k", model="m", body={}, sleep=lambda _s: None)
    assert calls["n"] == 1
    assert exc.value.status_code == 400


def test_exhausts_retries_on_persistent_503(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        return _Resp(503)

    monkeypatch.setattr(gemini_client.requests, "post", fake_post)
    with pytest.raises(GeminiRequestError) as exc:
        post_generate_content(
            api_key="k", model="m", body={}, max_attempts=3, sleep=lambda _s: None
        )
    assert exc.value.status_code == 503


def test_requires_api_key():
    with pytest.raises(ValueError):
        post_generate_content(api_key="", model="m", body={})


def test_retries_chunked_encoding_error_then_succeeds(monkeypatch):
    """`ChunkedEncodingError`는 (Timeout, ConnectionError) 하위가 아니라 예전에는
    재시도 없이 그대로 전파됐다 — 넓힌 `RequestException` 캐치로 재시도돼야 한다."""
    calls = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 2:
            raise gemini_client.requests.exceptions.ChunkedEncodingError("Response ended prematurely")
        return _Resp(200, {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    monkeypatch.setattr(gemini_client.requests, "post", fake_post)
    data = post_generate_content(
        api_key="k", model="m", body={}, base_delay_seconds=0.0, sleep=lambda _s: None
    )
    assert calls["n"] == 2
    assert data["candidates"][0]["content"]["parts"][0]["text"] == "ok"


def test_non_retryable_status_includes_response_message_detail(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        return _Resp(403, {"error": {"message": "API key not valid"}})

    monkeypatch.setattr(gemini_client.requests, "post", fake_post)
    with pytest.raises(GeminiRequestError) as exc:
        post_generate_content(api_key="test-api-key-value", model="m", body={}, sleep=lambda _s: None)
    assert exc.value.status_code == 403
    assert "API key not valid" in str(exc.value)


def test_exhausted_network_retries_include_exception_detail(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        raise gemini_client.requests.exceptions.ChunkedEncodingError("Response ended prematurely")

    monkeypatch.setattr(gemini_client.requests, "post", fake_post)
    with pytest.raises(GeminiRequestError) as exc:
        post_generate_content(
            api_key="k", model="m", body={}, max_attempts=2, base_delay_seconds=0.0,
            sleep=lambda _s: None,
        )
    assert exc.value.status_code is None
    assert "Response ended prematurely" in str(exc.value)
    assert "ChunkedEncodingError" in str(exc.value)


def test_invalid_url_fails_fast_without_retry(monkeypatch):
    """URL/스키마 설정 오류(MissingSchema 등)는 재시도해도 항상 같은 방식으로 실패하므로
    사람 유사 백오프로 수십 초를 태우지 않고 즉시 실패해야 한다."""
    calls = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        raise gemini_client.requests.exceptions.MissingSchema("Invalid URL")

    slept: list[float] = []
    monkeypatch.setattr(gemini_client.requests, "post", fake_post)
    with pytest.raises(GeminiRequestError) as exc:
        post_generate_content(
            api_key="k", model="m", body={}, max_attempts=5, sleep=slept.append
        )
    assert calls["n"] == 1
    assert slept == []
    assert "MissingSchema" in str(exc.value)


def test_response_message_detail_masks_api_key(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        return _Resp(403, {"error": {"message": "invalid key: secret-key-123"}})

    monkeypatch.setattr(gemini_client.requests, "post", fake_post)
    with pytest.raises(GeminiRequestError) as exc:
        post_generate_content(
            api_key="secret-key-123", model="m", body={}, sleep=lambda _s: None
        )
    assert "secret-key-123" not in str(exc.value)
    assert "***" in str(exc.value)


def test_exhausted_network_retry_detail_masks_authorization_header(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        raise gemini_client.requests.exceptions.ChunkedEncodingError(
            "broken pipe while sending Authorization: Bearer secret-key-123"
        )

    monkeypatch.setattr(gemini_client.requests, "post", fake_post)
    with pytest.raises(GeminiRequestError) as exc:
        post_generate_content(
            api_key="secret-key-123", model="m", body={}, max_attempts=1,
            base_delay_seconds=0.0, sleep=lambda _s: None,
        )
    assert "secret-key-123" not in str(exc.value)
