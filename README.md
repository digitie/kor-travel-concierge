<div align="center">
  <img src="https://img.shields.io/badge/Next.js-000000?style=for-the-badge&logo=nextdotjs&logoColor=white" alt="Next.js" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Gemini_API-8E75C2?style=for-the-badge&logo=google-gemini&logoColor=white" alt="Gemini" />
  <img src="https://img.shields.io/badge/SpatiaLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white" alt="SpatiaLite" />
  <img src="https://img.shields.io/badge/RustFS-111827?style=for-the-badge" alt="RustFS" />
  <img src="https://img.shields.io/badge/Playwright-2EAD33?style=for-the-badge&logo=playwright&logoColor=white" alt="Playwright" />

  <h1>TripMate Agent</h1>
  <p><strong>소형 프로젝트 기준 AI 유튜브 여행 콘텐츠 추출 및 공간 데이터베이스화 시스템</strong></p>
</div>

<br />

`tripmate-agent`는 사용자가 지정한 유튜버, 재생목록, 검색 키워드를 바탕으로 YouTube 여행 콘텐츠를 탐색하고, Gemini API로 영상 속 여행지 정보를 추출·요약해 SQLite + SpatiaLite 공간 데이터베이스로 구축하는 애플리케이션입니다.

이 저장소는 1~2인 개발·운영과 동시 사용자 10명 내외를 전제로 합니다. 대규모 분산 크롤러보다 공식 API, 파일 기반 공간 DB, 전면 비동기 처리, 단일 실행자 스케줄러를 우선해 운영 부담을 줄입니다.

## 핵심 특징

- **공식 YouTube Data API v3 중심 수집**: 검색과 메타데이터는 `search.list`, `playlistItems.list`, `channels.list`, `videos.list`를 사용합니다. 비공식 검색 크롤러는 초기 설계에서 제외합니다.
- **격리된 자막 폴백**: 타인 영상 자막은 공식 captions API로 처리하기 어렵기 때문에 `youtube-transcript-api` → `yt-dlp` → `faster-whisper` 순서로 폴백합니다.
- **Gemini 기반 POI 추출**: 자막과 메타데이터에서 장소명, 위치 단서, 설명, 타임스탬프를 JSON Schema 기반으로 추출합니다.
- **RustFS 미디어 저장**: 다운로드한 원본 동영상, 자막 파일, 전사 결과, 대표 프레임은 별도 로컬 Docker RustFS 서비스에 저장하고 무기한 보존합니다.
- **SQLite + SpatiaLite 공간 DB**: 별도 DB 서버 없이 단일 파일에 장소, 영상, 매핑, 작업 상태, 공간 인덱스를 저장합니다.
- **VWorld 우선 지오코딩**: 지오코딩과 역지오코딩은 `python-vworld-api`의 `AsyncVworldClient`를 직접 사용하고, Kakao Local 주소 검색·키워드 장소 검색과 Naver를 보조 경로로 사용합니다. `kraddr-geo` 연계는 현재 계획에 포함하지 않습니다.
- **매칭 검수 UX**: 자동 매칭이 실패하거나 모호한 장소는 사용자가 원문, 후보 주소, 영상 타임스탬프를 보고 직접 수정하거나 제외 처리할 수 있습니다.
- **설명 원문과 Gemini 보정 분리**: YouTube 영상 설명 원문, Gemini 오탈자 보정 설명, Gemini 장소 보강 설명을 별도 필드로 저장합니다.
- **Web REST + MCP 분리**: 사람은 세분 REST API와 웹 UI를 사용하고, AI 에이전트는 MCP의 굵은 단위 읽기/쓰기 도구를 사용합니다.
- **전면 비동기 실행**: `httpx.AsyncClient`, `aiosqlite`, `asyncio.Semaphore`를 기본으로 사용하고, `yt-dlp`, FFmpeg, `faster-whisper` 같은 블로킹 작업은 executor로 격리합니다.
- **프론트엔드 운영 UX**: React Hook Form, Zod, shadcn/ui, Tailwind CSS, TanStack Query, `maplibre-gl` + VWorld WMTS를 기준으로 합니다.

## 시스템 구성도

```
[Next.js 프론트엔드] ── Web REST ──► [FastAPI API 서버]
        │                                  │
        │ 상태 폴링                         │ crawl_runs 생성
        ▼                                  ▼
[TanStack Query]                    [SQLite + SpatiaLite]
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
                         [youtube-transcript-api / yt-dlp / FFmpeg]
```

## 시작하기

본 프로젝트는 Windows 호스트 환경에서의 개발 및 테스트에 최적화되어 있습니다.

### 환경 변수 설정

루트의 `.env.example`을 참고하여 `.env` 파일을 생성합니다.

```bash
# 프론트엔드
NEXT_PUBLIC_VWORLD_SERVICE_KEY=your_vworld_browser_key_here
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000

# SQLite + SpatiaLite
DATABASE_URL=sqlite+aiosqlite:///./tripmate.db
SPATIALITE_EXTENSION_PATH=mod_spatialite
SQLITE_WAL_ENABLED=true

# Gemini
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_ENGINE_VERSION=gemini-2.0-flash

# YouTube Data API v3
YOUTUBE_API_KEY=your_youtube_api_key_here
YOUTUBE_USE_OFFICIAL_API=true

# RustFS
RUSTFS_ENABLED=true
RUSTFS_ENDPOINT=http://localhost:9003
RUSTFS_CONSOLE_URL=http://localhost:9004
RUSTFS_ACCESS_KEY=your_rustfs_access_key_here
RUSTFS_SECRET_KEY=your_rustfs_secret_key_here
RUSTFS_BUCKET_RAW_VIDEOS=tripmate-raw-videos
RUSTFS_BUCKET_SUBTITLES=tripmate-subtitles
RUSTFS_BUCKET_FRAMES=tripmate-frames
RUSTFS_HEALTH_PATH=/health/live
MEDIA_RETENTION_POLICY=infinite

# 지오코딩 / 역지오코딩
GEOLOCATION_PROVIDER=vworld
KAKAO_REST_API_KEY=your_kakao_rest_api_key_here
NAVER_CLIENT_ID=your_naver_client_id_here
NAVER_CLIENT_SECRET=your_naver_client_secret_here
VWORLD_SERVICE_KEY=your_vworld_server_key_here

# MCP
MCP_WRITE_ENABLED=true
MCP_TRANSPORT=stdio
MCP_HOST=127.0.0.1
MCP_PORT=8010
MCP_STREAMABLE_HTTP_PATH=/mcp
```

### 백엔드 실행

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### 프론트엔드 실행

```powershell
cd ../frontend
npm install
npm run dev
```

### ETL 실행

```powershell
cd ../etl
python runner.py
```

### E2E 테스트 실행

```powershell
cd ../tests
npm install
npx playwright install
npx playwright test
```

Playwright 설정은 backend `127.0.0.1:18080`과 frontend `127.0.0.1:13100`을 자동 기동하고, `tests\.tmp\e2e.db`를 테스트마다 재시드한다.

## 참고 문서

- [`AGENTS.md`](./AGENTS.md) — 프로젝트 내 문서화 언어 정책 및 에이전트 개발 규칙
- [`CLAUDE.md`](./CLAUDE.md) — 세션 연동 프로젝트 현황 및 소스 트리 구조 설명
- [`SKILL.md`](./SKILL.md) — 에이전트 지침서, Windows 개발 팁 및 도메인 어휘집
- [`docs/architecture.md`](./docs/architecture.md) — 시스템 아키텍처와 데이터 흐름
- [`docs/decisions.md`](./docs/decisions.md) — 주요 아키텍처 결정 기록
- [`docs/tasks.md`](./docs/tasks.md) — 개발 진행 현황 및 백로그
- [`docs/dev-environment.md`](./docs/dev-environment.md) — 상세 개발 서버 셋업 매뉴얼

## 라이선스

MIT License.
