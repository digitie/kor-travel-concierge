"""외부 공개 API 키 생성·검증 서비스."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import string
from dataclasses import dataclass
from time import monotonic
from types import MappingProxyType
from typing import Literal, Mapping, TypeAlias

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ktc.models import PublicApiKey, utcnow

PUBLIC_API_KEY_QUERY_PARAM = "key"
PUBLIC_API_KEY_LENGTH = 32
PUBLIC_API_KEY_ALPHABET = string.ascii_letters + string.digits
PublicApiKeyScope: TypeAlias = Literal["read", "admin"]
PUBLIC_API_KEY_SCOPES: tuple[PublicApiKeyScope, ...] = ("read", "admin")


@dataclass(frozen=True, slots=True)
class _ActiveKeyScopeCacheEntry:
    scopes_by_hash: Mapping[str, PublicApiKeyScope]
    expires_at: float


_active_key_cache: _ActiveKeyScopeCacheEntry | None = None
_active_key_cache_lock = asyncio.Lock()
_active_key_cache_generation = 0


def generate_public_api_key() -> str:
    """VWorld와 같은 wire shape의 32자 영문/숫자 key 값을 생성한다."""
    return "".join(
        secrets.choice(PUBLIC_API_KEY_ALPHABET) for _ in range(PUBLIC_API_KEY_LENGTH)
    )


def hash_public_api_key(api_key: str) -> str:
    # 키는 32자 CSPRNG 토큰(~190비트)이라 brute-force가 불가능하므로, 활성 해시 집합에 대한
    # O(1) 멤버십 검사를 위해 의도적으로 빠른 무염 SHA-256을 사용한다(저엔트로피 패스워드용
    # 느린 KDF는 불필요). 평문 키는 저장·로깅하지 않는다.
    return hashlib.sha256(api_key.strip().encode("utf-8")).hexdigest()


def public_api_key_scope(
    api_key: str,
    scopes_by_hash: Mapping[str, PublicApiKeyScope],
) -> PublicApiKeyScope | None:
    """평문을 저장하지 않고 API 키의 활성 scope를 찾는다."""
    key_hash = hash_public_api_key(api_key)
    # 키 자체가 아니라 고정 길이 SHA-256 digest를 dictionary key로 조회한다. cache를
    # 집합이 아닌 mapping으로 둔 목적대로 hot path를 O(1)로 유지한다.
    return scopes_by_hash.get(key_hash)


async def active_key_scopes(
    session: AsyncSession,
) -> Mapping[str, PublicApiKeyScope]:
    result = await session.execute(
        select(PublicApiKey.key_hash, PublicApiKey.scope).where(
            PublicApiKey.state == "active"
        )
    )
    return MappingProxyType(
        {
            str(key_hash): scope
            for key_hash, scope in result.all()
            if scope in PUBLIC_API_KEY_SCOPES
        }
    )


async def cached_active_key_scopes(
    session: AsyncSession, *, ttl_seconds: int
) -> Mapping[str, PublicApiKeyScope]:
    """공개 API hot path용 `key_hash → scope` 프로세스 로컬 캐시."""
    global _active_key_cache

    now = monotonic()
    if _active_key_cache is not None and _active_key_cache.expires_at > now:
        return _active_key_cache.scopes_by_hash

    async with _active_key_cache_lock:
        while True:
            now = monotonic()
            if _active_key_cache is not None and _active_key_cache.expires_at > now:
                return _active_key_cache.scopes_by_hash
            generation = _active_key_cache_generation
            scopes_by_hash = await active_key_scopes(session)
            # SELECT와 publish 사이에 create/revoke가 commit+invalidate되면 방금 읽은
            # snapshot은 stale일 수 있다. generation이 바뀌었으면 새 transaction
            # visibility로 다시 읽고, 무효화 뒤 stale cache를 재게시하지 않는다.
            if generation != _active_key_cache_generation:
                continue
            _active_key_cache = _ActiveKeyScopeCacheEntry(
                scopes_by_hash=scopes_by_hash,
                expires_at=monotonic() + max(ttl_seconds, 0),
            )
            return scopes_by_hash


def invalidate_public_api_key_cache() -> None:
    global _active_key_cache, _active_key_cache_generation
    _active_key_cache_generation += 1
    _active_key_cache = None


async def list_keys(session: AsyncSession, *, limit: int = 100) -> list[PublicApiKey]:
    stmt = select(PublicApiKey).order_by(PublicApiKey.id.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_key(
    session: AsyncSession,
    *,
    label: str | None,
    created_by: str | None,
    scope: PublicApiKeyScope = "read",
    commit: bool = True,
) -> tuple[str, PublicApiKey]:
    """scope가 고정된 키를 발급한다. scope 변경은 폐기 후 재발급한다."""
    if scope not in PUBLIC_API_KEY_SCOPES:
        raise ValueError("public API key scope must be 'read' or 'admin'")
    normalized_label = label.strip() if label else None
    api_key = generate_public_api_key()
    row = PublicApiKey(
        label=normalized_label or None,
        key_hash=hash_public_api_key(api_key),
        key_hint=api_key[-6:],
        scope=scope,
        state="active",
        created_by=created_by,
    )
    session.add(row)
    if commit:
        await session.commit()
    else:
        await session.flush()
    await session.refresh(row)
    if commit:
        invalidate_public_api_key_cache()
    return api_key, row


async def revoke_key(
    session: AsyncSession,
    key_id: int,
    *,
    revoked_by: str | None,
    commit: bool = True,
) -> PublicApiKey | None:
    row = await session.get(PublicApiKey, key_id)
    if row is None or row.state != "active":
        return None
    row.state = "revoked"
    row.revoked_at = utcnow()
    row.revoked_by = revoked_by
    if commit:
        await session.commit()
    else:
        await session.flush()
    await session.refresh(row)
    if commit:
        invalidate_public_api_key_cache()
    return row
