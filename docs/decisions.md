# DECISIONS — Architecture Decision Records

본 문서는 `tripmate-agent` 프로젝트의 아키텍처 및 구현 의사결정을 시간순으로 누적한다. 결정이 뒤집힐 때도 이전 기록은 지우지 않고 `superseded by ADR-XXX`로 표시한다.

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
- 브라우저 DOM 조작이 필수적인 지도 라이브러리(`maplibre-vworld-js`)와 Client Component 경계를 명확하게 구분하여 연동할 수 있다.

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
Python 진동판인 **FastAPI**를 API 백엔드로 선정하고, ORM으로 **SQLAlchemy 2.0**을 사용하여 로컬 파일 기반의 **SQLite3** 데이터베이스에 연동한다.

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

## ADR-4: `maplibre-vworld-js` 지도 컴포넌트 통합 및 `.env`를 통한 API 키 주입

- 상태: accepted
- 날짜: 2026-06-03
- 결정자: AI agent, human

### 컨텍스트
한국 국토정보에 특화된 상세 배경 맵을 UI에 올리기 위해 VWorld 지도가 요구되었으며, 이를 MapLibre와 통합한 `maplibre-vworld-js` 라이브러리의 테스트 베드가 필요하다.

### 결정
프론트엔드 지도 뷰 영역에 **`maplibre-vworld-js`** 라이브러리를 직접 임포트하여 사용하며, 테스트 시 서비스 키는 `.env` 환경 변수에서 로드한다.

### 근거
- `maplibre-vworld-js`를 활용하여 Base Map, Hybrid, Satellite 레이어를 토글할 수 있는 뛰어난 지도 인터랙션을 제공한다.
- API 서비스 키의 유출을 막기 위해 Next.js의 `process.env.NEXT_PUBLIC_VWORLD_SERVICE_KEY` 규칙으로 통제한다.

### 결과 (긍정)
- 한국 주소 체계에 최적화된 국토교통부 VWorld 위성 및 기본 지도를 WebGL 네이티브 60fps 인터페이스로 렌더링.

### 결과 (부정)
- VWorld API 키 발급이 안 되어 있거나 호출 도메인이 `localhost`로 제한되어 있을 경우를 위해 fallback 처리가 필수적이다.

---

## ADR-5: YouTube API 할당량 절약을 위한 Scraping / Caching 전략

- 상태: accepted
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

- 상태: accepted
- 날짜: 2026-06-03
- 결정자: AI agent, human

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
