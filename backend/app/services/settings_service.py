"""`system_settings` 키-값 설정 서비스.

DB에 저장된 런타임 설정을 읽고 쓴다. 미저장 키는 `.env` 기반 기본값으로 보강한다.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import (
    GEMINI_ENGINE_OPTIONS,
    GEMINI_ENGINE_VERSION_DEFAULT,
    get_settings,
)
from app.models import SystemSetting

ALLOWED_SETTING_KEYS = frozenset({"gemini_engine_version"})


def validate_setting_key(key: str) -> None:
    """런타임에서 수정 가능한 설정 키인지 검증한다."""
    if key not in ALLOWED_SETTING_KEYS:
        raise ValueError(f"지원하지 않는 설정 키: {key}")


def validate_setting_value(key: str, value: str) -> None:
    """설정 키와 값을 함께 검증한다."""
    validate_setting_key(key)
    if key == "gemini_engine_version" and value not in GEMINI_ENGINE_OPTIONS:
        allowed = ", ".join(GEMINI_ENGINE_OPTIONS)
        raise ValueError(f"지원하지 않는 Gemini 엔진 버전: {value} (허용: {allowed})")


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


async def get_all(session: AsyncSession) -> dict[str, Any]:
    """DB 설정을 기본값(`.env`) 위에 덮어써 반환한다."""
    settings = get_settings()
    engine_version = _valid_gemini_engine_or_default(settings.GEMINI_ENGINE_VERSION)
    merged: dict[str, Any] = {
        "gemini_engine_version": engine_version,
        "gemini_engine_default": GEMINI_ENGINE_VERSION_DEFAULT,
        "gemini_engine_options": list(GEMINI_ENGINE_OPTIONS),
    }
    result = await session.execute(select(SystemSetting))
    for row in result.scalars().all():
        if row.key in ALLOWED_SETTING_KEYS:
            try:
                validate_setting_value(row.key, row.value)
            except ValueError:
                continue
            merged[row.key] = row.value
    return merged


async def get_gemini_engine_version(session: AsyncSession) -> str:
    """실제 Gemini 호출에 사용할 런타임 모델명을 반환한다."""
    settings = await get_all(session)
    return settings["gemini_engine_version"]


def _valid_gemini_engine_or_default(value: str) -> str:
    if value in GEMINI_ENGINE_OPTIONS:
        return value
    return GEMINI_ENGINE_VERSION_DEFAULT
