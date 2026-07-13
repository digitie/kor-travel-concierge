"""`audit_logs` 기록 서비스.

웹/MCP/scheduler의 쓰기 작업을 감사 추적한다. payload는 JSON 직렬화해
저장하되, 키 값 등 민감 정보는 호출자가 마스킹 후 전달한다.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ktc.models import AuditLog


async def record(
    session: AsyncSession,
    *,
    actor_type: str,
    action: str,
    target_type: str,
    target_id: str | None = None,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    idempotency_state: str | None = None,
    commit: bool = True,
) -> AuditLog:
    """감사 로그 1건을 기록한다."""
    if (idempotency_key is None) != (idempotency_state is None):
        raise ValueError("audit idempotency key/state는 함께 지정해야 한다")
    if idempotency_key is not None:
        if not 1 <= len(idempotency_key) <= 255:
            raise ValueError("audit idempotency key는 1~255자여야 한다")
        if idempotency_state not in {"pending", "final"}:
            raise ValueError("audit idempotency state는 pending 또는 final이어야 한다")
        if (
            payload is None
            or payload.get("idempotency_key") != idempotency_key
            or payload.get("idempotency_state") != idempotency_state
        ):
            raise ValueError("audit idempotency column과 payload가 일치해야 한다")
    log = AuditLog(
        actor_type=actor_type,
        action=action,
        target_type=target_type,
        target_id=target_id,
        idempotency_key=idempotency_key,
        idempotency_state=idempotency_state,
        payload_json=json.dumps(payload, ensure_ascii=False) if payload else None,
    )
    session.add(log)
    if commit:
        await session.commit()
        await session.refresh(log)
    return log


async def list_recent(session: AsyncSession, *, limit: int = 50) -> list[AuditLog]:
    """최근 감사 로그를 최신순으로 조회한다."""
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def find_by_idempotency_key(
    session: AsyncSession,
    *,
    actor_type: str,
    action: str,
    idempotency_key: str,
) -> AuditLog | None:
    """전용 partial unique index로 actor/action/key 감사 로그를 직접 찾는다."""
    return (
        await session.execute(
            select(AuditLog).where(
                AuditLog.actor_type == actor_type,
                AuditLog.action == action,
                AuditLog.idempotency_key == idempotency_key,
            ).execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
