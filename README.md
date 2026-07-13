<div align="center">
  <img src="https://img.shields.io/badge/Next.js-000000?style=for-the-badge&logo=nextdotjs&logoColor=white" alt="Next.js" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Gemini_API-8E75C2?style=for-the-badge&logo=google-gemini&logoColor=white" alt="Gemini" />
  <img src="https://img.shields.io/badge/PostgreSQL%20%2B%20PostGIS-336791?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL + PostGIS" />
  <img src="https://img.shields.io/badge/RustFS-111827?style=for-the-badge" alt="RustFS" />
  <img src="https://img.shields.io/badge/Playwright-2EAD33?style=for-the-badge&logo=playwright&logoColor=white" alt="Playwright" />

  <h1>Kor Travel Concierge</h1>
  <p><strong>소형 프로젝트 기준 AI 유튜브 여행 콘텐츠 추출 및 공간 데이터베이스화 시스템</strong></p>
</div>

<br />

`kor-travel-concierge`는 사용자가 지정한 유튜버, 재생목록, 검색 키워드를 바탕으로 YouTube 여행 콘텐츠를 탐색하고, Gemini API로 영상 속 여행지 정보를 추출·요약해 PostgreSQL + PostGIS 공간 데이터베이스로 구축하는 애플리케이션입니다.

이 저장소는 1~2인 개발·운영과 동시 사용자 10명 내외를 전제로 합니다. 대규모 분산 크롤러보다 공식 API, 관리 가능한 PostgreSQL/PostGIS schema, 전면 비동기 처리, 단일 실행자 스케줄러를 우선해 운영 부담을 줄입니다.

## 핵심 특징

- **공식 YouTube Data API v3 중심 수집**: 검색과 메타데이터는 `search.list`, `playlistItems.list`, `channels.list`, `videos.list`를 사용합니다. 비공식 검색 크롤러는 초기 설계에서 제외합니다.
- **격리된 자막 폴백**: 타인 영상 자막은 공식 captions API로 처리하기 어렵기 때문에 `youtube-transcript-api` → `yt-dlp` → `faster-whisper` 순서로 폴백합니다.
- **Gemini 기반 POI 추출**: 자막과 메타데이터에서 장소명, 위치 단서, 설명, 타임스탬프를 JSON Schema 기반으로 추출합니다.
- **RustFS 미디어 저장**: 다운로드한 원본 동영상, 자막 파일, 전사 결과, 대표 프레임은 별도 로컬 Docker RustFS 서비스에 저장하고 무기한 보존합니다.
- **PostgreSQL + PostGIS 목표 DB**: `python-kraddr-geo`가 쓰는 로컬 PostgreSQL/PostGIS 서버를 재사용하되 별도 DB `kor_travel_concierge`를 목표로 하고, 장소·영상·매핑·작업 상태·공간 인덱스를 Alembic으로 관리합니다.
- **VWorld 우선 지오코딩**: 지오코딩과 역지오코딩은 `python-vworld-api`의 `AsyncVworldClient`를 직접 사용하고, Kakao Local 주소 검색·키워드 장소 검색과 Naver를 보조 경로로 사용합니다. `kraddr-geo` 지오코딩 연계는 현재 계획에 포함하지 않습니다.
- **매칭 검수 UX**: 자동 매칭이 실패하거나 모호한 장소는 사용자가 원문, 후보 주소, 영상 타임스탬프를 보고 직접 수정하거나 제외 처리할 수 있습니다.
- **장소 언급 소스와 내보내기**: 확정 장소가 어느 영상과 유튜버에서 언급되었는지 확인하고, 언급 횟수로 정렬하며, 선택 또는 전체 장소를 `xlsx`, `gpx`, `kml`로 내보낼 수 있습니다.
- **범용 feature export API**: 검수 통과 YouTube 장소 후보를 `/api/v1/features/snapshot`·`/api/v1/features/changes`로 노출합니다. `kor-travel-map`이 이를 `kor-travel-concierge-youtube` provider로 pull해 `feature_id`와 `feature_snapshot`을 만들고, PinVi는 그 값을 자체 feature 연계 POI row로 저장합니다. Curated plan은 feature 자체가 아니라 이 POI row들의 모음으로 구성됩니다. 계약 정본은 `docs/feature-export-api.md`입니다.
- **완결성 있는 목록 API**: 검수·작업·장소·테마 목록은 `total`·`newest_id`·`newer_than`과 filter fingerprint keyset cursor가 있는 공통 envelope를 반환합니다. 범용 feature 공급의 기존 sequence cursor는 변경하지 않습니다. 계약 정본은 `docs/list-api-contract.md`입니다.
- **설명 원문과 Gemini 보정 분리**: YouTube 영상 설명 원문, Gemini 오탈자 보정 설명, Gemini 장소 보강 설명을 별도 필드로 저장합니다.
- **Web REST + MCP 분리**: 사람은 세분 REST API와 웹 UI를 사용하고, AI 에이전트는 MCP의 굵은 단위 읽기/쓰기 도구를 사용합니다.
- **전면 비동기 실행**: `httpx.AsyncClient`, SQLAlchemy async session, `asyncio.Semaphore`를 기본으로 사용하고, `yt-dlp`, FFmpeg, `faster-whisper` 같은 블로킹 작업은 executor로 격리합니다.
- **프론트엔드 운영 UX**: React Hook Form, Zod, shadcn/ui, Tailwind CSS, TanStack Query, `maplibre-gl` + VWorld WMTS를 기준으로 합니다.

## 시스템 구성도

```
[Next.js 프론트엔드] ── Web REST ──► [FastAPI API 서버]
        │                                  │
        │ 상태 폴링                         │ crawl_runs 생성
        ▼                                  ▼
[TanStack Query]                    [PostgreSQL + PostGIS]
                                           ▲
[MCP 서버] ── 도구 호출 / 작업 생성 ────────┤
                                           │
                                           ▼
                         [APScheduler 실행자] ── 객체 저장 ──► [RustFS 로컬 Docker]
                                           │
                                           ▼
                 [YouTube Data API / Gemini / Kakao / Naver / VWorld]
                                           │
                                           ▼
                     [youtube-transcript-api / yt-dlp / faster-whisper / FFmpeg]
```

## 시작하기

앱 런타임/배포는 **Linux Docker 전용**입니다(ADR-23). 기본 실행은 단일 호스트 Docker Compose이며, Windows 사용자는 WSL2(Ubuntu) + Docker 안에서 동일한 명령을 사용합니다. 에이전트/Codex 작업 명령은 `git`, `gh`, codegraph 계열 분석 명령까지 포함해 모두 WSL2(Ubuntu)를 포함한 Linux bash에서 실행합니다(ADR-33). **E2E Playwright 테스트는 n150 live/Linux 환경에서 우선 실행**하고, n150 접근·브라우저·환경 제약으로 불가할 때만 Windows 호스트에서 fallback 실행합니다.

REST API는 `/api/v1` 프리픽스 아래에 노출되고(`/health`·`/`만 버전 없음) `X-API-Key` 인증을 받습니다. 브라우저는 키를 직접 다루지 않고 same-origin Next BFF(`/api/v1/*` Route Handler)로 호출하며, BFF가 서버 사이드에서 백엔드로 프록시하면서 서버 전용 admin `BACKEND_API_KEY`를 주입합니다(키는 브라우저에 노출되지 않음). 외부 소비자는 DB에서 발급한 `read` 키로 명시된 공급 GET만 호출하며, query `key`에는 DB read 키만 사용할 수 있습니다. T-176부터 production consumer는 DB read 키만 사용하고 operator/BFF용 정적 admin 인증 정보와 분리합니다. 로컬 실행(`APP_ENV=local/test/e2e`)은 인증 코드 없이 동작하고, 외부에 노출하는 배포는 `APP_ENV=production`과 operator/BFF용 `API_KEYS`를 설정합니다(ADR-24·ADR-36).

### 환경 변수 설정

루트의 `.env.example`을 참고하여 `.env` 파일을 생성합니다.

```dotenv
# 프론트엔드
NEXT_PUBLIC_VWORLD_SERVICE_KEY=your_vworld_browser_key_here
# 브라우저는 same-origin BFF(`/api/v1`)로 호출하므로 기본 빈 값. 백엔드 직접 호출 시에만 설정
NEXT_PUBLIC_API_BASE_URL=
# BFF 프록시 대상(서버 전용). Compose는 http://api:8000, 로컬 기본 http://localhost:12601
BACKEND_ORIGIN=
# BFF가 주입하는 admin X-API-Key(서버 전용, NEXT_PUBLIC_* 아님). API_KEYS 중 하나와 동일하게
BACKEND_API_KEY=

# 고정 host port 계약
API_HOST_PORT=12601
MCP_HOST_PORT=12602
FRONTEND_HOST_PORT=12605
RUSTFS_HOST_PORT=12101
RUSTFS_CONSOLE_HOST_PORT=12105

# 실행 환경 및 API 인증 (ADR-24)
APP_ENV=local              # local/test/e2e는 무인증 우회, production은 X-API-Key 요구
API_AUTH_ENABLED=false     # true이면 환경과 무관하게 인증 강제
API_KEYS=                  # 외부 노출 배포의 BFF/operator용 static admin 키 목록

# PostgreSQL + PostGIS 목표(ADR-25, T-061)
# Compose 컨테이너는 host.docker.internal:5432, 컨테이너 밖 로컬 venv는 localhost:5432 사용
DATABASE_URL=postgresql+asyncpg://addr:addr@host.docker.internal:5432/kor_travel_concierge

# 스케줄러 / 주기 source scan
SCHEDULER_ENABLED=true
SCHEDULER_JOBSTORE_ENABLED=true
# 비우면 DATABASE_URL과 같은 DB를 sync psycopg URL로 사용
SCHEDULER_JOBSTORE_URL=
SCHEDULER_JOBSTORE_TABLE=apscheduler_jobs
SOURCE_SCAN_ENABLED=true
SOURCE_SCAN_INTERVAL_SECONDS=300

# Gemini
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_ENGINE_VERSION=gemini-2.0-flash

# YouTube Data API v3
YOUTUBE_API_KEY=your_youtube_api_key_here
YOUTUBE_USE_OFFICIAL_API=true

# RustFS
RUSTFS_ENABLED=true
RUSTFS_ENDPOINT=http://127.0.0.1:12101
RUSTFS_PUBLIC_BASE_URL=http://127.0.0.1:12101/kor-travel-concierge
RUSTFS_DOCKER_ENDPOINT=http://host.docker.internal:12101
RUSTFS_CONSOLE_URL=http://127.0.0.1:12105
RUSTFS_ACCESS_KEY=your_rustfs_access_key_here
RUSTFS_SECRET_KEY=your_rustfs_secret_key_here
RUSTFS_BUCKET_RAW_VIDEOS=kor-travel-concierge
RUSTFS_BUCKET_SUBTITLES=kor-travel-concierge
RUSTFS_BUCKET_FRAMES=kor-travel-concierge
RUSTFS_OBJECT_PREFIX=features
RUSTFS_REGION=us-east-1
RUSTFS_HEALTH_PATH=/health/live
MEDIA_RETENTION_POLICY=infinite

# 지오코딩 / 역지오코딩
GEOLOCATION_PROVIDER=vworld
KAKAO_REST_API_KEY=your_kakao_rest_api_key_here
NAVER_CLIENT_ID=your_naver_client_id_here
NAVER_CLIENT_SECRET=your_naver_client_secret_here
VWORLD_SERVICE_KEY=your_vworld_server_key_here

# MCP
MCP_WRITE_ENABLED=false
MCP_TRANSPORT=stdio
MCP_HOST=127.0.0.1
MCP_PORT=12402
MCP_STREAMABLE_HTTP_PATH=/mcp
```

쓰기 도구를 실제로 검증하거나 운영에서 허용할 때만 `.env`에서 `MCP_WRITE_ENABLED=true`로 명시합니다. Docker Compose의 MCP 서버는 같은 값을 사용하되 transport는 `streamable-http`로 override합니다.

### 기본 실행 (단일 호스트 Docker Compose, Linux/WSL2)

```bash
docker compose up -d --build    # host API 12601 / MCP 12602 / Web 12605, 외부 RustFS 12101·12105 사용
# 또는 thin 런처 (고정 포트 회수 후 기동)
bash scripts/start-live.sh
# smoke 검증 (api/mcp/scheduler/frontend 기동 → health 확인 → 외부 RustFS 검증 → 정리)
bash scripts/verify-docker-compose.sh
```

API는 `http://localhost:12601`, MCP는 `http://localhost:12602/mcp`, Web은 `http://localhost:12605`로 열립니다(host 고정 포트 → 컨테이너 내부 API `8000`·Web `3000`으로 매핑). RustFS는 이 Compose 스택 밖의 고정 Docker 서비스로 두고 S3 API `http://127.0.0.1:12101`, 콘솔 `http://127.0.0.1:12105`를 사용합니다. `scripts/start-live.sh`는 `docker compose up` 이전에 `scripts/stop-fixed-ports.sh`로 이 repo 소유 포트 `12601`/`12605`/`12602`를 점유한 리스너(Linux/Docker/WSL/Windows)를 회수하므로 이전 기동이 포트를 점유한 상태에서도 재시작이 성공합니다. RustFS 포트 `12101`/`12105`는 외부 서비스가 소유하므로 회수하지 않습니다(포트 회수 패턴은 `python-krtour-map` 프로젝트에서 차용). FFmpeg은 컨테이너 이미지(`Dockerfile.python`)가 apt로 제공하는 `/usr/bin/ffmpeg`를 사용하므로 호스트에서 별도로 준비할 필요가 없습니다.

### 백엔드 단독 실행 (컨테이너 밖 로컬 개발, Linux/WSL)

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cd ..
DATABASE_URL=postgresql+asyncpg://addr:addr@localhost:5432/kor_travel_concierge ./ktcctl api  # API 12601
```

### 프론트엔드 단독 실행

```bash
cd ../frontend
npm ci
npm run dev                     # Web 3000
```

### ETL 실행

```bash
./ktcctl etl
```

### E2E 테스트 실행 (n150 live/Linux 우선)

E2E Playwright 하니스는 **n150 live/Linux 환경에서 우선 실행**합니다. n150 접근, 브라우저 설치, 네트워크, DB, 계정 상태 때문에 실행할 수 없을 때만 Windows 호스트에서 fallback으로 같은 스위트를 실행합니다.

```bash
cd ../tests
npm install
npx playwright install
npx playwright test
```

Windows fallback이 필요한 경우에는 Windows 호스트의 `tests` 디렉토리에서 같은 명령을 PowerShell로 실행합니다. Playwright 설정은 backend `127.0.0.1:18080`과 frontend `127.0.0.1:13100`을 자동 기동하고, 테스트 DB를 매 테스트마다 재시드합니다(E2E backend는 `APP_ENV=e2e`로 무인증 동작).

## 참고 문서

- [`AGENTS.md`](./AGENTS.md) — 프로젝트 내 문서화 언어 정책 및 에이전트 개발 규칙
- [`CLAUDE.md`](./CLAUDE.md) — 세션 연동 프로젝트 현황 및 소스 트리 구조 설명
- [`SKILL.md`](./SKILL.md) — 에이전트 지침서, Linux/Docker(및 WSL2) 개발 팁 및 도메인 어휘집
- [`docs/architecture.md`](./docs/architecture.md) — 시스템 아키텍처와 데이터 흐름
- [`docs/decisions.md`](./docs/decisions.md) — 주요 아키텍처 결정 기록
- [`docs/tasks.md`](./docs/tasks.md) — 개발 진행 현황 및 백로그
- [`docs/dev-environment.md`](./docs/dev-environment.md) — 상세 개발 서버 셋업 매뉴얼

## 라이선스

MIT License. 자세한 내용은 [`LICENSE`](./LICENSE)를 참고합니다.
