"""YouTubeClient batching 테스트 (channels/playlists id 50개 상한 회피)."""

from __future__ import annotations

import httpx
import pytest

from ktc.etl.youtube_client import YouTubeClient


@pytest.mark.asyncio
async def test_channels_list_splits_into_batches_of_50():
    """YouTube `channels.list`는 `id`에 50개 초과 시 항상 400을 반환한다.

    호출부(`pipeline.py`)가 중복 제거된 채널 ID를 그대로 넘겨도(예: 148개) 안전하도록
    `channels_list`가 50개 단위로 나눠 여러 번 호출하고 결과를 합쳐야 한다.
    """
    ids = [f"UC{i:022d}" for i in range(120)]
    requested_id_batches: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_ids = request.url.params["id"].split(",")
        assert len(requested_ids) <= 50
        requested_id_batches.append(requested_ids)
        items = [{"id": cid, "snippet": {}} for cid in requested_ids]
        return httpx.Response(200, json={"items": items})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = YouTubeClient("key", http_client)
        data = await client.channels_list(ids)

    assert len(requested_id_batches) == 3  # 120 -> 50 + 50 + 20
    assert sum(len(batch) for batch in requested_id_batches) == 120
    assert [item["id"] for item in data["items"]] == ids


@pytest.mark.asyncio
async def test_channels_list_single_string_id_still_works():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["id"] == "UC1"
        return httpx.Response(200, json={"items": [{"id": "UC1"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = YouTubeClient("key", http_client)
        data = await client.channels_list("UC1")

    assert [item["id"] for item in data["items"]] == ["UC1"]


@pytest.mark.asyncio
async def test_playlists_list_splits_into_batches_of_50():
    ids = [f"PL{i:022d}" for i in range(75)]
    requested_id_batches: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_ids = request.url.params["id"].split(",")
        assert len(requested_ids) <= 50
        requested_id_batches.append(requested_ids)
        items = [{"id": pid} for pid in requested_ids]
        return httpx.Response(200, json={"items": items})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = YouTubeClient("key", http_client)
        data = await client.playlists_list(ids)

    assert len(requested_id_batches) == 2  # 75 -> 50 + 25
    assert [item["id"] for item in data["items"]] == ids
