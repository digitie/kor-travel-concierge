# Windows 개발 및 평가 환경 구축 가이드

본 문서는 Windows 10/11 호스트 운영체제 환경에서 `tripmate-agent` 프로젝트의 프론트엔드, 백엔드, ETL 스크립트 및 Playwright E2E 테스트를 빌드하고 실행하기 위한 상세 절차를 다룬다.

---

## 1. 사전 요구사항

Windows 호스트에 다음 도구들이 설치되어 있어야 합니다.

- **Node.js**: v20 LTS 이상 ([다운로드](https://nodejs.org/))
- **Python**: v3.10 이상 (Windows x86-64 executable installer로 설치 시 'Add Python to PATH' 옵션 필수 활성화)
- **SQLite3**: Python에 기본 내장되어 있으므로 별도 데이터베이스 설치 불필요. (원할 경우 DB Browser for SQLite 등의 GUI 클라이언트 권장)
- **Git**: Windows용 Git 설치 ([다운로드](https://git-scm.com/))

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

4. 개발 서버를 실행합니다:
   ```powershell
   python main.py
   ```
   서버는 기본적으로 `http://localhost:8000`에서 실행되며, API 명세(Swagger UI)는 `http://localhost:8000/docs`에서 확인할 수 있습니다.

---

## 3. 프론트엔드 (Next.js) 환경 구축

1. `frontend` 디렉토리로 이동하여 Node.js 의존성 패키지를 설치합니다:
   ```powershell
   cd ../frontend
   npm install
   ```

2. 로컬 개발 환경용 `.env` 파일을 생성합니다:
   ```powershell
   Copy-Item .env.example .env
   ```
   `.env` 파일을 메모장 등으로 열고, 발급받은 VWorld 지도 서비스 API 키를 입력합니다:
   ```env
   NEXT_PUBLIC_VWORLD_SERVICE_KEY=your_vworld_api_key_here
   ```

3. Next.js 개발 서버를 실행합니다:
   ```powershell
   npm run dev
   ```
   웹 브라우저에서 `http://localhost:3000`으로 접속하여 프론트엔드 화면을 확인합니다.

---

## 4. ETL 파이프라인 작동 테스트

ETL 프로세스는 백엔드 가상환경이 활성화된 상태에서 별도 Python 명령으로 트리거하거나 크론탭(Cron) 형태로 수행됩니다.

1. `.env` 환경 변수가 루트에 선언되어 있거나, `etl/` 폴더 내에 배치되어 있는지 확인합니다.
2. 가상환경이 활성화된 터미널에서 다음 스크립트를 구동합니다:
   ```powershell
   cd ../etl
   python runner.py
   ```
   - 스크립트가 돌아가며 사용자 등록 키워드로 YouTube를 분석하고 Gemini API, Kakao/Naver 지오코딩, VWorld 역지오코딩을 거쳐 DB에 최종 적재하는 로그를 관측할 수 있습니다.

---

## 5. MCP 서버 로컬 테스트 (구현 후)

MCP 서버는 웹 브라우저를 거치지 않는 AI 에이전트용 읽기/쓰기 UX입니다. T-010 구현 후에는 백엔드와 같은 `.env`를 사용하되, 쓰기 도구 활성화 여부를 명시적으로 확인합니다.

```powershell
MCP_WRITE_ENABLED=true
MCP_TRANSPORT=stdio
```

구현 후 실행 명령은 `mcp/` 디렉토리의 README 또는 스크립트에 맞춰 이 문서에 추가합니다. 모든 쓰기 도구는 감사 로그를 남겨야 하며, Windows 로컬 테스트에서는 실제 API 키가 로그에 출력되지 않는지 함께 확인합니다.

---

## 6. E2E 통합 테스트 (Playwright)

본 프로젝트는 프론트엔드와 백엔드가 정상적으로 메시지를 교환하고 SQLite3 DB 적재 및 VWorld 지도 로딩이 깨지지 않는지 Playwright E2E로 검증합니다.

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

## 7. Windows 트러블슈팅

### 1. SQLite3 DB Locked Error
ETL 스크립트가 대량의 쓰기(Write) 연산을 수행하는 중에 사용자가 웹에서 API를 조회/변경하면 데이터베이스 락이 발생할 수 있습니다.
- **해결책**: 백엔드 DB 세션 커넥션 문자열 설정에 `?timeout=20` 쿼리 파라미터를 붙여 Lock 대기 시간을 기본 5초에서 20초로 연장하거나, SQLite WAL(Write-Ahead Logging) 모드를 명시적으로 켭니다.

### 2. Node.js `node_modules` 빌드 에러
Windows 빌드 도구 누락으로 일부 네이티브 Node 패키지 빌드 오류가 발생할 수 있습니다.
- **해결책**: PowerShell에서 `npm install --global windows-build-tools`를 실행하거나 Visual Studio Installer를 통해 "C++를 사용한 데스크톱 개발" 도구를 설치하십시오.

### 3. VWorld 타일 로드 실패 (403 Forbidden)
지도가 나오지 않고 회색 배경만 출력되는 현상입니다.
- **해결책**: VWorld 개발자 센터에 등록된 API 키의 사용 도메인 설정이 `http://localhost:3000` 및 `http://localhost:8000`을 명시적으로 포함하고 있는지 재차 점검하십시오.
