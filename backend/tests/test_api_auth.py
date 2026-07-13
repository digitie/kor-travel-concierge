"""API 인증(인증 코드) 동작 테스트.

로컬 환경에서는 인증 없이 통과하고, 비-local 환경에서는 `X-API-Key`를 요구하는지
검증한다. 인증 정책은 `Settings`에만 의존하므로 `get_settings`를 오버라이드해
환경을 모사한다.
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from ktc.core import database
from ktc.core.config import Settings, get_settings
from ktc.core.database import get_repeatable_read_session, get_session
from ktc.core.security import is_read_scope_path
from ktc.models import PublicApiKey
from ktc.services import place_service, public_api_key_service
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

    async def override_repeatable_read_session():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[
        get_repeatable_read_session
    ] = override_repeatable_read_session
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
        resp = await ac.get(f"/api/v1/destinations?key={api_key}")
        assert resp.status_code == 200
    app.dependency_overrides.clear()


async def test_public_key_cache_miss_uses_separate_repeatable_read_session(
    session_factory, monkeypatch
):
    """인증 DB 조회가 먼저 일어나도 목록 transaction 격리를 보장한다."""
    settings = Settings(APP_ENV="production", API_AUTH_ENABLED=True, API_KEYS="")
    async with session_factory() as session:
        api_key, _item = await public_api_key_service.create_key(
            session,
            label="격리 수준 테스트 키",
            created_by="test",
            scope="read",
        )

    observed: dict[str, str] = {}
    original_list = place_service.list_place_summaries_page

    async def observed_list(session, **kwargs):
        observed["isolation"] = str(
            await session.scalar(text("SHOW transaction_isolation"))
        )
        return await original_list(session, **kwargs)

    monkeypatch.setattr(database, "async_session_factory", session_factory)
    monkeypatch.setattr(place_service, "list_place_summaries_page", observed_list)
    async with _make_client(session_factory, settings) as ac:
        # 테스트 override가 아닌 실제 목록 전용 dependency를 사용한다.
        app.dependency_overrides.pop(get_repeatable_read_session)
        response = await ac.get(
            "/api/v1/destinations", headers={"X-API-Key": api_key}
        )

    assert response.status_code == 200
    assert observed == {"isolation": "repeatable read"}
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
    """키 없는 CIDR 우회는 명시 활성화해도 read 공급 경로만 허용한다."""
    settings = Settings(
        APP_ENV="production",
        API_AUTH_ENABLED=True,
        API_KEYS="",
        API_TRUSTED_CLIENT_CIDRS="127.0.0.0/8",
        API_TRUSTED_CLIENT_BYPASS_ENABLED=True,
    )
    async with _make_client(session_factory, settings) as ac:
        read_resp = await ac.get("/api/v1/destinations")
        admin_resp = await ac.get("/api/v1/runs")
        assert read_resp.status_code == 200
        assert admin_resp.status_code == 403
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
        ok = await ac.get(f"/api/v1/destinations?key={api_key}")
        assert ok.status_code == 200
        async with session_factory() as session:
            await public_api_key_service.revoke_key(
                session, item.id, revoked_by="test"
            )
        revoked = await ac.get(f"/api/v1/destinations?key={api_key}")
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


async def test_login_event_retention_cap(session_factory, monkeypatch):
    """감사 로그가 보존 상한을 넘으면 오래된 행부터 정리된다."""
    from ktc.services import login_event_service

    class _CappedSettings:
        LOGIN_AUDIT_MAX_ROWS = 3

    monkeypatch.setattr(login_event_service, "get_settings", lambda: _CappedSettings())
    async with session_factory() as session:
        for _ in range(6):
            await login_event_service.record(
                session,
                event_type="login",
                outcome="denied",
                attempted_username="admin",
                reason="invalid_credentials",
                client_ip=None,
                user_agent=None,
                next_path=None,
            )
        rows = await login_event_service.list_recent(session, limit=100)
        assert len(rows) == 3


def test_settings_auth_required_rules():
    """auth_required 규칙: local 우회, 비-local 요구, 플래그 강제."""
    assert Settings(APP_ENV="local").auth_required is False
    assert Settings(APP_ENV="test").auth_required is False
    assert Settings(APP_ENV="production").auth_required is True
    assert Settings(APP_ENV="local", API_AUTH_ENABLED=True).auth_required is True


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/destinations",
        "/api/v1/destinations/facets",
        "/api/v1/destinations/export",
        "/api/v1/destinations/123/detail",
        "/api/v1/features/snapshot",
        "/api/v1/features/changes",
        "/api/v1/themes",
        "/api/v1/themes/places",
        "/api/v1/themes/video/abc_123/places",
        "/api/v1/categories",
        "/api/v1/categories/match",
    ],
)
def test_read_scope_policy_allows_only_declared_supply_paths(path):
    assert is_read_scope_path("GET", path) is True
    assert is_read_scope_path("HEAD", path) is True


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/v1/destinations"),
        ("GET", "/api/v1/runs"),
        ("GET", "/api/v1/destinations/unmatched"),
        ("GET", "/api/v1/destinations/candidates/1/detail"),
        ("GET", "/api/v1/destinations/not-a-number/detail"),
        ("GET", "/api/v1/features/internal"),
        ("GET", "/api/v1/themes/internal"),
        ("GET", "/api/v1/categories/internal"),
    ],
)
def test_read_scope_policy_denies_unmatched_paths_by_default(method, path):
    assert is_read_scope_path(method, path) is False


async def test_read_key_allows_supply_and_denies_write_and_internal_gets(
    session_factory,
):
    settings = Settings(APP_ENV="production", API_AUTH_ENABLED=True, API_KEYS="")
    async with session_factory() as session:
        api_key, _item = await public_api_key_service.create_key(
            session,
            label="소비자 read 키",
            created_by="test",
            scope="read",
        )

    headers = {"X-API-Key": api_key}
    async with _make_client(session_factory, settings) as ac:
        destinations = await ac.get("/api/v1/destinations", headers=headers)
        snapshot = await ac.get("/api/v1/features/snapshot", headers=headers)
        harvest = await ac.post("/api/v1/harvest", headers=headers, json={})
        delete_place = await ac.delete("/api/v1/destinations/1", headers=headers)
        settings_get = await ac.get("/api/v1/settings", headers=headers)
        unmatched = await ac.get("/api/v1/destinations/unmatched", headers=headers)
        candidate = await ac.get(
            "/api/v1/destinations/candidates/1/detail", headers=headers
        )

    assert destinations.status_code == 200
    assert snapshot.status_code == 200
    assert harvest.status_code == 403
    assert delete_place.status_code == 403
    assert settings_get.status_code == 403
    assert unmatched.status_code == 403
    assert candidate.status_code == 403
    app.dependency_overrides.clear()


async def test_admin_db_key_header_allows_internal_api_but_not_admin_proxy_api(
    session_factory,
):
    settings = Settings(APP_ENV="production", API_AUTH_ENABLED=True, API_KEYS="")
    async with session_factory() as session:
        api_key, _item = await public_api_key_service.create_key(
            session,
            label="운영자 admin 키",
            created_by="test",
            scope="admin",
        )

    headers = {"X-API-Key": api_key}
    async with _make_client(session_factory, settings) as ac:
        internal = await ac.get("/api/v1/runs", headers=headers)
        admin_proxy_only = await ac.get(
            "/api/v1/admin/public-api-keys", headers=headers
        )

    assert internal.status_code == 200
    assert admin_proxy_only.status_code == 403
    app.dependency_overrides.clear()


async def test_query_key_rejects_admin_db_and_static_keys(session_factory):
    static_admin_key = "static-admin-key"
    settings = Settings(
        APP_ENV="production",
        API_AUTH_ENABLED=True,
        API_KEYS=static_admin_key,
    )
    async with session_factory() as session:
        db_admin_key, _item = await public_api_key_service.create_key(
            session,
            label="query 금지 admin 키",
            created_by="test",
            scope="admin",
        )
        db_read_key, _read_item = await public_api_key_service.create_key(
            session,
            label="header 우선순위 read 키",
            created_by="test",
            scope="read",
        )

    async with _make_client(session_factory, settings) as ac:
        db_admin = await ac.get(f"/api/v1/destinations?key={db_admin_key}")
        db_admin_with_empty_header = await ac.get(
            f"/api/v1/destinations?key={db_admin_key}",
            headers={"X-API-Key": ""},
        )
        static_admin = await ac.get(f"/api/v1/destinations?key={static_admin_key}")
        static_header = await ac.get(
            "/api/v1/runs", headers={"X-API-Key": static_admin_key}
        )
        invalid_header_with_read_query = await ac.get(
            f"/api/v1/destinations?key={db_read_key}",
            headers={"X-API-Key": "invalid-header"},
        )
        valid_header_with_invalid_query = await ac.get(
            "/api/v1/runs?key=invalid-query",
            headers={"X-API-Key": static_admin_key},
        )

    assert db_admin.status_code == 403
    assert db_admin_with_empty_header.status_code == 403
    assert static_admin.status_code == 403
    assert static_header.status_code == 200
    assert invalid_header_with_read_query.status_code == 401
    assert valid_header_with_invalid_query.status_code == 200
    app.dependency_overrides.clear()


async def test_key_scope_cache_is_invalidated_on_create_and_revoke(session_factory):
    async with session_factory() as session:
        assert not await public_api_key_service.cached_active_key_scopes(
            session, ttl_seconds=600
        )
        api_key, item = await public_api_key_service.create_key(
            session,
            label="cache 무효화",
            created_by="test",
            scope="admin",
        )
        after_create = await public_api_key_service.cached_active_key_scopes(
            session, ttl_seconds=600
        )
        assert (
            public_api_key_service.public_api_key_scope(api_key, after_create)
            == "admin"
        )

        await public_api_key_service.revoke_key(session, item.id, revoked_by="test")
        after_revoke = await public_api_key_service.cached_active_key_scopes(
            session, ttl_seconds=600
        )
        assert (
            public_api_key_service.public_api_key_scope(api_key, after_revoke) is None
        )


async def test_cache_refill_does_not_republish_snapshot_stale_after_revoke(
    session_factory,
    monkeypatch,
):
    async with session_factory() as session:
        api_key, item = await public_api_key_service.create_key(
            session,
            label="동시 폐기 cache",
            created_by="test",
            scope="admin",
        )

    first_select_finished = asyncio.Event()
    resume_first_loader = asyncio.Event()
    original_active_key_scopes = public_api_key_service.active_key_scopes
    select_calls = 0

    async def delayed_active_key_scopes(session):
        nonlocal select_calls
        select_calls += 1
        snapshot = await original_active_key_scopes(session)
        if select_calls == 1:
            first_select_finished.set()
            await resume_first_loader.wait()
        return snapshot

    monkeypatch.setattr(
        public_api_key_service,
        "active_key_scopes",
        delayed_active_key_scopes,
    )

    async with session_factory() as loader_session:
        loader = asyncio.create_task(
            public_api_key_service.cached_active_key_scopes(
                loader_session,
                ttl_seconds=600,
            )
        )
        await asyncio.wait_for(first_select_finished.wait(), timeout=2)
        async with session_factory() as revoker_session:
            await public_api_key_service.revoke_key(
                revoker_session,
                item.id,
                revoked_by="test",
            )
        resume_first_loader.set()
        scopes = await asyncio.wait_for(loader, timeout=2)

    assert select_calls == 2
    assert public_api_key_service.public_api_key_scope(api_key, scopes) is None


async def test_admin_proxy_issues_requested_scope_and_defaults_to_read(session_factory):
    settings = Settings(
        APP_ENV="production",
        API_AUTH_ENABLED=True,
        API_KEYS="",
        KTC_ADMIN_PROXY_SECRET="proxy-secret-with-enough-length",
    )
    headers = {
        "X-KTC-Actor": "admin",
        "X-KTC-Admin-Proxy-Secret": "proxy-secret-with-enough-length",
    }
    async with _make_client(session_factory, settings) as ac:
        admin_key = await ac.post(
            "/api/v1/admin/public-api-keys",
            headers=headers,
            json={"label": "운영자", "scope": "admin"},
        )
        read_key = await ac.post(
            "/api/v1/admin/public-api-keys",
            headers=headers,
            json={"label": "소비자"},
        )
        invalid = await ac.post(
            "/api/v1/admin/public-api-keys",
            headers=headers,
            json={"label": "잘못된 키", "scope": "write"},
        )

    assert admin_key.status_code == 200
    assert admin_key.json()["item"]["scope"] == "admin"
    assert read_key.status_code == 200
    assert read_key.json()["item"]["scope"] == "read"
    assert invalid.status_code == 422
    app.dependency_overrides.clear()


async def test_admin_key_create_rolls_back_when_audit_write_fails(
    session_factory,
    monkeypatch,
):
    settings = Settings(
        APP_ENV="production",
        API_AUTH_ENABLED=True,
        API_KEYS="",
        KTC_ADMIN_PROXY_SECRET="proxy-secret-with-enough-length",
    )

    async def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("ktc.api.routes.audit_service.record", fail_audit)
    headers = {
        "X-KTC-Actor": "admin",
        "X-KTC-Admin-Proxy-Secret": "proxy-secret-with-enough-length",
    }
    async with _make_client(session_factory, settings) as ac:
        with pytest.raises(RuntimeError, match="audit unavailable"):
            await ac.post(
                "/api/v1/admin/public-api-keys",
                headers=headers,
                json={"label": "감사 실패 admin", "scope": "admin"},
            )

    async with session_factory() as session:
        rows = (
            await session.execute(
                select(PublicApiKey).where(PublicApiKey.label == "감사 실패 admin")
            )
        ).scalars().all()
    assert rows == []
    app.dependency_overrides.clear()


async def test_public_api_key_scope_check_constraint_rejects_unknown_value(session):
    session.add(
        PublicApiKey(
            label="DB 제약 검증",
            key_hash=public_api_key_service.hash_public_api_key("invalid-scope-key"),
            key_hint="ope-key",
            scope="write",
            state="active",
            created_by="test",
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()
