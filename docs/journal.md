# JOURNAL — 작업 일지

본 문서는 `tripmate-agent` 프로젝트의 작업 진행 역사를 역시간순으로 기록한다.

---

## 2026-06-09: T-057 REST API 버저닝(`/api/v1`)과 외부 호출용 API 인증

- **담당자**: Codex
- **작업 내용**:
  - **버저닝 (ADR-24)**: 모든 REST 엔드포인트를 `APIRouter(prefix="/api/v1")` 아래로 이동. 운영 점검용 `GET /health`와 루트 `GET /`는 버전 없이 유지. 향후 비호환 변경은 같은 패턴으로 `/api/v2`를 추가.
  - **인증 코드 (`X-API-Key`)**: `app/core/security.py`의 `require_api_key` 의존성을 라우터 전체에 적용. 설정 `APP_ENV`(기본 `local`)·`API_AUTH_ENABLED`(기본 false)·`API_KEYS`를 추가해 로컬(`local/test/e2e`)은 무인증 우회, 비-local은 유효 키를 강제(키 미설정 시 안전 측 401).
  - **연동 정리**: `docker-compose.yml`이 `APP_ENV`/`API_AUTH_ENABLED`/`API_KEYS`를 전달(기본 로컬 친화). frontend `api.ts`는 `/api/v1` 경로 호출 + `NEXT_PUBLIC_API_KEY` 기반 `X-API-Key` 헤더 주입. E2E backend는 `APP_ENV=e2e`로 무인증. `main.py` 직접 실행 포트를 stale `9041`에서 `0.0.0.0:8000`으로 정정.
  - **검증**: backend pytest 전체 통과(신규 `test_api_auth.py` 6건 포함), `py_compile` 통과.
- **다음 작업**:
  - 현재 등록된 대기 작업 없음.

---

## 2026-06-09: T-056 Windows 네이티브 실행 배제와 Linux Docker/WSL 전용 전환

- **담당자**: Codex
- **작업 내용**:
  - **실행 모델 결정 (ADR-23)**: 실행/평가 환경을 Linux Docker 전용으로 정하고, Windows 호스트는 WSL2(Ubuntu) 안에서 Docker로 구동하도록 정리. `AGENTS.md`의 "Windows 호스트 직접 진행" 정책과 DO-NOT #4를 bash/Linux 기준으로 반전.
  - **PowerShell 자산 제거**: `scripts/ensure-windows-ffmpeg.ps1`, `scripts/start-windows-live.ps1`, `scripts/verify-docker-compose.ps1`을 삭제.
  - **bash 스크립트 추가**: `scripts/verify-docker-compose.sh`(Compose 기동 → health 확인 → `verify_rustfs.py` → 정리)와 thin 런처 `scripts/start-live.sh`(`docker compose up --build`)를 추가.
  - **FFmpeg 단일 경로화**: `FFMPEG_PATH` 기본값을 `/usr/bin/ffmpeg`로 두고 `DOCKER_FFMPEG_PATH` 이원화를 제거. 컨테이너 이미지가 apt로 제공하는 경로만 사용.
  - **host port 복귀**: Windows 라이브 전용 `9041`/`9042`를 표준 `8000`/`3000`으로 되돌리고 `docker-compose.yml`, `config.py`, `.env.example`의 API base URL·CORS 기본값을 정리.
  - **크로스 플랫폼 정리**: frontend `dev:live` 스크립트 제거, `.gitattributes`의 `*.ps1` CRLF 규칙 제거, frame extraction 테스트 stub의 Windows 경로 문자열을 Linux 경로로 교체. 단 E2E 런처(`tests/scripts/start-backend.mjs`·`start-frontend.mjs`)는 Windows 호스트에서 실행되므로 OS별 처리(venv interpreter 경로 해석, `taskkill` 자식 프로세스 트리 정리)를 유지한다(ADR-23 E2E 예외).
  - **문서 재작성**: `docs/dev-environment.md`를 "Linux/Docker(및 Windows WSL2) 개발 환경 구축"으로 전면 개편하고, `README.md`, `SKILL.md`, `CLAUDE.md`, `docs/architecture.md`, `docs/decisions.md`(ADR-23 추가, ADR-6 supersede)를 bash/Docker/WSL2 기준으로 정렬.
  - **검증**: 편집한 backend Python `py_compile`, bash 스크립트 `bash -n` 구문 검사 통과. (Docker/npm 빌드는 호스트 가용성 문제로 실행하지 않음)
- **다음 작업**:
  - 현재 등록된 대기 작업 없음.

---

## 2026-06-08: T-055 Windows Python launcher fallback 정리

- **담당자**: Codex
- **작업 내용**:
  - **Python 선택 함수 분리**: `scripts/start-windows-live.ps1`의 backend Python command 생성을 `Resolve-PythonCommand`로 분리.
  - **3.10+ fallback 적용**: backend venv가 없을 때 `py -3.12`, `py -3.11`, `py -3.10`, `py -3`, `python` 순서로 Python 3.10+ 실행기만 선택하도록 변경.
  - **오류 메시지 보강**: venv가 3.10 미만이거나 3.10+ 실행기를 찾지 못하면 명확한 오류로 중단.
  - **PR #30 추적 갱신**: `docs/pr-review-2026-06.md`의 P3-5 항목을 T-055 후속 해소로 표시.
  - **검증**: Windows PowerShell parser, 고정 `py -3.10` 제거 확인, `git diff --check` 통과.
- **다음 작업**:
  - 현재 등록된 대기 작업 없음.

---

## 2026-06-08: T-054 코드 위생 정리

- **담당자**: Codex
- **작업 내용**:
  - **import 정렬**: `place_service`의 표준 라이브러리 import와 `app.models` import 순서를 정리.
  - **FK delete 정책 명시**: FK가 있는 모델의 `ForeignKey`에 현재 기본 동작과 같은 `ondelete="NO ACTION"`을 명시하고, legacy `video_place_mappings` 재생성 SQL도 같은 선언으로 맞춤.
  - **TimestampMixin 예외 사유 기록**: `YoutubeVideo`는 생성 시각보다 마지막 수집 시각이 도메인 상태라 `crawled_at`을 유지한다는 주석을 추가.
  - **회귀 테스트 추가**: 모델 FK 메타데이터와 legacy rebuild SQL의 delete 정책을 테스트로 검증.
  - **PR #30 추적 갱신**: `docs/pr-review-2026-06.md`의 P3-4 항목을 T-054 후속 해소로 표시.
  - **검증**: 모델/마이그레이션 pytest 13건, backend `compileall` 통과.
- **다음 작업**:
  - PR #30 P3-5 Windows Python launcher fallback 정리를 T-055로 처리한다.

---

## 2026-06-08: T-053 export 파일명 개선

- **담당자**: Codex
- **작업 내용**:
  - **파일명 메타데이터 추가**: `/api/destinations/export`의 응답 파일명에 선택/전체 범위, 실제 내보낸 장소 수, 정렬 기준, UTC timestamp를 포함.
  - **직렬화 경계 유지**: `place_export_service`의 형식별 직렬화는 유지하고, route가 요청 필터 정보를 알고 있는 지점에서 `Content-Disposition` 파일명을 보강.
  - **회귀 테스트 추가**: 선택 export와 전체 export의 파일명 패턴을 API 테스트에서 검증.
  - **PR #30 추적 갱신**: `docs/pr-review-2026-06.md`의 P3-3 항목을 T-053 후속 해소로 표시.
  - **검증**: 관련 API pytest 2건, backend 전체 pytest 152건, backend `compileall`, `git diff --check` 통과.
- **다음 작업**:
  - PR #30 P3-4 코드 위생 정리를 T-054로 처리한다.

---

## 2026-06-08: T-052 FFprobe/FFmpeg 환경변수 범위 정리

- **담당자**: Codex
- **작업 내용**:
  - **runtime 설정 축소**: backend `Settings`와 Docker Compose Python 공통 환경에서 실제 코드가 사용하는 `FFMPEG_PATH`만 유지하고 `FFPROBE_PATH` runtime 주입을 제거.
  - **frontend env 제거**: Next.js frontend compose 서비스에 불필요하게 들어가던 `FFMPEG_PATH`/`FFPROBE_PATH` 환경변수 주입 제거.
  - **Windows live 범위 명확화**: `FFPROBE_PATH`는 `scripts\ensure-windows-ffmpeg.ps1`이 `.env`에 기록하고 `start-windows-live.ps1`이 `ffprobe -version`을 확인하는 사전 검증용 값으로만 문서화.
  - **PR #30 추적 갱신**: `docs/pr-review-2026-06.md`의 P3-2 항목을 T-052 후속 해소로 표시.
  - **검증**: Docker Compose config, Windows PowerShell parser, frame extraction pytest 15건, backend `compileall`, `git diff --check` 통과.
- **다음 작업**:
  - PR #30 P3-3 export 파일명 개선을 T-053으로 처리한다.

---

## 2026-06-08: T-051 PR #30 문서 상태 불일치 정리

- **담당자**: Codex
- **작업 내용**:
  - **tasks backlog 정합화**: `docs/pr-review-2026-06.md`에 남아 있던 P3-2~P3-5를 `docs/tasks.md` 대기 작업 T-052~T-055로 승격.
  - **현재 상태 문서 갱신**: `CLAUDE.md`의 다음 착수 대상을 T-052로 갱신하고, `docs/pr-review-2026-06.md`의 P3-1을 T-051 후속 해소로 표시.
  - **검증**: 문서 diff 공백 검사 통과.
- **다음 작업**:
  - PR #30 P3-2 FFprobe/FFmpeg 환경변수 사용 범위 정리를 T-052로 처리한다.

---

## 2026-06-08: T-050 지오코딩 이름 호환 기준 축소

- **담당자**: Codex
- **작업 내용**:
  - **짧은 부분명 자동 재사용 차단**: `_names_compatible`의 포함 관계 alias 조건을 짧은 쪽 4자 이상, 긴 쪽 대비 60% 이상으로 좁혀 `카페` ↔ `월정리카페` 같은 false-positive를 막음.
  - **구체적 alias 유지**: exact match는 그대로 허용하고, `월정리카페` ↔ `월정리카페본점`, `감천문화마을` ↔ `부산 감천문화마을`처럼 충분히 구체적인 포함 관계는 유지.
  - **회귀 테스트 추가**: 짧은 부분명 근접 후보는 `nearby_place_name_mismatch`로 검수 대기에 남고, 구체적 alias는 호환되는지 검증.
  - **PR #30 추적 갱신**: `docs/pr-review-2026-06.md`의 P2-8 항목을 T-050 후속 해소로 표시.
  - **검증**: geocode service pytest 8건, backend 전체 pytest 152건, backend `compileall`, `git diff --check` 통과.
- **다음 작업**:
  - PR #30 P3-1 문서 상태 불일치 정리를 T-051로 승격해 처리한다.

---

## 2026-06-08: T-049 Gemini engine 설정 단일 출처 정리

- **담당자**: Codex
- **작업 내용**:
  - **backend 단일 출처 추가**: `backend/app/core/config.py`에 `GEMINI_ENGINE_OPTIONS`와 `GEMINI_ENGINE_VERSION_DEFAULT`를 정의하고 `Settings.GEMINI_ENGINE_VERSION` 기본값도 이를 사용하도록 정리.
  - **settings 검증 강화**: `settings_service`가 `gemini_engine_version` 값을 허용 모델 목록으로 검증하고, `/api/settings` 응답에 `gemini_engine_options`와 `gemini_engine_default`를 포함하도록 확장.
  - **frontend 하드코딩 제거**: 설정 화면의 Zod enum과 `SelectItem` 하드코딩을 제거하고 API가 내려주는 모델 옵션으로 select를 렌더링.
  - **실제 호출 연결**: POI 후처리와 Deep Research가 DB runtime 설정의 Gemini engine 값을 `make_gemini_llm(model=...)`에 전달하도록 연결.
  - **PR #30 추적 갱신**: `docs/pr-review-2026-06.md`의 P2-7 항목을 T-049 후속 해소로 표시.
  - **검증**: backend 설정/API/scheduler 테스트, backend `compileall`, frontend `npm run lint`, `npm run type-check`, `npm run build`, Playwright 설정 E2E, `git diff --check` 통과.
- **다음 작업**:
  - PR #30 P2-8 `_names_compatible` 부분일치 관대함 축소를 T-050으로 승격해 처리한다.

---

## 2026-06-08: T-048 heartbeat task 예외 처리 범위 축소

- **담당자**: Codex
- **작업 내용**:
  - **취소 처리 범위 축소**: scheduler `execute_run()`의 heartbeat task 종료 대기에서 `Exception` suppress를 제거하고 `CancelledError`만 정상 취소로 처리.
  - **예상 밖 예외 가시화**: heartbeat task가 이미 실패한 상태라면 `logger.exception`으로 run id와 traceback을 남겨 조용히 사라지지 않도록 보강.
  - **회귀 테스트 추가**: heartbeat task 예외가 job 완료를 막지 않되 로그에는 남는지 검증하는 scheduler worker 테스트 추가.
  - **PR #30 추적 갱신**: `docs/pr-review-2026-06.md`의 P2-6 항목을 T-048 후속 해소로 표시.
  - **검증**: scheduler worker pytest, backend 전체 pytest 147건, backend `compileall`, `git diff --check` 통과.
- **다음 작업**:
  - PR #30 P2-7 engine 모델 설정 단일 출처 정리를 T-049로 승격해 처리한다.

---

## 2026-06-08: T-047 hydration suppress와 VWorld 키 주입 정리

- **담당자**: Codex
- **작업 내용**:
  - **Input hydration suppress 제거**: 공유 `Input` 컴포넌트에서 전역 `suppressHydrationWarning`을 제거해 실제 SSR mismatch가 숨겨지지 않도록 수정.
  - **Windows live VWorld 키 상속 정리**: `scripts/start-windows-live.ps1`은 `.env`에서 읽은 `NEXT_PUBLIC_VWORLD_SERVICE_KEY`를 부모 PowerShell 환경에만 설정하고, frontend child 명령 블록에는 다시 주입하지 않도록 변경.
  - **E2E frontend 환경 정리**: VWorld fallback을 위한 빈 키 기본값은 E2E 시작 스크립트 부모 프로세스에만 설정하고 child는 상속 환경을 사용하도록 정리.
  - **PR #30 추적 갱신**: `docs/pr-review-2026-06.md`의 P2-5 항목을 T-047 후속 해소로 표시.
  - **검증**: frontend `npm run lint`, `npm run type-check`, `npm run build`, `node --check tests/scripts/start-frontend.mjs`, Windows PowerShell parser 검증, `git diff --check` 통과.
- **다음 작업**:
  - PR #30 P2-6 heartbeat 예외 삼킴 범위 축소를 T-048로 승격해 처리한다.

---

## 2026-06-08: T-046 Next 16 후속 정리

- **담당자**: Codex
- **작업 내용**:
  - **Node engine 명시**: frontend `package.json`에 `engines.node >=20.9.0`을 추가해 Next.js 16 런타임 하한을 명시.
  - **Node 타입 정렬**: `@types/node`를 런타임 기준과 맞지 않던 `^25` 계열에서 `^20` 계열로 낮추고 `package-lock.json`을 갱신.
  - **jsx 설정 검증**: `tsconfig.json`의 `jsx: preserve` 권고를 시험했으나 `next typegen`이 Next.js mandatory change로 `react-jsx`를 다시 적용하는 것을 확인해, 현재 Next 16.2.7 도구 강제값을 유지.
  - **PR #30 추적 갱신**: `docs/pr-review-2026-06.md`의 P2-4 항목을 T-046 후속 해소로 표시.
  - **검증**: `npm install --package-lock-only` audit 0건, frontend `npm run lint`, `npm run type-check`, `npm run build`, `git diff --check` 통과.
- **다음 작업**:
  - PR #30 P2-5 `suppressHydrationWarning` 범위와 VWorld 키 중복 주입 정리를 T-047로 승격해 처리한다.

---

## 2026-06-08: T-045 `next-env.d.ts` 생성물 추적 제거

- **담당자**: Codex
- **작업 내용**:
  - **생성물 추적 제거**: `frontend/next-env.d.ts`를 git index에서 제거하고 `.gitignore`에 추가해 Next.js 검증 중 재생성되어도 워크트리가 더러워지지 않도록 정리.
  - **정규화 훅 제거**: 추적 파일을 강제로 되돌리기 위한 `frontend/scripts/normalize-next-env.mjs`와 `posttype-check`/`postbuild` 실행을 제거.
  - **clean checkout 검증**: 실제 `frontend/next-env.d.ts` 파일을 삭제한 상태에서 `next typegen`과 `next build`가 파일을 재생성해도 ignored 상태로 남는지 확인.
  - **PR #30 추적 갱신**: `docs/pr-review-2026-06.md`의 P2-3 항목을 T-045 후속 해소로 표시.
  - **검증**: frontend `npm run lint`, `npm run type-check`, `npm run build`, `git check-ignore -v frontend/next-env.d.ts`, `git diff --check` 통과.
- **다음 작업**:
  - PR #30 P2-4 Next 16 후속 정리를 T-046으로 승격해 처리한다.

---

## 2026-06-08: T-044 keyword/playlist 증분 수집 보강

- **담당자**: Codex
- **작업 내용**:
  - **source target watermark 사용**: `source_targets.last_crawled_at` 조회·갱신 helper를 추가하고, 수집 성공 후 keyword/channel/playlist target의 마지막 성공 크롤 시각을 기록하도록 연결.
  - **keyword 증분 검색**: keyword harvest에서 이전 성공 시각을 YouTube `search.list`의 `publishedAfter`로 전달해 매 실행 full-rescan을 줄이도록 변경.
  - **playlist 증분 중단**: playlist harvest에서 항목의 영상 공개 시각이 target watermark 이하가 되는 지점에서 pagination을 중단하도록 변경.
  - **기존 channel 경로 유지**: channel harvest는 기존처럼 DB의 최신 영상 `published_at` watermark로 uploads playlist pagination을 중단하고, source target crawl 시각도 함께 갱신.
  - **문서 갱신**: 아키텍처와 ADR, PR #30 추적 문서를 target별 watermark 기준으로 갱신.
  - **검증**: keyword `publishedAfter` 전달과 playlist pagination 중단 테스트 추가. `backend/tests/test_etl_pipeline.py`, backend 전체 pytest, `python3 -m compileall backend/app backend/tests`, `git diff --check` 통과.
- **다음 작업**:
  - PR #30 P2-3 `next-env.d.ts` 생성물 추적 정리를 T-045로 승격해 처리한다.

---

## 2026-06-08: T-043 장소 export 직렬화 안정화

- **담당자**: Codex
- **작업 내용**:
  - **export 상한 추가**: `/api/destinations/export`에 기본 500건, 최대 1,000건의 장소 limit을 적용하고, `ids` 목록도 1,000개 초과 시 400 응답으로 제한.
  - **이벤트 루프 격리**: XLSX/GPX/KML 직렬화를 `asyncio.to_thread`로 실행해 ZIP/XML 생성이 FastAPI 이벤트 루프를 직접 막지 않도록 변경.
  - **XML 문자 정제**: XLSX inline string, GPX name/desc, KML name/description에 들어가는 문자열에서 XML 1.0 불법 제어문자를 제거한 뒤 escape하도록 보강.
  - **테스트 보강**: API route가 limit을 clamp하고 직렬화를 별도 thread에서 실행하는지 확인하는 테스트와, XLSX/GPX/KML XML sanitizer 단위 테스트를 추가.
  - **PR #30 추적 갱신**: `docs/pr-review-2026-06.md`의 P2-1 항목을 T-043 후속 해소로 표시.
  - **검증**: 관련 export 테스트, backend 전체 pytest, `python3 -m compileall backend/app backend/tests`, `git diff --check` 통과.
- **다음 작업**:
  - PR #30 P2-2 증분 수집 미완 항목을 T-044로 승격해 처리한다.

---

## 2026-06-08: T-042 docker-compose CORS override와 Windows live 포트 종료 안전장치 보강

- **담당자**: Codex
- **작업 내용**:
  - **Compose CORS override 복구**: `docker-compose.yml`의 `CORS_ALLOW_ORIGINS`가 `.env` 값을 우선하도록 바꾸고, 기본값에 Windows live Web 포트(`9042` 또는 `FRONTEND_HOST_PORT` override), 로컬 개발 `3000`, Compose smoke `13000`, Playwright E2E `13100` origin을 포함.
  - **Windows live CORS 우선순위 정리**: `scripts\start-windows-live.ps1`도 현재 PowerShell 환경변수, `.env`, 기본값 순서로 `CORS_ALLOW_ORIGINS`를 적용하도록 변경.
  - **포트 종료 안전장치**: `Stop-PortOwner`가 포트 점유 프로세스의 command line 또는 executable path에서 현재 TripMate 워크트리 경로가 확인되는 경우에만 자동 종료하도록 보강.
  - **명시 강제 옵션 추가**: 다른 프로세스가 `9041` 또는 `9042`를 점유하면 중단하고, 의도한 종료일 때만 `-ForcePortKill`을 명시하도록 안내.
  - **문서 갱신**: README, 개발 환경, 아키텍처, ADR 실행 계약, PR #30 추적 문서를 새 정책에 맞춤.
  - **검증**: Windows PowerShell parser 검증 통과. `docker compose --env-file .env config --quiet`, `CORS_ALLOW_ORIGINS='http://example.test' docker compose --env-file .env config`, 기본 compose config의 CORS origin 목록 확인 통과.
- **다음 작업**:
  - PR #30 P2-1 export 직렬화 executor 격리, limit 상한, XML 제어문자 정제를 T-043으로 승격해 처리한다.

---

## 2026-06-08: T-041 FFmpeg 자동 다운로드 무결성 검증과 안정 URL 보강

- **담당자**: Codex
- **작업 내용**:
  - **안정 URL 전환**: `scripts\ensure-windows-ffmpeg.ps1`의 기본 FFmpeg 아카이브를 날짜 고정 URL에서 gyan.dev 안정 링크 `https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full.7z`로 변경.
  - **hash 검증 강제**: FFmpeg 아카이브는 `.sha256` sidecar 또는 명시 `-ArchiveSha256` 값을 `Get-FileHash` 결과와 비교한 뒤에만 압축 해제하도록 보강.
  - **portable 7-Zip 검증**: 로컬 7-Zip이 없을 때 내려받는 `7zr.exe`를 버전 고정 GitHub asset과 고정 SHA256으로 검증한 뒤 사용하도록 변경.
  - **압축 해제 안정화**: Windows PowerShell 5.1에서 portable 실행 파일을 pipeline 중간에 직접 실행할 때 발생하는 오류를 피하기 위해 `Start-Process` 기반 압축 해제와 종료 코드 검증으로 전환.
  - **문서 갱신**: README, 개발 환경, 아키텍처, ADR 실행 계약, PR #30 추적 문서를 새 검증 흐름에 맞춤.
  - **검증**: Windows PowerShell parser 검증 통과. `ffmpeg-release-essentials.7z`와 `.sha256` sidecar를 사용한 smoke에서 archive hash 검증, portable `7zr.exe` hash 검증, 압축 해제, `ffmpeg.exe`/`ffprobe.exe` 경로 반환까지 확인.
- **다음 작업**:
  - PR #30 P1-6 docker-compose CORS 하드코딩과 포트 점유 프로세스 강제 종료 보강을 T-042로 승격해 처리한다.

---

## 2026-06-08: T-040 지도 marker diff 기반 캐싱과 선택 재중심 보강

- **담당자**: Codex
- **작업 내용**:
  - **marker cache 도입**: `VWorldMap`의 marker를 `place_id` 기준 cache로 관리해 장소 refresh나 선택 변경 때 기존 marker를 전량 제거·재생성하지 않고 필요한 항목만 추가·갱신·삭제하도록 변경.
  - **이벤트 핸들러 갱신**: marker entry에 click handler와 최신 장소 데이터를 함께 저장하고, 장소 데이터가 바뀌면 popup, 위치, click handler를 최신 값으로 교체.
  - **선택 스타일 분리**: 선택 여부에 따른 marker 크기, 색상, 그림자, 접근성 label을 별도 동기화 함수로 분리해 선택 변경 때 DOM marker만 가볍게 갱신.
  - **재중심 조건 축소**: 선택 장소 이동은 marker cache의 `selectedPlaceId` 항목을 기준으로 선택 변경 때만 수행해, 장소 목록 데이터 refresh가 사용자의 지도 pan 위치를 강제로 되돌리지 않게 보강.
  - **PR #30 추적 갱신**: `docs/pr-review-2026-06.md`의 P1-4 항목을 T-040 후속 해소로 표시.
  - **검증**: frontend `npm run lint`, `npm run type-check`, `npm run build`, Playwright E2E 4건 통과.
- **다음 작업**:
  - PR #30 P1-5 FFmpeg 자동 다운로드 무결성 검증과 안정 URL 보강을 T-041로 승격해 처리한다.

---

## 2026-06-08: T-039 schema_migrations 경량 registry 도입

- **담당자**: Codex
- **작업 내용**:
  - **migration registry 추가**: `schema_migrations` 테이블과 `run_schema_migrations`를 추가해 기존 SQLite DB 보정 작업의 적용 이력을 기록하도록 구성.
  - **기존 보정 통합**: `ensure_crawl_run_status_columns`, `ensure_video_place_mapping_repeatable`을 현재 migration 목록에 등록하고, `init_db()`는 `create_all` 이후 registry를 통해 보정 작업을 실행하도록 변경.
  - **중복 실행 방지**: 이미 적용된 migration id는 다시 실행하지 않고 건너뛰도록 구성.
  - **PR #30 추적 갱신**: `docs/pr-review-2026-06.md`의 P1-3 항목을 T-039 후속 해소로 표시.
  - **검증**: 동일 migration id를 두 번 실행해도 실제 migration 함수는 한 번만 호출되는 테스트 추가. DB migration 테스트 통과.
- **다음 작업**:
  - PR #30 P1-4 지도 marker diff 기반 캐싱과 재중심 조건 보강을 T-040으로 승격해 처리한다.

---

## 2026-06-08: T-038 crawl_runs 원자적 claim 보강

- **담당자**: Codex
- **작업 내용**:
  - **상태 가드 추가**: `claim_next_pending`을 후보 id 조회 후 `WHERE state='pending'` 조건이 있는 `UPDATE ... RETURNING`으로 전환해 같은 pending 작업을 두 실행자가 동시에 claim하지 못하도록 보강.
  - **로그 유지**: claim 성공 후 기존처럼 `작업 실행자가 작업을 시작했습니다.` 상태 로그와 progress `0.05`를 남기도록 유지.
  - **경쟁 테스트 추가**: in-memory `StaticPool` 대신 파일 기반 SQLite 엔진을 사용해 두 세션이 동시에 claim해도 하나만 `running`으로 전이되는지 검증.
  - **PR #30 추적 갱신**: `docs/pr-review-2026-06.md`의 P1-2 항목을 T-038 후속 해소로 표시.
  - **검증**: crawl run service와 scheduler 관련 테스트 통과.
- **다음 작업**:
  - PR #30 P1-3 스키마 드리프트 전반 보강을 T-039로 승격해 처리한다.

---

## 2026-06-08: T-037 원본 미디어 스트리밍 업로드 경로 추가

- **담당자**: Codex
- **작업 내용**:
  - **저장소 인터페이스 확장**: `MediaStore`에 `put_object_stream`을 추가하고, RustFS 구현은 boto3 `upload_fileobj`를 사용해 file-like 객체를 전송하도록 보강.
  - **메타데이터 계산**: `HashingReader`를 추가해 업로드 중 읽은 chunk로 SHA256과 byte 수를 계산하고 `media_assets.sha256`, `size_bytes`에 기록.
  - **원본 저장 API 확장**: `store_raw_media`가 기존 `bytes` 입력과 새 `fileobj` 입력 중 하나만 받도록 변경해, 대용량 원본 동영상은 전체 메모리 적재 없이 저장할 수 있게 구성.
  - **PR #30 추적 갱신**: `docs/pr-review-2026-06.md`의 P1-1 항목을 T-037 후속 해소로 표시.
  - **검증**: 원본 동영상 streaming 저장 테스트를 추가하고 frame extraction/media store 관련 테스트를 통과.
- **다음 작업**:
  - PR #30 P1-2 `claim_next_pending` 원자적 claim 보강을 T-038로 승격해 처리한다.

---

## 2026-06-08: T-036 video_place_mappings stale unique 제약 제거

- **담당자**: Codex
- **작업 내용**:
  - **기존 DB 보정**: `init_db()`에 `ensure_video_place_mapping_repeatable`을 추가해 `video_place_mappings(video_id, place_id)` 반복 등장 unique 제약이 기존 SQLite DB에 남아 있으면 제거하도록 구성.
  - **table-level constraint 대응**: 과거 `UniqueConstraint`로 생성된 SQLite DB는 autoindex를 직접 DROP할 수 없으므로, 현재 스키마로 `video_place_mappings` 테이블을 재생성하고 기존 데이터를 보존한 뒤 `video_id`/`place_id` 일반 index를 복원.
  - **명시 index 대응**: 개발 DB에 명시 unique index로 남은 경우도 `DROP INDEX IF EXISTS uq_video_place_mappings_video_place`로 정리.
  - **PR #30 추적 갱신**: `docs/pr-review-2026-06.md`의 P0-3 항목을 T-036 후속 해소로 표시.
  - **검증**: legacy unique table을 구성한 뒤 보정 helper를 실행하고 같은 영상·장소 매핑 2건을 insert하는 회귀 테스트 추가. backend 관련 테스트 통과.
- **다음 작업**:
  - PR #30 P1 후속 항목을 우선순위대로 task로 승격해 처리한다.

---

## 2026-06-08: T-035 Deep Research scheduler handler 등록

- **담당자**: Codex
- **작업 내용**:
  - **handler 등록**: scheduler `DEFAULT_HANDLERS`에 `deep_research`를 추가해 REST/MCP가 생성한 Deep Research 작업이 더 이상 unsupported `job_type`으로 즉시 실패하지 않도록 수정.
  - **조사 서비스 추가**: `deep_research_service`를 추가해 장소 정보와 사용자 `prompt`, `max_sources`를 Gemini JSON Schema 요청으로 보내고, 결과를 `travel_places.detailed_research_content`, `gemini_enriched_description`, `last_reviewed_at`에 저장하도록 연결.
  - **상태 로그 보강**: Deep Research 프롬프트 구성, Gemini 상세 조사, 결과 저장 단계를 `crawl_runs.status_log_json`에 남기도록 reporter를 연결.
  - **PR #30 추적 갱신**: `docs/pr-review-2026-06.md`의 P0-2 항목을 T-035 후속 해소로 표시.
  - **검증**: scheduler 기본 실행에서 `deep_research` 작업이 `done`으로 완료되고 장소 상세 조사 필드가 갱신되는 단위 테스트를 추가. 관련 scheduler/API/MCP 테스트 통과.
- **다음 작업**:
  - PR #30 P0-3 기존 SQLite DB의 stale unique index 제거를 T-036으로 승격해 처리한다.

---

## 2026-06-08: T-034 Tailwind 색상 토큰 alpha modifier 보강

- **담당자**: Codex
- **작업 내용**:
  - **alpha modifier 복구**: Tailwind semantic 색상 토큰을 `opacityValue`를 받는 함수형 토큰으로 전환해 `bg-muted/70`, `ring-ring/50`, `bg-destructive/10`, invalid focus ring 등 opacity modifier가 실제 CSS로 생성되도록 수정.
  - **누락 토큰 보강**: `--destructive-foreground`를 light/dark theme에 추가하고, `--sidebar-ring` 선언의 세미콜론 누락을 정리.
  - **PR #30 추적 갱신**: `docs/pr-review-2026-06.md`의 P0-1 항목을 T-034 후속 해소로 표시.
  - **검증**: Tailwind CLI 산출물에서 `bg-muted/70`, `bg-muted/30`, `focus-visible:ring-ring/50`, `bg-destructive/10`, `focus-visible:ring-destructive/20`, `focus-visible:border-destructive/40`, `ring-foreground/10` class 생성을 확인. frontend `npm run lint`, `npm run type-check`, `npm run build`, Playwright E2E 4건 통과.
- **다음 작업**:
  - PR #30 P0-2 `deep_research` job handler 미등록 문제를 T-035로 승격해 처리한다.

---

## 2026-06-08: T-033 RustFS 로컬 설정 워크트리 동기화

- **담당자**: Codex
- **작업 내용**:
  - **기준값 확인**: `python-kraddr-geo-codex`의 RustFS 운영 기준이 S3 API `9003`, console `9004`, 기본 credential `rustfsadmin`, 로컬 운영 주체 `kraddr-geo-rustfs`임을 확인.
  - **로컬 credential 통일**: 현재 워크트리와 `tripmate-agent-live-test`의 `.env` RustFS credential을 `python-kraddr-geo` 기본값과 맞추고, 두 워크트리의 RustFS 블록이 동일한지 마스킹 diff로 확인.
  - **설정 표면 정리**: `.env.example`, README, `SKILL.md`, Docker Compose, `Settings`, RustFS init/verify 스크립트, scaffold `etl/media.py`가 호스트 `http://127.0.0.1:9003`, Docker 내부 `http://rustfs:9000`, 단일 `krtour-map` 버킷, `features/` prefix, public base URL `http://127.0.0.1:9003/krtour-map`을 쓰도록 정리.
  - **live-test 보강**: `tripmate-agent-live-test`에 빠져 있던 `RUSTFS_PUBLIC_BASE_URL`, `RUSTFS_DOCKER_ENDPOINT`, `RUSTFS_OBJECT_PREFIX`, `RUSTFS_REGION`과 관련 테스트 기대값을 반영.
  - **런타임 반영**: 실행 중이던 `tripmate-agent-rustfs-1`을 새 `.env` 기준으로 재생성해 컨테이너 credential도 `rustfsadmin`으로 맞춤.
  - **검증**: `docker compose --env-file .env config --quiet`, backend `.venv/bin/pytest --capture=no -q` 137건, `python3 -m compileall`, frontend `npm run lint`, `npm run type-check`, `npm run build`, RustFS `krtour-map/features/healthcheck/t014-smoke.txt` 객체 smoke, Playwright E2E 4건 통과.
- **다음 작업**:
  - PR #30 리뷰 종합 문서의 P0 후속 항목을 task로 승격해 순차 처리한다.

---

## 2026-06-08: T-032 harvest 후처리 장소 생성 연결 및 RustFS 설정 반영

- **담당자**: Codex
- **작업 내용**:
  - **장소 생성 본수정**: `pipeline.run_harvest`가 적재한 `video_ids`를 반환하고, scheduler `harvest` handler가 신규 영상의 자막 추출, Gemini POI 요약, 지오코딩 적용 후처리를 이어 실행하도록 `postprocess_service`를 추가.
  - **장소 목록 반영 보장**: 후처리에서 확정 가능한 후보는 `travel_places`와 `video_place_mappings`까지 생성하고, 모호하거나 공급자 키가 없는 후보는 `needs_review`로 남기도록 구성.
  - **상세 상태 로그 연결**: 자막 추출, RustFS 저장, Gemini 보정, 후보 생성, 위치 보정, 확정 장소/검수 대기 집계를 scheduler reporter로 기록해 작업 상태 타임라인에 남기도록 연결.
  - **RustFS 개발 설정 반영**: 로컬 venv/브라우저 기준 endpoint를 `http://127.0.0.1:9003`, Docker 내부 endpoint를 `http://rustfs:9000`, 단일 버킷을 `krtour-map`, object prefix를 `features`, 공개 URL 기준을 `http://127.0.0.1:9003/krtour-map`으로 정리. 로컬 `.env`에는 제공된 개발 접속값을 반영하고, 추적 문서에는 secret placeholder만 유지.
  - **검증**: 관련 ETL/스케줄러 테스트 30건, backend pytest 137건, `compileall`, `docker compose --env-file .env config --quiet`, RustFS `krtour-map/features/healthcheck/t014-smoke.txt` smoke, Playwright E2E 4건 통과.
- **다음 작업**:
  - PR #30 리뷰 종합 문서의 P0 후속 항목을 task로 승격해 순차 처리한다.

---

## 2026-06-08: T-031 작업 상태 상세 로그·실행 큐 표시 보강

- **담당자**: Codex
- **작업 내용**:
  - **작업 상태 저장 확장**: `crawl_runs`에 `current_message`, `status_log_json`을 추가하고 기존 SQLite DB에는 `init_db`에서 누락 컬럼을 보강하도록 구성.
  - **상세 로그 누적**: scheduler와 harvest 파이프라인이 Gemini 검색어 보정, YouTube 검색, 동영상 상세 조회, DB 적재, 완료·실패·stale 재시도 흐름을 한국어 메시지로 남기도록 연결.
  - **후속 ETL 로그 계약**: 자막/Gemini POI 요약 서비스도 자막 추출, RustFS 저장, Gemini 설명 보정, 장소 후보 생성 과정을 reporter 콜백으로 기록할 수 있게 확장.
  - **웹 표시 보강**: 수집 패널의 작업 상태 영역에 현재 메시지와 상세 로그 타임라인을 추가하고, 운영 패널에는 `running`/`pending`을 별도 조회하는 실행 큐 목록과 진행률을 표시.
  - **API/MCP 응답 보강**: `/api/harvest/{job_id}`, `/api/runs`, MCP `get_harvest_status`가 현재 메시지와 상세 로그를 함께 반환하도록 갱신.
  - **검증**: backend pytest 137건, frontend `npm run lint`, `npm run type-check`, `npm run build`, Playwright E2E 4건 통과.
- **다음 작업**:
  - PR #30 리뷰 종합 문서의 P0 후속 항목을 task로 승격해 순차 처리한다.

---

## 2026-06-07: T-030 Windows FFmpeg 자동 준비 및 VWorld 지도 축소 안정화

- **담당자**: Codex
- **작업 내용**:
  - **FFmpeg 자동 준비**: `scripts\ensure-windows-ffmpeg.ps1`을 추가해 Windows live 시작 전 프로젝트 로컬 `.local\ffmpeg`에 지정된 gyan.dev Windows 빌드가 없으면 내려받고 압축을 풀도록 구성.
  - **환경변수 주입**: `.env`의 `FFMPEG_PATH`, `FFPROBE_PATH`를 갱신하고, `scripts\start-windows-live.ps1`이 API 프로세스 시작 전에 `ffmpeg -version`, `ffprobe -version`을 확인한 뒤 같은 경로를 프로세스 환경변수로 넘기도록 보강.
  - **Docker 경로 분리**: Docker Compose에서는 Windows 호스트 경로가 컨테이너에 들어가지 않도록 `DOCKER_FFMPEG_PATH`, `DOCKER_FFPROBE_PATH`를 컨테이너 내부 `FFMPEG_PATH`, `FFPROBE_PATH`로 주입.
  - **지도 축소 오류 보정**: VWorld WMTS source에 대한민국 tile bounds와 최소 zoom을 지정하고 MapLibre 지도에도 `minZoom`, `maxBounds`를 설정해 대한민국 범위를 벗어난 tile 요청을 막음.
  - **Windows E2E 기동 보강**: Playwright webServer와 E2E frontend 시작 스크립트가 `node`/`npm` PATH에 의존하지 않고 현재 Node 실행 파일과 Next.js CLI를 직접 사용하도록 정리.
- **다음 작업**:
  - Windows live 서버 재기동 후 Playwright로 지도 축소와 console error 재현 여부를 확인한다.

---

## 2026-06-07: T-029 Windows live test 후속 보완

- **담당자**: Codex
- **작업 내용**:
  - **Web 기동 안정화**: Windows PowerShell 세션에서 `npm.cmd` 또는 `.cmd` 내부 `node` PATH 해석이 실패하는 환경을 확인하고, `scripts/start-windows-live.ps1`이 Windows Node.js 설치 경로를 직접 찾아 Next.js CLI를 `node.exe`로 실행하도록 보강.
  - **Gemini 설정 보정**: live `.env`의 `gemini-flash-latest` 값을 설정 화면에서 그대로 표시·저장할 수 있도록 Gemini 엔진 선택지에 추가.
  - **Input hydration 경고 제거**: SSR/클라이언트 style 속성이 달라지는 경고를 확인하고, 공용 `Input`을 native `input` 기반으로 단순화한 뒤 브라우저 주입 속성 차이를 hydration 경고에서 제외.
  - **live test 정리**: API `9041`, Web `9042`, RustFS `9003/9004`, Gemini/YouTube/VWorld/Kakao 키 smoke, Playwright 화면 검증을 clean worktree와 Windows 프로세스 기준으로 재확인.
- **다음 작업**:
  - 현재 등록된 대기 작업 없음.

---

## 2026-06-07: T-028 장소 언급 소스·중복 정렬·내보내기 구현

- **담당자**: Codex
- **작업 내용**:
  - **언급 소스 집계**: `video_place_mappings`와 `youtube_videos`를 묶어 확정 장소별 `mention_count`, `source_channel_count`, `source_videos`를 계산하고 `/api/destinations` 응답에 포함.
  - **반복 등장 보존**: 같은 영상에서 같은 장소가 여러 구간에 반복 등장해도 각각의 매핑을 저장할 수 있도록 `video_place_mappings`의 영상-장소 unique 제약을 제거.
  - **웹 UX 보강**: 장소 목록에 언급 횟수, 대표 영상·유튜버, 정렬 Select, export 선택 체크박스, `xlsx`/`gpx`/`kml` 형식 선택, 선택/전체 내보내기 버튼을 추가.
  - **내보내기 API**: `/api/destinations/export`를 추가해 선택 ID 또는 전체 장소를 같은 집계 기준으로 파일화. `xlsx`는 장소-언급 행 단위로, `gpx`/`kml`은 장소 좌표와 소스 설명을 포함.
  - **MCP 상세 보강**: `get_place_detail` 결과에 `mention_count`와 `source_channel_count`를 추가해 에이전트도 웹과 같은 집계 기준을 사용.
  - **카테고리 정책 정리**: Kakao Local 공식 카테고리를 우선 근거로 사용하고, Gemini 후보 카테고리와 VWorld/Naver 주소 맥락을 보조 근거로 삼으며 불확실하면 검수 큐로 남기는 방식으로 문서화.
  - **검증**: backend pytest 130건, frontend `npm run lint`, `npm run type-check`, `npm run build`, Playwright E2E 4건 통과.
- **다음 작업**:
  - Windows Playwright 전체 E2E에서 export 버튼 클릭과 다운로드 응답까지 추가 검증할 수 있다.

---

## 2026-06-07: T-027 Windows live 포트 고정

- **담당자**: Codex
- **작업 내용**:
  - **고정 포트 반영**: Windows live API 포트를 `9041`, Web 포트를 `9042`로 정하고 `.env.example`, backend 설정 fallback, frontend API fallback, Docker Compose host port 기본값을 갱신.
  - **실행 스크립트 추가**: `scripts/start-windows-live.ps1`을 추가해 `9041`/`9042` 점유 리스너를 먼저 종료하고 RustFS/API/Web을 고정 포트로 띄우도록 구성.
  - **문서 갱신**: README, 개발 환경 문서, 아키텍처, ADR-18, 에이전트 컨텍스트 문서에 Windows live 포트와 포트 점유 시 처리 방법을 반영.
- **다음 작업**:
  - Windows 호스트에서 서버를 띄우고 live test를 진행한다.

---

## 2026-06-05: T-026 Next.js route type 생성물 안정화

- **담당자**: Codex
- **작업 내용**:
  - **생성물 흔들림 제거**: `next typegen`, `next build`, `next dev` 실행 순서에 따라 `frontend/next-env.d.ts`의 route type import가 `.next/dev/types`와 `.next/types` 사이에서 바뀌는 문제를 확인.
  - **정규화 hook 추가**: `frontend/scripts/normalize-next-env.mjs`를 추가하고 `posttype-check`/`postbuild`에서 실행해 route import를 `.next/dev/types/routes.d.ts`로 되돌리도록 구성.
  - **타입 포함 경로 유지**: 실제 route type은 `tsconfig.json`의 `.next/types/**/*.ts`, `.next/dev/types/**/*.ts` include를 유지해 사용한다.
- **다음 작업**:
  - 후속 PR 머지 후 전체 live test를 재실행한다.

---

## 2026-06-05: T-025 PR #6~19 프론트엔드·E2E·문서 리뷰 반영

- **담당자**: Codex
- **작업 내용**:
  - **프론트엔드 class 호환성 보정**: shadcn/ui primitive에 남아 있던 Tailwind v4 계열 selector를 Tailwind v3에서 해석 가능한 class로 정리.
  - **설정·검수 폼 정리**: 설정 페이지와 매칭 실패 검수 큐를 React Hook Form/Zod 기반 검증과 TanStack Query mutation 흐름으로 맞추고, API 오류 메시지는 HTTP status와 길이 제한을 포함하도록 보강.
  - **지도 fallback 개선**: VWorld 키가 없는 E2E/로컬 환경에서도 fallback overlay와 접근성 region이 보이도록 하고, marker 재생성과 선택 장소 이동 효과를 분리.
  - **E2E 안정화**: Python 3.10 호환 `timezone.utc`를 사용하고, 테스트 frontend는 VWorld 키를 비워 외부 타일 호출을 차단. shadcn Select는 실제 클릭/option 선택 흐름으로 검증하고, 관련 console error만 실패로 판단하도록 필터링.
  - **ADR-20 보강**: sqlite-vec/PostGIS/PgQueuer 전환 기준을 관측 가능한 수치 트리거로 구체화하고, ADR-12/ADR-17 후속 갱신 필요성을 명시.
- **다음 작업**:
  - PR 생성, 머지 후 전체 live test를 진행한다.

---

## 2026-06-05: T-024 PR #6~19 ETL·동영상·지오코딩 리뷰 반영

- **담당자**: Codex
- **작업 내용**:
  - **YouTube API 보안·쿼터 보강**: API 키를 URL query string에서 제거하고 `X-goog-api-key` 헤더로 전달. HTTP 오류 메시지에서 키를 마스킹하고, 429/5xx/네트워크 재시도, per-run quota budget, `videos.list` 50개 chunking을 적용.
  - **증분 채널 수집**: 채널 harvest에서 `get_channel_watermark`를 실제로 사용해 uploads playlist 항목이 기존 최신 업로드 시각 이하로 내려가면 pagination을 중단.
  - **Gemini·RustFS 비동기 격리**: RustFS `put_object`와 Gemini POI 추출 호출을 executor로 격리. POI 추출 실패 시 영상 상태를 `failed`로 남기고, 같은 bucket/object_key의 `media_assets`는 재사용.
  - **Gemini REST 호출 연결**: `make_gemini_llm`을 추가해 Gemini REST `generateContent` 호출에 JSON response schema를 전달. 기존 주입형 `llm` 테스트 구조는 유지.
  - **프레임 추출 보강**: FFmpeg timeout을 `FrameExtractionError`로 래핑하고, 오디오 전용 스트림은 프레임 추출 후보에서 제외. 대용량 원본 저장 helper의 메모리 한계를 docstring에 명시.
  - **지오코딩 보강**: VWorld 비-NoData 오류와 역지오코딩 오류는 fallback 가능하도록 흡수. road/parcel 동일 좌표 후보를 병합하고, 자동 지오코딩 확정 시 영상-장소 매핑과 geom 동기화를 수행. 근접 기존 장소 이름이 맞지 않으면 자동 재사용 대신 검수 대기로 남김.
  - **검증**: ETL 타깃 테스트 67건, backend 전체 `pytest` 128건 통과.
- **다음 작업**:
  - PR #6~19 리뷰 중 프론트엔드·E2E·전환 기준 문서 묶음을 반영한다.

---

## 2026-06-05: T-023 PR #6~19 백엔드 코어·MCP·스케줄러 리뷰 반영

- **담당자**: Codex
- **작업 내용**:
  - **Python 3.10 호환 모델 정리**: `StrEnum` 의존을 제거하고 `str, Enum` 기반 enum으로 변경. 모델에는 중복 방지 제약, `BigInteger` 파일 크기, non-null 설명 검수 상태를 반영.
  - **설정 API 보호**: `/api/settings`와 `settings_service`를 whitelist 기반으로 제한하고, 여러 설정 저장은 검증 후 단일 트랜잭션으로 처리. 알 수 없는 키와 API 키 평문 저장 시도를 400으로 거절.
  - **SQLite 연결 보강**: 연결 시 `PRAGMA foreign_keys=ON`, `PRAGMA busy_timeout=5000`을 적용하고 SpatiaLite 미설치 경로에는 debug 로그를 남기도록 변경.
  - **MCP 정합성 보강**: 장소 병합 시 `media_assets.place_id`를 target 장소로 이전. MCP 쓰기는 도메인 변경과 감사 로그를 같은 commit으로 묶고, 같은 `idempotency_key`로 다른 파라미터가 들어오면 명시 오류를 반환.
  - **scheduler race 제거**: 배포 직후 즉시 실행을 수동 `run_once` 호출이 아니라 APScheduler `next_run_time`으로 처리해 `max_instances=1` 보호 안에 넣음.
  - **검증**: backend 전체 `pytest` 114건 통과.
- **다음 작업**:
  - PR #6~19 리뷰 중 ETL·동영상·지오코딩 묶음을 반영한다.

---

## 2026-06-05: T-022 PR #1~5 리뷰 정합성 반영

- **담당자**: Codex
- **작업 내용**:
  - **MCP 안전 기본값**: `.env.example`과 `Settings.MCP_WRITE_ENABLED` 기본값을 `false`로 조정. 쓰기 검증·운영 허용 시에만 `.env`에서 `true`로 명시하도록 README와 개발 환경 문서를 갱신.
  - **RustFS 보존 설명 보강**: `subtitle`/`transcript` 자산이 `tripmate-subtitles` 버킷을 공유한다는 점과 `MEDIA_RETENTION_POLICY`가 `media_assets.retention_policy`의 전역 기본값이라는 점을 명시.
  - **ADR 정합성 보정**: ADR-9의 YouTube 수집 원칙을 ADR-11의 공식 YouTube Data API 우선 정책과 맞추고, `yt-dlp`는 자막·대표 프레임 구간에만 격리한다고 정리.
  - **문서·빌드 위생**: README 환경 변수 예시를 `dotenv` 블록으로 바꾸고, MIT `LICENSE` 파일을 추가. frontend Dockerfile은 lockfile 기준 재현 설치를 위해 `npm ci`를 사용하도록 변경.
- **다음 작업**:
  - PR #6~19 리뷰 중 백엔드 코어·MCP·스케줄러 묶음을 반영한다.

---

## 2026-06-05: T-020 Next.js 메이저 업그레이드 및 npm audit 대응

- **담당자**: Codex
- **작업 내용**:
  - **Next/React 업그레이드**: frontend를 Next.js `16.2.7`, React / React DOM `19.2.7`, `eslint-config-next` `16.2.7`, ESLint `9.39.4`로 업그레이드.
  - **audit 해소**: Next 14 계열 취약점과 Next 내부 `postcss@8.4.31` transitive 항목을 해소. root `postcss@8.5.15`를 npm `overrides`로 적용해 `npm audit` 0건 확인.
  - **lint/type-check 전환**: `next lint` 제거에 맞춰 `.eslintrc.json`을 삭제하고 `eslint.config.mjs` flat config를 추가. `npm run type-check`는 clean checkout에서도 route type을 생성하도록 `next typegen && tsc --noEmit`으로 변경.
  - **Turbopack CSS 호환성 보정**: Next 16 build의 package CSS import 해석에 맞춰 `tw-animate-css` / `shadcn/tailwind.css` import를 제거하고 Tailwind v3 호환 `tailwindcss-animate` plugin으로 select animation utility를 제공. Tailwind v4식 arbitrary class는 v3식으로 정리.
  - **React 19 lint 보정**: React Compiler lint가 경고한 React Hook Form `form.watch()` 사용을 `useWatch`로 교체.
  - **ADR 추가**: `docs/decisions.md`에 ADR-21을 추가하고, 개발 환경 문서와 현재 컨텍스트를 Next 16 기준으로 갱신.
  - **검증**: `npm audit` 0건, frontend `npm run lint`, clean `.next` 기준 `npm run type-check`, `npm run build`, Playwright E2E 4건 통과.
- **다음 작업**:
  - 현재 등록된 대기 작업 없음.

---

## 2026-06-05: T-016 고도화 후보 검토

- **담당자**: Codex
- **작업 내용**:
  - **의미론적 검색 검토**: sqlite-vec와 SQLite Vec1의 virtual table 기반 vector search를 검토. 현재 검색 품질 병목이 확인되지 않았고 extension 안정성·Windows/Docker 검증 비용이 남아 있어 기본 의존성 도입은 보류.
  - **PostgreSQL/PostGIS 전환 기준 수립**: 확정 장소 100,000건, 영상-장소 매핑 1,000,000건, 반경 검색 p95 500ms 초과, 최근 7일 `database is locked` 재시도 10회 이상을 전환 검토 트리거로 문서화. 전환 시 변경 범위는 `app.core.spatial`과 `app.services.place_service` 중심으로 제한.
  - **멀티 워커 후보 정리**: 현재는 APScheduler 단일 실행자를 유지. PostgreSQL 전환 이후 pending 대기 작업 최고 연령 5분 초과가 3회 연속 관측되거나 단일 worker가 24시간 내 신규 영상 처리량을 소화하지 못하면 PgQueuer를 1순위로 검토. APScheduler + PostgreSQL advisory lock은 여러 scheduler 프로세스 중 단일 leader 보장이 필요할 때만 보조 후보로 둠.
  - **ADR 추가**: `docs/decisions.md`에 ADR-20을 추가하고, `docs/architecture.md`의 대규모 전환 후보 표를 수치 트리거 중심으로 갱신.
  - **wrapper 최소화 유지**: 의미론적 검색이나 queue 전환도 실제 병목 전까지 optional feature 또는 별도 ADR로만 다루며, 선제 adapter/wrapper 계층은 추가하지 않는 원칙을 명시.
- **다음 작업**:
  - T-020: Next.js 메이저 업그레이드 및 npm audit 대응 검토.

---

## 2026-06-05: T-015 Playwright E2E 검증

- **담당자**: Codex
- **작업 내용**:
  - **자동 E2E 서버 기동**: `tests/playwright.config.ts`가 backend `127.0.0.1:18080`과 frontend `127.0.0.1:13100`을 `webServer`로 자동 실행하도록 구성. Windows Node.js에서 `npm.cmd` 직접 spawn이 실패하는 경우를 피하기 위해 frontend 기동은 `cmd.exe` 경유로 처리.
  - **결정론적 시드 데이터**: `tests/scripts/seed_e2e.py`가 테스트 전용 SQLite DB를 초기화하고 확정 장소, 매칭 실패 후보, MCP 감사 로그, 대표 프레임 `media_assets`를 매 테스트마다 재생성.
  - **브라우저 시나리오 검증**: 메인 화면의 VWorld 지도 fallback과 장소/검수/운영 패널, 수집 시작 `job_id`와 `pending` 상태 표시, Deep Research 작업 생성, 매칭 실패 후보의 사용자 보정 저장 후 장소 목록 반영, 설정 페이지 Gemini 엔진 저장을 검증.
  - **프론트 보강**: React Hook Form이 사용하는 ref가 실제 input까지 전달되도록 공용 `Input`을 수정하고, 장소 목록/검수 큐/운영 패널에 접근성 이름을 추가해 UI와 테스트의 탐색 기준을 일치시킴.
  - **로컬 실행 안정화**: E2E용 CORS 허용 origin(`13100`)을 설정에 추가하고, `tests/.tmp`, `tests/test-results`, `tests/playwright-report` 등 산출물을 ignore 처리.
  - **wrapper 최소화 유지**: 새 제품 계층이나 adapter는 추가하지 않고, Playwright 검증은 기존 REST API와 화면 접근성 이름을 직접 사용하도록 구성.
  - **테스트**: Browser plugin은 현재 세션에 없어 일반 Playwright로 검증. `npm test` 4건, frontend `npm run lint`, `npm run type-check`, `npm run build`, backend `compileall`, backend pytest, `docker compose --env-file .env config --quiet` 통과.
- **다음 작업**:
  - T-016: sqlite-vec/PostGIS 전환/멀티 워커 후보 검토 또는 T-020: Next.js 메이저 업그레이드 및 npm audit 대응 검토.

---

## 2026-06-05: T-021 VWorld 우선 지오코딩 및 Kakao 키워드 장소 검색 보강

- **담당자**: Codex
- **작업 내용**:
  - **VWorld 직접 사용**: `python-vworld-api`의 `AsyncVworldClient`를 직접 받도록 `geocode_service`를 바꾸고, 기존 `VWorldGeocoder`/`VWorldReverseGeocoder` 내부 wrapper class를 제거. 내부에는 응답 dict를 `GeocodeCandidate`와 주소 dict로 바꾸는 최소 변환 함수만 유지.
  - **로컬 패키지 활용**: `backend/requirements.txt`에 `python-vworld-api` GitHub archive commit pin을 추가하고, 검증 환경에는 `F:\dev\python-vworld-api`를 editable 설치해 사용.
  - **Kakao 공식 기능 반영**: Kakao Local 주소 검색 결과가 없을 때 공식 `GET /v2/local/search/keyword.json` 키워드 장소 검색 fallback을 호출하도록 보강. POI명, 도로명 주소, 지번 주소, 카테고리를 후보에 저장.
  - **우선순위 정리**: 지오코딩·역지오코딩 정책을 VWorld → Kakao → Naver로 갱신하고, `GEOLOCATION_PROVIDER` 기본값과 `.env.example`을 `vworld`로 정리.
  - **문서 보강**: README, `docs/architecture.md`, `docs/dev-environment.md`, `docs/decisions.md` ADR-19, `AGENTS.md`, `SKILL.md`, `CLAUDE.md`에 wrapper 최소화와 VWorld 우선 원칙을 반영.
  - **테스트**: Kakao 키워드 장소 검색 fallback, VWorld `AsyncVworldClient` 직접 geocode/reverse 변환, 기존 DB 적용 경로를 포함한 지오코딩 테스트 15건 통과. backend 전체 pytest, `compileall`, `docker compose config --quiet`, Python Compose image build, API 컨테이너 `AsyncVworldClient` import, RustFS smoke, `npm run lint`, `npm run type-check`, `npm run build` 통과.
- **다음 작업**:
  - T-015: Playwright E2E 검증. 수집 시작, 상태 폴링, 지도/검수/운영 패널, MCP 쓰기 반영 경로를 브라우저에서 확인한다.

---

## 2026-06-05: T-014 Windows 및 Docker Compose 통합 검증

- **담당자**: Codex
- **작업 내용**:
  - **Compose 실행 계약 보강**: `.env`가 없어도 `docker compose config --quiet`가 통과하도록 optional `env_file`을 적용하고, 기본 포트가 이미 사용 중인 환경을 위해 `RUSTFS_HOST_PORT`, `RUSTFS_CONSOLE_HOST_PORT`, `API_HOST_PORT`, `MCP_HOST_PORT`, `FRONTEND_HOST_PORT` override를 추가.
  - **RustFS 네트워크 분리**: Windows 호스트 URL은 `localhost:9003/9004`, 컨테이너 내부 endpoint는 `http://rustfs:9000`으로 분리. RustFS 기본 버킷 환경 변수와 무기한 보존 정책을 Compose 공통 환경에 포함.
  - **MCP Compose 실행**: 로컬 기본값은 `stdio`로 유지하고, Docker Compose에서는 `streamable-http` transport를 `0.0.0.0:8010/mcp`로 실행하도록 설정.
  - **시작 순서 보정**: API healthcheck를 추가하고 MCP/scheduler/frontend는 API healthy 이후 시작하도록 구성해 SQLite DDL race를 방지.
  - **DB 초기화 수정**: `aiosqlite` connect event에서 SpatiaLite extension loading을 `run_async` 경유로 수행하게 수정하고, 공간 컬럼 존재 검사에서 `scalar()`를 두 번 소비하던 버그를 수정.
  - **검증 자동화**: `scripts/verify-docker-compose.ps1`과 `scripts/verify_rustfs.py`를 추가. health, MCP port listening, RustFS 버킷 생성, smoke 객체 업로드·조회를 수행.
  - **빌드 최적화**: 루트와 프론트엔드 `.dockerignore`를 추가해 Docker build context를 root 6.47KB, frontend 1.34KB 수준으로 축소.
  - **실행 검증**: 기존 로컬 서비스가 기본 포트를 사용 중이라 `19003/19004`, `18000`, `18010`, `13000`으로 override하여 `rustfs`, `api`, `mcp`, `scheduler`, `frontend` 전체 실행 확인. RustFS/API/frontend HTTP 200, MCP port listening, RustFS 3개 버킷 smoke 객체 업로드·조회, SQLite DB 파일 생성 확인.
  - **제한 사항**: Windows PowerShell에서 Docker CLI가 PATH에 없어 PowerShell 래퍼는 preflight 실패 메시지까지만 확인. 같은 Docker engine에 대해 WSL Docker CLI로 Compose smoke를 완료.
  - **테스트**: backend pytest 105건, `npm run lint`, `npm run type-check`, `npm run build`, `docker compose config --quiet`, Docker Compose build/up/RustFS smoke 통과.
- **다음 작업**:
  - T-015: Playwright E2E 검증. 수집 시작, 상태 폴링, 지도/검수/운영 패널, MCP 쓰기 반영 경로를 브라우저에서 확인한다.

---

## 2026-06-05: T-013 지도·리스트·운영 패널 구현

- **담당자**: Codex
- **작업 내용**:
  - **REST 운영 표면 추가**: `/api/runs`, `/api/audit-logs`, `/api/storage/rustfs`, `/api/destinations/{place_id}/correct`, `/api/destinations/{place_id}/deep-research`, `/api/destinations/unmatched/{candidate_id}/resolve` 추가.
  - **RustFS 패널 데이터**: `media_assets`의 asset type별 객체 수·크기 합계와 RustFS `/health/live` 연결 상태를 반환.
  - **지도 구현**: 공개 npm 패키지 `maplibre-vworld`/`maplibre-vworld-js`가 없어, `maplibre-gl`에 VWorld WMTS raster tile URL을 직접 구성. VWorld 키가 없으면 fallback background로 렌더링.
  - **장소 리스트/지도 동기화**: 장소 목록 선택 시 지도 중심 이동, marker 클릭 시 선택 장소 변경, Deep Research 작업 생성 버튼 연결.
  - **검수 큐**: `needs_review` 후보 목록, 신규 장소 생성 폼, 제외 처리 버튼을 구현하고 처리 후 장소/후보/감사 로그 query를 갱신.
  - **운영 패널**: 최근 작업, 실패 작업 수, RustFS 객체 수/헬스 상태, 최근 MCP·웹 쓰기 감사 로그를 표시.
  - **테스트**: API endpoint 테스트를 보강. backend pytest 105건, `npm run lint`, `npm run type-check`, `npm run build` 통과. dev server 3001 포트에서 첫 화면 응답과 `장소`/`검수 큐`/`운영` 렌더링 확인.
- **다음 작업**:
  - T-014: Windows 및 Docker Compose 통합 검증. API, MCP, scheduler, frontend, RustFS를 단일 호스트 구성으로 검증한다.

---

## 2026-06-05: T-012 Next.js 프론트엔드 스택 정비

- **담당자**: Codex
- **작업 내용**:
  - **shadcn/ui 초기화**: `components.json`, `cn` 유틸, `Button`, `Input`, `Select`, `Field`, `Badge` 컴포넌트를 추가하고 Tailwind semantic color/radius token을 구성.
  - **폼/검증**: React Hook Form + Zod로 수집 시작 폼을 구현. 검색어, 채널 ID, 재생목록 ID 중 하나를 선택하고 `max_videos` 범위를 검증.
  - **상태 관리**: TanStack Query `QueryProvider`를 루트에 연결하고, `POST /api/harvest` mutation과 `GET /api/harvest/{job_id}` polling을 `HarvestConsole`에 구현.
  - **API client**: `frontend/src/lib/api.ts`에 수집 시작, 상태 조회, 여행지 목록 조회 함수를 추가하고 백엔드 snake_case payload를 캡슐화.
  - **의존성 보정**: npm에 공개되지 않은 `maplibre-vworld` 의존성을 제거하고 `maplibre-gl`은 유지. T-013에서 VWorld 타일 구성 또는 실제 공개 wrapper 확인이 필요.
  - **lint 설정**: Next 14와 호환되도록 ESLint 8 + `eslint-config-next@14.2.35` 및 `.eslintrc.json`을 추가.
  - **추가 작업 식별**: `npm audit`이 Next 14 계열 보안 이슈를 보고했으나 자동 수정은 Next 16 major upgrade를 요구하므로 T-020으로 분리.
  - **검증**: `npm run lint`, `npm run type-check`, `npm run build` 통과. dev server는 3000 포트 사용 중으로 3001 포트에서 띄워 `http://127.0.0.1:3001/` 응답과 한글 Select 라벨 렌더링을 확인.
- **다음 작업**:
  - T-013: 지도·리스트·운영 패널 구현. `maplibre-gl` 기반 VWorld 지도, 장소 리스트, 검수 큐, 작업/저장소 운영 패널을 연결한다.

---

## 2026-06-05: T-011 MCP 서버 읽기/쓰기 UX 구현

- **담당자**: Codex
- **작업 내용**:
  - **패키지 구조 정리**: 외부 MCP SDK 패키지 이름과 로컬 `mcp/` 디렉터리 이름 충돌을 피하기 위해 실제 구현을 `tripmate_mcp` 패키지로 분리. `mcp/server.py`는 기존 Docker Compose 명령을 보존하는 호환 래퍼로 유지.
  - **FastMCP 서버 등록**: `tripmate_mcp.server.build_server`가 FastMCP 인스턴스를 만들고, `MCP_WRITE_ENABLED`에 따라 읽기/쓰기 도구를 등록.
  - **읽기 도구**: `get_harvest_status`, `search_existing_places`, `get_place_detail` 구현. 작업 상태 JSON, 장소 검색 결과, 영상 매핑·대표 프레임·후보 근거를 반환.
  - **쓰기 도구**: `harvest_travel_destinations`, `correct_place`, `merge_places`, `trigger_deep_research`, `review_unmatched_place`, `resolve_place_candidate` 구현.
  - **검증/감사/멱등성**: 모든 쓰기 도구에 Pydantic 입력 스키마, 필수 `idempotency_key`, `audit_logs` 기록, 동일 멱등 키 재호출 시 기존 결과 반환 적용.
  - **도메인 서비스 보강**: `place_service`에 장소 검색, 상세 조회 보조, 수동 보정, 중복 병합, 후보 검수 메타데이터 기록, 후보 해결(기존 장소 매칭·신규 장소 생성·제외)을 추가.
  - **실행 구조**: `Dockerfile.python`이 `tripmate_mcp` 패키지를 복사하도록 갱신하고, MCP 서버는 시작 시 `init_db()` 후 설정된 transport로 실행.
  - **테스트**: MCP runtime 단위 테스트 10건 추가. 전체 백엔드 pytest 103건 통과.
- **다음 작업**:
  - T-012: Next.js 프론트엔드 스택 정비. Tailwind CSS, shadcn/ui, React Hook Form, Zod, TanStack Query를 실제 화면과 연결한다.

---

## 2026-06-05: T-019 채널·재생목록 harvest 오케스트레이션 보강

- **담당자**: Codex
- **작업 내용**:
  - **pipeline.run_harvest 확장**: 기존 keyword 수집 경로를 유지하면서 `channel_id`, `playlist_id` 입력을 추가 지원.
  - **playlist 수집**: `playlistItems.list`에서 `contentDetails.videoId` 또는 `snippet.resourceId.videoId`를 읽어 중복 없는 video_id 목록을 수집하고, pagination과 `max_videos` 상한을 적용.
  - **channel 수집**: `channels.list`로 uploads playlist ID를 찾은 뒤 playlist 수집 경로를 재사용.
  - **공통 적재 경로**: keyword/channel/playlist 모두 `videos.list` 상세 조회, ranking, `ingest_service.ingest_candidates` 멱등 적재 경로를 공유.
  - **scheduler handler**: 기본 `harvest` handler가 keyword/channel/playlist target을 모두 `run_harvest`로 전달하도록 보강.
  - **결과 요약**: `target_type`, `target_id`, `channel_id`, `playlist_id`, `uploads_playlist_id`, `quota_used`를 `crawl_runs.result_json`에 남길 수 있도록 summary를 확장.
  - **테스트**: playlist 직접 수집, channel uploads playlist 수집, scheduler handler channel/playlist 전달을 추가. 전체 백엔드 pytest 93건 통과.
- **다음 작업**:
  - T-011: MCP 서버 읽기/쓰기 UX 구현. REST와 같은 `crawl_runs`, 장소 조회, 보정/병합/검수 도메인 서비스를 재사용한다.

---

## 2026-06-05: T-010 APScheduler 단일 실행자 구현

- **담당자**: Codex
- **작업 내용**:
  - **scheduler.worker**: `run_once`를 테스트 가능한 1회 tick으로 구현. stale running 작업을 먼저 재투입/격리한 뒤 FIFO pending 작업을 claim하고 handler 실행.
  - **상태 전이**: `execute_run`이 heartbeat/progress 갱신, handler 결과 `done` 처리, handler 예외와 unknown job_type의 `failed` 격리를 담당.
  - **APScheduler 실행 루프**: `worker_loop`가 APScheduler interval job으로 `run_once`를 반복 실행하며 `max_instances=1`, `coalesce=True`로 단일 실행자 계약을 유지.
  - **기본 harvest handler**: keyword target은 기존 `pipeline.run_harvest`에 연결. channel/playlist target은 현재 오케스트레이션이 없으므로 명시적으로 실패시켜 조용한 오동작을 막음.
  - **설정**: `SCHEDULER_POLL_INTERVAL_SECONDS`, `SCHEDULER_HEARTBEAT_INTERVAL_SECONDS`, `SCHEDULER_STALE_THRESHOLD_SECONDS`, `SCHEDULER_MAX_RETRIES`를 `.env.example`과 `Settings`에 추가.
  - **추가 작업 식별**: API는 channel/playlist target을 받을 수 있으나 수집 오케스트레이션이 keyword 중심이므로 T-019를 새로 추가.
  - **테스트**: claim→done, empty tick, handler 실패, unknown job, stale 재투입, max retry 격리, channel target 명시 실패, payload JSON 오류까지 검증. 전체 백엔드 pytest 90건 통과.
- **다음 작업**:
  - T-019: channel/playlist harvest 오케스트레이션을 `YouTubeClient.channels_list`/`playlistItems.list`와 기존 ingest 경로로 보강.

---

## 2026-06-05: T-009 대표 프레임 추출 구현

- **담당자**: Codex
- **작업 내용**:
  - **frame_extraction**: POI 시작 타임스탬프(`HH:MM:SS`, `MM:SS`, 초)를 파싱하고 5~10초 오프셋을 더해 대표 프레임 추출 시각을 계산.
  - **yt-dlp 연동**: `resolve_stream_url_ytdlp`를 지연 import 방식으로 구현하고, `select_stream_url`이 직접 URL 또는 최고 해상도 video format URL을 선택하도록 구현.
  - **FFmpeg Input Seeking**: `extract_jpeg_with_ffmpeg`에서 `-ss`를 `-i` 앞에 둔 명령으로 JPEG를 stdout 추출. 테스트에서는 runner 주입으로 실제 FFmpeg 바이너리 없이 명령 계약 검증.
  - **RustFS 저장**: 추출한 JPEG를 `AssetType.FRAME`으로 `tripmate-frames` 버킷에 저장하고 `media_assets`에 URI·체크섬·크기·무기한 보존 정책 기록. `mapping_id`가 주어지면 `video_place_mappings.frame_asset_id`에 연결.
  - **원본 미디어 보존 helper**: 이미 확보한 원본 동영상 또는 오디오 bytes를 `AssetType.RAW_VIDEO`로 `tripmate-raw-videos` 버킷에 저장하는 `store_raw_media` 추가.
  - **테스트**: 타임스탬프 파싱, object key sanitize, stream URL 선택, FFmpeg 명령 순서, 실패 처리, frame asset 저장·mapping 연결, raw media 저장까지 검증. 전체 백엔드 pytest 82건 통과.
- **다음 작업**:
  - T-010: APScheduler 단일 실행자가 `crawl_runs.pending` 작업을 claim하고 T-006~T-009 파이프라인을 실행하도록 연결.

---

## 2026-06-05: T-008 지오코딩·역지오코딩 구현

- **담당자**: Claude
- **작업 내용**:
  - **geocoding**: Kakao Local(1차)·Naver(보조 검증)·VWorld(역지오코딩) 초기 호출 계층을 `httpx.AsyncClient` 주입형으로 구현(ADR-8, `kraddr-geo` 미연계). 이후 T-021에서 VWorld 우선 및 `python-vworld-api` 직접 client 사용으로 보강. `normalize_to_wgs84`로 `pyproj always_xy=True` 좌표 정규화(미설치/4326은 graceful identity).
  - **복원력**: `request_with_backoff`로 429 지수 백오프 + 지터 재시도, `asyncio.Semaphore` 동시성 상한.
  - **평가**: `evaluate_geocode`가 단일 결과는 확정, 후보 과다 시 Naver 최상위 좌표 근접도로 디스앰비규에이션, 실패·모호·낮은 신뢰도는 `needs_review`로 판정(자동 확정 금지, ADR-16).
  - **geocode_service**: 매칭 시 좌표 근접 중복(T-005 저장소 계층)을 재사용하거나 새 `travel_places`를 만들고, VWorld 역지오코딩으로 도로명·지번 주소 보강. 미매칭은 후보를 `needs_review`로 유지하고 사유 기록.
  - 루트 `etl/geocode.py`에 정규 구현 위치 명시.
  - **테스트**: 어댑터 파싱, 백오프 재시도/포기, 좌표 정규화, 평가 분기(no_result/single/ambiguous/disambiguated), 적용 영속화(매칭 생성·중복 재사용·needs_review 유지·VWorld 보강)까지 pytest 72건 통과.
- **다음 작업**:
  - T-009: `yt-dlp` 스트림 URL + FFmpeg Input Seeking 대표 프레임 추출, RustFS `tripmate-frames` 저장.

---

## 2026-06-05: T-007 자막·전사·Gemini POI 추출 구현

- **담당자**: Claude
- **작업 내용**:
  - **transcript**: `youtube-transcript-api → yt-dlp → faster-whisper` provider 체인. 각 provider는 사용 시점에만 지연 import해 라이브러리 없는 환경에서도 import·테스트 가능. 블로킹 호출은 `asyncio.to_thread`로 격리(`get_transcript_async`).
  - **poi_extraction**: Gemini JSON Schema(`RESPONSE_JSON_SCHEMA`) 기반 POI 추출. 실제 Gemini 호출은 주입형 `llm` 콜러블로 분리. JSON 파싱/Pydantic 검증 실패 시 `max_retries`까지 재시도, 모두 실패하면 `POIExtractionError`.
  - **media_store**: `MediaStore` 프로토콜로 저장 백엔드 추상화(`InMemoryMediaStore`/`RustFSMediaStore`). `store_and_record`가 RustFS 업로드 후 `media_assets`에 버킷·객체 키·URI·sha256·크기·무기한 보존 정책 기록. asset_type별 버킷 라우팅.
  - **summarize_service**: 자막 RustFS 저장 → Gemini POI 추출 → 영상 설명 보정본 저장(원문 `description_raw` 보존, ADR-16) → 추출 장소를 `needs_review` 후보로 생성(자동 확정 금지). 자막 없으면 `failed` 처리.
  - 루트 `etl/summarize.py`에 정규 구현 위치 명시.
  - **테스트**: provider 체인 폴백, POI 파싱·재시도·스키마 검증, media_store 저장·라우팅, summarize 전체 흐름까지 pytest 60건 통과.
- **다음 작업**:
  - T-008: Kakao/Naver/VWorld 지오코딩·역지오코딩, 좌표 정규화, 429 백오프, needs_review 처리.

---

## 2026-06-05: T-006 공식 YouTube Data API v3 수집 파이프라인 구현

- **담당자**: Claude
- **작업 내용**:
  - scheduler가 import해 실행할 수 있도록 비동기 수집 파이프라인을 `backend/app/etl/` 패키지로 구현.
  - **youtube_client**: 공식 `search.list`/`playlistItems.list`/`channels.list`/`videos.list`를 감싸는 `httpx.AsyncClient` 주입형 클라이언트. 엔드포인트별 쿼터 비용 누적(`search`=100 등). 비공식 검색 크롤러 미사용(ADR-11).
  - **keyword_expansion**: 시드 키워드 + 계절 맥락 → 파생 키워드 생성. 실제 Gemini 호출은 주입형 `generator` 콜러블로 분리하고 키 없이도 결정론적 폴백으로 동작(T-007에서 Gemini 연결). 중복·시드 제거.
  - **ranking**: 업로드 최신성(반감기 지수 감쇠), 키워드 유사도(Jaccard), 조회수 대비 참여도를 정규화한 합성 점수.
  - **ingest_service**: `video_id` 기준 멱등 upsert(재수집 시 통계 갱신, Gemini 보정 필드 보존), 파생 키워드 `search_keywords` 저장, 채널 워터마크(최신 업로드 시각) 조회.
  - **pipeline.run_harvest**: 파생 키워드 → 검색 → 상세 조회 → 점수 정렬 → 멱등 적재 오케스트레이션. 요약(quota_used·season·derived 포함) 반환.
  - **테스트**: ranking/keyword, ingest 멱등·워터마크, httpx `MockTransport` 기반 파이프라인 통합까지 pytest 45건 통과. 루트 `etl/search.py`에 정규 구현 위치를 명시.
- **다음 작업**:
  - T-007: 자막(youtube-transcript-api→yt-dlp→faster-whisper)·Gemini POI 추출, RustFS 저장.

---

## 2026-06-05: T-005 SpatiaLite 공간 데이터 모델 구현

- **담당자**: Claude
- **작업 내용**:
  - **도메인/공간 모델 7종 구현**: `search_keywords`, `source_targets`, `youtube_videos`, `travel_places`, `extracted_place_candidates`, `video_place_mappings`, `media_assets`.
    - `youtube_videos`: `description_raw`/`description_gemini_corrected` 분리(원문 보존).
    - `travel_places`: `description`/`gemini_enriched_description`/`description_review_status` 분리.
    - `extracted_place_candidates`: `match_status`(기본 `needs_review`) + 검수자·검수 시각·검수 메모.
    - `media_assets`: RustFS 버킷·객체 키·URI·체크섬·크기·무기한 보존 정책.
  - **공간 컬럼 관리(ADR-17)**: `app/core/spatial.py`가 `travel_places.geom` Point(4326)와 R-Tree 공간 인덱스를 ORM 밖 SpatiaLite DDL로 멱등 관리. `mod_spatialite` 미로드 환경에서는 graceful skip. `init_db`에 연결.
  - **저장소 계층 캡슐화**: `place_service`에 근접 검색(`find_places_within_radius`)·중복 후보(`find_duplicate_candidates`)를 경위도 bounding box + Haversine으로 구현. 공간 함수 호출을 한곳에 모아 PostGIS 전환 시 `ST_DWithin` 대체가 쉽도록 함.
  - **API 연동**: `/api/destinations`(확정 장소)·`/api/destinations/unmatched`(needs_review 검수 큐)를 실제 DB 조회로 연결.
  - **의사결정**: ADR-17 추가(공간 컬럼 ORM 밖 관리·저장소 계층 캡슐화·geoalchemy2 미도입).
  - **테스트**: 모델 영속성·관계, Haversine 정확도, 근접/중복 탐색, 검수 큐, 엔드포인트까지 pytest 30건 통과.
- **다음 작업**:
  - T-006: 공식 YouTube Data API v3 수집 파이프라인(파생 키워드·검색·정규화·멱등) 구현.

---

## 2026-06-05: T-004 FastAPI 비동기 백엔드 기반 구축

- **담당자**: Claude
- **작업 내용**:
  - **공통 모델 구현**: `crawl_runs`(작업 테이블), `audit_logs`, `system_settings`를 SQLAlchemy 2.0 선언형으로 구현. `RunState`/`RunSource` enum, `TimestampMixin` 도입.
  - **도메인 서비스**:
    - `crawl_run_service`: 작업 생성, FIFO `claim_next_pending`(pending→running 전이), heartbeat·진행률 갱신, 완료/실패 처리, heartbeat 만료(stale) 작업 재투입·최대 재시도 초과 격리.
    - `audit_service`: 감사 로그 기록·조회.
    - `settings_service`: `system_settings` upsert·조회, `.env` 기본값 병합.
  - **DB 초기화**: `init_db()`(create_all + SpatiaLite 메타데이터 멱등 초기화)를 lifespan에 연결. `get_session` async 의존성 제공. `mod_spatialite` 미로드 환경에서도 동작하도록 graceful skip.
  - **API 연동**: `POST /api/harvest`가 `crawl_runs` 작업만 생성하고 `job_id` 즉시 반환(ADR-13), `GET /api/harvest/{job_id}` 상태 조회, `/api/settings` GET/POST를 서비스에 연결. 작업 생성·설정 변경 시 감사 로그 기록.
  - **테스트**: `backend/tests/`에 pytest-asyncio 기반 서비스·API 테스트 17건 추가, 전부 통과.
- **다음 작업**:
  - T-005: SpatiaLite 공간 데이터 모델(`travel_places.geom` 등)과 근접 중복 조회 저장소 계층 구현.

---

## 2026-06-05: T-003 스캐폴딩 정비 — 코드 구현 진입 준비

- **담당자**: Claude
- **작업 내용**:
  - 문서(`architecture.md`, `decisions.md`, `tasks.md`)와 실제 코드 사이의 갭을 점검하고, 코드 구현(T-004 이후)에 진입할 수 있도록 스캐폴딩을 보완.
  - **백엔드 구조화**: `backend/app/` 패키지 도입.
    - `app/core/config.py`: `.env.example`의 모든 환경 변수를 1:1로 매핑한 `pydantic-settings` 기반 `Settings` 로더. (T-003: 환경 변수 이름 동기화 완료)
    - `app/core/database.py`: SQLAlchemy 2.0 + `aiosqlite` async 엔진, SpatiaLite 확장 로드와 WAL 모드 적용 지점 정의.
    - `app/core/logging.py`: API 키 마스킹 헬퍼.
    - `app/models`, `app/services`, `app/api`: 구현 대상 명시한 패키지 스캐폴드. `main.py`를 팩토리 패턴 + 라우터 조립 구조로 리팩터링.
  - **누락 디렉토리 생성**: `mcp/`(server + 읽기/쓰기 도구 메타데이터), `scheduler/`(단일 실행자 루프), `etl/media.py`(RustFS 저장 계층) 신설.
  - **Docker Compose 초안**: `frontend`, `api`, `mcp`, `scheduler`, `rustfs` 서비스와 SQLite/RustFS 데이터 볼륨, `Dockerfile.python`(공용 Python 이미지), `frontend/Dockerfile` 작성. RustFS는 별도 서비스로 분리(S3 API 9003, 콘솔 9004).
  - **RustFS 버킷 초기화**: `scripts/init_rustfs_buckets.py`로 3개 버킷 멱등 생성 절차 정리.
  - **컴포넌트별 의존성 매니페스트**: `etl/requirements.txt`, `scheduler/requirements.txt`, `mcp/requirements.txt` 분리.
  - **프론트엔드 App Router 스캐폴드**: `src/app/layout.tsx`, `page.tsx`(`#destination-list`, `#vworld-map-container`), `settings/page.tsx`(`#gemini-engine-select` 등), `VWorldMap` 컴포넌트, Tailwind 설정 추가 — 기존 E2E 스펙의 타깃을 실재화.
  - **검증**: `config`/`database`/`mcp`/`scheduler`/`etl.media` 모듈 import·구동 확인, FastAPI 라우트 등록 확인.
- **남은 사항**:
  - Docker 이미지 빌드와 `npm ci`/Playwright 통합 검증은 T-014에서 수행.
  - 모델·서비스·라우터 실제 구현은 T-004(백엔드 기반)·T-005(공간 모델)부터 진행.
- **다음 작업**:
  - T-004: FastAPI 비동기 백엔드 기반 구축(`crawl_runs`/`audit_logs`/`system_settings` 모델, SpatiaLite 초기화).

---

## 2026-06-05: RustFS 미디어 저장 및 장소 검수 요구사항 반영

- **담당자**: Codex
- **작업 내용**:
  - 후속 요구사항에 따라 받은 원본 동영상, 자막 파일, 전사 결과, 대표 프레임을 RustFS에 저장하는 계획을 추가.
  - RustFS는 애플리케이션 컨테이너에 내장하지 않고 별도 로컬 Docker 서비스로 구동하며, S3 API `9003`, 콘솔 `9004` 포트를 기본 후보로 정리.
  - 미디어 객체 보존 기간을 무기한으로 확정하고, DB 논리 삭제나 장소 매칭 실패만으로 RustFS 객체를 자동 삭제하지 않는 정책을 문서화.
  - `media_assets` 테이블을 추가해 RustFS 버킷, 객체 키, URI, 체크섬, 크기, 보존 정책을 저장하도록 데이터 모델 보강.
  - 지오코딩 결과가 없거나 모호한 장소를 `extracted_place_candidates`에 `needs_review` 상태로 남기고, 웹 UI와 MCP에서 사용자가 직접 장소명·주소·좌표·카테고리를 수정할 수 있게 계획 수정.
  - YouTube 영상 설명 원문, Gemini 오탈자·문맥 보정 설명, Gemini 장소 설명 보강 필드를 분리해 저장하도록 스키마 계획 보강.
  - `docs/decisions.md`에 ADR-15, ADR-16 추가.
- **다음 작업**:
  - T-003: 스캐폴딩 단계에서 RustFS 로컬 Docker 서비스, 버킷 초기화, 저장 계층 인터페이스를 코드 구조에 반영.

---

## 2026-06-05: Google Docs 소형 프로젝트 SpatiaLite 명세 반영

- **담당자**: Codex
- **작업 내용**:
  - Google Docs `AI유튜브여행_소형프로젝트_SpatiaLite_명세서` 내용을 확인하고 로컬 문서 계획을 최신 기준으로 재정렬.
  - 기존 문서의 대규모 지향 설계와 충돌하는 항목을 보완:
    - 비공식 검색/스크래퍼 중심 표현을 공식 YouTube Data API v3 우선 전략으로 교체.
    - 단순 SQLite3 표현을 SQLite + SpatiaLite 임베디드 공간 DB 기준으로 보강.
    - 장시간 작업 실행 주체를 API/MCP가 아니라 APScheduler 단일 실행자로 명확화.
    - `etl_jobs` 중심 표현을 Web REST, MCP, scheduler가 공유하는 `crawl_runs` 작업 테이블로 정리.
    - 프론트엔드 스택에 React Hook Form, Zod, shadcn/ui, Tailwind CSS, TanStack Query를 반영.
    - Zustand는 초기 범위에서 보류하는 것으로 정리.
  - `docs/decisions.md`에서 ADR-5와 ADR-10을 superseded 처리하고 ADR-11 ~ ADR-14를 추가.
  - `docs/tasks.md`를 T-003 이후 실제 구현 순서에 맞게 재정렬.
- **다음 작업**:
  - T-003: 소형 프로젝트 기준 스캐폴딩, Docker Compose, SpatiaLite 환경 변수, scheduler 디렉토리 구조 정비.

---

## 2026-06-04: 상세 기획서 반영 및 MCP UX 계획 추가

- **담당자**: Codex
- **작업 내용**:
  - `G:\My Drive\tripmate\AI유튜브여행_상세기획서.docx`의 핵심 설계 요소를 현재 개발 계획에 반영.
  - 상세 기획서의 다음 항목을 백로그와 아키텍처에 승격:
    - Gemini 기반 파생 키워드와 `season_context` 저장.
    - 채널, 재생목록, 일반 검색 결과의 우선순위 큐.
    - `yt-dlp` 기반 `skip_download`, `extract_flat` 수집.
    - `youtube-transcript-api` → `yt-dlp` 자막 추출 → `faster-whisper` 3단계 전사 폴백.
    - Gemini JSON Schema 기반 POI 추출.
    - FFmpeg Input Seeking 대표 프레임 추출.
    - 지오코딩 캐시, API 429 지수 백오프, 좌표계 정규화.
    - 작업 상태, heartbeat, retry_count, stale 작업 재투입.
  - 웹 UX 외에 AI 에이전트가 사용할 MCP 서버 읽기/쓰기 UX를 별도 사용자 접점으로 추가.
  - 최신 요청에 따라 `kraddr-geo` 연계는 취소하고, Kakao / Naver / VWorld 기반 Geocoding/Reverse Geocoding으로 정리. 이후 T-021에서 VWorld 우선 및 `python-vworld-api` 직접 client 사용으로 보강.
  - `docs/decisions.md`에 ADR-7 ~ ADR-10 추가:
    - MCP 서버 읽기/쓰기 UX 채택.
    - 지오코딩 공급자 전략 및 `kraddr-geo` 제외.
    - ETL 복원력 보강 원칙.
    - SQLite3 우선 구현과 PostGIS 전환 유보.
- **다음 작업**:
  - `frontend/`, `backend/`, `etl/`, `tests/`, `mcp/` 디렉토리 뼈대와 실제 구현 파일 생성 (T-003).

---

## 2026-06-03: 프로젝트 초기화 및 문서 시스템 정교화

- **담당자**: AI 에이전트 (Antigravity 2.0)
- **작업 내용**:
  - `tripmate-agent` 프로젝트의 기본 골격을 `maplibre-vworld-js`와 완벽히 호환되는 한글 문서 및 구조로 초기화.
  - 루트 디렉토리에 핵심 정보 파일 작성:
    - [README.md](../README.md): 프로젝트 개요, 시스템 흐름도, 퀵스타트 명령어 및 도큐먼트 링크 제공.
    - [AGENTS.md](../AGENTS.md): 한글 문서 원칙, 보존 식별자 규칙, Windows 개발 정책 및 DO NOT 룰 설정.
    - [CLAUDE.md](../CLAUDE.md): 프로젝트 개발 진척도, 디렉토리 구조도, 검증 명령어 및 아키텍처 결정 인덱스 수록.
    - [SKILL.md](../SKILL.md): 가상환경 구성, YouTube API 할당량 회피 전술 및 Playwright E2E 관련 개발 지침서.
    - [.env.example](../.env.example): 로컬 테스트용 VWorld 키, Gemini API 키, YouTube API 키 템플릿 정의.
  - `docs/` 디렉토리에 기술 명세 수립:
    - [architecture.md](architecture.md): Next.js/FastAPI/SQLite3/ETL 간 통합 아키텍처 다이어그램 및 3단계 ETL 동작도 작성.
    - [decisions.md](decisions.md): Next.js App Router(ADR-1), FastAPI + SQLAlchemy 2.0(ADR-2), Gemini 요약 파이프라인(ADR-3), VWorld 지도 통합(ADR-4), YouTube 할당량 캐싱(ADR-5), Playwright E2E(ADR-6) 의사결정 수립.
    - [tasks.md](tasks.md): 로드맵 백로그 구성 (T-001 ~ T-009).
    - [dev-environment.md](dev-environment.md): Windows 호스트 전용 Python 가상환경 구축, node_modules 설치, Playwright 브라우저 연동 매뉴얼 작성.
  - Git 초기화 및 origin 설정:
    - `main` 브랜치 최초 생성 및 `.gitignore`, `.gitattributes` 커밋 후 원격 저장소(`https://github.com/digitie/tripmate-agent`)에 푸시 완료.
    - 현재는 `feature/project-bootstrap` 기능 브랜치에서 셋업 작업 진행 중.
- **다음 작업**:
  - `frontend/`, `backend/`, `etl/`, `tests/` 각각의 뼈대 설정 파일 배치 및 디렉토리 트리 구축 (T-003).
