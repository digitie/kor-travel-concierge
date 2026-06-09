# Linux/Docker(및 Windows WSL2) 개발 및 평가 환경 구축 가이드

본 문서는 `tripmate-agent` 프로젝트의 프론트엔드, 백엔드, ETL 파이프라인을 **Linux Docker**(앱 런타임/배포 전용, ADR-23)에서 빌드·실행하고, **E2E Playwright 테스트를 Windows 호스트에서 실행**(ADR-23 예외)하기 위한 상세 절차를 다룹니다. Windows 사용자는 앱 구동에 한해 WSL2(Ubuntu) + Docker를 사용합니다.

> 앱 런타임을 Windows 네이티브로 직접 띄우지 않습니다. 모든 앱 실행 명령은 Linux/WSL2 bash 기준이며, E2E 하니스만 Windows 호스트에서 실행합니다.

---

## 1. 사전 요구사항

### 앱 런타임/개발 (Linux 또는 Windows WSL2)
- **Docker Engine / Docker Compose**: 기본 실행 경로(단일 호스트 Compose). Windows 사용자는 Docker Desktop의 WSL2 backend 또는 WSL2 내부 Docker Engine을 사용합니다.
- **Node.js**: v20.9 이상. Next.js 16 기준 Node.js 20.9 이상이 필요합니다. ([다운로드](https://nodejs.org/))
- **Python**: v3.10 이상(컨테이너 밖 로컬 개발 시). Linux/WSL의 `python3 -m venv`를 사용합니다.
- **SQLite3 + SpatiaLite**: SQLite3는 Python에 기본 내장되어 있으며, 공간 함수 사용을 위해 `mod_spatialite` 확장이 필요합니다. 컨테이너 이미지는 apt로 제공합니다.
- **Git**: ([다운로드](https://git-scm.com/))

### E2E 테스트 (Windows 호스트, ADR-23 예외)
- **Node.js 20.9+**: Windows 호스트에 설치합니다.
- **Playwright 브라우저**: `npx playwright install`로 설치합니다(아래 9절 참조).

---

## 2. 백엔드 (FastAPI) 환경 구축 — Linux/WSL2

가장 간단한 경로는 단일 호스트 Docker Compose입니다(7절·8절 참조). 컨테이너 밖에서 백엔드만 단독으로 돌리려면 다음을 따릅니다.

1. `backend` 디렉토리로 이동하여 Python 가상환경(`.venv`)을 생성합니다:
   ```bash
   cd backend
   python3 -m venv .venv
   ```

2. 가상환경을 활성화합니다:
   ```bash
   . .venv/bin/activate
   ```

3. 필수 패키지를 설치합니다:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. SpatiaLite 확장 경로를 `.env`에 지정합니다:
   ```dotenv
   SPATIALITE_EXTENSION_PATH=mod_spatialite
   ```
   Linux/WSL에서 확장 로드가 실패하면 설치된 `mod_spatialite.so`의 절대 경로를 사용합니다(예: `apt install libsqlite3-mod-spatialite`).

5. 개발 서버를 실행합니다:
   ```bash
   python main.py
   ```
   서버는 `http://localhost:8000`에서 실행되며, API 명세(Swagger UI)는 `http://localhost:8000/docs`에서 확인할 수 있습니다. REST 엔드포인트는 `/api/v1` 프리픽스 아래에 있고(`/health`·`/`만 버전 없음) `X-API-Key` 인증을 받습니다. 로컬(`APP_ENV=local/test/e2e`)은 무인증 우회합니다(ADR-24).

---

## 3. RustFS 로컬 미디어 저장소

RustFS는 앱 컨테이너에 포함하지 않고 별도의 로컬 Docker 서비스로 구동합니다. ETL이 확보한 원본 동영상, 자막 파일, 전사 결과, 대표 프레임은 RustFS에 저장하고 SQLite + SpatiaLite에는 객체 URI와 체크섬만 기록합니다.

권장 로컬 포트:

- S3 API: `http://127.0.0.1:9003`
- 콘솔: `http://127.0.0.1:9004`
- 공개 객체 URL 기준: `http://127.0.0.1:9003/krtour-map`

Docker Compose 내부에서 `api`, `mcp`, `scheduler` 컨테이너가 RustFS에 접근할 때는
호스트 포트가 아니라 서비스명과 내부 포트인 `http://rustfs:9000`을 사용합니다.
`docker-compose.yml`은 이 값을 컨테이너 환경 변수로 override하므로, 로컬 `.env`의
`RUSTFS_ENDPOINT=http://127.0.0.1:9003`은 컨테이너 밖 Linux/WSL2에서 직접 실행하는
Python 프로세스 기준으로 유지합니다.

`.env`에는 다음 값을 둡니다.

```dotenv
RUSTFS_ENABLED=true
RUSTFS_ENDPOINT=http://127.0.0.1:9003
RUSTFS_PUBLIC_BASE_URL=http://127.0.0.1:9003/krtour-map
RUSTFS_DOCKER_ENDPOINT=http://rustfs:9000
RUSTFS_CONSOLE_URL=http://127.0.0.1:9004
RUSTFS_ACCESS_KEY=your_rustfs_access_key_here
RUSTFS_SECRET_KEY=your_rustfs_secret_key_here
RUSTFS_BUCKET_RAW_VIDEOS=krtour-map
RUSTFS_BUCKET_SUBTITLES=krtour-map
RUSTFS_BUCKET_FRAMES=krtour-map
RUSTFS_OBJECT_PREFIX=features
RUSTFS_REGION=us-east-1
RUSTFS_HEALTH_PATH=/health/live
MEDIA_RETENTION_POLICY=infinite
```

초기 버킷은 단일 `krtour-map` 버킷입니다. 원본 동영상, 자막, 전사 결과, 대표 프레임 객체는 모두 `features/` prefix 아래에 저장합니다. 객체 저장소 lifecycle 만료 정책은 설정하지 않습니다. DB에서 영상이나 장소가 제외 처리되더라도 RustFS 객체는 자동 삭제하지 않습니다.

`raw_video`, `subtitle`, `transcript`, `frame` 자산은 모두 `krtour-map` 버킷을 사용하고 객체 키 prefix로만 구분합니다. `MEDIA_RETENTION_POLICY`는 새 `media_assets.retention_policy`의 전역 기본값이며, 현재 정책에서는 행 단위 값도 `infinite`로 고정해 RustFS lifecycle 만료보다 항상 우선합니다.

상태 확인은 `/health/live` 엔드포인트로 수행합니다. `scripts/verify-docker-compose.sh`는
RustFS health 확인 후 `api` 컨테이너 안에서 `scripts/verify_rustfs.py`를 실행해 기본 버킷을 만들고 `features/healthcheck/t014-smoke.txt` 객체를 업로드·조회합니다.
무기한 보존 원칙에 따라 smoke 객체도 자동 삭제하지 않고 같은 key로 덮어씁니다.

---

## 4. 프론트엔드 (Next.js) 환경 구축 — Linux/WSL2

가장 간단한 경로는 Docker Compose(7절·8절)로 `frontend` 컨테이너를 함께 띄우는 것입니다. 컨테이너 밖에서 프론트엔드만 단독으로 개발하려면 다음을 따릅니다.

1. 프로젝트 루트에서 로컬 개발 환경용 `.env` 파일을 생성합니다:
   ```bash
   cp .env.example .env
   ```
   `.env` 파일을 편집기로 열고, 발급받은 VWorld 지도 서비스 API 키를 입력합니다:
   ```dotenv
   NEXT_PUBLIC_VWORLD_SERVICE_KEY=your_vworld_api_key_here
   ```

2. `frontend` 디렉토리로 이동하여 Node.js 의존성 패키지를 설치합니다:
   ```bash
   cd frontend
   npm install
   ```

3. Next.js 개발 서버를 실행합니다:
   ```bash
   npm run dev
   ```
   웹 브라우저에서 `http://localhost:3000`으로 접속하여 프론트엔드 화면을 확인합니다. 프론트엔드는 기본적으로 API `http://localhost:8000`을 호출하며, REST 호출은 `/api/v1` 프리픽스를 사용합니다. 로컬(`APP_ENV=local/test/e2e`)에서는 API 인증이 우회되므로 `X-API-Key` 없이 호출합니다(ADR-24).

   `CORS_ALLOW_ORIGINS`는 환경변수, `.env`, 기본값 순서로 적용됩니다. 기본값에는 프론트엔드 개발 포트(`3000` 또는 `FRONTEND_HOST_PORT` override)와 E2E 포트 `13100`의 `localhost` 및 `127.0.0.1` origin을 포함합니다.

4. 정적 검증을 실행합니다:
   ```bash
   npm run lint
   npm run type-check
   npm run build
   ```
   - `npm run lint`는 Next.js 16의 `next lint` 제거에 맞춰 ESLint flat config(`eslint.config.mjs`)와 `eslint .`를 사용합니다.
   - `npm run type-check`는 clean checkout에서도 `.next/dev/types`를 만들 수 있도록 `next typegen && tsc --noEmit`을 실행합니다.
   - Next.js 16 / React 19 업그레이드 이후 `npm audit`은 0건이어야 합니다. Next 내부 `postcss` transitive 보안 항목은 root `postcss` 버전과 맞추는 npm `overrides`로 관리합니다.

---

## 5. ETL 파이프라인 작동 테스트

ETL 프로세스는 백엔드 가상환경이 활성화된 상태에서 별도 Python 명령으로 트리거하거나, 구현 후 APScheduler 실행자가 `crawl_runs`의 pending 작업을 처리합니다. RustFS가 켜져 있으면 자막, 전사 결과, 대표 프레임, 필요 시 원본 동영상 또는 오디오가 RustFS에 저장되어야 합니다.

실제 외부 서비스를 호출하는 통합 검증에는 다음 값이 필요합니다.

| 검증 범위 | 필요한 환경 변수 |
| --- | --- |
| Docker/API/UI/MCP/RustFS smoke | 외부 API 키 불필요. RustFS는 개발 기본값 사용 가능 |
| YouTube 검색·채널·재생목록 수집 | `YOUTUBE_API_KEY` |
| Gemini POI 추출·설명 보정·Deep Research | `GEMINI_API_KEY`, `GEMINI_ENGINE_VERSION` |
| VWorld 지오코딩·역지오코딩 | `VWORLD_SERVICE_KEY` |
| Kakao 키워드 장소 검색·Naver 보조 검증 | `KAKAO_REST_API_KEY`, `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` |
| 브라우저 VWorld 지도 타일 | `NEXT_PUBLIC_VWORLD_SERVICE_KEY` |
| 실제 RustFS 계정값 검증 | `RUSTFS_ACCESS_KEY`, `RUSTFS_SECRET_KEY` |
| 대표 프레임 추출 | `FFMPEG_PATH` |

VWorld 서버 호출은 `python-vworld-api`의 `AsyncVworldClient`를 직접 사용한다. `backend/requirements.txt`는 Docker 이미지에 `git` 바이너리를 요구하지 않도록 GitHub archive commit pin을 사용하며, 로컬 패키지 변경분을 바로 검증할 때만 다음처럼 editable 설치로 덮어쓴다.

```bash
cd backend
. .venv/bin/activate
pip install -e ../../python-vworld-api
```

Kakao 보조 경로는 공식 [Local API 개발 가이드](https://developers.kakao.com/docs/ko/local/dev-guide)의 주소 검색 후 결과가 없을 때 `GET /v2/local/search/keyword.json` 키워드 장소 검색을 사용한다. 내부 wrapper 계층은 늘리지 않고, 외부 응답을 내부 후보 모델로 바꾸는 최소 변환만 유지한다.

대표 프레임 추출 runtime은 `FFMPEG_PATH` 환경변수에 지정된 실행 파일만 직접 사용합니다. Docker Compose 이미지는 apt로 설치한 `/usr/bin/ffmpeg`를 사용하며, `DOCKER_FFMPEG_PATH`를 컨테이너 내부 `FFMPEG_PATH`(`/usr/bin/ffmpeg`)로 주입합니다. 컨테이너 밖 Linux/WSL2에서 직접 실행할 때는 `apt install ffmpeg` 후 `FFMPEG_PATH`를 설치된 `ffmpeg` 경로로 지정합니다.

YouTube E2E 입력은 표시명보다 API에서 바로 처리 가능한 ID를 사용합니다.

- 채널 기준: `UC...` 형식의 YouTube channel id
- 재생목록 기준: `PL...`, `UU...` 등 playlist id

`@handle`, 채널 URL, 유튜버 표시명은 현재 파이프라인의 1차 입력이 아닙니다. 사람이 보기 좋은 이름만 알고 있다면 먼저 YouTube Studio, 채널 페이지 metadata, 또는 YouTube Data API로 `UC...` channel id를 확인한 뒤 사용합니다. 가장 안정적인 E2E 입력은 재생목록 ID이며, 채널 ID를 주면 `channels.list`로 uploads playlist를 찾아 수집합니다.

1. `.env` 환경 변수가 루트에 선언되어 있거나, `etl/` 폴더 내에 배치되어 있는지 확인합니다.
2. 가상환경이 활성화된 터미널에서 다음 스크립트를 구동합니다:
   ```bash
   cd ../etl
   python runner.py
   ```
   - 스크립트가 돌아가며 공식 YouTube Data API v3, Gemini API, VWorld 지오코딩·역지오코딩, Kakao 키워드 장소 검색, Naver 보조 검증을 거쳐 SQLite + SpatiaLite DB에 최종 적재하는 로그를 관측할 수 있습니다.
   - RustFS 저장이 활성화된 경우 `media_assets`에 객체 URI, 체크섬, 크기, `retention_policy = infinite`가 기록되는지 확인합니다.

---

## 6. MCP 서버 로컬 테스트

MCP 서버는 웹 브라우저를 거치지 않는 AI 에이전트용 읽기/쓰기 UX입니다. 백엔드와 같은 SQLite + SpatiaLite 데이터베이스와 도메인 서비스를 공유하며, 장시간 작업은 직접 실행하지 않고 `crawl_runs.pending` 작업으로 생성합니다.

```dotenv
MCP_WRITE_ENABLED=false
MCP_TRANSPORT=stdio
```

쓰기 도구를 직접 검증할 때만 `.env`에서 `MCP_WRITE_ENABLED=true`로 바꿉니다. 기본값은 읽기 도구만 노출하는 안전 모드입니다.

로컬 Python 가상환경에서 MCP 의존성을 함께 설치합니다.

```bash
cd backend
. .venv/bin/activate
pip install -r ../mcp/requirements.txt
cd ..
python mcp/server.py
```

실제 구현 패키지는 외부 MCP SDK 패키지 이름과 충돌하지 않도록 `tripmate_mcp`에 둡니다. `mcp/server.py`는 Docker Compose의 기존 실행 명령을 보존하는 래퍼입니다.

등록 도구는 다음과 같습니다.

| 구분 | 도구 |
| --- | --- |
| 읽기 | `get_harvest_status`, `search_existing_places`, `get_place_detail` |
| 쓰기 | `harvest_travel_destinations`, `correct_place`, `merge_places`, `trigger_deep_research`, `review_unmatched_place`, `resolve_place_candidate` |

모든 쓰기 도구는 필수 `idempotency_key`를 받습니다. 같은 멱등 키로 재호출하면 새 변경을 만들지 않고 `audit_logs`에 저장된 이전 결과를 반환합니다. 로컬 테스트에서는 쓰기 도구 호출 후 `audit_logs.actor_type = 'mcp'` 행이 기록되는지, 실제 API 키가 로그에 출력되지 않는지 함께 확인합니다.

---

## 7. APScheduler 실행자 테스트 (구현 후)

스케줄러는 API 서버나 MCP 서버가 만든 `crawl_runs.pending` 작업을 단일 실행자로 claim해 처리합니다.

```dotenv
SCHEDULER_ENABLED=true
CRAWL_MAX_CONCURRENT_VIDEOS=4
HTTP_MAX_CONCURRENT_REQUESTS=8
SCHEDULER_POLL_INTERVAL_SECONDS=5
SCHEDULER_HEARTBEAT_INTERVAL_SECONDS=30
SCHEDULER_STALE_THRESHOLD_SECONDS=300
SCHEDULER_MAX_RETRIES=3
```

검증 시 API/MCP가 직접 장시간 작업을 실행하지 않고 `job_id`만 반환하는지 확인합니다. scheduler는 APScheduler interval job으로 `crawl_runs.pending` 작업을 claim하며, handler 예외나 지원하지 않는 job type은 `failed` 상태와 `last_error`로 남겨야 합니다.

---

## 8. Docker Compose 통합 검증 — Linux/WSL2

이것이 기본 실행/검증 경로입니다. Linux 또는 Windows WSL2(Ubuntu) 안에서 Docker Engine(또는 Docker Desktop WSL backend)이 실행 중인 상태로 다음을 실행합니다.

```bash
cp .env.example .env
# 실제 API 키가 필요한 경로를 검증할 때만 .env 값을 수정합니다.
./scripts/verify-docker-compose.sh
```

`scripts/verify-docker-compose.sh`가 수행하는 일:

1. `docker compose config --quiet`로 Compose 문법과 환경 변수 해석을 확인합니다.
2. `api`, `mcp`, `scheduler`, `frontend` 이미지를 빌드합니다(`SKIP_BUILD=1`로 생략 가능).
3. `rustfs`, `api`, `mcp`, `scheduler`, `frontend`를 단일 프로젝트(`tripmate-agent-verify`)로 실행합니다.
4. `http://127.0.0.1:9003/health/live`, `http://localhost:8000/health`, `http://localhost:3000` 응답을 확인합니다. API health(`/health`)는 버전 프리픽스 없이 노출되며, 검증 컨텍스트는 무인증입니다.
5. MCP `streamable-http` 포트(`8010`)가 리스닝 중인지 확인합니다. MCP endpoint는 일반 브라우저 GET이 아니라 MCP client protocol로 접근해야 합니다.
6. `api` 컨테이너 안에서 `scripts/verify_rustfs.py`를 실행해 `krtour-map` 버킷 생성과 `features/healthcheck/t014-smoke.txt` 객체 업로드·조회를 확인합니다.
7. 기본적으로 `docker compose down`으로 컨테이너를 정리합니다.

컨테이너를 계속 띄워 화면을 확인하려면 `KEEP_RUNNING=1`을 지정합니다.

```bash
KEEP_RUNNING=1 ./scripts/verify-docker-compose.sh
```

단순히 라이브로 띄우기만 하려면 `scripts/start-live.sh`를 사용합니다. 이 스크립트는 Docker CLI를 확인한 뒤 `docker compose up --build`로 `rustfs`/`api`/`mcp`/`scheduler`/`frontend`를 함께 띄우는 래퍼입니다.

```bash
./scripts/start-live.sh
```

이미 다른 로컬 프로젝트가 기본 포트를 사용 중이면 host port override 환경 변수만 바꿔 검증합니다. `docker-compose.yml`은 `${RUSTFS_HOST_PORT}`, `${API_HOST_PORT}`, `${MCP_HOST_PORT}`, `${FRONTEND_HOST_PORT}`(및 `${RUSTFS_CONSOLE_HOST_PORT}`)를 지원합니다.

```bash
RUSTFS_HOST_PORT=19003 \
RUSTFS_CONSOLE_HOST_PORT=19004 \
API_HOST_PORT=18000 \
MCP_HOST_PORT=18010 \
FRONTEND_HOST_PORT=13000 \
./scripts/verify-docker-compose.sh
```

예를 들어 API 포트만 바꾸려면 `API_HOST_PORT=18000 ./scripts/verify-docker-compose.sh`처럼 단일 변수만 지정합니다.

Compose에서 MCP 서버는 로컬 `stdio` 기본값과 달리 `streamable-http` transport로 실행하며,
기본 포트 기준 `http://localhost:8010/mcp`로 접근합니다.

---

## 9. E2E 통합 테스트 (Playwright) — Windows 호스트 (ADR-23 예외)

> **여기만 Windows입니다.** 앱 런타임/배포는 Linux/WSL2 Docker로만 구동하지만(2~8절), E2E Playwright 스위트는 **의도적으로 Windows 호스트에서 직접 실행**합니다. 실제 Windows 브라우저 사용 경험(VWorld 지도 렌더링 포함)을 검증하기 위함이며, 이 절의 PowerShell 명령은 Windows 호스트에서 그대로 실행하는 것이 맞습니다. E2E 백엔드는 `APP_ENV=e2e`로 기동하므로 API 인증(`X-API-Key`)이 우회됩니다(ADR-24).

본 프로젝트는 프론트엔드와 백엔드가 정상적으로 메시지를 교환하고 SQLite + SpatiaLite DB 적재 및 VWorld 지도 로딩이 깨지지 않는지 Playwright E2E로 검증합니다.

1. Windows 호스트에서 `tests` 디렉토리로 이동하여 의존 모듈을 설치합니다:
   ```powershell
   cd ../tests
   npm install
   ```

2. Playwright 전용 헤드리스 브라우저를 다운로드합니다:
   ```powershell
   npx playwright install
   ```

3. 테스트를 실행합니다. Playwright 설정이 backend `127.0.0.1:18080`과 frontend `127.0.0.1:13100` 개발 서버를 자동으로 기동합니다:
   ```powershell
   npx playwright test
   ```
   - 특정 테스트 브라우저 UI를 보면서 시각적으로 검증하고 싶다면 `--headed` 플래그를 추가합니다:
     ```powershell
     npx playwright test --headed
     ```
   - 포트를 바꾸려면 `E2E_BACKEND_PORT`, `E2E_FRONTEND_PORT`, `E2E_API_BASE_URL`, `E2E_FRONTEND_URL` 환경 변수를 지정합니다.
   - 테스트 DB는 `tests\.tmp\e2e.db`에 생성되며, 매 테스트 시작 전에 `tests\scripts\seed_e2e.py`가 장소, 검수 후보, MCP 감사 로그, RustFS 대표 프레임 메타데이터를 재시드합니다.
   - 테스트 산출물(`tests\test-results`, `tests\playwright-report`)은 Git 추적 대상이 아닙니다.

검증 범위는 다음과 같습니다.

| 시나리오 | 확인 내용 |
| --- | --- |
| 메인 화면 | VWorld 지도 fallback/렌더링, 장소 목록, 검수 큐, 운영 패널, MCP 감사 로그 |
| 수집 시작 | `POST /api/v1/harvest` 호출, `job_id`, `pending` 상태 표시 |
| Deep Research 및 검수 | Deep Research 작업 생성, 매칭 실패 후보 사용자 보정 저장, 장소 목록 반영 |
| 설정 저장 | Gemini 엔진 설정 저장 및 `/api/v1/settings` 반영 |

Browser plugin이 없는 환경에서는 일반 Playwright CLI로 검증합니다. 제품 코드에는 E2E만을 위한 별도 adapter/wrapper를 추가하지 않고, REST API와 화면의 접근성 이름을 직접 사용합니다.

---

## 10. 트러블슈팅 — Linux/WSL2/Docker

### 1. SQLite3 DB Locked Error
ETL 스크립트가 대량의 쓰기(Write) 연산을 수행하는 중에 사용자가 웹에서 API를 조회/변경하면 데이터베이스 락이 발생할 수 있습니다.
- **해결책**: 백엔드 DB 세션 커넥션 문자열 설정에 `?timeout=20` 쿼리 파라미터를 붙여 Lock 대기 시간을 기본 5초에서 20초로 연장하거나, SQLite WAL(Write-Ahead Logging) 모드를 명시적으로 켭니다.

### 2. SpatiaLite 확장 로드 실패
`mod_spatialite`를 찾지 못하거나 공유 라이브러리 의존성이 누락되면 공간 함수 초기화가 실패할 수 있습니다.
- **해결책**: Docker 이미지는 `apt install libsqlite3-mod-spatialite`로 확장을 제공하므로 `SPATIALITE_EXTENSION_PATH=mod_spatialite`이면 충분합니다. 컨테이너 밖 Linux/WSL2에서 로드가 실패하면 동일 패키지를 설치한 뒤 `SPATIALITE_EXTENSION_PATH`를 설치된 `mod_spatialite.so`의 절대 경로로 지정합니다.

### 3. Docker / WSL2 환경 문제
WSL2에서 `docker` 명령을 찾지 못하거나 컨테이너가 기동하지 못할 수 있습니다.
- **해결책**: WSL2(Ubuntu) 안에서 Docker Engine을 설치하거나 Docker Desktop의 WSL backend 통합을 활성화하고, `docker` 명령이 PATH에 잡히는지 확인합니다. 빌드 캐시나 네트워크 문제로 이미지 빌드가 실패하면 `docker compose build --no-cache`로 재시도합니다. 기본 포트가 이미 점유된 경우 8절의 host port override 환경 변수(`API_HOST_PORT` 등)로 우회합니다.

### 4. VWorld 타일 로드 실패 (403 Forbidden)
지도가 나오지 않고 회색 배경만 출력되는 현상입니다.
- **해결책**: VWorld 개발자 센터에 등록된 API 키의 사용 도메인 설정이 `http://localhost:3000`(및 필요 시 API `http://localhost:8000`)을 명시적으로 포함하고 있는지 재차 점검하십시오.

### 5. RustFS 헬스체크 실패
RustFS 컨테이너는 실행 중인데 앱에서 저장소 연결 실패가 발생할 수 있습니다.
- **해결책**: `RUSTFS_ENDPOINT`가 S3 API 포트(`9003`)를 가리키는지 확인하고, 브라우저 콘솔 포트(`9004`)와 혼동하지 마십시오. 사용하는 RustFS 이미지에 따라 `/health`와 `/health/live` 중 실제 200 응답을 반환하는 경로를 `RUSTFS_HEALTH_PATH`에 지정합니다.
