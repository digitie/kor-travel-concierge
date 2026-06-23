"""settings_service / audit_service 단위 테스트."""

from __future__ import annotations

import types

import pytest

from ktc.services import audit_service, settings_service


async def test_settings_upsert_and_get(session):
    await settings_service.set_setting(session, "gemini_engine_version", "gemini-flash-latest")
    value = await settings_service.get_setting(session, "gemini_engine_version")
    assert value == "gemini-flash-latest"

    # 같은 키 재설정은 갱신된다.
    await settings_service.set_setting(session, "gemini_engine_version", "gemini-2.0-flash")
    assert await settings_service.get_setting(session, "gemini_engine_version") == "gemini-2.0-flash"


async def test_settings_rejects_unknown_gemini_engine(session):
    with pytest.raises(ValueError, match="지원하지 않는 AI 엔진"):
        await settings_service.set_setting(
            session,
            "gemini_engine_version",
            "gemini-unknown-model",
        )


async def test_settings_get_default(session):
    assert await settings_service.get_setting(session, "missing", default="x") == "x"


async def test_get_all_merges_env_default(session):
    merged = await settings_service.get_all(session)
    # DB에 값이 없어도 .env 기반 기본값이 들어온다.
    assert "gemini_engine_version" in merged
    assert merged["gemini_engine_default"] == "gemini-2.5-flash"
    assert merged["gemini_engine_version"] in merged["gemini_engine_options"]
    assert "gemini-2.0-flash" in merged["gemini_engine_options"]

    with pytest.raises(ValueError, match="지원하지 않는 설정 키"):
        await settings_service.set_setting(session, "custom_key", "custom_value")


async def test_set_many_commits_allowed_settings_together(session):
    await settings_service.set_many(
        session,
        {"gemini_engine_version": "gemini-2.0-flash"},
    )
    merged2 = await settings_service.get_all(session)
    assert merged2["gemini_engine_version"] == "gemini-2.0-flash"


async def test_get_secret_db_override_and_env_fallback(session, monkeypatch):
    fake = types.SimpleNamespace(YOUTUBE_API_KEY="env-youtube")
    monkeypatch.setattr(settings_service, "get_settings", lambda: fake)
    # DB 미저장 → .env 폴백.
    assert await settings_service.get_secret(session, "youtube_api_key") == "env-youtube"
    # DB 저장값이 .env보다 우선.
    await settings_service.set_setting(session, "youtube_api_key", "db-youtube")
    assert await settings_service.get_secret(session, "youtube_api_key") == "db-youtube"


async def test_get_secret_unknown_key_raises(session):
    with pytest.raises(ValueError, match="알 수 없는 시크릿 키"):
        await settings_service.get_secret(session, "not_a_secret")


async def test_get_all_exposes_api_key_set_flags(session):
    merged = await settings_service.get_all(session)
    assert set(merged["api_keys"]) == set(settings_service.SECRET_ENV_ATTRS)
    for entry in merged["api_keys"].values():
        # 값은 노출하지 않고 설정 여부만 반환한다.
        assert list(entry) == ["set"]
        assert isinstance(entry["set"], bool)

    await settings_service.set_setting(session, "kakao_rest_api_key", "db-kakao")
    merged2 = await settings_service.get_all(session)
    assert merged2["api_keys"]["kakao_rest_api_key"]["set"] is True


async def test_audit_record_and_list(session):
    await audit_service.record(
        session,
        actor_type="web",
        action="harvest.create",
        target_type="crawl_run",
        target_id="1",
        payload={"query": "부산"},
    )
    logs = await audit_service.list_recent(session)
    assert len(logs) == 1
    assert logs[0].action == "harvest.create"
    assert '"query": "부산"' in logs[0].payload_json
