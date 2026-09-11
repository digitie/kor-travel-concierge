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


async def test_deepseek_flash_is_current_default_and_v4_flash_retired(session):
    """deepseek-flash(V4.1-Flash)가 옵션에 있고 선택 가능해야 하며, 구 식별자
    deepseek-v4-flash(V4.0-Flash)는 지원을 완전히 내려 더 이상 유효하지 않아야 한다."""
    from ktc.core.config import DEEPSEEK_ENGINE_OPTIONS

    assert DEEPSEEK_ENGINE_OPTIONS[0] == "deepseek-flash"
    assert "deepseek-v4-flash" not in DEEPSEEK_ENGINE_OPTIONS

    await settings_service.set_setting(session, "gemini_engine_version", "deepseek-flash")
    assert await settings_service.get_setting(session, "gemini_engine_version") == "deepseek-flash"

    with pytest.raises(ValueError, match="지원하지 않는 AI 엔진"):
        await settings_service.set_setting(session, "gemini_engine_version", "deepseek-v4-flash")


async def test_get_all_falls_back_to_gemini_default_for_stale_deepseek_v4_flash_row(session):
    """마이그레이션을 거치지 않고 deepseek-v4-flash 값이 남아 있는(예: 배포 전 상태를
    흉내낸) 기존 행은 조용히 Gemini 기본값으로 폴백한다 — provider가 말없이 바뀌는
    이 안전망 동작 자체를 명시적으로 고정해 둔다(실제 배포에서는 DB 값을 직접
    deepseek-flash로 마이그레이션해 이 폴백이 발동하지 않도록 한다)."""
    from ktc.models import SystemSetting

    session.add(SystemSetting(key="gemini_engine_version", value="deepseek-v4-flash"))
    await session.commit()

    merged = await settings_service.get_all(session)
    assert merged["gemini_engine_version"] == settings_service.GEMINI_ENGINE_VERSION_DEFAULT


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
