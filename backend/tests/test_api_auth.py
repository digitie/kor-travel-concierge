"""API 인증(인증 코드) 동작 테스트.

로컬 환경에서는 인증 없이 통과하고, 비-local 환경에서는 `X-API-Key`를 요구하는지
검증한다. 인증 정책은 `Settings`에만 의존하므로 `get_settings`를 오버라이드해
환경을 모사한다.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from ktc.core.config import Settings, get_settings
from ktc.core.database import get_session
from ktc.services import public_api_key_service
from main import app

PROD_API_KEY = "secret-key-1"


@pytest.fixture(autouse=True)
def _clear_public_api_key_cache():
    """프로세스 전역 공개 키 캐시가 테스트 간 오염되지 않도록 초기화한다."""
    public_api_key_service.invalidate_public_api_key_cache()
    yield
    public_api_key_service.invalidate_public_api_key_cache()


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


async def test_non_local_accepts_db_public_api_key(session_factory):
    settings = Settings(APP_ENV="production", API_AUTH_ENABLED=True, API_KEYS="")
    async with session_factory() as session:
        api_key, _item = await public_api_key_service.create_key(
            session,
            label="테스트 키",
            created_by="test",
        )
    async with _make_client(session_factory, settings) as ac:
        resp = await ac.get(f"/api/v1/runs?key={api_key}")
        assert resp.status_code == 200
    app.dependency_overrides.clear()


async def test_admin_proxy_bypasses_public_api_key(session_factory):
    settings = Settings(
        APP_ENV="production",
        API_AUTH_ENABLED=True,
        API_KEYS="",
        KTC_ADMIN_PROXY_SECRET="proxy-secret-with-enough-length",
    )
    async with _make_client(session_factory, settings) as ac:
        resp = await ac.get(
            "/api/v1/admin/login-events",
            headers={
                "X-KTC-Actor": "admin",
                "X-KTC-Admin-Proxy-Secret": "proxy-secret-with-enough-length",
            },
        )
        assert resp.status_code == 200
    app.dependency_overrides.clear()


async def test_admin_proxy_rejects_missing_or_wrong_secret(session_factory):
    settings = Settings(
        APP_ENV="production",
        API_AUTH_ENABLED=True,
        API_KEYS="",
        KTC_ADMIN_PROXY_SECRET="proxy-secret-with-enough-length",
    )
    async with _make_client(session_factory, settings) as ac:
        missing = await ac.get(
            "/api/v1/admin/login-events",
            headers={"X-KTC-Actor": "admin"},
        )
        wrong = await ac.get(
            "/api/v1/admin/login-events",
            headers={
                "X-KTC-Actor": "admin",
                "X-KTC-Admin-Proxy-Secret": "wrong-secret",
            },
        )
        ok = await ac.get(
            "/api/v1/admin/login-events",
            headers={
                "X-KTC-Actor": "admin",
                "X-KTC-Admin-Proxy-Secret": "proxy-secret-with-enough-length",
            },
        )

    assert missing.status_code == 403
    assert wrong.status_code == 403
    assert ok.status_code == 200
    app.dependency_overrides.clear()


async def test_trusted_client_cidr_bypasses_key_when_enabled(session_factory):
    """키 없는 CIDR 우회는 명시 활성화 시에만 동작한다."""
    settings = Settings(
        APP_ENV="production",
        API_AUTH_ENABLED=True,
        API_KEYS="",
        API_TRUSTED_CLIENT_CIDRS="127.0.0.0/8",
        API_TRUSTED_CLIENT_BYPASS_ENABLED=True,
    )
    async with _make_client(session_factory, settings) as ac:
        resp = await ac.get("/api/v1/runs")
        assert resp.status_code == 200
    app.dependency_overrides.clear()


async def test_trusted_client_cidr_ignored_without_enable_flag(session_factory):
    """활성 플래그 없이 CIDR만 설정하면 우회되지 않는다(스푸핑 위험 차단)."""
    settings = Settings(
        APP_ENV="production",
        API_AUTH_ENABLED=True,
        API_KEYS="",
        API_TRUSTED_CLIENT_CIDRS="127.0.0.0/8",
        # API_TRUSTED_CLIENT_BYPASS_ENABLED 기본 False
    )
    async with _make_client(session_factory, settings) as ac:
        resp = await ac.get("/api/v1/runs")
        assert resp.status_code == 401
    app.dependency_overrides.clear()


async def test_revoked_public_api_key_rejected(session_factory):
    """폐기된 공개 API 키는 더 이상 통과하지 못한다."""
    settings = Settings(
        APP_ENV="production",
        API_AUTH_ENABLED=True,
        API_KEYS="",
        PUBLIC_API_KEY_CACHE_TTL_SECONDS=0,
    )
    async with session_factory() as session:
        api_key, item = await public_api_key_service.create_key(
            session, label="폐기 대상", created_by="test"
        )
    async with _make_client(session_factory, settings) as ac:
        ok = await ac.get(f"/api/v1/runs?key={api_key}")
        assert ok.status_code == 200
        async with session_factory() as session:
            await public_api_key_service.revoke_key(
                session, item.id, revoked_by="test"
            )
        revoked = await ac.get(f"/api/v1/runs?key={api_key}")
        assert revoked.status_code == 401
    app.dependency_overrides.clear()


async def test_deny_all_when_auth_required_but_no_keys(session_factory):
    """인증이 필요한데 정적/공개 키가 모두 없으면 전부 거부한다."""
    settings = Settings(APP_ENV="production", API_AUTH_ENABLED=True, API_KEYS="")
    async with _make_client(session_factory, settings) as ac:
        resp = await ac.get("/api/v1/runs")
        assert resp.status_code == 401
    app.dependency_overrides.clear()


async def test_admin_proxy_rejected_outside_trusted_cidr(session_factory):
    """올바른 secret이어도 peer가 신뢰 CIDR 밖이면 관리자 API는 403."""
    settings = Settings(
        APP_ENV="production",
        API_AUTH_ENABLED=True,
        API_KEYS="",
        KTC_ADMIN_PROXY_SECRET="proxy-secret-with-enough-length",
        # 127.0.0.1(테스트 peer)을 포함하지 않는 CIDR로 좁힌다.
        KTC_ADMIN_TRUSTED_PROXY_CIDRS="10.123.0.0/24",
    )
    async with _make_client(session_factory, settings) as ac:
        resp = await ac.get(
            "/api/v1/admin/login-events",
            headers={
                "X-KTC-Actor": "admin",
                "X-KTC-Admin-Proxy-Secret": "proxy-secret-with-enough-length",
            },
        )
        assert resp.status_code == 403
    app.dependency_overrides.clear()


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
