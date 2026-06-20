"""`system_settings` 키-값 설정 서비스.

DB에 저장된 런타임 설정을 읽고 쓴다. 미저장 키는 `.env` 기반 기본값으로 보강한다.
런타임 수정 가능한 키: `gemini_engine_version`(=AI 엔진, Gemini/DeepSeek), `deepseek_api_key`,
`ai_preprompt`(사전 프롬프트). DeepSeek 키 값은 GET 응답에 평문으로 노출하지 않는다.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ktc.core.config import (
    AI_PREPROMPT_DEFAULT,
    GEMINI_ENGINE_VERSION_DEFAULT,
    LLM_ENGINE_OPTIONS,
    get_settings,
)
from ktc.etl.llm_client import LlmRuntime
from ktc.models import SystemSetting

ALLOWED_SETTING_KEYS = frozenset({"gemini_engine_version", "deepseek_api_key", "ai_preprompt"})
AI_PREPROMPT_MAX_LEN = 4000


def validate_setting_key(key: str) -> None:
    """런타임에서 수정 가능한 설정 키인지 검증한다."""
    if key not in ALLOWED_SETTING_KEYS:
        raise ValueError(f"지원하지 않는 설정 키: {key}")


def validate_setting_value(key: str, value: str) -> None:
    """설정 키와 값을 함께 검증한다."""
    validate_setting_key(key)
    if key == "gemini_engine_version" and value not in LLM_ENGINE_OPTIONS:
        allowed = ", ".join(LLM_ENGINE_OPTIONS)
        raise ValueError(f"지원하지 않는 AI 엔진: {value} (허용: {allowed})")
    if key == "ai_preprompt" and len(value) > AI_PREPROMPT_MAX_LEN:
        raise ValueError(f"사전 프롬프트가 너무 깁니다({AI_PREPROMPT_MAX_LEN}자 이하)")


async def get_setting(
    session: AsyncSession, key: str, default: str | None = None
) -> str | None:
    """단일 설정 값을 조회한다."""
    row = await session.get(SystemSetting, key)
    return row.value if row is not None else default


async def set_setting(
    session: AsyncSession, key: str, value: str, *, commit: bool = True
) -> SystemSetting:
    """설정 값을 upsert한다."""
    validate_setting_value(key, value)
    row = await session.get(SystemSetting, key)
    if row is None:
        row = SystemSetting(key=key, value=value)
        session.add(row)
    else:
        row.value = value
    if commit:
        await session.commit()
        await session.refresh(row)
    return row


async def set_many(session: AsyncSession, values: dict[str, str]) -> dict[str, str]:
    """여러 설정을 검증 후 하나의 트랜잭션으로 저장한다."""
    for key, value in values.items():
        validate_setting_value(key, value)
    rows: list[SystemSetting] = []
    for key, value in values.items():
        rows.append(await set_setting(session, key, value, commit=False))
    await session.commit()
    for row in rows:
        await session.refresh(row)
    return {row.key: row.value for row in rows}


async def _load_db_settings(session: AsyncSession) -> dict[str, str]:
    db: dict[str, str] = {}
    result = await session.execute(select(SystemSetting))
    for row in result.scalars().all():
        if row.key not in ALLOWED_SETTING_KEYS:
            continue
        try:
            validate_setting_value(row.key, row.value)
        except ValueError:
            continue
        db[row.key] = row.value
    return db


async def get_all(session: AsyncSession) -> dict[str, Any]:
    """DB 설정을 기본값(`.env`) 위에 덮어써 반환한다.

    DeepSeek 키는 평문으로 노출하지 않고 설정 여부(`deepseek_api_key_set`)만 반환한다.
    """
    settings = get_settings()
    db = await _load_db_settings(session)

    engine_version = db.get("gemini_engine_version") or settings.GEMINI_ENGINE_VERSION
    if engine_version not in LLM_ENGINE_OPTIONS:
        engine_version = GEMINI_ENGINE_VERSION_DEFAULT

    preprompt = db.get("ai_preprompt")
    if preprompt is None:
        preprompt = settings.AI_PREPROMPT or AI_PREPROMPT_DEFAULT

    deepseek_set = bool(db.get("deepseek_api_key") or settings.DEEPSEEK_API_KEY)

    return {
        "gemini_engine_version": engine_version,
        "gemini_engine_default": GEMINI_ENGINE_VERSION_DEFAULT,
        "gemini_engine_options": list(LLM_ENGINE_OPTIONS),
        "ai_preprompt": preprompt,
        "ai_preprompt_default": AI_PREPROMPT_DEFAULT,
        "deepseek_api_key_set": deepseek_set,
    }


async def get_gemini_engine_version(session: AsyncSession) -> str:
    """실제 AI 호출에 사용할 런타임 엔진명을 반환한다(Gemini 또는 DeepSeek)."""
    settings = await get_all(session)
    return settings["gemini_engine_version"]


async def get_ai_preprompt(session: AsyncSession) -> str:
    """모든 AI 프롬프트 앞에 붙는 사전 프롬프트(DB→env→기본 예제)."""
    value = await get_setting(session, "ai_preprompt")
    if value is not None:
        return value
    settings = get_settings()
    return settings.AI_PREPROMPT or AI_PREPROMPT_DEFAULT


async def get_deepseek_api_key(session: AsyncSession) -> str:
    """DeepSeek API 키(DB 오버라이드→env)."""
    value = await get_setting(session, "deepseek_api_key")
    if value:
        return value
    return get_settings().DEEPSEEK_API_KEY


async def get_llm_runtime(session: AsyncSession) -> LlmRuntime:
    """선택된 엔진 + provider별 키 + 사전 프롬프트를 한 번에 묶어 반환한다."""
    settings = get_settings()
    return LlmRuntime(
        model=await get_gemini_engine_version(session),
        gemini_api_key=settings.GEMINI_API_KEY,
        deepseek_api_key=await get_deepseek_api_key(session),
        deepseek_base_url=settings.DEEPSEEK_BASE_URL,
        preprompt=await get_ai_preprompt(session),
    )
