# 아키텍처

본 문서는 `tripmate-agent` 프로젝트의 전체 시스템 설계와 구성 요소 간 데이터 흐름을 다룬다. 의사결정의 역사는 `decisions.md`의 ADR에서 별도로 관리한다.

---

## 1. 전체 시스템 구조

`tripmate-agent`는 웹 화면만 제공하는 도구가 아니라, 사람이 브라우저로 쓰는 UX와 AI 에이전트가 도구 호출로 쓰는 UX를 함께 제공하는 여행 데이터 구축 시스템으로 설계한다.

```
                  ┌────────────────────────────────────────┐
                  │          Next.js 프론트엔드             │
                  │  - 리스트 / 상세 / 설정 / 지도 UX       │
                  │  - maplibre-vworld-js 지도 뷰           │
                  └───────────────────┬────────────────────┘
                                      │
                              HTTP REST API
                                      │
                  ┌───────────────────▼────────────────────┐
                  │          FastAPI 백엔드                 │
                  │  - 도메인 서비스 / REST API             │
                  │  - Deep Research 트리거                 │
                  │  - 작업 상태 및 감사 로그               │
                  └─────────┬───────────────────▲──────────┘
                            │                   │
                            │ 내부 서비스 호출   │ 도구 호출
                            │                   │
                  ┌─────────▼───────────────────┴──────────┐
                  │          MCP 서버 UX                    │
                  │  - 읽기 도구: 검색, 조회, 상태 확인      │
                  │  - 쓰기 도구: CRUD, 보정, 병합, 실행     │
                  └─────────┬───────────────────▲──────────┘
                            │                   │
                     읽기 / 쓰기                │ DB 갱신
                            ▼                   │
                  ┌───────────────────┐         │
                  │     SQLite3       │         │
                  │   (tripmate.db)   │         │
                  └─────────▲─────────┘         │
                            │                   │
                  ┌─────────┴───────────────────┴──────────┐
                  │            ETL 파이프라인               │
                  │  - 키워드 확장 및 우선순위 큐            │
                  │  - yt-dlp / 자막 / 전사 / 요약           │
                  │  - 지오코딩 / 역지오코딩 / 프레임 추출    │
                  └───────────────────┬────────────────────┘
                                      │
                                외부 서비스 호출
                                      │
                  ┌───────────────────▼────────────────────┐
                  │              외부 API                   │
                  │  - YouTube / yt-dlp                     │
                  │  - Google Gemini API                    │
                  │  - Kakao / Naver / VWorld               │
                  └────────────────────────────────────────┘
```

초기 저장소는 AGENTS.md의 현재 기준에 따라 **FastAPI + SQLAlchemy 2.0 + SQLite3**를 우선 구현한다. 다만 상세 기획서가 요구한 공간 중복 제거, 반경 검색, 대량 크롤링 운영성이 커지는 시점에는 PostgreSQL/PostGIS 전환을 별도 ADR로 검토한다.

---

## 2. UX 표면

### 2.1 웹 기반 UX

웹 UX는 사람이 여행 데이터를 탐색하고 운영 설정을 조정하는 기본 화면이다.

- 여행지 목록, 상세 카드, 원본 영상 링크, 요약 문장, 대표 프레임 이미지를 제공한다.
- `maplibre-vworld-js` 기반 지도에서 장소 마커, 목록 선택 동기화, 지도 레이어 토글을 제공한다.
- 검색 키워드, 유튜버, 재생목록, Gemini 엔진 설정, 지오코딩 공급자 설정을 CRUD로 관리한다.
- 사용자가 특정 장소를 선택하면 Deep Research를 트리거하고 완료 상태를 확인할 수 있다.

### 2.2 MCP 서버 읽기/쓰기 UX

MCP 서버는 브라우저 UI와 동등한 1급 UX로 둔다. AI 에이전트가 여행 데이터베이스를 조회하고 운영 작업을 수행할 수 있도록 읽기와 쓰기 도구를 모두 제공한다.

읽기 도구 범위:

- 여행지 검색, 여행지 상세 조회, 영상별 장소 조회
- 검색 키워드, 유튜버, 재생목록, 파생 키워드 조회
- ETL 작업 상태, 실패 작업, 최근 실행 로그, API 쿼터 사용량 조회
- 지오코딩 결과, 역지오코딩 결과, 중복 후보 조회

쓰기 도구 범위:

- 검색 키워드, 유튜버, 재생목록 등록/수정/비활성화
- ETL 수집, 자막 전사, Gemini 요약, 지오코딩, Deep Research 작업 트리거
- 여행지 설명, 카테고리, 주소, 좌표, 대표 이미지, 공개 상태 보정
- 중복 여행지 병합 및 영상-장소 매핑 수정

쓰기 도구는 실제 변경을 수행할 수 있어야 한다. 대신 모든 쓰기 도구는 Pydantic 스키마 검증, 멱등 키, 감사 로그, 실패 재시도 상태를 남겨 브라우저 조작과 동일한 수준으로 추적 가능하게 만든다.

---

## 3. ETL 파이프라인 상세 아키텍처

유튜브 여행 영상으로부터 양질의 여행지 정보를 정제하여 DB를 구축하는 ETL은 다음 단계로 구동한다.

```
[시작]
  │
  ├─► 1단계: 검색 의도 확장 및 수집 큐 생성
  │     ├── 사용자가 CRUD한 검색 키워드, 유튜버, 재생목록 조회
  │     ├── Gemini API로 계절, 월, 지역, 테마를 반영한 파생 키워드 생성
  │     ├── 원본 키워드와 파생 키워드의 1:N 관계 및 season_context 저장
  │     ├── YouTube Data API는 최소 호출하고 yt-dlp 기반 탐색을 병행
  │     └── 최신성, 채널 지정 여부, 참여도, 키워드 유사도로 우선순위 큐 적재
  │
  ├─► 2단계: 메타데이터, 자막, 전사, POI 추출
  │     ├── yt-dlp skip_download / extract_flat로 메타데이터 우선 수집
  │     ├── 기존 video_id는 DB 캐시로 스킵하여 멱등성 보장
  │     ├── youtube-transcript-api → yt-dlp 자막 → faster-whisper 순서로 전사 폴백
  │     ├── Gemini API에 JSON Schema 기반 POI 추출 프롬프트 전달
  │     └── 장소명, 위치 단서, 설명, 시작/종료 타임스탬프를 임시 저장
  │
  ├─► 3단계: 대표 프레임 추출
  │     ├── Gemini가 식별한 timestamp_start에 5~10초 오프셋 적용
  │     ├── yt-dlp로 직접 스트림 URL 확보
  │     ├── FFmpeg `-ss`를 `-i` 앞에 두는 Input Seeking 방식 사용
  │     └── JPEG 바이트를 로컬 저장 또는 추후 객체 스토리지에 저장
  │
  └─► 4단계: 지오코딩, 역지오코딩, 중복 병합
        ├── 내부 DB 캐시에서 기존 보정 결과 우선 확인
        ├── Kakao Local API를 1차 지오코딩 공급자로 사용
        ├── 결과가 없거나 모호하면 Naver API로 2차 보강
        ├── VWorld API로 좌표 기반 역지오코딩 및 행정/도로명 주소 보강
        ├── pyproj `always_xy=True`로 WGS84(EPSG:4326) 좌표계 정규화
        ├── 429 응답에는 지수 백오프와 지터를 적용
        └── 좌표 근접성 및 이름 유사도로 중복 후보를 병합 [완료]
```

현재 계획에서 `kraddr-geo` 연계는 채택하지 않는다. 지오코딩과 역지오코딩은 Kakao, Naver, VWorld 공급자 어댑터를 우선 구현하고, 공급자 교체가 가능하도록 Strategy Pattern으로 감싼다.

---

## 4. 스케줄링 및 복원력

상세 기획서는 3~7일 주기 크롤링과 작업 복원력을 강하게 요구한다. 초기 구현은 별도 브로커 없이 SQLite3 상태 테이블과 프로세스 내 스케줄러로 시작하되, 다음 원칙을 코드 설계에 반영한다.

- 작업 상태는 `pending`, `running`, `done`, `failed`로 기록한다.
- `started_at`, `heartbeat_at`, `retry_count`, `last_error`를 남겨 실패 원인을 추적한다.
- 일정 시간 heartbeat가 갱신되지 않은 `running` 작업은 stale로 보고 재시도 큐에 되돌린다.
- 채널별 마지막 크롤 시점 또는 최신 `published_at` 워터마크를 저장해 증분 크롤링만 수행한다.
- 업로드 빈도가 낮은 채널은 다음 크롤 간격을 14일 또는 30일까지 늘려 호출량을 줄인다.
- 대량 처리와 다중 워커가 필요해지면 PostgreSQL Advisory Lock 또는 PgQueuer 계열을 후속 ADR로 검토한다.

---

## 5. 프론트엔드 컴포넌트 아키텍처

Next.js React Client Component 단에서 VWorld 지도를 선언적으로 표시하기 위해 `maplibre-vworld-js`를 활용한다.

- **지도 연동**: `.env`에 정의된 `NEXT_PUBLIC_VWORLD_SERVICE_KEY`를 사용해 VWorld WMTS 타일을 렌더한다.
- **리스트-지도 동기화**: 리스트 뷰에서 특정 여행지를 호버/클릭하면 지도 마커가 포커스되거나 바운드가 이동한다.
- **설정 저장소**: Gemini 엔진 버전, 지오코딩 공급자 우선순위, ETL 주기 설정은 FastAPI의 `settings` API를 통해 SQLite3에 저장한다.
- **Deep Research 트리거**: 사용자가 특정 여행지를 선택해 Deep Research를 지시하면 백엔드가 Gemini 기반 심층 조사 작업을 생성하고 완료 후 해당 장소의 상세 소개 정보를 업데이트한다.
- **운영 상태 표시**: ETL 큐, 실패 작업, API 쿼터, 최근 MCP 쓰기 작업을 웹에서도 확인할 수 있게 한다.

---

## 6. 데이터베이스 엔티티 구조

초기 구현은 SQLite3로 시작하되, 공간 데이터 확장을 염두에 둔 필드명을 사용한다.

### 6.1 `search_keywords`

- `id` (Integer, PK)
- `seed_keyword` (String)
- `derived_keyword` (String, Nullable)
- `season_context` (String, Nullable)
- `is_active` (Boolean)
- `created_at` (DateTime)

### 6.2 `subscribed_youtubers`

- `id` (Integer, PK)
- `channel_id` (String, Unique)
- `channel_name` (String)
- `is_active` (Boolean)
- `last_scraped_at` (DateTime)
- `next_scrape_at` (DateTime, Nullable)

### 6.3 `youtube_videos`

- `video_id` (String, PK)
- `title` (String)
- `url` (String)
- `channel_id` (String)
- `published_at` (DateTime, Nullable)
- `engagement_score` (Float, Nullable)
- `crawl_status` (String)
- `crawled_at` (DateTime)

### 6.4 `travel_destinations`

- `id` (Integer, PK)
- `name` (String)
- `description` (Text)
- `address` (String)
- `road_address` (String, Nullable)
- `latitude` (Float)
- `longitude` (Float)
- `api_source` (String, Nullable)
- `category` (String, Nullable)
- `is_geocoded` (Boolean)
- `detailed_research_content` (Text, Nullable)
- `created_at` (DateTime)

### 6.5 `video_destination_mappings`

- `id` (Integer, PK)
- `video_id` (String, FK)
- `destination_id` (Integer, FK)
- `ai_summary` (Text)
- `speaker_note` (Text, Nullable)
- `timestamp_start` (String, Nullable)
- `timestamp_end` (String, Nullable)
- `frame_image_path` (String, Nullable)
- `created_at` (DateTime)

### 6.6 `etl_jobs`

- `id` (Integer, PK)
- `job_type` (String)
- `target_type` (String, Nullable)
- `target_id` (String, Nullable)
- `state` (String)
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
- `actor_type` (String) - `web`, `mcp`, `etl`
- `action` (String)
- `target_type` (String)
- `target_id` (String, Nullable)
- `payload_json` (Text, Nullable)
- `created_at` (DateTime)

---

## 7. PostGIS 전환 후보

상세 기획서는 PostGIS 기반 `ST_DWithin`, GiST 인덱스, geography 캐스팅을 권장한다. 현재 AGENTS.md 기준은 SQLite3이므로 즉시 변경하지 않는다. 대신 다음 조건 중 하나가 충족되면 PostgreSQL/PostGIS 전환 ADR을 작성한다.

- 동일 장소 중복이 문자열/좌표 휴리스틱만으로 관리하기 어려울 정도로 증가한다.
- 반경 검색, 주변 추천, 지도 클러스터링, 행정구역 기반 필터가 핵심 기능이 된다.
- 백그라운드 ETL과 MCP 쓰기 도구의 동시 쓰기가 SQLite3 락으로 반복 실패한다.
- 작업 큐와 스케줄링을 DB 레벨 락 또는 `FOR UPDATE SKIP LOCKED`로 안정화해야 한다.
