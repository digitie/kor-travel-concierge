# CLAUDE.md — 프로젝트 컨텍스트

이 파일은 에이전트가 매 세션 시작 시 자동으로 읽어 현재 프로젝트 상태와 연속성을 파악하는 진입점이다.
프로젝트 규칙은 `AGENTS.md`에, 개발 환경 상세 팁은 `SKILL.md`에 정의한다.

## 목표

`kor-travel-concierge`는 YouTube 여행 콘텐츠에서 여행지(POI) 정보를 추출·저장하고 외부에 공급하는 서비스다.

1. **수집·추출·저장**: 사용자가 지정한 키워드·플레이리스트·사용자 입력을 바탕으로 YouTube를 검색하고, 동영상·자막·동영상 정보를 확인해 여행 관련 장소 정보를 추출·저장한다. 1회 추출과 사용자가 설정한 주기의 반복 추출을 모두 지원하며, 동영상 원본도 저장한다.
2. **AI + 외부 API 보강**: 키워드 정제, 자막 정리, 자막에서의 POI 추출은 AI agent의 도움을 받고, 외부 API(지오코딩 등)로 정보를 수정·보완한다.
3. **외부 공급**: REST API를 통해 외부에서 저장된 여행 정보를 가져갈 수 있다.

## 프로젝트 현황 (2026-07-13)

Gemini API 기반의 YouTube 여행 컨텐츠 검색, 정리, VWorld 지도 시각화, MCP 읽기/쓰기 도구 UX를 함께 제공하는 `kor-travel-concierge` 개발 초기 단계이다. 최신 기준 문서는 Google Docs `AI유튜브여행_소형프로젝트_SpatiaLite_명세서`와 후속 RustFS 미디어 저장 요구사항이며, 1~2인 운영 기준 소형 프로젝트로 설계를 경량화한다.

### 현재 작업

- **T-177 완료**: 검수·작업·장소·테마 목록을 `items/next_cursor/has_more/total/newest_id/newer_than`
  공통 envelope로 전환했다. watermark keyset과 filter fingerprint, page 밖 단건 상세, 엄격한 cursor·
  filter 입력 경계, 인증과 분리된 `REPEATABLE READ` 목록 session을 적용했다. 프런트 임시 wrapper는
  기존 배열/그룹 계약을 보존하고 features cursor 계약은 변경하지 않았다. n150 PostgreSQL 301/501건
  통합 검증, backend 전체 pytest, frontend lint/type-check/Vitest/build, Playwright 5건을 통과했다.
- **T-176 완료**: T-175의 immutable `read|admin` scope를 production 소비자에 적용했다. DB
  read key는 docker-manager 단일 원천에서 `kor-travel-map` Dagster·daemon에만 주입하고 Map
  API에서는 제거했다. snapshot/changes 1,416개 전체 순회와 실제 Dagster 가져오기 경로, read
  공급 GET 200·write/내부 GET 403, 구 정적 admin key 401·신규 BFF/operator admin GET 200,
  UI 로그인 계약을 n150에서 검증한 뒤 평문 임시 파일과 백업을 제거했다. 관련 변경은 Concierge PR #182,
  `kor-travel-map` PR #664, docker-manager PR #51이다.
- **T-175 완료**: 공개 API 키에 DB CHECK가 있는 immutable `read|admin` scope를 추가하고 기존
  행을 read로 backfill했다. generation-safe `key_hash→scope` cache, 공급 GET 11경로 exact
  allowlist, 내부 GET·write deny-by-default, DB read query 한정, DB/static admin header,
  CIDR read, `/admin/*` BFF proxy 전용 계약을 구현했다. 발급 UI와 공급 문서를 scope 기준으로
  정렬했다. production `kor-travel-map` read key 회전·구 consumer 정적 항목 제거는 T-176에서 완료했다.
- **T-154 완료**: 검수 큐 첫 진입 성능을 개선했다. 프런트는 `/destinations/unmatched` 초기 조회를
  최신 300개로 낮추고 필요 시 300개씩 확장하도록 바꿨으며, 자동 refetch를 15초→60초로 완화해
  2,000행 전체 JSON 파싱·DOM 렌더를 첫 화면에서 피한다. 백엔드는 검수 큐 조회용 복합 인덱스
  (`match_status,id`, `source_channel_id,match_status,id`, `source_playlist_id,match_status,id`)와
  검색어 필터용 `youtube_videos.source_search_query` 인덱스를 추가했다. Google Places 403은
  prod에서 유효 길이의 env key가 사용되는 상태에서도 Google만 `PERMISSION_DENIED`를 반환하고
  Kakao/Naver는 정상이라 Cloud Console API 키 제한/API 제한 설정 문제로 재확인했다.
- **T-152 완료**: (a) 수집 페이지 상단 밴드 grid 재조정 + 폼 2열 배치로 폭 활용. (b) 검수 큐 `/destinations/unmatched` 응답을 리스트 전용 경량 payload로 축소(3.8MB→~1.3MB, provider_evidence_json 제외·파생 카테고리 코드만 서버 계산). (c) 테마 중심 POI 공급 API 3종(`/api/v1/themes`, `/themes/places?kind=&value=`, `/themes/video/{id}/places` — 동영상 테마는 매치/검수완료 POI ≥5일 때만 공개) + `theme_service`(ADR-35). (d) 관리 nav `API`·`/api-test` 외부 API 테스트 페이지. 부수로 stale 테스트 1건 정정.
- **T-150 완료**: 유지보수 UI/UX 개편 — `@base-ui/react` 기반 shadcn 프리미티브 확장(checkbox/switch/textarea/popover/alert-dialog), `window.confirm`·raw input 전면 교체와 파괴적 액션 확인 다이얼로그 통일(`ConfirmActionButton`), 중복 대시보드 조각 공용화(`components/panels.tsx`·`detail.tsx`·`CopyButton`·`lib/format.ts`), 사장 코드(AppNav/SettingsDialog/OpsMetricsDialog) 삭제, 수집 폼 자동 인식 미리보기·유형별 형식 검증(`lib/youtube.ts`+vitest), 검수 좌표 검증, 설정 프롬프트 글자 수 카운터, 긴 설명의 `HelpTip`(popover) 이관, backend `source_resolve` 불균형 `[` 500 크래시 수정(ADR-34).
- **T-151 완료**: Google Places 403 응답 본문(원인 코드)을 `/place-search` `errors.google`에 노출. prod 진단으로 원인이 Cloud Console API 키 제한임을 확정(코드 정상).
- **T-149 완료**: `AppShell` 헤더를 얇은 한 줄 바로 축소하고 페이지 설명 문구·섹션 배지·경로 표시·반복 부제를 제거(내부 도구 기준, E2E heading 어서션은 유지).
- **T-148 완료**: 개발·검증 실행 정책을 Linux/WSL 전용으로 재정렬했다. 과거 예외였던 `git`/`gh`/codegraph 계열 분석 명령도 Linux bash에서 실행하며, Playwright E2E는 n150 live/Linux 환경에서 우선 실행하고 불가할 때만 Windows 호스트 fallback을 허용한다는 기준을 ADR-33과 문서 전반에 반영했다.
- **T-014 완료**: 단일 호스트 Docker Compose 구성, RustFS host/container endpoint 분리, MCP `streamable-http`, API health 기반 시작 순서, RustFS 버킷/객체 smoke 검증 스크립트를 정비하고 실제 Compose smoke를 완료.
- **T-021 완료**: VWorld 우선 지오코딩과 `python-vworld-api` `AsyncVworldClient` 직접 사용, Kakao 공식 키워드 장소 검색 fallback, wrapper 최소화 정책을 코드와 문서에 반영.
- **T-015 완료**: Playwright가 backend `127.0.0.1:18080`과 frontend `127.0.0.1:13100`을 자동 기동하고, 테스트 전용 SQLite DB를 시드해 메인 화면, 수집 시작, Deep Research, 검수 후보 보정, 설정 저장을 브라우저에서 검증한다.
- **T-016 완료**: sqlite-vec / SQLite Vec1, PostgreSQL/PostGIS, PgQueuer, APScheduler + PostgreSQL advisory lock 후보를 검토하고 ADR-20에 “선제 도입 보류, 수치 트리거 기반 전환”으로 정리.
- **T-020 완료**: frontend를 Next.js 16.2.7 / React 19.2.7로 업그레이드하고 ESLint flat config, `next typegen`, Tailwind animation 보정, PostCSS override로 `npm audit` 0건을 달성.
- **T-027 완료**: Windows live 포트를 API `12401`, Web `12405`로 고정하고, `.env.example`, Docker Compose host port, Windows live 재시작 스크립트, 문서를 정리.
- **T-028 완료**: 장소별 YouTube 영상·유튜버 언급 소스 집계, 언급 횟수 정렬, 선택/전체 장소 `xlsx`/`gpx`/`kml` export, MCP 상세 집계, 카테고리 추정 정책을 구현·문서화.
- **T-029 완료**: Windows live test 후속 보완으로 Web 기동 안정화, `gemini-flash-latest` 설정 선택지 보존, 공용 `Input` hydration 경고 제거, live 포트·키 smoke를 재확인.
- **T-030 완료**: Windows FFmpeg 자동 준비와 VWorld 지도 축소 안정화를 반영해 Windows live 시작과 Playwright 지도 검증 경로를 보강.
- **T-031 완료**: 작업 상태에 현재 메시지와 상세 로그를 저장·반환하고, Gemini 검색어 보정·YouTube 검색·동영상 적재·완료/실패/stale 재시도 로그를 누적. 웹 수집 패널은 상세 로그 타임라인을, 운영 패널은 `running`/`pending` 실행 큐 목록을 표시.
- **T-032 완료**: harvest 완료 후 신규 YouTube 영상의 자막 추출, Gemini POI 요약, VWorld/Kakao/Naver 지오코딩 후처리를 이어 실행해 `travel_places`와 `video_place_mappings`까지 생성한다.
- **T-033 완료**: RustFS 로컬 개발 설정은 단일 `kor-travel-concierge` 버킷, `features/` prefix, 호스트 `http://127.0.0.1:12101`, Compose 컨테이너 `http://host.docker.internal:12101` 기준으로 맞춘다. `http://rustfs:9000`은 선택형 내장 RustFS profile에서만 사용한다.
- **T-034 완료**: PR #30 P0-1 Tailwind 색상 토큰 alpha modifier 미생성 문제를 해소하고 `--destructive-foreground` 누락 토큰을 보강했다.
- **T-035 완료**: PR #30 P0-2 `deep_research` job handler 미등록 문제를 해소하고, Gemini Deep Research 결과를 `travel_places.detailed_research_content`에 저장하는 scheduler 경로를 추가했다.
- **T-036 완료**: PR #30 P0-3 기존 SQLite DB의 `video_place_mappings(video_id, place_id)` stale unique 제약 제거 경로를 `init_db()`에 추가했다.
- **T-037 완료**: PR #30 P1-1 원본 미디어 저장 경로에 file-like streaming 업로드와 업로드 중 checksum/size 기록을 추가했다.
- **T-038 완료**: PR #30 P1-2 `claim_next_pending`을 `WHERE state='pending'` 가드가 있는 update claim으로 보강했다.
- **T-039 완료**: PR #30 P1-3 스키마 드리프트 대응을 위해 `schema_migrations` 경량 registry를 추가했다.
- **T-040 완료**: PR #30 P1-4 지도 marker diff 기반 캐싱과 선택 변경 기준 재중심 보강을 반영했다.
- **T-041 완료**: PR #30 P1-5 FFmpeg 자동 다운로드를 gyan.dev 안정 URL과 SHA256 sidecar 검증, portable `7zr.exe` 고정 SHA256 검증 경로로 보강했다.
- **T-042 완료**: PR #30 P1-6 docker-compose CORS override/default origin과 Windows live 포트 점유 프로세스 종료 안전장치를 보강했다.
- **T-043 완료**: PR #30 P2-1 장소 export 직렬화를 thread로 격리하고 export limit 상한과 XML 1.0 제어문자 정제를 추가했다.
- **T-044 완료**: PR #30 P2-2 keyword `publishedAfter`와 playlist target watermark 기반 증분 수집을 보강했다.
- **T-045 완료**: PR #30 P2-3 `next-env.d.ts` 생성물 추적과 정규화 hook 의존을 제거했다.
- **T-046 완료**: PR #30 P2-4 Node engine과 `@types/node` 런타임 계열 정리를 반영하고, `jsx` 권고는 Next 16.2.7의 강제 재설정 때문에 유지했다.
- **T-047 완료**: PR #30 P2-5 공유 `Input` 전역 `suppressHydrationWarning`과 VWorld 키 child 재주입을 제거했다.
- **T-048 완료**: PR #30 P2-6 heartbeat task 종료 await에서 `CancelledError`만 정상 처리하고 예상 밖 예외는 로그로 남기도록 좁혔다.
- **T-049 완료**: PR #30 P2-7 Gemini engine 모델 목록·기본값·runtime 설정 검증을 backend 단일 출처로 정리하고 실제 Gemini 호출에 DB 설정을 연결했다.
- **T-050 완료**: PR #30 P2-8 `_names_compatible` 부분일치 기준에 최소 길이와 비율 조건을 추가해 짧은 부분명 false-positive 재사용을 줄였다.
- **T-051 완료**: PR #30 P3-1 문서 상태 불일치를 정리하고 남은 P3 항목을 `docs/tasks.md` 대기 작업 T-052~T-055로 승격했다.
- **T-052 완료**: PR #30 P3-2 FFmpeg runtime 설정은 `FFMPEG_PATH`만 주입하고 `FFPROBE_PATH`는 Windows live 사전 검증 전용으로 범위를 정리했다.
- **T-053 완료**: PR #30 P3-3 export 파일명에 선택/전체 범위, 실제 내보낸 개수, 정렬 기준, UTC timestamp를 반영했다.
- **T-054 완료**: PR #30 P3-4 코드 위생 정리로 모델 FK `ondelete` 정책을 명시하고, `YoutubeVideo` timestamp 예외 사유와 import 정렬을 보강했다.
- **T-055 완료**: PR #30 P3-5 Windows live Python launcher fallback을 Python 3.10+ 정책에 맞게 정리했다.
- **T-056 완료**: Windows 네이티브 실행 경로를 배제하고 실행/평가 환경을 Linux Docker 전용(Windows는 WSL2)으로 전환. PowerShell 라이브/FFmpeg 스크립트 제거, bash `scripts/verify-docker-compose.sh`·`scripts/start-live.sh` 추가, FFmpeg을 컨테이너 `/usr/bin/ffmpeg` 단일 경로로 정리, host port는 고정 API `12401` / Web `12405`를 유지(컨테이너 내부 `8000`/`3000` 매핑), 문서를 bash/Docker/WSL2 기준으로 재작성(ADR-23).
- **T-057 완료**: REST API를 `/api/v1` 프리픽스로 버저닝하고 외부 호출용 `X-API-Key` 인증(인증 코드)을 추가. `APP_ENV`(기본 `local`)·`API_AUTH_ENABLED`(기본 false)·`API_KEYS` 설정으로 로컬(`local/test/e2e`)은 무인증 우회, 비-local은 인증을 강제(ADR-24). 잔여 Windows 스크립트 정리(`scripts/*.ps1` 삭제, bash `verify-docker-compose.sh`로 대체)와 함께 당시 기준의 E2E Playwright Windows 호스트 예외를 문서에 명시했다. 현재 기준은 ADR-33의 n150 live/Linux 우선, Windows fallback 정책이다. README·SKILL·dev-environment·architecture 문서를 Docker Compose 기준으로 정리.
- **T-061 완료**: backend DB runtime을 PostgreSQL/PostGIS(`asyncpg`)로 전환하고 SpatiaLite/SQLite 보정 registry를 제거했다. `TravelPlace.geom geometry(Point, 4326)`와 GiST/FK/composite index를 모델·Alembic 초기 migration에 반영했으며, 반경 검색은 `ST_DWithin`, 작업 claim은 `FOR UPDATE SKIP LOCKED` 기준으로 바꿨다. `.env.example`, local `.env`, Compose, Dockerfile, E2E DB env도 Postgres 기준으로 맞췄다.
- **T-062 완료**: `youtube_channels`, `youtube_playlists`, `youtube_playlist_videos`, `youtube_video_analysis_runs`와 migration `20260610_0002`를 추가했다. `youtube_videos.channel_id`를 channel FK로 승격하고 canonical URL, duration, thumbnail, tags JSONB, Gemini URL summary, transcript summary, reconciled summary 필드를 보강했으며, 수집 파이프라인이 YouTube channel/playlist/video/link metadata를 함께 upsert한다.
- **T-063 완료**: `source_targets`에 scan interval/cursor/watermark/budget/failure 필드를 추가하고, `source_scan` handler가 due keyword/channel/playlist/video target을 `harvest` 또는 `video_analysis` crawl_run으로 enqueue한다. APScheduler에는 PostgreSQL SQLAlchemyJobStore 기반 persistent job store와 `source-scan-enqueue` interval job을 적용했다.
- **T-064 완료**: Gemini 공식 문서 기준 공개 YouTube URL 입력(`file_data.file_uri`, preview)을 확인하고, `video_analysis_service`가 `url_summary`와 `reconcile` pending run을 실행해 `youtube_video_analysis_runs`와 `youtube_videos.gemini_url_summary*`/`reconciled_summary*`에 결과를 저장한다. transcript 기반 POI 추출 summary도 `youtube_videos.transcript_summary`에 남긴다. 충돌·낮은 신뢰도 후보는 자동 확정하지 않고 `needs_review`와 `review_note`로 유지한다. 실제 Gemini URL smoke는 API 키와 할당량을 쓰지 않기 위해 아직 수행하지 않았다.
- **T-065 완료**: `extracted_place_candidates`와 `video_place_mappings`에 YouTube channel/playlist/analysis run provenance, `source_kind`, `provider_evidence_json`, `feature_export_status`를 추가하고 migration `20260610_0004`를 작성했다. transcript 후보는 transcript asset/source/timestamp evidence를, 지오코딩은 VWorld/Kakao/Naver 후보와 선택 결과를 JSONB로 저장한다. 자동/수동 확정은 `ready`, 검수 대기는 `pending`, 제외는 `rejected`로 둔다. Google Places API 보강과 `python-krtour-map` 8자리 category mapping은 별도 확인 후 구현한다.
- **T-070 완료**: `python-krtour-map`의 8자리 category 코드표(144개)를 `backend/ktc/data/place_category_codes.json`으로 복사하고, `category_catalog` 로더와 `category_suggestion` Gemini 선택기(주입형 `LlmCallable`)를 추가했다. Gemini가 복사된 카탈로그에서 8자리 코드 하나를 고르고 카탈로그 검증·미지정/미상은 `None`으로 둔다. `TravelPlace.category_code_suggestion`과 migration `20260610_0006`를 추가하고, `geocode_service`가 장소 확정 시 채워 `feature_export` payload로 노출한다. 런타임 참조 순환참조를 복사로 끊었고 카테고리 drift는 수용 가능하다고 판단(2026-06-11). `feature_id` 생성은 `python-krtour-map` 책임 유지.
- **T-068 완료**: PinVi feature 연계 POI/curated plan 소비 흐름을 검증했다. `kor-travel-concierge`는 PinVi DB에 직접 쓰거나 자동 POI/curated plan 등록을 하지 않고, `python-krtour-map`이 `kor-travel-concierge-youtube` provider로 생성한 feature의 `feature_id`와 `feature_snapshot`을 PinVi가 자체 feature 연계 POI row로 저장하는 흐름을 유지한다. Curated plan은 feature 모음이 아니라 그 POI row들의 모음이다. `docs/feature-export-api.md`를 공급자 정본 계약으로 추가하고, feature export API 테스트에 이름·좌표·8자리 카테고리 제안·YouTube video/channel/playlist 근거·Gemini URL evidence가 snapshot 응답에 보존되는 회귀 검증을 추가했다.
- **T-069 완료**: PostgreSQL/PostGIS disposable DB 기준 feature export target pytest, backend 전체 pytest, backend compileall, bash/Compose config, frontend lint/type-check/build, Docker Compose smoke, Windows host Playwright E2E, `python-krtour-map` provider/live pull smoke, PinVi POI/notice plan snapshot fallback smoke를 모두 통과했다. E2E seed는 `youtube_videos.channel_id` FK에 맞춰 `YoutubeChannel` stub을 함께 적재하도록 보정했다.
- **T-085 완료**: AI 엔진 다중 provider를 도입했다. Gemini 외에 DeepSeek V4(`deepseek-v4-flash`, `deepseek-v4-pro`, OpenAI 호환 `https://api.deepseek.com`)를 대안 LLM provider로 추가하고, 웹 설정(`/settings`)에서 엔진을 Gemini/DeepSeek로 전환·DeepSeek 키 저장(평문 미노출, 감사 로그 마스킹)한다. `ktc/etl/deepseek_client.py`(OpenAI 호환 chat completion + JSON mode), `ktc/etl/llm_client.py`(provider 디스패치 `complete_json` + `LlmRuntime` + 사전 프롬프트 prepend), `config.py`의 `DEEPSEEK_*`/`DEEPSEEK_ENGINE_OPTIONS`/`LLM_ENGINE_OPTIONS`/`is_deepseek_model`을 추가했다. 모든 AI 프롬프트 앞에 붙는 사용자 편집 가능 사전 프롬프트(런타임 설정 `ai_preprompt`, 기본 `AI_PREPROMPT_DEFAULT`)를 두고, JSON 출력은 Gemini `responseSchema`·DeepSeek `response_format=json_object`+스키마 첨부로 보강했다. 느린 사람 유사 재시도(`LLM_RETRY_*`: base 15s/max 90s/jitter 0.3/4회, `gemini_client.human_like_retry_delay` Gemini·DeepSeek 공용)로 기존 2/4/8초를 대체했다. DeepSeek 키는 gitignore된 `.env`/`.env.production`에만 두고 `.env.example`은 placeholder다(ADR-30).
- **T-086 완료**: Next App Router 기본 오류 화면 대신 한국어 에러 복구 UI를 이식했다(kor-travel-geo PR #391 동등). `frontend/src/app/error.tsx`, `global-error.tsx`, `components/layout/AppErrorPanel.tsx`, `lib/error-recovery.ts`를 추가해 chunk/RSC/network 런타임 오류 시 같은 pathname에서 1회만 hard reload하고, 반복 실패 시 재시도/이전 화면/오류 정보를 제공한다. Tailwind + shadcn으로 적용했다(ADR-30).
- **T-084 완료**: 형제 프로젝트 `kor-travel-geo`의 UI 지침(`kor-travel-geo-ui/docs/DESIGN-RULES.md`, StyleSeed 기반)을 프런트에 그대로 이식하고 빌드 엔진을 Tailwind v3.4→**v4**로 전환했다. 단일 accent brand(teal `#0f766e`)·5단계 text·surface/status/shadow/motion semantic 토큰을 `globals.css`/`tailwind.config.ts`에 단일 출처로 두고 shadcn 토큰을 brand에 매핑(기존 컴포넌트 자동 적용). primitive(`button/input/label/badge/select`)를 44px touch·8px radius·uppercase 12px label·named motion·brand ring으로 정렬, 하드코딩 색을 semantic으로 치환, `frontend/docs/DESIGN-RULES.md` 정본 추가. v4는 `@tailwindcss/postcss`·`@import "tailwindcss"`·`@config`·`tw-animate-css`·`@custom-variant dark`(light 전용). lint/type-check/build 통과, `/settings`·`/` Playwright 시각 검증(ADR-29).
- **T-083 완료**: 외부 노출 prod를 공개 도메인 5개(Web, REST API, MCP, RustFS S3 API, RustFS 콘솔)로 운영하도록 구성했다. 앱은 이미 CORS/인증/RustFS 공개 URL/BFF origin/프록시 헤더가 모두 env 기반이라 **백엔드·프론트 코드 변경 없이** env + TLS 종단 리버스 프록시로만 처리한다. `docker-compose.yml`의 하드코딩 `RUSTFS_CONSOLE_URL`(127.0.0.1)/`NEXT_PUBLIC_API_BASE_URL`을 env-driven으로 바꾸고 `FORWARDED_ALLOW_IPS`(uvicorn 직접 사용)를 전달한다. `.env.example`에 prod 예시(placeholder만), gitignore된 `.env.production`에 실제 도메인 + `APP_ENV=production` + 생성한 `API_KEYS`/`BACKEND_API_KEY`, `deploy/Caddyfile`(자동 TLS, `{$ENV}` 치환, MCP SSE-off·`basic_auth` 옵션)을 추가했다. **실제 도메인/비밀은 외부 비노출** — 커밋 산출물에는 placeholder만, 실제 값은 gitignore된 `.env(.production)`에만 둔다. RustFS 매핑은 `s3-api.<base>`=S3 API/공개 객체(`RUSTFS_PUBLIC_BASE_URL`), `s3.<base>`=콘솔(`RUSTFS_CONSOLE_URL`), 백엔드 boto3 연결은 내부 `host.docker.internal:12101` 유지. 추가로 prod 오케스트레이션은 `kor-travel-docker-manager`(공식 도메인)이고 dev는 여기에서 `127.0.0.1`+고정 12xxx로 실행하도록 구분했으며, dev 기동 스크립트(`start-live.sh`/`stop-fixed-ports.sh`)는 점유 포트를 새 포트로 바꾸지 않고 강제 종료 여부를 묻고 거부 시 중지하도록 바꿨다. compose `env_file` 경로를 `${APP_ENV_FILE:-.env}`로 덮어쓸 수 있게 하고, MCP는 Caddy `basic_auth`(기본 ON, fail-safe 잠금 기본값)로 보호한다(ADR-28). 자체 검증 워크플로(3 렌즈→반박 검증)로 확인된 MCP 익명 노출·`--env-file` 비밀키 누락 이슈를 반영했다.
- **T-066 완료**: `extracted_place_candidates`를 출처로 삼는 export ledger `feature_exports`와 migration `20260610_0005`를 추가했다. `export_id`, 증가 cursor `sequence`(전용 PostgreSQL sequence), `operation`(`upsert`/`reject`/`tombstone`), `payload_json`/`payload_hash`(`sha256:`), reject/tombstone 재전송 필드를 보존하고, `feature_export_service.sync_feature_exports`가 후보 상태로부터 ledger를 멱등 동기화한다. `GET /api/v1/features/snapshot`(활성 `upsert`)과 `GET /api/v1/features/changes`(전 operation)를 opaque base64 cursor 기반으로 노출하며 ADR-24 `X-API-Key` 인증을 적용한다. `category_code_suggestion`은 `python-krtour-map` 8자리 mapping 확정 전까지 `null`로 둔다.
- **T-060 완료**: SQLite + SpatiaLite에서 PostgreSQL + PostGIS로 전환하고 `python-kraddr-geo` 로컬 DB 서버를 재사용하는 결정을 ADR-25로 추가. YouTube channel/video/playlist metadata, Gemini YouTube URL 요약과 transcript 비교, 범용 full/incremental feature pull API, PinVi feature 연계 POI와 curated plan 소비 흐름을 ADR-26과 `docs/youtube-feature-pipeline-plan.md`로 문서화하고 T-061~T-069로 작업을 분해했다.
- **실행 모델 결정**: 앱 런타임은 단일 호스트 Docker Compose(`docker compose up -d --build`)이며 host 고정 포트 API `12601`, MCP `12602`, Web `12605`로 띄운다(컨테이너 내부 API `8000`, Web `3000`). RustFS는 외부 고정 Docker 서비스로 두고 S3 API `12101`, 콘솔 `12105`를 사용한다. `scripts/start-live.sh`는 기동 전 `scripts/stop-fixed-ports.sh`로 이 repo 소유 고정 포트 `12601`/`12602`/`12605`를 점유한 리스너(Linux/Docker/WSL/Windows)를 회수해 재시작을 보장하고, RustFS 포트는 회수하지 않는다(패턴은 `python-krtour-map`에서 차용). Windows 사용자는 WSL2(Ubuntu) + Docker 안에서 동일한 bash 명령으로 앱을 구동한다(ADR-23). 에이전트/Codex 작업 명령은 `git`, `gh`, codegraph 계열 분석 명령까지 포함해 모두 WSL2(Ubuntu)를 포함한 Linux bash에서 실행한다(ADR-33). **E2E Playwright는 n150 live/Linux 환경에서 우선 실행하고, 불가할 때만 Windows 호스트 fallback으로 실행한다**.
- **API 경계 결정**: REST 엔드포인트는 `/api/v1` 프리픽스 아래(`/health`·`/`는 버전 없음)이며 `X-API-Key` 인증을 받는다. 브라우저는 same-origin Next BFF를 거쳐 서버 전용 static admin `BACKEND_API_KEY`를 주입한다. 외부 소비자는 DB `read` 키로 명시된 공급 GET만 호출하고, DB/static `admin` key는 header에서 일반 운영 API를 허용하되 `/admin/*`는 BFF proxy 전용이다. `?key=`는 DB read key만 허용한다. `APP_ENV=local/test/e2e`는 무인증 우회, 외부 노출 배포는 `APP_ENV=production`+BFF/operator용 `API_KEYS`로 인증을 강제한다(ADR-24/36).
- **DB 전환 기준**: 목표 DB는 PostgreSQL + PostGIS다. 로컬 개발 서버는 `python-kraddr-geo`의 PostgreSQL/PostGIS 서버를 재사용하고 별도 DB `kor_travel_concierge`를 목표로 한다. T-061에서 `asyncpg`, Alembic bootstrap, PostGIS `travel_places.geom`, `ST_DWithin` 검색, PostgreSQL claim을 구현했다. 로컬 검증은 `python-kraddr-geo` DB 서버의 `localhost:5432`에 disposable DB `kor_travel_concierge_test`를 만들어 실행한다.
- **YouTube feature 공급 결정**: `kor-travel-concierge`는 YouTube 장소 후보 provider가 되고, `/api/v1/features/snapshot`·`/api/v1/features/changes` 범용 API를 제공한다. REST path에는 특정 downstream 이름을 넣지 않는다. `kor-travel-map`은 이 API를 주기적으로 pull하는 첫 consumer이며, `feature_id` 생성은 `kor-travel-map` 책임이다. production consumer는 T-176부터 DB read key만 사용하며 BFF/operator용 정적 admin 인증 정보와 분리한다. PinVi는 해당 `feature_id`와 `feature_snapshot`을 자체 feature 연계 POI row에 저장하고, curated plan은 그 POI row들의 모음으로 구성한다.
- **dev/prod 실행 구분**: 별도 지시가 없으면 이 repo의 실행/스크립트는 **dev**를 의미한다. dev는 여기에서 직접(`scripts/start-live.sh`/`docker compose`/`./ktcctl`) 띄우고 **내부 주소 `127.0.0.1` + 고정 12xxx 포트**(API 12601 / MCP 12602 / Web 12605 / RustFS 12101·12105)로 접속한다. **prod**는 **`kor-travel-docker-manager`**가 도커를 올리고 **공식 도메인**을 적용한다 — prod도 같은 12xxx host 포트를 쓰되 공식 도메인 + TLS 리버스 프록시로 노출한다(포트 번호 동일, 접속 주소만 다름).
- **dev 기동 안전장치**: `scripts/start-live.sh`/`stop-fixed-ports.sh`는 고정 포트가 이미 사용 중이면 **새 포트로 바꾸지 않고**, prod 유무와 무관하게 강제 종료 여부를 사용자에게 묻는다. 거부하면(또는 비대화형+`FORCE_KILL_PORTS` 미설정) 기동을 중지하고 떠 있는 인스턴스를 보존한다.
- **프로덕션 도메인 결정**: 외부 노출 prod는 TLS 종단 리버스 프록시(Caddy, `deploy/Caddyfile`) 뒤에서 공개 도메인 5개를 고정 포트(Web 12605 / API 12601 / MCP 12602 / RustFS S3 API 12101 / 콘솔 12105)로 라우팅한다. 실제 도메인/비밀은 git에 커밋하지 않고 gitignore된 `.env`(또는 `.env.production`)에만 둔다. prod는 `APP_ENV=production`+`API_KEYS`로 인증을 강제하고(`BACKEND_API_KEY`는 그중 하나), `FORWARDED_ALLOW_IPS=*`로 프록시 헤더를 신뢰하며, RustFS는 `s3-api`=공개 객체/`s3`=콘솔로 매핑한다. MCP는 앱 인증이 없어 Caddy `basic_auth`(기본 ON, 미설정 시 잠금 기본 해시로 fail-safe)로 보호한다. 브라우저는 same-origin BFF를 유지하므로 `NEXT_PUBLIC_API_BASE_URL`은 비운다(ADR-28).
- **다음 착수 대상**: Agent B는 T-178 `/destinations` 프런트 cursor append 전환부터 순서대로 진행한다. Agent A와의 교차 선행·파일 소유는 로드맵 §4를 따른다. 새 작업은 PostgreSQL/PostGIS + Linux Docker 실행 모델, ADR-36 scope 계약, prod ADR-28 리버스 프록시 모델을 유지한다.
- **지오코딩 결정**: 최신 요청에 따라 `kraddr-geo` 연계는 취소한다. VWorld를 최우선으로 사용하며 `python-vworld-api`의 `AsyncVworldClient`를 직접 호출하고, Kakao는 주소 검색 후 공식 키워드 장소 검색 fallback, Naver는 보조 검증으로 둔다.
- **YouTube 수집 결정**: 소형 프로젝트 기준 공식 YouTube Data API v3를 기본 수집 경로로 사용하고, 비공식 의존은 자막/프레임 구간으로 격리.
- **미디어 저장 결정**: 원본 동영상, 자막, 전사 결과, 대표 프레임은 별도 로컬 Docker RustFS 서비스의 `kor-travel-concierge` 버킷과 `features/` prefix에 저장하고 무기한 보존한다.
- **데이터 품질 결정**: 매칭 실패 장소는 자동 확정하지 않고 웹 UI/MCP 검수 큐에서 사용자가 보정한다. 영상 설명 원문, Gemini 보정 설명, Gemini 장소 보강 설명은 별도 필드로 저장한다.
- **장소 소스·카테고리 결정**: 확정 장소의 언급 수는 `video_place_mappings` 행 수로 계산하고, source video/channel은 `youtube_videos`와 조인해 노출한다. 카테고리는 Kakao Local 공식 카테고리를 우선하되 Gemini 후보, VWorld/Naver 주소 맥락을 보조 근거로 쓰고 불확실하면 검수 큐에 남긴다.
- **계층화 원칙**: 외부 API SDK를 숨기는 내부 adapter/wrapper는 새로 만들지 않거나 최소화한다. 필요한 경우에도 응답 dict를 내부 모델로 바꾸는 좁은 변환 함수 수준에 머문다.

### 잔존 기술 부채

- Next 내부 `postcss` override는 Next가 의존성을 직접 올리면 제거 가능 여부를 재검토한다.
- PostgreSQL/PostGIS 전환은 ADR-25와 T-061로 구현되었다. sqlite-vec과 멀티 워커 큐 전환은 PostgreSQL 전환 이후에도 별도 신호가 생길 때만 검토한다.

### 브랜치 상태

- `main` 직접 푸시는 금지한다. 모든 변경은 작업별 `codex/*` 브랜치에서 커밋하고 PR 생성 후 머지한다.

## 로컬 개발 환경 레이아웃

```
F:\dev\kor-travel-concierge\
├── frontend/             # Next.js App Router 프론트엔드 (Compose host Port: 12605 → 컨테이너 3000)
│   ├── src/
│   │   ├── app/          # 페이지 컴포넌트 (설정, 리스트, 지도뷰 등)
│   │   ├── components/   # 재사용 UI (maplibre-gl + VWorld WMTS 지도 포함)
│   │   └── utils/
│   ├── package.json
│   └── tsconfig.json
├── backend/              # FastAPI 비동기 API 백엔드 (Compose host Port: 12601 → 컨테이너 8000)
│   ├── app/
│   │   ├── api/          # API 라우터 (키워드 CRUD, 유튜버 CRUD 등)
│   │   ├── core/         # DB 세션 및 공통 설정
│   │   ├── etl/          # 수집·요약·지오코딩·대표 프레임 추출 파이프라인
│   │   ├── models/       # SQLAlchemy 2.0 모델 (T-061 이후 PostgreSQL + PostGIS 목표)
│   │   └── services/     # 도메인 서비스 및 RustFS 저장 계층
│   ├── requirements.txt
│   └── main.py
├── etl/                  # 비동기 ETL 파이프라인 스크립트
│   ├── search.py         # 1단계: 키워드 조합 YouTube 검색 (Gemini 보정)
│   ├── summarize.py      # 2단계: 신규 영상 요약 정리 및 설명 보정 (Gemini API)
│   ├── geocode.py        # VWorld 우선, Kakao/Naver 보조 지오코딩 및 역지오코딩
│   ├── media.py          # RustFS 원본 동영상/자막/전사 결과/프레임 저장
│   └── runner.py         # ETL 통합 실행기 (스케줄러/CLI)
├── scheduler/            # APScheduler 단일 실행자 (계획)
│   └── worker.py         # crawl_runs pending 작업 claim 및 실행
├── mcp/                  # Docker Compose 호환 MCP 실행 래퍼
│   └── server.py         # ktc.mcp_server.server 호출
├── ktc.mcp_server/        # MCP 서버 읽기/쓰기 도구 UX 구현
│   ├── server.py         # FastMCP 서버 생성 및 도구 등록
│   └── tools.py          # 여행지 조회, 보정, 병합, ETL 트리거 도구
├── tests/                # Playwright E2E 테스트 환경 (n150 live/Linux 우선, 불가 시 Windows fallback)
│   ├── e2e/
│   ├── scripts/          # E2E backend/frontend 기동 및 DB 시드 스크립트
│   ├── playwright.config.ts
│   └── package.json
└── docs/                 # 아키텍처 및 이력 관리 문서
    ├── architecture.md   # 전체 시스템 흐름도
    ├── decisions.md      # ADR 기록 (ADR-1 ~ ADR-35)
    ├── tasks.md          # 백로그 추적
    ├── journal.md        # 일지 기록
    └── dev-environment.md# Linux/Docker(및 WSL2) 개발 환경 구축 가이드
```

## 빠른 검증 및 실행 명령

실행/평가 환경은 Linux Docker 전용이다. Windows 사용자는 WSL2(Ubuntu) + Docker 안에서 아래 bash 명령을 실행한다.

### 기본 실행 (단일 호스트 Docker Compose, ADR-18/ADR-23)
```bash
docker compose up -d --build    # host API 12601 / MCP 12602 / Web 12605, 외부 RustFS 12101·12105 사용
# 또는 thin 런처 (start-live.sh: stop-fixed-ports.sh로 고정 포트 회수 후 기동)
bash scripts/start-live.sh
# smoke 검증 (기동 → health 확인 → RustFS 검증 → 정리)
bash scripts/verify-docker-compose.sh
```

### 백엔드 (FastAPI, 컨테이너 밖 로컬 개발)
```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cd ..
DATABASE_URL=postgresql+asyncpg://addr:addr@localhost:5432/kor_travel_concierge ./ktcctl api  # 12601 포트 구동
```

### 프론트엔드 (Next.js)
```bash
cd frontend
npm install
npm run dev     # 3000 포트 구동
```

### ETL 실행
```bash
./ktcctl etl
```

### E2E 테스트 (Playwright, **n150 live/Linux 우선** — ADR-33)
```bash
cd tests
npm install
npx playwright install
npx playwright test
```
앱 런타임과 개발 작업은 Linux Docker/WSL 전용이다. E2E 하니스는 n150 live/Linux 환경에서 우선 실행하고, n150 접근·브라우저·환경 제약으로 불가할 때만 Windows 호스트에서 같은 명령을 fallback으로 실행한다. Playwright 설정은 backend `127.0.0.1:18080`, frontend `127.0.0.1:13100`을 자동 기동하고 테스트 DB를 매 테스트마다 재시드하며, E2E backend는 `APP_ENV=e2e`로 무인증 동작한다.

## 주요 결정 사항 (ADR Index)

- **ADR-1**: Next.js (React) 기반의 프론트엔드 및 App Router 채택
- **ADR-2**: FastAPI 및 SQLAlchemy 2.0 백엔드 스택 선정 (DB 세부는 ADR-12로 보강)
- **ADR-3**: Gemini API를 이용한 YouTube 검색어 세분화 및 여행지 정보 지능형 요약
- **ADR-4**: VWorld 지도 시뮬레이션 및 로컬 `.env` 테스트 (T-013 기준 `maplibre-gl` 직접 WMTS 구성으로 보정)
- **ADR-5**: YouTube API의 엄격한 할당량 극복을 위한 스크래핑 우회 및 DB 캐싱 전략 (ADR-11로 대체)
- **ADR-6**: Windows 로컬 개발 환경 전용 Playwright E2E 검증 절차 확립
- **ADR-7**: MCP 서버를 읽기/쓰기 UX로 채택
- **ADR-8**: Kakao/Naver/VWorld 지오코딩 공급자 전략 및 `kraddr-geo` 제외
- **ADR-9**: `yt-dlp`, 자막 폴백, 작업 상태 추적 기반 ETL 복원력 보강
- **ADR-10**: SQLite3 우선 구현과 PostGIS 전환 유보 (ADR-12로 대체)
- **ADR-11**: 소형 프로젝트 기준 공식 YouTube Data API 우선
- **ADR-12**: SQLite + SpatiaLite 임베디드 공간 DB 채택
- **ADR-13**: 전면 asyncio와 APScheduler 단일 실행자 채택
- **ADR-14**: React Hook Form, Zod, shadcn/ui, Tailwind CSS, TanStack Query 프론트 스택 채택
- **ADR-15**: RustFS 기반 원본 미디어 저장과 무기한 보존
- **ADR-16**: 장소 매칭 검수 UX와 Gemini 설명 보정 필드 분리
- **ADR-17**: 공간 컬럼은 ORM 밖 SpatiaLite DDL로 관리하고 저장소 계층에 캡슐화
- **ADR-18**: 단일 호스트 Docker Compose 실행 계약
- **ADR-19**: VWorld 우선 지오코딩과 `python-vworld-api` 직접 사용
- **ADR-20**: 고도화 후보 도입 보류와 전환 트리거
- **ADR-21**: Next.js 16 / React 19 업그레이드와 ESLint flat config 전환
- **ADR-22**: 장소 언급 소스 집계와 export 계약
- **ADR-23**: Windows 네이티브 실행 배제와 Linux Docker/WSL 전용 실행 모델 (ADR-33에서 개발 명령 Linux 전용과 Playwright n150 우선으로 보강)
- **ADR-24**: REST API 버저닝(`/api/v1`)과 외부 호출용 API 인증(인증 코드, `X-API-Key`)
- **ADR-25**: PostgreSQL/PostGIS 전환과 `python-kraddr-geo` DB 서버 재사용
- **ADR-26**: YouTube 장소 후보를 범용 feature 공급원으로 노출
- **ADR-27**: 포트 대역을 통합 `kor-travel-docker-manager` 정책(126xx: API 12601 / MCP 12602 / Web 12605)으로 정렬 (ADR-18/ADR-23 포트 값 대체)
- **ADR-28**: 프로덕션 공개 도메인 노출(리버스 프록시 + TLS)과 도메인 비밀 유지 (앱 코드 변경 없이 env + Caddy; `s3-api`=공개 객체/`s3`=콘솔; 실제 도메인은 `.env`에만)
- **ADR-29**: `kor-travel-geo` UI 지침(StyleSeed) 채택과 Tailwind v4 전환 (단일 accent brand·semantic 토큰·44px·uppercase label, ADR-14 보강)
- **ADR-30**: AI 엔진 다중 provider(Gemini/DeepSeek) + 사전 프롬프트 + JSON + 느린 재시도 (DeepSeek OpenAI 호환, `ai_preprompt`, `LLM_RETRY_*`, 한국어 에러 복구 UI, ADR-3/ADR-9 확장)
- **ADR-33**: 개발 명령 Linux 전용과 Playwright n150 우선 실행 정책
- **ADR-34**: 유지보수 UI 공용 컴포넌트·확인 다이얼로그·필드 도움말 규약 (Base UI 프리미티브 단일 계열, Checkbox=폼 값/Switch=즉시 적용, 파괴적 액션은 `ConfirmActionButton`, 대시보드 조각은 `components/panels.tsx` 단일 출처, 긴 설명은 `HelpTip`, ADR-29 보강)
- **ADR-35**: 테마 중심 POI 공급 API (`/api/v1/themes`·`/themes/places`·`/themes/video/{id}/places`, 동영상 테마는 매치/검수완료 POI ≥5 게이트, 결과 보기 출처 필터 재사용, ADR-24/ADR-26 확장)

핵심 ADR은 `docs/decisions.md` 본문에 그대로 두고, 대체·보류·이력 ADR(ADR-4·5·6·8·9·10·12·14·17·20·21, 번호 오기 ADR-27 배포명)은 같은 문서 말미 `이력·대체·보류 ADR (요약)` 섹션에 한 줄 요약으로 보존한다.

상세는 `docs/decisions.md`를 참고한다.

## 작업 후 의무사항

1. `docs/journal.md`에 작업 내용 추가 (역시간순)
2. `docs/tasks.md`의 현재 작업 진행 사항 업데이트
3. 추가 의사결정이 필요하거나 발생한 경우 `docs/decisions.md`에 ADR 문서 업데이트
4. PR 생성 및 머지 흐름 준수
