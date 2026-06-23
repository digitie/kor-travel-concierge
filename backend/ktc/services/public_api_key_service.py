"""외부 공개 API 키 생성·검증 서비스."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import string
from dataclasses import dataclass
from time import monotonic

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ktc.models import PublicApiKey, utcnow

PUBLIC_API_KEY_QUERY_PARAM = "key"
PUBLIC_API_KEY_LENGTH = 32
PUBLIC_API_KEY_ALPHABET = string.ascii_letters + string.digits


@dataclass(frozen=True, slots=True)
class _ActiveKeyCacheEntry:
    hashes: frozenset[str]
    expires_at: float


_active_key_cache: _ActiveKeyCacheEntry | None = None
_active_key_cache_lock = asyncio.Lock()


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


def public_api_key_matches(api_key: str, key_hashes: frozenset[str]) -> bool:
    key_hash = hash_public_api_key(api_key)
    return any(hmac.compare_digest(key_hash, stored_hash) for stored_hash in key_hashes)


async def active_key_hashes(session: AsyncSession) -> frozenset[str]:
    result = await session.execute(
        select(PublicApiKey.key_hash).where(PublicApiKey.state == "active")
    )
    return frozenset(str(row) for row in result.scalars().all())


async def cached_active_key_hashes(
    session: AsyncSession, *, ttl_seconds: int
) -> frozenset[str]:
    """공개 API hot path에서 DB 조회를 줄이기 위한 프로세스 로컬 캐시."""
    global _active_key_cache

    now = monotonic()
    if _active_key_cache is not None and _active_key_cache.expires_at > now:
        return _active_key_cache.hashes

    async with _active_key_cache_lock:
        now = monotonic()
        if _active_key_cache is not None and _active_key_cache.expires_at > now:
            return _active_key_cache.hashes
        hashes = await active_key_hashes(session)
        _active_key_cache = _ActiveKeyCacheEntry(
            hashes=hashes,
            expires_at=now + max(ttl_seconds, 0),
        )
        return hashes


def invalidate_public_api_key_cache() -> None:
    global _active_key_cache
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
) -> tuple[str, PublicApiKey]:
    normalized_label = label.strip() if label else None
    api_key = generate_public_api_key()
    row = PublicApiKey(
        label=normalized_label or None,
        key_hash=hash_public_api_key(api_key),
        key_hint=api_key[-6:],
        state="active",
        created_by=created_by,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    invalidate_public_api_key_cache()
    return api_key, row


async def revoke_key(
    session: AsyncSession,
    key_id: int,
    *,
    revoked_by: str | None,
) -> PublicApiKey | None:
    row = await session.get(PublicApiKey, key_id)
    if row is None or row.state != "active":
        return None
    row.state = "revoked"
    row.revoked_at = utcnow()
    row.revoked_by = revoked_by
    await session.commit()
    await session.refresh(row)
    invalidate_public_api_key_cache()
    return row
