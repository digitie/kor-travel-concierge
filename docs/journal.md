# JOURNAL — 작업 일지

본 문서는 `tripmate-agent` 프로젝트의 작업 진행 역사를 역시간순으로 기록한다.

---

## 2026-06-05: Google Docs 소형 프로젝트 SpatiaLite 명세 반영

- **담당자**: Codex
- **작업 내용**:
  - Google Docs `AI유튜브여행_소형프로젝트_SpatiaLite_명세서` 내용을 확인하고 로컬 문서 계획을 최신 기준으로 재정렬.
  - 기존 문서의 대규모 지향 설계와 충돌하는 항목을 보완:
    - 비공식 검색/스크래퍼 중심 표현을 공식 YouTube Data API v3 우선 전략으로 교체.
    - 단순 SQLite3 표현을 SQLite + SpatiaLite 임베디드 공간 DB 기준으로 보강.
    - 장시간 작업 실행 주체를 API/MCP가 아니라 APScheduler 단일 실행자로 명확화.
    - `etl_jobs` 중심 표현을 Web REST, MCP, scheduler가 공유하는 `crawl_runs` 작업 테이블로 정리.
    - 프론트엔드 스택에 React Hook Form, Zod, shadcn/ui, Tailwind CSS, TanStack Query를 반영.
    - Zustand는 초기 범위에서 보류하는 것으로 정리.
  - `docs/decisions.md`에서 ADR-5와 ADR-10을 superseded 처리하고 ADR-11 ~ ADR-14를 추가.
  - `docs/tasks.md`를 T-003 이후 실제 구현 순서에 맞게 재정렬.
- **다음 작업**:
  - T-003: 소형 프로젝트 기준 스캐폴딩, Docker Compose, SpatiaLite 환경 변수, scheduler 디렉토리 구조 정비.

---

## 2026-06-04: 상세 기획서 반영 및 MCP UX 계획 추가

- **담당자**: Codex
- **작업 내용**:
  - `G:\My Drive\tripmate\AI유튜브여행_상세기획서.docx`의 핵심 설계 요소를 현재 개발 계획에 반영.
  - 상세 기획서의 다음 항목을 백로그와 아키텍처에 승격:
    - Gemini 기반 파생 키워드와 `season_context` 저장.
    - 채널, 재생목록, 일반 검색 결과의 우선순위 큐.
    - `yt-dlp` 기반 `skip_download`, `extract_flat` 수집.
    - `youtube-transcript-api` → `yt-dlp` 자막 추출 → `faster-whisper` 3단계 전사 폴백.
    - Gemini JSON Schema 기반 POI 추출.
    - FFmpeg Input Seeking 대표 프레임 추출.
    - 지오코딩 캐시, API 429 지수 백오프, 좌표계 정규화.
    - 작업 상태, heartbeat, retry_count, stale 작업 재투입.
  - 웹 UX 외에 AI 에이전트가 사용할 MCP 서버 읽기/쓰기 UX를 별도 사용자 접점으로 추가.
  - 최신 요청에 따라 `kraddr-geo` 연계는 취소하고, Kakao / Naver / VWorld 공급자 어댑터 기반 Geocoding/Reverse Geocoding으로 정리.
  - `docs/decisions.md`에 ADR-7 ~ ADR-10 추가:
    - MCP 서버 읽기/쓰기 UX 채택.
    - 지오코딩 공급자 전략 및 `kraddr-geo` 제외.
    - ETL 복원력 보강 원칙.
    - SQLite3 우선 구현과 PostGIS 전환 유보.
- **다음 작업**:
  - `frontend/`, `backend/`, `etl/`, `tests/`, `mcp/` 디렉토리 뼈대와 실제 구현 파일 생성 (T-003).

---

## 2026-06-03: 프로젝트 초기화 및 문서 시스템 정교화

- **담당자**: AI 에이전트 (Antigravity 2.0)
- **작업 내용**:
  - `tripmate-agent` 프로젝트의 기본 골격을 `maplibre-vworld-js`와 완벽히 호환되는 한글 문서 및 구조로 초기화.
  - 루트 디렉토리에 핵심 정보 파일 작성:
    - [README.md](../README.md): 프로젝트 개요, 시스템 흐름도, 퀵스타트 명령어 및 도큐먼트 링크 제공.
    - [AGENTS.md](../AGENTS.md): 한글 문서 원칙, 보존 식별자 규칙, Windows 개발 정책 및 DO NOT 룰 설정.
    - [CLAUDE.md](../CLAUDE.md): 프로젝트 개발 진척도, 디렉토리 구조도, 검증 명령어 및 아키텍처 결정 인덱스 수록.
    - [SKILL.md](../SKILL.md): 가상환경 구성, YouTube API 할당량 회피 전술 및 Playwright E2E 관련 개발 지침서.
    - [.env.example](../.env.example): 로컬 테스트용 VWorld 키, Gemini API 키, YouTube API 키 템플릿 정의.
  - `docs/` 디렉토리에 기술 명세 수립:
    - [architecture.md](architecture.md): Next.js/FastAPI/SQLite3/ETL 간 통합 아키텍처 다이어그램 및 3단계 ETL 동작도 작성.
    - [decisions.md](decisions.md): Next.js App Router(ADR-1), FastAPI + SQLAlchemy 2.0(ADR-2), Gemini 요약 파이프라인(ADR-3), VWorld 지도 통합(ADR-4), YouTube 할당량 캐싱(ADR-5), Playwright E2E(ADR-6) 의사결정 수립.
    - [tasks.md](tasks.md): 로드맵 백로그 구성 (T-001 ~ T-009).
    - [dev-environment.md](dev-environment.md): Windows 호스트 전용 Python 가상환경 구축, node_modules 설치, Playwright 브라우저 연동 매뉴얼 작성.
  - Git 초기화 및 origin 설정:
    - `main` 브랜치 최초 생성 및 `.gitignore`, `.gitattributes` 커밋 후 원격 저장소(`https://github.com/digitie/tripmate-agent`)에 푸시 완료.
    - 현재는 `feature/project-bootstrap` 기능 브랜치에서 셋업 작업 진행 중.
- **다음 작업**:
  - `frontend/`, `backend/`, `etl/`, `tests/` 각각의 뼈대 설정 파일 배치 및 디렉토리 트리 구축 (T-003).
