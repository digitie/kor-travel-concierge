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
import re

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
ADMIN_PROXY_ONLY_PATH = "/api/v1/admin"

# 공개 소비자용 read 키는 현재 공급 계약에 속하는 경로만 통과한다. 새 GET 라우트는
# 여기에 명시적으로 추가하기 전까지 admin으로 남는다(deny-by-default).
READ_SCOPE_EXACT_PATHS = frozenset(
    {
        "/api/v1/destinations",
        "/api/v1/destinations/facets",
        "/api/v1/destinations/export",
        "/api/v1/features/snapshot",
        "/api/v1/features/changes",
        "/api/v1/themes",
        "/api/v1/themes/places",
        "/api/v1/categories",
        "/api/v1/categories/match",
    }
)
READ_SCOPE_PATH_PATTERNS = (
    re.compile(r"^/api/v1/destinations/\d+/detail$"),
    re.compile(r"^/api/v1/themes/video/[^/]+/places$"),
)

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

    기존 `X-API-Key` 정적 키는 admin, DB 공개 키는 저장된 scope로 판정한다.
    VWorld식 `?key=`는 DB read 키만 허용한다. 인증된 Next.js 관리자 proxy는
    admin, 명시적으로 신뢰한 클라이언트 CIDR의 무키 우회는 read로 취급한다.
    """
    if not settings.auth_required:
        return

    if resolve_admin_proxy_actor(request, settings) is not None:
        request.state.api_scope = "admin"
        return

    if _is_admin_proxy_only_path(request.url.path):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 proxy 인증이 필요하다.",
        )

    # 명시적이고 비어 있지 않은 header가 query key보다 우선한다. 잘못된 header를
    # 유효한 query key로 우회하지 않으며, 빈 header는 credential로 취급하지 않는다.
    header_key = (api_key or "").strip() or None
    query_key = (key or "").strip() or None
    if header_key is not None:
        provided_key = header_key
        credential_source = "header"
    elif query_key is not None:
        provided_key = query_key
        credential_source = "query"
    else:
        provided_key = None
        credential_source = None
    if provided_key is None:
        # 키 없는 CIDR 우회는 read로만 취급한다. admin이 필요하면 header key를 써야
        # 하며, client IP는 FORWARDED_ALLOW_IPS 설정에 따라 위조될 수 있어 기본 off다.
        if settings.api_trusted_client_bypass_active and _peer_in_cidrs(
            request, settings.api_trusted_client_cidrs
        ):
            _authorize_scope(request, "read")
            return

    active_scopes = await public_api_key_service.cached_active_key_scopes(
        session,
        ttl_seconds=settings.PUBLIC_API_KEY_CACHE_TTL_SECONDS,
    )
    has_any_key = bool(settings.api_keys or active_scopes)
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

    if credential_source == "header" and provided_key is not None and any(
        hmac.compare_digest(provided_key, static_key)
        for static_key in settings.api_keys
    ):
        _authorize_scope(request, "admin")
        return

    if credential_source == "query" and provided_key is not None and any(
        hmac.compare_digest(provided_key, static_key)
        for static_key in settings.api_keys
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="query key에는 read scope만 사용할 수 있다.",
        )

    db_scope = (
        public_api_key_service.public_api_key_scope(provided_key, active_scopes)
        if provided_key
        else None
    )
    if db_scope is not None:
        if credential_source == "query" and db_scope != "read":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="query key에는 read scope만 사용할 수 있다.",
            )
        _authorize_scope(request, db_scope)
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="유효한 API 인증 코드가 필요하다.",
        headers={"WWW-Authenticate": API_KEY_HEADER_NAME},
    )


def is_read_scope_path(method: str, path: str) -> bool:
    """요청이 명시적으로 공개한 read 공급 표면인지 판정한다."""
    if method.upper() not in {"GET", "HEAD"}:
        return False
    if path in READ_SCOPE_EXACT_PATHS:
        return True
    return any(pattern.fullmatch(path) for pattern in READ_SCOPE_PATH_PATTERNS)


def _authorize_scope(
    request: Request,
    scope: public_api_key_service.PublicApiKeyScope,
) -> None:
    request.state.api_scope = scope
    if scope == "read" and not is_read_scope_path(request.method, request.url.path):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="이 API에는 admin scope가 필요하다.",
        )


def _is_admin_proxy_only_path(path: str) -> bool:
    return path == ADMIN_PROXY_ONLY_PATH or path.startswith(f"{ADMIN_PROXY_ONLY_PATH}/")


def resolve_admin_proxy_actor(request: Request, settings: Settings) -> str | None:
    """신뢰 proxy에서 주입한 관리자 actor를 검증해 반환한다.

    주의: CIDR(peer IP) 검사는 방어심층(defense-in-depth)일 뿐이다. 운영에서
    FORWARDED_ALLOW_IPS=*이면 `request.client.host`가 X-Forwarded-For로 위조될 수
    있으므로, 관리자 권한의 실질 게이트는 상수시간 비교하는 공유 비밀
    `KTC_ADMIN_PROXY_SECRET`이다(아래). FORWARDED_ALLOW_IPS는 실제 프록시 IP로
    고정하는 것을 권장한다.
    """
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
