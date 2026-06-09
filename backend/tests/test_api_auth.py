"""API 인증(인증 코드) 동작 테스트.

로컬 환경에서는 인증 없이 통과하고, 비-local 환경에서는 `X-API-Key`를 요구하는지
검증한다. 인증 정책은 `Settings`에만 의존하므로 `get_settings`를 오버라이드해
환경을 모사한다.
"""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings, get_settings
from app.core.database import get_session
from main import app

PROD_API_KEY = "secret-key-1"


def _make_client(session_factory, settings: Settings) -> AsyncClient:
    async def override_get_session():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_settings] = lambda: settings
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest_asyncio.fixture
async def prod_client(session_factory):
    """인증이 강제되는 비-local 환경 클라이언트."""
    settings = Settings(
        APP_ENV="production",
        API_AUTH_ENABLED=True,
        API_KEYS=f"{PROD_API_KEY},secret-key-2",
    )
    async with _make_client(session_factory, settings) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def local_client(session_factory):
    """로컬 환경 클라이언트(인증 우회)."""
    settings = Settings(APP_ENV="local")
    async with _make_client(session_factory, settings) as ac:
        yield ac
    app.dependency_overrides.clear()


async def test_local_env_bypasses_auth(local_client):
    """로컬 실행은 인증 코드 없이도 동작한다."""
    resp = await local_client.get("/api/v1/runs")
    assert resp.status_code == 200


async def test_non_local_requires_api_key(prod_client):
    """비-local 환경에서 인증 코드 없는 요청은 401."""
    resp = await prod_client.get("/api/v1/runs")
    assert resp.status_code == 401


async def test_non_local_rejects_wrong_key(prod_client):
    resp = await prod_client.get("/api/v1/runs", headers={"X-API-Key": "wrong"})
    assert resp.status_code == 401


async def test_non_local_accepts_valid_key(prod_client):
    resp = await prod_client.get("/api/v1/runs", headers={"X-API-Key": PROD_API_KEY})
    assert resp.status_code == 200


async def test_health_is_open_without_key(prod_client):
    """health/liveness는 버전·인증과 무관하게 열려 있다."""
    resp = await prod_client.get("/health")
    assert resp.status_code == 200


def test_settings_auth_required_rules():
    """auth_required 규칙: local 우회, 비-local 요구, 플래그 강제."""
    assert Settings(APP_ENV="local").auth_required is False
    assert Settings(APP_ENV="test").auth_required is False
    assert Settings(APP_ENV="production").auth_required is True
    assert Settings(APP_ENV="local", API_AUTH_ENABLED=True).auth_required is True
