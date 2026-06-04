<div align="center">
  <img src="https://img.shields.io/badge/Next.js-000000?style=for-the-badge&logo=nextdotjs&logoColor=white" alt="Next.js" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Gemini_API-8E75C2?style=for-the-badge&logo=google-gemini&logoColor=white" alt="Gemini" />
  <img src="https://img.shields.io/badge/SQLite3-003B57?style=for-the-badge&logo=sqlite&logoColor=white" alt="SQLite3" />
  <img src="https://img.shields.io/badge/Playwright-2EAD33?style=for-the-badge&logo=playwright&logoColor=white" alt="Playwright" />

  <h1>🗺️ TripMate Agent</h1>
  <p><strong>Gemini AI와 VWorld 지도를 활용한 지능형 유튜브 여행 콘텐츠 큐레이션 및 검색 플랫폼</strong></p>
</div>

<br />

`tripmate-agent`는 유튜브의 방대한 여행 콘텐츠 영상을 지능적으로 탐색하고, Gemini API를 통해 영상 내용 요약 및 추천 여행지를 자동으로 발라내어 데이터베이스화하는 여행 데이터 구축 애플리케이션입니다.

수집된 장소 정보는 Kakao, Naver, VWorld 공급자 어댑터 기반 Geocoding/Reverse Geocoding을 통해 정밀 주소와 위경도로 보정된 후, 프론트엔드의 `maplibre-vworld-js` 지도 위에 매핑됩니다. 사용자는 웹의 리스트 및 지도 뷰로 정보를 확인하고, AI 에이전트는 MCP 서버의 읽기/쓰기 도구로 같은 데이터를 조회·보정·실행할 수 있습니다.

## 핵심 특징

- **지능형 YouTube 검색 (ETL 1단계)**: 사용자가 지정한 키워드를 조합하여 적절한 검색 질의를 도출하되, Gemini를 호출하여 검색어를 풍부하게 확장하고 보정한 뒤 업데이트를 탐색합니다.
- **영상 요약 및 장소 데이터베이스화 (ETL 2단계)**: 새로 탐색된 영상 내용과 스크립트를 Gemini API를 활용해 자동으로 정리/요약하고 여행 목적지 정보를 추출하여 SQLite3 데이터베이스에 적재합니다.
- **위치 보정 및 정보 보완 (ETL 3단계)**: 텍스트 형태로 적재된 불완전한 주소명을 Kakao Local API, Naver API, VWorld API 공급자 어댑터와 연동해 실제 경위도 좌표 및 표준 주소로 치환 및 가공합니다. `kraddr-geo` 연계는 현재 계획에서 제외합니다.
- **MCP 서버 읽기/쓰기 UX**: AI 에이전트가 여행지 검색, ETL 상태 조회, 키워드·유튜버 CRUD, 지오코딩 재시도, Deep Research 실행, 중복 병합을 도구 호출로 수행할 수 있도록 MCP 서버를 제공합니다.
- **운영형 ETL 복원력**: `yt-dlp` 기반 메타데이터 수집, 3단계 자막 폴백, FFmpeg 대표 프레임 추출, 작업 상태/heartbeat/retry 기록, API 429 지수 백오프를 계획에 포함합니다.
- **Next.js & React 모던 프론트엔드**:
  - 수집 데이터 통합 뷰(리스트 및 지도 뷰).
  - VWorld 지도를 표시하기 위해 `maplibre-vworld-js` 연동.
  - 검색 키워드 및 구독 유튜버 정보 관리 CRUD 패널.
  - 상세 설정 화면 (사용할 Gemini 엔진 버전, API 토큰 상세 셋업 등).
- **Gemini Deep Research 상세 조사**: 리스트나 지도에서 특정 여행지를 선택하여 Gemini Deep Research 모듈을 가동, 해당 지역에 대한 정밀 정보를 대화형/지식 백과 형태로 심층 수집하여 로컬 DB를 지속 고도화합니다.
- **Windows 최적화 개발 및 테스트**: Windows 호스트 환경에서 안정적으로 빌드되고 작동하며, Playwright 기반 E2E 검증 절차를 기본으로 포함합니다.

## 시스템 구성도

```
[YouTube 영상/스크립트] 
       │ (ETL 1단계: Gemini 검색어 보정 및 탐색)
       ▼
[ETL Pipeline (etl/)] ──(ETL 2단계: Gemini API 요약)──► [SQLite3 DB]
       │                                                    ▲
       │ (ETL 3단계: Geocoding/Reverse Geocoding)           │ (Deep Research)
       └────────────────────────────────────────────────────┘
                               ▲
                               │ API 요청 / MCP 도구 호출
                               ▼
                        [FastAPI Backend]
                         ▲               ▲
                         │               │
                         ▼               ▼
              [Next.js 프론트엔드]   [MCP 서버]
          (maplibre-vworld-js)      (읽기/쓰기 도구)
```

## 시작하기

본 프로젝트는 Windows 호스트 환경에서의 개발 및 테스트에 최적화되어 있습니다.

### 환경 변수 설정
루트에 `.env.example`을 참고하여 `.env` 파일을 생성합니다:
```bash
# VWorld 지도 서비스 키 (프론트엔드 테스트용)
NEXT_PUBLIC_VWORLD_SERVICE_KEY=your_vworld_key_here

# Gemini API 키 및 기본 엔진 버전
GEMINI_API_KEY=your_gemini_key_here
GEMINI_ENGINE_VERSION=gemini-2.0-flash

# YouTube API 키 (할당량 초과 시 스크래퍼 백업 동작)
YOUTUBE_API_KEY=your_youtube_key_here

# 지오코딩 / 역지오코딩
GEOLOCATION_PROVIDER=kakao
KAKAO_REST_API_KEY=your_kakao_rest_api_key_here
NAVER_CLIENT_ID=your_naver_client_id_here
NAVER_CLIENT_SECRET=your_naver_client_secret_here
VWORLD_SERVICE_KEY=your_vworld_server_key_here

# MCP 서버 쓰기 도구 활성화
MCP_WRITE_ENABLED=true
```

### 1. 백엔드 (FastAPI) 빌드 및 실행
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```
백엔드는 기본적으로 `http://localhost:8000`에서 실행됩니다.

### 2. 프론트엔드 (Next.js) 빌드 및 실행
```powershell
cd ../frontend
npm install
npm run dev
```
프론트엔드는 기본적으로 `http://localhost:3000`에서 실행됩니다.

### 3. E2E 테스트 실행 (Playwright)
```powershell
cd ../tests
npm install
npx playwright install
npx playwright test
```

## 참고 문서

- [`AGENTS.md`](./AGENTS.md) — 프로젝트 내 문서화 언어 정책 및 에이전트 개발 규칙
- [`CLAUDE.md`](./CLAUDE.md) — 세션 연동 프로젝트 현황 및 소스 트리 구조 설명
- [`SKILL.md`](./SKILL.md) — 에이전트 지침서, Windows 개발 팁 및 도메인 어휘집
- [`docs/architecture.md`](./docs/architecture.md) — ETL 파이프라인 및 백엔드/프론트엔드 데이터 상세 아키텍처
- [`docs/decisions.md`](./docs/decisions.md) — 주요 아키텍처 결정 기록 (ADR)
- [`docs/tasks.md`](./docs/tasks.md) — 개발 진행 현황 및 백로그 태스크
- [`docs/dev-environment.md`](./docs/dev-environment.md) — 상세 개발 서버 셋업 매뉴얼

## 라이선스

MIT License.
