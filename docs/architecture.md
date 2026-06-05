# 아키텍처

본 문서는 `tripmate-agent` 프로젝트의 전체 시스템 설계와 구성 요소 간 데이터 흐름을 다룬다. 기준 문서는 Google Docs `AI유튜브여행_소형프로젝트_SpatiaLite_명세서`이며, 의사결정의 역사는 `decisions.md`의 ADR에서 별도로 관리한다.

---

## 1. 설계 기준

`tripmate-agent`는 1~2인이 개발·운영하고 동시 사용자가 10명 내외인 소형 프로젝트를 전제로 한다. 따라서 대규모 분산 크롤링보다 운영 단순성, 장애 원인 축소, 재현 가능한 로컬/단일 호스트 배포를 우선한다.

핵심 원칙은 다음과 같다.

- 검색·메타데이터 수집은 공식 YouTube Data API v3를 기본으로 한다.
- 비공식 의존은 공식 대안이 없는 자막 추출과 프레임 추출로만 격리한다.
- 공간 DB는 별도 DB 서버 없이 SQLite + SpatiaLite로 시작한다.
- 백엔드와 ETL은 전면 `asyncio` 기반으로 작성한다.
- 블로킹 라이브러리(`yt-dlp`, `faster-whisper`, FFmpeg, SpatiaLite 동기 호출)는 executor로 격리한다.
- 정기 크롤 실행자는 APScheduler 단일 실행자로 시작하며, Celery, Redis, RabbitMQ, PostgreSQL Advisory Lock은 초기 범위에서 제외한다.
- 사람용 Web REST UX와 AI 에이전트용 MCP UX는 분리하되 같은 작업 테이블과 같은 파이프라인을 공유한다.

---

## 2. 전체 시스템 구조

```
                  ┌────────────────────────────────────────┐
                  │          Next.js 프론트엔드             │
                  │  - React Hook Form / Zod               │
                  │  - shadcn/ui / Tailwind                │
                  │  - TanStack Query 상태 조회·폴링        │
                  │  - maplibre-vworld-js 지도 뷰           │
                  └───────────────────┬────────────────────┘
                                      │
                              Web REST API
                                      │
                  ┌───────────────────▼────────────────────┐
                  │          FastAPI API 서버               │
                  │  - 세분 CRUD REST 엔드포인트             │
                  │  - crawl_runs 작업 생성                 │
                  │  - 조회·설정·감사 로그 API              │
                  └─────────┬───────────────────▲──────────┘
                            │                   │
                            │ 공유 도메인 서비스 │ 작업 생성
                            │                   │
                  ┌─────────▼───────────────────┴──────────┐
                  │            MCP 서버                     │
                  │  - 굵은 단위 에이전트 도구              │
                  │  - 수집 실행 / 상태 조회 / 장소 조회     │
                  │  - 보정 / 병합 / Deep Research           │
                  └─────────┬───────────────────▲──────────┘
                            │                   │
                            │ crawl_runs 생성    │ 상태 조회
                            ▼                   │
                  ┌────────────────────────────────────────┐
                  │        Scheduler / Worker              │
                  │  - APScheduler                         │
                  │  - pending 작업 단일 claim              │
                  │  - async ETL 파이프라인 실행             │
                  └─────────┬───────────────────▲──────────┘
                            │                   │
                            │ aiosqlite + WAL   │ 결과 적재
                            ▼                   │
                  ┌────────────────────────────────────────┐
                  │        SQLite + SpatiaLite             │
                  │  - tripmate.db                         │
                  │  - 공간 함수 / R-Tree 인덱스            │
                  │  - crawl_runs / places / mappings       │
                  └─────────┬──────────────────────────────┘
                            │
                            │ 외부 서비스 호출
                            ▼
                  ┌────────────────────────────────────────┐
                  │              외부 API                   │
                  │  - YouTube Data API v3                 │
                  │  - Google Gemini API                   │
                  │  - Kakao / Naver / VWorld              │
                  │  - youtube-transcript-api / yt-dlp      │
                  │  - faster-whisper / FFmpeg              │
                  └────────────────────────────────────────┘
```

Docker Compose 배포 시에는 `frontend`, `api`, `mcp`, `scheduler` 컨테이너가 같은 SQLite/SpatiaLite 데이터 볼륨을 공유한다. 실제 무거운 작업 실행은 `scheduler`가 단일 claim 방식으로 담당하여 API 서버와 MCP 서버가 직접 장시간 작업을 수행하지 않게 한다.

---

## 3. UX 표면

### 3.1 웹 기반 UX

웹 UX는 사람이 데이터를 입력·검수·조회하는 화면이다.

- 키워드, 유튜버, 재생목록, 수집 옵션을 관리한다.
- 수집 시작 시 `POST /api/harvest`로 작업을 만들고 `job_id`를 즉시 받는다.
- TanStack Query `refetchInterval`로 `GET /api/harvest/{job_id}`를 폴링한다.
- 완료된 장소는 리스트와 `maplibre-vworld-js` 지도에 함께 표시한다.
- 실패 작업, 쿼터 사용량, 최근 MCP 쓰기 로그를 운영 패널에서 확인한다.

### 3.2 MCP 서버 읽기/쓰기 UX

MCP는 에이전트용 UX다. REST API의 세분 CRUD를 그대로 노출하지 않고, 에이전트가 한 번에 사용할 수 있는 굵은 단위 도구를 제공한다.

대표 도구:

- `harvest_travel_destinations(query, channel_id, playlist_id, max_videos)`:
  검색어·채널·재생목록 기준으로 수집 작업을 만들고 `job_id`를 반환한다.
- `get_harvest_status(job_id)`:
  작업 상태, 진행률, 실패 원인, 완료 요약을 반환한다.
- `search_existing_places(query, radius, category)`:
  이미 적재된 장소를 검색한다.
- `get_place_detail(place_id)`:
  장소 상세, 원본 영상, 대표 프레임, 위치 보정 근거를 반환한다.
- `correct_place`, `merge_places`, `trigger_deep_research`:
  보정·병합·심층 조사 쓰기 작업을 생성한다.

모든 MCP 쓰기 도구는 Pydantic 스키마 검증, 멱등 키, 감사 로그, 작업 상태 기록을 거친다.

---

## 4. ETL 파이프라인

### 4.1 검색 의도 확장

사용자가 입력한 시드 키워드에 현재 월·계절 정보를 넣어 Gemini로 2~3개의 파생 키워드를 생성한다. 원본 키워드와 파생 키워드는 `search_keywords`에 1:N으로 저장하고, 계절 맥락은 `season_context`로 남긴다.

### 4.2 공식 YouTube Data API v3 수집

검색·메타데이터 수집은 공식 API를 기본으로 한다.

| 엔드포인트 | 용도 | 쿼터 비용 |
| --- | --- | --- |
| `search.list` | 키워드/채널 검색 | 호출당 100 |
| `playlistItems.list` | 재생목록 항목 나열 | 호출당 1 |
| `channels.list` | 채널 업로드 목록 조회 | 호출당 1 |
| `videos.list` | 영상 상세 메타데이터 조회 | 호출당 1 |

소형 프로젝트에서는 일일 10,000 유닛 한도에 도달할 가능성이 낮다. 따라서 `scrapetube`류 비공식 검색 크롤러는 기본 설계에서 제외한다. 검색 결과의 최신성, 키워드 유사도, 업로드일, 조회수 대비 참여도는 애플리케이션 레벨에서 정규화해 우선순위 큐에 적재한다.

### 4.3 자막·전사 폴백

타인 영상 자막은 공식 captions API로 받을 수 없으므로 비공식 의존을 이 구간에만 허용한다.

1. `youtube-transcript-api`로 수동/자동 자막을 우선 확보한다.
2. 차단, 포맷 변경, 자막 부재 시 `yt-dlp --write-auto-sub` 또는 `--write-subs`로 폴백한다.
3. 두 경로 모두 실패하면 `faster-whisper` 로컬 전사를 최종 폴백으로 사용한다.

### 4.4 Gemini POI 추출

타임스탬프가 포함된 자막을 Gemini에 전달하고 자유 텍스트가 아니라 JSON Schema 기반 출력을 요구한다.

필수 추출 필드:

- 영상 전체 요약
- 장소명
- 화자 설명
- 위치 단서
- 시작/종료 타임스탬프
- 장소 카테고리 후보

### 4.5 지오코딩·역지오코딩

지오코딩은 공식 Kakao / Naver / VWorld API만 사용한다. `kraddr-geo`는 현재 계획에 포함하지 않는다.

- Kakao Local API: 1차 장소 검색, 좌표 변환, 카테고리 식별
- Naver API: 모호한 결과의 보조 검증과 검색 메타데이터 보강
- VWorld API: 좌표 기반 행정 주소, 도로명 주소, 지번 주소 보강
- `pyproj` `always_xy=True`: 모든 좌표를 WGS84(EPSG:4326) 경도/위도 순서로 정규화
- 429 응답: 지수 백오프와 지터 적용

### 4.6 대표 프레임 추출

Gemini가 식별한 시작 타임스탬프에 5~10초 오프셋을 더하고, `yt-dlp`로 직접 스트림 URL을 확보한 뒤 FFmpeg Input Seeking으로 JPEG 대표 프레임을 추출한다.

핵심 규칙:

```powershell
ffmpeg -ss 00:03:25 -i "<STREAM_URL>" -frames:v 1 -q:v 2 -f image2 pipe:1
```

`-ss`는 반드시 `-i` 앞에 둔다. 뒤에 두면 FFmpeg이 시작부터 목표 시점까지 디코딩하여 비용이 커진다.

---

## 5. 비동기 실행 모델

파이프라인의 I/O 작업은 `async def` 코루틴으로 작성한다.

- HTTP 호출: `httpx.AsyncClient`
- 동시성 상한: `asyncio.Semaphore`
- DB 접근: `aiosqlite`
- SQLite 동시 접근 완화: WAL 모드
- 블로킹 격리: `asyncio.to_thread()` 또는 `loop.run_in_executor()`
- CPU 집약 전사: 필요 시 별도 프로세스풀

API 서버, MCP 서버, 정기 스케줄러는 모두 같은 작업 테이블(`crawl_runs`)을 통해 작업을 만들고 조회한다. 실제 실행은 scheduler가 `pending` 작업을 claim하여 처리한다.

---

## 6. 데이터베이스 엔티티 구조

초기 DB는 SQLite + SpatiaLite다. SQLAlchemy 2.0과 `aiosqlite`를 사용하며, 공간 함수와 R-Tree 인덱스는 SpatiaLite로 제공한다.

### 6.1 `search_keywords`

- `id` (Integer, PK)
- `seed_keyword` (String)
- `derived_keyword` (String, Nullable)
- `season_context` (String, Nullable)
- `is_active` (Boolean)
- `created_at` (DateTime)

### 6.2 `source_targets`

- `id` (Integer, PK)
- `target_type` (String) - `keyword`, `channel`, `playlist`
- `source_value` (String)
- `display_name` (String, Nullable)
- `is_active` (Boolean)
- `last_crawled_at` (DateTime, Nullable)
- `next_crawl_at` (DateTime, Nullable)
- `created_at` (DateTime)

### 6.3 `youtube_videos`

- `video_id` (String, PK)
- `title` (String)
- `url` (String)
- `channel_id` (String)
- `channel_name` (String, Nullable)
- `published_at` (DateTime, Nullable)
- `view_count` (Integer, Nullable)
- `like_count` (Integer, Nullable)
- `engagement_score` (Float, Nullable)
- `crawl_status` (String)
- `crawled_at` (DateTime)

### 6.4 `travel_places`

- `place_id` (Integer, PK)
- `name` (String)
- `description` (Text, Nullable)
- `official_address` (String, Nullable)
- `road_address` (String, Nullable)
- `latitude` (Float)
- `longitude` (Float)
- `geom` (SpatiaLite Point, 4326)
- `api_source` (String, Nullable)
- `category` (String, Nullable)
- `is_geocoded` (Boolean)
- `detailed_research_content` (Text, Nullable)
- `created_at` (DateTime)

### 6.5 `video_place_mappings`

- `id` (Integer, PK)
- `video_id` (String, FK)
- `place_id` (Integer, FK)
- `ai_summary` (Text)
- `speaker_note` (Text, Nullable)
- `timestamp_start` (String, Nullable)
- `timestamp_end` (String, Nullable)
- `frame_image_path` (String, Nullable)
- `created_at` (DateTime)

### 6.6 `crawl_runs`

- `id` (Integer, PK)
- `job_type` (String)
- `source` (String) - `web`, `mcp`, `scheduler`
- `target_type` (String, Nullable)
- `target_id` (String, Nullable)
- `state` (String) - `pending`, `running`, `done`, `failed`
- `progress` (Float)
- `started_at` (DateTime, Nullable)
- `heartbeat_at` (DateTime, Nullable)
- `finished_at` (DateTime, Nullable)
- `retry_count` (Integer)
- `last_error` (Text, Nullable)

### 6.7 `system_settings`

- `key` (String, PK)
- `value` (String)
- `updated_at` (DateTime)

### 6.8 `audit_logs`

- `id` (Integer, PK)
- `actor_type` (String) - `web`, `mcp`, `scheduler`
- `action` (String)
- `target_type` (String)
- `target_id` (String, Nullable)
- `payload_json` (Text, Nullable)
- `created_at` (DateTime)

---

## 7. 프론트엔드 아키텍처

프론트엔드는 다음 스택을 기준으로 한다.

| 영역 | 채택 기술 | 역할 |
| --- | --- | --- |
| 프레임워크 | Next.js + React | App Router 기반 화면 구성 |
| 폼 | React Hook Form | 키워드, 타겟, 설정 입력 |
| 검증 | Zod | 폼·API 응답 스키마 검증 |
| UI | shadcn/ui + Tailwind CSS | 일관된 컴포넌트와 스타일 |
| 서버 상태 | TanStack Query | 조회 캐싱, 작업 상태 폴링, mutation |
| 지도 | `maplibre-vworld-js` | VWorld 지도 표시 |

Zustand는 현 단계에서 도입하지 않는다. 서버 데이터는 TanStack Query가, 폼 상태는 React Hook Form이 처리하므로 별도 전역 클라이언트 상태 수요가 명확해질 때 추가한다.

---

## 8. 대규모 전환 후보

다음 조건이 실제로 발생하면 후속 ADR로 전환을 검토한다.

- 동시 사용자나 수집 대상이 늘어 SQLite 동시 쓰기 한계가 반복된다.
- 멀티 워커가 필요해 scheduler 단일 실행자 모델이 병목이 된다.
- 반경 검색, 클러스터링, 공간 조인이 SpatiaLite로 감당하기 어려워진다.
- 작업 큐 모니터링과 재시도 투명성이 더 중요해진다.

전환 후보:

- PostgreSQL/PostGIS: SpatiaLite 공간 함수를 PostGIS `ST_DWithin`, GiST 인덱스로 이전
- PgQueuer: `LISTEN/NOTIFY` + `SKIP LOCKED` 기반 DB 네이티브 큐
- Celery + Beat: 수십 워커 분산 처리가 필요할 때만 검토
- Airflow / Dagster: 수백 데이터소스 의존성을 관리해야 할 때만 검토
