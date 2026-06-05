"""API 엔드포인트 통합 테스트.

`get_session` 의존성을 테스트 엔진으로 오버라이드해 ASGI 앱을 직접 호출한다.
"""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import get_session
from main import app


@pytest_asyncio.fixture
async def client(session_factory):
    async def override_get_session():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def test_harvest_create_and_status(client):
    resp = await client.post("/api/harvest", json={"query": "제주도 맛집", "max_videos": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "pending"
    job_id = body["job_id"]

    status = await client.get(f"/api/harvest/{job_id}")
    assert status.status_code == 200
    sbody = status.json()
    assert sbody["job_id"] == job_id
    assert sbody["state"] == "pending"
    assert sbody["progress"] == 0.0


async def test_harvest_status_404(client):
    resp = await client.get("/api/harvest/999999")
    assert resp.status_code == 404


async def test_settings_roundtrip(client):
    resp = await client.post("/api/settings", json={"gemini_engine_version": "gemini-1.5-pro"})
    assert resp.status_code == 200
    assert resp.json()["settings"]["gemini_engine_version"] == "gemini-1.5-pro"

    get_resp = await client.get("/api/settings")
    assert get_resp.json()["gemini_engine_version"] == "gemini-1.5-pro"


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
