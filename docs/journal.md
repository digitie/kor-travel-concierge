# JOURNAL — 작업 일지

본 문서는 `tripmate-agent` 프로젝트의 작업 진행 역사를 역시간순으로 기록한다.

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
