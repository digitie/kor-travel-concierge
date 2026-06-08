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
    NEXT_PUBLIC_API_BASE_URL: str = "http://localhost:9041"
    CORS_ALLOW_ORIGINS: str = (
        "http://localhost:9042,http://127.0.0.1:9042,"
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:13000,http://127.0.0.1:13000,"
        "http://localhost:13100,http://127.0.0.1:13100"
    )

    # --- 2. 데이터베이스 (SQLite + SpatiaLite) ---
    DATABASE_URL: str = "sqlite+aiosqlite:///./tripmate.db"
    SPATIALITE_EXTENSION_PATH: str = "mod_spatialite"
    SQLITE_WAL_ENABLED: bool = True

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
    FFMPEG_PATH: str = "ffmpeg"
    FFPROBE_PATH: str = "ffprobe"

    # --- RustFS 미디어 저장소 ---
    RUSTFS_ENABLED: bool = True
    RUSTFS_ENDPOINT: str = "http://127.0.0.1:9003"
    RUSTFS_PUBLIC_BASE_URL: str = "http://127.0.0.1:9003/krtour-map"
    RUSTFS_DOCKER_ENDPOINT: str = "http://rustfs:9000"
    RUSTFS_CONSOLE_URL: str = "http://127.0.0.1:9004"
    RUSTFS_ACCESS_KEY: str = ""
    RUSTFS_SECRET_KEY: str = ""
    RUSTFS_BUCKET_RAW_VIDEOS: str = "krtour-map"
    RUSTFS_BUCKET_SUBTITLES: str = "krtour-map"
    RUSTFS_BUCKET_FRAMES: str = "krtour-map"
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
    MCP_PORT: int = 8010
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
