# TASKS — 백로그

작업 항목은 `T-NNN` 형식의 ID로 관리한다. 새 작업은 "대기"의 우선순위 순서대로 들어가고, 진행 중이 되면 담당자를 표시한다. 완료된 작업은 "완료" 섹션 상단에 누적한다.

---

## 진행 중

- 현재 진행 중인 구현 작업 없음. 다음 착수 대상은 **T-020**이다.

---

## 대기 (우선순위 순)

- **T-020**: Next.js 메이저 업그레이드 및 npm audit 대응 검토
  - T-012 기준 `npm audit`이 Next 14 / `eslint-config-next` 계열 transitive 취약점 5건(1 moderate, 4 high)을 보고
  - 자동 수정은 Next 16 major upgrade를 요구하므로 프론트 안정화 후 별도 브랜치에서 Next/React 호환성 검토
  - 업그레이드 시 `next lint` 대체 전략(ESLint flat config 또는 Next 최신 lint workflow)도 함께 정리

---

## 완료

- [x] **T-016**: 고도화 후보 검토 — sqlite-vec / SQLite Vec1 의미론적 검색, PostgreSQL/PostGIS 전환, PgQueuer, APScheduler + PostgreSQL advisory lock 후보를 공식 문서 기준으로 검토. 현재 소형 프로젝트 단계에서는 선제 도입하지 않고, 의미론적 검색은 `place_embeddings` optional feature, PostGIS는 확정 장소 100,000건·매핑 1,000,000건·반경 검색 p95 500ms 초과·SQLite write lock 반복, PgQueuer는 PostgreSQL 전환 이후 backlog 5분 이상 지속 또는 단일 worker SLA 미달 시 검토하는 것으로 ADR-20에 결정. 아키텍처 대규모 전환 후보 표와 wrapper 최소화 원칙을 갱신. (2026-06-05)
- [x] **T-015**: Playwright E2E 검증 — `tests/playwright.config.ts`가 backend `127.0.0.1:18080`과 frontend `127.0.0.1:13100` 개발 서버를 자동 기동하도록 구성. `tests/scripts/seed_e2e.py`로 SQLite E2E DB에 장소, 검수 후보, MCP 감사 로그, RustFS 대표 프레임 메타데이터를 매 테스트마다 재시드. 메인 화면의 VWorld 지도 fallback/패널 렌더링, 수집 시작 `job_id`/`pending` 표시, Deep Research 트리거, 매칭 실패 후보 수동 보정 후 장소 목록 반영, 설정 페이지 Gemini 엔진 저장을 브라우저에서 검증. CORS 허용 origin 설정, E2E 산출물 ignore, 공용 `Input` ref 전달 보정, 검수/장소/운영 패널 접근성 이름을 추가. Browser plugin은 현재 세션에 없어 일반 Playwright로 검증. `npm test` 4건, `npm run lint`, `npm run type-check`, `npm run build`, backend `compileall`, backend pytest, `docker compose --env-file .env config --quiet` 통과. (2026-06-05)
- [x] **T-021**: VWorld 우선 지오코딩 및 Kakao 키워드 장소 검색 보강 — 지오코딩 기본 우선순위를 VWorld → Kakao → Naver로 조정하고, VWorld는 `python-vworld-api`의 `AsyncVworldClient`를 직접 사용하도록 `VWorldGeocoder`/`VWorldReverseGeocoder` 내부 wrapper class를 제거. `backend/requirements.txt`에 `python-vworld-api` GitHub archive commit pin 추가, 로컬 검증은 `F:\dev\python-vworld-api` editable 설치로 수행. Kakao Local은 주소 검색 결과가 없을 때 공식 `GET /v2/local/search/keyword.json` 키워드 장소 검색 fallback을 사용해 POI명·도로명 주소·지번 주소·카테고리를 후보로 저장. `.env.example`, README, 아키텍처, 개발 환경, ADR-19, 에이전트 문서를 최신 정책으로 갱신. 지오코딩 단위 테스트 15건, backend 전체 pytest, `compileall`, `docker compose config --quiet`, Python Compose image build, API 컨테이너 `AsyncVworldClient` import, RustFS smoke, `npm run lint`, `npm run type-check`, `npm run build` 통과. (2026-06-05)
- [x] **T-014**: Windows 및 Docker Compose 통합 검증 — Compose를 `.env` optional 구성과 host port override(`RUSTFS_HOST_PORT`, `API_HOST_PORT`, `MCP_HOST_PORT`, `FRONTEND_HOST_PORT`) 가능 구조로 보강. RustFS는 호스트 `9003/9004`, 컨테이너 내부 `rustfs:9000/9001`로 분리하고, API health 이후 MCP/scheduler/frontend가 시작되도록 `depends_on.condition` 적용. Docker Compose MCP는 `streamable-http` transport(`8010/mcp`)로 실행. `.dockerignore` 추가로 Docker build context를 root 6.47KB, frontend 1.34KB 수준으로 축소. `aiosqlite` SpatiaLite extension loading을 `run_async` 경유로 보정하고 공간 컬럼 검사 버그를 수정. `scripts/verify-docker-compose.ps1`와 `scripts/verify_rustfs.py`로 health, MCP port, RustFS 버킷 생성, 객체 업로드·조회 smoke 검증 자동화. WSL Docker CLI에서 override 포트 `19003/19004`, `18000`, `18010`, `13000`으로 `rustfs/api/mcp/scheduler/frontend` 전체 실행, HTTP health 200, RustFS 3개 버킷 smoke 객체 업로드·조회, SQLite DB 생성 확인. Windows PowerShell은 현재 세션 PATH에서 Docker CLI를 찾지 못해 래퍼 preflight 메시지까지만 확인. backend pytest 105건, `npm run lint`, `npm run type-check`, `npm run build`, `docker compose config --quiet` 통과. (2026-06-05)
- [x] **T-013**: 지도·리스트·운영 패널 구현 — `maplibre-gl` 기반 VWorld WMTS raster style과 장소 marker 표시, 장소 리스트/선택 동기화, Deep Research 트리거, 매칭 실패 후보 검수 큐(신규 장소 생성·제외), 최근 작업/실패 작업/MCP·웹 감사 로그/RustFS 객체·헬스 요약 운영 패널 구현. `/api/runs`, `/api/audit-logs`, `/api/storage/rustfs`, 장소 보정, 후보 해결, Deep Research REST endpoint 추가. 공개 npm 패키지 `maplibre-vworld`/`maplibre-vworld-js`가 없어 T-013 구현은 `maplibre-gl` 직접 WMTS 구성으로 진행. backend pytest 105건, `npm run lint`, `npm run type-check`, `npm run build` 통과. dev server `http://127.0.0.1:3001/` 응답 및 패널 렌더링 확인. (2026-06-05)
- [x] **T-012**: Next.js 프론트엔드 스택 정비 — shadcn/ui 초기화(`components.json`, `Button`, `Input`, `Select`, `Field`, `Badge`, `cn`), Tailwind semantic token 구성, React Hook Form + Zod 수집 폼, TanStack Query provider 및 수집 시작 mutation/상태 polling 구현. `maplibre-vworld` npm 의존성은 공개 패키지가 없어 제거하고 `maplibre-gl`은 유지. Next 14 호환을 위해 ESLint 8 + `eslint-config-next@14.2.35` 설정 추가. `npm run lint`, `npm run type-check`, `npm run build` 통과. dev server `http://127.0.0.1:3001/` 응답 확인. (2026-06-05)
- [x] **T-011**: MCP 서버 읽기/쓰기 UX 구현 — 외부 MCP SDK와 로컬 `mcp/` 실행 디렉터리 이름 충돌을 피하기 위해 실제 구현을 `tripmate_mcp` 패키지로 분리하고 `mcp/server.py`는 Docker Compose 호환 래퍼로 유지. FastMCP 서버 등록, 읽기 도구(`get_harvest_status`, `search_existing_places`, `get_place_detail`), 쓰기 도구(`harvest_travel_destinations`, `correct_place`, `merge_places`, `trigger_deep_research`, `review_unmatched_place`, `resolve_place_candidate`) 구현. 쓰기 도구는 Pydantic 스키마 검증, 필수 `idempotency_key`, `audit_logs` 기록을 적용. `place_service`에 장소 보정, 병합, 후보 검수/해결 도메인 함수 추가. pytest 103건 통과. (2026-06-05)
- [x] **T-019**: 채널·재생목록 harvest 오케스트레이션 보강 — `pipeline.run_harvest`가 `seed_keyword`/`channel_id`/`playlist_id` 입력을 모두 처리하고, channel은 `channels.list`로 uploads playlist를 찾아 `playlistItems.list`로 video_id를 수집하며, playlist는 직접 `playlistItems.list`를 사용. 모든 target은 기존 `videos.list` 상세 조회, ranking, `ingest_service` 멱등 적재 경로를 재사용하고 `target_type`/`target_id`/`quota_used`/`uploads_playlist_id`를 결과에 기록. scheduler 기본 `harvest` handler도 keyword/channel/playlist를 모두 전달. pytest 93건 통과. (2026-06-05)
- [x] **T-010**: APScheduler 단일 실행자 구현 — `scheduler.worker`: `run_once`가 stale running 작업 재투입/격리 후 FIFO pending 작업을 claim하고 handler를 실행, `execute_run`이 heartbeat/progress/done/failed 상태 전이를 일원화, unknown job과 handler 예외를 failed로 격리, 기본 `harvest` handler를 keyword `pipeline.run_harvest`에 연결. `worker_loop`는 APScheduler interval job(`max_instances=1`, `coalesce=True`)으로 `run_once` 반복 실행. scheduler poll/heartbeat/stale/max retry 환경 변수 추가. channel/playlist harvest 오케스트레이션 갭은 T-019로 분리. pytest 90건 통과. (2026-06-05)
- [x] **T-009**: 대표 프레임 추출 구현 — `frame_extraction`: POI 시작 타임스탬프 파싱(`HH:MM:SS`/`MM:SS`/초)과 5~10초 오프셋 적용, `yt-dlp` 지연 import 기반 직접 스트림 URL 선택, FFmpeg Input Seeking(`-ss`를 `-i` 앞에 배치) JPEG 추출, RustFS `tripmate-frames` 저장 및 `media_assets` 기록, `video_place_mappings.frame_asset_id` 연결, 원본 동영상/오디오 bytes를 `tripmate-raw-videos`에 무기한 보존하는 helper 구현. pytest 82건 통과. (2026-06-05)
- [x] **T-008**: 지오코딩·역지오코딩 초기 구현 — `geocoding`: Kakao Local 1차/Naver 보조 검증/VWorld 역지오코딩, `pyproj always_xy` 좌표 정규화(미설치 graceful), 429 지수 백오프+지터·Semaphore 동시성 상한, `evaluate_geocode`(단일 매칭/Naver 디스앰비규에이션/후보 과다·실패 시 `needs_review`). `geocode_service`: 매칭 시 좌표 근접 중복 재사용 또는 신규 `travel_places` 생성·VWorld 주소 보강, 실패·모호는 needs_review 유지(자동 확정 금지). `kraddr-geo` 미연계. 최신 VWorld 우선 직접 client 사용 기준은 T-021에서 보강. pytest 72건 통과. (2026-06-05)
- [x] **T-007**: 자막·전사·Gemini POI 추출 구현 — `transcript`(youtube-transcript-api→yt-dlp→faster-whisper provider 체인, 지연 import·executor 격리), `poi_extraction`(Gemini JSON Schema·파싱 실패 재시도, 주입형 llm), `media_store`(RustFS 저장 추상화 + `media_assets` 기록, 무기한 보존), `summarize_service`(자막 RustFS 저장→POI 추출→설명 보정본 저장·원문 보존→`needs_review` 후보 생성). pytest 60건 통과. (2026-06-05)
- [x] **T-006**: 공식 YouTube Data API v3 수집 파이프라인 구현 — `backend/app/etl/` 비동기 패키지: `youtube_client`(search/playlistItems/channels/videos.list, 쿼터 누적), `keyword_expansion`(주입형 Gemini generator + 결정론적 폴백, `season_context`), `ranking`(업로드 최신성·키워드 유사도·참여도 정규화 점수), `ingest_service`(`video_id` 멱등 upsert, 파생 키워드 저장, 채널 워터마크), `pipeline.run_harvest` 오케스트레이션. httpx `MockTransport` 통합 테스트 포함 pytest 45건 통과. 비공식 크롤러 미사용(ADR-11). (2026-06-05)
- [x] **T-005**: SpatiaLite 공간 데이터 모델 구현 — `search_keywords`/`source_targets`/`youtube_videos`/`travel_places`/`extracted_place_candidates`/`video_place_mappings`/`media_assets` 모델, 설명 원문·Gemini 보정/보강 필드 분리, `match_status`·검수 메타데이터, `media_assets` 무기한 보존. `app.core.spatial`이 `geom` Point(4326)·R-Tree를 ORM 밖 SpatiaLite DDL로 관리(ADR-17), `place_service` 근접/중복 탐색(bbox+Haversine, PostGIS 대체 가능)·검수 큐 조회, `/api/destinations`·`/api/destinations/unmatched` 연동. pytest 30건 통과. (2026-06-05)
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
