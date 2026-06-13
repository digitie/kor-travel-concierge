# AGENTS.md

## 문서 언어 정책

이 저장소의 **모든 Markdown 문서는 한글로 작성한다**. 예외 없음. `README.md`, `CLAUDE.md`, `SKILL.md`도 본문은 한글이다.

다음 항목만 영어를 유지한다 — 한글로 옮기면 의미가 변하거나 정확성이 깨지기 때문:

- **코드 식별자**: 함수/타입/prop/이벤트/모듈 이름 (`useVWorldMap`, `TravelDestination`, `GeminiEngineSettings`, `'use client'`).
- **명령어와 경로**: `npm run dev`, `poetry run uvicorn`, `F:\dev\kor-travel-concierge\frontend`, `pytest`.
- **외부 공식 용어**: Next.js, React, FastAPI, SQLAlchemy, PostgreSQL, PostGIS, SQLite3, SpatiaLite, Alembic, RustFS, Playwright, MapLibre GL JS, WMTS, REST API, Gemini API, ETL.
- **벤더/제품명**: Google, Kakao, Naver, VWorld, YouTube, OpenAI.
- **표준 keyword**: ADR, CHANGELOG, ISO 8601 날짜, semver 라벨(`Added`/`Changed`/`Removed`/`Fixed`/`Security`).
- **shell 출력 / 로그 예시**: 그대로 캡처한 문자열은 보존.

설명 문장, 절제목, 표 column 헤더, ADR 본문, 빠른 시작 가이드, 일지 항목은 한글로 적는다. 새 문서를 만들 때 영문 초안을 두지 않는다 — 처음부터 한글로 쓴다.

## 역할

이 저장소(GitHub 저장소 이름 `kor-travel-concierge`)는 Gemini를 활용하여 YouTube의 여행 컨텐츠를 검색, 분석, 요약하고 정리하여 여행지 데이터를 구축하는 **지능형 여행 비서 애플리케이션**이다. 시스템은 다음 네 부분으로 구성된다:
1. **Next.js & React 프론트엔드**: 수집된 데이터 조회, 검색 키워드 및 유튜버 CRUD, VWorld 지도 기반 위치 매핑, Gemini Deep Research 실행 및 설정 화면.
2. **MCP 서버 UX**: AI 에이전트가 여행 데이터베이스를 조회하고 키워드/유튜버 CRUD, 보정, 병합, ETL 실행 트리거를 수행하는 읽기/쓰기 도구 표면.
3. **FastAPI & SQLAlchemy 2.0 백엔드**: PostgreSQL + PostGIS 기반으로 비동기 API 엔드포인트와 도메인 로직을 서빙하며, schema 이력은 Alembic으로 관리한다.
4. **ETL 파이프라인**: 공식 YouTube Data API v3 검색 및 업데이트 탐색 → 자막/전사/Gemini 활용 영상 정리 및 POI 추출 → 대표 프레임 추출 및 원본 동영상·자막·전사 결과·대표 프레임 RustFS 저장 → 외부 REST API 연동 주소 보정 작업 수행.

## 식별자 (혼동 방지)

| 항목 | 값 |
|------|----|
| GitHub 저장소 이름 | `kor-travel-concierge` |
| 프론트엔드 프레임워크 | Next.js (React 기반) |
| 백엔드 프레임워크 | FastAPI (Python 기반) |
| ORM / 데이터베이스 | SQLAlchemy 2.0 / PostgreSQL + PostGIS (`asyncpg`, Alembic) |
| 지도 뷰 라이브러리 | `maplibre-gl + VWorld WMTS` |
| E2E 테스트 도구 | Playwright — **E2E 하니스는 Windows 호스트에서 실행**(앱 런타임/배포는 Linux Docker 전용, ADR-23 예외) |
| REST API 경계 | 모든 엔드포인트는 `/api/v1` 프리픽스 아래(`/health`·`/`는 버전 없음). 브라우저는 same-origin Next BFF 경유로 호출하고 BFF가 서버 전용 `BACKEND_API_KEY`로 `X-API-Key`를 주입(키 비노출), 직접/외부 호출자는 `X-API-Key` 직접 전송, 로컬(`APP_ENV=local/test/e2e`)은 무인증 우회 (ADR-24) |
| LLM API | Gemini API (1.5 / 2.0 / Flash 등 설정 가능) |
| MCP UX | 읽기/쓰기 모두 가능한 MCP 서버 |
| Geocoding / Reverse Geocoding | VWorld 최우선(`python-vworld-api`의 `AsyncVworldClient` 직접 사용), Kakao Local 주소·키워드 장소 검색 보조, Naver 보조 검증 (`kraddr-geo` 지오코딩 연계 없음; ADR-25의 `python-kraddr-geo` PostgreSQL/PostGIS DB 서버 재사용은 별도) |
| YouTube 수집 | 공식 YouTube Data API v3 우선, 비공식 의존은 자막/프레임 구간으로 격리 |
| 미디어 저장소 | 별도 로컬 Docker RustFS 서비스, 원본 동영상·자막·전사 결과·대표 프레임 무기한 보존 |
| 스케줄러 | APScheduler 단일 실행자 |
| 프론트엔드 폼/상태 | React Hook Form / Zod / shadcn/ui / Tailwind CSS / TanStack Query |

## 개발 환경 정책

앱 런타임/배포 실행 환경은 **Linux Docker 전용**이다(ADR-23). Windows 네이티브 **앱** 실행 경로는 배제하며, Windows 호스트에서는 **WSL2(Ubuntu) 안에서 Linux/Docker로 구동**한다. 모든 신규 스크립트·명령은 bash·Linux 기준으로 작성한다. **단, E2E Playwright 테스트 하니스는 의도적으로 Windows 호스트에서 실행한다**(ADR-23 예외, 아래 Playwright 구동 참조).
- **Codex 명령 실행 위치 강제**: 이 저장소에서 에이전트/Codex가 실행하는 모든 작업 명령은 기본적으로 WSL2(Ubuntu) bash에서 수행한다. 예외는 `git` 명령과 Windows 호스트 Playwright E2E(`cd tests; npm install; npx playwright install; npx playwright test`)뿐이다. `gh`, Docker, Python, Node.js, 테스트, 빌드, 파일 검색·확인 명령은 WSL에서 실행한다.
- **기본 실행**: 단일 호스트 Docker Compose(ADR-18). `docker compose up --build`로 backend(8000), frontend(3000), rustfs, mcp를 함께 띄운다. Windows 사용자는 WSL2 + Docker Engine(또는 Docker Desktop WSL backend) 안에서 같은 명령을 bash로 실행한다.
- **REST API 경계**: REST 엔드포인트는 `/api/v1` 프리픽스 아래에 있다(`/health`·`/`만 버전 없음). 브라우저는 키를 직접 다루지 않고 same-origin Next BFF(`/api/v1/*` Route Handler)로 호출하며, BFF가 서버 사이드에서 백엔드로 프록시하면서 서버 전용 `BACKEND_API_KEY`로 `X-API-Key`를 주입한다(키는 브라우저에 노출되지 않음). 직접/외부(비-브라우저) 호출자는 `X-API-Key`를 직접 보내며, 로컬 실행(`APP_ENV=local/test/e2e`)은 인증 코드 없이 우회한다. 외부 노출 배포는 `APP_ENV=production`과 `API_KEYS`를 설정한다(ADR-24).
- **Python 환경**: 컨테이너 밖 로컬 개발은 Linux/WSL에서 `python3 -m venv .venv && . .venv/bin/activate`로 Python 3.10+ 가상환경을 만들어 FastAPI, SQLAlchemy, ETL 스크립트를 구동한다. DB 연결은 PostgreSQL/PostGIS 기준이다.
- **Node.js 환경**: Node.js 20+ 버전을 사용하며, frontend 폴더 내에서 Next.js를 구동한다.
- **Playwright 구동(Windows 호스트 예외)**: E2E 테스트 하니스는 **Windows 호스트**에서 실행한다 — `cd tests; npm install; npx playwright install; npx playwright test`. 이는 실제 사용자에 가까운 Windows 브라우저 화면을 검증하기 위한 ADR-23의 유일한 예외이며, 앱 런타임을 Windows 네이티브로 되살리는 것이 아니다(앱 런타임 코드에는 `win32` 분기를 두지 않는다. 단 E2E 런처 스크립트 `tests/scripts/*.mjs`는 Windows 호스트 실행을 위해 venv interpreter 경로 해석·`taskkill` 자식 프로세스 정리 같은 OS별 처리를 유지한다).
- **FFmpeg**: 컨테이너 이미지(`Dockerfile.python`)가 apt로 `/usr/bin/ffmpeg`를 제공한다. 호스트 자동 다운로드·경로 분기는 두지 않는다.
- **RustFS 환경**: 원본 동영상, 자막, 전사 결과, 대표 프레임은 별도 로컬 Docker RustFS 서비스에 저장하고 자동 만료 정책을 두지 않는다.
- **API 키 관리**: VWorld, Gemini, YouTube, Kakao, Naver, RustFS 등 외부 API 키와 접근 키는 절대 코드에 하드코딩하지 않고 `.env` 파일로 주입하며 로그 출력 시 마스킹 처리한다.

작업 전에 반드시 다음을 읽는다:

1. `CLAUDE.md` — 현재 작업과 잔존 부채
2. `SKILL.md` — 에이전트 매뉴얼 및 Linux/Docker 개발 팁
3. `docs/architecture.md` — 전체 시스템 아키텍처 및 ETL 데이터 흐름
4. `docs/decisions.md` — ADR-1 ~ ADR-26
5. `docs/tasks.md` — T-NNN 백로그

## 지시 우선순위

1. 사용자 요청
2. 이 `AGENTS.md`
3. `SKILL.md`
4. `docs/architecture.md`, `docs/decisions.md`
5. `docs/tasks.md`, `docs/journal.md`, `README.md`
6. 기존 코드와 테스트

## 절대 하지 말 것 (DO NOT)

1. **`main` 직접 푸시 금지** — 반드시 feature 브랜치 생성 후 작업하여 Pull Request(PR)를 작성하고 머지한다.
2. **API 키 평문 커밋 금지** — Gemini API 키, VWorld 서비스 키, YouTube API 키 등은 절대로 소스코드나 설정 파일에 평문으로 커밋하지 않는다. `.env`에 보관하며 `.gitignore`를 통해 추적을 방지한다.
3. **무분별한 YouTube API 할당량 소모 금지** — YouTube Data API v3를 공식 수집 경로로 사용하되, 검색 키워드 수와 수집 주기를 제한하고 캐싱으로 중복 호출을 막는다. 비공식 검색 크롤러는 기본 설계에 넣지 않는다.
4. **Windows 네이티브 앱 실행 경로 작성 금지** — 앱 런타임/배포 환경은 Linux Docker 전용이다(ADR-23). 모든 스크립트·명령은 bash·Linux 기준으로 작성하고, PowerShell(`*.ps1`)·cmd 전용 자산이나 `process.platform === 'win32'` 류의 Windows 전용 앱 분기를 새로 만들지 않는다. Windows 사용자는 WSL2(Ubuntu) 안에서 동일한 bash/Docker 명령으로 앱을 구동한다. **예외**: E2E Playwright 테스트 하니스는 Windows 호스트에서 실행한다(ADR-23 예외). 이 예외는 테스트 하니스에 한정되며 Windows 네이티브 앱 실행 경로나 `win32` 앱 분기를 되살리지 않는다.
5. **데이터베이스 마이그레이션 누락 금지** — SQLAlchemy 2.0 스키마를 수정할 때 PostgreSQL/PostGIS schema와 Alembic migration을 함께 갱신해야 한다.
6. **RustFS 객체 자동 삭제 금지** — 원본 동영상, 자막, 전사 결과, 대표 프레임은 무기한 보존한다. DB 논리 삭제, 매칭 실패, 영상 제외 처리만으로 RustFS 객체를 삭제하지 않는다.
7. **매칭 실패 장소 자동 확정 금지** — 지오코딩 결과가 없거나 모호한 장소는 `needs_review` 후보로 남기고, 웹 UI 또는 MCP 검수 도구에서 사용자가 확정하도록 한다.
8. **PowerShell/cmd 직접 작업 금지** — 에이전트/Codex는 `git` 명령과 Windows Playwright E2E를 제외한 작업 명령을 PowerShell/cmd에서 직접 실행하지 않는다. `gh`, Docker, Python, Node.js, 테스트, 빌드, 파일 검색·확인 명령은 WSL2(Ubuntu) bash에서 실행한다.

## 작업 후 체크리스트

- [ ] 백엔드 파이썬 코드 스타일 및 린트 검사 통과
- [ ] 프론트엔드 TypeScript 빌드 및 타입 검사 통과
- [ ] Playwright E2E 테스트 (`npx playwright test`, **Windows 호스트**) 통과
- [ ] `docs/journal.md`에 작업 항목 추가 (역시간순)
- [ ] `docs/tasks.md`의 T-NNN 상태 갱신
- [ ] 의사결정이 있었다면 `docs/decisions.md`에 ADR 추가
- [ ] 사용자 가시 변경이면 `CHANGELOG.md` 갱신 (배포 시)

## 검증

앱 런타임/배포 환경은 Linux Docker 전용이다. Windows 사용자는 WSL2(Ubuntu) 안에서 아래 bash 명령으로 앱·백엔드·프론트엔드를 구동·검증한다. 에이전트/Codex 실행 명령도 `git`과 Windows Playwright E2E를 제외하면 WSL에서만 수행한다. **E2E Playwright만 Windows 호스트에서 실행한다**(ADR-23 예외).

```bash
# --- Linux / WSL2 (앱 런타임·백엔드·프론트엔드) ---
# 단일 호스트 Docker Compose 통합 검증 (기본 실행 계약, ADR-18)
docker compose up --build       # host API 12601 / MCP 12602 / Web 12605 / RustFS 12101·12105
# 또는 smoke 검증 스크립트
bash scripts/verify-docker-compose.sh

# 백엔드 의존성 및 테스트 (컨테이너 밖 로컬 개발, Linux/WSL)
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pytest

# 프론트엔드 빌드 검사
cd ../frontend
npm ci
npm run build
```

```powershell
# --- Windows 호스트 (E2E Playwright 하니스, ADR-23 예외) ---
cd tests
npm install
npx playwright install
npx playwright test
```
