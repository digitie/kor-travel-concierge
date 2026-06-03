# TASKS — 백로그

작업 항목은 `T-NNN` 형식의 ID로 관리한다. 새 작업은 "대기"의 우선순위 순서대로 들어가고, 진행 중이 되면 담당자를 표시한다. 완료된 작업은 "완료" 섹션 상단에 누적한다.

---

## 진행 중

- **T-002**: 프로젝트 `docs/` 디렉토리 문서 자산 생성 — `architecture.md`, `decisions.md`, `tasks.md`, `journal.md`, `dev-environment.md` 작성 중. (담당: Antigravity 2.0)

---

## 대기 (우선순위 순)

- **T-003**: 기본 프로젝트 디렉토리 뼈대 및 구성 파일 생성
  - `frontend/`, `backend/`, `etl/`, `tests/` 디렉토리 생성
  - `package.json`, `requirements.txt`, `playwright.config.ts`, `vite` 혹은 `next` 기본 설정 배치
- **T-004**: FastAPI API 백엔드 구축 (FastAPI + SQLAlchemy 2.0)
  - SQLite3 데이터베이스 연동 및 SQLAlchemy 모델 정의 (`search_keywords`, `subscribed_youtubers`, `video_cache`, `travel_destinations`, `system_settings`)
  - 키워드 CRUD, 유튜버 CRUD, 여행지 목록 조회 및 Deep Research 트리거용 API 엔드포인트 구현
- **T-005**: Next.js 프론트엔드 및 maplibre-vworld-js 연동
  - Tailwind CSS 혹은 수려한 테마를 갖춘 모던 Custom CSS UI 구현
  - 리스트 뷰 & 지도 뷰 통합 레이아웃 작성 (VWorld 지도 연동)
  - 키워드 관리 화면, 유튜버 관리 화면, Deep Research 상세 조사 트리거 동작 엮기
  - Gemini 엔진 설정 기능 탑재
- **T-006**: 3단계 ETL 파이프라인 구현 (`etl/` 디렉토리)
  - 1단계: 키워드 조합 및 Gemini 검색어 보정, YouTube 탐색
  - 2단계: 유튜브 내용 요약/정리 및 DB 저장 (Gemini API)
  - 3단계: Kakao Local / Naver Maps REST API 연동 위치 보정 및 소개 보완
  - YouTube API 최소화용 비공식 스크래핑/파싱 라이브러리 및 DB 중복 캐싱 결합
- **T-007**: Gemini Deep Research 백그라운드 태스크 구현
  - 특정 여행지 세부 정보의 지능형 심층 조사 및 DB 업데이트 로직
- **T-008**: Windows Playwright E2E 통합 테스트 검증
  - Next.js ↔ FastAPI ↔ DB 통합 상태에서 Playwright E2E 시나리오 실행 및 Windows 환경 검증
- **T-009**: 프로젝트 배포 및 Windows 환경 동작 최종 평가

---

## 완료

- [x] **T-001**: 프로젝트 루트 문서 자산 생성 — `README.md`, `AGENTS.md`, `CLAUDE.md`, `SKILL.md`, `.env.example` 작성 완료. (2026-06-03)

---

## 사양 참조
- 아키텍처 세부: `docs/architecture.md`
- 결정 기록: `docs/decisions.md`
- 작업 일지: `docs/journal.md`
- 개발 환경: `docs/dev-environment.md`
