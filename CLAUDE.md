# CLAUDE.md — 프로젝트 컨텍스트

이 파일은 에이전트가 매 세션 시작 시 자동으로 읽어 현재 프로젝트 상태와 연속성을 파악하는 진입점이다.
프로젝트 규칙은 `AGENTS.md`에, 개발 환경 상세 팁은 `SKILL.md`에 정의한다.

## 프로젝트 현황 (2026-06-05)

Gemini API 기반의 YouTube 여행 컨텐츠 검색, 정리, VWorld 지도 시각화, MCP 읽기/쓰기 도구 UX를 함께 제공하는 `tripmate-agent` 개발 초기 단계이다. 최신 기준 문서는 Google Docs `AI유튜브여행_소형프로젝트_SpatiaLite_명세서`와 후속 RustFS 미디어 저장 요구사항이며, 1~2인 운영 기준 소형 프로젝트로 설계를 경량화한다.

### 현재 작업

- **T-014 완료**: 단일 호스트 Docker Compose 구성, RustFS host/container endpoint 분리, MCP `streamable-http`, API health 기반 시작 순서, RustFS 버킷/객체 smoke 검증 스크립트를 정비하고 실제 Compose smoke를 완료.
- **T-021 완료**: VWorld 우선 지오코딩과 `python-vworld-api` `AsyncVworldClient` 직접 사용, Kakao 공식 키워드 장소 검색 fallback, wrapper 최소화 정책을 코드와 문서에 반영.
- **T-015 완료**: Playwright가 backend `127.0.0.1:18080`과 frontend `127.0.0.1:13100`을 자동 기동하고, 테스트 전용 SQLite DB를 시드해 메인 화면, 수집 시작, Deep Research, 검수 후보 보정, 설정 저장을 브라우저에서 검증한다.
- **T-016 완료**: sqlite-vec / SQLite Vec1, PostgreSQL/PostGIS, PgQueuer, APScheduler + PostgreSQL advisory lock 후보를 검토하고 ADR-20에 “선제 도입 보류, 수치 트리거 기반 전환”으로 정리.
- **다음 착수 대상**: T-020 Next.js 메이저 업그레이드 및 npm audit 대응 검토.
- **지오코딩 결정**: 최신 요청에 따라 `kraddr-geo` 연계는 취소한다. VWorld를 최우선으로 사용하며 `python-vworld-api`의 `AsyncVworldClient`를 직접 호출하고, Kakao는 주소 검색 후 공식 키워드 장소 검색 fallback, Naver는 보조 검증으로 둔다.
- **YouTube 수집 결정**: 소형 프로젝트 기준 공식 YouTube Data API v3를 기본 수집 경로로 사용하고, 비공식 의존은 자막/프레임 구간으로 격리.
- **미디어 저장 결정**: 원본 동영상, 자막, 전사 결과, 대표 프레임은 별도 로컬 Docker RustFS 서비스에 저장하고 무기한 보존한다.
- **데이터 품질 결정**: 매칭 실패 장소는 자동 확정하지 않고 웹 UI/MCP 검수 큐에서 사용자가 보정한다. 영상 설명 원문, Gemini 보정 설명, Gemini 장소 보강 설명은 별도 필드로 저장한다.
- **계층화 원칙**: 외부 API SDK를 숨기는 내부 adapter/wrapper는 새로 만들지 않거나 최소화한다. 필요한 경우에도 응답 dict를 내부 모델로 바꾸는 좁은 변환 함수 수준에 머문다.

### 잔존 기술 부채

- `npm audit`이 Next 14 계열 보안 이슈를 보고했으나 자동 수정은 Next 16 major upgrade를 요구한다. T-020에서 별도 검토한다.
- sqlite-vec, PostgreSQL/PostGIS 전환, 멀티 워커 큐 전환은 ADR-20 기준의 실제 규모 신호가 생길 때 별도 ADR로 재검토한다.

### 브랜치 상태

- `main` 직접 푸시는 금지한다. 모든 변경은 작업별 `codex/*` 브랜치에서 커밋하고 PR 생성 후 머지한다.

## 로컬 개발 환경 레이아웃

```
F:\dev\tripmate-agent\
├── frontend/             # Next.js App Router 프론트엔드 (Port: 3000)
│   ├── src/
│   │   ├── app/          # 페이지 컴포넌트 (설정, 리스트, 지도뷰 등)
│   │   ├── components/   # 재사용 UI (maplibre-gl + VWorld WMTS 지도 포함)
│   │   └── utils/
│   ├── package.json
│   └── tsconfig.json
├── backend/              # FastAPI 비동기 API 백엔드 (Port: 8000)
│   ├── app/
│   │   ├── api/          # API 라우터 (키워드 CRUD, 유튜버 CRUD 등)
│   │   ├── core/         # DB 세션 및 공통 설정
│   │   ├── etl/          # 수집·요약·지오코딩·대표 프레임 추출 파이프라인
│   │   ├── models/       # SQLAlchemy 2.0 모델 (SQLite + SpatiaLite)
│   │   └── services/     # 도메인 서비스 및 RustFS 저장 계층
│   ├── requirements.txt
│   └── main.py
├── etl/                  # 비동기 ETL 파이프라인 스크립트
│   ├── search.py         # 1단계: 키워드 조합 YouTube 검색 (Gemini 보정)
│   ├── summarize.py      # 2단계: 신규 영상 요약 정리 및 설명 보정 (Gemini API)
│   ├── geocode.py        # VWorld 우선, Kakao/Naver 보조 지오코딩 및 역지오코딩
│   ├── media.py          # RustFS 원본 동영상/자막/전사 결과/프레임 저장
│   └── runner.py         # ETL 통합 실행기 (스케줄러/CLI)
├── scheduler/            # APScheduler 단일 실행자 (계획)
│   └── worker.py         # crawl_runs pending 작업 claim 및 실행
├── mcp/                  # Docker Compose 호환 MCP 실행 래퍼
│   └── server.py         # tripmate_mcp.server 호출
├── tripmate_mcp/         # MCP 서버 읽기/쓰기 도구 UX 구현
│   ├── server.py         # FastMCP 서버 생성 및 도구 등록
│   └── tools.py          # 여행지 조회, 보정, 병합, ETL 트리거 도구
├── tests/                # Windows Playwright E2E 테스트 환경
│   ├── e2e/
│   ├── scripts/          # E2E backend/frontend 기동 및 DB 시드 스크립트
│   ├── playwright.config.ts
│   └── package.json
└── docs/                 # 아키텍처 및 이력 관리 문서
    ├── architecture.md   # 전체 시스템 흐름도
    ├── decisions.md      # ADR 기록 (ADR-1 ~ ADR-20)
    ├── tasks.md          # 백로그 추적
    ├── journal.md        # 일지 기록
    └── dev-environment.md# Windows 개발 환경 구축 가이드
```

## 빠른 검증 및 실행 명령

### 백엔드 (FastAPI)
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python main.py  # 8000 포트 구동
```

### 프론트엔드 (Next.js)
```powershell
cd frontend
npm install
npm run dev     # 3000 포트 구동
```

### ETL 실행
```powershell
cd etl
python runner.py
```

### E2E 테스트 (Playwright)
```powershell
cd tests
npm install
npx playwright install
npx playwright test
```
Playwright 설정은 backend `127.0.0.1:18080`, frontend `127.0.0.1:13100`을 자동 기동하고 `tests\.tmp\e2e.db`를 테스트마다 재시드한다.

## 주요 결정 사항 (ADR Index)

- **ADR-1**: Next.js (React) 기반의 프론트엔드 및 App Router 채택
- **ADR-2**: FastAPI 및 SQLAlchemy 2.0 백엔드 스택 선정 (DB 세부는 ADR-12로 보강)
- **ADR-3**: Gemini API를 이용한 YouTube 검색어 세분화 및 여행지 정보 지능형 요약
- **ADR-4**: VWorld 지도 시뮬레이션 및 로컬 `.env` 테스트 (T-013 기준 `maplibre-gl` 직접 WMTS 구성으로 보정)
- **ADR-5**: YouTube API의 엄격한 할당량 극복을 위한 스크래핑 우회 및 DB 캐싱 전략 (ADR-11로 대체)
- **ADR-6**: Windows 로컬 개발 환경 전용 Playwright E2E 검증 절차 확립
- **ADR-7**: MCP 서버를 읽기/쓰기 UX로 채택
- **ADR-8**: Kakao/Naver/VWorld 지오코딩 공급자 전략 및 `kraddr-geo` 제외
- **ADR-9**: `yt-dlp`, 자막 폴백, 작업 상태 추적 기반 ETL 복원력 보강
- **ADR-10**: SQLite3 우선 구현과 PostGIS 전환 유보 (ADR-12로 대체)
- **ADR-11**: 소형 프로젝트 기준 공식 YouTube Data API 우선
- **ADR-12**: SQLite + SpatiaLite 임베디드 공간 DB 채택
- **ADR-13**: 전면 asyncio와 APScheduler 단일 실행자 채택
- **ADR-14**: React Hook Form, Zod, shadcn/ui, Tailwind CSS, TanStack Query 프론트 스택 채택
- **ADR-15**: RustFS 기반 원본 미디어 저장과 무기한 보존
- **ADR-16**: 장소 매칭 검수 UX와 Gemini 설명 보정 필드 분리
- **ADR-17**: 공간 컬럼은 ORM 밖 SpatiaLite DDL로 관리하고 저장소 계층에 캡슐화
- **ADR-18**: 단일 호스트 Docker Compose 실행 계약
- **ADR-19**: VWorld 우선 지오코딩과 `python-vworld-api` 직접 사용
- **ADR-20**: 고도화 후보 도입 보류와 전환 트리거

상세는 `docs/decisions.md`를 참고한다.

## 작업 후 의무사항

1. `docs/journal.md`에 작업 내용 추가 (역시간순)
2. `docs/tasks.md`의 현재 작업 진행 사항 업데이트
3. 추가 의사결정이 필요하거나 발생한 경우 `docs/decisions.md`에 ADR 문서 업데이트
4. PR 생성 및 머지 흐름 준수
