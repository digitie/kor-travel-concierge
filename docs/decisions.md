# DECISIONS — Architecture Decision Records

본 문서는 `kor-travel-concierge` 프로젝트의 아키텍처 및 구현 의사결정을 시간순으로 누적한다. 결정이 뒤집힐 때도 이전 기록은 지우지 않고 `superseded by ADR-XXX`로 표시한다.

---

## ADR-27: 배포명 `kor-travel-concierge`와 Python 패키지명 `ktc` 채택

- 상태: accepted
- 날짜: 2026-06-13
- 결정자: human, Codex

### 컨텍스트
프로젝트가 기존 중간 명칭에서 더 제품 지향적인 배포명으로 전환되어야 한다. 동시에 Python import 경로는 짧고 명확한 단일 패키지명으로 정렬해 FastAPI, scheduler, MCP, 테스트가 같은 package namespace를 사용해야 한다.

### 결정
시스템 배포명과 GitHub 저장소명은 `kor-travel-concierge`로 변경한다. Python import package는 `ktc`로 채택한다.

구현 기준은 다음과 같다.

- 기존 백엔드 패키지는 `backend/ktc`로 이동한다.
- 기존 별도 MCP 구현 패키지는 `ktc.mcp_server`로 편입한다.
- 내부 Python import는 `ktc.*` 경로를 사용한다.
- 환경 변수 접두사는 `KTC_*`를 사용한다.
- 기본 개발 DB 이름은 `kor_travel_concierge`로 둔다.
- YouTube feature provider 식별자는 `kor-travel-concierge-youtube`로 둔다.

### 근거
- 배포명과 저장소명이 일치하면 Docker/Compose, GitHub, 문서, 운영 로그에서 같은 이름을 사용하게 되어 혼동이 줄어든다.
- `ktc`는 짧은 import namespace라 `ktc.core`, `ktc.models`, `ktc.services`, `ktc.mcp_server`처럼 계층을 읽기 쉽다.
- MCP 구현을 `ktc.mcp_server`에 두면 외부 MCP SDK의 `mcp` 패키지명과 충돌하지 않는다.

### 결과
- 기존 백엔드 패키지명 또는 별도 MCP 패키지명 기반 import는 신규 코드에서 사용하지 않는다.
- 기존 DB 이름과 provider 이름을 참조하는 외부 consumer는 새 이름으로 설정을 갱신해야 한다.
- `python-krtour-map`은 외부 sibling repository 이름이므로 이 결정으로 이름을 바꾸지 않는다.

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

## ADR-4: VWorld 지도 컴포넌트 통합 및 `.env`를 통한 API 키 주입

- 상태: accepted, T-013에서 `maplibre-gl + VWorld WMTS` 직접 구성으로 보강
- 날짜: 2026-06-03
- 결정자: AI agent, human

### 컨텍스트
한국 국토정보에 특화된 상세 배경 맵을 UI에 올리기 위해 VWorld 지도가 요구되었으며, 초기에는 이를 MapLibre와 통합한 `maplibre-vworld-js` 라이브러리 사용을 검토했다.

### 결정
프론트엔드 지도 뷰 영역은 T-013 기준 공개 wrapper 없이 `maplibre-gl` raster source에 VWorld WMTS tile URL을 직접 구성한다. 테스트 시 서비스 키는 `.env` 환경 변수에서 로드한다.

### 근거
- `maplibre-gl + VWorld WMTS` 직접 구성은 공개 npm wrapper 의존 없이 Base Map, Hybrid, Satellite 레이어 토글을 제공한다.
- API 서비스 키의 유출을 막기 위해 Next.js의 `process.env.NEXT_PUBLIC_VWORLD_SERVICE_KEY` 규칙으로 통제한다.

### 결과 (긍정)
- 한국 주소 체계에 최적화된 국토교통부 VWorld 위성 및 기본 지도를 WebGL 네이티브 60fps 인터페이스로 렌더링.

### 결과 (부정)
- VWorld API 키 발급이 안 되어 있거나 호출 도메인이 `localhost`로 제한되어 있을 경우를 위해 fallback 처리가 필수적이다.

---

## ADR-5: YouTube API 할당량 절약을 위한 Scraping / Caching 전략

- 상태: superseded by ADR-11
- 날짜: 2026-06-03
- 결정자: AI agent, human

### 컨텍스트
YouTube Data API v3의 기본 할당량 한도는 일일 10,000 포인트다. 검색 1회에 100 포인트가 차감되므로, 주기적인 백그라운드 ETL 검색을 수행하면 할당량이 즉각 고갈된다.

### 결정
수집 파이프라인에서 YouTube Data API를 최소화하기 위해 **비공식 검색/스크래퍼 모듈**을 백업(우회) 수단으로 설정하고, 이미 분석 완료된 영상 ID는 **로컬 SQLite3 캐시**에 넣어 LLM/YouTube API 재조회를 차단한다.

### 근거
- `youtube-search-python` 또는 `yt-dlp` 같은 스크래퍼 라이브러리는 비용이 0이므로 대량의 키워드 검색 및 자막 추출을 할당량 제약 없이 보조할 수 있다.
- `video_cache` 테이블을 두어 동일 영상에 대해 API를 단 1회만 호출하도록 제한한다.

### 결과 (긍정)
- API 할당량 소모가 거의 없어 상시적인 ETL 구동 및 지속 가능한 데이터 수집 가능.

### 결과 (부정)
- YouTube 측의 UI 레이아웃 변경 등 비공식 스크래퍼가 깨질 위험이 있으므로 에러 핸들러 및 Fallback을 둔다.

---

## ADR-6: Windows 환경 Playwright E2E 검증 파이프라인

- 상태: superseded by ADR-23
- 날짜: 2026-06-03
- 결정자: AI agent, human

> 본 ADR의 "Windows 호스트 전용 Playwright 구동" 전제는 ADR-23(Linux Docker/WSL 전용 실행 모델)으로 대체되었다. Playwright 도구 채택 자체는 유지하되, 구동 환경은 Linux(또는 Windows WSL2)로 본다.

### 컨텍스트
Next.js 프론트엔드와 FastAPI 백엔드, SQLite3 데이터베이스 및 VWorld 지도 인터랙션이 올바르게 통합되어 동작하는지 Windows 호스트 환경에서 안정적으로 회귀 테스트할 방안이 요구된다.

### 결정
E2E 테스트 라이브러리로 **Playwright (TypeScript)**를 도입하고, Windows 환경 전용 Playwright 구동 스크립트를 구축한다.

### 근거
- Playwright는 Chromium, Firefox, WebKit의 헤드리스/헤디드 브라우저 시뮬레이션을 신속하게 수행하며 Windows PowerShell CLI와 완벽히 호환된다.
- 프론트엔드의 VWorld 지도 렌더링 검사, CRUD 인터페이스 작동 여부, Deep Research 트리거 동작을 실제 브라우저 이벤트 레벨에서 완벽하게 모방 검증할 수 있다.

### 결과 (긍정)
- 배포/평가 전 Windows 시스템에서의 신뢰도 높은 통합 안정성 획득.

### 결과 (부정)
- Playwright 구동을 위한 브라우저 바이너리 설치 파일로 인해 로컬 용량 점유가 증가한다.

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

## ADR-8: 지오코딩 공급자 전략 및 `kraddr-geo` 제외

- 상태: accepted, ADR-19로 구현 기준 보강
- 날짜: 2026-06-04
- 결정자: AI agent, human

### 컨텍스트
상세 기획서는 Kakao, Naver, VWorld를 조합한 지오코딩과 역지오코딩 파이프라인을 제안한다. 한때 `kraddr-geo` 연계를 검토했지만, 최신 요청에 따라 해당 연계는 취소되었다.

### 결정
현재 계획에서는 `kraddr-geo`를 연계하지 않는다.

지오코딩은 Kakao Local API를 1차 공급자로 두고, 결과가 없거나 모호할 때 Naver API를 보조로 사용한다. 역지오코딩과 행정/도로명 주소 보강은 VWorld API를 우선 활용한다. 이후 ADR-19에서 VWorld를 지오코딩과 역지오코딩 모두의 최우선 경로로 올리고, 내부 wrapper 계층을 최소화하는 구현 기준으로 보강했다.

### 근거
- Kakao Local API는 국내 POI 커버리지와 카테고리 정보가 강하다.
- Naver API는 장소 평판과 검색 메타데이터 보강에 유리하다.
- VWorld API는 좌표 기반 행정 주소, 도로명 주소, 공공 공간 데이터 보강에 적합하다.
- `kraddr-geo` 제외를 명시해야 향후 백로그와 구현에서 잘못된 의존성이 생기지 않는다.

### 결과 (긍정)
- 공급자별 강점을 나눠 쓰면서도 쿼터와 실패를 통제할 수 있다.
- `kraddr-geo`를 전제로 한 작업이 생성되는 것을 방지한다.

### 결과 (부정)
- 여러 외부 API 키와 공급자별 응답 정규화 로직을 관리해야 한다.

---

## ADR-9: ETL 복원력 보강 원칙 채택

- 상태: accepted
- 날짜: 2026-06-04
- 결정자: AI agent, human

### 컨텍스트
상세 기획서는 YouTube 비공식 수집 경로의 파손 가능성, 자막 부재, API 429, 중복 처리, 장시간 작업 실패를 주요 리스크로 다룬다. 초기 계획의 3단계 ETL만으로는 운영 중단과 비용 낭비를 충분히 막기 어렵다.

### 결정
ETL 구현 범위를 다음 원칙으로 보강한다.

- YouTube 검색과 메타데이터 수집은 ADR-11에 따라 공식 YouTube Data API v3를 우선 사용하고, `yt-dlp`는 공식 대안이 부족한 자막 추출·대표 프레임 스트림 확보 구간에만 격리한다.
- 자막 전사는 `youtube-transcript-api` → `yt-dlp` 자막 추출 → `faster-whisper` 순서의 3단계 폴백을 둔다.
- 모든 신규 영상은 `video_id` 기준 캐시로 멱등 처리한다.
- 키워드·채널·재생목록 target별 watermark와 적응형 크롤 주기로 호출량을 줄인다.
- 작업 상태, heartbeat, retry_count, last_error를 DB에 기록한다.
- 지오코딩과 수집 단계 모두 429 응답에 지수 백오프와 지터를 적용한다.

### 근거
- YouTube와 지도 API는 외부 서비스라 응답 포맷 변경과 쿼터 제한에 취약하다.
- 영상 처리와 Gemini 요약은 비용이 큰 작업이므로 중복 실행 방지가 필수다.
- 실패 작업을 DB에 남기면 웹 UX와 MCP UX 양쪽에서 복구 작업을 수행할 수 있다.

### 결과 (긍정)
- 단일 라이브러리 장애가 전체 ETL 중단으로 이어질 가능성이 줄어든다.
- 장시간 작업 실패가 조용히 묻히지 않고 재시도 또는 운영 조치 대상이 된다.

### 결과 (부정)
- 초기 구현 범위가 단순 수집 스크립트보다 넓어지고 작업 상태 모델이 추가된다.

---

## ADR-10: SQLite3 우선 구현과 PostGIS 전환 유보

- 상태: superseded by ADR-12
- 날짜: 2026-06-04
- 결정자: AI agent, human

### 컨텍스트
상세 기획서는 PostGIS, `ST_DWithin`, GiST 인덱스, geography 캐스팅 기반 공간 DB를 권장한다. 반면 저장소의 현재 지시와 초기 목표는 Windows 로컬 평가가 쉬운 SQLite3 기반 FastAPI 애플리케이션이다.

### 결정
초기 구현은 ADR-2에 따라 SQLite3를 유지한다. 단, 데이터 모델은 위도/경도, 공급자, 주소, 중복 병합 후보, 영상-장소 N:M 매핑을 분리하여 PostGIS로 전환할 수 있는 구조로 설계한다. PostGIS 전환은 데이터 규모, 반경 검색 요구, 동시 쓰기 실패가 실제로 커졌을 때 별도 ADR로 결정한다.

### 근거
- SQLite3는 Windows 로컬 평가와 초기 개발 속도에 유리하다.
- PostGIS는 공간 검색 성능에는 강하지만 PostgreSQL 운영, 확장 설치, 마이그레이션 부담이 있다.
- 초기부터 테이블 경계를 적절히 두면 나중에 PostGIS로 옮길 때 도메인 모델의 재작성 범위를 줄일 수 있다.

### 결과 (긍정)
- 초기 부트스트랩 속도와 운영 단순성을 보존한다.
- 상세 기획서의 공간 데이터 요구를 무시하지 않고 후속 전환 조건으로 관리한다.

### 결과 (부정)
- 대량 장소 중복 제거와 반경 검색은 SQLite3 휴리스틱으로 먼저 구현되며, 규모가 커지면 전환 비용이 발생한다.

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

## ADR-12: SQLite + SpatiaLite 임베디드 공간 DB 채택

- 상태: accepted
- 날짜: 2026-06-05
- 결정자: AI agent, human

### 컨텍스트
이전 계획은 SQLite3로 시작하되 PostGIS 전환 가능성을 크게 열어 두었다. 최신 Google Docs 명세는 별도 DB 서버 없는 소형 프로젝트를 명확히 전제로 하며, 공간 검색은 SQLite + SpatiaLite로 처리하는 쪽이 운영 비용과 백업·이전 비용 면에서 더 적합하다고 판단한다.

### 결정
초기 데이터베이스는 SQLite + SpatiaLite로 확정한다. Python 접근은 `aiosqlite`를 사용하고, SQLite WAL 모드를 켜 동시 접근을 완화한다. 공간 컬럼과 R-Tree 인덱스는 SpatiaLite를 사용한다.

### 근거
- 파일 하나로 백업, 복사, 이전이 가능하다.
- PostGIS 서버 운영이 필요 없어 Windows 로컬 개발과 Docker Compose 배포가 단순하다.
- SpatiaLite와 PostGIS는 OGC `ST_*` 계열 함수 개념을 공유하므로 대규모 전환 시 이전 부담이 제한적이다.

### 결과 (긍정)
- 초기 인프라 복잡도를 낮춘다.
- 반경 검색과 중복 장소 탐지에 필요한 최소 공간 DB 기능을 확보한다.

### 결과 (부정)
- SpatiaLite 확장 설치와 Windows 경로 설정을 개발 환경 문서에서 명확히 다뤄야 한다.
- 멀티 워커·대량 동시 쓰기에는 PostGIS보다 한계가 빠르게 온다.

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

## ADR-14: 프론트엔드 폼·상태·UI 스택 채택

- 상태: accepted
- 날짜: 2026-06-05
- 결정자: AI agent, human

### 컨텍스트
기존 문서에는 Next.js와 React만 명확했고, 폼 검증, 서버 상태, 컴포넌트 시스템이 구체화되지 않았다. 최신 Google Docs 명세는 Web REST와 비동기 작업 폴링이 핵심 흐름임을 전제로 한다.

### 결정
프론트엔드 기본 스택을 다음으로 확정한다.

- 폼: React Hook Form
- 검증: Zod
- UI: shadcn/ui + Tailwind CSS
- 서버 상태: TanStack Query
- 지도: `maplibre-gl + VWorld WMTS`

Zustand는 초기 범위에서 보류한다. 서버 데이터는 TanStack Query가, 폼 상태는 React Hook Form이 처리하므로 순수 클라이언트 전역 상태가 2~3개 이상 명확해질 때 추가한다.

### 근거
- `POST /api/harvest` → `job_id` → `GET /api/harvest/{job_id}` 폴링 흐름은 TanStack Query에 적합하다.
- React Hook Form과 Zod를 결합하면 입력 폼과 API 계약을 일관되게 검증할 수 있다.
- shadcn/ui와 Tailwind CSS는 작은 팀이 빠르게 일관된 운영 UI를 만들기에 적합하다.

### 결과 (긍정)
- 비동기 작업 UI의 로딩, 에러, 재요청, 캐싱 처리가 단순해진다.
- 폼 검증과 API 응답 검증이 같은 스키마에서 출발할 수 있다.

### 결과 (부정)
- shadcn/ui 컴포넌트 생성 규칙과 Tailwind 설정을 초기 스캐폴딩에서 함께 관리해야 한다.

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

## ADR-17: 공간 컬럼은 ORM 밖 SpatiaLite DDL로 관리하고 저장소 계층에 캡슐화

- 상태: accepted
- 날짜: 2026-06-05
- 결정자: AI agent

### 컨텍스트
`travel_places.geom`은 SpatiaLite Point(4326) 컬럼과 R-Tree 공간 인덱스를 필요로 한다. `geoalchemy2`로 ORM에 직접 매핑하는 방법도 있으나, 이는 모든 실행 환경(개발 Windows, CI, Docker)에 `mod_spatialite` 로드를 강제한다. 소형 프로젝트에서는 확장이 없는 환경에서도 코드가 import·테스트되어야 한다.

### 결정
- ORM 모델 `TravelPlace`는 `latitude`/`longitude` Float 컬럼만 매핑한다.
- `geom` Point(4326) 컬럼과 R-Tree 공간 인덱스는 ORM 밖에서 `ktc.core.spatial`이 SpatiaLite DDL(`AddGeometryColumn`, `CreateSpatialIndex`, `MakePoint`)로 멱등 관리한다. `mod_spatialite` 미로드 환경에서는 graceful하게 건너뛴다.
- 근접 검색은 저장소 계층(`ktc.services.place_service`)에 캡슐화한다. 기본 구현은 경위도 bounding box로 후보를 좁힌 뒤 Haversine으로 정밀 필터링하며, SpatiaLite/PostGIS 환경에서는 동일 인터페이스를 `ST_DWithin`/`PtDistWithin`으로 대체할 수 있다.

### 근거
- 확장 의존을 한 모듈로 격리하면 확장이 없는 환경에서도 전체 테스트가 돈다.
- 공간 함수 호출 지점을 저장소 계층 한곳에 모으면 PostGIS 전환(ADR-12 대규모 후보) 시 호출부 변경을 최소화한다.

### 결과 (긍정)
- SpatiaLite 없이도 모델·서비스·API를 import하고 단위 테스트할 수 있다.
- 근접/중복 탐색 인터페이스가 백엔드 공간 엔진과 분리된다.

### 결과 (부정)
- `geom` 컬럼이 ORM 메타데이터에 없으므로 동기화를 `ktc.core.spatial`이 별도로 책임진다.
- 확장이 없는 환경의 근접 검색은 R-Tree 대신 bounding box + Haversine이라 대량 데이터에서 상대적으로 느리다(소형 프로젝트 규모에서는 무방).

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

## ADR-20: 고도화 후보 도입 보류와 전환 트리거

- 상태: accepted
- 날짜: 2026-06-05
- 결정자: AI agent

### 컨텍스트
T-016은 sqlite-vec 기반 의미론적 검색, PostgreSQL/PostGIS 전환, 멀티 워커 큐 전환을 검토하는 작업이다. 현재 제품은 1~2인 운영의 소형 프로젝트이며, SQLite + SpatiaLite, APScheduler 단일 실행자, REST/MCP 작업 생성 분리 구조가 이미 동작한다. 따라서 새 저장소·큐 계층을 선제 도입하면 운영 비용과 마이그레이션 부담이 이득보다 커질 수 있다.

검토한 기준 자료는 다음과 같다.

- [`sqlite-vec`](https://github.com/asg017/sqlite-vec): SQLite용 vector search extension이며 `vec0` virtual table을 제공하지만 pre-v1로 breaking change 가능성을 명시한다.
- [SQLite `Vec1`](https://sqlite.org/vec1): SQLite 공식 ANN vector extension 후보로, virtual table 기반 ANN과 cosine/L2 distance를 제공한다.
- [PostGIS spatial indexes FAQ](https://postgis.net/documentation/faq/spatial-indexes/): GiST spatial index와 `ST_DWithin` 같은 index-aware 함수를 권장한다.
- [PostgreSQL `SKIP LOCKED`](https://www.postgresql.org/docs/current/static/sql-select.html): queue-like table에서 여러 consumer가 lock contention을 피할 수 있는 용도를 명시한다.
- [PostgreSQL `LISTEN`](https://www.postgresql.org/docs/current/sql-listen.html) / [`NOTIFY`](https://www.postgresql.org/docs/17/sql-notify.html): DB 기반 event notification의 기본 동작과 race 조건을 설명한다.
- [PostgreSQL advisory locks](https://www.postgresql.org/docs/17/explicit-locking.html#ADVISORY-LOCKS): application-defined lock이며 사용 규칙은 애플리케이션 책임이다.
- [APScheduler user guide](https://apscheduler.readthedocs.io/en/3.x/userguide.html): `max_instances`와 `coalesce`로 단일 job 중복 실행을 제한할 수 있다.
- [PgQueuer architecture](https://pgqueuer.readthedocs.io/en/stable/architecture.html): `LISTEN/NOTIFY`와 `FOR UPDATE SKIP LOCKED` 기반 worker dispatch 구조를 제공한다.

### 결정
- **sqlite-vec / Vec1은 지금 도입하지 않는다.**
  - 의미론적 검색이 실제 UX 병목으로 확인되기 전까지는 현재의 이름·주소·카테고리 검색과 Gemini 보강 설명 저장으로 충분하다.
  - 도입 후보는 확정 장소 20,000건 이상 또는 최근 30일 검색 결과 0건/오탐으로 인한 수동 보정 비율이 20%를 넘는 경우다.
  - 도입 시에는 `place_embeddings` 같은 별도 테이블을 만들고, 기존 `travel_places` 스키마와 검색 API를 깨지 않는 optional feature flag(`SEMANTIC_SEARCH_ENABLED`)로 시작한다.
  - 내부 vector repository wrapper를 만들기보다, extension loading과 SQL 쿼리를 검색 서비스 함수 한곳에 좁게 둔다.
- **PostgreSQL/PostGIS 전환은 수치 트리거가 생길 때만 별도 ADR로 실행한다.**
  - 전환 후보는 확정 장소 100,000건 이상, 영상-장소 매핑 1,000,000건 이상, 반경 검색 p95 500ms 초과, 최근 7일 `database is locked` 재시도 10회 이상, 또는 백업/복구·관측 요구가 단일 `.db` 파일을 넘어설 때다.
  - 전환 시 호출부 변경은 `ktc.services.place_service`와 `ktc.core.spatial`에 국한한다. 반경 검색은 PostGIS `ST_DWithin`, geometry GiST index, 필요 시 geography cast로 대체한다.
  - 전환 검토는 SQLite + SpatiaLite 채택 근거를 둔 ADR-12와 공간 컬럼 관리 경계를 둔 ADR-17을 함께 갱신하는 후속 ADR로 진행한다.
- **멀티 워커는 PostgreSQL 도입 이후에만 검토한다.**
  - 현재는 APScheduler 단일 실행자(`max_instances=1`, `coalesce=True`)와 `crawl_runs` claim 방식이 운영 복잡도 대비 충분하다.
  - PostgreSQL 전환 이후 pending 대기 작업 최고 연령이 5분 초과 상태로 3회 연속 관측되거나, 단일 worker가 24시간 내 신규 영상 처리량을 소화하지 못하면 PgQueuer를 1순위로 검토한다.
  - APScheduler + PostgreSQL advisory lock은 “여러 scheduler 프로세스 중 단일 leader 보장”이 필요할 때만 보조 후보로 둔다. 여러 consumer가 같은 queue를 처리해야 하는 경우에는 `SKIP LOCKED` 기반 큐가 더 직접적이다.
- **Celery/Redis/RabbitMQ는 이번 단계의 후보에서 제외한다.**
  - DB native queue로도 부족하고, 외부 분산 worker·고립된 retry·별도 observability가 필요한 시점에 새 ADR로 재검토한다.

### 근거
- 현재 코드의 확장 지점은 이미 좁다. 공간 함수 호출은 `place_service`, SpatiaLite DDL은 `ktc.core.spatial`, 작업 실행은 `scheduler.worker`에 모여 있다.
- sqlite-vec은 Windows와 SQLite 유지 장점이 있지만 pre-v1 extension이므로 검색 품질 요구가 확인되기 전에 기본 의존성으로 넣기에는 이르다. SQLite 공식 Vec1도 새 extension이므로 Windows/Docker 바이너리 검증 비용이 남는다.
- PostGIS는 대량 공간 검색에는 강하지만 PostgreSQL 서버 운영, migration, backup, Docker/Windows 개발 경로가 추가된다.
- PgQueuer는 PostgreSQL 전제가 있어 지금의 SQLite 구조와 맞지 않는다. 반대로 PostgreSQL 전환 이후에는 `LISTEN/NOTIFY`와 `SKIP LOCKED`를 직접 구현하는 것보다 전용 라이브러리를 쓰는 편이 코드량과 실패 모드를 줄인다.
- advisory lock은 leader election에는 좋지만, 모든 작업 row 처리 규칙을 직접 설계해야 하므로 queue abstraction으로 남용하지 않는다.

### 결과 (긍정)
- 현재 소형 프로젝트 운영 비용을 유지하면서도 확장 기준이 문서화된다.
- PostGIS나 queue 전환 시 손대야 할 모듈 경계가 명확해진다.
- adapter/wrapper 최소화 원칙을 유지하고, 새 abstraction을 “검증된 병목” 이후로 미룬다.

### 결과 (부정)
- 의미론적 검색 UX 개선은 즉시 제공하지 않는다.
- 규모 증가 시점에는 별도 benchmark, migration rehearsal, 운영 모니터링을 추가해야 한다.
- PostgreSQL 전환 전까지 SQLite write lock과 단일 worker 처리량은 계속 관측 대상이다.

---

## ADR-21: Next.js 16 / React 19 업그레이드와 ESLint flat config 전환

- 상태: accepted
- 날짜: 2026-06-05
- 결정자: AI agent

### 컨텍스트
T-012 이후 `npm audit`은 Next 14 / `eslint-config-next` 계열 transitive 취약점 5건(1 moderate, 4 high)을 보고했고, 자동 수정은 Next 16 major upgrade를 요구했다. T-020에서 최신 Next.js 공식 문서와 npm audit 결과를 기준으로 업그레이드를 수행했다.

참고 기준:

- [Next.js 16 업그레이드 가이드](https://nextjs.org/docs/app/guides/upgrading/version-16)는 Node.js 20.9 이상, React 19.2 이상, `next lint` 제거와 ESLint CLI 전환을 요구한다.
- [Next.js ESLint 설정 문서](https://nextjs.org/docs/app/api-reference/config/eslint)는 `eslint.config.mjs` flat config와 `eslint-config-next/core-web-vitals`, `eslint-config-next/typescript` 조합을 안내한다.
- [Next.js TypeScript 설정 문서](https://nextjs.org/docs/app/api-reference/config/typescript)는 route type generation과 최신 `next-env.d.ts` 참조 경로를 설명한다.

### 결정
- frontend를 Next.js `16.2.7`, React / React DOM `19.2.7`, `eslint-config-next` `16.2.7`로 업그레이드한다.
- ESLint는 하위 plugin peer 범위와 맞는 `9.39.4`를 사용한다. `next lint`가 제거되었으므로 `npm run lint`는 `eslint .`를 실행한다.
- `.eslintrc.json`은 삭제하고 `eslint.config.mjs` flat config로 전환한다. 내부 호환 wrapper 없이 Next가 제공하는 config 배열을 직접 조합한다.
- `npm run type-check`는 clean checkout에서도 `.next/dev/types`를 생성할 수 있도록 `next typegen && tsc --noEmit`을 실행한다.
- Next 16 Turbopack build에서 package CSS import가 더 엄격해졌으므로, Tailwind v4용 `tw-animate-css` / `shadcn/tailwind.css` import를 제거하고 Tailwind v3 호환 `tailwindcss-animate` plugin으로 select animation utility를 제공한다.
- Next 내부 `postcss@8.4.31` transitive audit 항목은 root `postcss@8.5.15`로 맞추는 npm `overrides`(`"postcss": "$postcss"`)로 해소한다.

### 근거
- Next 14에 남아 있으면 audit high 항목이 지속된다.
- 현재 앱은 App Router 기반이며 `cookies()`, `headers()`, `params`, `searchParams`, middleware/proxy 같은 breaking API 사용이 거의 없어 major upgrade 영향이 제한적이다.
- ESLint 10은 일부 Next 하위 ESLint plugin peer 범위와 맞지 않아 경고가 발생했다. ESLint 9는 Next 16 요구사항을 충족하면서 peer warning이 없다.
- package CSS import를 빌드 도구 alias로 우회하기보다 Tailwind v3 플러그인과 명시 class 표기로 정리하면 Next/Turbopack 전환에 덜 취약하다.

### 결과 (긍정)
- `npm audit` 취약점이 0건으로 해소된다.
- Next 16 기본 Turbopack production build와 React 19 런타임에서 E2E 4건이 통과한다.
- lint/type-check/build 명령이 최신 Next CLI 흐름과 맞는다.

### 결과 (부정)
- Next 16과 React 19는 major upgrade이므로 앞으로 shadcn/ui 또는 Base UI 업데이트 시 peer compatibility를 계속 확인해야 한다.
- `postcss` override는 Next가 내부 의존성을 올릴 때 제거 가능 여부를 재검토해야 한다.
- Tailwind v4 전환은 이번 범위에서 제외했으므로, shadcn CLI가 생성하는 Tailwind v4용 CSS import는 계속 수동으로 걸러야 한다.

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
- 에이전트/Codex가 이 저장소에서 실행하는 작업 명령은 기본적으로 WSL2(Ubuntu) bash에서 수행한다.
- 예외는 `git` 명령과 Windows 호스트 Playwright E2E(`cd tests; npm install; npx playwright install; npx playwright test`)뿐이다.
- `gh`, Docker, Python, Node.js, 테스트, 빌드, 파일 검색·확인 명령은 WSL에서 실행한다. 이 규칙은 Windows 네이티브 앱 실행 경로를 되살리지 않기 위한 운영 규칙이다.

### 예외 — E2E Playwright는 Windows 호스트에서 실행 (2026-06-09 보강)
- 위 "Linux Docker 전용" 모델은 **애플리케이션 런타임/배포**에 적용된다(backend, frontend, mcp, scheduler, rustfs).
- **E2E Playwright 테스트 하니스만은 의도적으로 Windows 호스트에서 실행한다.** 즉 `cd tests; npm install; npx playwright install; npx playwright test`를 Windows에서 구동해 실제 사용자 환경(Windows 브라우저)에 가까운 화면 검증을 수행한다. 이는 앱 구동 환경의 예외가 아니라 테스트 하니스에 한정된 예외다.
- 이 예외는 Windows 네이티브 **앱**(backend/frontend/mcp/scheduler) 실행 경로나 앱 런타임 코드의 `win32` 분기를 되살리지 않는다. 다만 **E2E 런처 스크립트(`tests/scripts/start-backend.mjs`·`start-frontend.mjs`)는 Windows 호스트에서 동작해야 하므로 OS별 처리(venv interpreter 경로 해석, `taskkill` 기반 자식 프로세스 트리 정리)를 유지한다.** 이는 테스트 하니스에 한정된 분기이며 앱 코드에는 적용되지 않는다. E2E backend는 `APP_ENV=e2e`로 무인증 동작한다(ADR-24).
- 따라서 ADR-6의 "Playwright E2E를 Windows에서 검증" 의도는 **테스트 하니스 차원에서 유지**되고, supersede 되는 것은 앱 구동 환경(=Linux/WSL2 Docker)에 한정된다.

### 관련
- ADR-18(단일 호스트 Docker Compose 실행 계약)을 유일 실행 경로로 강화한다.
- ADR-6(Windows 환경 Playwright E2E 파이프라인) 중 앱 구동 환경 부분을 supersede 한다. 단, **E2E 테스트 하니스의 Windows 호스트 실행은 위 예외로 유지**한다(도구·구동 호스트 모두 Windows, 앱 런타임만 Linux/WSL2).
- ADR-24(REST API 버저닝과 외부 호출용 인증)의 `APP_ENV` 기반 로컬 우회는 Windows E2E 하니스(`APP_ENV=e2e`)에도 동일하게 적용된다.

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
