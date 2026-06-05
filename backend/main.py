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

    # CORS: 개발 단계에서는 프론트엔드 베이스 URL을 허용한다.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.NEXT_PUBLIC_API_BASE_URL, "http://localhost:3000"],
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
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
