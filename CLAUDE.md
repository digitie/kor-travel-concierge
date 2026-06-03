# CLAUDE.md — 프로젝트 컨텍스트

이 파일은 에이전트가 매 세션 시작 시 자동으로 읽어 현재 프로젝트 상태와 연속성을 파악하는 진입점이다.
프로젝트 규칙은 `AGENTS.md`에, 개발 환경 상세 팁은 `SKILL.md`에 정의한다.

## 프로젝트 현황 (2026-06-03)

Gemini API 기반의 YouTube 여행 컨텐츠 검색, 정리 및 VWorld 지도 시각화 웹 애플리케이션 `tripmate-agent` 개발 초기 단계이다. 현재는 프로젝트의 디렉토리 구조 부트스트랩 및 `maplibre-vworld-js` 스타일의 마크다운 문서 자산 작성을 승인받아 진행 중이다.

### 현재 작업

- **T-001/T-002/T-003**: 기본 마크다운 문서 작성 및 프로젝트 뼈대 디렉토리(frontend, backend, etl, tests) 및 설정 파일 생성.

### 잔존 기술 부채

- 프로젝트 신규 생성 단계로 부채 없음.

### 브랜치 상태

- `main` 브랜치 최초 커밋 후, `feature/project-bootstrap` 브랜치를 생성하여 문서작업 및 디렉토리 구조 구축을 수행 중. 완료 후 PR 생성 및 머지 예정.

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
├── backend/              # FastAPI API 백엔드 (Port: 8000)
│   ├── app/
│   │   ├── api/          # API 라우터 (키워드 CRUD, 유튜버 CRUD 등)
│   │   ├── core/         # DB 세션 및 공통 설정
│   │   └── models/       # SQLAlchemy 2.0 모델 (SQLite3)
│   ├── requirements.txt
│   └── main.py
├── etl/                  # 비동기 ETL 파이프라인 스크립트
│   ├── search.py         # 1단계: 키워드 조합 YouTube 검색 (Gemini 보정)
│   ├── summarize.py      # 2단계: 신규 영상 요약 정리 (Gemini API)
│   ├── geocode.py        # 3단계: 외부 REST API 기반 주소 보정
│   └── runner.py         # ETL 통합 실행기 (스케줄러/CLI)
├── tests/                # Windows Playwright E2E 테스트 환경
│   ├── e2e/
│   ├── playwright.config.ts
│   └── package.json
└── docs/                 # 아키텍처 및 이력 관리 문서
    ├── architecture.md   # 전체 시스템 흐름도
    ├── decisions.md      # ADR 기록 (ADR-1 ~ ADR-6)
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
- **ADR-2**: FastAPI 및 SQLAlchemy 2.0 (SQLite3) 백엔드 스택 선정
- **ADR-3**: Gemini API를 이용한 YouTube 검색어 세분화 및 여행지 정보 지능형 요약
- **ADR-4**: `maplibre-vworld-js` 라이브러리를 사용한 지도 시뮬레이션 및 로컬 `.env` 테스트
- **ADR-5**: YouTube API의 엄격한 할당량 극복을 위한 스크래핑 우회 및 DB 캐싱 전략
- **ADR-6**: Windows 로컬 개발 환경 전용 Playwright E2E 검증 절차 확립

상세는 `docs/decisions.md`를 참고한다.

## 작업 후 의무사항

1. `docs/journal.md`에 작업 내용 추가 (역시간순)
2. `docs/tasks.md`의 현재 작업 진행 사항 업데이트
3. 추가 의사결정이 필요하거나 발생한 경우 `docs/decisions.md`에 ADR 문서 업데이트
4. PR 생성 및 머지 흐름 준수
