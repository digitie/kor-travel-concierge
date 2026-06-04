# TASKS — 백로그

작업 항목은 `T-NNN` 형식의 ID로 관리한다. 새 작업은 "대기"의 우선순위 순서대로 들어가고, 진행 중이 되면 담당자를 표시한다. 완료된 작업은 "완료" 섹션 상단에 누적한다.

---

## 진행 중

- **T-002**: 프로젝트 `docs/` 디렉토리 문서 자산 생성 및 상세 기획서 반영
  - `architecture.md`, `decisions.md`, `tasks.md`, `journal.md`, `dev-environment.md` 작성
  - 상세 기획서의 검색 우선순위, 자막 폴백, 프레임 추출, 지오코딩 캐시, 작업 복원력 요구사항 반영
  - 웹 UX 외에 MCP 서버 읽기/쓰기 UX를 개발 계획에 반영
  - `kraddr-geo` 연계 취소 사항을 지오코딩 계획에 명시
  - 담당: Codex

---

## 대기 (우선순위 순)

- **T-003**: 기본 프로젝트 디렉토리 뼈대 및 구성 파일 생성
  - `frontend/`, `backend/`, `etl/`, `tests/`, `mcp/` 디렉토리 생성
  - `package.json`, `requirements.txt`, `playwright.config.ts`, 기본 Next.js 설정 배치
  - MCP 서버 엔트리포인트와 FastAPI 도메인 서비스 재사용 구조 초안 배치

- **T-004**: FastAPI API 백엔드 구축 (FastAPI + SQLAlchemy 2.0)
  - SQLite3 데이터베이스 연동 및 SQLAlchemy 모델 정의
  - `search_keywords`, `subscribed_youtubers`, `youtube_videos`, `travel_destinations`, `video_destination_mappings`, `etl_jobs`, `system_settings`, `audit_logs` 모델 작성
  - 키워드 CRUD, 유튜버 CRUD, 여행지 목록 조회, Deep Research 트리거용 REST API 구현
  - 쓰기 API는 Pydantic 검증, 멱등 처리, 감사 로그 기록을 기본으로 구현

- **T-005**: Next.js 프론트엔드 및 `maplibre-vworld-js` 연동
  - Tailwind CSS 또는 Custom CSS 기반의 모던 UI 구현
  - 리스트 뷰와 지도 뷰 통합 레이아웃 작성
  - 키워드 관리, 유튜버 관리, 재생목록 관리, Gemini 엔진 설정, 지오코딩 공급자 설정 화면 작성
  - Deep Research 트리거 및 작업 상태 조회 UI 작성
  - ETL 실패 작업, API 쿼터, MCP 쓰기 로그를 확인하는 운영 패널 추가

- **T-006**: 1단계 ETL 수집 파이프라인 구현
  - Gemini 기반 검색 키워드 확장 및 `season_context` 저장
  - YouTube Data API 최소 호출 정책 적용
  - `yt-dlp` 기반 `skip_download`, `extract_flat` 메타데이터 수집 래퍼 작성
  - 채널, 재생목록, 일반 검색 결과의 우선순위 점수 산정
  - 기존 `video_id` 캐시 확인 후 신규 영상만 큐에 적재

- **T-007**: 2단계 자막 전사 및 Gemini POI 추출 구현
  - `youtube-transcript-api` → `yt-dlp` 자막 추출 → `faster-whisper` 순서의 3단계 전사 폴백 구현
  - Gemini JSON Schema 기반 프롬프트로 장소명, 위치 단서, 설명, 시작/종료 타임스탬프 추출
  - 파싱 실패, 토큰 초과, 빈 결과에 대한 재시도 및 실패 기록 처리

- **T-008**: 3단계 대표 프레임 추출 구현
  - POI 시작 타임스탬프에 5~10초 오프셋 적용
  - `yt-dlp` 직접 스트림 URL 확보
  - FFmpeg Input Seeking 방식으로 JPEG 대표 프레임 추출
  - 초기에는 로컬 경로 저장, 추후 객체 스토리지 전환 가능하도록 저장소 인터페이스 작성

- **T-009**: 4단계 지오코딩, 역지오코딩, 중복 병합 구현
  - 내부 DB 캐시 우선 조회로 외부 API 쿼터 방어
  - Kakao Local API 1차 지오코딩, Naver API 2차 보강 구현
  - VWorld API 기반 좌표 → 행정/도로명 주소 역지오코딩 구현
  - `pyproj`와 `always_xy=True`로 WGS84(EPSG:4326) 정규화
  - 429 응답에 지수 백오프와 지터 적용
  - `kraddr-geo` 연계는 구현하지 않음

- **T-010**: MCP 서버 읽기/쓰기 UX 구현
  - 여행지 검색, 여행지 상세 조회, 영상별 장소 조회, ETL 상태 조회 읽기 도구 작성
  - 키워드, 유튜버, 재생목록 CRUD 쓰기 도구 작성
  - 지오코딩 재시도, Deep Research 트리거, 여행지 보정, 중복 병합 쓰기 도구 작성
  - 모든 쓰기 도구에 스키마 검증, 멱등 키, 감사 로그, 실패 상태 기록 적용

- **T-011**: 스케줄링 및 작업 복원력 구현
  - `etl_jobs` 상태 모델과 heartbeat 갱신 구현
  - stale `running` 작업 재투입 로직 구현
  - 채널별 마지막 크롤 워터마크 및 적응형 크롤 주기 구현
  - 초기에는 SQLite3 기반 상태 테이블로 구현하고, 다중 워커 필요 시 PostgreSQL Advisory Lock 또는 PgQueuer 검토

- **T-012**: Gemini Deep Research 백그라운드 태스크 구현
  - 특정 여행지 세부 정보의 심층 조사 및 DB 업데이트 로직 작성
  - 웹 UI와 MCP 쓰기 도구에서 동일한 작업 생성 API를 사용하도록 구성
  - 작업 결과를 여행지 상세 설명, 추천 포인트, 주의사항, 관련 영상 근거로 분리 저장

- **T-013**: Windows Playwright E2E 통합 테스트 검증
  - Next.js, FastAPI, SQLite3, ETL 상태가 연결된 상태에서 E2E 시나리오 실행
  - 지도 렌더링, CRUD, Deep Research 트리거, 작업 상태 표시 검증
  - MCP 쓰기 도구가 생성한 변경사항이 웹 UI에 반영되는 경로 검증

- **T-014**: 공간 데이터 고도화 및 PostGIS 전환 검토
  - SQLite3 기반 좌표 근접성 중복 병합 한계 측정
  - 반경 검색, 클러스터링, 주변 추천 요구가 커질 경우 PostgreSQL/PostGIS 전환 ADR 작성
  - `ST_DWithin`, GiST 인덱스, geography 캐스팅 기반 마이그레이션 초안 작성

- **T-015**: 의미론적 검색 및 추천 고도화 검토
  - Gemini 요약과 장소 메타데이터 임베딩 저장 전략 검토
  - 자연어 검색, 여행 취향 기반 추천, 계절/상황 기반 추천 UX 초안 작성

- **T-016**: 프로젝트 배포 및 Windows 환경 동작 최종 평가
  - Windows PowerShell 기준 백엔드, 프론트엔드, ETL, MCP 서버 구동 검증
  - `.env.example`, 개발 환경 문서, 운영 체크리스트 최종 동기화

---

## 완료

- [x] **T-001**: 프로젝트 루트 문서 자산 생성 — `README.md`, `AGENTS.md`, `CLAUDE.md`, `SKILL.md`, `.env.example` 작성 완료. (2026-06-03)

---

## 사양 참조

- 아키텍처 세부: `docs/architecture.md`
- 결정 기록: `docs/decisions.md`
- 작업 일지: `docs/journal.md`
- 개발 환경: `docs/dev-environment.md`
