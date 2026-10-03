"""종료된 작업의 LLM 스레드가 재시도를 계속하지 않는지 검증한다."""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from ktc.etl import deepseek_client, gemini_client, llm_client


@pytest.mark.asyncio
@pytest.mark.parametrize("client", [gemini_client, deepseek_client])
@pytest.mark.parametrize("during_request", [True, False])
async def test_cancel_stops_http_retry_and_joins_thread(
    monkeypatch, client, during_request
):
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def post(*args, **kwargs):
        nonlocal calls
        calls += 1
        started.set()
        if during_request:
            assert release.wait(5)
        return SimpleNamespace(status_code=503, json=lambda: {})

    monkeypatch.setattr(client.requests, "post", post)
    kwargs = dict(
        api_key="test-placeholder",
        model="test",
        max_attempts=3,
        base_delay_seconds=30,
        jitter=0,
    )
    if client is gemini_client:
        function = client.post_generate_content
        kwargs["body"] = {}
    else:
        function = client.post_chat_completion_payload
        kwargs["prompt"] = "test"
    task = asyncio.create_task(llm_client._call_in_thread(function, **kwargs))
    for _ in range(100):
        if started.is_set():
            break
        await asyncio.sleep(0.01)
    assert started.is_set()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    assert calls == 1
