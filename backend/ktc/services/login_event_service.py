"""관리자 인증 이벤트 기록/조회 서비스."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ktc.core.config import get_settings
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
        await _prune_login_events(session)
    return row


async def _prune_login_events(session: AsyncSession) -> None:
    """감사 로그가 무한 증식하지 않도록 보존 상한 초과분(오래된 행)을 정리한다.

    로그아웃·오설정 로그인 등 미인증 경로도 감사 행을 남길 수 있어, 상한이 없으면
    테이블이 무제한으로 커질 수 있다. `LOGIN_AUDIT_MAX_ROWS`로 조정한다(<=0이면 비활성).
    """
    max_rows = get_settings().LOGIN_AUDIT_MAX_ROWS
    if max_rows <= 0:
        return
    threshold = await session.execute(
        select(LoginEvent.id)
        .order_by(LoginEvent.id.desc())
        .offset(max_rows - 1)
        .limit(1)
    )
    threshold_id = threshold.scalars().first()
    if threshold_id is None:
        return
    await session.execute(delete(LoginEvent).where(LoginEvent.id < threshold_id))
    await session.commit()


async def list_recent(session: AsyncSession, *, limit: int = 50) -> list[LoginEvent]:
    stmt = select(LoginEvent).order_by(LoginEvent.id.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())
