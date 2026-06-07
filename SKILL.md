# SKILL — tripmate-agent 에이전트 매뉴얼

> 이 파일은 당신(AI 에이전트)이 작업을 시작하기 전 반드시 읽어야 한다.
> Windows 개발 환경 셋업과 Gemini API, YouTube API 최적화에 대한 팁을 담고 있다.

## 1. 정체성

이 저장소(GitHub 저장소 이름 `tripmate-agent`)는 유튜브 여행 컨텐츠에서 장소 정보를 추출하고 정리하여 여행 지도 서비스를 제공하는 **AI 기반 여행 큐레이션 애플리케이션**이다.
- **프론트엔드**: Next.js (App Router) + React. `maplibre-gl`에 VWorld WMTS raster tile URL을 직접 연결하여 지도 시각화를 구현한다.
- **MCP 서버**: AI 에이전트가 여행지, 키워드, 유튜버, 작업 상태를 조회하고 CRUD, 보정, 병합, 실행 트리거를 수행하는 읽기/쓰기 도구 UX를 제공한다.
- **백엔드**: FastAPI + SQLAlchemy 2.0 + `aiosqlite`. SQLite + SpatiaLite 데이터베이스에 연동하여 비즈니스 데이터, 공간 데이터, 작업 상태를 보관한다.
- **ETL 모듈**: 공식 YouTube Data API v3 검색(Gemini 보정) → 자막/전사/POI 추출(Gemini API) → 대표 프레임 추출(`yt-dlp`/FFmpeg) → 원본 동영상·자막·전사 결과·대표 프레임 RustFS 저장 → 외부 REST API를 통한 Geocoding/Reverse Geocoding을 수행한다.
- **스케줄러**: APScheduler 단일 실행자가 `crawl_runs`의 pending 작업을 claim하고 전면 비동기 파이프라인을 실행한다.
- **미디어 저장소**: RustFS를 별도 로컬 Docker 서비스로 구동하고, 원본 동영상·자막·전사 결과·대표 프레임을 무기한 보존한다.

### 개발 환경 기본 요건

- **운영체제**: Windows 10/11 호스트 직접 빌드 및 평가.
- **Python**: Python 3.10+ 기반 가상환경(`.venv`) 사용.
- **Node.js**: Node.js 20+ LTS 사용.
- **E2E 테스트**: Playwright를 활용하여 Windows에서 실제 동작 테스트.

## 2. 빠른 시작 (Windows PowerShell 기준)

### 백엔드 실행
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```
Windows live 고정 포트는 API `9041`이다.

### 프론트엔드 실행
```powershell
cd frontend
npm install
npm run dev:live
```
Windows live 고정 포트는 Web `9042`이다. 포트가 이미 점유 중이면 프로젝트 루트에서 `.\scripts\start-windows-live.ps1`을 실행해 해당 리스너를 종료하고 다시 띄운다.

### Playwright 테스트 실행
```powershell
cd tests
npm install
npx playwright install
npx playwright test
```

## 3. 절대 하지 말 것 (DO NOT)

1. **`main` 직접 푸시 금지**: 반드시 기능별 feature 브랜치를 생성하여 작업하고 PR을 머지한다.
2. **API 키 평문 커밋 금지**: Gemini API 키, VWorld 서비스 키, YouTube API 키 등은 절대 커밋하지 않는다. `.env.example`만 템플릿으로 제공하고 실제 키는 로컬 `.env`에 보관한다.
3. **YouTube API 할당량 무단 낭비 금지**: 공식 YouTube Data API v3를 기본 수집 경로로 사용한다. 검색 API(`search.list`)는 1회 호출에 100 유닛을 소모하므로:
   - Gemini API를 활용하여 검색 키워드를 조합 및 극도로 최적화한 후 호출 횟수를 조율한다.
   - `playlistItems.list`, `channels.list`, `videos.list`처럼 1 유닛 호출로 해결 가능한 경로를 우선한다.
   - 비공식 검색 크롤러는 기본 설계에서 제외하고, 비공식 의존은 자막 추출과 프레임 추출 구간으로 격리한다.
   - 한 번 수집된 비디오 정보는 SQLite + SpatiaLite 데이터베이스에 캐싱하여 재수집을 배제한다.
4. **FastAPI 비동기 세션 leak 방지**: SQLAlchemy 2.0의 `AsyncSession` 또는 동기 `Session`을 사용할 때 Context Manager(`with` 또는 `async with`)를 사용하거나 Depends 주입 방식을 명확히 준수하여 DB 연결 누수를 막는다.
5. **Windows 비호환 쉘 파일 작성 금지**: 윈도우 환경이므로 `.sh` 파일에 개발 유틸 스크립트를 작성하여 그것으로만 검증하도록 요구하지 않는다. 가급적 Node.js 스크립트(`package.json` scripts)나 Python 스크립트, 혹은 `.ps1` 형태로 크로스 플랫폼을 고려해 작성한다.
6. **`kraddr-geo` 연계 재도입 금지**: 최신 요청에 따라 `kraddr-geo` 연계는 취소되었다. Geocoding/Reverse Geocoding은 VWorld를 최우선으로 하며, VWorld 호출은 `python-vworld-api`의 `AsyncVworldClient`를 직접 사용하고 내부 adapter/wrapper 계층은 만들지 않는다.
7. **RustFS 객체 자동 삭제 금지**: 원본 동영상, 자막, 전사 결과, 대표 프레임은 무기한 보존한다. DB 논리 삭제나 장소 매칭 실패만으로 객체를 삭제하는 로직을 만들지 않는다.
8. **매칭 실패 장소 자동 확정 금지**: 지오코딩 결과가 없거나 모호하면 `needs_review` 후보로 남기고 웹 UI 또는 MCP 도구를 통한 사용자 판단을 요구한다.

## 4. 자주 묻는 작업

### 데이터베이스 스키마 및 CRUD 추가
- **위치**: `backend/app/models/`에 SQLAlchemy 2.0 스타일 모델 정의.
- **설명**: CRUD 관련 엔드포인트는 `backend/app/api/` 폴더 내에 배치하며, 스키마 검증은 Pydantic v2를 사용한다. 원본 미디어는 DB에 직접 넣지 않고 `media_assets`에 RustFS 객체 위치와 체크섬을 저장한다.
- **장소 언급 소스**: 확정 장소가 어느 영상과 유튜버에서 언급되었는지는 `video_place_mappings`와 `youtube_videos` 조인으로 계산한다. 같은 영상에서 같은 장소가 여러 구간에 반복 등장할 수 있으므로 `video_id`, `place_id` 조합은 unique로 가정하지 않는다.
- **장소 export**: 선택 또는 전체 장소 내보내기는 `/api/destinations/export`에서 처리한다. `xlsx`는 장소-언급 행 단위, `gpx`/`kml`은 장소 좌표와 소스 설명 중심으로 생성한다.

### Gemini API 프롬프트 및 엔진 설정
- **위치**: `etl/summarize.py` 및 `etl/search.py`.
- **설명**: 설정값(Gemini 엔진 버전 등)은 DB의 `settings` 테이블 혹은 `.env` 환경 변수에서 동적으로 읽어오도록 구성하며, 프롬프트는 한국어 여행 정보 추출에 맞게 정제한다.

### ETL 복원력 구현
- **위치**: `etl/` 디렉토리와 백엔드 작업 상태 모델.
- **설명**:
  - 검색 키워드는 원본 키워드와 Gemini 파생 키워드를 1:N으로 저장하고 `season_context`를 남긴다.
  - YouTube 검색·메타데이터는 공식 YouTube Data API v3를 사용한다.
  - 자막은 `youtube-transcript-api` → `yt-dlp` 자막 추출 → `faster-whisper` 순서로 폴백한다.
  - 자막 파일, 전사 결과, 원본 동영상 또는 오디오, 대표 프레임은 RustFS에 저장하고 무기한 보존한다.
  - YouTube 영상 설명 원문은 `description_raw`, Gemini 오탈자·문맥 보정 결과는 `description_gemini_corrected`에 분리 저장한다.
  - 장소 설명은 기본 설명과 Gemini 보강 설명(`gemini_enriched_description`)을 분리한다.
  - Gemini POI 추출은 자유 텍스트가 아니라 JSON Schema 기반 결과를 요구한다.
  - 지오코딩은 VWorld → Kakao → Naver 순서로 시도한다. VWorld는 `AsyncVworldClient` 직접 호출, Kakao는 주소 검색 후 공식 키워드 장소 검색 fallback, Naver는 보조 검증으로 사용한다.
  - 장소 카테고리는 Kakao Local 공식 `category_name`을 우선하되, Gemini 후보 카테고리와 VWorld/Naver 주소 맥락을 보조 근거로 삼는다. 근거가 충돌하면 자동 확정하지 않고 검수 큐에 남긴다.
  - 지오코딩 실패 또는 모호한 후보는 `extracted_place_candidates.match_status = needs_review`로 남긴다.
  - 장시간 작업은 `crawl_runs`에 상태, heartbeat, retry_count, last_error를 기록한다.
  - HTTP I/O는 `httpx.AsyncClient`로 작성하고, 블로킹 라이브러리는 executor로 격리한다.

### RustFS 미디어 저장 구현
- **위치**: `etl/` 저장소 계층 또는 `backend/app/services/storage/` 계층.
- **설명**:
  - RustFS 접속 정보는 `RUSTFS_ENDPOINT`, `RUSTFS_ACCESS_KEY`, `RUSTFS_SECRET_KEY`로 주입한다.
  - 기본 버킷은 단일 `krtour-map`이고, 객체 키는 `features/` prefix 아래에 저장한다.
  - 저장 후 `media_assets`에 `storage_provider`, `bucket`, `object_key`, `object_uri`, `sha256`, `size_bytes`, `retention_policy = infinite`를 기록한다.
  - RustFS는 별도 로컬 Docker 서비스로 실행하며 상태 확인은 `/health` 또는 `/health/live`를 사용한다.

### MCP 서버 도구 추가
- **위치**: `mcp/` 디렉토리 및 FastAPI 도메인 서비스.
- **설명**:
  - 읽기 도구는 여행지 검색, 상세 조회, 영상별 장소 조회, ETL 상태 조회, 실패 작업 조회를 제공한다.
  - 쓰기 도구는 키워드/유튜버/재생목록 CRUD, 지오코딩 재시도, Deep Research 트리거, 여행지 보정, 중복 병합을 제공한다.
  - 매칭 실패 후보 보정을 위해 `review_unmatched_place`, `resolve_place_candidate` 계열 도구를 제공한다.
  - 쓰기 도구는 Pydantic 스키마 검증, 멱등 키, 감사 로그 기록을 반드시 거친다.

### Playwright E2E 시나리오 생성
- **위치**: `tests/e2e/` 디렉토리에 `.spec.ts` 파일 추가.
- **설명**: `tests/playwright.config.ts`의 `webServer`가 backend `127.0.0.1:18080`과 frontend `127.0.0.1:13100`을 자동 기동한다. 테스트 전용 DB는 `tests\.tmp\e2e.db`이며, 시나리오는 REST API와 화면 접근성 이름을 직접 사용하고 E2E 전용 adapter/wrapper를 만들지 않는다.

## 5. 도메인 어휘

| 용어 | 정의 |
|------|------|
| **Deep Research** | 사용자가 선택한 특정 여행지에 대해 Gemini API를 활용하여 보다 정밀하고 광범위한 세부 조사를 수행하고 데이터베이스를 업데이트하는 기능. |
| **YouTube Curation** | 키워드 CRUD 및 유튜버 CRUD를 통해 등록된 탐색 소스를 바탕으로, 효율적으로 신규 업데이트를 수집하고 여행 관련성 정보를 발라내는 로직. |
| **maplibre-gl + VWorld WMTS** | 공개 npm 래퍼 의존 없이 VWorld 베이스맵 타일을 MapLibre GL JS raster source로 직접 연결하는 지도 구성. |
| **MCP 서버 UX** | AI 에이전트가 브라우저 없이도 여행 데이터베이스를 읽고 쓰는 도구 기반 사용자 경험. |
| **Geocoding API** | YouTube 영상 설명 속 불완전한 텍스트 장소명을 VWorld 우선, Kakao Local 키워드 장소 검색 fallback, Naver 보조 검증으로 표준 주소 및 위경도에 매핑하는 외부 API 경로. |
| **Reverse Geocoding API** | 위경도 좌표를 `python-vworld-api`의 `AsyncVworldClient`로 행정 주소, 도로명 주소, 지번 주소에 매핑하는 외부 API 경로. |
| **SpatiaLite** | SQLite에 공간 함수와 R-Tree 인덱스를 더해 반경 검색과 중복 장소 탐지를 지원하는 임베디드 공간 DB 확장. |
| **RustFS** | 원본 동영상, 자막, 전사 결과, 대표 프레임을 S3 호환 API로 저장하는 별도 로컬 Docker 객체 저장소. |
| **media_assets** | RustFS 객체의 버킷, 키, URI, 체크섬, 크기, 보존 정책을 DB에 기록하는 메타데이터 테이블. |
| **extracted_place_candidates** | Gemini가 추출했지만 자동 매칭되지 않았거나 사용자 검수가 필요한 장소 후보 테이블. |
| **crawl_runs** | Web REST, MCP, 정기 스케줄러가 공유하는 작업 상태 테이블. |
| **ETL Runner** | 수집(Extract), 요약(Transform), 보정(Load) 단계를 조율하여 백그라운드 또는 CLI 명령으로 전체 여행지 데이터를 자동 갱신해주는 실행 스크립트. |

## 6. 작업 후 체크리스트

- [ ] Python 가상 환경에서 `pytest` 테스트 통과
- [ ] 프론트엔드 TypeScript 오류(`npm run type-check`) 및 린터 체크 통과
- [ ] Windows Playwright E2E 테스트 통과
- [ ] `docs/tasks.md` 및 `docs/journal.md` 문서 최신화
- [ ] PR 제출 및 코드 정합성 검증 확인
