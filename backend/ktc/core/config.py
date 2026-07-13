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

GEMINI_ENGINE_VERSION_DEFAULT = "gemini-2.5-flash"
GEMINI_ENGINE_OPTIONS: tuple[str, ...] = (
    GEMINI_ENGINE_VERSION_DEFAULT,
    "gemini-2.0-flash",
    "gemini-flash-latest",
    # gemini-1.5-flash / gemini-1.5-pro는 Google이 API에서 은퇴시켜 404가 나므로 제외(T-115).
)

# DeepSeek V4 (OpenAI 호환, base_url=https://api.deepseek.com). 두 모델 모두 1M context,
# JSON 출력·tool call 지원. api-docs.deepseek.com 기준.
DEEPSEEK_ENGINE_OPTIONS: tuple[str, ...] = (
    "deepseek-v4-flash",
    "deepseek-v4-pro",
)

# 웹 설정의 AI 엔진 선택지 = Gemini + DeepSeek 통합 목록(순서 보존).
LLM_ENGINE_OPTIONS: tuple[str, ...] = (*GEMINI_ENGINE_OPTIONS, *DEEPSEEK_ENGINE_OPTIONS)


def is_deepseek_model(model: str) -> bool:
    """선택된 엔진이 DeepSeek provider인지 판별한다."""
    return model.strip().lower().startswith("deepseek")


# AI에게 명령을 주기 전에 모든 프롬프트 앞에 붙는 사용자 편집 가능 사전 프롬프트의 기본 예제.
# 웹 설정에서 수정할 수 있고, 비우면 이 기본값이 쓰인다(JSON 출력 안정성도 함께 강화).
AI_PREPROMPT_DEFAULT = (
    "당신은 한국 여행 콘텐츠(YouTube 영상·자막)를 분석해 여행지(POI) 정보를 정리하는 보조자다. "
    "항상 한국어로, 영상에 실제로 드러난 사실에 근거해 답하라. 확실하지 않은 장소명·위치·"
    "카테고리는 단정하지 말고 불확실성을 함께 표시하라. 광고·과장 표현은 제거하고 사실만 남겨라. "
    "출력은 지정된 JSON 스키마에 정확히 맞는 JSON만 반환하고, 코드펜스(```)나 추가 설명 문장은 붙이지 마라."
)


# 자막 교정 전용 system instruction(평문 응답). 영상 설명을 표기 근거로 활용하도록 5항 포함.
TRANSCRIPT_CORRECTION_SYSTEM_INSTRUCTION = (
    "너는 전문 자막 교정자다. 입력되는 유튜브 STT(음성인식) 자막의 오탈자, 맞춤법, "
    "띄어쓰기를 문맥에 맞게 교정하라.\n\n"
    "[엄격한 제약 조건]\n"
    "1. 원본 자막에 포함된 타임스탬프(예: 00:01:23) 구조를 절대 수정하거나 누락하지 마라.\n"
    "2. 음성인식 오류로 뭉개진 고유명사나 상호명은 문맥을 파악하여 표준 표기법으로 교정하라.\n"
    "3. 원본 문장의 타임라인 싱크를 유지해야 하므로, 임의로 문장을 합치거나 길이를 크게 늘리지 마라.\n"
    "4. 교정된 자막 이외의 불필요한 설명이나 인사말은 절대 출력하지 마라.\n"
    "5. 함께 제공되는 [영상 설명]은 정확한 상호명·고유명사·지명 표기의 근거다. 자막에서 음성인식으로 "
    "뭉개진 고유명사·상호명·지명은 [영상 설명]의 표기에 맞춰 교정하라. 단, 영상 설명에만 있고 자막에 "
    "없는 내용을 자막에 새로 추가하지는 마라.\n"
    "6. 이 서비스는 대한민국(한국) 국내 여행지만 다룬다. 대한민국이 아닌 해외 지역·장소·여행지에 대한 "
    "설명·내용은 교정하지 말고 원본 자막 그대로 남겨라(해외 내용은 보정 대상이 아니다)."
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
    # Web UI에서 생성한 공개 API 키를 public request hot path에서 캐시하는 시간(초).
    PUBLIC_API_KEY_CACHE_TTL_SECONDS: int = 60
    # 신뢰 CIDR에서 들어온 외부 클라이언트는 공개 API key 검증을 생략할 수 있다.
    # 기본은 비어 있어 명시 설정 없이는 우회하지 않는다.
    API_TRUSTED_CLIENT_CIDRS: str = ""
    # 키 없는 CIDR 우회는 client IP에 의존하는데, FORWARDED_ALLOW_IPS=*처럼 프록시가
    # 모든 X-Forwarded-For를 신뢰하면 client IP가 위조 가능하다(우회 무력화). 그래서
    # 이 우회는 기본 비활성이며, 위험을 이해한 운영자가 명시적으로 켜야 하고 반드시
    # FORWARDED_ALLOW_IPS를 실제 프록시 IP로 고정해야 한다.
    API_TRUSTED_CLIENT_BYPASS_ENABLED: bool = False
    # Next.js BFF가 관리자 요청임을 증명하는 서버 전용 shared secret.
    KTC_ADMIN_PROXY_SECRET: str = ""
    # 관리자 proxy로 신뢰할 수 있는 peer CIDR. Docker bridge와 localhost를 포함한다.
    KTC_ADMIN_TRUSTED_PROXY_CIDRS: str = (
        "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
    )
    KTC_ADMIN_USERNAME: str = "admin"
    # 로그인/로그아웃 감사 로그(login_events) 보존 행 수 상한. 미인증 경로(로그아웃·오설정
    # 로그인)도 감사 행을 남길 수 있어 무한 적재를 막는다. 초과분은 오래된 것부터 정리,
    # <=0이면 비활성.
    LOGIN_AUDIT_MAX_ROWS: int = 5000

    # --- 2. 데이터베이스 (PostgreSQL + PostGIS, ADR-25) ---
    DATABASE_URL: str = "postgresql+asyncpg://addr:addr@localhost:5432/kor_travel_concierge"
    KTC_TEST_PG_DSN: str = ""

    # --- LLM: Gemini ---
    GEMINI_API_KEY: str = ""
    GEMINI_ENGINE_VERSION: str = GEMINI_ENGINE_VERSION_DEFAULT

    # --- LLM: DeepSeek V4 (OpenAI 호환) ---
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"

    # --- AI 사전 프롬프트(모든 프롬프트 앞에 prepend). 비우면 AI_PREPROMPT_DEFAULT 사용 ---
    AI_PREPROMPT: str = ""

    # --- LLM 재시도(사람과 유사한 느린 백오프). Gemini·DeepSeek 공용 ---
    LLM_RETRY_MAX_ATTEMPTS: int = 4
    LLM_RETRY_BASE_DELAY_SECONDS: float = 15.0
    LLM_RETRY_MAX_DELAY_SECONDS: float = 90.0
    LLM_RETRY_JITTER: float = 0.3
    # 영상 1건 자막 교정의 시간예산(초). 긴 자막·느린 LLM이 단일 워커를 무한 점유하지
    # 않도록 초과 시 원본 자막으로 진행(best-effort)하고 다음 영상으로 넘어간다.
    LLM_TRANSCRIPT_CORRECTION_TIMEOUT_SECONDS: int = 240

    # --- Gemini API 키 전역 rate limit (gemini-2.5-flash 기준 가정값). DeepSeek는 별도 쿼터라
    # 이 한도에 잡히지 않는다. 키 전역(API+scheduler) 공유를 위해 DB 카운터로 강제한다(순차). ---
    GEMINI_RATE_RPM: int = 10  # 분당 요청 수
    GEMINI_RATE_RPD: int = 1500  # 일일 요청 수(PT 자정 리셋)
    GEMINI_RATE_TPM: int = 250_000  # 분당 토큰 수(입력+출력 추정)
    # POI 배치 1콜에 담을 영상 수 상한과 토큰 예산(TPM 헤드룸 확보). 20분급 영상은 수가 줄어든다.
    POI_BATCH_MAX_VIDEOS: int = 10
    POI_BATCH_TOKEN_BUDGET: int = 180_000
    # description 단독 후보 경로(T-168, 로드맵 PR-17, §1.3 D1 수율). 자막 전 provider 최종
    # 실패(T-164 판정) 시 영상을 폐기하는 대신, 저장된 영상 설명(제목·태그 포함)이 이 길이
    # 이상이면 그 텍스트로 검수 전용 후보를 추출한다(자동확정 금지, recall 경로). 미달이면
    # 기존대로 실패(사유 코드 description_too_short).
    # 주의: 이 길이 하한은 **신호 밀도 필터가 아니라 최소 컷**이다 — 극단적으로 짧은 설명만
    # 배제할 뿐 off-topic(홍보·해시태그 나열 등) 판별은 하지 않는다. 실제 off-topic 필터는
    # 하위 LLM POI 추출이며, 자막 대량 실패 시 저품질 description 후보가 검수 큐로 유입될 수
    # 있다. 그 유입량·승인율은 source_kind='description' audit 필터로 분리 측정한다(recall
    # 경로, §7.1 G9 — 후보 수 증가를 신뢰성 향상으로 계상하지 않는다).
    DESCRIPTION_POI_MIN_LENGTH: int = 200

    # --- 자동확정 근접 병합·audit 표본 (T-167, 로드맵 PR-14 개정판, D6·G9) ---
    # 근접 중복 재사용(병합) 반경(m). 이름·행정구역 identity 게이트(T-166) 통과 후에만 쓰이므로
    # 100→300m 상향이 오병합을 늘리지 않는다(무검증 반경 확대 금지 원칙과 정합).
    GEOCODE_MERGE_RADIUS_METERS: float = 300.0
    # 자동확정(MATCHED, reviewer="system") 후보 중 auto-match audit 표본으로 표시할 비율(0~1).
    # 표본은 오확정률(자동확정 뒤집힘 비율, §7 G9) 측정용이며, 표시일 뿐 MATCHED·export 상태는
    # 그대로 둔다(사후 관측). 1.0=전량, 0.0=비활성.
    AUTO_MATCH_AUDIT_SAMPLE_RATE: float = 0.1

    # --- YouTube Data API v3 ---
    YOUTUBE_API_KEY: str = ""
    YOUTUBE_USE_OFFICIAL_API: bool = True
    YOUTUBE_SEARCH_DAILY_BUDGET_UNITS: int = 1000
    # 한 수집 실행이 받을 수 있는 최대 영상 수(상한 겸 미지정 시 기본값). UI/소스 대상에서
    # 이 값까지 요청할 수 있다(수집 함수는 pageToken으로 50개 초과도 페이지네이션 수집).
    YOUTUBE_MAX_VIDEOS_PER_RUN: int = 300
    # 콘텐츠 유형 필터(숏츠/동영상)의 숏츠 판정 기준(초). duration이 이 값 이하면 숏츠로 본다.
    SHORTS_MAX_DURATION_SECONDS: int = 60

    # --- 자막/전사 폴백 순서 ---
    TRANSCRIPT_PROVIDER_ORDER: str = "youtube-transcript-api,yt-dlp,faster-whisper"
    # 실행 환경은 Linux Docker 전용이며 FFmpeg은 컨테이너 이미지가 apt로 제공한다.
    FFMPEG_PATH: str = "/usr/bin/ffmpeg"

    # --- whisper 수동 재전사 (T-169, 선별 실행 — auto whisper와 독립) ---
    # 운영자가 자막이 최종 실패한 영상을 명시적으로 whisper(faster-whisper 로컬 STT)로
    # 재전사할 때만 쓰는 상한/기본값이다. auto 전사 게이트(env `TRANSCRIPT_WHISPER_ENABLED`,
    # prod ON)의 동작·기본값은 아래 필드들이 건드리지 않는다 — 수동 force 경로 전용이다.
    #
    # 운영 결정(2026-07-13): 수동 whisper는 batch 레인(T-163) 단일 워커에서만 돌아
    # concurrency=1이 구조적으로 보장된다. duration cap이 1건당 상한을 걸고, 일일 CPU
    # 예산은 운영자가 batch 레인 투입량으로 통제한다(하드 리미터는 미구현 — 상한만 구현).
    # transcript_source='whisper' 기록은 PR-11 컬럼에 그대로 남는다.
    #
    # 영상 1건 재전사 상한(초). 이 값을 초과하는 영상은 수동 force 대상에서 400으로 거절한다.
    TRANSCRIPT_WHISPER_FORCE_MAX_DURATION_SECONDS: int = 1200
    # 수동 force 기본 whisper 모델(auto의 env `WHISPER_MODEL_SIZE` 기본 "base"보다 정확도 우선).
    WHISPER_MANUAL_MODEL_SIZE: str = "small"

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
    # --- Phase -1 provider 정책 kill switch (T-158, docs/provider-policy.md) ---
    # 원본 동영상/오디오(YouTube audiovisual content)의 RustFS "저장" 게이트.
    # 다운로드 자체는 이 플래그가 막지 않는다 — whisper 오디오는
    # TRANSCRIPT_WHISPER_ENABLED가 게이트, 프레임 스트림 취득(yt-dlp)은 현재 별도
    # 게이트 없음. YouTube API Developer Policies III.E.1(사전 서면 승인 없는
    # 다운로드·저장 제한)과 긴장 관계라 ADR-15 재검토 결정 전 prod에서는 false를
    # 권고한다. 기본값은 현행 동작 유지(true) — 끄면 store_raw_media가 저장을 스킵한다.
    RAW_MEDIA_STORE_ENABLED: bool = True

    # --- Geocoding / Reverse Geocoding ---
    GEOLOCATION_PROVIDER: str = "vworld"
    KAKAO_REST_API_KEY: str = ""
    NAVER_CLIENT_ID: str = ""
    NAVER_CLIENT_SECRET: str = ""
    VWORLD_SERVICE_KEY: str = ""
    # kor-travel-geo v2 연동 키. 별도 값이 없으면 현재 VWorld 서버 키와 동일하게 쓴다.
    KOR_TRAVEL_GEO_V2_API_KEY: str = ""
    # kor-travel-geo v2 REST endpoint. 비우면 행정코드 보강을 건너뛴다.
    KOR_TRAVEL_GEO_V2_BASE_URL: str = ""
    # 검수 페이지 멀티 provider 장소 검색용 (geocoding 키와 별개).
    GOOGLE_PLACES_API_KEY: str = ""
    NAVER_SEARCH_CLIENT_ID: str = ""
    NAVER_SEARCH_CLIENT_SECRET: str = ""
    # --- Phase -1 provider 정책 kill switch (T-158, docs/provider-policy.md) ---
    # 검수 장소 검색의 Google Places provider 호출 게이트. Google Maps Platform
    # Service Specific Terms §14.2는 Places 결과의 비-Google 지도(VWorld) 표시를
    # 금지하지만, 사용자 결정(2026-07-13)으로 현행 유지(true)가 승인됐다(인지된
    # 정책 리스크 — docs/provider-policy.md §7). 필요 시 끄는 수단으로 유지하며,
    # false면 /place-search가 google 결과를 빈 목록 + disabled 사유로 준다.
    GOOGLE_PLACE_SEARCH_ENABLED: bool = True

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
    def api_trusted_client_cidrs(self) -> list[str]:
        """공개 API 키 검증을 우회할 신뢰 클라이언트 CIDR 목록."""
        return [
            cidr.strip()
            for cidr in self.API_TRUSTED_CLIENT_CIDRS.split(",")
            if cidr.strip()
        ]

    @property
    def api_trusted_client_bypass_active(self) -> bool:
        """키 없는 신뢰 CIDR 우회가 실제로 활성인지(명시 활성 + CIDR 설정)."""
        return self.API_TRUSTED_CLIENT_BYPASS_ENABLED and bool(
            self.api_trusted_client_cidrs
        )

    @property
    def admin_trusted_proxy_cidrs(self) -> list[str]:
        """관리자 proxy header를 신뢰할 peer CIDR 목록."""
        return [
            cidr.strip()
            for cidr in self.KTC_ADMIN_TRUSTED_PROXY_CIDRS.split(",")
            if cidr.strip()
        ]

    @property
    def kor_travel_geo_v2_api_key(self) -> str:
        """kor-travel-geo v2 키는 미설정 시 VWorld 서버 키로 폴백한다."""
        return self.KOR_TRAVEL_GEO_V2_API_KEY or self.VWORLD_SERVICE_KEY

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
        """쉼표 구분 CORS origin 목록.

        `allow_credentials=True`(main.py)와 와일드카드 `*`는 함께 쓸 수 없으므로,
        실수로 섞여 들어온 `*` 항목은 제거한다(자격증명 포함 CORS는 정확한 Origin 매칭).
        """
        origins = [
            origin.strip()
            for origin in self.CORS_ALLOW_ORIGINS.split(",")
            if origin.strip() and origin.strip() != "*"
        ]
        if self.NEXT_PUBLIC_API_BASE_URL.startswith("http"):
            origins.append(self.NEXT_PUBLIC_API_BASE_URL.rstrip("/"))
        return sorted(set(origins))


@lru_cache
def get_settings() -> Settings:
    """프로세스 전역 단일 설정 인스턴스를 반환한다."""
    return Settings()
