# 아키텍처

본 문서는 `tripmate-agent` 프로젝트의 전체 시스템 설계와 구성 요소 간의 데이터 흐름을 다룬다. 의사결정의 역사는 `decisions.md` (ADR)에서 별도로 관리한다.

---

## 1. 전체 시스템 구조

```
                  ┌────────────────────────────────────────┐
                  │          Next.js Frontend              │
                  │   - 리스트 뷰 / 상세 카드 / 설정         │
                  │   - maplibre-vworld-js 지도 뷰          │
                  └───────────────────┬────────────────────┘
                                      │
                         HTTP REST    │ API 요청
                         (JSON)       │
                                      ▼
                  ┌────────────────────────────────────────┐
                  │          FastAPI Backend               │
                  │   - API 엔드포인트 (Keywords, YouTubers)│
                  │   - Deep Research 트리거 API           │
                  └─────────┬───────────────────▲──────────┘
                            │                   │
                     Read / │ SQLAlchemy        │ DB 갱신
                     Write  │ 2.0 ORM           │
                            ▼                   │
                  ┌───────────────────┐         │
                  │     SQLite3       │         │
                  │   (tripmate.db)   │         │
                  └─────────▲─────────┘         │
                            │                   │
                  ┌─────────┴───────────────────┴──────────┐
                  │            ETL Pipeline                │
                  │   - YouTube 수집기 (search & scraper)  │
                  │   - Gemini AI 요약 (summarize)         │
                  │   - Geocoding API 위치 보정 (geocode)   │
                  └───────────────────┬────────────────────┘
                                      │
                         외부 서비스  │ API 호출
                         (REST/HTTPS) │
                                      ▼
                  ┌────────────────────────────────────────┐
                  │        External APIs                   │
                  │   - YouTube Data API (최소 호출)        │
                  │   - Google Gemini API (요약 / Deep)     │
                  │   - Kakao / Naver Geocoder REST API    │
                  └────────────────────────────────────────┘
```

애플리케이션은 **프론트엔드 Web App**, **FastAPI 백엔드 API 서버**, **SQLite3 데이터베이스**, 그리고 주기적/수동으로 실행되는 **비동기 ETL 파이프라인** 4개의 주요 레이어로 이루어집니다.

---

## 2. ETL 파이프라인 상세 아키텍처

유튜브 여행 영상으로부터 양질의 여행지 정보를 정제하여 DB를 구축하는 ETL 로직은 다음 3단계 파이프라인으로 순차 구동됩니다.

```
[시작]
  │
  ├─► 1단계: 수집 (Extract)
  │     ├── 사용자가 CRUD한 검색 키워드 목록 조회
  │     ├── Gemini API를 활용하여 검색 키워드 보정 및 상세화 (예: "부산 여행" -> "부산 꼭 가봐야 할 맛집 핫플레이스 코스")
  │     ├── 유튜브 검색 API 및 스크래핑 모듈로 신규 영상 탐색
  │     └── 구독 유튜버 / 저장 목록의 업데이트 탐색
  │
  ├─► 2단계: 변환 및 요약 (Transform)
  │     ├── 신규 탐색된 비디오의 캡션/메타데이터 추출
  │     ├── Gemini API에 정제된 프롬프트 전달
  │     ├── 영상 내용 요약 및 실제 언급된 '여행지(장소명/설명)' 추출
  │     └── 임시 장소 레코드를 데이터베이스에 1차 저장 (SQLite3)
  │
  └─► 3단계: 위치 보정 및 적재 (Load)
        ├── DB에서 위치 보정이 완료되지 않은(Geocoded = False) 장소 조회
        ├── 외부 Geocoding REST API (Kakao Local / Naver Maps) 호출
        ├── 불완전한 장소 텍스트를 정밀 주소와 위경도로 변환
        ├── Gemini API를 다시 구동하여 위치 기반 여행지 소개 정보 수정/보완
        └── DB에 최종 완료 상태로 업데이트 (Geocoded = True) [완료]
```

### YouTube API 할당량 관리 전략 (ADR-5)
- YouTube 공식 API는 검색 및 호출 할당량 비용이 매우 크기 때문에, 비공식 스크래핑 라이브러리를 동시 결합하여 활용합니다.
- 수집 대상 비디오 ID는 로컬 DB(`video_cache` 테이블)에 기록하여 이미 처리한 비디오에 대한 Gemini API 및 YouTube API 중복 호출을 원천 차단합니다.

---

## 3. 프론트엔드 컴포넌트 아키텍처

Next.js React Client Component 단에서 VWorld 지도를 선언적으로 표시하기 위해 `maplibre-vworld-js`를 활용합니다.

- **VWorldMap Integration**: `.env`에 정의된 `NEXT_PUBLIC_VWORLD_SERVICE_KEY`를 바인딩하여 백그라운드에서 WMTS 타일을 렌더합니다.
- **상태 관리**:
  - **리스트-지도 동기화**: 리스트 뷰에서 특정 여행지를 호버/클릭하면 지도 뷰 상의 마커가 포커스되거나 바운드가 이동합니다.
  - **Settings Store**: 세팅 화면에서 저장한 Gemini 버전 설정(`gemini-2.0-flash`, `gemini-1.5-pro` 등)은 FastAPI 백엔드의 `settings` API를 통해 SQLite3에 저장되며, ETL 및 Deep Research 구동 시 최우선적으로 참조됩니다.
- **Deep Research 트리거**: 사용자가 특정 여행지를 선택하여 "Deep Research"를 지시하면, 프론트엔드는 FastAPI 백엔드로 즉시 트리거 요청을 전송하고, 백엔드는 Gemini를 활용한 심층 자료 조사 태스크를 백그라운드로 실행한 뒤 완료 시 해당 장소의 상세 소개 정보를 풍부하게 업그레이드합니다.

---

## 4. 데이터베이스 엔티티 구조 (SQLite3)

SQLAlchemy 2.0 매핑에 부합하는 개념적 테이블 구조 설계는 다음과 같습니다.

### 1. `search_keywords` (검색 키워드 CRUD용)
- `id` (Integer, PK)
- `keyword` (String, Unique)
- `is_active` (Boolean)
- `created_at` (DateTime)

### 2. `subscribed_youtubers` (구독 유튜버 CRUD용)
- `id` (Integer, PK)
- `channel_id` (String, Unique)
- `channel_name` (String)
- `is_active` (Boolean)
- `last_scraped_at` (DateTime)

### 3. `video_cache` (비디오 중복 수집 방지 캐시)
- `video_id` (String, PK)
- `title` (String)
- `channel_id` (String)
- `scraped_at` (DateTime)

### 4. `travel_destinations` (최종 추출된 여행지 정보)
- `id` (Integer, PK)
- `name` (String) - 장소명
- `description` (Text) - 요약 정보
- `address` (String) - 지번/도로명 주소
- `latitude` (Float)
- `longitude` (Float)
- `source_video_id` (String, FK)
- `is_geocoded` (Boolean) - Geocoding 완료 여부
- `detailed_research_content` (Text, Nullable) - Gemini Deep Research 결과물
- `created_at` (DateTime)

### 5. `system_settings` (설정 저장소)
- `key` (String, PK) - 예: `gemini_engine_version`
- `value` (String)
- `updated_at` (DateTime)
