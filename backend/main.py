"""FastAPI 애플리케이션 엔트리포인트.

설정 로더(`app.core.config`)와 API 라우터(`app.api`)를 조립한다. 무거운 ETL
작업은 직접 수행하지 않고, 라우터가 `crawl_runs` 작업만 생성한다.
"""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.core.config import get_settings
from app.core.database import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """애플리케이션 lifespan: 시작 시 DB 테이블을 초기화한다."""
    await init_db()
    yield


def create_app() -> FastAPI:
    """애플리케이션 팩토리."""
    settings = get_settings()

    app = FastAPI(
        title="TripMate Agent API",
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
        return {"message": "Welcome to TripMate Agent API", "status": "running"}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(router)
    return app


app = create_app()


if __name__ == "__main__":
    # 실행 환경은 Linux Docker 전용이다. Compose는 컨테이너 내부에서
    # `uvicorn main:app --host 0.0.0.0 --port 8000`으로 기동하고 host port 12401로
    # 매핑한다. WSL2 등에서 직접 실행할 때는 고정 라이브 포트 12401을 사용한다.
    uvicorn.run("main:app", host="0.0.0.0", port=12401, reload=True)
