"""LLM 게이트웨이(llm_client) 단위 테스트 (T-161).

provider 디스패치 + 사전 프롬프트 + quota reservation + per-call 옵션 + usage 실측 +
예외 계약을 fake client/limiter로 검증한다. DB 없이 동작한다(HTTP·limiter는 monkeypatch).
"""

from __future__ import annotations

import json
import logging

import pytest

from ktc.etl import deepseek_client, gemini_client, gemini_rate_limiter, llm_client

_GEMINI_OK = {
    "candidates": [{"content": {"parts": [{"text": "RESULT"}]}}],
    "usageMetadata": {
        "promptTokenCount": 120,
        "candidatesTokenCount": 30,
        "totalTokenCount": 150,
    },
}

_DEEPSEEK_OK = {
    "choices": [{"message": {"content": '{"summary": "x", "places": []}'}}],
    "usage": {"prompt_tokens": 77, "completion_tokens": 11, "total_tokens": 88},
}


@pytest.fixture
def fake_acquire(monkeypatch):
    """rate limiter 예약을 기록형 fake로 대체한다(DB 미사용)."""
    calls: list[int] = []

    async def _acquire(*, estimated_tokens: int) -> None:
        calls.append(estimated_tokens)

    monkeypatch.setattr(gemini_rate_limiter, "acquire", _acquire)
    return calls


# --- 헬퍼 ---


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


async def test_maybe_await_supports_sync_and_async():
    assert await llm_client.maybe_await("plain") == "plain"

    async def coro():
        return "awaited"

    assert await llm_client.maybe_await(coro()) == "awaited"


# --- provider 디스패치 ---


async def test_complete_json_dispatches_to_deepseek(monkeypatch, fake_acquire):
    captured: dict = {}

    def fake_chat(**kwargs):
        captured.update(kwargs)
        return _DEEPSEEK_OK

    monkeypatch.setattr(deepseek_client, "post_chat_completion_payload", fake_chat)
    runtime = llm_client.LlmRuntime(
        model="deepseek-v4-flash", deepseek_api_key="ds-key", preprompt="PRE"
    )
    out = await llm_client.complete_json(runtime, "BODY", response_schema={"type": "object"})

    assert out == '{"summary": "x", "places": []}'
    assert captured["model"] == "deepseek-v4-flash"
    assert captured["api_key"] == "ds-key"
    assert captured["json_mode"] is True
    # 사전 프롬프트 + 스키마가 프롬프트에 포함된다.
    assert "PRE" in captured["prompt"]
    assert "BODY" in captured["prompt"]
    assert "JSON Schema" in captured["prompt"]
    # DeepSeek는 Gemini rate limiter 예약 대상이 아니다(별도 쿼터).
    assert fake_acquire == []


async def test_complete_json_dispatches_to_gemini_and_reserves_quota(
    monkeypatch, fake_acquire
):
    captured: dict = {}

    def fake_post(**kwargs):
        captured.update(kwargs)
        return _GEMINI_OK

    monkeypatch.setattr(gemini_client, "post_generate_content", fake_post)
    runtime = llm_client.LlmRuntime(
        model="gemini-2.0-flash", gemini_api_key="g-key", preprompt="PRE"
    )
    out = await llm_client.complete_json(runtime, "BODY", response_schema={"type": "object"})

    assert out == "RESULT"
    assert captured["model"] == "gemini-2.0-flash"
    body = captured["body"]
    assert body["generationConfig"]["responseSchema"] == {"type": "object"}
    assert "PRE" in body["contents"][0]["parts"][0]["text"]
    assert "BODY" in body["contents"][0]["parts"][0]["text"]
    # Gemini 경로는 호출 직전 rate limiter 슬롯을 예약한다(기존 추정식 재사용).
    full = body["contents"][0]["parts"][0]["text"]
    assert fake_acquire == [gemini_rate_limiter.estimate_tokens("", full)]


async def test_gateway_passes_per_call_options(monkeypatch, fake_acquire):
    captured: dict = {}

    def fake_post(**kwargs):
        captured.update(kwargs)
        return _GEMINI_OK

    monkeypatch.setattr(gemini_client, "post_generate_content", fake_post)
    runtime = llm_client.LlmRuntime(model="gemini-2.0-flash", gemini_api_key="k")
    await llm_client.complete_json(
        runtime,
        "BODY",
        system_instruction="SYS",
        temperature=0.1,
        timeout_seconds=240.0,
        max_attempts=1,
    )
    # per-call 옵션(timeout/max_attempts)이 provider client로 그대로 전달된다.
    assert captured["timeout_seconds"] == 240.0
    assert captured["max_attempts"] == 1
    body = captured["body"]
    assert body["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert body["generationConfig"]["temperature"] == 0.1
    # 전용 system_instruction이 있으면 사전 프롬프트를 prepend하지 않는다.
    assert body["contents"][0]["parts"][0]["text"] == "BODY"
    # 추정 토큰은 system_instruction + prompt 기준(기존 batch_poi/교정과 동일).
    assert fake_acquire == [gemini_rate_limiter.estimate_tokens("SYS", "BODY")]


async def test_deepseek_per_call_options_passthrough(monkeypatch, fake_acquire):
    captured: dict = {}

    def fake_chat(**kwargs):
        captured.update(kwargs)
        return _DEEPSEEK_OK

    monkeypatch.setattr(deepseek_client, "post_chat_completion_payload", fake_chat)
    runtime = llm_client.LlmRuntime(model="deepseek-v4-pro", deepseek_api_key="k")
    await llm_client.complete_text(
        runtime, "BODY", system_instruction="SYS", temperature=0.1,
        timeout_seconds=33.0, max_attempts=2,
    )
    assert captured["timeout_seconds"] == 33.0
    assert captured["max_attempts"] == 2
    assert captured["temperature"] == 0.1
    assert captured["system_instruction"] == "SYS"
    assert captured["json_mode"] is False


# --- usage 실측 (LlmResult + 구조화 로그) ---


async def test_generate_returns_result_with_gemini_usage(
    monkeypatch, fake_acquire, caplog
):
    monkeypatch.setattr(gemini_client, "post_generate_content", lambda **k: _GEMINI_OK)
    runtime = llm_client.LlmRuntime(model="gemini-2.0-flash", gemini_api_key="k")
    with caplog.at_level(logging.INFO, logger="ktc.etl.llm_client"):
        result = await llm_client.generate(runtime, "BODY")

    assert result.text == "RESULT"
    assert result.provider == "gemini"
    assert result.model == "gemini-2.0-flash"
    assert result.outcome == "ok"
    assert result.elapsed_seconds >= 0.0
    assert result.usage == llm_client.LlmUsage(
        prompt_tokens=120, output_tokens=30, total_tokens=150
    )
    assert result.estimated_tokens == fake_acquire[0]
    # 구조화 usage 로그(추정식 보정 데이터 원천 — PR-05)가 남는다.
    usage_logs = [r.message for r in caplog.records if r.message.startswith("llm_usage ")]
    assert len(usage_logs) == 1
    assert "provider=gemini" in usage_logs[0]
    assert "outcome=ok" in usage_logs[0]
    assert "prompt_tokens=120" in usage_logs[0]


async def test_generate_returns_result_with_deepseek_usage(monkeypatch, fake_acquire):
    monkeypatch.setattr(
        deepseek_client, "post_chat_completion_payload", lambda **k: _DEEPSEEK_OK
    )
    runtime = llm_client.LlmRuntime(model="deepseek-v4-flash", deepseek_api_key="k")
    result = await llm_client.generate(runtime, "BODY")

    assert result.provider == "deepseek"
    assert result.outcome == "ok"
    assert result.usage == llm_client.LlmUsage(
        prompt_tokens=77, output_tokens=11, total_tokens=88
    )
    assert result.estimated_tokens is None
    assert fake_acquire == []


# --- 예외 계약 ---


async def test_complete_json_wraps_provider_error(monkeypatch, fake_acquire):
    def boom(**kwargs):
        raise deepseek_client.DeepSeekRequestError(
            "fail", status_code=503, model="deepseek-v4-flash"
        )

    monkeypatch.setattr(deepseek_client, "post_chat_completion_payload", boom)
    runtime = llm_client.LlmRuntime(model="deepseek-v4-flash", deepseek_api_key="k")
    with pytest.raises(llm_client.LlmRequestError) as exc:
        await llm_client.complete_json(runtime, "BODY")
    assert exc.value.status_code == 503


async def test_complete_json_wraps_gemini_error(monkeypatch, fake_acquire):
    def boom(**kwargs):
        raise gemini_client.GeminiRequestError(
            "fail", status_code=429, model="gemini-2.0-flash"
        )

    monkeypatch.setattr(gemini_client, "post_generate_content", boom)
    runtime = llm_client.LlmRuntime(model="gemini-2.0-flash", gemini_api_key="k")
    with pytest.raises(llm_client.LlmRequestError) as exc:
        await llm_client.complete_json(runtime, "BODY")
    assert exc.value.status_code == 429


async def test_quota_rejection_propagates_and_skips_http_call(monkeypatch):
    async def deny(*, estimated_tokens: int) -> None:
        raise gemini_rate_limiter.GeminiQuotaExceeded("일일 한도 소진")

    called = {"post": 0}

    def fake_post(**kwargs):
        called["post"] += 1
        return _GEMINI_OK

    monkeypatch.setattr(gemini_rate_limiter, "acquire", deny)
    monkeypatch.setattr(gemini_client, "post_generate_content", fake_post)
    runtime = llm_client.LlmRuntime(model="gemini-2.0-flash", gemini_api_key="k")
    # 쿼터 거부는 기존 예외 클래스 그대로 전파(재노출 별칭 동일 객체).
    assert llm_client.GeminiQuotaExceeded is gemini_rate_limiter.GeminiQuotaExceeded
    with pytest.raises(gemini_rate_limiter.GeminiQuotaExceeded):
        await llm_client.complete_json(runtime, "BODY")
    assert called["post"] == 0


# --- 멀티모달 (parts/file_data pass-through) ---


async def test_generate_multimodal_passes_parts_and_surcharges_quota(
    monkeypatch, fake_acquire
):
    captured: dict = {}

    def fake_post(**kwargs):
        captured.update(kwargs)
        return _GEMINI_OK

    monkeypatch.setattr(gemini_client, "post_generate_content", fake_post)
    runtime = llm_client.LlmRuntime(
        model="gemini-2.0-flash", gemini_api_key="k", preprompt="PRE"
    )
    parts = [
        {"file_data": {"file_uri": "https://www.youtube.com/watch?v=abc"}},
        {"text": "요약하라"},
    ]
    out = await llm_client.generate_multimodal(
        runtime, parts, response_schema={"type": "object"}, timeout_seconds=12.0
    )

    assert out == "RESULT"
    sent = captured["body"]["contents"][0]["parts"]
    # media part는 그대로 pass-through, 첫 text part에만 사전 프롬프트 prepend.
    assert sent[0] == {"file_data": {"file_uri": "https://www.youtube.com/watch?v=abc"}}
    assert sent[1]["text"].startswith("PRE")
    assert sent[1]["text"].endswith("요약하라")
    assert captured["timeout_seconds"] == 12.0
    # 보수적 추정: 텍스트 추정 + media part당 고정 가산.
    expected = (
        gemini_rate_limiter.estimate_tokens("", sent[1]["text"])
        + llm_client.MULTIMODAL_MEDIA_TOKEN_SURCHARGE
    )
    assert fake_acquire == [expected]
    # 호출자 parts 리스트는 변형하지 않는다.
    assert parts[1]["text"] == "요약하라"


async def test_generate_multimodal_rejects_deepseek(fake_acquire):
    runtime = llm_client.LlmRuntime(model="deepseek-v4-flash", deepseek_api_key="k")
    with pytest.raises(ValueError):
        await llm_client.generate_multimodal(runtime, [{"text": "x"}])
    assert fake_acquire == []


async def test_generate_requires_exactly_one_input():
    runtime = llm_client.LlmRuntime(model="gemini-2.0-flash", gemini_api_key="k")
    with pytest.raises(ValueError):
        await llm_client.generate(runtime)
    with pytest.raises(ValueError):
        await llm_client.generate(runtime, "BODY", parts=[{"text": "x"}])


# --- provider client 재시도/본문 (기존 계약 유지) ---


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


def test_deepseek_payload_variant_returns_usage(monkeypatch):
    class FakeResp:
        status_code = 200

        @staticmethod
        def json():
            return _DEEPSEEK_OK

    monkeypatch.setattr(
        deepseek_client.requests, "post", lambda *a, **k: FakeResp()
    )
    payload = deepseek_client.post_chat_completion_payload(
        api_key="k", model="deepseek-v4-pro", prompt="hi json"
    )
    assert payload["usage"]["total_tokens"] == 88
    assert (
        deepseek_client.extract_message_content(payload, model="deepseek-v4-pro")
        == '{"summary": "x", "places": []}'
    )
