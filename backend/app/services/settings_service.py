"""`system_settings` 키-값 설정 서비스.

DB에 저장된 런타임 설정을 읽고 쓴다. 미저장 키는 `.env` 기반 기본값으로 보강한다.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import SystemSetting


async def get_setting(
    session: AsyncSession, key: str, default: str | None = None
) -> str | None:
    """단일 설정 값을 조회한다."""
    row = await session.get(SystemSetting, key)
    return row.value if row is not None else default


async def set_setting(session: AsyncSession, key: str, value: str) -> SystemSetting:
    """설정 값을 upsert한다."""
    row = await session.get(SystemSetting, key)
    if row is None:
        row = SystemSetting(key=key, value=value)
        session.add(row)
    else:
        row.value = value
    await session.commit()
    await session.refresh(row)
    return row


async def get_all(session: AsyncSession) -> dict[str, str]:
    """DB 설정을 기본값(`.env`) 위에 덮어써 반환한다."""
    settings = get_settings()
    merged: dict[str, str] = {
        "gemini_engine_version": settings.GEMINI_ENGINE_VERSION,
    }
    result = await session.execute(select(SystemSetting))
    for row in result.scalars().all():
        merged[row.key] = row.value
    return merged
