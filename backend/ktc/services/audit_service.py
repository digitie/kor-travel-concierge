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
    commit: bool = True,
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
    limit: int = 200,
) -> AuditLog | None:
    """멱등 키가 같은 최근 감사 로그를 찾는다.

    `audit_logs.payload_json`은 SQLite 호환성을 위해 Text로 저장한다. JSON 함수
    의존을 피하고 최근 동일 action 로그만 좁혀 파싱한다.
    """
    stmt = (
        select(AuditLog)
        .where(AuditLog.actor_type == actor_type, AuditLog.action == action)
        .order_by(AuditLog.id.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    for log in result.scalars().all():
        if not log.payload_json:
            continue
        try:
            payload = json.loads(log.payload_json)
        except json.JSONDecodeError:
            continue
        if payload.get("idempotency_key") == idempotency_key:
            return log
    return None
