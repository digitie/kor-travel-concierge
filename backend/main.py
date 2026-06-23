"""FastAPI 애플리케이션 엔트리포인트.

설정 로더(`ktc.core.config`)와 API 라우터(`ktc.api`)를 조립한다. 무거운 ETL
작업은 직접 수행하지 않고, 라우터가 `crawl_runs` 작업만 생성한다.
"""

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ktc.api import router
from ktc.core.config import get_settings
from ktc.core.database import init_db


def _warn_on_risky_auth_config() -> None:
    """위험한 인증 구성을 기동 시 경고한다(차단하지는 않는다)."""
    settings = get_settings()
    logger = logging.getLogger("ktc.security")
    if settings.api_trusted_client_bypass_active:
        logger.warning(
            "API_TRUSTED_CLIENT_CIDRS 키 없는 우회가 활성화되었다. client IP는 "
            "FORWARDED_ALLOW_IPS=*에서 X-Forwarded-For로 위조될 수 있으니, "
            "FORWARDED_ALLOW_IPS를 실제 프록시 IP로 고정했는지 반드시 확인하라."
        )
    if settings.auth_required and not settings.KTC_ADMIN_PROXY_SECRET.strip():
        logger.warning(
            "auth_required 환경이지만 KTC_ADMIN_PROXY_SECRET이 비어 있어 관리자 API가 "
            "모두 403으로 차단된다(fail-closed). 관리자 기능을 쓰려면 비밀을 설정하라."
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """애플리케이션 lifespan: 인증 구성 경고 후 DB를 준비한다."""
    _warn_on_risky_auth_config()
    await init_db()
    yield


def create_app() -> FastAPI:
    """애플리케이션 팩토리."""
    settings = get_settings()

    app = FastAPI(
        title="kor-travel-concierge API",
        description="FastAPI Backend for YouTube Travel Curation with Gemini",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS: 개발·E2E에서 사용하는 프론트엔드 origin을 허용한다.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    def read_root() -> dict[str, str]:
        return {"message": "Welcome to kor-travel-concierge API", "status": "running"}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(router)
    return app


app = create_app()


if __name__ == "__main__":
    # 실행 환경은 Linux Docker 전용이다. Compose는 컨테이너 내부에서
    # `python -m ktc.cli api --host 0.0.0.0 --port 8000`으로 기동하고 host port 12601로
    # 매핑한다. WSL2 등에서 직접 실행할 때는 고정 라이브 포트 12601을 사용한다.
    uvicorn.run("main:app", host="0.0.0.0", port=12601, reload=True)
