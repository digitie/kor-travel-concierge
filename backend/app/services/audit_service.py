"""`audit_logs` 기록 서비스.

웹/MCP/scheduler의 쓰기 작업을 감사 추적한다. payload는 JSON 직렬화해
저장하되, 키 값 등 민감 정보는 호출자가 마스킹 후 전달한다.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def record(
    session: AsyncSession,
    *,
    actor_type: str,
    action: str,
    target_type: str,
    target_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditLog:
    """감사 로그 1건을 기록한다."""
    log = AuditLog(
        actor_type=actor_type,
        action=action,
        target_type=target_type,
        target_id=target_id,
        payload_json=json.dumps(payload, ensure_ascii=False) if payload else None,
    )
    session.add(log)
    await session.commit()
    await session.refresh(log)
    return log


async def list_recent(session: AsyncSession, *, limit: int = 50) -> list[AuditLog]:
    """최근 감사 로그를 최신순으로 조회한다."""
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())
