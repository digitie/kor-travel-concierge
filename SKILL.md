# SKILL — tripmate-agent 에이전트 매뉴얼

> 이 파일은 당신(AI 에이전트)이 작업을 시작하기 전 반드시 읽어야 한다.
> Windows 개발 환경 셋업과 Gemini API, YouTube API 최적화에 대한 팁을 담고 있다.

## 1. 정체성

이 저장소(GitHub 저장소 이름 `tripmate-agent`)는 유튜브 여행 컨텐츠에서 장소 정보를 추출하고 정리하여 여행 지도 서비스를 제공하는 **AI 기반 여행 큐레이션 애플리케이션**이다.
- **프론트엔드**: Next.js (App Router) + React. `maplibre-vworld-js`를 활용하여 VWorld 지도 시각화를 시뮬레이션 및 구현한다.
- **MCP 서버**: AI 에이전트가 여행지, 키워드, 유튜버, 작업 상태를 조회하고 CRUD, 보정, 병합, 실행 트리거를 수행하는 읽기/쓰기 도구 UX를 제공한다.
- **백엔드**: FastAPI + SQLAlchemy 2.0. SQLite3 데이터베이스에 연동하여 비즈니스 데이터 및 설정 정보를 보관한다.
- **ETL 모듈**: YouTube 데이터 검색(Gemini 보정) → 자막/전사/POI 추출(Gemini API) → 대표 프레임 추출(yt-dlp/FFmpeg) → 외부 REST API를 통한 Geocoding/Reverse Geocoding을 수행한다.

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

### 프론트엔드 실행
```powershell
cd frontend
npm install
npm run dev
```

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
3. **YouTube API 할당량 무단 낭비 금지**: 검색 API(YouTube Data API v3 search)는 1회 호출에 100 할당량을 소모하여 일일 제한(10,000)을 빠르게 채운다. 따라서:
   - Gemini API를 활용하여 검색 키워드를 조합 및 극도로 최적화한 후 호출 횟수를 조율한다.
   - 가능하면 `yt-dlp` 기반 메타데이터 수집과 비공식 파서를 함께 검토하여 할당량 소모를 방어한다.
   - 한 번 수집된 비디오 정보는 SQLite3 데이터베이스에 캐싱하여 재수집을 배제한다.
4. **FastAPI 비동기 세션 leak 방지**: SQLAlchemy 2.0의 `AsyncSession` 또는 동기 `Session`을 사용할 때 Context Manager(`with` 또는 `async with`)를 사용하거나 Depends 주입 방식을 명확히 준수하여 DB 연결 누수를 막는다.
5. **Windows 비호환 쉘 파일 작성 금지**: 윈도우 환경이므로 `.sh` 파일에 개발 유틸 스크립트를 작성하여 그것으로만 검증하도록 요구하지 않는다. 가급적 Node.js 스크립트(`package.json` scripts)나 Python 스크립트, 혹은 `.ps1` 형태로 크로스 플랫폼을 고려해 작성한다.
6. **`kraddr-geo` 연계 재도입 금지**: 최신 요청에 따라 `kraddr-geo` 연계는 취소되었다. Geocoding/Reverse Geocoding은 Kakao, Naver, VWorld 공급자 어댑터로 정리한다.

## 4. 자주 묻는 작업

### 데이터베이스 스키마 및 CRUD 추가
- **위치**: `backend/app/models/`에 SQLAlchemy 2.0 스타일 모델 정의.
- **설명**: CRUD 관련 엔드포인트는 `backend/app/api/` 폴더 내에 배치하며, 스키마 검증은 Pydantic v2를 사용한다.

### Gemini API 프롬프트 및 엔진 설정
- **위치**: `etl/summarize.py` 및 `etl/search.py`.
- **설명**: 설정값(Gemini 엔진 버전 등)은 DB의 `settings` 테이블 혹은 `.env` 환경 변수에서 동적으로 읽어오도록 구성하며, 프롬프트는 한국어 여행 정보 추출에 맞게 정제한다.

### ETL 복원력 구현
- **위치**: `etl/` 디렉토리와 백엔드 작업 상태 모델.
- **설명**:
  - 검색 키워드는 원본 키워드와 Gemini 파생 키워드를 1:N으로 저장하고 `season_context`를 남긴다.
  - YouTube 수집은 YouTube Data API 최소 호출, `yt-dlp` `skip_download`, `extract_flat` 조합을 우선 고려한다.
  - 자막은 `youtube-transcript-api` → `yt-dlp` 자막 추출 → `faster-whisper` 순서로 폴백한다.
  - Gemini POI 추출은 자유 텍스트가 아니라 JSON Schema 기반 결과를 요구한다.
  - 장시간 작업은 `etl_jobs`에 상태, heartbeat, retry_count, last_error를 기록한다.

### MCP 서버 도구 추가
- **위치**: `mcp/` 디렉토리 및 FastAPI 도메인 서비스.
- **설명**:
  - 읽기 도구는 여행지 검색, 상세 조회, 영상별 장소 조회, ETL 상태 조회, 실패 작업 조회를 제공한다.
  - 쓰기 도구는 키워드/유튜버/재생목록 CRUD, 지오코딩 재시도, Deep Research 트리거, 여행지 보정, 중복 병합을 제공한다.
  - 쓰기 도구는 Pydantic 스키마 검증, 멱등 키, 감사 로그 기록을 반드시 거친다.

### Playwright E2E 시나리오 생성
- **위치**: `tests/e2e/` 디렉토리에 `.spec.ts` 파일 추가.
- **설명**: 프론트엔드 Next.js 개발 서버와 백엔드 FastAPI 서버를 동시에 띄운 뒤 Playwright 테스트를 실행해야 하므로, `tests/playwright.config.ts` 파일의 `webServer` 설정을 적절히 구성한다.

## 5. 도메인 어휘

| 용어 | 정의 |
|------|------|
| **Deep Research** | 사용자가 선택한 특정 여행지에 대해 Gemini API를 활용하여 보다 정밀하고 광범위한 세부 조사를 수행하고 데이터베이스를 업데이트하는 기능. |
| **YouTube Curation** | 키워드 CRUD 및 유튜버 CRUD를 통해 등록된 탐색 소스를 바탕으로, 효율적으로 신규 업데이트를 수집하고 여행 관련성 정보를 발라내는 로직. |
| **maplibre-vworld-js** | VWorld 오픈 API 베이스맵 타일을 MapLibre GL JS 위에서 쉽게 다루도록 지원하는 래퍼 컴포넌트. |
| **MCP 서버 UX** | AI 에이전트가 브라우저 없이도 여행 데이터베이스를 읽고 쓰는 도구 기반 사용자 경험. |
| **Geocoding API** | YouTube 영상 설명 속 불완전한 텍스트 장소명을 Kakao Local API 또는 Naver API로 표준 주소 및 위경도에 매핑하는 외부 REST 서비스. |
| **Reverse Geocoding API** | 위경도 좌표를 VWorld API 등으로 행정 주소, 도로명 주소, 지번 주소에 매핑하는 외부 REST 서비스. |
| **ETL Runner** | 수집(Extract), 요약(Transform), 보정(Load) 단계를 조율하여 백그라운드 또는 CLI 명령으로 전체 여행지 데이터를 자동 갱신해주는 실행 스크립트. |

## 6. 작업 후 체크리스트

- [ ] Python 가상 환경에서 `pytest` 테스트 통과
- [ ] 프론트엔드 TypeScript 오류(`npm run type-check`) 및 린터 체크 통과
- [ ] Windows Playwright E2E 테스트 통과
- [ ] `docs/tasks.md` 및 `docs/journal.md` 문서 최신화
- [ ] PR 제출 및 코드 정합성 검증 확인
