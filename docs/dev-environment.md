# Windows 개발 및 평가 환경 구축 가이드

본 문서는 Windows 10/11 호스트 운영체제 환경에서 `tripmate-agent` 프로젝트의 프론트엔드, 백엔드, ETL 스크립트 및 Playwright E2E 테스트를 빌드하고 실행하기 위한 상세 절차를 다룬다.

---

## 1. 사전 요구사항

Windows 호스트에 다음 도구들이 설치되어 있어야 합니다.

- **Node.js**: v20 LTS 이상 ([다운로드](https://nodejs.org/))
- **Python**: v3.10 이상 (Windows x86-64 executable installer로 설치 시 'Add Python to PATH' 옵션 필수 활성화)
- **SQLite3 + SpatiaLite**: SQLite3는 Python에 기본 내장되어 있으나, 공간 함수 사용을 위해 SpatiaLite 확장 설치가 필요합니다.
- **Git**: Windows용 Git 설치 ([다운로드](https://git-scm.com/))
- **Docker Desktop**: Docker Compose 기반 단일 호스트 실행 검증과 별도 RustFS 로컬 서비스를 구동하는 데 사용합니다. (T-014)

---

## 2. 백엔드 (FastAPI) 환경 구축

1. `backend` 디렉토리로 이동하여 Python 가상환경(`.venv`)을 생성합니다:
   ```powershell
   cd backend
   python -m venv .venv
   ```

2. 가상환경을 활성화합니다. (PowerShell 기준)
   ```powershell
   .\.venv\Scripts\activate
   ```
   > [!NOTE]
   > 만약 스크립트 실행 권한 오류(`Execution_Policies`)가 발생하면, PowerShell을 관리자 권한으로 열고 `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`를 실행하십시오.

3. 필수 패키지를 설치합니다:
   ```powershell
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. SpatiaLite 확장 경로를 `.env`에 지정합니다:
   ```powershell
   SPATIALITE_EXTENSION_PATH=mod_spatialite
   ```
   Windows에서 확장 로드가 실패하면 OS에 설치된 `mod_spatialite.dll`의 절대 경로를 사용합니다.

5. 개발 서버를 실행합니다:
   ```powershell
   python main.py
   ```
   서버는 기본적으로 `http://localhost:8000`에서 실행되며, API 명세(Swagger UI)는 `http://localhost:8000/docs`에서 확인할 수 있습니다.

---

## 3. RustFS 로컬 미디어 저장소

RustFS는 앱 컨테이너에 포함하지 않고 별도의 로컬 Docker 서비스로 구동합니다. ETL이 확보한 원본 동영상, 자막 파일, 전사 결과, 대표 프레임은 RustFS에 저장하고 SQLite + SpatiaLite에는 객체 URI와 체크섬만 기록합니다.

권장 로컬 포트:

- S3 API: `http://localhost:9003`
- 콘솔: `http://localhost:9004`

`.env`에는 다음 값을 둡니다.

```powershell
RUSTFS_ENABLED=true
RUSTFS_ENDPOINT=http://localhost:9003
RUSTFS_CONSOLE_URL=http://localhost:9004
RUSTFS_ACCESS_KEY=your_rustfs_access_key_here
RUSTFS_SECRET_KEY=your_rustfs_secret_key_here
RUSTFS_BUCKET_RAW_VIDEOS=tripmate-raw-videos
RUSTFS_BUCKET_SUBTITLES=tripmate-subtitles
RUSTFS_BUCKET_FRAMES=tripmate-frames
RUSTFS_HEALTH_PATH=/health/live
MEDIA_RETENTION_POLICY=infinite
```

초기 버킷은 `tripmate-raw-videos`, `tripmate-subtitles`, `tripmate-frames`입니다. 객체 저장소 lifecycle 만료 정책은 설정하지 않습니다. DB에서 영상이나 장소가 제외 처리되더라도 RustFS 객체는 자동 삭제하지 않습니다.

상태 확인은 RustFS 이미지가 제공하는 `/health` 또는 `/health/live` 엔드포인트로 수행합니다. 구현 후에는 PowerShell 실행 스크립트나 Docker Compose 파일에 헬스체크를 명시하고, 객체 업로드·조회 검증을 T-014에서 수행합니다.

---

## 4. 프론트엔드 (Next.js) 환경 구축

1. 프로젝트 루트에서 `frontend` 디렉토리로 이동하여 Node.js 의존성 패키지를 설치합니다:
   ```powershell
   cd frontend
   npm install
   ```

2. 프로젝트 루트로 이동하여 로컬 개발 환경용 `.env` 파일을 생성합니다:
   ```powershell
   cd ..
   Copy-Item .env.example .env
   ```
   `.env` 파일을 메모장 등으로 열고, 발급받은 VWorld 지도 서비스 API 키를 입력합니다:
   ```env
   NEXT_PUBLIC_VWORLD_SERVICE_KEY=your_vworld_api_key_here
   ```

3. Next.js 개발 서버를 실행합니다:
   ```powershell
   cd frontend
   npm run dev
   ```
   웹 브라우저에서 `http://localhost:3000`으로 접속하여 프론트엔드 화면을 확인합니다.

---

## 5. ETL 파이프라인 작동 테스트

ETL 프로세스는 백엔드 가상환경이 활성화된 상태에서 별도 Python 명령으로 트리거하거나, 구현 후 APScheduler 실행자가 `crawl_runs`의 pending 작업을 처리합니다. RustFS가 켜져 있으면 자막, 전사 결과, 대표 프레임, 필요 시 원본 동영상 또는 오디오가 RustFS에 저장되어야 합니다.

1. `.env` 환경 변수가 루트에 선언되어 있거나, `etl/` 폴더 내에 배치되어 있는지 확인합니다.
2. 가상환경이 활성화된 터미널에서 다음 스크립트를 구동합니다:
   ```powershell
   cd ../etl
   python runner.py
   ```
   - 스크립트가 돌아가며 공식 YouTube Data API v3, Gemini API, Kakao/Naver 지오코딩, VWorld 역지오코딩을 거쳐 SQLite + SpatiaLite DB에 최종 적재하는 로그를 관측할 수 있습니다.
   - RustFS 저장이 활성화된 경우 `media_assets`에 객체 URI, 체크섬, 크기, `retention_policy = infinite`가 기록되는지 확인합니다.

---

## 6. MCP 서버 로컬 테스트 (구현 후)

MCP 서버는 웹 브라우저를 거치지 않는 AI 에이전트용 읽기/쓰기 UX입니다. T-010 구현 후에는 백엔드와 같은 `.env`를 사용하되, 쓰기 도구 활성화 여부를 명시적으로 확인합니다.

```powershell
MCP_WRITE_ENABLED=true
MCP_TRANSPORT=stdio
```

구현 후 실행 명령은 `mcp/` 디렉토리의 README 또는 스크립트에 맞춰 이 문서에 추가합니다. 모든 쓰기 도구는 감사 로그를 남겨야 하며, Windows 로컬 테스트에서는 실제 API 키가 로그에 출력되지 않는지 함께 확인합니다.

---

## 7. APScheduler 실행자 테스트 (구현 후)

스케줄러는 API 서버나 MCP 서버가 만든 `crawl_runs.pending` 작업을 단일 실행자로 claim해 처리합니다.

```powershell
SCHEDULER_ENABLED=true
CRAWL_MAX_CONCURRENT_VIDEOS=4
HTTP_MAX_CONCURRENT_REQUESTS=8
```

검증 시 API/MCP가 직접 장시간 작업을 실행하지 않고 `job_id`만 반환하는지 확인합니다.

---

## 8. E2E 통합 테스트 (Playwright)

본 프로젝트는 프론트엔드와 백엔드가 정상적으로 메시지를 교환하고 SQLite + SpatiaLite DB 적재 및 VWorld 지도 로딩이 깨지지 않는지 Playwright E2E로 검증합니다.

1. `tests` 디렉토리로 이동하여 의존 모듈을 설치합니다:
   ```powershell
   cd ../tests
   npm install
   ```

2. Playwright 전용 헤드리스 브라우저를 다운로드합니다:
   ```powershell
   npx playwright install
   ```

3. 백엔드(`localhost:8000`)와 프론트엔드(`localhost:3000`) 개발 서버가 모두 구동 중인 상태에서 테스트를 실행합니다:
   ```powershell
   npx playwright test
   ```
   - 특정 테스트 브라우저 UI를 보면서 시각적으로 검증하고 싶다면 `--headed` 플래그를 추가합니다:
     ```powershell
     npx playwright test --headed
     ```

---

## 9. Windows 트러블슈팅

### 1. SQLite3 DB Locked Error
ETL 스크립트가 대량의 쓰기(Write) 연산을 수행하는 중에 사용자가 웹에서 API를 조회/변경하면 데이터베이스 락이 발생할 수 있습니다.
- **해결책**: 백엔드 DB 세션 커넥션 문자열 설정에 `?timeout=20` 쿼리 파라미터를 붙여 Lock 대기 시간을 기본 5초에서 20초로 연장하거나, SQLite WAL(Write-Ahead Logging) 모드를 명시적으로 켭니다.

### 2. SpatiaLite 확장 로드 실패
`mod_spatialite`를 찾지 못하거나 DLL 의존성이 누락되면 공간 함수 초기화가 실패할 수 있습니다.
- **해결책**: Windows에 SpatiaLite를 설치하고 `SPATIALITE_EXTENSION_PATH`를 실제 `mod_spatialite.dll` 경로로 지정합니다.

### 3. Node.js `node_modules` 빌드 에러
Windows 빌드 도구 누락으로 일부 네이티브 Node 패키지 빌드 오류가 발생할 수 있습니다.
- **해결책**: PowerShell에서 `npm install --global windows-build-tools`를 실행하거나 Visual Studio Installer를 통해 "C++를 사용한 데스크톱 개발" 도구를 설치하십시오.

### 4. VWorld 타일 로드 실패 (403 Forbidden)
지도가 나오지 않고 회색 배경만 출력되는 현상입니다.
- **해결책**: VWorld 개발자 센터에 등록된 API 키의 사용 도메인 설정이 `http://localhost:3000` 및 `http://localhost:8000`을 명시적으로 포함하고 있는지 재차 점검하십시오.

### 5. RustFS 헬스체크 실패
RustFS 컨테이너는 실행 중인데 앱에서 저장소 연결 실패가 발생할 수 있습니다.
- **해결책**: `RUSTFS_ENDPOINT`가 S3 API 포트(`9003`)를 가리키는지 확인하고, 브라우저 콘솔 포트(`9004`)와 혼동하지 마십시오. 사용하는 RustFS 이미지에 따라 `/health`와 `/health/live` 중 실제 200 응답을 반환하는 경로를 `RUSTFS_HEALTH_PATH`에 지정합니다.
