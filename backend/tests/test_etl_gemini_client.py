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
