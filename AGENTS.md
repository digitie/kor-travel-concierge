# AGENTS.md

## 문서 언어 정책

이 저장소의 **모든 Markdown 문서는 한글로 작성한다**. 예외 없음. `README.md`, `CLAUDE.md`, `SKILL.md`도 본문은 한글이다.

다음 항목만 영어를 유지한다 — 한글로 옮기면 의미가 변하거나 정확성이 깨지기 때문:

- **코드 식별자**: 함수/타입/prop/이벤트/모듈 이름 (`useVWorldMap`, `TravelDestination`, `GeminiEngineSettings`, `'use client'`).
- **명령어와 경로**: `npm run dev`, `poetry run uvicorn`, `F:\dev\tripmate-agent\frontend`, `pytest`.
- **외부 공식 용어**: Next.js, React, FastAPI, SQLAlchemy, SQLite3, SpatiaLite, RustFS, Playwright, MapLibre GL JS, WMTS, REST API, Gemini API, ETL.
- **벤더/제품명**: Google, Kakao, Naver, VWorld, YouTube, OpenAI.
- **표준 keyword**: ADR, CHANGELOG, ISO 8601 날짜, semver 라벨(`Added`/`Changed`/`Removed`/`Fixed`/`Security`).
- **shell 출력 / 로그 예시**: 그대로 캡처한 문자열은 보존.

설명 문장, 절제목, 표 column 헤더, ADR 본문, 빠른 시작 가이드, 일지 항목은 한글로 적는다. 새 문서를 만들 때 영문 초안을 두지 않는다 — 처음부터 한글로 쓴다.

## 역할

이 저장소(GitHub 저장소 이름 `tripmate-agent`)는 Gemini를 활용하여 YouTube의 여행 컨텐츠를 검색, 분석, 요약하고 정리하여 여행지 데이터를 구축하는 **지능형 여행 비서 애플리케이션**이다. 시스템은 다음 네 부분으로 구성된다:
1. **Next.js & React 프론트엔드**: 수집된 데이터 조회, 검색 키워드 및 유튜버 CRUD, VWorld 지도 기반 위치 매핑, Gemini Deep Research 실행 및 설정 화면.
2. **MCP 서버 UX**: AI 에이전트가 여행 데이터베이스를 조회하고 키워드/유튜버 CRUD, 보정, 병합, ETL 실행 트리거를 수행하는 읽기/쓰기 도구 표면.
3. **FastAPI & SQLAlchemy 2.0 백엔드**: `aiosqlite`와 SQLite + SpatiaLite 데이터베이스를 기반으로 비동기 API 엔드포인트 및 도메인 로직 서빙.
4. **ETL 파이프라인**: 공식 YouTube Data API v3 검색 및 업데이트 탐색 → 자막/전사/Gemini 활용 영상 정리 및 POI 추출 → 대표 프레임 추출 및 원본 동영상·자막·전사 결과·대표 프레임 RustFS 저장 → 외부 REST API 연동 주소 보정 작업 수행.

## 식별자 (혼동 방지)

| 항목 | 값 |
|------|----|
| GitHub 저장소 이름 | `tripmate-agent` |
| 프론트엔드 프레임워크 | Next.js (React 기반) |
| 백엔드 프레임워크 | FastAPI (Python 기반) |
| ORM / 데이터베이스 | SQLAlchemy 2.0 / SQLite + SpatiaLite (`aiosqlite`) |
| 지도 뷰 라이브러리 | `maplibre-gl + VWorld WMTS` |
| E2E 테스트 도구 | Playwright (Windows 구동) |
| LLM API | Gemini API (1.5 / 2.0 / Flash 등 설정 가능) |
| MCP UX | 읽기/쓰기 모두 가능한 MCP 서버 |
| Geocoding / Reverse Geocoding | VWorld 최우선(`python-vworld-api`의 `AsyncVworldClient` 직접 사용), Kakao Local 주소·키워드 장소 검색 보조, Naver 보조 검증 (`kraddr-geo` 연계 없음) |
| YouTube 수집 | 공식 YouTube Data API v3 우선, 비공식 의존은 자막/프레임 구간으로 격리 |
| 미디어 저장소 | 별도 로컬 Docker RustFS 서비스, 원본 동영상·자막·전사 결과·대표 프레임 무기한 보존 |
| 스케줄러 | APScheduler 단일 실행자 |
| 프론트엔드 폼/상태 | React Hook Form / Zod / shadcn/ui / Tailwind CSS / TanStack Query |

## 개발 환경 정책

PC 개발 및 평가는 **Windows 호스트**에서 직접 진행한다. 
- **Python 환경**: 가상환경(`.venv`)을 생성하여 Python 3.10+ 기반으로 FastAPI, SQLAlchemy, `aiosqlite`, SpatiaLite, ETL 스크립트를 구동한다.
- **Node.js 환경**: Node.js 20+ 버전을 사용하며, frontend 폴더 내에서 Next.js를 구동한다.
- **Playwright 구동**: Windows 환경에 맞게 브라우저 바이너리를 설치하고 Headless/Headed 모드로 E2E 테스트를 수행한다.
- **RustFS 환경**: 원본 동영상, 자막, 전사 결과, 대표 프레임은 별도 로컬 Docker RustFS 서비스에 저장하고 자동 만료 정책을 두지 않는다.
- **API 키 관리**: VWorld, Gemini, YouTube, Kakao, Naver, RustFS 등 외부 API 키와 접근 키는 절대 코드에 하드코딩하지 않고 `.env` 파일로 주입하며 로그 출력 시 마스킹 처리한다.

작업 전에 반드시 다음을 읽는다:

1. `CLAUDE.md` — 현재 작업과 잔존 부채
2. `SKILL.md` — 에이전트 매뉴얼 및 Windows 개발 팁
3. `docs/architecture.md` — 전체 시스템 아키텍처 및 ETL 데이터 흐름
4. `docs/decisions.md` — ADR-1 ~ ADR-19
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
4. **Windows 비호환 명령어 작성 금지** — 호스트 운영체제가 Windows이므로, bash 전용 명령어(예: `&&` 결합문, `export VAR=val`, `/tmp` 경로 등) 대신 PowerShell/cmd 호환 명령어나 크로스 플랫폼 스크립트를 작성한다.
5. **데이터베이스 마이그레이션 누락 금지** — SQLAlchemy 2.0 스키마를 수정할 때 SQLite + SpatiaLite 테이블 구조와 모순이 생기지 않도록 마이그레이션 도구(Alembic 등) 또는 스키마 초기화 스크립트를 동기화해야 한다.
6. **RustFS 객체 자동 삭제 금지** — 원본 동영상, 자막, 전사 결과, 대표 프레임은 무기한 보존한다. DB 논리 삭제, 매칭 실패, 영상 제외 처리만으로 RustFS 객체를 삭제하지 않는다.
7. **매칭 실패 장소 자동 확정 금지** — 지오코딩 결과가 없거나 모호한 장소는 `needs_review` 후보로 남기고, 웹 UI 또는 MCP 검수 도구에서 사용자가 확정하도록 한다.

## 작업 후 체크리스트

- [ ] 백엔드 파이썬 코드 스타일 및 린트 검사 통과
- [ ] 프론트엔드 TypeScript 빌드 및 타입 검사 통과
- [ ] Windows Playwright E2E 테스트 (`npx playwright test`) 통과
- [ ] `docs/journal.md`에 작업 항목 추가 (역시간순)
- [ ] `docs/tasks.md`의 T-NNN 상태 갱신
- [ ] 의사결정이 있었다면 `docs/decisions.md`에 ADR 추가
- [ ] 사용자 가시 변경이면 `CHANGELOG.md` 갱신 (배포 시)

## 검증

```powershell
# 백엔드 의존성 및 린트 검사 (Windows PowerShell)
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
pytest

# 프론트엔드 빌드 검사
cd ..\frontend
npm ci
npm run build

# E2E 테스트 실행
cd ..\tests
npm ci
npx playwright install
npx playwright test
```
