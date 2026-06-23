"""API 인증(인증 코드) 의존성.

외부 호출을 고려해 REST API를 `X-API-Key` 헤더 기반으로 보호한다. 단,
로컬 실행(`APP_ENV=local` 등)에서는 인증 코드 없이 동작하도록 우회한다
(`Settings.auth_required` 참조).

인증 정책은 설정에만 의존하므로, 라우터에 `Depends(require_api_key)`를 걸면
버전이 다른 라우터에도 동일하게 재사용할 수 있다.
"""

from __future__ import annotations

import hmac
import ipaddress
import logging

from fastapi import Depends, HTTPException, Query, Request, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from ktc.core.config import Settings, get_settings
from ktc.core.database import get_session
from ktc.services import public_api_key_service

logger = logging.getLogger(__name__)

API_KEY_HEADER_NAME = "X-API-Key"
ADMIN_ACTOR_HEADER_NAME = "X-KTC-Actor"
ADMIN_PROXY_SECRET_HEADER_NAME = "X-KTC-Admin-Proxy-Secret"

# auto_error=False: 키가 없어도 여기서 막지 않고, 로컬 우회 여부를 직접 판단한다.
api_key_header = APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False)


async def require_api_key(
    request: Request,
    key: str | None = Query(default=None, alias=public_api_key_service.PUBLIC_API_KEY_QUERY_PARAM),
    api_key: str | None = Security(api_key_header),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> None:
    """비-local 환경에서 유효한 API 키를 요구한다.

    기존 `X-API-Key` 정적 키와 Web UI에서 발급한 VWorld식 `?key=` 공개 키를
    모두 허용한다. 인증된 Next.js 관리자 proxy와 명시적으로 신뢰한 클라이언트
    CIDR은 키 검증을 생략할 수 있다.
    """
    if not settings.auth_required:
        return

    if resolve_admin_proxy_actor(request, settings) is not None:
        return

    if request.url.path.startswith("/api/v1/admin/"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 proxy 인증이 필요하다.",
        )

    if _peer_in_cidrs(request, settings.api_trusted_client_cidrs):
        return

    provided_key = key or api_key
    active_hashes = await public_api_key_service.cached_active_key_hashes(
        session,
        ttl_seconds=settings.PUBLIC_API_KEY_CACHE_TTL_SECONDS,
    )
    has_any_key = bool(settings.api_keys or active_hashes)
    if not has_any_key:
        logger.warning(
            "API 인증이 필요한 환경(APP_ENV=%s)이지만 API_KEYS와 공개 API 키가 비어 있어 모든 요청을 거부한다.",
            settings.APP_ENV,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API 인증 코드가 설정되지 않았다.",
            headers={"WWW-Authenticate": API_KEY_HEADER_NAME},
        )

    if provided_key and provided_key in settings.api_keys:
        return

    if provided_key and public_api_key_service.public_api_key_matches(
        provided_key,
        active_hashes,
    ):
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="유효한 API 인증 코드가 필요하다.",
        headers={"WWW-Authenticate": API_KEY_HEADER_NAME},
    )


def resolve_admin_proxy_actor(request: Request, settings: Settings) -> str | None:
    """신뢰 proxy에서 주입한 관리자 actor를 검증해 반환한다."""
    if not _peer_in_cidrs(request, settings.admin_trusted_proxy_cidrs):
        return None
    expected_secret = settings.KTC_ADMIN_PROXY_SECRET.strip()
    if not expected_secret:
        return None
    actual_secret = (request.headers.get(ADMIN_PROXY_SECRET_HEADER_NAME) or "").strip()
    if not actual_secret or not hmac.compare_digest(actual_secret, expected_secret):
        return None
    actor = (request.headers.get(ADMIN_ACTOR_HEADER_NAME) or "").strip()
    return actor or None


async def require_admin_proxy(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> str:
    """관리자 API가 Next.js BFF에서 온 요청인지 검증한다."""
    actor = resolve_admin_proxy_actor(request, settings)
    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 proxy 인증이 필요하다.",
        )
    return actor


def _peer_in_cidrs(request: Request, cidrs: list[str]) -> bool:
    if not cidrs or request.client is None:
        return False
    try:
        peer_ip = ipaddress.ip_address(request.client.host)
    except ValueError:
        return False
    for raw in cidrs:
        try:
            if peer_ip in ipaddress.ip_network(raw, strict=False):
                return True
        except ValueError:
            logger.warning("잘못된 CIDR 설정을 무시한다: %s", raw)
    return False
