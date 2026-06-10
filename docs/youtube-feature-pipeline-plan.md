# YouTube 장소 feature 공급 로드맵

본 문서는 `tripmate-agent`가 YouTube 여행 콘텐츠에서 장소 후보를 추출하고,
`python-krtour-map`이 주기적으로 가져가 `feature`로 승격할 수 있도록 만드는
후속 작업의 실행 계획이다. 구현은 문서화 → DB 전환 → 수집·분석 스키마 보강 →
증분 API → sibling repo 연동 순서로 진행한다.

## 1. 목표

1. SQLite + SpatiaLite를 PostgreSQL + PostGIS 기반으로 전환한다.
2. 개발 DB 서버는 `python-kraddr-geo`가 쓰는 로컬 PostgreSQL/PostGIS 서버를
   공유하되, DB는 `tripmate_agent`처럼 별도 이름으로 분리한다.
3. 유튜버, 개별 YouTube 영상, 재생목록 정보를 별도 테이블로 저장하고, 장소
   후보·확정 장소·영상 언급 매핑과 연결한다.
4. 플레이리스트에서 발견한 영상이라면 그 출처 플레이리스트까지 추적한다.
5. 자막 기반 POI 추출과 별도로 Gemini에 YouTube URL을 직접 전달해 영상 상세
   요약을 만들고, 자막 기반 결과와 비교·조정하는 분석 절차를 추가한다.
6. `python-krtour-map`은 `tripmate-agent` REST API를 주기적으로 스캔해 full 또는
   incremental 방식으로 후보를 가져가 `FeatureBundle`로 변환한다.
7. TripMate curated plan 또는 POI 첨부에 넣을 수 있도록 `feature_id` 생성 이후
   `feature_snapshot`에 필요한 이름, 좌표, 카테고리, 설명, 영상 근거를 제공한다.

## 2. 참조 계약

### 2.1 PostgreSQL/PostGIS 서버

`python-kraddr-geo` 로컬 repo 기준 개발 서버는 다음 형태다.

- host: `localhost`
- port: `15434`
- user/password: `addr` / `addr` (개발 기본값)
- 기존 DB: `kraddr_geo`
- `tripmate-agent` 목표 DB: `tripmate_agent`
- 목표 DSN: `postgresql+asyncpg://addr:addr@localhost:15434/tripmate_agent`

운영 배포에서는 같은 변수명(`DATABASE_URL`)에 운영 DSN을 주입한다. 개발 기본값을
문서화하더라도 실제 비밀값은 `.env`에만 둔다.

### 2.2 TripMate POI 첨부

TripMate의 `app.trip_day_pois`는 `feature_id TEXT`와 `feature_snapshot JSONB`를
통해 `python-krtour-map` feature를 참조한다. TripMate DB에는 외래키가 없고,
`feature_snapshot`은 이름, 좌표, 카테고리, 마커 정보의 적재 시점 캐시다.

따라서 첫 단계에서 `tripmate-agent`가 TripMate DB에 직접 curated plan을 쓰지
않는다. `python-krtour-map`이 feature를 만든 뒤 TripMate의 notice plan 또는 POI
작성 화면이 그 `feature_id`를 선택하는 흐름을 기본으로 둔다.

### 2.3 `python-krtour-map` feature 공급

`python-krtour-map`의 적재 단위는 `FeatureBundle`이다.

- `Feature`: `kind`, `name`, `coord`, `address`, `category`, `urls`,
  `marker_icon`, `marker_color`, `detail`, `raw_refs`를 가진다.
- `SourceRecord`: provider 원본 payload와 checksum을 보존한다.
- `SourceLink`: feature와 source record를 연결하고 `source_role`,
  `match_method`, `confidence`, `is_primary_source`를 가진다.
- provider cursor는 `provider_sync.provider_sync_state.cursor`로 관리한다.

`tripmate-agent`는 `FeatureBundle`을 직접 DB에 쓰지 않고, `python-krtour-map`이
가져갈 수 있는 API payload를 제공한다. `feature_id` 생성은
`python-krtour-map`의 `make_feature_id(...)` 책임으로 남긴다.

## 3. PostgreSQL/PostGIS 전환 작업

### 3.1 결정 사항

- `DATABASE_URL` 기본 형태를 `postgresql+asyncpg://...`로 전환한다.
- `aiosqlite`, SpatiaLite DDL, SQLite WAL 설정은 제거 대상이다.
- `travel_places`에는 PostGIS `geometry(Point, 4326)` 컬럼을 ORM 또는 migration
  기준으로 추가하고 GiST 인덱스를 둔다.
- 반경·중복 검색은 PostGIS `ST_DWithin`을 사용한다.
- PostgreSQL은 FK 컬럼을 자동으로 인덱싱하지 않는다. 새 FK와 기존 FK 승격 컬럼은
  migration에서 명시 인덱스를 함께 만든다.
- 증분 API가 자주 조회하는 상태 + 시간 범위 조건은 단일 컬럼 인덱스 여러 개가
  아니라 composite index로 만든다. 예: `(feature_export_status, updated_at, id)`,
  `(state, next_crawl_at, id)`, `(video_id, run_type, state)`.
- JSONB는 payload 보존용과 조회용을 구분한다. `provider_evidence_json`,
  `summary_json`, export payload에서 containment 검색이 필요한 필드에는 GIN 인덱스
  또는 구체 key expression index를 둔다.
- 스키마 변경은 Alembic으로 관리한다. 기존 경량 `schema_migrations` registry는
  SQLite 보정 전용이므로 Postgres 전환 후 제거하거나 Alembic bootstrap 기록으로
  흡수한다.
- 테스트는 기본 단위 테스트와 별도로 실제 PostGIS DSN이 있을 때만 실행되는
  optional integration test를 둔다.

### 3.2 구현 체크리스트

- [ ] `backend/requirements.txt`에 `asyncpg`, `geoalchemy2`, `alembic` 추가.
- [ ] `backend/app/core/database.py`에서 SQLite connect event와 SpatiaLite 초기화 제거.
- [ ] `backend/app/core/spatial.py`를 PostGIS DDL/쿼리 helper로 교체하거나 제거.
- [ ] `TravelPlace.geom` 또는 migration DDL로 `geometry(Point, 4326)` 생성.
- [ ] FK 컬럼, `source_scan` 조회 조건, feature export cursor 조건의 인덱스를
  migration에 함께 작성.
- [ ] `place_service`의 bbox + Haversine 후보 검색을 `ST_DWithin`로 교체.
- [ ] `crawl_runs` claim은 PostgreSQL `UPDATE ... WHERE state='pending' RETURNING`
  또는 `FOR UPDATE SKIP LOCKED` 기반으로 정리한다.
- [ ] `docker-compose.yml`은 `python-kraddr-geo` 서버를 기본 외부 DB로 사용하고,
  repo 내부 PostgreSQL 컨테이너를 새로 띄우지 않는다. 단, CI/testcontainers가
  필요하면 테스트 전용으로만 둔다.

## 4. YouTube source 테이블 보강

### 4.1 새 테이블

#### `youtube_channels`

유튜버 또는 채널 단위의 정규 테이블이다.

| 컬럼 | 설명 |
| --- | --- |
| `channel_id` | YouTube channel id, PK |
| `title` | 채널명 |
| `handle` | `@handle`, nullable |
| `custom_url` | custom URL, nullable |
| `description` | 채널 설명 원문 |
| `thumbnail_url` | 대표 썸네일 |
| `subscriber_count` | 구독자 수, nullable |
| `video_count` | 영상 수, nullable |
| `published_at` | 채널 생성 시각 |
| `gemini_summary` | Gemini가 정리한 채널 성격·여행 스타일 요약 |
| `gemini_summary_model` | 요약 모델 |
| `gemini_summary_at` | 요약 시각 |
| `last_seen_at` | 마지막 메타데이터 확인 시각 |

#### `youtube_playlists`

재생목록 단위의 정규 테이블이다.

| 컬럼 | 설명 |
| --- | --- |
| `playlist_id` | YouTube playlist id, PK |
| `channel_id` | 소유 채널 FK |
| `title` | 재생목록 제목 |
| `description` | 설명 |
| `thumbnail_url` | 대표 썸네일 |
| `item_count` | 영상 수 |
| `published_at` | 생성 시각 |
| `last_crawled_at` | 마지막 수집 시각 |
| `last_item_published_at` | 증분 중단 기준 |

#### `youtube_playlist_videos`

영상이 어느 재생목록에서 발견되었는지 보존한다.

| 컬럼 | 설명 |
| --- | --- |
| `playlist_id` | 재생목록 FK |
| `video_id` | 영상 FK |
| `position` | 재생목록 내 순서 |
| `playlist_item_id` | YouTube playlist item id |
| `added_at` | 재생목록에 추가된 시각 |
| `first_seen_at` | 최초 관측 시각 |
| `last_seen_at` | 마지막 관측 시각 |

PK는 `(playlist_id, video_id)`로 둔다.

#### `youtube_video_analysis_runs`

자막 추출, YouTube URL Gemini 요약, 두 결과 비교·정리 실행을 추적한다.

| 컬럼 | 설명 |
| --- | --- |
| `id` | PK |
| `video_id` | 영상 FK |
| `run_type` | `transcript_extract`, `url_summary`, `reconcile` |
| `state` | `pending`, `running`, `done`, `failed` |
| `model` | Gemini 모델 |
| `prompt_version` | prompt 버전 |
| `input_asset_id` | 사용한 transcript/media asset, nullable |
| `summary_json` | 구조화 결과 JSONB |
| `summary_text` | 사람이 읽는 요약 |
| `confidence_score` | 결과 신뢰도 |
| `started_at` / `finished_at` | 실행 시각 |
| `last_error` | 실패 원인 |

#### `feature_exports`

범용 feature pull API의 안정적인 full/incremental cursor와 tombstone을 위한 export
ledger다. 후보 테이블의 `updated_at`만 직접 노출하면 reject/tombstone 재전송과
payload checksum 비교가 어려우므로 별도 테이블로 둔다. `python-krtour-map`은 이
범용 API를 가져가는 첫 consumer다.

| 컬럼 | 설명 |
| --- | --- |
| `export_id` | 안정적인 export id, PK |
| `sequence` | 증가 cursor용 bigint identity 또는 sequence |
| `candidate_id` | `extracted_place_candidates.id` FK |
| `operation` | `upsert`, `reject`, `tombstone` |
| `export_state` | `pending`, `ready`, `exported`, `rejected` |
| `payload_json` | API 응답에 쓰는 정규화 payload JSONB |
| `payload_hash` | `sha256:` prefix를 포함한 payload checksum |
| `last_exported_at` | 마지막으로 API에서 노출된 시각 |
| `rejection_reason` | 검수 제외 또는 export 제외 사유 |
| `created_at` / `updated_at` | 생성·갱신 시각 |

필수 인덱스:

- `(export_state, updated_at, export_id)`
- `(sequence)`
- `(candidate_id)`
- `payload_json` 조회가 필요하면 GIN 또는 key expression index

### 4.2 기존 테이블 보강

`youtube_videos`에는 다음을 추가하거나 기존 컬럼을 FK 기준으로 승격한다. 현재
`channel_id`는 문자열 컬럼으로 존재하므로 새 컬럼을 중복 생성하지 말고
`youtube_channels.channel_id` FK와 인덱스로 정리한다.

- `channel_id` FK
- `canonical_url`
- `duration_seconds`
- `thumbnail_url`
- `default_language`
- `tags_json`
- `gemini_url_summary`
- `gemini_url_summary_json`
- `gemini_url_summary_model`
- `gemini_url_summary_at`
- `transcript_summary`
- `reconciled_summary`
- `reconciled_summary_json`
- `reconciled_summary_at`

`extracted_place_candidates`에는 다음을 추가한다.

- `source_channel_id`
- `source_playlist_id`
- `analysis_run_id`
- `source_kind`: `transcript`, `url_summary`, `reconcile`, `manual`, `geocoding`
- `provider_evidence_json`: transcript, reconcile, VWorld/Kakao/Naver 보강 근거 JSONB
- `feature_export_status`: `pending`, `ready`, `exported`, `rejected`

`video_place_mappings`에는 다음을 추가한다.

- `source_channel_id`
- `source_playlist_id`
- `analysis_run_id`
- `source_kind`
- `provider_evidence_json`
- `feature_export_status`

T-065 구현은 위 컬럼을 `extracted_place_candidates`와 `video_place_mappings` 양쪽에
추가했다. transcript 후보 생성 시 영상 channel과 첫 playlist provenance를 채우고,
지오코딩 결정은 `provider_evidence_json.geocoding`에 구조화해 저장한다. 사람이
후보를 확정하거나 자동 지오코딩이 확정한 매핑은 `ready`, 검수 대기 후보는
`pending`, 제외 후보는 `rejected`로 둔다. Google Places API 보강과
`python-krtour-map` 8자리 category mapping은 과금·저장 정책과 mapping 표 확인 전까지
별도 작업으로 남긴다.

## 5. 주기 스캔 job

새 job type은 `source_scan`으로 둔다. 이 job은 직접 Gemini 분석까지 수행하지 않고,
활성 `source_targets` 또는 새 source 테이블을 훑어 필요한 `harvest`/`video_analysis`
작업을 생성한다.

`source_targets`는 현재 `target_type`, `source_value`, `display_name`, `is_active`,
`last_crawled_at`, `next_crawl_at`를 가진다. T-063에서는 필요하면 아래 필드를
추가한다.

- `scan_interval_minutes`
- `last_seen_cursor`
- `last_seen_video_published_at`
- `api_budget_group`
- `scan_failure_count`
- `last_scan_error`
- `last_scan_at`

`source_scan` 조회는 `(is_active, next_crawl_at, id)`와
`(api_budget_group, is_active, next_crawl_at, id)` composite index를 사용한다.
여러 scheduler가 동시에 실행될 가능성을 열어 둘 경우에는 PostgreSQL claim 쿼리에
`FOR UPDATE SKIP LOCKED`를 적용한다.

흐름:

1. scheduler가 `source_scan`을 주기적으로 실행한다.
2. `source_targets.is_active = true`이고 `next_crawl_at <= now()`인 target을 조회한다.
3. target별로 YouTube API 호출량 budget을 확인한다.
4. channel target은 uploads playlist 또는 RSS/`playlistItems.list`를 사용한다.
5. playlist target은 `playlistItems.list` 증분 수집을 수행한다.
6. 새 영상 또는 메타데이터 변경 영상은 `youtube_videos`,
   `youtube_channels`, `youtube_playlists`, `youtube_playlist_videos`에 upsert한다.
7. 분석이 필요한 영상에 `video_analysis` 또는 기존 `harvest` 후처리 job을 생성한다.
8. target의 `last_scan_at`, `next_crawl_at`, scan 실패 카운트를 갱신한다.
   실제 수집 watermark인 `last_crawled_at`은 후속 `harvest` 성공 경로에서만
   갱신해 증분 수집 기준이 scan enqueue만으로 앞당겨지지 않게 한다.

재시도와 stale 처리는 기존 `crawl_runs` 정책을 재사용한다.

## 6. Gemini URL 요약과 자막 비교 절차

### 6.1 실행 순서

1. YouTube Data API로 영상 메타데이터를 확보한다.
2. 자막·전사를 기존 체인(`youtube-transcript-api` → `yt-dlp` → `faster-whisper`)으로
   확보하고 RustFS에 저장한다.
3. Gemini에 transcript 기반 POI 추출을 요청한다.
4. Gemini에 YouTube URL을 직접 전달해 영상 전체의 상세 요약, 방문 장소,
   화면·설명란 근거, 유튜버 관점의 추천 포인트를 요청한다.
   T-064 구현은 Gemini API video understanding 문서의 REST 예시를 기준으로
   공개 YouTube URL을 `file_data.file_uri`에 담아 보낸다. 해당 기능은 preview로
   문서화되어 있어 모델별 안정성은 운영 전 실제 key smoke가 필요하다.
5. 세 번째 Gemini 호출에서 transcript 결과와 URL summary 결과를 비교한다.
   T-064 구현은 deterministic merge가 아니라 구조화 JSON을 요구하는 Gemini
   reconcile prompt를 사용한다.
6. 불일치가 있으면 자동 확정하지 않고 `needs_review` 후보로 남긴다.
7. 일치하거나 충분히 높은 신뢰도의 후보만 `feature_export_status = ready`로 둔다.
   `feature_export_status` 컬럼과 외부 evidence 연결은 T-065에서 추가한다.

### 6.2 비교 기준

- 장소명 exact 또는 alias 일치
- 좌표 거리: PostGIS `ST_DWithin` 기준 기본 100m
- 주소 일치: 도로명/지번/행정동/법정동 단위 비교
- 카테고리 일치: Kakao Local category, Gemini category, `python-krtour-map`
  8자리 category mapping 비교
- 영상 근거: transcript timestamp와 Gemini URL evidence가 같은 구간을 가리키는지

## 7. 범용 feature 수집 API

downstream consumer가 주기적으로 긁어갈 REST API를 `tripmate-agent`에 추가한다.
REST path에는 특정 consumer 이름을 넣지 않는다. `python-krtour-map`은
이 범용 API를 가져가는 첫 consumer다. 외부 호출이므로 `/api/v1`와 `X-API-Key`
인증을 그대로 사용한다.

### 7.1 Full snapshot

```http
GET /api/v1/features/snapshot?cursor=<opaque>&limit=200
X-API-Key: ...
```

응답:

```json
{
  "items": [
    {
      "export_id": "ytpc_...",
      "candidate_id": 123,
      "operation": "upsert",
      "place": {
        "name": "월정리 해변",
        "description": "...",
        "gemini_enriched_description": "...",
        "category_label": "해변",
        "category_code_suggestion": "01000000",
        "longitude": 126.7958,
        "latitude": 33.5563,
        "address": {
          "official_address": "...",
          "road_address": "...",
          "legal_dong_code": null,
          "sido_code": null,
          "sigungu_code": null
        }
      },
      "youtube": {
        "video_id": "...",
        "video_url": "https://www.youtube.com/watch?v=...",
        "video_title": "...",
        "video_summary": "...",
        "channel_id": "...",
        "channel_title": "...",
        "channel_summary": "...",
        "playlist_id": "...",
        "playlist_title": "..."
      },
      "evidence": {
        "timestamp_start": "00:03:12",
        "timestamp_end": "00:04:10",
        "transcript_excerpt": "...",
        "gemini_url_evidence": "...",
        "confidence_score": 0.86,
        "providers": {
          "vworld": {},
          "kakao": {},
          "naver": {},
          "google": {}
        }
      },
      "source_record": {
        "provider": "tripmate-agent-youtube",
        "dataset_key": "youtube_place_candidates",
        "source_entity_type": "extracted_place_candidate",
        "source_entity_id": "123",
        "raw_payload_hash": "sha256:..."
      },
      "updated_at": "2026-06-10T00:00:00Z"
    }
  ],
  "next_cursor": "...",
  "has_more": true
}
```

### 7.2 Incremental changes

```http
GET /api/v1/features/changes?cursor=<opaque>&limit=200
X-API-Key: ...
```

증분 cursor는 opaque string으로 둔다. 내부적으로는 `(updated_at, export_id)` 또는
별도 `feature_exports.sequence`를 사용한다. API 소비자는 cursor 내용을
해석하지 않는다.

증분 응답은 `operation`을 포함한다.

- `upsert`: 새 후보 또는 변경 후보
- `reject`: 후보가 검수에서 제외됨
- `tombstone`: 과거 export 후보가 더 이상 유효하지 않음

`python-krtour-map`은 full snapshot으로 재동기화할 수 있어야 하며, incremental은
운영 효율을 위한 최적화로 둔다.

## 8. 외부 API 보강

현재 확정 경로는 VWorld → Kakao → Naver다. 사용자가 Google 보강 가능성을 열었으나,
아래는 구현 전 재확인이 필요하다.

- Google Places API 사용 여부와 과금·쿼터·저장 정책
- Google 결과를 `python-krtour-map` feature source로 저장할 수 있는 라이선스 범위
- Kakao/Naver/VWorld 결과와 Google 결과가 충돌할 때 우선순위
- Google API 키의 환경변수 이름과 로그 마스킹 정책

재확인 전에는 Google을 필수 의존성으로 추가하지 않고 optional enrichment provider로
문서와 스키마 자리만 둔다.

## 9. 재확인 필요 사항

- `tripmate-agent` DB 이름을 `tripmate_agent`로 확정할지, 사용자가 다른 이름을
  원하는지 확인한다.
- `DATABASE_URL` 드라이버를 `asyncpg`로 확정할지, `python-kraddr-geo`와 같은
  `psycopg` 계열로 맞출지 확인한다. 본 문서는 우선 `asyncpg`를 목표로 둔다.
- `python-krtour-map`이 pull API를 직접 호출할지, 별도 provider 모듈을
  `python-krtour-map` repo에 추가할지 구현 위치를 확정한다.
- `python-krtour-map` category 8자리 코드와 TripMate 표시 카테고리 간 mapping 표가
  필요하다. 초기에는 `category_code_suggestion`을 제안값으로만 제공한다.
- TripMate curated plan에 자동 등록까지 할지, admin이 feature를 골라 notice plan에
  넣는 수동 흐름을 유지할지 확인한다.
- YouTube URL 직접 Gemini 호출의 현재 모델 지원 범위는 T-064 구현 직전에 공식
  문서로 확인했다. 공개 YouTube URL은 preview 기능이고 REST payload는
  `file_data.file_uri`를 사용한다. 실제 API key smoke는 아직 수행하지 않았다.

## 10. 구현 순서

1. `T-061`: PostgreSQL/PostGIS 전환과 Alembic bootstrap.
2. `T-062`: YouTube channel/video/playlist 정규 테이블과 ingestion upsert.
3. `T-063`: `source_scan` 주기 job과 target별 증분 수집.
4. `T-064`: Gemini URL 요약, transcript 비교·정리, analysis run 저장.
5. `T-065`: 장소 후보 보강 스키마와 외부 API evidence 저장.
6. `T-066`: 범용 full/incremental feature 수집 API.
7. `T-067`: `python-krtour-map` provider/import 쪽 후속 PR.
8. `T-068`: TripMate curated plan 소비 흐름과 `feature_snapshot` 호환 검증.
9. `T-069`: 통합 검증, E2E, 운영 문서 정리.
