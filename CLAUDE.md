# CLAUDE.md — 프로젝트 컨텍스트

이 파일은 에이전트가 매 세션 시작 시 자동으로 읽어 현재 프로젝트 상태와 연속성을 파악하는 진입점이다.
프로젝트 규칙은 `AGENTS.md`에, 개발 환경 상세 팁은 `SKILL.md`에 정의한다.

## 프로젝트 현황 (2026-06-05)

Gemini API 기반의 YouTube 여행 컨텐츠 검색, 정리, VWorld 지도 시각화, MCP 읽기/쓰기 도구 UX를 함께 제공하는 `tripmate-agent` 개발 초기 단계이다. 최신 기준 문서는 Google Docs `AI유튜브여행_소형프로젝트_SpatiaLite_명세서`와 후속 RustFS 미디어 저장 요구사항이며, 1~2인 운영 기준 소형 프로젝트로 설계를 경량화한다.

### 현재 작업

- **T-018**: RustFS 미디어 저장, 무기한 보존, 매칭 실패 장소 검수, Gemini 설명 보정·보강 필드를 로컬 문서 계획에 반영.
- **T-003 이후**: `frontend`, `backend`, `etl`, `tests`, `mcp`, `scheduler` 디렉토리 뼈대와 실제 구현을 순차 진행.
- **지오코딩 결정**: 최신 요청에 따라 `kraddr-geo` 연계는 취소하고, Kakao / Naver / VWorld 공급자 어댑터 기반으로 정리.
- **YouTube 수집 결정**: 소형 프로젝트 기준 공식 YouTube Data API v3를 기본 수집 경로로 사용하고, 비공식 의존은 자막/프레임 구간으로 격리.
- **미디어 저장 결정**: 원본 동영상, 자막, 전사 결과, 대표 프레임은 별도 로컬 Docker RustFS 서비스에 저장하고 무기한 보존한다.
- **데이터 품질 결정**: 매칭 실패 장소는 자동 확정하지 않고 웹 UI/MCP 검수 큐에서 사용자가 보정한다. 영상 설명 원문, Gemini 보정 설명, Gemini 장소 보강 설명은 별도 필드로 저장한다.

### 잔존 기술 부채

- 아직 코드 구현 전이므로 런타임 부채는 없다.
- 현재 문서는 Google Docs 소형 프로젝트 명세와 RustFS 후속 요구사항 기준으로 정렬되었고, 실제 구현은 T-003부터 환경 변수, 디렉토리 구조, 비동기 실행 모델, RustFS 저장 계층을 코드에 반영해야 한다.

### 브랜치 상태

- `main` 직접 푸시는 금지한다. 모든 변경은 작업별 `codex/*` 브랜치에서 커밋하고 PR 생성 후 머지한다.

## 로컬 개발 환경 레이아웃

```
F:\dev\tripmate-agent\
├── frontend/             # Next.js App Router 프론트엔드 (Port: 3000)
│   ├── src/
│   │   ├── app/          # 페이지 컴포넌트 (설정, 리스트, 지도뷰 등)
│   │   ├── components/   # 재사용 UI (maplibre-vworld 지도 연동 포함)
│   │   └── utils/
│   ├── package.json
│   └── tsconfig.json
├── backend/              # FastAPI 비동기 API 백엔드 (Port: 8000)
│   ├── app/
│   │   ├── api/          # API 라우터 (키워드 CRUD, 유튜버 CRUD 등)
│   │   ├── core/         # DB 세션 및 공통 설정
│   │   ├── models/       # SQLAlchemy 2.0 모델 (SQLite + SpatiaLite)
│   │   └── services/     # 도메인 서비스 및 RustFS 저장 계층
│   ├── requirements.txt
│   └── main.py
├── etl/                  # 비동기 ETL 파이프라인 스크립트
│   ├── search.py         # 1단계: 키워드 조합 YouTube 검색 (Gemini 보정)
│   ├── summarize.py      # 2단계: 신규 영상 요약 정리 및 설명 보정 (Gemini API)
│   ├── geocode.py        # Kakao/Naver/VWorld 기반 지오코딩 및 역지오코딩
│   ├── media.py          # RustFS 원본 동영상/자막/전사 결과/프레임 저장
│   └── runner.py         # ETL 통합 실행기 (스케줄러/CLI)
├── scheduler/            # APScheduler 단일 실행자 (계획)
│   └── worker.py         # crawl_runs pending 작업 claim 및 실행
├── mcp/                  # MCP 서버 읽기/쓰기 도구 UX (계획)
│   ├── server.py         # MCP 서버 엔트리포인트
│   └── tools/            # 여행지 조회, CRUD, 보정, 병합, ETL 트리거 도구
├── tests/                # Windows Playwright E2E 테스트 환경
│   ├── e2e/
│   ├── playwright.config.ts
│   └── package.json
└── docs/                 # 아키텍처 및 이력 관리 문서
    ├── architecture.md   # 전체 시스템 흐름도
    ├── decisions.md      # ADR 기록 (ADR-1 ~ ADR-16)
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

## 주요 결정 사항 (ADR Index)

- **ADR-1**: Next.js (React) 기반의 프론트엔드 및 App Router 채택
- **ADR-2**: FastAPI 및 SQLAlchemy 2.0 백엔드 스택 선정 (DB 세부는 ADR-12로 보강)
- **ADR-3**: Gemini API를 이용한 YouTube 검색어 세분화 및 여행지 정보 지능형 요약
- **ADR-4**: `maplibre-vworld-js` 라이브러리를 사용한 지도 시뮬레이션 및 로컬 `.env` 테스트
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

상세는 `docs/decisions.md`를 참고한다.

## 작업 후 의무사항

1. `docs/journal.md`에 작업 내용 추가 (역시간순)
2. `docs/tasks.md`의 현재 작업 진행 사항 업데이트
3. 추가 의사결정이 필요하거나 발생한 경우 `docs/decisions.md`에 ADR 문서 업데이트
4. PR 생성 및 머지 흐름 준수
