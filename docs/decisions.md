# DECISIONS — Architecture Decision Records

본 문서는 `kor-travel-concierge` 프로젝트의 아키텍처 및 구현 의사결정을 시간순으로 누적한다. 결정이 뒤집힐 때도 이전 기록은 지우지 않고 `superseded by ADR-XXX`로 표시한다.

가독성을 위해 **핵심 구조·기능 ADR은 본문을 그대로 유지**하고, **대체·보류·이력 ADR은 문서 말미 `이력·대체·보류 ADR (요약)` 섹션에 한 줄 요약으로 보존**한다. 어떤 ADR 번호도 사라지지 않으며, 요약으로 옮긴 ADR도 번호·제목·상태(또는 superseded-by 포인터)를 그대로 남긴다.

---

## ADR-1: Next.js (React) 기반의 프론트엔드 및 App Router 채택

- 상태: accepted
- 날짜: 2026-06-03
- 결정자: AI agent, human

### 컨텍스트
사용자는 수집된 유튜브 정보 리스트, 키워드 CRUD, 유튜버 CRUD, 상세 설정 화면 및 인터랙티브한 지도 연동 기능이 포함된 프리미엄 UI가 필요하다. 렌더링 성능이 높고 상태 관리가 용이하며 컴포넌트 단위 개발이 유리한 모던 React 생태계의 도입이 요구되었다.

### 결정
**Next.js 14+ App Router**를 프론트엔드 웹 프레임워크로 채택하고 React Client Component 기반으로 UI 및 상태 관리를 구현한다.

### 근거
- Next.js의 App Router 구조를 도입하여 설정 페이지(`/settings`), 지도/목록 뷰 페이지(`/`) 등으로의 라우팅 구조를 직관적으로 설계할 수 있다.
- 모던 Typography, Layout, Custom CSS를 활용하여 프리미엄 테마를 제공하기 쉽다.
- 브라우저 DOM 조작이 필수적인 지도 라이브러리(`maplibre-gl + VWorld WMTS`, 초기 검토명 `maplibre-vworld-js`)와 Client Component 경계를 명확하게 구분하여 연동할 수 있다.

### 결과 (긍정)
- 최상의 UX를 만족하는 마이크로 애니메이션 및 지도 뷰 결합 UI 제공 가능.
- 페이지 컴포넌트 단위의 폴더 관리로 유지보수성 향상.

### 결과 (부정)
- SSR과 CSR의 경계 설정에 따른 Next.js `'use client'` 지시어의 적절한 배치가 요구된다.

---

## ADR-2: FastAPI 및 SQLAlchemy 2.0 (SQLite3) 백엔드 스택 선정

- 상태: accepted
- 날짜: 2026-06-03
- 결정자: AI agent, human

### 컨텍스트
ETL 파이프라인에서 수집한 데이터는 로컬 데이터베이스에 유연하게 적재되어야 하며, 프론트엔드가 이를 고속으로 조회할 수 있는 REST API 엔드포인트가 필요하다. 또한 윈도우 환경에서 평가 및 조작이 간편해야 한다.

### 결정
Python 기반의 **FastAPI**를 API 백엔드로 선정하고, ORM으로 **SQLAlchemy 2.0**을 사용하여 로컬 파일 기반의 **SQLite3** 데이터베이스에 연동한다.

### 근거
- FastAPI는 비동기 요청 처리에 우수하고 Pydantic v2를 내장하여 엄격한 데이터 유효성 검사 및 OpenAPI 문서를 자동으로 제공한다.
- SQLAlchemy 2.0의 신규 syntax를 활용해 타입 안전하고 현대적인 ORM 쿼리를 작성할 수 있다.
- SQLite3는 별도의 데이터베이스 프로세스 실행(Docker, 외부 호스팅 등)이 불필요하므로 Windows 로컬 환경에서의 포터블한 실행 및 평가에 최적이다.

### 결과 (긍정)
- Windows 환경에서 단일 `.db` 파일로 전체 데이터 관리가 가능하여 배포 및 초기 셋업 비용이 0에 수렴.
- 백엔드 코드 베이스 크기 축소로 인한 신속한 개발 속도.

### 결과 (부정)
- SQLite3는 동시 쓰기(Write) 작업 시 락(Lock)에 걸릴 위험이 있어, 백그라운드 ETL 구동과 사용자 API 호출 간의 Write 정합성 제어가 필요하다. (WAL 모드 도입 검토)

---

## ADR-3: Gemini API 기반의 키워드 정제 및 여행지 정보 지능형 요약

- 상태: accepted
- 날짜: 2026-06-03
- 결정자: AI agent, human

### 컨텍스트
사용자가 정의한 여행 키워드("부산 맛집" 등)로 유튜브를 단순 검색하면 노이즈가 많다. 또한 영상 스크립트나 설명 란에서 실제 지리학적인 장소(식당, 명소)를 추출하고 요약하는 로직을 하드코딩된 정규식으로 처리하는 것은 불가능하다.

### 결정
**Google Gemini API**를 ETL 핵심 LLM 파이프라인 및 Deep Research 모듈로 도입하여 검색 키워드 고도화, 텍스트 요약, 상세 장소 추출, 여행지 백과 수준의 심층 조사(Deep Research)를 수행한다.

### 근거
- Gemini의 뛰어난 한글 이해도와 넓은 Context Window를 활용해 유튜브 자막 전체를 파싱하고 정확한 장소명과 특징을 추출할 수 있다.
- 사용자가 설정 화면에서 Gemini 엔진 버전(`gemini-2.0-flash`, `gemini-1.5-pro` 등)을 커스텀으로 관리 및 저장하도록 함으로써 모델 업데이트에 신속히 적응한다.

### 결과 (긍정)
- 자연어 텍스트에서 불완전한 위치 정형화 성능 극대화.
- 사용자가 선택한 특정 장소에 대한 정교한 "Deep Research"를 트리거하여 매력적인 소개 정보 확장 가능.

### 결과 (부정)
- Gemini API 토큰 소모 비용 발생 및 네트워크 지연(Latency)이 수반된다.

---

## ADR-7: MCP 서버를 읽기/쓰기 UX로 채택

- 상태: accepted
- 날짜: 2026-06-04
- 결정자: AI agent, human

### 컨텍스트
초기 계획은 사람이 브라우저에서 사용하는 웹 UX를 중심으로 작성되었다. 그러나 이 프로젝트는 AI 에이전트가 여행 데이터베이스를 직접 조회하고 운영 작업을 수행하는 자동화 UX도 필요하다. 단순 REST API만으로는 에이전트가 사용할 도구 설명, 입력 스키마, 작업 결과 표현을 일관되게 제공하기 어렵다.

### 결정
FastAPI 백엔드의 도메인 서비스를 재사용하는 **MCP 서버**를 별도 UX 표면으로 제공한다. MCP 서버는 읽기 도구와 쓰기 도구를 모두 제공하며, 웹 UI에서 가능한 주요 운영 작업을 에이전트도 수행할 수 있게 한다.

### 근거
- AI 에이전트가 여행지 검색, 영상별 장소 조회, ETL 상태 확인, 실패 작업 점검을 도구 호출로 수행할 수 있다.
- 검색 키워드, 유튜버, 재생목록, 여행지 보정, 중복 병합, Deep Research 실행 같은 쓰기 작업도 구조화된 스키마와 감사 로그로 관리할 수 있다.
- 웹 UI와 MCP 서버가 같은 도메인 서비스를 호출하면 권한, 검증, 멱등성, 실패 처리 로직을 중복 구현하지 않아도 된다.

### 결과 (긍정)
- 사람용 브라우저 UX와 에이전트용 도구 UX가 같은 데이터와 작업 상태를 공유한다.
- 운영 자동화, 대량 정리, 반복 보정 작업을 에이전트가 안전하게 수행할 수 있다.

### 결과 (부정)
- 쓰기 도구가 실제 DB를 변경하므로 감사 로그, 입력 검증, 멱등 키, 실패 복구 설계가 필수다.

---

## ADR-11: 소형 프로젝트 기준 공식 YouTube Data API 우선

- 상태: accepted
- 날짜: 2026-06-05
- 결정자: AI agent, human

### 컨텍스트
이전 계획은 YouTube Data API 쿼터를 과도하게 우려하여 비공식 검색/스크래퍼를 수집 경로의 주요 백업 수단으로 두었다. 그러나 최신 Google Docs 명세는 1~2인 운영, 동시 사용자 10명 내외, 3~7일 주기 수집을 전제로 한다. 이 규모에서는 일일 10,000 유닛 한도에 도달할 가능성이 낮고, 비공식 검색 크롤러 파손 대응 시간이 더 큰 비용이다.

### 결정
검색과 메타데이터 수집은 공식 YouTube Data API v3를 기본으로 한다. 비공식 의존은 공식 대안이 없는 자막 추출과 대표 프레임 추출에만 격리한다.

구체 기준:

- 키워드 검색: `search.list`
- 재생목록 항목: `playlistItems.list`
- 채널 업로드 목록: `channels.list`
- 영상 상세: `videos.list`
- 자막: `youtube-transcript-api` → `yt-dlp` 폴백
- 자막 최종 폴백: `faster-whisper`
- 대표 프레임: `yt-dlp` 직접 스트림 URL + FFmpeg

### 근거
- 소형 프로젝트에서는 공식 API 쿼터보다 비공식 크롤러 파손 대응 시간이 더 비싸다.
- 공식 API는 응답 계약, 인증, 쿼터, 오류 처리가 명확하다.
- 자막은 공식 captions API가 타인 영상에 적합하지 않으므로 예외적으로 비공식 경로를 둔다.

### 결과 (긍정)
- 수집 경로의 불확실성이 줄어든다.
- 장애 원인이 공식 API 응답, 자막 추출, 전사 폴백으로 분리되어 추적이 쉬워진다.

### 결과 (부정)
- `search.list` 호출은 비용이 높으므로 키워드 확장 수, 수집 주기, 검색 대상 수를 설정으로 제한해야 한다.

---

## ADR-13: 전면 asyncio와 APScheduler 단일 실행자 채택

- 상태: accepted
- 날짜: 2026-06-05
- 결정자: AI agent, human

### 컨텍스트
YouTube API, Gemini, 지오코딩, DB 접근은 대부분 네트워크 또는 파일 I/O 대기다. 기존 문서에는 작업 상태 추적과 stale 재시도는 있었지만, 실행 주체가 API 서버, MCP 서버, 스케줄러 사이에서 어떻게 일원화되는지가 명확하지 않았다.

### 결정
백엔드와 ETL은 전면 `asyncio` 기반으로 작성한다. REST API, MCP 서버, 정기 스케줄러는 모두 `crawl_runs` 작업 행을 생성하거나 조회하고, 실제 실행은 APScheduler 기반 scheduler 실행자가 단일 claim 방식으로 처리한다.

T-063 이후 APScheduler interval job 정의는 SQLAlchemyJobStore로 PostgreSQL에
저장한다. 이 persistent job store는 `crawl-run-worker`, `source-scan-enqueue` 같은
주기 job 정의와 next run time만 보존하며, 실제 작업 payload, heartbeat, 재시도,
완료/실패 상태의 source of truth는 계속 `crawl_runs`다.

동기·블로킹 라이브러리는 다음처럼 격리한다.

- `yt-dlp`: executor
- FFmpeg subprocess: executor 또는 비동기 subprocess 래퍼
- `faster-whisper`: CPU/GPU 부하에 따라 프로세스풀 검토
- SpatiaLite 동기 호출: 필요한 경우 executor로 격리

### 근거
- API/MCP 요청은 즉시 `job_id`를 반환해야 하며 장시간 수집을 직접 수행하면 안 된다.
- 단일 실행자가 pending 작업을 claim하면 소형 단계에서 분산 락이 필요 없다.
- 하나의 비동기 파이프라인을 공유하면 REST, MCP, 정기 크롤 경로가 어긋나지 않는다.

### 결과 (긍정)
- 작업 생성과 작업 실행의 책임이 분리된다.
- 중복 실행과 API 요청 타임아웃 위험이 줄어든다.

### 결과 (부정)
- executor 경계, 동시성 상한, 취소 처리, heartbeat 갱신을 구현 규칙으로 강제해야 한다.

---

## ADR-15: RustFS 기반 원본 미디어 저장과 무기한 보존

- 상태: accepted
- 날짜: 2026-06-05
- 결정자: AI agent, human

### 컨텍스트
ETL은 자막 파일, 전사 결과, 대표 프레임뿐 아니라 필요 시 원본 동영상 또는 오디오 파일도 확보한다. 이 파일들은 SQLite DB에 넣기에는 크고, 로컬 파일 경로만 저장하면 Docker 컨테이너와 Windows 호스트 사이의 경로 정합성이 깨지기 쉽다. 사용자는 받은 동영상 및 자막 파일을 RustFS에 저장하고, 보존 기간을 무기한으로 하며, RustFS를 별도의 로컬 Docker 서비스로 구동하도록 요구했다.

### 결정
대용량 미디어 파일 저장소로 S3 호환 RustFS를 채택한다. RustFS는 `api`, `mcp`, `scheduler` 애플리케이션 컨테이너에 내장하지 않고 별도의 로컬 Docker 서비스로 구동한다.

초기 저장 대상은 다음이다.

- 다운로드한 원본 동영상 또는 오디오 파일
- `youtube-transcript-api`, `yt-dlp`, `faster-whisper`로 확보한 자막·전사 결과 파일
- FFmpeg으로 추출한 대표 프레임 JPEG

SQLite + SpatiaLite에는 `media_assets` 테이블을 두고 RustFS 버킷, 객체 키, URI, MIME 타입, 파일 크기, SHA-256 체크섬, 보존 정책만 저장한다. 보존 정책 값은 기본적으로 `infinite`이며 자동 lifecycle 삭제를 설정하지 않는다.

### 근거
- DB 파일 크기 증가와 백업 시간을 통제할 수 있다.
- Docker 컨테이너 간 파일 경로 공유 문제를 S3 호환 API로 단순화할 수 있다.
- 자막·원본 미디어를 무기한 보존하면 Gemini 재처리, 프롬프트 개선, 장소 재검수 시 외부 YouTube 상태에 덜 의존한다.
- RustFS를 별도 서비스로 분리하면 앱 재배포와 객체 저장소 수명 주기를 독립적으로 운영할 수 있다.

### 결과 (긍정)
- 대용량 파일과 구조화 데이터를 분리해 SQLite 운영 안정성이 높아진다.
- 수집 결과를 재처리할 때 같은 원본 파일과 자막을 재사용할 수 있다.
- 추후 S3 호환 객체 저장소로 이전할 때 저장 계층 추상화가 쉬워진다.

### 결과 (부정)
- 로컬 Docker 서비스와 접근 키, 버킷 초기화 절차가 추가된다.
- 무기한 보존은 디스크 사용량 증가를 의미하므로 운영 패널에서 저장 용량과 객체 수를 보여줘야 한다.

---

## ADR-16: 장소 매칭 검수 UX와 Gemini 설명 보정 필드 분리

- 상태: accepted
- 날짜: 2026-06-05
- 결정자: AI agent, human

### 컨텍스트
영상 자막과 설명에서 추출한 장소명은 불완전하거나 애매할 수 있다. Kakao, Naver, VWorld 공급자가 결과를 찾지 못하거나 후보가 여러 개인 경우 자동 확정하면 잘못된 좌표와 주소가 DB에 남는다. 또한 YouTube 영상 설명에는 오탈자와 광고성 문구가 섞여 있어 원문 보존과 Gemini 보정 결과를 분리할 필요가 있다.

### 결정
매칭되지 않은 장소는 자동으로 `travel_places`에 확정하지 않고 `extracted_place_candidates`에 저장한다. 웹 UI에는 "매칭 검수" 큐를 제공해 사용자가 원문, Gemini 추출명, 위치 단서, 후보 주소, 영상 타임스탬프를 보고 직접 장소명·주소·좌표·카테고리를 수정하거나 제외 처리할 수 있게 한다. MCP에도 동일한 보정 도구를 제공한다.

영상 설명과 장소 설명은 다음처럼 원문과 AI 보정 결과를 분리한다.

- `youtube_videos.description_raw`: YouTube 영상 설명 원문
- `youtube_videos.description_gemini_corrected`: Gemini가 오탈자와 문맥을 보정한 영상 설명
- `travel_places.gemini_enriched_description`: Gemini가 추가·보강한 장소 설명
- `travel_places.description_review_status`: AI 생성 설명의 사람 검수 상태

### 근거
- 원문과 보정 결과를 분리해야 Gemini 오류를 추적하고 재처리할 수 있다.
- 자동 지오코딩이 실패한 후보를 사람이 확정하면 데이터 품질이 올라간다.
- 웹 UI와 MCP가 같은 후보 테이블과 감사 로그를 쓰면 사람 검수와 에이전트 자동화가 충돌하지 않는다.

### 결과 (긍정)
- 잘못 매칭된 장소가 지도에 바로 노출되는 위험이 줄어든다.
- 사용자가 판단한 수정값을 이후 유사 후보 매칭 근거로 활용할 수 있다.
- 영상 설명 원문, Gemini 보정 설명, 장소 보강 설명의 책임 경계가 명확해진다.

### 결과 (부정)
- 장소 확정 전 단계가 추가되어 UI와 작업 상태 모델이 복잡해진다.
- 수동 검수 전까지 일부 장소는 지도에 표시되지 않거나 "검수 필요" 상태로만 보인다.

---

## ADR-18: 단일 호스트 Docker Compose 실행 계약

- 상태: accepted (ADR-23과 2026-06-12 포트 고정 계약으로 보강)
- 날짜: 2026-06-05
- 결정자: AI agent

> 보강(2026-06-09, ADR-23): 본 계약 중 `ensure-windows-ffmpeg.ps1` 기반 호스트 FFmpeg 부트스트랩, Windows live 재시작 PowerShell 스크립트 항목은 ADR-23으로 대체되었다. FFmpeg은 컨테이너 `/usr/bin/ffmpeg`로 단일화했으며 PowerShell 스크립트는 제거했다.
>
> 보강(2026-06-12): 로컬/WSL2 Docker host port는 API `12401`, 추가 MCP `12402`, Web UI `12405`, RustFS S3 API `12101`, RustFS 콘솔 `12105`로 고정한다. PostgreSQL/PostGIS 접속 포트는 표준 `5432`를 사용한다. 이 repo Compose는 기본적으로 `api`/`mcp`/`scheduler`/`frontend`만 띄우고, RustFS는 같은 host의 별도 고정 Docker 서비스로 둔다. 앱 컨테이너에서 호스트 DB는 `host.docker.internal:5432`, 외부 RustFS는 `http://host.docker.internal:12101`로 접근한다. 선택형 내장 RustFS는 `embedded-rustfs` profile에서만 사용한다. 포트 override 변수는 Compose 호환성 때문에 남기지만 일반 개발·검증·라이브 실행에서는 고정값을 바꾸지 않는다.

### 컨텍스트
T-014 통합 검증에서 Windows 호스트에는 이미 다른 로컬 프로젝트가 `3000`, `8000`, `12101`, `12105` 포트를 사용 중일 수 있음이 확인되었다. 또한 RustFS는 호스트에서 접근하는 포트와 컨테이너 내부 서비스 포트가 다르며, MCP 서버는 로컬 `stdio` transport로는 Compose에서 장기 실행 서비스가 되기 어렵다. API, MCP, scheduler가 같은 SQLite 파일을 공유하며 동시에 시작하면 테이블 생성과 SpatiaLite 초기화가 충돌할 수도 있다.

### 결정
Docker Compose 실행 계약을 다음으로 확정한다.

- RustFS는 이 repo Compose의 기본 서비스가 아니라 별도 고정 Docker 서비스로 실행한다. 호스트 포트는 S3 API `12101`, 콘솔 `12105`로 고정하고, RustFS 컨테이너 자체의 내부 포트는 S3 API `9000`, 콘솔 `9001`을 유지한다.
- 앱 컨테이너의 `RUSTFS_ENDPOINT`는 기본적으로 `http://host.docker.internal:12101`로 override하고, 컨테이너 밖 Linux/WSL2에서 직접 실행하는 `.env` 기본값은 `http://127.0.0.1:12101`으로 둔다. `http://rustfs:9000`은 선택형 `embedded-rustfs` profile에서만 사용한다.
- 미디어 자산은 단일 `kor-travel-concierge` 버킷과 `features/` prefix를 사용한다. 공개 객체 URL은 `http://127.0.0.1:12101/kor-travel-concierge` 기준으로 조립한다.
- API와 Web의 고정 포트는 각각 `12401`, `12405`다. Compose 내부 포트는 API `8000`, Web `3000`을 유지하되 host port 기본값을 `12401`, `12405`로 매핑한다.
- Docker Compose의 `CORS_ALLOW_ORIGINS`는 `.env` 값을 우선하며, 기본값에는 Web 고정 포트 `12405`, 로컬 개발 `3000`, Playwright E2E `13100`의 `localhost`와 `127.0.0.1` origin을 포함한다.
- `scripts/start-live.sh`는 이 repo가 소유한 고정 포트(`12401`/`12402`/`12405`)를 기동 전에 정리한다. RustFS 포트 `12101`/`12105`는 외부 서비스가 소유하므로 기본 회수 대상이 아니다.
- `RUSTFS_HOST_PORT`, `RUSTFS_CONSOLE_HOST_PORT`는 선택형 `embedded-rustfs` profile 호환성을 위해 남기고, `API_HOST_PORT`, `MCP_HOST_PORT`, `FRONTEND_HOST_PORT`는 repo 서비스 포트 변수로 남긴다. 일반 실행에서는 고정값을 유지한다.
- Compose의 MCP 서버는 `streamable-http` transport를 사용하고 `0.0.0.0:12402/mcp`로 실행한다. 로컬 개발 기본값은 기존처럼 `stdio`로 유지한다.
- API 서비스에 `/health` healthcheck를 두고, MCP/scheduler/frontend는 API healthy 이후 시작한다.
- RustFS smoke 검증은 기본 버킷 생성과 객체 업로드·조회까지 수행하되, 무기한 보존 원칙에 따라 smoke 객체도 자동 삭제하지 않고 같은 key로 덮어쓴다.

### 근거
- 호스트 포트와 컨테이너 내부 포트를 분리하면 기존 로컬 서비스와 충돌하지 않고 검증할 수 있다.
- Compose 내부에서 `localhost`를 사용하면 앱 컨테이너 자신을 바라보므로 RustFS 서비스명 endpoint가 필요하다.
- MCP `stdio`는 컨테이너 서비스로 실행하기에 적합하지 않으며, `streamable-http`가 health와 접근성을 확인하기 쉽다.
- API가 DB 스키마를 먼저 초기화하면 SQLite DDL race와 SpatiaLite 초기화 경고를 줄일 수 있다.

### 결과 (긍정)
- 단일 호스트에서 `rustfs`, `api`, `mcp`, `scheduler`, `frontend`를 반복 실행·검증할 수 있다.
- 고정 포트 계약이 문서·Compose·검증 스크립트에 함께 반영되어 접속 URL 혼선을 줄인다.
- RustFS 버킷과 객체 저장 경로가 실제 S3 API 수준에서 검증된다.

### 결과 (부정)
- `.env`의 호스트용 endpoint와 Compose 컨테이너 endpoint가 다르므로 문서와 스크립트가 이 차이를 계속 명확히 설명해야 한다.
- MCP endpoint는 일반 브라우저 GET에서 406을 반환할 수 있어, 단순 HTTP 200 health 대신 port listening 또는 MCP client protocol로 확인해야 한다.

---

## ADR-19: VWorld 우선 지오코딩과 `python-vworld-api` 직접 사용

- 상태: accepted
- 날짜: 2026-06-05
- 결정자: 사용자, AI agent

### 컨텍스트
최신 요청에서 지오코딩·역지오코딩은 VWorld API를 최우선으로 사용하고, `F:\dev\python-vworld-api` 로컬 패키지를 활용하라는 요구가 추가되었다. 동시에 adapter/wrapper는 만들지 않거나 필요하더라도 최소화해야 한다. Kakao는 공식 [Local API 개발 가이드](https://developers.kakao.com/docs/ko/local/dev-guide)의 `키워드로 장소 검색` 기능을 사용해야 한다.

### 결정
- VWorld 호출은 `python-vworld-api`의 `AsyncVworldClient`를 직접 사용한다.
- 내부에는 별도 `VWorldGeocoder`/`VWorldReverseGeocoder` adapter class를 두지 않는다. 서비스 함수는 `AsyncVworldClient`를 직접 받고, 응답 dict를 내부 `GeocodeCandidate`와 주소 dict로 바꾸는 최소 변환 함수만 둔다.
- `backend/requirements.txt`에는 Docker 이미지에 `git` 바이너리를 요구하지 않는 `python-vworld-api` GitHub archive commit pin을 추가한다. 로컬 패키지 변경분 검증이 필요할 때만 `pip install -e F:\dev\python-vworld-api`로 editable 설치한다.
- 지오코딩 우선순위는 VWorld → Kakao → Naver로 둔다.
- Kakao는 주소 검색을 먼저 호출하고 결과가 없을 때 공식 Local API의 `GET /v2/local/search/keyword.json` 키워드 장소 검색을 사용한다. 장소명, 도로명 주소, 지번 주소, 카테고리를 후보에 보존한다.
- Naver는 모호한 후보의 좌표 근접 검증과 최종 fallback으로만 사용한다.

### 근거
- VWorld가 국내 주소·좌표 변환과 공공 공간 데이터 보강의 기준 경로가 되면 지도·역지오코딩 결과와 일관성이 높아진다.
- 이미 존재하는 `python-vworld-api` 클라이언트를 직접 쓰면 URL 조립, 인증 key 주입, 좌표 순서 실수를 줄일 수 있다.
- 내부 wrapper를 줄이면 외부 클라이언트 API와 우리 코드 사이의 중복 추상화가 줄어든다.
- Kakao 키워드 장소 검색은 주소 문자열이 아니라 POI명·업체명으로 추출된 후보를 보완하는 데 적합하다.

### 결과 (긍정)
- VWorld 호출 경로가 단순해지고 테스트 fake도 `AsyncVworldClient`의 공개 메서드만 흉내내면 된다.
- Kakao fallback이 주소 검색 실패 시 POI명 기반 후보를 확보할 수 있다.
- `kraddr-geo` 미연계 방침과 최신 공급자 우선순위가 코드·문서에 명확해진다.

### 결과 (부정)
- `python-vworld-api`가 아직 PyPI 배포본으로 확인되지 않아 GitHub archive commit pin 또는 로컬 editable 설치를 관리해야 한다.
- VWorld 장애나 할당량 문제 시 Kakao/Naver fallback으로 넘어가기 전 오류 처리 정책을 계속 세밀하게 조정해야 한다.

---

## ADR-22: 장소 언급 소스 집계와 export 계약

- 상태: accepted
- 날짜: 2026-06-07
- 결정자: 사용자, AI agent

### 컨텍스트
사용자는 확정 장소가 어느 YouTube 영상과 어느 유튜버에서 언급되었는지 확인하고, 같은 장소가 여러 번 등장하는 경우 그 횟수로 정렬하며, 선택 또는 전체 장소를 `xlsx`, `gpx`, `kml`로 내보내길 원했다. 또한 장소 카테고리를 추가하고, Kakao 검색 기반 추정이 적절한지 검토가 필요했다.

### 결정
- 장소 언급 근거는 새 테이블을 만들지 않고 기존 `video_place_mappings`와 `youtube_videos`를 집계한다.
- 같은 영상 안에서 같은 장소가 여러 구간에 반복 등장할 수 있으므로 `video_place_mappings`의 `video_id`, `place_id` unique 제약을 제거한다.
- `/api/destinations`는 `mention_count`, `source_channel_count`, `source_videos`를 반환하고 `sort=mention_count|latest|name|category`를 지원한다.
- `/api/destinations/export`는 `format=xlsx|gpx|kml`, 선택 ID 목록(`ids`)을 받아 선택 장소만 내보내며, ID가 없으면 전체 장소를 내보낸다.
- `xlsx`는 장소-언급 행 단위로 영상 제목, 유튜버, URL, 타임스탬프, 요약을 포함한다. `gpx`/`kml`은 지도 앱 호환성을 우선해 장소별 waypoint 또는 placemark를 만들고, 언급 소스는 설명 필드에 넣는다.
- 카테고리 추정은 Kakao Local 공식 `category_name`을 1순위 근거로 사용한다. 다만 Gemini가 문맥에서 추출한 `candidate_category`, VWorld 주소·행정 맥락, Naver 보조 검증 결과를 함께 비교하고, 충돌하거나 신뢰도가 낮으면 자동 확정하지 않고 검수 큐에 남긴다.

### 근거
- `video_place_mappings`는 이미 영상, 장소, 후보, 타임스탬프, 대표 프레임을 연결하는 도메인 테이블이다. 이 테이블을 집계하면 웹, MCP, export가 같은 기준으로 언급 횟수를 계산할 수 있다.
- 같은 영상에서 장소가 여러 번 등장하는 것은 여행 브이로그와 맛집 투어에서 자연스러운 데이터다. unique 제약을 유지하면 반복 등장 횟수와 구간별 타임스탬프를 잃는다.
- Kakao Local은 국내 POI 업종 카테고리가 강하지만, 관광지·자연지명·행정구역성 장소는 Gemini 문맥 또는 VWorld 주소 맥락이 더 안정적일 수 있다.
- `xlsx`는 사람이 검토하기 좋은 표 형식이고, `gpx`/`kml`은 지도·내비게이션 도구와 교환하기 좋다.

### 결과 (긍정)
- 사용자는 장소별로 어느 영상과 유튜버에서 언급되었는지 웹 UI와 export 파일에서 확인할 수 있다.
- 여러 영상 또는 같은 영상의 반복 언급이 `mention_count`에 반영되어 인기·중복 등장 장소를 우선 검토할 수 있다.
- 카테고리 자동 추정의 공급자별 책임이 명확해지고, 불확실한 결과를 검수 큐로 넘기는 기존 품질 원칙이 유지된다.

### 결과 (부정)
- 기존 DB에 이미 생성된 unique index가 있는 경우에는 별도 스키마 마이그레이션 또는 DB 재초기화가 필요할 수 있다.
- `mention_count`는 매핑 행 수 기준이므로 ETL이 같은 후보를 중복 생성하지 않도록 후보 멱등성은 계속 관리해야 한다.
- GPX/KML은 표 형식보다 속성 표현력이 낮아 상세 소스 목록은 설명 문자열에 직렬화된다.

---

## ADR-23: Windows 네이티브 실행 배제와 Linux Docker/WSL 전용 실행 모델

- 상태: accepted
- 날짜: 2026-06-09
- 결정자: 사용자, AI agent

> 보강(2026-06-28, ADR-33): 개발·검증·리포지토리 작업 명령은 `git`, `gh`,
> codegraph 계열 분석 명령까지 포함해 모두 WSL2(Ubuntu)를 포함한 Linux bash에서
> 실행한다. E2E Playwright는 Windows 호스트 고정 예외가 아니라 n150 live/Linux
> 환경에서 우선 실행하고, 불가할 때만 Windows 호스트 fallback을 사용한다.

### 컨텍스트
초기 설계는 Windows 호스트에서 직접 빌드·평가하는 것을 전제로 했고(ADR-6), 이를 위해 PowerShell 라이브 런처(`scripts/start-windows-live.ps1`), Windows용 FFmpeg 자동 다운로드 스크립트(`scripts/ensure-windows-ffmpeg.ps1`), 호스트와 컨테이너 FFmpeg 경로 이원화(`FFMPEG_PATH` vs `DOCKER_FFMPEG_PATH`), `.mjs`·playwright 설정의 `process.platform === 'win32'` 분기 등 Windows 전용 자산이 누적되었다. 이 경로는 공급망 검증(FFmpeg 아카이브 해시), 라이브 포트 점유 프로세스 종료, Python launcher fallback 등 Windows 고유의 복잡도와 운영 부담을 키웠다. 단일 호스트 Docker Compose 실행 계약(ADR-18)이 이미 자리잡았으므로, 실행·평가 환경을 하나로 수렴할 필요가 있었다.

### 결정
- 실행/평가 환경은 **Linux Docker 전용**으로 한다. Windows 네이티브 실행 경로는 배제한다.
- Windows 호스트 사용자는 **WSL2(Ubuntu) 안에서 Linux/Docker로 구동**한다. 모든 신규 스크립트·명령은 bash·Linux 기준으로 작성하고 PowerShell(`*.ps1`) 전용 자산은 제거하거나 bash로 대체한다.
- 기본 실행은 단일 호스트 Docker Compose(ADR-18): `docker compose up -d --build`로 `api`/`mcp`/`scheduler`/`frontend`를 띄우고, RustFS는 외부 고정 Docker 서비스로 사용한다. Compose host port는 고정 `12401`(API)/`12402`(MCP)/`12405`(Web)을 유지하고, 외부 RustFS는 `12101`·`12105`를 유지한다. 컨테이너 내부 포트는 API `8000`, Web `3000`을 유지하므로 host가 `12401→8000`, `12405→3000`으로 매핑한다.
- `scripts/start-live.sh`는 이 repo가 소유한 고정 포트(`12401`/`12402`/`12405`)를 기동 전에 정리한다. RustFS 포트 `12101`/`12105`는 외부 서비스가 소유하므로 기본 회수 대상이 아니다.
- FFmpeg은 컨테이너 이미지(`Dockerfile.python` apt)가 `/usr/bin/ffmpeg`로 제공한다. 호스트 자동 다운로드·경로 분기와 `DOCKER_FFMPEG_PATH` 이원화를 제거하고 단일 override 변수 `FFMPEG_PATH`(기본 `/usr/bin/ffmpeg`)만 둔다.
- PowerShell 라이브/FFmpeg/검증 스크립트는 삭제하고, Compose smoke 검증은 bash `scripts/verify-docker-compose.sh`, 라이브 기동은 bash `scripts/start-live.sh`로 대체한다.
- 이 결정은 `AGENTS.md`의 "Windows 호스트 직접 진행" 정책과 기존 DO-NOT #4("Windows 비호환 명령어 금지")를 뒤집는다. DO-NOT #4는 반대 방향(= bash/Linux 기준으로 작성, Windows 전용 분기 금지)으로 다시 쓴다.

### 근거
- 실행 환경을 하나(Linux Docker)로 수렴하면 호스트 OS별 분기, 공급망 검증, 포트 점유 처리 같은 Windows 고유 복잡도를 제거할 수 있다.
- ADR-18의 단일 호스트 Compose 계약은 `api`/`mcp`/`scheduler`/`frontend` 앱 런타임과 외부 RustFS 연계를 포괄하므로, 동일 계약을 유일한 실행 경로로 강화하는 것이 자연스럽다.
- WSL2는 Windows에서 Linux/Docker를 그대로 구동하는 표준 경로이므로 Windows 사용자 경험도 끊기지 않는다.

### 결과 (긍정)
- 실행/평가 경로가 단일화되어 문서와 코드가 일관된다. Windows 전용 스크립트·분기 유지보수 부담이 사라진다.
- FFmpeg은 컨테이너가 항상 제공하므로 호스트 바이너리 준비·무결성 검증 단계가 불필요하다.
- bash·Docker 기준 명령으로 통일되어 CI/로컬/평가 환경 간 차이가 줄어든다.

### 결과 (부정)
- Windows 사용자는 WSL2 + Docker 설치가 선행되어야 한다(네이티브 실행 불가).
- ADR-6, T-030, T-041, T-055 등 Windows 전제 작업 산출물(FFmpeg 자동 준비, PowerShell launcher)은 본 ADR로 보정·대체된다. T-027의 고정 포트 `12401`/`12405`는 폐기하지 않고 OS 중립적인 Compose 표준 host port로 유지하며, 포트 회수는 bash `scripts/stop-fixed-ports.sh`로 옮긴다.

### 보강 — Codex 명령 실행 위치 (2026-06-12)
- 에이전트/Codex가 이 저장소에서 실행하는 작업 명령은 WSL2(Ubuntu)를 포함한 Linux bash에서 수행한다.
- 2026-06-28 ADR-33 이후 과거 예외였던 `git` 명령도 Linux 실행 대상에 포함한다.
- `gh`, Docker, Python, Node.js, 테스트, 빌드, 파일 검색·확인, codegraph 계열 인덱싱/분석 명령도 Linux에서 실행한다. 이 규칙은 Windows 네이티브 앱 실행 경로를 되살리지 않기 위한 운영 규칙이다.

### 예외 — E2E Playwright는 n150 우선, Windows fallback (2026-06-28 보강)
- 위 "Linux Docker 전용" 모델은 **애플리케이션 런타임/배포**에 적용된다(backend, frontend, mcp, scheduler, rustfs).
- **E2E Playwright 테스트 하니스는 n150 live/Linux 환경에서 우선 실행한다.** 즉 `cd tests; npm install; npx playwright install; npx playwright test`를 n150 또는 이에 준하는 Linux 환경에서 먼저 실행해 실제 live 배포와 가까운 화면 검증을 수행한다.
- n150 접근, 브라우저 설치, 네트워크, DB, 계정 상태 때문에 n150 검증이 불가능할 때만 Windows 호스트에서 같은 Playwright 스위트를 fallback 실행한다.
- 이 fallback은 Windows 네이티브 **앱**(backend/frontend/mcp/scheduler) 실행 경로나 앱 런타임 코드의 `win32` 분기를 되살리지 않는다. 다만 **E2E 런처 스크립트(`tests/scripts/start-backend.mjs`·`start-frontend.mjs`)는 fallback 하니스 호환성 때문에 OS별 처리(venv interpreter 경로 해석, `taskkill` 기반 자식 프로세스 트리 정리)를 유지할 수 있다.** 이는 테스트 하니스에 한정된 분기이며 앱 코드에는 적용되지 않는다. E2E backend는 `APP_ENV=e2e`로 무인증 동작한다(ADR-24).
- 따라서 ADR-6의 "Playwright E2E를 Windows에서 검증" 의도는 **fallback 하니스 차원으로 축소**되고, 기본 E2E 검증 호스트는 n150 live/Linux로 이동한다.

### 관련
- ADR-18(단일 호스트 Docker Compose 실행 계약)을 유일 실행 경로로 강화한다.
- ADR-6(Windows 환경 Playwright E2E 파이프라인) 중 앱 구동 환경 부분을 supersede 한다. 단, **E2E 테스트 하니스의 Windows 호스트 실행은 n150 실행 불가 시 fallback으로만 유지**한다.
- ADR-24(REST API 버저닝과 외부 호출용 인증)의 `APP_ENV` 기반 로컬 우회는 n150/Windows E2E 하니스(`APP_ENV=e2e`)에 동일하게 적용된다.

---

## ADR-24: REST API 버저닝(`/api/v1`)과 외부 호출용 API 인증(인증 코드)

- 상태: accepted
- 날짜: 2026-06-09
- 결정자: 사용자, AI agent

### 컨텍스트
초기 REST API는 버전 프리픽스 없이 `/api/...` 경로로 노출되었고(`POST /api/harvest`, `/api/destinations` 등), 외부 호출용 인증 장치가 없었다. 단일 호스트 Docker Compose 실행 계약(ADR-18)과 Linux Docker 전용 실행 모델(ADR-23)을 정리하면서, 앱을 외부에 노출하는 배포 시나리오가 현실화되었다. 외부 노출 시에는 (1) 향후 비호환 변경을 안전하게 도입할 버저닝 경계와 (2) 무인증 공개를 막을 최소한의 인증 코드가 필요하다. 동시에 1~2인 소형 프로젝트의 로컬 개발·E2E 흐름은 인증 코드 없이도 마찰 없이 동작해야 한다.

### 결정
- **버전 프리픽스**: 모든 REST 엔드포인트를 `/api/v1` 아래로 옮긴다(`router = APIRouter(prefix="/api/v1", ...)`). 운영 점검용 `GET /health`와 루트 `GET /`는 버전 없이 유지한다. 향후 비호환 변경은 같은 패턴으로 `/api/v2` 라우터를 추가해 도입한다.
- **인증 코드(`X-API-Key`)**: 라우터 전체에 `Depends(require_api_key)`를 걸어 `X-API-Key` 헤더 기반 인증을 적용한다(`ktc.core.security`). 인증은 설정에만 의존하므로 다른 버전 라우터에도 그대로 재사용된다.
- **APP_ENV 기반 로컬 우회**: 새 설정 `APP_ENV`(기본 `local`), `API_AUTH_ENABLED`(기본 `false`), `API_KEYS`(쉼표 구분)를 둔다. `APP_ENV`가 `local`/`test`/`e2e`이면 인증 코드 없이 통과한다. 비-local(예: `production`)에서는 유효한 `X-API-Key`를 요구한다. `API_AUTH_ENABLED=true`이면 환경과 무관하게 인증을 강제한다(로컬에서 인증 동작 검증용).
- **안전 측 실패**: 인증이 필요한 환경인데 `API_KEYS`가 비어 있으면 모든 요청을 401로 거부한다(무인증 노출 방지).
- **외부 배포 활성화**: 외부에 노출하는 운영자는 `.env`/Compose에 `APP_ENV=production`과 `API_KEYS=<쉼표 구분 키>`를 설정한다. `docker-compose.yml`은 `APP_ENV`/`API_AUTH_ENABLED`/`API_KEYS`를 환경 변수로 전달하며 기본값은 로컬 친화적(`local`/`false`/빈 값)이다.
- **프론트엔드 연동**: 브라우저는 API 키를 직접 다루지 않고 same-origin Next BFF Route Handler(`/api/v1/*`, `frontend/src/app/api/v1/[...path]/route.ts`)로 호출한다. BFF가 서버 사이드에서 백엔드(`BACKEND_ORIGIN`)로 프록시하면서 서버 전용 `BACKEND_API_KEY`로 `X-API-Key` 헤더를 주입한다. 키는 브라우저 번들·네트워크에 노출되지 않는다. export(top-level navigation) 다운로드도 BFF를 거치므로 인증 환경에서 401 없이 정상 동작한다.

### 근거
- 버전 프리픽스는 외부 소비자가 생긴 뒤에도 비호환 변경을 안전하게 도입할 경계를 제공한다.
- `APP_ENV` 기반 우회는 소형 프로젝트의 로컬·E2E 마찰을 0으로 유지하면서, 외부 노출 배포에서만 인증을 강제하는 단일 스위치를 준다.
- 인증을 라우터 의존성과 설정에만 의존시키면 헤더 검사 로직이 한 곳에 모이고 버전 라우터 간 재사용이 쉽다.

### 결과 (긍정)
- 외부 노출 배포에 버저닝 경계와 최소 인증이 생긴다. 무인증 공개가 안전 측 실패로 차단된다.
- 로컬/E2E 개발은 인증 코드 없이 그대로 동작한다(`APP_ENV=local`/`e2e`).
- 인증 정책이 설정 한 곳(`Settings.auth_required`)으로 모여 `/api/v2` 등 신규 라우터에도 재사용된다.

### 결과 (부정)
- 엔드포인트 경로가 `/api/v1`로 바뀌어 기존 `/api/...` 경로를 가정한 클라이언트·문서·테스트는 갱신이 필요하다.
- `API_KEYS` 발급·배포·로테이션은 운영자의 추가 책임이 된다(소형 프로젝트 범위에서는 단순 정적 키 목록으로 운용).
- 브라우저 호출이 same-origin BFF를 한 단계 더 거치므로(`frontend`→Next 서버→백엔드) 프론트엔드 컨테이너가 백엔드에 도달할 수 있어야 하고 BFF 프록시 라우트를 유지·관리해야 한다(아래 "보강(2026-06-09)" 참조).

### 보강 (2026-06-09) — 브라우저 키 노출 제거를 위한 same-origin BFF 프록시 (PR #54 리뷰 반영)
- **배경**: PR #54 리뷰에서 두 가지 문제가 제기되었다. (P1-2) `NEXT_PUBLIC_*` 환경 변수는 빌드 시 브라우저 번들에 인라인되어 누구나 볼 수 있으므로 `NEXT_PUBLIC_API_KEY`는 보안 경계가 되지 못한다. (P1-1) export 등 top-level navigation 다운로드는 fetch 헤더를 붙일 수 없어 인증 환경에서 `X-API-Key` 없이 요청되어 401이 발생한다.
- **결정**: 브라우저는 API 키를 더 이상 전송하지 않는다. 프론트엔드는 same-origin Next BFF(catch-all Route Handler `frontend/src/app/api/v1/[...path]/route.ts`)를 호출하고, BFF가 서버 사이드에서 백엔드로 프록시하며 `X-API-Key`를 주입한다.
- **서버 전용 환경 변수**: 키는 `BACKEND_API_KEY`(서버 전용, `NEXT_PUBLIC_*` 아님)로 둔다. 외부 배포 시 이 값은 백엔드 `API_KEYS` 중 하나와 동일해야 한다. 프록시 대상은 `BACKEND_ORIGIN`(서버 전용)으로, Docker Compose에서는 `http://api:8000`, 로컬 기본값은 `http://localhost:12401`이다. `NEXT_PUBLIC_API_KEY`는 제거했다.
- **브라우저 API base**: `NEXT_PUBLIC_API_BASE_URL`은 기본 빈 값으로 두어 브라우저가 same-origin(`/api/v1`)으로 호출하게 한다. 백엔드를 직접 호출해야 하는 경우에만 설정한다.
- **효과**: (P1-2) 키가 브라우저 번들·네트워크에 절대 노출되지 않는다. (P1-1) export 다운로드도 same-origin BFF를 거치므로 인증 환경에서 401 없이 동작한다. 직접/외부(비-브라우저) 호출자는 여전히 `X-API-Key`를 직접 보내야 하며, 로컬 백엔드(`APP_ENV=local/test/e2e`)는 인증을 우회한다.

### 관련
- ADR-13(작업 생성/폴링 REST 흐름)·ADR-22(장소 export 계약)의 엔드포인트는 모두 `/api/v1` 프리픽스 아래로 이동한다(계약 자체는 불변).
- ADR-18/ADR-23의 Docker Compose 실행 계약에 `APP_ENV`/`API_AUTH_ENABLED`/`API_KEYS` 전달을 추가한다.

---

## ADR-25: PostgreSQL/PostGIS 전환과 `python-kraddr-geo` DB 서버 재사용

- 상태: accepted
- 날짜: 2026-06-10
- 결정자: 사용자, AI agent

### 컨텍스트
초기 구현은 SQLite + SpatiaLite를 기준으로 만들어졌다(ADR-12/ADR-17). 그러나 최신 요청에서 사용자는 `kor-travel-concierge`의 DB를 PostgreSQL/PostGIS 기반으로 전환하고, 별도 DB 서버를 새로 만들지 말고 `python-kraddr-geo`가 사용 중인 로컬 PostgreSQL/PostGIS 서버를 활용하라고 지시했다. 동시에 `tripmate`의 POI/curated plan 흐름과 `python-krtour-map`의 feature schema를 확인해 장소 데이터 구조를 보강해야 한다.

참조한 sibling repo 기준:

- `python-kraddr-geo` 개발 PostgreSQL/PostGIS 서버는 host `localhost`, 표준 port `5432`, 개발 사용자 `addr`, 개발 DB `kraddr_geo`를 사용한다.
- `tripmate`의 여행 POI와 curated plan POI는 `feature_id TEXT`와 `feature_snapshot JSONB`로 `python-krtour-map` feature를 참조한다.
- `python-krtour-map`은 `feature.features`, `provider_sync.source_records`, `provider_sync.source_links`, `provider_sync.provider_sync_state`를 중심으로 `FeatureBundle`을 적재한다.

### 결정
- `kor-travel-concierge`의 목표 DB는 PostgreSQL + PostGIS로 전환한다. SQLite + SpatiaLite는 전환 전 legacy 구현으로만 남긴다.
- 로컬 개발 DB 서버는 `python-kraddr-geo`의 PostgreSQL/PostGIS 서버를 재사용한다. 단, `kraddr_geo` DB를 같이 쓰지 않고 별도 DB `kor_travel_concierge`를 생성한다.
- 목표 개발 DSN은 `postgresql+asyncpg://addr:addr@localhost:5432/kor_travel_concierge`로 문서화한다. 실제 값은 `DATABASE_URL`로 주입한다.
- SQLAlchemy 2.0 async 패턴은 유지하되, DB driver와 migration 체계를 PostgreSQL 기준으로 정리한다.
- 스키마 변경은 Alembic으로 관리한다. 기존 경량 `schema_migrations` registry는 SQLite 보정 전용이므로 Postgres 전환 후 제거하거나 Alembic bootstrap으로 흡수한다.
- `travel_places`는 PostGIS `geometry(Point, 4326)` 컬럼과 GiST 인덱스를 가진다. 근접/중복 검색은 `ST_DWithin`을 사용한다.
- PostgreSQL은 FK 컬럼을 자동으로 인덱싱하지 않으므로 YouTube source, 후보, mapping, export ledger의 FK에는 migration에서 명시 인덱스를 둔다.
- scheduler claim, `source_scan`, feature incremental export처럼 상태와 시간 범위를 함께 쓰는 조회는 composite index로 설계한다.
- `crawl_runs` claim은 PostgreSQL의 원자적 update 또는 `FOR UPDATE SKIP LOCKED`를 사용해 단일/다중 worker 양쪽에 안전한 형태로 정리한다.
- `docker-compose.yml`은 앱과 RustFS를 계속 띄우되, DB는 기본적으로 외부 PostgreSQL 서버를 바라보게 한다. repo 내부 PostgreSQL 컨테이너는 필요하면 테스트 전용으로만 추가한다.

### 근거
- 사용자가 DB 서버를 명시했으므로 ADR-20의 “수치 트리거가 생길 때만 전환” 조건보다 최신 사용자 요청이 우선한다.
- PostgreSQL/PostGIS를 도입하면 장소 중복 탐지, 반경 검색, 증분 export cursor, 향후 `python-krtour-map` 연동에 같은 공간 DB 어휘를 쓸 수 있다.
- `python-kraddr-geo` 서버를 재사용하면 로컬에 PostGIS 서버를 중복 운영하지 않아도 된다.
- 별도 DB를 쓰면 `python-kraddr-geo`의 주소 정본 스키마와 `kor-travel-concierge`의 YouTube/ETL 스키마가 충돌하지 않는다.

### 결과 (긍정)
- 공간 검색과 증분 동기화 구현이 PostGIS 기준으로 단순해진다.
- 향후 `python-krtour-map`과 `tripmate`가 소비할 feature 후보 payload를 더 안정적으로 만들 수 있다.
- SQLite 파일 공유, SpatiaLite extension loading, WAL 설정 같은 런타임 분기가 사라진다.

### 결과 (부정)
- 로컬 개발에 PostgreSQL/PostGIS 서버가 필수가 된다.
- 기존 SQLite 개발 DB는 자동 호환 대상이 아니며, 필요하면 별도 one-off migration 또는 재수집을 해야 한다.
- Alembic bootstrap, PostGIS extension 준비, optional real DB integration test가 새 작업 범위로 추가된다.

### 재확인 필요
- `kor_travel_concierge` DB 이름을 그대로 쓸지 사용자가 다른 이름을 원하는지 확인한다.
- SQLAlchemy async driver를 `asyncpg`로 확정할지, `python-kraddr-geo`와 같은 `psycopg` 계열로 맞출지 구현 직전에 확인한다.
- 운영 환경에서 DB 서버를 `python-kraddr-geo`와 계속 공유할지, 로컬 개발에만 공유하고 운영은 별도 DB로 분리할지 확인한다.

### 관련
- ADR-12(SQLite + SpatiaLite 채택)를 supersede 한다.
- ADR-17(SpatiaLite DDL을 ORM 밖에서 관리)은 PostGIS 전환 후 폐기 또는 PostGIS helper로 대체한다.
- ADR-20의 PostgreSQL/PostGIS 전환 유보 결정은 최신 사용자 요청으로 supersede 한다.
- 상세 구현 순서는 `docs/youtube-feature-pipeline-plan.md`와 `docs/tasks.md` T-061 이후 항목을 따른다.

---

## ADR-26: YouTube 장소 후보를 범용 feature 공급원으로 노출

- 상태: accepted
- 날짜: 2026-06-10
- 결정자: 사용자, AI agent

### 컨텍스트
사용자는 `kor-travel-concierge`가 뽑아낸 장소 정보를 TripMate feature 연계 POI로 저장하고, curated plan은 그 POI들의 모음으로 만들 수 있게 하라고 요청했다. 장소 후보에는 YouTube 동영상 정보, 유튜버 정보, 플레이리스트 정보를 연결해야 한다. 또한 `python-krtour-map`에는 이 결과를 feature로 추가하되, `python-krtour-map`이 `kor-travel-concierge`를 주기적으로 긁어가는 구조를 원했다. 따라서 `kor-travel-concierge`는 source provider 역할을 하고, `python-krtour-map`은 feature owner 역할을 유지해야 한다.

### 결정
- `kor-travel-concierge`는 `youtube_channels`, `youtube_playlists`, `youtube_playlist_videos`, `youtube_video_analysis_runs`를 추가해 유튜버·영상·재생목록·분석 실행을 정규화한다.
- 기존 `youtube_videos`는 channel FK, canonical URL, duration, thumbnail, Gemini URL summary, transcript summary, reconciled summary를 갖도록 보강한다.
- 기존 `extracted_place_candidates`와 `video_place_mappings`는 어떤 채널·플레이리스트·분석 실행에서 유래했는지 추적하는 FK/상태 컬럼을 갖는다.
- 범용 full/incremental feature API는 `feature_exports` 같은 export ledger를 사용해 안정적인 `export_id`, sequence cursor, payload hash, reject/tombstone 재전송 상태를 관리한다.
- 주기 scan job(`source_scan`)을 추가한다. 이 job은 active source를 훑고 새 영상 또는 변경 영상을 발견해 수집·분석 작업을 enqueue한다.
- 영상 분석은 두 축으로 수행한다.
  - 자막·전사 기반 POI 추출
  - Gemini에 YouTube URL을 직접 전달한 영상 상세 요약
- 두 결과는 별도 reconcile 단계에서 비교한다. 불일치, 낮은 신뢰도, 지오코딩 충돌은 자동 확정하지 않고 `needs_review`로 남긴다.
- `kor-travel-concierge`는 `/api/v1/features/snapshot`과 `/api/v1/features/changes` API를 제공한다. REST path에는 특정 downstream 이름을 넣지 않는다. `python-krtour-map`은 full snapshot 또는 incremental changes를 선택해 주기적으로 가져가는 첫 consumer다.
- API payload에는 `python-krtour-map`이 `FeatureBundle`을 만들 수 있도록 place, address, coordinate, category suggestion, YouTube evidence, source record metadata를 포함한다.
- `feature_id` 생성과 최종 `feature.features` 적재는 `python-krtour-map` 책임으로 둔다. `kor-travel-concierge`는 안정적인 `export_id`, `source_entity_id`, `raw_payload_hash`를 제공한다.
- TripMate는 직접 `kor-travel-concierge` DB를 보지 않고, `python-krtour-map`에 생성된 `feature_id`와 `feature_snapshot`을 자체 POI row(`app.trip_day_pois`, `app.notice_pois`)에 저장한다. Curated plan은 feature row 자체가 아니라 이 POI row들의 모음이다.

### 근거
- `python-krtour-map`이 feature schema와 `FeatureBundle` 계약을 소유하므로, `kor-travel-concierge`가 feature 테이블에 직접 쓰면 schema 책임이 흐려진다.
- pull 방식은 `python-krtour-map`의 provider cursor, full/incremental sync, source_records/source_links 패턴과 맞는다.
- YouTube 영상/채널/플레이리스트 근거를 별도 테이블로 정규화해야 TripMate POI와 curated plan에서 “왜 이 장소가 추천되었는지”를 설명할 수 있다.
- Gemini URL summary와 transcript 결과를 비교하면 자막 누락, 자동 전사 오류, 영상 설명란 과장 정보를 더 잘 걸러낼 수 있다.

### 결과 (긍정)
- `kor-travel-concierge`는 YouTube 장소 intelligence provider로 독립적으로 발전할 수 있다.
- `python-krtour-map`은 기존 feature/source lineage 모델을 유지하면서 YouTube 기반 장소 후보를 수집할 수 있다.
- TripMate는 feature_id 기반 POI와 curated plan 흐름을 그대로 유지한다.

### 결과 (부정)
- 이 작업은 `kor-travel-concierge`, `python-krtour-map`, `tripmate` 세 repo의 순차 PR이 필요하다.
- category 8자리 코드 mapping, Gemini YouTube URL 입력 안정성, Google API 보강 여부는 구현 전 재확인이 필요하다.
- full/incremental API cursor와 tombstone 정책을 잘못 설계하면 `python-krtour-map` 쪽 중복 feature 또는 누락이 생길 수 있다.

### 재확인 필요
- 2026-06-11 T-068/T-069 정렬에서 TripMate feature 연계 POI와 curated plan 소비 흐름을
  재확인했다. 자동 등록은 하지 않고, admin이 `python-krtour-map`에 생성된 feature를
  선택해 `app.trip_day_pois` 또는 `app.notice_pois`에 `feature_id`와
  `feature_snapshot`으로 저장하는 수동 흐름을 유지한다. Curated plan은 저장된
  POI row들의 모음이다.
- Google Places API를 보강 provider로 도입할지 확인한다. 도입 시 과금, 저장 정책, 라이선스, API 키 이름을 별도 ADR로 확정한다.
- YouTube URL 직접 Gemini 호출의 공식 지원 범위는 T-064 구현 직전에 확인했다.
  공개 YouTube URL은 preview 기능이며 REST payload는 `file_data.file_uri`를
  사용한다. 실제 API key smoke는 아직 남은 확인 항목이다.
- `python-krtour-map` category mapping 표를 어느 repo에서 관리할지 결정한다.
  2026-06-11 T-070에서는 provider↔consumer 순환참조를 피하기 위해
  `python-krtour-map` 8자리 코드표를 `kor-travel-concierge`에 복사해 사용한다.

### 관련
- ADR-22(장소 언급 소스 집계와 export 계약)를 확장한다.
- ADR-24(`/api/v1`와 `X-API-Key`)의 외부 호출 인증을 범용 feature pull API에도 적용한다.
- 상세 API와 테이블 후보는 `docs/youtube-feature-pipeline-plan.md`를 따른다.

---

## ADR-27: 포트 대역을 통합 `kor-travel-docker-manager` 정책(126xx)으로 정렬

- **상태**: 채택 (2026-06-14)
- **맥락**: `kor-travel-docker-manager`가 TripMate 계열 통합 로컬 인프라의 포트 정책을 단일 출처로 정의한다(`docs/ports.md`, `config/docker-targets.yml`). 로컬 포트는 `12000`부터 target마다 `100` 단위 대역을 배정하고 API는 `+1`, 추가 서비스는 `+2`부터, Web UI는 `+5`를 쓴다. `kor-travel-concierge`에는 `conc` 대역 `12600-12699`가 배정되어 API `12601`, MCP `12602`, Web UI `12605`가 정책 포트다. 통합 docker-manager compose는 이미 이 포트로 concierge를 빌드·기동했으나, concierge repo 자체 설정(`docker-compose.yml`, `.env.example`, 스크립트, 문서)은 이전 ADR-18/ADR-23의 `124xx` 고정 포트를 사용해 불일치가 있었다.
- **결정**:
  - concierge host 고정 포트를 API `12601`(컨테이너 `8000`), MCP `12602`(컨테이너 내부 streamable-http bind `12402` 유지), Web `12605`(컨테이너 `3000`)로 이관한다.
  - 컨테이너 내부 포트와 MCP bind 포트(`MCP_PORT=12402`)는 유지한다. 참조 서비스 포트는 통합 정책과 이미 일치하므로 유지한다(PostgreSQL host `5432`, RustFS S3 API `12101`/콘솔 `12105`).
  - 본 ADR은 ADR-18(단일 호스트 Compose)과 ADR-23(Linux Docker 실행 모델)에 명시된 `124xx`(`12401`/`12402`/`12405`) 고정 포트 값을 대체한다. 두 ADR의 나머지 실행 모델 결정은 그대로 유효하다.
  - 포트 정책의 단일 출처는 `kor-travel-docker-manager`이며 concierge는 이를 따른다. 새 포트 변경은 docker-manager 정책을 먼저 갱신한 뒤 본 repo에 반영한다.
- **결과 (긍정)**: 통합 docker-manager 스택과 concierge 단독 `docker compose`가 동일한 포트 계약을 사용한다. 대역 충돌 없이 geo/map/pinvi 등 형제 서비스와 공존한다.
- **결과 (부정)**: 과거 문서·이력에 남은 `124xx` 참조와 새 `126xx`가 공존한다(이력은 의도적으로 보존). 외부에서 `124xx`를 가정한 사용자 설정/북마크는 갱신이 필요하다.
- **관련**: ADR-18, ADR-23을 보강·대체한다. 포트 정책 출처는 `kor-travel-docker-manager`의 `docs/ports.md`.

---

## ADR-28: 프로덕션 공개 도메인 노출(리버스 프록시 + TLS)과 도메인 비밀 유지

- **상태**: 채택 (2026-06-20)
- **맥락**: 외부 노출 배포에서 다섯 개의 공개 서비스 도메인(Web, REST API, MCP, RustFS S3 API, RustFS 콘솔)을 쓴다. 실제 도메인 값은 외부에 노출하지 않아야 하고(git 커밋 금지), 앱은 기존 단일 호스트 Docker Compose 고정 포트(API `12601`, MCP `12602`, Web `12605`, RustFS `12101`/`12105`, ADR-27)를 그대로 유지한 채 prod에서 그 도메인으로 동작해야 한다. 앱 설정은 이미 CORS(`CORS_ALLOW_ORIGINS`), 인증(`APP_ENV`/`API_KEYS`, ADR-24), RustFS 공개 URL(`RUSTFS_PUBLIC_BASE_URL`/`RUSTFS_CONSOLE_URL`, ADR-15), BFF origin(`BACKEND_ORIGIN`, ADR-24)이 전부 환경변수 기반이라 앱 코드 변경 없이 prod 구성이 가능하다.
- **결정**:
  - **dev/prod 오케스트레이션 구분**: 별도 지시가 없으면 이 repo의 실행/스크립트는 **dev**를 의미한다. dev는 여기에서 직접(`scripts/start-live.sh`/`docker compose`/`ktcctl`) 띄우고 **내부 주소 `127.0.0.1` + 고정 12xxx 포트**로 접속한다. **prod**는 **`kor-travel-docker-manager`**가 도커를 올리고 **공식 도메인**을 적용한다(포트 정책 단일 출처도 docker-manager, ADR-27). prod도 같은 12xxx host 포트를 쓰되 공식 도메인 + TLS 프록시로 노출한다(포트 번호 동일, 접속 주소만 다름).
  - **dev 기동 안전장치**: `scripts/start-live.sh`/`stop-fixed-ports.sh`는 고정 포트가 이미 사용 중이면 **새 포트로 바꾸지 않고**, prod 인스턴스 유무와 무관하게 강제 종료 여부를 사용자에게 묻는다. 거부하면(또는 비대화형이고 `FORCE_KILL_PORTS=1` 미설정) 종료 코드로 빠져 기동을 중지하고 떠 있는 인스턴스를 보존한다. dev 검증/접속 주소는 `127.0.0.1`로 통일한다.
  - **토폴로지**: 단일 호스트 앞에 TLS 종단 **리버스 프록시(Caddy 권장, `deploy/Caddyfile`)**를 두고, 공개 도메인 5개를 Host 기반으로 고정 host port에 라우팅한다. 앱/Compose는 포트 계약(ADR-27)을 바꾸지 않는다. 다섯 도메인이 같은 IP를 공유하므로 Host 기반 프록시는 필수다.
  - **env_file 경로 override**: compose `env_file` 경로를 `${APP_ENV_FILE:-.env}`로 두어, 복사 없이 `APP_ENV_FILE=.env.production`으로 prod env를 주입할 수 있게 한다(`--env-file`은 `${...}` 보간 소스만 바꾸고 컨테이너 비밀 키는 `env_file:`이 결정하므로, 둘을 함께 지정해야 한다).
    - `<web>` → `127.0.0.1:12605`, `<api>` → `12601`, `<mcp>` → `12602`(streamable-http `/mcp`, SSE 버퍼링 off), `<s3-api>` → `12101`, `<s3-console>` → `12105`.
  - **RustFS 도메인 매핑**: `s3-api.<...>` = S3 API/공개 객체 URL(`RUSTFS_PUBLIC_BASE_URL`), `s3.<...>` = 관리 콘솔(`RUSTFS_CONSOLE_URL`). 백엔드 boto3 연결(`RUSTFS_ENDPOINT`/`RUSTFS_DOCKER_ENDPOINT`)은 같은 호스트 내부 경로(`host.docker.internal:12101`)를 유지해 프록시/TLS를 우회한다.
  - **same-origin BFF 유지**: 브라우저는 공개 API 도메인을 직접 호출하지 않는다. `NEXT_PUBLIC_API_BASE_URL`은 비워 두고(상대 경로) Next BFF가 컨테이너 내부 `http://api:8000`으로 프록시하며 `X-API-Key`를 주입한다. 따라서 공개 Web 도메인이 무엇이든 프론트는 그대로 동작한다.
  - **인증 강제**: prod는 `APP_ENV=production`(+선택적으로 `API_AUTH_ENABLED=true`)와 `API_KEYS`를 설정하고, BFF의 `BACKEND_API_KEY`를 그중 하나와 동일하게 둔다(ADR-24).
  - **프록시 헤더**: TLS 종단 뒤에서 `FORWARDED_ALLOW_IPS=*`를 설정한다. uvicorn이 `os.environ["FORWARDED_ALLOW_IPS"]`를 직접 읽고 `proxy_headers`가 기본 활성이라 앱 코드 변경이 없다.
  - **도메인 비밀 유지**: 실제 공개 도메인/비밀은 git에 커밋하지 않는다. 커밋 파일(`.env.example`, `deploy/Caddyfile`, 문서)에는 placeholder/`{$ENV}`만 둔다. 실제 값은 gitignore된 `.env`(또는 `.env.production`)에만 둔다. Caddy는 `--envfile`로 같은 파일에서 도메인을 읽는다.
  - **MCP 노출 보안**: MCP는 앱 자체 인증이 없다. `deploy/Caddyfile`은 MCP 도메인에 `basic_auth`를 **기본 ON**으로 두고, `MCP_BASIC_AUTH_HASH`(`caddy hash-password` bcrypt)를 주입하지 않으면 커밋된 **잠금 기본 해시**가 적용되어 Caddy는 정상 기동하되 아무도 인증할 수 없다(익명 노출 방지, fail-safe). `MCP_WRITE_ENABLED=false`도 유지한다. 잠금 기본 해시는 폐기된 무작위 비밀번호의 bcrypt 값이라 커밋해도 안전하다.
- **결과 (긍정)**: 앱 코드 변경 없이 환경변수 + 프록시 설정만으로 prod 도메인 운영이 가능하다. 실제 도메인이 git/공개 산출물에 남지 않는다. 로컬/E2E는 기존 무인증·localhost 동작을 그대로 유지한다.
- **결과 (부정)**: 프록시(TLS, 동적 DNS A 레코드, 80/443 개방)는 repo 밖 인프라 책임이다. 실제 도메인이 gitignore된 두 곳(`.env`와, 필요 시 Caddy envfile)에 나뉘어 들어갈 수 있다. RustFS `s3`/`s3-api` 역할 매핑을 반대로 두면 미디어 링크/콘솔 링크가 깨진다.
- **관련**: ADR-24(인증), ADR-27(포트), ADR-15(RustFS), ADR-18/ADR-23(Compose/실행 모델)을 prod 노출 관점에서 보강한다.

---

## ADR-29: `kor-travel-geo` UI 지침(StyleSeed) 채택과 Tailwind v4 전환

- **상태**: 채택 (2026-06-20)
- **맥락**: 프런트엔드는 stock shadcn `base-nova` neutral(oklch 무채색) 테마였고, accent·semantic 토큰·운영 콘솔 규칙이 없었다. 사용자가 형제 프로젝트 `kor-travel-geo`(`kor-travel-geo-ui/docs/DESIGN-RULES.md`)의 UI 지침을 **그대로 따르고**, 빌드 엔진을 **Tailwind v4**로 바꾸도록 요청했다. 지침의 원본은 StyleSeed(`styleseed-demo.vercel.app/llms.txt`) 해석본으로 단일 accent, 의미 토큰, 카드 구조, 낮은 그림자, 일관된 모션을 강조한다.
- **결정**:
  - **디자인 시스템 이식**: geo-ui의 semantic 토큰을 `src/app/globals.css` `:root`에 단일 출처로 둔다 — 단일 accent `--brand`(teal `#0f766e`), 5단계 `--text-*`, `--surface-*`, status(`--ok/--warn/--danger/--info`), `--shadow-*`(4/6/8/12%), `--duration-*`/`--ease-default`. shadcn 토큰(`--background/--primary/--border/--ring` 등)을 이 brand 팔레트에 매핑해 기존 컴포넌트가 자동으로 brand+light를 채택한다. `tailwind.config.ts`에 `text.*/surface.*/brand/info/success/warn/danger`와 `shadow-card|button|modal`, `duration-fast|normal`, `ease-default` 토큰을 추가한다.
  - **primitive 규칙 정렬**: `button/input/label/badge/select`를 DESIGN-RULES에 맞춘다 — 44px touch(`min-h-11`), 8px radius(`--radius: 0.5rem`), 약한 shadow, named motion 토큰, label은 12px·`tracking-[0.05em]`·uppercase, focus ring은 brand.
  - **하드코딩 색 제거**: 페이지/컴포넌트의 잔여 hex/raw color(`emerald/amber/green`, map marker `#111827/#2563eb`)를 `success/warn/brand` 등 semantic으로 치환한다. 선택 marker는 단일 accent(brand), 그림자는 색 없는 중립으로 둔다.
  - **Tailwind v3.4 → v4 전환**: PostCSS는 `@tailwindcss/postcss`, CSS는 `@import "tailwindcss"`. 기존 JS config는 `@config "../../tailwind.config.ts"`로 유지하되, v3 전용 `cssVariableColor`(opacity callback) helper를 제거한다(v4는 `var()` 색상에 opacity modifier를 color-mix로 native 처리). animation은 `tailwindcss-animate` 대신 `tw-animate-css`(`@import`)를 쓴다. `@custom-variant dark (&:is(.dark *))`로 `dark:`를 클래스 기준으로 좁혀 OS dark-mode와 무관하게 **light 전용**으로 둔다(geo는 light 운영 콘솔).
  - **정본 문서**: `frontend/docs/DESIGN-RULES.md`를 concierge 프런트의 디자인 규칙 정본으로 추가한다.
- **결과 (긍정)**: geo와 동일한 디자인 언어(brand teal·light surface·uppercase label·dot+text status·낮은 그림자)를 단일 토큰 출처로 적용했다. `npm run build`/`lint`/`type-check` 통과, 설정·메인 화면을 실제 렌더로 시각 검증했다. 빌드 엔진은 v4로 현대화했다.
- **결과 (부정)**: geo-ui 자체는 아직 Tailwind v3(`@tailwind` directives)이라 엔진 버전은 다르다(클래스 규칙·토큰은 동일하게 맞춤). dark 테마는 비활성(light 전용). shadcn CLI(devDep) 전이 의존 `hono` advisory는 런타임 미배포·기존 항목으로 본 작업과 무관하다.
- **관련**: ADR-14(프런트 스택: shadcn/ui·Tailwind·RHF·Zod·TanStack)를 디자인 시스템·Tailwind v4 관점에서 보강한다.

---

## ADR-30: AI 엔진 다중 provider(Gemini/DeepSeek) + 사전 프롬프트 + JSON 출력 + 느린 재시도

- **상태**: 채택 (2026-06-20)
- **결정자**: 사용자, AI agent
- **맥락**: 그동안 ETL·Deep Research의 모든 LLM 호출은 Gemini 단일 provider에 묶여 있었다(ADR-3). 사용자는 (1) Gemini 외에 DeepSeek V4를 대안 LLM provider로 추가해 웹 설정에서 엔진을 전환할 수 있게 하고, (2) 모든 AI 프롬프트 앞에 사용자가 편집 가능한 공통 지침(사전 프롬프트)을 붙이며, (3) 두 provider 모두에서 안정적인 JSON 출력을 받고, (4) 외부 LLM 429/일시 오류에 사람처럼 충분히 느리게 재시도하고, (5) Next 기본 오류 화면 대신 형제 프로젝트 geo의 한국어 에러 복구 UI를 적용하길 요청했다. DeepSeek는 OpenAI 호환 API(`base_url=https://api.deepseek.com`)를 제공하므로 별도 SDK 없이 chat completion으로 연동할 수 있다.
- **결정**:
  - **DeepSeek provider 디스패치**: DeepSeek V4(`deepseek-v4-flash`, `deepseek-v4-pro`)를 OpenAI 호환 chat completion으로 호출하는 `ktc/etl/deepseek_client.py`(JSON mode 포함)와, provider를 선택해 `complete_json`을 노출하는 `ktc/etl/llm_client.py`(`LlmRuntime`, 사전 프롬프트 prepend)를 추가한다. `config.py`에 `DEEPSEEK_API_KEY`/`DEEPSEEK_BASE_URL`, `DEEPSEEK_ENGINE_OPTIONS`, 통합 `LLM_ENGINE_OPTIONS`, `is_deepseek_model` 판별을 둔다. 웹 설정(`/settings`)에서 엔진을 Gemini/DeepSeek로 전환하고 DeepSeek API 키를 저장하되 평문은 노출하지 않고 감사 로그에서 마스킹한다.
  - **사전 프롬프트(pre-prompt)**: 모든 AI 프롬프트 앞에 붙는 사용자 편집 가능 지침을 런타임 설정 `ai_preprompt`(`system_settings`)로 두고 기본 예제 `AI_PREPROMPT_DEFAULT`를 제공한다. 웹 설정에서 수정한다.
  - **JSON 출력 보강**: Gemini는 기존 `responseSchema`를, DeepSeek는 `response_format=json_object` + 스키마를 프롬프트에 첨부하는 방식을 쓴다. 기본 사전 프롬프트도 "코드펜스 없이 JSON만" 출력을 강조한다.
  - **느린 사람 유사 재시도**: `LLM_RETRY_*` env(base 15s, max 90s, jitter 0.3, 4회)와 `gemini_client.human_like_retry_delay`를 Gemini·DeepSeek 공용으로 둔다. 기존 2/4/8초 백오프를 충분히 늦은 사람 유사 지연으로 바꾼다.
  - **에러 복구 UI**: Next App Router 기본 오류 화면 대신 `frontend/src/app/error.tsx`, `global-error.tsx`, `components/layout/AppErrorPanel.tsx`, `lib/error-recovery.ts`를 추가한다(geo PR #391 동등 이식). chunk/RSC/network 런타임 오류 시 같은 pathname에서 1회만 hard reload하고, 반복 실패 시 재시도/이전 화면/오류 정보를 제공한다. Tailwind + shadcn으로 적용한다.
  - **키 비밀 유지**: DeepSeek 키는 gitignore된 `.env`/`.env.production`에 `DEEPSEEK_API_KEY=sk-...`로 두고, 커밋된 `.env.example`에는 placeholder만 둔다. git과 감사 로그에 평문으로 남기지 않는다.
- **결과 (긍정)**: Gemini 단일 의존을 끊고 DeepSeek를 동등한 대안으로 운영할 수 있다. 사전 프롬프트로 두 provider의 출력 형식·톤을 한곳에서 통제한다. JSON 강제와 느린 재시도로 파싱 실패·일시 오류 내성이 높아진다. 사용자는 한국어 에러 화면에서 복구 행동을 직접 고를 수 있다.
- **결과 (부정)**: 두 provider의 응답 차이를 `llm_client` 디스패치가 흡수해야 하므로 호출 경로가 한 단계 늘어난다. DeepSeek 키 발급·로테이션·과금이 새 운영 책임이 된다. 느린 재시도는 실패 시 작업 지연을 키운다. provider별 JSON mode 동작 차이를 계속 검증해야 한다.
- **관련**: ADR-3(Gemini LLM 파이프라인)을 다중 provider로 확장한다. ADR-9(ETL 복원력 보강 — 429 지수 백오프·지터)의 재시도 원칙을 LLM 호출의 사람 유사 느린 재시도로 강화한다.

---

## ADR-31: 검수 멀티-provider 비교 페이지 + 작업/반복 관리 UX + API 키 DB 관리

- **상태**: 채택 (2026-06-21)
- **결정자**: 사용자, AI agent
- **맥락**: 메인 한 화면에 수집·장소·지도·검수·반복·운영이 몰려 있어 검수(장소 좌표 보정)가 비좁았고, 반복 작업의 주기·횟수 수정과 작업별 누적 영상 확인 수단이 없었다. 또 각종 API 키를 `.env` 편집으로만 바꿀 수 있었다. 사용자는 (1) 검수를 별도 페이지로 빼서 Google Places·Kakao·Naver 검색과 Gemini 의견을 한 번에 비교하며 좌표를 보정하고, (2) 메인 기존 검수 자리에는 실행 큐를, 작업은 반복/1회성 탭으로 모두 표시하며 항목 클릭 시 상세(대상·키워드·최대수·간격·누적 영상)와 중지/재시작을 제공하고, (3) 반복 작업의 주기·횟수를 수정(0=무한)하고, (4) 자막 확인 단계 없이 자동 완료하고, (5) 운영 수치를 별도 모달로, (6) 설정 모달에서 8종 API 키를 저장/수정하길 요청했다. 각 UI 단계는 스샷 검토를 받으며 진행한다.
- **결정**:
  - **검수 별도 페이지(`/review`)**: 후보 목록 + 선택 후보 정보 + 멀티-provider 비교(클릭→좌표 선택) + 직접 검색 + 지도 + 확정/제외. 백엔드 `GET /api/v1/place-search?q=`를 신설하고 `ktc/etl/place_search.py`에서 Google Places(New)·Kakao 키워드·Naver 지역검색을 병렬 호출(결함 격리, 정규화 `{provider,name,address,road_address,latitude,longitude,category}`, Naver mapx/mapy÷1e7)하고 Gemini 의견을 덧붙인다. 키 미설정 provider는 빈 결과 + `errors`.
  - **메인 재편**: 좌측 수집 사이드바 접이식(48px), 장소 목록을 지도 왼쪽 좁은 칼럼으로, 하단을 실행 큐 | 작업(반복/1회성 탭)으로. 검수는 사이드바 검수 버튼→페이지, 운영은 사이드바 운영 버튼→모달.
  - **작업 상세·반복 관리**: 작업/반복 클릭→상세 모달(`GET /runs/{id}/videos`, `GET /source-targets/{id}/videos`로 누적 영상). 반복 수정 모달은 `PATCH /api/v1/source-targets/{id}`로 주기·횟수를 바꾼다. `source_targets.max_runs`(0=무한)/`run_count`를 추가(migration `20260621_0009`; alembic 이전 DB는 직접 ALTER), `scan_due_targets`가 enqueue마다 run_count를 올리고 max_runs 도달 시 비활성화한다. 생성 폼의 반복 간격은 1시간·12시간·1일·1주일·2주일·1달·3달.
  - **자동 완료**: 수집 시작이 `skip_transcript=false`로 자막→POI→지오코딩→DB까지 자동 진행한다(별도 확인 단계 제거).
  - **운영 지표**: `GET /api/v1/metrics`(RustFS 객체/용량/타입별 + DB 카운트·후보상태·작업상태)를 운영 모달이 소비한다.
  - **API 키 DB 관리**: `settings_service.get_secret(session, name)`가 `system_settings`→`.env` 순으로 해석하고, `GET /settings`가 8종 키의 `api_keys.{name}.set`만(값 비노출) 내려준다. POST는 빈 값은 미변경, 감사 로그는 비밀을 마스킹한다. 소비처(harvest YouTube, place-search, geocoding postprocess, `get_llm_runtime`)가 `get_secret`로 해석하되 DB에 값이 없으면 env로 폴백해 동작이 바뀌지 않는다. NCP geocoding의 `NAVER_CLIENT_ID/SECRET`은 검색용 `naver_search_*`와 구분되는 별개 키라 env에 둔다.
  - **UI 프리미티브**: base-ui 기반 `Dialog`/`Tabs`(`components/ui/dialog.tsx`, `tabs.tsx`)를 추가해 모달·탭 공용으로 쓴다.
- **결과 (긍정)**: 검수가 넓은 전용 화면에서 4개 출처를 한눈에 비교·보정할 수 있다. 모든 작업을 탭으로 보고 상세·중지·재시작·반복 수정까지 한 화면에서 처리한다. 운영자가 `.env` 편집 없이 키를 교체할 수 있고, env 폴백으로 무중단 호환된다.
- **결과 (부정)**: place-search가 외부 4 provider에 의존해 지연·할당량 변동이 검수 UX에 노출된다. 키를 DB와 env 두 곳에서 관리하게 되어 우선순위(DB>env)를 문서로 명확히 유지해야 한다. 비밀이 `system_settings`에 평문 저장되므로 DB 접근 통제가 중요하다.
- **관련**: ADR-22(장소 언급·검수 UX), ADR-24(`/api/v1`·`X-API-Key`), ADR-29(StyleSeed UI)를 확장한다. ADR-30의 `get_llm_runtime`·설정 저장 모델을 API 키 전반으로 일반화한다.

---

## ADR-32: 관리자 로그인, 관리자 BFF proxy, 공개 API 키 발급

- **상태**: 채택 (2026-06-23)
- **결정자**: 사용자, AI agent
- **맥락**: 외부 공급용 REST API는 ADR-24에서 `X-API-Key` 인증과 same-origin Next BFF 경계를 정했지만, 관리자 화면 자체는 별도 로그인 없이 열려 있었고 공개 API 키도 `.env` 기반 정적 목록에 의존했다. 사용자는 형제 프로젝트 `kor-travel-geo` PR #399와 같은 형태로 단일 관리자 로그인, 보안 세션, 로그인 기록 조회, Web UI 기반 공개 API 키 생성·폐기, 관리자 API의 프론트엔드 전용 호출 제한, `kor travel geo v2` 키 설정을 요구했다.
- **결정**:
  - **단일 관리자 계정**: 관리자 아이디는 기본 `admin` 하나만 둔다. 초기 비밀번호는 평문을 코드·문서·git에 남기지 않고, `KTC_ADMIN_PASSWORD_HASH`에 PBKDF2-SHA256 해시로만 저장한다. 해시와 세션 secret은 gitignore된 `.env`에만 둔다.
  - **Next 서버 세션**: 로그인은 Next Route Handler(`/api/auth/login`)가 처리한다. 성공 시 httpOnly `SameSite=Strict` HMAC 세션 쿠키를 발급하고, 세션 payload에는 audience, issue/expire time, session id, admin subject, user-agent fingerprint를 넣는다. 로그아웃과 재로그인은 서버 프로세스 메모리의 revoked session id Map으로 현재 세션을 폐기한다. 로그인 요청은 same-origin Origin, JSON-only, 실패 rate-limit을 통과해야 한다.
  - **관리자 화면 보호**: Next `proxy.ts`가 `/login`, `/api/auth/*`, 정적 자산을 제외한 모든 페이지와 BFF API 요청에 세션을 요구한다. 세션이 없으면 페이지는 `/login?next=...`로 보내고 API는 401을 반환한다. 프런트 API 클라이언트는 401을 받으면 로그인 화면으로 이동한다.
  - **로그인 감사 로그**: `login_events` 테이블을 만들고 로그인 시도·성공·실패·거부·로그아웃을 저장한다. 사용자는 설정 UI에서 최근 로그인 기록을 조회한다. client IP는 기본적으로 `X-Forwarded-For`를 신뢰하지 않으며, 운영 리버스 프록시가 클라이언트 제공 헤더를 덮어쓴다는 확신이 있을 때만 `KTC_UI_TRUST_FORWARDED_IPS=true`로 켠다.
  - **관리자 API proxy 인증**: 백엔드 `/api/v1/admin/*`는 공개 API key로 접근할 수 없다. Next BFF가 유효 세션을 확인한 뒤 서버 전용 `KTC_ADMIN_PROXY_SECRET`과 actor header를 주입하고, 백엔드는 peer IP가 `KTC_ADMIN_TRUSTED_PROXY_CIDRS` 안에 있으며 shared secret이 일치할 때만 관리자 API를 허용한다. BFF는 브라우저가 보낸 `x-api-key`/관리자 proxy 헤더를 그대로 전달하지 않는다.
  - **공개 API 키 발급**: Web UI에서 VWorld와 같은 wire shape의 32자 영문/숫자 key를 CSPRNG로 생성한다. 평문 key는 생성 응답에서 1회만 보여 주고, DB `public_api_keys`에는 SHA-256 hash와 끝 6자리 hint, 상태, 생성/폐기 actor만 저장한다. 공개 API는 `X-API-Key` 또는 VWorld식 `?key=`를 받는다.
  - **성능과 갱신 전략**: 공개 API hot path는 활성 key hash 목록을 `PUBLIC_API_KEY_CACHE_TTL_SECONDS` 동안 프로세스 메모리에 캐시한다. key 생성·폐기 직후에는 캐시를 즉시 무효화하고, 설정 UI는 화면이 열릴 때와 mutation 완료 후 목록을 다시 불러온다.
  - **신뢰 클라이언트 우회**: 외부 노출 API라도 운영자가 `API_TRUSTED_CLIENT_CIDRS`에 명시한 CIDR에서 들어온 요청은 공개 API key 검증을 생략할 수 있다. 기본값은 비어 있어 명시 설정 없이는 우회가 없다.
  - **kor-travel-geo v2 키**: `KOR_TRAVEL_GEO_V2_API_KEY`와 런타임 설정명 `kor_travel_geo_v2_api_key`를 추가한다. 값이 비어 있으면 현재 요구대로 `VWORLD_SERVICE_KEY`와 동일하게 사용한다.
- **결과 (긍정)**: 관리자 UI는 브라우저에 백엔드 비밀을 노출하지 않고 세션으로 보호된다. 공개 API key는 사용자가 UI에서 발급·폐기할 수 있고, DB에는 평문 key가 남지 않는다. 관리자 API는 Next BFF와 백엔드 shared secret을 모두 통과해야 하므로 공개 API key만으로는 관리자 기능에 접근할 수 없다.
- **결과 (부정)**: 세션 폐기와 공개 key cache는 프로세스 메모리라 서버 재시작 또는 다중 replica 환경에서는 공유되지 않는다. 현재 단일 호스트·소형 운영에는 충분하지만 다중 인스턴스가 되면 Redis/PostgreSQL 기반 세션 폐기 저장소와 cache invalidation이 필요하다. 관리자 계정은 단일 계정이므로 세분 권한과 개인별 추적은 후속 범위다.
- **관련**: ADR-24(`/api/v1`와 `X-API-Key`)를 관리자 UI 인증과 DB 발급 공개 key로 확장한다. ADR-28(공개 도메인 노출), ADR-31(API 키 DB 관리)와 함께 적용한다.

---

## ADR-33: 개발 명령 Linux 전용과 Playwright n150 우선 실행 정책

- **상태**: 채택 (2026-06-28)
- **결정자**: 사용자, AI agent

### 맥락
ADR-23은 Windows 네이티브 앱 실행 경로를 제거하고 Linux Docker/WSL 실행 모델로 수렴했지만,
2026-06-12 보강에서는 `git` 명령과 Windows 호스트 Playwright E2E를 예외로 남겼다.
최근 운영은 n150 live 환경에서 UI와 로그인, 배포 상태를 직접 검증하는 흐름이 늘었고,
사용자는 과거 예외였던 `git`/codegraph도 Linux에서 실행하며 Playwright도 n150에서 우선
실행하도록 정책을 명확히 하라고 요청했다.

### 결정
- 모든 개발·검증·리포지토리 작업 명령은 WSL2(Ubuntu)를 포함한 Linux bash에서 실행한다.
- `git`, `gh`, codegraph 계열 인덱싱/분석 명령도 예외 없이 Linux에서 실행한다.
- Windows PowerShell/cmd 직접 작업은 금지한다. 단, n150에서 Playwright를 실행할 수 없을 때의
  Windows 호스트 fallback E2E 하니스만 예외로 둔다.
- E2E Playwright는 n150 live/Linux 환경에서 우선 실행한다. n150 접근, 브라우저 설치, 네트워크,
  DB, 계정 상태 등으로 불가능할 때만 Windows 호스트에서 같은 Playwright 스위트를 fallback 실행한다.
- fallback을 사용한 경우에는 n150 실행이 불가했던 이유와 fallback 결과를 PR 또는
  `docs/journal.md`에 남긴다.
- Windows fallback은 테스트 하니스에 한정되며, 앱 런타임 코드나 신규 개발 스크립트에
  Windows 전용 실행 경로를 추가하는 근거가 될 수 없다.

### 근거
- 개발 명령 실행 위치를 Linux로 고정하면 `git`, codegraph, 빌드, 테스트 결과의 경로·권한·줄바꿈
  차이를 줄일 수 있다.
- n150 live 환경은 실제 배포 상태, 인증, 프록시, 데이터베이스, 브라우저 렌더링을 함께 확인할 수 있어
  현재 운영 검증에 더 직접적이다.
- Windows Playwright는 여전히 유용한 비상 검증 경로지만, 기본 경로로 두면 Windows 네이티브 앱 실행
  경로가 되살아난 것처럼 문서가 읽힐 수 있다.

### 결과 (긍정)
- 에이전트와 사람이 같은 Linux 실행 계약을 따른다.
- PR 검증 기록에서 n150 live 검증과 Windows fallback 검증의 의미가 구분된다.
- Windows 전용 앱 분기나 스크립트를 새로 만들 유인이 줄어든다.

### 결과 (부정)
- n150 접근 권한, 브라우저 설치, 라이브 데이터 상태가 E2E 검증의 선행 조건이 된다.
- n150이 일시적으로 불안정하면 Windows fallback을 쓰고 그 사유를 기록해야 한다.

### 관련
- ADR-23의 Codex 명령 실행 위치와 E2E Playwright 예외를 보강한다.
- ADR-6의 Windows Playwright 검증은 기본 경로가 아니라 fallback 하니스로 축소한다.
- prod/n150 접속 세부와 민감정보는 gitignore된 `docs/deploy-runbook.local.md`에만 둔다.

---

## 이력·대체·보류 ADR (요약)

핵심 구조·기능과 직접 관련된 ADR만 위 본문에 full로 유지한다. 아래는 다른 ADR로 대체되었거나 보류·이력성 결정이라 한 줄 요약으로 보존한 항목이다. 번호는 사라지지 않으며 상세 맥락이 필요하면 git 이력(이전 본문)을 참조한다.

- **ADR-4**: VWorld 지도 컴포넌트 통합 및 `.env` API 키 주입 — accepted, T-013에서 `maplibre-gl + VWorld WMTS` 직접 구성으로 보강(공개 wrapper 미사용).
- **ADR-5**: YouTube API 할당량 절약용 Scraping/Caching 전략 — superseded by ADR-11(공식 YouTube Data API 우선).
- **ADR-6**: Windows 환경 Playwright E2E 파이프라인 — superseded by ADR-23(앱 구동 환경 한정), 이후 ADR-33이 기본 E2E 검증 호스트를 n150 live/Linux로 옮기고 Windows 호스트 실행은 fallback 하니스로 축소.
- **ADR-8**: 지오코딩 공급자 전략 및 `kraddr-geo` 제외 — accepted, ADR-19로 VWorld 최우선 구현 기준 보강.
- **ADR-9**: ETL 복원력 보강 원칙 — accepted, 자막 3단계 폴백·멱등·watermark·작업 상태·429 백오프(ADR-11/ADR-30이 인용·확장).
- **ADR-10**: SQLite3 우선 구현과 PostGIS 전환 유보 — superseded by ADR-12, 이후 ADR-25로 PostgreSQL/PostGIS 전환.
- **ADR-12**: SQLite + SpatiaLite 임베디드 공간 DB 채택 — superseded by ADR-25(PostgreSQL/PostGIS).
- **ADR-14**: 프론트엔드 폼·상태·UI 스택(RHF·Zod·shadcn/ui·Tailwind·TanStack Query·`maplibre-gl + VWorld WMTS`) — accepted, ADR-29에서 디자인 시스템·Tailwind v4 관점으로 보강.
- **ADR-17**: 공간 컬럼을 ORM 밖 SpatiaLite DDL로 관리하고 저장소 계층에 캡슐화 — accepted, ADR-25 PostGIS 전환 후 폐기/PostGIS helper로 대체.
- **ADR-20**: 고도화 후보(sqlite-vec/PostGIS/멀티 워커 큐) 도입 보류와 수치 트리거 — accepted, PostGIS 전환 유보 결정은 ADR-25 사용자 요청으로 supersede.
- **ADR-21**: Next.js 16 / React 19 업그레이드와 ESLint flat config 전환 — accepted, `npm audit` 0건. Tailwind v4 전환은 후속 ADR-29에서 수행.
- **ADR-27(번호 오기)**: 배포명 `kor-travel-concierge`와 Python 패키지명 `ktc` 채택 — accepted(2026-06-13), 배포명/저장소명/패키지명(`ktc.*`)·`KTC_*` env·기본 DB `kor_travel_concierge` 결정. 동일 번호의 ADR-27(포트 정책 126xx)와 번호가 겹쳐 이력으로 보존한다.
