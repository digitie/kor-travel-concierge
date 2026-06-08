"""settings_service / audit_service 단위 테스트."""

from __future__ import annotations

import pytest

from app.services import audit_service, settings_service


async def test_settings_upsert_and_get(session):
    await settings_service.set_setting(session, "gemini_engine_version", "gemini-1.5-pro")
    value = await settings_service.get_setting(session, "gemini_engine_version")
    assert value == "gemini-1.5-pro"

    # 같은 키 재설정은 갱신된다.
    await settings_service.set_setting(session, "gemini_engine_version", "gemini-2.0-flash")
    assert await settings_service.get_setting(session, "gemini_engine_version") == "gemini-2.0-flash"


async def test_settings_rejects_unknown_gemini_engine(session):
    with pytest.raises(ValueError, match="지원하지 않는 Gemini 엔진 버전"):
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
    assert merged["gemini_engine_default"] == "gemini-2.0-flash"
    assert merged["gemini_engine_version"] in merged["gemini_engine_options"]
    assert "gemini-1.5-pro" in merged["gemini_engine_options"]

    with pytest.raises(ValueError, match="지원하지 않는 설정 키"):
        await settings_service.set_setting(session, "custom_key", "custom_value")


async def test_set_many_commits_allowed_settings_together(session):
    await settings_service.set_many(
        session,
        {"gemini_engine_version": "gemini-1.5-flash"},
    )
    merged2 = await settings_service.get_all(session)
    assert merged2["gemini_engine_version"] == "gemini-1.5-flash"


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
