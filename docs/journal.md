# JOURNAL — 작업 일지

본 문서는 `tripmate-agent` 프로젝트의 작업 진행 역사를 역시간순으로 기록한다.

---

## 2026-06-05: T-012 Next.js 프론트엔드 스택 정비

- **담당자**: Codex
- **작업 내용**:
  - **shadcn/ui 초기화**: `components.json`, `cn` 유틸, `Button`, `Input`, `Select`, `Field`, `Badge` 컴포넌트를 추가하고 Tailwind semantic color/radius token을 구성.
  - **폼/검증**: React Hook Form + Zod로 수집 시작 폼을 구현. 검색어, 채널 ID, 재생목록 ID 중 하나를 선택하고 `max_videos` 범위를 검증.
  - **상태 관리**: TanStack Query `QueryProvider`를 루트에 연결하고, `POST /api/harvest` mutation과 `GET /api/harvest/{job_id}` polling을 `HarvestConsole`에 구현.
  - **API client**: `frontend/src/lib/api.ts`에 수집 시작, 상태 조회, 여행지 목록 조회 함수를 추가하고 백엔드 snake_case payload를 캡슐화.
  - **의존성 보정**: npm에 공개되지 않은 `maplibre-vworld` 의존성을 제거하고 `maplibre-gl`은 유지. T-013에서 VWorld 타일 구성 또는 실제 공개 wrapper 확인이 필요.
  - **lint 설정**: Next 14와 호환되도록 ESLint 8 + `eslint-config-next@14.2.35` 및 `.eslintrc.json`을 추가.
  - **추가 작업 식별**: `npm audit`이 Next 14 계열 보안 이슈를 보고했으나 자동 수정은 Next 16 major upgrade를 요구하므로 T-020으로 분리.
  - **검증**: `npm run lint`, `npm run type-check`, `npm run build` 통과. dev server는 3000 포트 사용 중으로 3001 포트에서 띄워 `http://127.0.0.1:3001/` 응답과 한글 Select 라벨 렌더링을 확인.
- **다음 작업**:
  - T-013: 지도·리스트·운영 패널 구현. `maplibre-gl` 기반 VWorld 지도, 장소 리스트, 검수 큐, 작업/저장소 운영 패널을 연결한다.

---

## 2026-06-05: T-011 MCP 서버 읽기/쓰기 UX 구현

- **담당자**: Codex
- **작업 내용**:
  - **패키지 구조 정리**: 외부 MCP SDK 패키지 이름과 로컬 `mcp/` 디렉터리 이름 충돌을 피하기 위해 실제 구현을 `tripmate_mcp` 패키지로 분리. `mcp/server.py`는 기존 Docker Compose 명령을 보존하는 호환 래퍼로 유지.
  - **FastMCP 서버 등록**: `tripmate_mcp.server.build_server`가 FastMCP 인스턴스를 만들고, `MCP_WRITE_ENABLED`에 따라 읽기/쓰기 도구를 등록.
  - **읽기 도구**: `get_harvest_status`, `search_existing_places`, `get_place_detail` 구현. 작업 상태 JSON, 장소 검색 결과, 영상 매핑·대표 프레임·후보 근거를 반환.
  - **쓰기 도구**: `harvest_travel_destinations`, `correct_place`, `merge_places`, `trigger_deep_research`, `review_unmatched_place`, `resolve_place_candidate` 구현.
  - **검증/감사/멱등성**: 모든 쓰기 도구에 Pydantic 입력 스키마, 필수 `idempotency_key`, `audit_logs` 기록, 동일 멱등 키 재호출 시 기존 결과 반환 적용.
  - **도메인 서비스 보강**: `place_service`에 장소 검색, 상세 조회 보조, 수동 보정, 중복 병합, 후보 검수 메타데이터 기록, 후보 해결(기존 장소 매칭·신규 장소 생성·제외)을 추가.
  - **실행 구조**: `Dockerfile.python`이 `tripmate_mcp` 패키지를 복사하도록 갱신하고, MCP 서버는 시작 시 `init_db()` 후 설정된 transport로 실행.
  - **테스트**: MCP runtime 단위 테스트 10건 추가. 전체 백엔드 pytest 103건 통과.
- **다음 작업**:
  - T-012: Next.js 프론트엔드 스택 정비. Tailwind CSS, shadcn/ui, React Hook Form, Zod, TanStack Query를 실제 화면과 연결한다.

---

## 2026-06-05: T-019 채널·재생목록 harvest 오케스트레이션 보강

- **담당자**: Codex
- **작업 내용**:
  - **pipeline.run_harvest 확장**: 기존 keyword 수집 경로를 유지하면서 `channel_id`, `playlist_id` 입력을 추가 지원.
  - **playlist 수집**: `playlistItems.list`에서 `contentDetails.videoId` 또는 `snippet.resourceId.videoId`를 읽어 중복 없는 video_id 목록을 수집하고, pagination과 `max_videos` 상한을 적용.
  - **channel 수집**: `channels.list`로 uploads playlist ID를 찾은 뒤 playlist 수집 경로를 재사용.
  - **공통 적재 경로**: keyword/channel/playlist 모두 `videos.list` 상세 조회, ranking, `ingest_service.ingest_candidates` 멱등 적재 경로를 공유.
  - **scheduler handler**: 기본 `harvest` handler가 keyword/channel/playlist target을 모두 `run_harvest`로 전달하도록 보강.
  - **결과 요약**: `target_type`, `target_id`, `channel_id`, `playlist_id`, `uploads_playlist_id`, `quota_used`를 `crawl_runs.result_json`에 남길 수 있도록 summary를 확장.
  - **테스트**: playlist 직접 수집, channel uploads playlist 수집, scheduler handler channel/playlist 전달을 추가. 전체 백엔드 pytest 93건 통과.
- **다음 작업**:
  - T-011: MCP 서버 읽기/쓰기 UX 구현. REST와 같은 `crawl_runs`, 장소 조회, 보정/병합/검수 도메인 서비스를 재사용한다.

---

## 2026-06-05: T-010 APScheduler 단일 실행자 구현

- **담당자**: Codex
- **작업 내용**:
  - **scheduler.worker**: `run_once`를 테스트 가능한 1회 tick으로 구현. stale running 작업을 먼저 재투입/격리한 뒤 FIFO pending 작업을 claim하고 handler 실행.
  - **상태 전이**: `execute_run`이 heartbeat/progress 갱신, handler 결과 `done` 처리, handler 예외와 unknown job_type의 `failed` 격리를 담당.
  - **APScheduler 실행 루프**: `worker_loop`가 APScheduler interval job으로 `run_once`를 반복 실행하며 `max_instances=1`, `coalesce=True`로 단일 실행자 계약을 유지.
  - **기본 harvest handler**: keyword target은 기존 `pipeline.run_harvest`에 연결. channel/playlist target은 현재 오케스트레이션이 없으므로 명시적으로 실패시켜 조용한 오동작을 막음.
  - **설정**: `SCHEDULER_POLL_INTERVAL_SECONDS`, `SCHEDULER_HEARTBEAT_INTERVAL_SECONDS`, `SCHEDULER_STALE_THRESHOLD_SECONDS`, `SCHEDULER_MAX_RETRIES`를 `.env.example`과 `Settings`에 추가.
  - **추가 작업 식별**: API는 channel/playlist target을 받을 수 있으나 수집 오케스트레이션이 keyword 중심이므로 T-019를 새로 추가.
  - **테스트**: claim→done, empty tick, handler 실패, unknown job, stale 재투입, max retry 격리, channel target 명시 실패, payload JSON 오류까지 검증. 전체 백엔드 pytest 90건 통과.
- **다음 작업**:
  - T-019: channel/playlist harvest 오케스트레이션을 `YouTubeClient.channels_list`/`playlistItems.list`와 기존 ingest 경로로 보강.

---

## 2026-06-05: T-009 대표 프레임 추출 구현

- **담당자**: Codex
- **작업 내용**:
  - **frame_extraction**: POI 시작 타임스탬프(`HH:MM:SS`, `MM:SS`, 초)를 파싱하고 5~10초 오프셋을 더해 대표 프레임 추출 시각을 계산.
  - **yt-dlp 연동**: `resolve_stream_url_ytdlp`를 지연 import 방식으로 구현하고, `select_stream_url`이 직접 URL 또는 최고 해상도 video format URL을 선택하도록 구현.
  - **FFmpeg Input Seeking**: `extract_jpeg_with_ffmpeg`에서 `-ss`를 `-i` 앞에 둔 명령으로 JPEG를 stdout 추출. 테스트에서는 runner 주입으로 실제 FFmpeg 바이너리 없이 명령 계약 검증.
  - **RustFS 저장**: 추출한 JPEG를 `AssetType.FRAME`으로 `tripmate-frames` 버킷에 저장하고 `media_assets`에 URI·체크섬·크기·무기한 보존 정책 기록. `mapping_id`가 주어지면 `video_place_mappings.frame_asset_id`에 연결.
  - **원본 미디어 보존 helper**: 이미 확보한 원본 동영상 또는 오디오 bytes를 `AssetType.RAW_VIDEO`로 `tripmate-raw-videos` 버킷에 저장하는 `store_raw_media` 추가.
  - **테스트**: 타임스탬프 파싱, object key sanitize, stream URL 선택, FFmpeg 명령 순서, 실패 처리, frame asset 저장·mapping 연결, raw media 저장까지 검증. 전체 백엔드 pytest 82건 통과.
- **다음 작업**:
  - T-010: APScheduler 단일 실행자가 `crawl_runs.pending` 작업을 claim하고 T-006~T-009 파이프라인을 실행하도록 연결.

---

## 2026-06-05: T-008 지오코딩·역지오코딩 구현

- **담당자**: Claude
- **작업 내용**:
  - **geocoding**: Kakao Local(1차)·Naver(보조 검증)·VWorld(역지오코딩) 어댑터를 `httpx.AsyncClient` 주입형으로 구현(ADR-8, `kraddr-geo` 미연계). `normalize_to_wgs84`로 `pyproj always_xy=True` 좌표 정규화(미설치/4326은 graceful identity).
  - **복원력**: `request_with_backoff`로 429 지수 백오프 + 지터 재시도, `asyncio.Semaphore` 동시성 상한.
  - **평가**: `evaluate_geocode`가 단일 결과는 확정, 후보 과다 시 Naver 최상위 좌표 근접도로 디스앰비규에이션, 실패·모호·낮은 신뢰도는 `needs_review`로 판정(자동 확정 금지, ADR-16).
  - **geocode_service**: 매칭 시 좌표 근접 중복(T-005 저장소 계층)을 재사용하거나 새 `travel_places`를 만들고, VWorld 역지오코딩으로 도로명·지번 주소 보강. 미매칭은 후보를 `needs_review`로 유지하고 사유 기록.
  - 루트 `etl/geocode.py`에 정규 구현 위치 명시.
  - **테스트**: 어댑터 파싱, 백오프 재시도/포기, 좌표 정규화, 평가 분기(no_result/single/ambiguous/disambiguated), 적용 영속화(매칭 생성·중복 재사용·needs_review 유지·VWorld 보강)까지 pytest 72건 통과.
- **다음 작업**:
  - T-009: `yt-dlp` 스트림 URL + FFmpeg Input Seeking 대표 프레임 추출, RustFS `tripmate-frames` 저장.

---

## 2026-06-05: T-007 자막·전사·Gemini POI 추출 구현

- **담당자**: Claude
- **작업 내용**:
  - **transcript**: `youtube-transcript-api → yt-dlp → faster-whisper` provider 체인. 각 provider는 사용 시점에만 지연 import해 라이브러리 없는 환경에서도 import·테스트 가능. 블로킹 호출은 `asyncio.to_thread`로 격리(`get_transcript_async`).
  - **poi_extraction**: Gemini JSON Schema(`RESPONSE_JSON_SCHEMA`) 기반 POI 추출. 실제 Gemini 호출은 주입형 `llm` 콜러블로 분리. JSON 파싱/Pydantic 검증 실패 시 `max_retries`까지 재시도, 모두 실패하면 `POIExtractionError`.
  - **media_store**: `MediaStore` 프로토콜로 저장 백엔드 추상화(`InMemoryMediaStore`/`RustFSMediaStore`). `store_and_record`가 RustFS 업로드 후 `media_assets`에 버킷·객체 키·URI·sha256·크기·무기한 보존 정책 기록. asset_type별 버킷 라우팅.
  - **summarize_service**: 자막 RustFS 저장 → Gemini POI 추출 → 영상 설명 보정본 저장(원문 `description_raw` 보존, ADR-16) → 추출 장소를 `needs_review` 후보로 생성(자동 확정 금지). 자막 없으면 `failed` 처리.
  - 루트 `etl/summarize.py`에 정규 구현 위치 명시.
  - **테스트**: provider 체인 폴백, POI 파싱·재시도·스키마 검증, media_store 저장·라우팅, summarize 전체 흐름까지 pytest 60건 통과.
- **다음 작업**:
  - T-008: Kakao/Naver/VWorld 지오코딩·역지오코딩, 좌표 정규화, 429 백오프, needs_review 처리.

---

## 2026-06-05: T-006 공식 YouTube Data API v3 수집 파이프라인 구현

- **담당자**: Claude
- **작업 내용**:
  - scheduler가 import해 실행할 수 있도록 비동기 수집 파이프라인을 `backend/app/etl/` 패키지로 구현.
  - **youtube_client**: 공식 `search.list`/`playlistItems.list`/`channels.list`/`videos.list`를 감싸는 `httpx.AsyncClient` 주입형 클라이언트. 엔드포인트별 쿼터 비용 누적(`search`=100 등). 비공식 검색 크롤러 미사용(ADR-11).
  - **keyword_expansion**: 시드 키워드 + 계절 맥락 → 파생 키워드 생성. 실제 Gemini 호출은 주입형 `generator` 콜러블로 분리하고 키 없이도 결정론적 폴백으로 동작(T-007에서 Gemini 연결). 중복·시드 제거.
  - **ranking**: 업로드 최신성(반감기 지수 감쇠), 키워드 유사도(Jaccard), 조회수 대비 참여도를 정규화한 합성 점수.
  - **ingest_service**: `video_id` 기준 멱등 upsert(재수집 시 통계 갱신, Gemini 보정 필드 보존), 파생 키워드 `search_keywords` 저장, 채널 워터마크(최신 업로드 시각) 조회.
  - **pipeline.run_harvest**: 파생 키워드 → 검색 → 상세 조회 → 점수 정렬 → 멱등 적재 오케스트레이션. 요약(quota_used·season·derived 포함) 반환.
  - **테스트**: ranking/keyword, ingest 멱등·워터마크, httpx `MockTransport` 기반 파이프라인 통합까지 pytest 45건 통과. 루트 `etl/search.py`에 정규 구현 위치를 명시.
- **다음 작업**:
  - T-007: 자막(youtube-transcript-api→yt-dlp→faster-whisper)·Gemini POI 추출, RustFS 저장.

---

## 2026-06-05: T-005 SpatiaLite 공간 데이터 모델 구현

- **담당자**: Claude
- **작업 내용**:
  - **도메인/공간 모델 7종 구현**: `search_keywords`, `source_targets`, `youtube_videos`, `travel_places`, `extracted_place_candidates`, `video_place_mappings`, `media_assets`.
    - `youtube_videos`: `description_raw`/`description_gemini_corrected` 분리(원문 보존).
    - `travel_places`: `description`/`gemini_enriched_description`/`description_review_status` 분리.
    - `extracted_place_candidates`: `match_status`(기본 `needs_review`) + 검수자·검수 시각·검수 메모.
    - `media_assets`: RustFS 버킷·객체 키·URI·체크섬·크기·무기한 보존 정책.
  - **공간 컬럼 관리(ADR-17)**: `app/core/spatial.py`가 `travel_places.geom` Point(4326)와 R-Tree 공간 인덱스를 ORM 밖 SpatiaLite DDL로 멱등 관리. `mod_spatialite` 미로드 환경에서는 graceful skip. `init_db`에 연결.
  - **저장소 계층 캡슐화**: `place_service`에 근접 검색(`find_places_within_radius`)·중복 후보(`find_duplicate_candidates`)를 경위도 bounding box + Haversine으로 구현. 공간 함수 호출을 한곳에 모아 PostGIS 전환 시 `ST_DWithin` 대체가 쉽도록 함.
  - **API 연동**: `/api/destinations`(확정 장소)·`/api/destinations/unmatched`(needs_review 검수 큐)를 실제 DB 조회로 연결.
  - **의사결정**: ADR-17 추가(공간 컬럼 ORM 밖 관리·저장소 계층 캡슐화·geoalchemy2 미도입).
  - **테스트**: 모델 영속성·관계, Haversine 정확도, 근접/중복 탐색, 검수 큐, 엔드포인트까지 pytest 30건 통과.
- **다음 작업**:
  - T-006: 공식 YouTube Data API v3 수집 파이프라인(파생 키워드·검색·정규화·멱등) 구현.

---

## 2026-06-05: T-004 FastAPI 비동기 백엔드 기반 구축

- **담당자**: Claude
- **작업 내용**:
  - **공통 모델 구현**: `crawl_runs`(작업 테이블), `audit_logs`, `system_settings`를 SQLAlchemy 2.0 선언형으로 구현. `RunState`/`RunSource` enum, `TimestampMixin` 도입.
  - **도메인 서비스**:
    - `crawl_run_service`: 작업 생성, FIFO `claim_next_pending`(pending→running 전이), heartbeat·진행률 갱신, 완료/실패 처리, heartbeat 만료(stale) 작업 재투입·최대 재시도 초과 격리.
    - `audit_service`: 감사 로그 기록·조회.
    - `settings_service`: `system_settings` upsert·조회, `.env` 기본값 병합.
  - **DB 초기화**: `init_db()`(create_all + SpatiaLite 메타데이터 멱등 초기화)를 lifespan에 연결. `get_session` async 의존성 제공. `mod_spatialite` 미로드 환경에서도 동작하도록 graceful skip.
  - **API 연동**: `POST /api/harvest`가 `crawl_runs` 작업만 생성하고 `job_id` 즉시 반환(ADR-13), `GET /api/harvest/{job_id}` 상태 조회, `/api/settings` GET/POST를 서비스에 연결. 작업 생성·설정 변경 시 감사 로그 기록.
  - **테스트**: `backend/tests/`에 pytest-asyncio 기반 서비스·API 테스트 17건 추가, 전부 통과.
- **다음 작업**:
  - T-005: SpatiaLite 공간 데이터 모델(`travel_places.geom` 등)과 근접 중복 조회 저장소 계층 구현.

---

## 2026-06-05: T-003 스캐폴딩 정비 — 코드 구현 진입 준비

- **담당자**: Claude
- **작업 내용**:
  - 문서(`architecture.md`, `decisions.md`, `tasks.md`)와 실제 코드 사이의 갭을 점검하고, 코드 구현(T-004 이후)에 진입할 수 있도록 스캐폴딩을 보완.
  - **백엔드 구조화**: `backend/app/` 패키지 도입.
    - `app/core/config.py`: `.env.example`의 모든 환경 변수를 1:1로 매핑한 `pydantic-settings` 기반 `Settings` 로더. (T-003: 환경 변수 이름 동기화 완료)
    - `app/core/database.py`: SQLAlchemy 2.0 + `aiosqlite` async 엔진, SpatiaLite 확장 로드와 WAL 모드 적용 지점 정의.
    - `app/core/logging.py`: API 키 마스킹 헬퍼.
    - `app/models`, `app/services`, `app/api`: 구현 대상 명시한 패키지 스캐폴드. `main.py`를 팩토리 패턴 + 라우터 조립 구조로 리팩터링.
  - **누락 디렉토리 생성**: `mcp/`(server + 읽기/쓰기 도구 메타데이터), `scheduler/`(단일 실행자 루프), `etl/media.py`(RustFS 저장 계층) 신설.
  - **Docker Compose 초안**: `frontend`, `api`, `mcp`, `scheduler`, `rustfs` 서비스와 SQLite/RustFS 데이터 볼륨, `Dockerfile.python`(공용 Python 이미지), `frontend/Dockerfile` 작성. RustFS는 별도 서비스로 분리(S3 API 9003, 콘솔 9004).
  - **RustFS 버킷 초기화**: `scripts/init_rustfs_buckets.py`로 3개 버킷 멱등 생성 절차 정리.
  - **컴포넌트별 의존성 매니페스트**: `etl/requirements.txt`, `scheduler/requirements.txt`, `mcp/requirements.txt` 분리.
  - **프론트엔드 App Router 스캐폴드**: `src/app/layout.tsx`, `page.tsx`(`#destination-list`, `#vworld-map-container`), `settings/page.tsx`(`#gemini-engine-select` 등), `VWorldMap` 컴포넌트, Tailwind 설정 추가 — 기존 E2E 스펙의 타깃을 실재화.
  - **검증**: `config`/`database`/`mcp`/`scheduler`/`etl.media` 모듈 import·구동 확인, FastAPI 라우트 등록 확인.
- **남은 사항**:
  - Docker 이미지 빌드와 `npm ci`/Playwright 통합 검증은 T-014에서 수행.
  - 모델·서비스·라우터 실제 구현은 T-004(백엔드 기반)·T-005(공간 모델)부터 진행.
- **다음 작업**:
  - T-004: FastAPI 비동기 백엔드 기반 구축(`crawl_runs`/`audit_logs`/`system_settings` 모델, SpatiaLite 초기화).

---

## 2026-06-05: RustFS 미디어 저장 및 장소 검수 요구사항 반영

- **담당자**: Codex
- **작업 내용**:
  - 후속 요구사항에 따라 받은 원본 동영상, 자막 파일, 전사 결과, 대표 프레임을 RustFS에 저장하는 계획을 추가.
  - RustFS는 애플리케이션 컨테이너에 내장하지 않고 별도 로컬 Docker 서비스로 구동하며, S3 API `9003`, 콘솔 `9004` 포트를 기본 후보로 정리.
  - 미디어 객체 보존 기간을 무기한으로 확정하고, DB 논리 삭제나 장소 매칭 실패만으로 RustFS 객체를 자동 삭제하지 않는 정책을 문서화.
  - `media_assets` 테이블을 추가해 RustFS 버킷, 객체 키, URI, 체크섬, 크기, 보존 정책을 저장하도록 데이터 모델 보강.
  - 지오코딩 결과가 없거나 모호한 장소를 `extracted_place_candidates`에 `needs_review` 상태로 남기고, 웹 UI와 MCP에서 사용자가 직접 장소명·주소·좌표·카테고리를 수정할 수 있게 계획 수정.
  - YouTube 영상 설명 원문, Gemini 오탈자·문맥 보정 설명, Gemini 장소 설명 보강 필드를 분리해 저장하도록 스키마 계획 보강.
  - `docs/decisions.md`에 ADR-15, ADR-16 추가.
- **다음 작업**:
  - T-003: 스캐폴딩 단계에서 RustFS 로컬 Docker 서비스, 버킷 초기화, 저장 계층 인터페이스를 코드 구조에 반영.

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
