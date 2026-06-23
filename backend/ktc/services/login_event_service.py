"""관리자 인증 이벤트 기록/조회 서비스."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ktc.models import LoginEvent


async def record(
    session: AsyncSession,
    *,
    event_type: str,
    outcome: str,
    attempted_username: str | None,
    reason: str | None,
    client_ip: str | None,
    user_agent: str | None,
    next_path: str | None,
    commit: bool = True,
) -> LoginEvent:
    row = LoginEvent(
        event_type=event_type,
        outcome=outcome,
        attempted_username=attempted_username,
        reason=reason,
        client_ip=client_ip,
        user_agent=user_agent,
        next_path=next_path,
    )
    session.add(row)
    if commit:
        await session.commit()
        await session.refresh(row)
    return row


async def list_recent(session: AsyncSession, *, limit: int = 50) -> list[LoginEvent]:
    stmt = select(LoginEvent).order_by(LoginEvent.id.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())
