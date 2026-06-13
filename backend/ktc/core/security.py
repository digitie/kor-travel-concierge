"""API 인증(인증 코드) 의존성.

외부 호출을 고려해 REST API를 `X-API-Key` 헤더 기반으로 보호한다. 단,
로컬 실행(`APP_ENV=local` 등)에서는 인증 코드 없이 동작하도록 우회한다
(`Settings.auth_required` 참조).

인증 정책은 설정에만 의존하므로, 라우터에 `Depends(require_api_key)`를 걸면
버전이 다른 라우터에도 동일하게 재사용할 수 있다.
"""

from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from ktc.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

API_KEY_HEADER_NAME = "X-API-Key"

# auto_error=False: 키가 없어도 여기서 막지 않고, 로컬 우회 여부를 직접 판단한다.
api_key_header = APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False)


async def require_api_key(
    api_key: str | None = Security(api_key_header),
    settings: Settings = Depends(get_settings),
) -> None:
    """비-local 환경에서 유효한 `X-API-Key`를 요구한다.

    로컬 실행에서는 인증 코드가 없어도 통과한다. 인증이 필요한데 허용 키가
    하나도 설정되어 있지 않으면 모든 요청을 거부(잠금)해 안전 측 실패를 택한다.
    """
    if not settings.auth_required:
        return

    if not settings.api_keys:
        logger.warning(
            "API 인증이 필요한 환경(APP_ENV=%s)이지만 API_KEYS가 비어 있어 모든 요청을 거부한다.",
            settings.APP_ENV,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API 인증 코드가 설정되지 않았다.",
            headers={"WWW-Authenticate": API_KEY_HEADER_NAME},
        )

    if api_key and api_key in settings.api_keys:
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="유효한 API 인증 코드가 필요하다.",
        headers={"WWW-Authenticate": API_KEY_HEADER_NAME},
    )
