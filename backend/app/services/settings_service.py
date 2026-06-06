"""`system_settings` 키-값 설정 서비스.

DB에 저장된 런타임 설정을 읽고 쓴다. 미저장 키는 `.env` 기반 기본값으로 보강한다.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import SystemSetting

ALLOWED_SETTING_KEYS = frozenset({"gemini_engine_version"})


def validate_setting_key(key: str) -> None:
    """런타임에서 수정 가능한 설정 키인지 검증한다."""
    if key not in ALLOWED_SETTING_KEYS:
        raise ValueError(f"지원하지 않는 설정 키: {key}")


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
    validate_setting_key(key)
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
    for key in values:
        validate_setting_key(key)
    rows: list[SystemSetting] = []
    for key, value in values.items():
        rows.append(await set_setting(session, key, value, commit=False))
    await session.commit()
    for row in rows:
        await session.refresh(row)
    return {row.key: row.value for row in rows}


async def get_all(session: AsyncSession) -> dict[str, str]:
    """DB 설정을 기본값(`.env`) 위에 덮어써 반환한다."""
    settings = get_settings()
    merged: dict[str, str] = {
        "gemini_engine_version": settings.GEMINI_ENGINE_VERSION,
    }
    result = await session.execute(select(SystemSetting))
    for row in result.scalars().all():
        if row.key in ALLOWED_SETTING_KEYS:
            merged[row.key] = row.value
    return merged
