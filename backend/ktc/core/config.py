"""애플리케이션 설정 로더.

`.env.example`에 정의된 모든 환경 변수를 단일 `Settings` 객체로 모아서
백엔드 API, ETL, MCP, scheduler가 동일한 이름으로 참조하도록 한다.
(`docs/tasks.md` T-003: `.env.example`과 실제 실행 코드의 환경 변수 이름 동기화)

API 키 등 민감 값은 절대 로그에 평문으로 남기지 않는다. `masked()` 헬퍼로
마스킹한 뒤에만 출력한다.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

GEMINI_ENGINE_VERSION_DEFAULT = "gemini-2.0-flash"
GEMINI_ENGINE_OPTIONS: tuple[str, ...] = (
    GEMINI_ENGINE_VERSION_DEFAULT,
    "gemini-2.5-flash",
    "gemini-flash-latest",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
)


class Settings(BaseSettings):
    """`.env` 주입 기반 전역 설정.

    필드 이름은 `.env.example`의 변수 이름과 1:1로 일치시킨다. 새 환경 변수를
    추가할 때는 반드시 `.env.example`과 이 클래스를 함께 갱신한다.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- 1. 프론트엔드 (참조용, 백엔드에서는 사용하지 않음) ---
    NEXT_PUBLIC_VWORLD_SERVICE_KEY: str = ""
    NEXT_PUBLIC_API_BASE_URL: str = "http://localhost:12601"
    CORS_ALLOW_ORIGINS: str = (
        "http://localhost:12605,http://127.0.0.1:12605,"
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:13100,http://127.0.0.1:13100"
    )

    # --- 1.5. 실행 환경 및 API 인증 ---
    # APP_ENV이 local(또는 test/e2e)일 때는 외부 호출용 인증 코드 없이 동작한다.
    # 외부에 노출되는 비-local 배포에서는 API 키(X-API-Key 헤더)를 요구한다.
    APP_ENV: str = "local"
    # 명시적으로 인증을 강제하고 싶을 때 true로 둔다(로컬에서 인증 동작 검증 등).
    API_AUTH_ENABLED: bool = False
    # 허용 API 키 목록(쉼표 구분). 외부 노출 배포에서 반드시 설정한다.
    API_KEYS: str = ""

    # --- 2. 데이터베이스 (PostgreSQL + PostGIS, ADR-25) ---
    DATABASE_URL: str = "postgresql+asyncpg://addr:addr@localhost:5432/kor_travel_concierge"
    KTC_TEST_PG_DSN: str = ""

    # --- LLM: Gemini ---
    GEMINI_API_KEY: str = ""
    GEMINI_ENGINE_VERSION: str = GEMINI_ENGINE_VERSION_DEFAULT

    # --- YouTube Data API v3 ---
    YOUTUBE_API_KEY: str = ""
    YOUTUBE_USE_OFFICIAL_API: bool = True
    YOUTUBE_SEARCH_DAILY_BUDGET_UNITS: int = 1000
    YOUTUBE_MAX_VIDEOS_PER_RUN: int = 20

    # --- 자막/전사 폴백 순서 ---
    TRANSCRIPT_PROVIDER_ORDER: str = "youtube-transcript-api,yt-dlp,faster-whisper"
    # 실행 환경은 Linux Docker 전용이며 FFmpeg은 컨테이너 이미지가 apt로 제공한다.
    FFMPEG_PATH: str = "/usr/bin/ffmpeg"

    # --- RustFS 미디어 저장소 ---
    RUSTFS_ENABLED: bool = True
    RUSTFS_ENDPOINT: str = "http://127.0.0.1:12101"
    RUSTFS_PUBLIC_BASE_URL: str = "http://127.0.0.1:12101/kor-travel-concierge"
    RUSTFS_DOCKER_ENDPOINT: str = "http://host.docker.internal:12101"
    RUSTFS_CONSOLE_URL: str = "http://127.0.0.1:12105"
    RUSTFS_ACCESS_KEY: str = ""
    RUSTFS_SECRET_KEY: str = ""
    RUSTFS_BUCKET_RAW_VIDEOS: str = "kor-travel-concierge"
    RUSTFS_BUCKET_SUBTITLES: str = "kor-travel-concierge"
    RUSTFS_BUCKET_FRAMES: str = "kor-travel-concierge"
    RUSTFS_OBJECT_PREFIX: str = "features"
    RUSTFS_REGION: str = "us-east-1"
    RUSTFS_HEALTH_PATH: str = "/health/live"
    MEDIA_RETENTION_POLICY: str = "infinite"

    # --- Geocoding / Reverse Geocoding ---
    GEOLOCATION_PROVIDER: str = "vworld"
    KAKAO_REST_API_KEY: str = ""
    NAVER_CLIENT_ID: str = ""
    NAVER_CLIENT_SECRET: str = ""
    VWORLD_SERVICE_KEY: str = ""

    # --- 3. MCP 서버 ---
    MCP_WRITE_ENABLED: bool = False
    MCP_TRANSPORT: str = "stdio"
    MCP_HOST: str = "127.0.0.1"
    MCP_PORT: int = 12402
    MCP_STREAMABLE_HTTP_PATH: str = "/mcp"

    # --- 4. 스케줄러 및 동시성 ---
    SCHEDULER_ENABLED: bool = True
    CRAWL_DEFAULT_INTERVAL_DAYS: int = 7
    CRAWL_MAX_CONCURRENT_VIDEOS: int = 4
    HTTP_MAX_CONCURRENT_REQUESTS: int = 8
    SCHEDULER_POLL_INTERVAL_SECONDS: int = 5
    SCHEDULER_HEARTBEAT_INTERVAL_SECONDS: int = 30
    SCHEDULER_STALE_THRESHOLD_SECONDS: int = 300
    SCHEDULER_MAX_RETRIES: int = 3
    SCHEDULER_JOBSTORE_ENABLED: bool = True
    SCHEDULER_JOBSTORE_URL: str = ""
    SCHEDULER_JOBSTORE_TABLE: str = "apscheduler_jobs"
    SOURCE_SCAN_ENABLED: bool = True
    SOURCE_SCAN_INTERVAL_SECONDS: int = 300
    SOURCE_SCAN_BATCH_SIZE: int = 20
    SOURCE_SCAN_DEFAULT_INTERVAL_MINUTES: int = 10_080
    SOURCE_SCAN_DUPLICATE_BACKOFF_MINUTES: int = 15

    @property
    def api_keys(self) -> list[str]:
        """`API_KEYS`를 허용 키 목록으로 파싱한다."""
        return [key.strip() for key in self.API_KEYS.split(",") if key.strip()]

    @property
    def is_local_env(self) -> bool:
        """local/test/e2e 실행 환경 여부."""
        return self.APP_ENV.strip().lower() in {"local", "test", "e2e"}

    @property
    def auth_required(self) -> bool:
        """API 인증(인증 코드) 요구 여부.

        로컬 실행(`APP_ENV=local` 등)에서는 인증 없이 동작하고, 외부에 노출되는
        비-local 환경에서는 인증 코드를 요구한다. `API_AUTH_ENABLED=true`이면
        환경과 무관하게 인증을 강제한다.
        """
        if self.API_AUTH_ENABLED:
            return True
        return not self.is_local_env

    @property
    def transcript_provider_order(self) -> list[str]:
        """`TRANSCRIPT_PROVIDER_ORDER`를 폴백 순서 리스트로 파싱한다."""
        return [p.strip() for p in self.TRANSCRIPT_PROVIDER_ORDER.split(",") if p.strip()]

    @property
    def rustfs_buckets(self) -> dict[str, str]:
        """asset 종류별 RustFS 버킷 매핑."""
        return {
            "raw_video": self.RUSTFS_BUCKET_RAW_VIDEOS,
            "subtitle": self.RUSTFS_BUCKET_SUBTITLES,
            "transcript": self.RUSTFS_BUCKET_SUBTITLES,
            "frame": self.RUSTFS_BUCKET_FRAMES,
        }

    @property
    def cors_allow_origins(self) -> list[str]:
        """쉼표 구분 CORS origin 목록."""
        origins = [
            origin.strip()
            for origin in self.CORS_ALLOW_ORIGINS.split(",")
            if origin.strip()
        ]
        if self.NEXT_PUBLIC_API_BASE_URL.startswith("http"):
            origins.append(self.NEXT_PUBLIC_API_BASE_URL.rstrip("/"))
        return sorted(set(origins))


@lru_cache
def get_settings() -> Settings:
    """프로세스 전역 단일 설정 인스턴스를 반환한다."""
    return Settings()
