# TASKS — 백로그

작업 항목은 `T-NNN` 형식의 ID로 관리한다. 새 작업은 "대기"의 우선순위 순서대로 들어가고, 진행 중이 되면 담당자를 표시한다. 완료된 작업은 "완료" 섹션 상단에 누적한다.

---

## 진행 중

- 현재 진행 중인 구현 작업 없음. 다음 착수 대상은 **T-005**이다.

---

## 대기 (우선순위 순)

- **T-005**: SpatiaLite 공간 데이터 모델 구현
  - `search_keywords`, `source_targets`, `youtube_videos`, `travel_places`, `extracted_place_candidates`, `video_place_mappings`, `media_assets` 모델 작성
  - `travel_places.geom` Point(4326) 컬럼과 R-Tree 공간 인덱스 구성
  - `youtube_videos.description_raw`, `youtube_videos.description_gemini_corrected`, `travel_places.gemini_enriched_description` 필드 구현
  - 매칭 실패 후보의 `match_status`, 검수자, 검수 시각, 검수 메모 필드 구현
  - RustFS 객체 URI, 체크섬, 크기, 무기한 보존 정책을 `media_assets`에 저장
  - 좌표 근접성 기반 중복 후보 조회 함수 구현
  - PostGIS 전환을 고려해 공간 함수 호출을 저장소 계층에 캡슐화

- **T-006**: 공식 YouTube Data API v3 수집 파이프라인 구현
  - Gemini 기반 시드 키워드 → 파생 키워드 생성 및 `season_context` 저장
  - `search.list`, `playlistItems.list`, `channels.list`, `videos.list` 클라이언트 구현
  - 검색 결과를 업로드일, 키워드 유사도, 조회수 대비 참여도 기준으로 정규화
  - `video_id` 기준 멱등 처리와 채널 워터마크 저장
  - 비공식 검색 크롤러는 초기 범위에서 제외

- **T-007**: 자막·전사·Gemini POI 추출 구현
  - `youtube-transcript-api` 1차 자막 추출
  - `yt-dlp` 자막 추출 폴백
  - `faster-whisper` 로컬 전사 최종 폴백
  - 확보한 자막 파일과 전사 결과를 RustFS에 저장하고 `media_assets`에 기록
  - YouTube 영상 설명 원문 저장 및 Gemini 오탈자·문맥 보정 설명 저장
  - Gemini가 추가·보강한 장소 설명을 별도 필드에 저장
  - 블로킹 작업을 executor 또는 프로세스풀로 격리
  - Gemini JSON Schema 기반 POI 추출 및 파싱 실패 재시도 처리

- **T-008**: 지오코딩·역지오코딩 구현
  - Kakao Local API 1차 지오코딩
  - Naver API 보조 검증
  - VWorld API 기반 역지오코딩과 행정/도로명 주소 보강
  - `pyproj` `always_xy=True` 좌표 정규화
  - API 429 지수 백오프, 지터, 동시성 상한 적용
  - 지오코딩 실패, 후보 과다, 낮은 신뢰도 결과를 `needs_review` 후보로 남김
  - `kraddr-geo` 연계는 구현하지 않음

- **T-009**: 대표 프레임 추출 구현
  - POI 시작 타임스탬프에 5~10초 오프셋 적용
  - `yt-dlp`로 직접 스트림 URL 확보
  - FFmpeg Input Seeking 방식으로 JPEG 대표 프레임 추출
  - 대표 프레임 JPEG를 RustFS `tripmate-frames` 버킷에 저장
  - 원본 동영상 또는 오디오 다운로드가 필요한 경우 RustFS `tripmate-raw-videos` 버킷에 무기한 보존

- **T-010**: APScheduler 단일 실행자 구현
  - `scheduler` 실행자가 `crawl_runs.pending` 작업을 claim
  - REST, MCP, 정기 크롤이 같은 작업 테이블을 공유
  - heartbeat, progress, retry_count, last_error 갱신
  - stale 작업 재투입 및 최대 재시도 초과 격리
  - Celery, Redis, RabbitMQ, PostgreSQL Advisory Lock은 초기 범위에서 제외

- **T-011**: MCP 서버 읽기/쓰기 UX 구현
  - `harvest_travel_destinations` 작업 생성 도구
  - `get_harvest_status` 작업 상태 조회 도구
  - `search_existing_places`, `get_place_detail` 조회 도구
  - `correct_place`, `merge_places`, `trigger_deep_research` 쓰기 도구
  - `review_unmatched_place`, `resolve_place_candidate` 매칭 검수 쓰기 도구
  - 모든 쓰기 도구에 스키마 검증, 멱등 키, 감사 로그 기록 적용

- **T-012**: Next.js 프론트엔드 스택 정비
  - Tailwind CSS와 shadcn/ui 초기화
  - React Hook Form + Zod 폼 검증 구성
  - TanStack Query로 수집 시작 mutation과 작업 상태 폴링 구현
  - Zustand는 명확한 전역 클라이언트 상태 수요가 생길 때까지 보류

- **T-013**: 지도·리스트·운영 패널 구현
  - `maplibre-vworld-js` 지도 표시
  - 장소 리스트, 지도 마커, 상세 패널 동기화
  - 매칭되지 않은 장소 후보 검수 큐와 수동 보정 폼 작성
  - 영상 설명 원문, Gemini 보정 설명, Gemini 장소 보강 설명 비교 표시
  - 작업 상태, 실패 작업, API 쿼터, MCP 쓰기 로그 운영 패널 작성
  - RustFS 저장 용량, 객체 수, 최근 저장 실패 로그 표시
  - Deep Research 트리거 및 완료 결과 표시

- **T-014**: Windows 및 Docker Compose 통합 검증
  - Windows PowerShell 기준 백엔드, 프론트엔드, MCP, scheduler 실행 검증
  - Docker Compose로 단일 호스트 다중 컨테이너 실행 검증
  - SQLite/SpatiaLite 데이터 볼륨, WAL, 확장 로드 확인
  - 별도 RustFS 로컬 Docker 서비스의 `/health` 또는 `/health/live` 상태 확인
  - RustFS S3 API, 콘솔, 버킷 생성, 객체 업로드·조회 검증

- **T-015**: Playwright E2E 검증
  - 수집 시작 → `job_id` 반환 → 상태 폴링 → 완료 결과 표시 시나리오
  - 지도 렌더링, CRUD, 작업 상태, Deep Research 트리거 검증
  - MCP 쓰기 도구가 생성한 변경사항이 웹 UI에 반영되는 경로 검증

- **T-016**: 고도화 후보 검토
  - sqlite-vec 기반 의미론적 검색 후보 검토
  - 규모 증가 시 PostgreSQL/PostGIS 전환 ADR 작성
  - 멀티 워커 필요 시 PgQueuer 또는 APScheduler + Advisory Lock 검토

---

## 완료

- [x] **T-004**: FastAPI 비동기 백엔드 기반 구축 — `crawl_runs`/`audit_logs`/`system_settings` SQLAlchemy 2.0 모델, `crawl_run_service`(생성·claim·heartbeat·완료·실패·stale 재투입)/`audit_service`/`settings_service` 도메인 서비스, `get_session` 의존성과 lifespan `init_db`, `/api/harvest` 작업 생성·상태 조회 및 `/api/settings` 연동 구현. REST는 작업 생성만 하고 직접 실행하지 않음. pytest 17건 통과. (2026-06-05)
- [x] **T-003**: 소형 프로젝트 기준 스캐폴딩 정비 — `backend/app/`(config·database·logging·models·services·api) 구조화, `mcp/`·`scheduler/`·`etl/media.py` 신설, Docker Compose 초안(`frontend`/`api`/`mcp`/`scheduler`/`rustfs`)과 `Dockerfile.python`·`frontend/Dockerfile`, RustFS 버킷 초기화 스크립트, 컴포넌트별 requirements, 프론트 App Router 스캐폴드 작성. `.env.example`과 `Settings` 환경 변수 이름 동기화 완료. (Docker/Playwright 통합 빌드 검증은 T-014로 이관) (2026-06-05)
- [x] **T-018**: RustFS 미디어 저장, 무기한 보존, 매칭 실패 장소 수동 검수, Gemini 설명 보정·보강 필드 요구사항을 개발 계획에 반영. (2026-06-05)
- [x] **T-017**: Google Docs 소형 프로젝트 SpatiaLite 명세 반영 — 공식 YouTube API 중심, SQLite + SpatiaLite, 전면 asyncio, APScheduler 단일 실행자, REST/MCP 분리, 프론트 스택 기준으로 문서 재정렬. (2026-06-05)
- [x] **T-002**: 프로젝트 `docs/` 디렉토리 문서 자산 생성 및 상세 기획서 반영 — `architecture.md`, `decisions.md`, `tasks.md`, `journal.md`, `dev-environment.md` 작성 및 MCP UX 계획 반영 완료. (2026-06-04)
- [x] **T-001**: 프로젝트 루트 문서 자산 생성 — `README.md`, `AGENTS.md`, `CLAUDE.md`, `SKILL.md`, `.env.example` 작성 완료. (2026-06-03)

---

## 사양 참조

- 최신 기준 문서: Google Docs `AI유튜브여행_소형프로젝트_SpatiaLite_명세서`
- 아키텍처 세부: `docs/architecture.md`
- 결정 기록: `docs/decisions.md`
- 작업 일지: `docs/journal.md`
- 개발 환경: `docs/dev-environment.md`
