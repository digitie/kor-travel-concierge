"""provider 디스패치(llm_client) + 사전 프롬프트 + 사람 유사 재시도 테스트.

DB 없이 동작한다(HTTP는 monkeypatch).
"""

from __future__ import annotations

import pytest

from ktc.etl import deepseek_client, gemini_client, llm_client


def test_compose_prompt_prepends_preprompt():
    assert llm_client.compose_prompt("", "BODY") == "BODY"
    assert llm_client.compose_prompt("   ", "BODY") == "BODY"
    out = llm_client.compose_prompt("PRE", "BODY")
    assert out.startswith("PRE")
    assert out.endswith("BODY")
    assert "BODY" in out


def test_runtime_is_deepseek():
    assert llm_client.LlmRuntime(model="deepseek-v4-flash").is_deepseek is True
    assert llm_client.LlmRuntime(model="deepseek-v4-pro").is_deepseek is True
    assert llm_client.LlmRuntime(model="gemini-2.0-flash").is_deepseek is False


def test_complete_json_dispatches_to_deepseek(monkeypatch):
    captured: dict = {}

    def fake_chat(**kwargs):
        captured.update(kwargs)
        return '{"summary": "x", "places": []}'

    monkeypatch.setattr(deepseek_client, "post_chat_completion", fake_chat)
    runtime = llm_client.LlmRuntime(
        model="deepseek-v4-flash", deepseek_api_key="ds-key", preprompt="PRE"
    )
    out = llm_client.complete_json(runtime, "BODY", response_schema={"type": "object"})

    assert out == '{"summary": "x", "places": []}'
    assert captured["model"] == "deepseek-v4-flash"
    assert captured["api_key"] == "ds-key"
    assert captured["json_mode"] is True
    # 사전 프롬프트 + 스키마가 프롬프트에 포함된다.
    assert "PRE" in captured["prompt"]
    assert "BODY" in captured["prompt"]
    assert "JSON Schema" in captured["prompt"]


def test_complete_json_dispatches_to_gemini(monkeypatch):
    captured: dict = {}

    def fake_post(**kwargs):
        captured.update(kwargs)
        return {"candidates": [{"content": {"parts": [{"text": "RESULT"}]}}]}

    monkeypatch.setattr(gemini_client, "post_generate_content", fake_post)
    runtime = llm_client.LlmRuntime(
        model="gemini-2.0-flash", gemini_api_key="g-key", preprompt="PRE"
    )
    out = llm_client.complete_json(runtime, "BODY", response_schema={"type": "object"})

    assert out == "RESULT"
    assert captured["model"] == "gemini-2.0-flash"
    body = captured["body"]
    assert body["generationConfig"]["responseSchema"] == {"type": "object"}
    assert "PRE" in body["contents"][0]["parts"][0]["text"]
    assert "BODY" in body["contents"][0]["parts"][0]["text"]


def test_complete_json_wraps_provider_error(monkeypatch):
    def boom(**kwargs):
        raise deepseek_client.DeepSeekRequestError("fail", status_code=503, model="deepseek-v4-flash")

    monkeypatch.setattr(deepseek_client, "post_chat_completion", boom)
    runtime = llm_client.LlmRuntime(model="deepseek-v4-flash", deepseek_api_key="k")
    with pytest.raises(llm_client.LlmRequestError) as exc:
        llm_client.complete_json(runtime, "BODY")
    assert exc.value.status_code == 503


def test_human_like_retry_delay_is_slow_and_bounded():
    # rng=0.5 -> jitter 항 0 -> 정확히 지수 백오프(상한 적용)
    base, mx, jit = 15.0, 90.0, 0.3
    half = lambda: 0.5  # noqa: E731
    assert gemini_client.human_like_retry_delay(0, base_delay_seconds=base, max_delay_seconds=mx, jitter=jit, rng=half) == 15.0
    assert gemini_client.human_like_retry_delay(2, base_delay_seconds=base, max_delay_seconds=mx, jitter=jit, rng=half) == 60.0
    # 5회차는 15*32=480이지만 상한 90으로 cap
    assert gemini_client.human_like_retry_delay(5, base_delay_seconds=base, max_delay_seconds=mx, jitter=jit, rng=half) == 90.0
    # jitter 경계: rng=0 -> -30%, rng=1 -> +30%
    assert gemini_client.human_like_retry_delay(0, base_delay_seconds=base, max_delay_seconds=mx, jitter=jit, rng=lambda: 0.0) == pytest.approx(15.0 * 0.7)
    assert gemini_client.human_like_retry_delay(0, base_delay_seconds=base, max_delay_seconds=mx, jitter=jit, rng=lambda: 1.0) == pytest.approx(15.0 * 1.3)
    # 첫 재시도도 충분히 늦다(2·4·8초가 아님)
    assert gemini_client.human_like_retry_delay(0, base_delay_seconds=base, max_delay_seconds=mx, jitter=jit, rng=half) >= 10.0


def test_deepseek_client_builds_openai_body(monkeypatch):
    captured: dict = {}

    class FakeResp:
        status_code = 200

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "OK"}}]}

    def fake_post(url, headers=None, json=None, timeout=None):  # noqa: A002
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return FakeResp()

    monkeypatch.setattr(deepseek_client.requests, "post", fake_post)
    out = deepseek_client.post_chat_completion(
        api_key="k", model="deepseek-v4-pro", prompt="hi json", json_mode=True
    )
    assert out == "OK"
    assert captured["url"].endswith("/chat/completions")
    assert captured["headers"]["Authorization"] == "Bearer k"
    assert captured["json"]["model"] == "deepseek-v4-pro"
    assert captured["json"]["response_format"] == {"type": "json_object"}
    assert captured["json"]["messages"][0]["content"] == "hi json"
