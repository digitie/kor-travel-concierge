# JOURNAL — 작업 일지

본 문서는 `kor-travel-concierge` 프로젝트의 작업 진행 역사를 역시간순으로 기록한다.

---

## 2026-06-24: T-119 — 공개 도메인 로그인 403(INVALID_ORIGIN) 수정 — 신뢰 origin 화이트리스트

라이브 브라우저 E2E(prod n150, 공개 도메인 `concierge.digitie.mywire.org`)에서 관리자 **로그인 POST가 403 INVALID_ORIGIN**으로 막히는 버그를 발견했다(curl/LAN-http smoke로는 안 잡힘). 원인: T-116의 same-origin(CSRF) 검사 + 운영 TLS 종단 프록시(라우터 `192.168.1.1`의 **HAProxy**)가 `X-Forwarded-Proto: https`를 주입하지 않아 `requestOrigin`이 `http://…`로 재구성돼 브라우저의 `https://…` Origin과 불일치. LAN(`http://192.168.1.14:12605`) 접속은 정상.

라우터 직접 수정이 막혀(SSH 자격 불일치) **앱 측 보완**으로 해결:
- `auth.ts` `requestHasSameOrigin`에 신뢰 공개 origin 화이트리스트(`KTC_UI_PUBLIC_ORIGINS`) 추가. 헤더 재구성 origin과 불일치해도 브라우저 Origin이 명시 화이트리스트와 일치하면 허용한다(화이트리스트 대조이므로 CSRF 방어 유지). 미설정 시 기존 헤더 기반 검사 유지.
- prod `~/kor-travel-concierge/.env`에 `KTC_UI_PUBLIC_ORIGINS=https://concierge.digitie.mywire.org` 설정.

정석 인프라 수정(HAProxy concierge 백엔드에 `http-request set-header X-Forwarded-Proto https`)도 별도 권장 — 적용 시 화이트리스트는 무해한 이중 안전망이 된다.

검증: frontend vitest 15/15(origin 5건 추가)·type-check·lint·build. prod 배포 후 로그인 POST 403→401, 실제 브라우저 로그인 검증.

## 2026-06-24: T-118 — 형제 프로젝트 docker-manager PR #37/#38 보안 수정 concierge 이식

`kor-travel-docker-manager`의 관리자 인증 사후 리뷰 fix-forward(PR #37/#38, 이미 머지)에서 concierge에도 해당하는 보안 수정을 이식했다.

- **AUTH-5 (username 열거 타이밍)**: `verifyAdminLogin`이 사용자명 불일치 시 즉시 반환해 PBKDF2를 건너뛰던 것을, 항상 PBKDF2를 수행하고 사용자명도 상수시간 비교하도록 변경(응답시간이 사용자명 일치 여부에 의존하지 않게 함). #124 리뷰가 놓친 항목.
- **AUTH-1 (감사 로그 무한 적재)**: `login_events`에 보존 상한 `LOGIN_AUDIT_MAX_ROWS`(기본 5000)를 추가하고 record 시 초과분(오래된 행)을 정리. 로그아웃·오설정 등 미인증 경로 감사로 인한 무제한 증식 방지.
- **AUTH-4 (CORS)**: `cors_allow_origins`에서 stray `*`를 제거(`allow_credentials=True`와 일관).
- **APIKEY 주석**: 고엔트로피 키에 대한 의도적 fast unsalted SHA-256 설명 추가.
- **FE-5/FE-6**: 로그인 비밀번호 autofocus, 생성된 공개 키 "지우기" 컨트롤(화면 노출 단축).

이미 적용/무관: deprecated `datetime.utcnow`(concierge는 `now(timezone.utc)` 사용), 캐시 TTL 파싱(pydantic int), 모달 a11y(shadcn Dialog), `key_hint` 폭(미관·마이그레이션 필요). **분리(후속)**: durable rate-limit(#38)은 concierge의 Next(TS) 로그인 경로에 백엔드 왕복+백엔드 테스트가 필요하고 단일 인스턴스 운영에선 인메모리로 충분; trusted-proxy-secret(#38)은 concierge admin이 이미 `KTC_ADMIN_PROXY_SECRET`을 요구하므로 대체로 커버됨.

검증: frontend type-check/lint/build/vitest(10/10), backend compileall + `test_api_auth.py`에 감사 retention 테스트 추가(backend pytest는 WSL/CI). prod 배포 후 smoke 검증.

## 2026-06-24: T-117 — PR #124(T-116) 인증 기능 사후 보안 리뷰 + High/Medium 보강 (prod 배포·검증 완료)

PR #124(관리자 로그인·공개 API 키)는 이미 squash 머지(`3fa933c`)되어 운영 배포된 상태였다. 다중 에이전트 사후 보안 리뷰(원시 32→반박 검증 후 확정 26: High 1/Medium 5/Low 16/Nit 4)를 PR에 코멘트로 남기고, High·Medium을 코드로 보강했다.

- **High — XFF 스푸핑 가능한 CIDR 신뢰**(`security.py`): 운영 `FORWARDED_ALLOW_IPS=*`에서 uvicorn이 `request.client.host`를 X-Forwarded-For로 덮어써 `_peer_in_cidrs` 신뢰가 위조 가능. 키 없는 `API_TRUSTED_CLIENT_CIDRS` 우회를 새 플래그 `API_TRUSTED_CLIENT_BYPASS_ENABLED`(기본 false) 뒤로 게이트하고, 기동 시 위험 구성 경고(`main.py`)를 추가. admin 게이트의 실질 보호는 shared secret임을 코드 주석/`.env.example`에 명시하고 `FORWARDED_ALLOW_IPS`를 실제 프록시 IP로 고정하라는 가이드를 추가. (정의적 운영 조치=프록시 IP 고정은 prod `.env`에서 적용 필요.)
- **Medium — `init_db` create_all ↔ Alembic 충돌**(`database.py`): 비-local에서 create_all을 건너뛰고 운영 schema는 Alembic이 단독 소유하도록 게이트(비멱등 마이그레이션 "relation already exists" 충돌 제거).
- **Medium — `?key=` 쿼리 키 누출**: 기능은 유지(VWorld 호환), `.env.example`에 로그·Referer 누출 위험 + 프록시 로그 마스킹·키 회전 가이드 추가.
- **Medium — LoginForm 네트워크 오류 무시**: `catch`로 사용자 오류 메시지 노출.
- **Medium — 로그인 rate-limit 전역 `local` 버킷**: 버킷 키를 (신뢰 client IP)+계정으로 분리해 단일 출처가 관리자를 전역 잠그는 DoS를 완화.
- **Medium — 프런트 인증 테스트 0건**: vitest 도입 + `auth.ts` 단위 테스트 10건(세션 서명/검증·만료·계정 불일치, `sanitizeLocalPath` open-redirect, `verifyAdminLogin`, rate-limit). backend `test_api_auth.py`에 폐기 키 거부·deny-all·CIDR 밖 admin 거부·우회 플래그 음성 테스트 추가.

검증: frontend type-check/lint/build + vitest 10/10 + `npm audit` 0, backend compileall. backend pytest는 Windows 호스트 venv 미가용으로 WSL2/Docker 환경에서 수행 필요. **운영 검증/배포는 prod SSH 접근 확보 후 진행 예정**(현재 리뷰어가 `digitie@192.168.1.14` 접근 불가).

## 2026-06-23: T-116 완료 — 관리자 로그인·공개 API 키 관리와 PR #399 후속 리뷰 반영

사용자 요청: `kor-travel-geo` PR #399의 로그인/API 키 UX를 참고해 concierge에도 관리자 로그인, 보안 세션, 로그인 감사 로그, Web UI 기반 공개 API 키 생성·저장·검증, 관리자 API BFF 제한, `kor travel geo v2` 키 설정을 추가.

- **관리자 로그인**: `/login` 화면 + `/api/auth/login|logout`. 단일 계정 기본 아이디는 `admin`, 초기 비밀번호는 PBKDF2-SHA256 해시(`KTC_ADMIN_PASSWORD_HASH`)로 gitignore된 `.env`에만 저장. 세션은 httpOnly `SameSite=Strict` HMAC 쿠키, 8시간 TTL, user-agent fingerprint, 서버측 폐기 Map, Origin 검증, JSON-only 요청, 실패 rate-limit(5회/10분).
- **로그인 감사**: `login_events` 테이블과 관리자 API(`POST /admin/auth-events`, `GET /admin/login-events`)를 추가. 로그인 시도·성공·실패·거부·로그아웃, 사용자명, 사유, user-agent, next path, 신뢰 가능한 경우 client_ip를 저장하고 설정 모달에서 조회.
- **공개 API 키**: `public_api_keys` 테이블 + Alembic `20260623_0010`. UI에서 VWorld 호환 32자 영문/숫자 key를 랜덤 생성하고, 평문은 1회만 보여 주며 DB에는 SHA-256 hash와 끝 6자리 hint만 저장. 활성 hash는 `PUBLIC_API_KEY_CACHE_TTL_SECONDS` 동안 프로세스 메모리에 캐시하고 생성·폐기 시 즉시 무효화. 외부 API는 `X-API-Key` 또는 `?key=`를 검증하고, 명시 CIDR(`API_TRUSTED_CLIENT_CIDRS`)은 key 검증을 생략할 수 있음.
- **관리자 API 제한**: Next BFF가 유효 세션을 확인한 뒤 `X-KTC-Actor`와 서버 전용 `KTC_ADMIN_PROXY_SECRET`을 백엔드에 주입한다. 백엔드는 trusted proxy peer CIDR과 shared secret을 모두 만족한 요청만 `/api/v1/admin/*`에 허용한다. 브라우저가 보낸 `x-api-key`/관리자 헤더는 BFF에서 전달하지 않는다.
- **kor-travel-geo v2 키**: 설정 키 `kor_travel_geo_v2_api_key`와 env `KOR_TRAVEL_GEO_V2_API_KEY`를 추가. 값이 비어 있으면 코드에서 `VWORLD_SERVICE_KEY`와 동일하게 사용하고, 현재 `.env`에도 같은 값으로 맞춤.
- **PR #399 후속 리뷰 반영**: 최신 코멘트(2026-06-23 23:22 KST) 기준으로 검증되지 않은 `X-Forwarded-For`는 기본 미신뢰(`KTC_UI_TRUST_FORWARDED_IPS=false`), admin proxy secret 403/403/200 테스트 추가, 프런트 API 401 시 `/login?next=...` 리다이렉트, 로그인 오류 `role=alert`/`aria-live`/`aria-describedby`/`aria-invalid` 적용.

검증: backend compileall, backend auth/settings pytest(테스트 DB 미설정 항목 skip), frontend type-check/lint/build. 운영 호스트에 rsync 배포 후 docker-manager prod override에 UI env_file을 보강하고 API/MCP/scheduler/UI를 재빌드·재시작했다. 운영 smoke: API health 200, 무키 공개 API 401, admin API 무proxy 403, 로그인 페이지 200, 루트 로그인 redirect 307, 틀린 로그인 401. Windows Playwright E2E는 로그인 흐름을 포함하도록 하니스를 보강해 4/4 통과.

## 2026-06-23: T-115 — 은퇴된 Gemini 1.5 옵션 제거 + AI 엔진 DeepSeek v4-pro 전환

라이브 테스트 중 발견: `gemini-1.5-flash`/`gemini-1.5-pro`는 Google이 API에서 은퇴시켜 **404**(model not found)를 반환한다(`gemini-2.5-flash`는 키 쿼터 429). 사용자가 드롭다운에서 선택하면 작업이 실패하므로 `config.GEMINI_ENGINE_OPTIONS`에서 두 모델을 제거(남은 Gemini: 2.5-flash·2.0-flash·flash-latest). 관련 테스트(`test_settings_and_audit`·`test_api`·`test_scheduler_worker`·e2e `ktc.spec.ts`)의 1.5 참조를 `gemini-2.0-flash`/`gemini-flash-latest`로 교체.

**AI 엔진 전환**: dev/prod 모두 `deepseek-v4-pro`로 변경(DB 설정). DeepSeek는 별도 API/쿼터라 Gemini 쿼터·은퇴 문제를 우회한다. 직접 스모크로 검증: 자막 교정(complete_text)→`PONG`, POI 배치(complete_json/JSON 모드)→`부산 감천문화마을` 정상 추출. DeepSeek는 Gemini rate limiter를 거치지 않는다(별도 쿼터). 라이브 poi_batch(2969/2970)가 0 교정 실패로 진행.

검증: backend 282 pytest+compileall. dev/prod 배포.

## 2026-06-23: T-114 — 쓰레기 데이터 정리(dev/prod) + 남은 배치(#5/#7/#9)

T-113 후속. **데이터 정리**: 보수적 분류기(행정구역명·F코드·앱/브랜드·일반명사·"불확실/어딘가" 패턴; 정상 영문 POI[Coex Mall/Starfield Library 등]는 보존)로 dry-run 검증 후 FK-safe 트랜잭션 삭제. dev 장소 79→71·후보 229→197, prod 장소·후보 14건 삭제(사용자 확정). **남은 배치 3건**:
- **#5** 키워드 harvest 쿼터 낭비: 증분(watermark) 수집에서 시드(첫 검색어)가 신규 0건이면 파생 검색어 `search.list`(각 100 units)를 조기 종료.
- **#7** 확정 시 좌표 중복: `resolve_candidate` create_place에서 `find_duplicate_candidates`로 근접 기존 장소가 있으면 신규 생성 대신 그 장소에 매핑(동일 좌표 무한 중복 방지). (검수 'match_existing' UI는 후속.)
- **#9** discovered 백로그 자동 재처리: `source_scan_handler`가 대기/실행 중 poi_batch가 없을 때 DISCOVERED 영상(≤50)을 poi_batch로 재투입.

남은 LOW: #12 export 좌표 None 방어(NOT NULL로 비도달), #14 category 정규화, #7 검수 match_existing UI. 검증: backend 282 pytest+compileall. dev/prod 배포.

## 2026-06-23: T-113 — "대구 맛집" 라이브 e2e 전수 점검 후 데이터 품질·검수·파이프라인 버그 일괄 수정

다영역 병렬 감사(파이프라인/검수/결과/지오코딩 + 적대 재검증)로 14건 확인, 그중 고영향 7건 수정:
- **#1 timestamp 컬럼 미적용 migration**: dev/prod DB의 `extracted_place_candidates`/`video_place_mappings` `timestamp_start/end`가 `varchar(16)`로 남아(20260620_0007 미적용) 16자 초과 timestamp가 `StringDataRightTruncationError`+세션 롤백 캐스케이드. → 양 DB `ALTER ... TYPE varchar(64)`.
- **#2 지오코딩 echo 자동확정**(쓰레기 POI 1차 원인): VWorld get_coord가 정제 주소 없이 질의를 임의 좌표에 snap하고 입력을 echo만 한 단일 결과를 `evaluate_geocode`가 confidence 1.0으로 자동 확정. → `GeocodeCandidate.refined` 플래그, count==1+`refined=False`면 `needs_review`(우버/GS25/대한민국 비-POI 자동확정 차단) + 회귀 테스트.
- **#4 비-POI 추출**: `batch_poi` 시스템 프롬프트에 브랜드·체인·앱·국가 단독·일반명사 제외 지시 추가.
- **#6 검수 페이지 크래시**: 좌표 없는 provider 결과에서 `hit.latitude.toFixed` null 크래시 → `PlaceSearchHit` 좌표 `number|null`, 없으면 "좌표 없음(선택 불가)"+비활성, `mapPlaces`/`hitPlace` null 필터.
- **#8 보류 은폐**: quota_deferred poi_batch가 "완료"로 마감 → `mark_done` final_message/level + 워커가 보류 시 "일일 쿼터로 POI 추출을 보류했습니다(추후 재처리)"+warning.
- **#10 검수 큐 100건 캡**: 144 중 100만 노출+배지 오류 → `/destinations/unmatched` limit(기본 500, ≤2000)+서비스 기본 500.
- **#11 후보 삭제 차단**: `feature_exports` FK가 미확정 후보 삭제까지 막음 → 삭제 전 해당 후보 export ledger 정리, 확정 장소 연결만 409.

검증: backend 282 pytest+compileall, frontend tsc/lint/build, dev 라이브 점검. dev/prod 배포.

**남은 항목**: #5 키워드 harvest 400 쿼터 낭비, #7 좌표 dedup+match_existing UI, #9 discovered 백로그 자동 재처리, #12 export None 방어(LOW), #14 category 정규화(LOW). **운영 블로커**: Gemini 키 gemini-2.5-flash 쿼터 소진(429) → 쿼터 전까지 신규 POI 미생성(코드 정상).

## 2026-06-23: T-112 완료 — poi_batch "알 수 없는 asset_type" 실패 수정 + 작업 로그·오류 상세 다이얼로그(복사)

사용자 보고: "대구 맛집" 검색 중 "작업이 실패했습니다: 알 수 없는 asset_type:.,". 로그가 잘리고 실패.
- **근본 원인(T-109 회귀)**: `AssetType.TRANSCRIPT_CORRECTED`를 enum에만 추가하고 `media_store._BUCKET_BY_ASSET_TYPE` 매핑을 빠뜨려, poi_batch가 교정본을 저장할 때 `bucket_for`가 `ValueError("알 수 없는 asset_type: transcript_corrected")`로 실패 → 모든 poi_batch 작업 실패. **prod도 동일하게 깨져 있었음.** → 매핑 추가(교정본=자막 버킷), 모든 `AssetType`이 버킷에 매핑되는지 검증하는 회귀 테스트 추가(`test_etl_media_store`).
- **로그 잘림**: DB는 `Text`(무손실)지만 프런트 `StatusRow`가 CSS `truncate`로 잘라 표시. error 행을 `wrap`으로 바꿔 인라인에서도 안 잘리게.
- **로그·오류 상세 + 복사**: 공용 `JobLogDialog`/`JobLogView` 추가 — 상태·현재 메시지·오류 전문(pre-wrap, 스크롤)·전체 상태 로그 타임라인 + **"전체 복사"** 버튼(`buildJobReport`로 job_id·상태·오류·로그 포맷). 수집 패널(HarvestConsole) "작업 상태"에 **"오류·로그 상세"** 버튼, 작업 상세(JobDetailDialog)에 "상태 로그·오류" 섹션으로 연결. 복붙해 바로 공유·수정 가능.

검증: backend 281 pytest+compileall, frontend tsc/lint/build. dev/prod 배포(asset_type는 prod 긴급 수정).

## 2026-06-23: T-111 완료 — 수집 키워드 보정 멈춤 해소 + 수집 상태/로그 페이지 이동 보존

사용자 보고 2건:
1. **"Gemini에서 검색어 보정 중"에서 한참 멈춤** — `pipeline.py`의 키워드 보정 단계가 동기 Gemini 호출(`keyword_expansion.complete_json`)을 `await` 없이 실행해 워커 이벤트 루프를 막았고, 429 키에서 느린 재시도(15→90s×4)로 ~90s 동안 상태/heartbeat가 멈춤. → (a) `complete_json(max_attempts=1)`로 429 즉시 템플릿 폴백, (b) `asyncio.to_thread`로 보정 호출을 offload해 루프 비차단, (c) "YouTube에서 검색어 N개로 영상을 검색 중" 중간 상태 추가. 이후 기존 상세 메시지(보정 결과→조회→적재→POI 배치 N건 등록)가 정상 흐름.
2. **페이지 이동 후 수집 로그/상태 소실** — `HarvestConsole`의 `jobId`가 `useState`라 /collect 언마운트 시 소실. → 작업 id를 `localStorage`에 보존(마운트 복원→statusQuery가 백엔드에서 상태·로그 재조회), 새 수집 시작 시 직전 자막 작업 id 정리. 복원 effect는 hydration 안전 위해 `set-state-in-effect` 1곳 허용.

검증: backend 279 pytest+compileall, frontend tsc/lint/build. 앱 dev/prod 배포.

## 2026-06-23: T-110 완료 — Playwright E2E 스펙을 멀티페이지 UI에 맞게 갱신

T-097+ UI 개편(결과/수집/검수 페이지 분리, 설정 모달·페이지, 장소 상세 모달, Deep Research 상세 이동) 이후 갱신 안 됐던 `tests/e2e/ktc.spec.ts` 4개를 현행 UI에 맞게 재작성:
- 결과(/): `장소 목록` region + 지도(`#vworld-map-container` fallback) + 간단 실행 큐 + 헤더 nav(수집/검수). (검수·운영 패널은 별도 페이지/모달로 이동했으므로 제외)
- 수집(/collect): `#harvest-target`/`#harvest-max-videos`/수집 시작 + `aria-live` 상태 패널의 job_id·pending.
- Deep Research는 결과 장소 **상세 모달**(`월정리 해변 상세` ⓘ → dialog → Deep Research, T-107), 검수 저장은 `/review`에서 확정 장소명/위도/경도/카테고리(라벨 변경) 입력 후 저장 → unmatched 0.
- 설정(/settings): 엔진 셀렉터 id `#gemini-engine-select`→`#ai-engine-select`, `gemini-1.5-pro` 선택 후 저장 → `#success-toast` + 설정 반영.
- 결과: Windows 호스트 Playwright **4/4 통과**(KTC_TEST_PG_DSN 시드). 셀렉터 strict-mode(행 버튼 vs ⓘ)·nav 링크는 `.first()`·`header nav` 텍스트로 보정. (앱 코드 변경 없음)

## 2026-06-22: T-109 완료 — 자막 교정 + 10개 묶음 POI 배치 파이프라인 + Gemini 키 전역 rate limiter

사용자 요청 8항 반영. POI 처리를 영상당 1콜에서 **영상 단위 자막 교정 + 묶음(≤10) POI 배치**로 재설계.
- **모델**: 기본 `gemini-2.5-flash`. rate limit `GEMINI_RATE_RPM=10`·`RPD=1500`·`TPM=250000`(키 전역).
- **dispatch**: `llm_client.complete_text`(평문) + `build_gemini_body`/`complete_json`에 `systemInstruction`·`temperature` 추가. `deepseek_client`에 system 메시지·temperature. Gemini/DeepSeek 모두 지원.
- **rate limiter**(`gemini_rate_limiter`+`GeminiRateState` 단일행): API·scheduler 두 프로세스 공유, `FOR UPDATE`로 직렬화. 분 윈도우(RPM/TPM)·PT 자정 일일(RPD). **병렬 없음(순차)**. Gemini 콜만 대상(DeepSeek 별도 쿼터). Gemini 콜 전 `acquire`로 슬롯 예약.
- **자막 교정**(`transcript_correction`, 영상 단위): `config.TRANSCRIPT_CORRECTION_SYSTEM_INSTRUCTION`(영상 설명을 표기 근거로 활용하는 5항 포함) + temp 0.1, 평문. raw는 `TRANSCRIPT`, 교정본은 신규 `TRANSCRIPT_CORRECTED` 에셋으로 RustFS 저장.
- **POI 배치**(`batch_poi`): 교정본 ≤10개를 `<video_transcripts>` XML로 묶어 1콜. system에 추출 규칙+교차참조 금지+카테고리 마스터(8자리 코드표). `response_schema=BatchPOIResult`(video_id·official_name·location_hint·category_code·timestamp·speaker_note). 결과는 입력 alias로 역매핑·검증(미존재 alias·미지 코드 폐기 → 환각/교차오염 차단). 긴 영상은 토큰 예산(`POI_BATCH_TOKEN_BUDGET`)으로 sub-batch 분할.
- **오케스트레이션**(`batch_poi_service.process_video_batch`): 교정→저장→배치 추출→영상별 `needs_review` 후보 생성(카테고리 8자리 코드는 evidence에 그대로, 변경 금지)→지오코딩(`postprocess_service.geocode_candidates` 재사용).
- **job 모델**: harvest/transcript가 신규 `poi_batch` 작업으로 분리 enqueue(≤`POI_BATCH_MAX_VIDEOS`개/job, 15→[10,5]). worker `poi_batch_handler`. 자동(harvest 후) + 수동(`POST /jobs/poi-batch`, discovered 영상). **개별 영상 트리거 없음(job 단위)**. UI에 "미처리 영상 POI 추출" 버튼 + `poi_batch` 작업 목록 노출(라벨).
- **검증**: backend 279 pytest + compileall, frontend tsc/lint/build, 적대적 리뷰, dev live smoke, Windows Playwright e2e. dev/prod 배포.

## 2026-06-22: T-108 완료 — Gemini 호출 절감(A안): 8자리 카테고리 코드를 POI 추출 콜에 통합

사용자 요청(호출 횟수·프롬프트 최적화). 기존엔 **확정 장소마다** `category_suggestion`이 144개 코드표 전체를 매번 보내며 별도 Gemini 호출(영상당 N콜). A안으로 이를 **영상당 POI 추출 1콜에 통합**:
- `poi_extraction`: `ExtractedPOI`/`RESPONSE_JSON_SCHEMA`에 `category_code` 추가, `build_prompt`에 `category_catalog.prompt_catalog()`(코드표)를 **한 번** 포함, `parse_extraction`이 `category_catalog.normalize_code`로 유효 코드만 통과(미상·미분류·미존재→None).
- `summarize_service`: 추출한 코드를 후보 `provider_evidence_json["transcript"]["category_code"]`에 저장.
- 확정 경로(`place_service.resolve_candidate`·`geocode_service.apply_geocode_to_candidate`): 후보 evidence의 코드를 **복사**(`place_service.candidate_category_code`). **별도 Gemini 호출 제거** — `category_code_selector`/`category_code_llm` 파라미터, `_UNSET`, to_thread Gemini 호출, 관련 import(routes·mcp 포함) 정리.
- 효과: 확정 장소당 Gemini 호출 **N→0**, 코드표 전송 **N회→영상당 1회**. 단발 카테고리 호출의 이벤트 루프 블로킹(T-105) 원인도 함께 소멸.
- 검증: 신규 단위 테스트(코드 파싱·카탈로그 검증·prompt 코드표 포함·확정 시 evidence 복사·코드 없으면 None) + 영향 테스트 전체 통과(backend 276 pytest), compileall. 적대적 리뷰로 end-to-end 체인·하위호환·dead code 점검. `category_suggestion` 모듈은 자동 경로에서 미사용(향후 재제안 기능용으로 보존).

## 2026-06-22: T-107 완료 — 결과 화면 선택-장소 하단 패널 제거(중복 표시 해소) + Deep Research 이동

사용자 보고: "UI에서 해동용궁사만 또 나온다". 진단: **데이터 중복 아님**(해동용궁사는 `place_id` 하나뿐, 검수 큐·근접 중복 없음). 원인은 `DestinationWorkspace`가 목록(언급 많은 순 → 해동용궁사 1번) 아래에 **현재 선택 장소 상세 패널**(좌표·언급 소스·Deep Research)을 두고, 선택값이 없으면 `places[0]`을 기본 선택해서 같은 장소가 목록+패널에 동시 표시된 것. 사용자가 "패널 제거" 선택.
- `DestinationWorkspace`의 하단 선택-장소 패널 제거(+ 관련 props·`deepResearchMutation`·미사용 import 정리). 지도 연동용 `selectedPlace` 상태는 유지.
- 패널에 있던 **Deep Research** 버튼을 `PlaceDetailView`(상세 모달, 삭제 버튼 옆)로 이동 — 장소별 작업을 상세에 모음. 상세는 각 항목 ⓘ로 연다.
- 검증: tsc/lint(0 warning)/build, 13200 라이브(하단 패널 제거 확인, 상세 모달에 Deep Research+삭제 확인). dev/prod 배포.

## 2026-06-22: T-106 완료 — 확정 장소(정리된 리스트) 삭제 기능

사용자 요청: "정리된 리스트에서도 삭제할 수 있게". 검수 큐 후보만 삭제 가능하던 것을 **확정 장소(travel_places)** 삭제로 확장.
- **백엔드**: `place_service.delete_place` — `travel_places`를 참조하는 FK 3개(모두 `NO ACTION`)를 명시적으로 정리한다: 이 장소를 매칭한 후보는 `needs_review`+`feature_export_status=pending`으로 되돌려 검수 큐로(데이터 보존), 영상-장소 매핑은 삭제, 미디어 자산은 링크만 해제(미디어 보존). `DELETE /api/v1/destinations/{place_id}` 엔드포인트가 서비스 호출 후 `sync_feature_exports(commit=False)`로 이미 내보낸 feature를 **tombstone**으로 전환하고, `audit_service.record`로 단일 커밋(원자적). 되돌린 후보 수를 반환.
- **프런트**: `PlaceDetailView`에 "장소 삭제" 버튼 + 2단계 확인("정말 삭제할까요? 이 장소를 만든 검수 후보는 검수 큐로 되돌아갑니다") + `deletePlace` API. PC 모달은 닫고 모바일 `/place/[id]`는 결과로 이동, `["destinations"]`/`["unmatched-candidates"]` invalidate + stale `["place-detail"]` 제거.
- **검증**: 신규 단위 테스트 2건(되돌림·미디어 unlink·매핑 삭제, 미존재 404) + 적대적 데이터 정합성 리뷰(고아 참조·라우트 충돌·트랜잭션 원자성·원장 tombstone·엣지 — 중대 이슈 없음) + dev 라이브: place 1 삭제 시 장소·매핑 제거, 후보 `matched→needs_review`(검수 큐 복귀), 원장 `upsert→tombstone` 확인. UI: 삭제 버튼·확인 흐름 확인. compileall·pytest·tsc/lint/build 통과. dev/prod 배포.

## 2026-06-22: T-105 완료 — 검수 저장 시 동기 Gemini 호출이 이벤트 루프를 막던 먹통 수정

**버그(사용자 보고)**: "처음 한 번 검수(저장) 후 리스트 상세·API 검색이 둘 다 먹통, 시간이 좀 지나면 다시 동작".
**진단**: `resolve_candidate`의 `create_place` 경로가 8자리 카테고리 제안(T-070)을 위해 `category_code_selector(...)`를 **동기로 호출**(place_service.py)한다. selector는 동기 Gemini(`complete_json`) 호출이고, dev/prod Gemini 키가 429라 느린 사람-유사 재시도(15→90s)가 **async 이벤트 루프 안에서 동기로 실행**되며 그동안 모든 다른 요청(상세·검색)이 멈춘다 → 재시도가 끝나면(=시간이 지나면) 다시 동작. harvest의 `geocode_service`도 같은 동기 호출로 worker 루프를 막는다.
**수정**:
- `category_suggestion.make_llm`: `complete_json(..., max_attempts=1)`로 단발 호출(429 시 ~1s 실패). 카테고리 제안은 best-effort(null 허용)라 느린 재시도가 불필요.
- `place_service.resolve_candidate`·`geocode_service`: selector 호출을 `await asyncio.to_thread(...)` + `asyncio.wait_for(timeout=10s)`로 격리 → 이벤트 루프를 막지 않고, 초과·실패는 None으로 흡수.
**검증**: compileall + 영향 테스트 53 통과. dev(키 429)에서 저장 중 동시 검색/상세가 막히지 않음을 라이브 확인. dev/prod 배포.

## 2026-06-22: T-104 완료 — 검수 페이지 UX 4건 (저장 즉시 제거·후보전환 가드·검색 재요청)

사용자 보고 4건:
1. **저장/제외 시 검수 대기 목록에서 즉시 제거**: `resolveMutation`에 낙관적 제거(`onMutate`로 cache에서 후보 필터 + `cancelQueries`로 자동 refetch 덮어쓰기 방지, `onError` 복구, `onSettled` 동기화) 추가. 라이브 검증: 제외 클릭 180ms 내 후보 사라짐(refetch 전), resolve 200, settle 후에도 유지. (백엔드는 이미 resolve 시 `IGNORED`/`USER_CORRECTED`로 바꿔 `NEEDS_REVIEW`만 보는 unmatched에서 제외 — 기존엔 느린 refetch가 체감 지연이었음.)
2. **검수 상세가 안 나옴**: 상세 엔드포인트·모달(PC)·페이지(모바일)는 dev/prod 모두 정상 동작(200, 콘텐츠 렌더 확인). 재현 불가 — 커넥션 포화(아래 4, T-103) 증상으로 추정. BFF abort 수정 + 검색 가드로 완화. 잔존 시 재확인 필요.
3. **검색 중 다른 후보 클릭 시 가드 없음**: `pickCandidate`가 진행 중 `place-search`/`place-opinion`을 `cancelQueries`로 취소하고 nonce를 올려 새 후보 검색을 깨끗이 시작(이전 검색이 새 후보에 매달리지 않음).
4. **검색 버튼 무반응/지연**: `searchQuery`/`opinionQuery` queryKey에 `searchNonce`를 추가하고 `runSearch`/`pickCandidate`마다 증가 → 동일 검색어로도 항상 강제 refetch. 라이브 검증: 같은 검색어로 검색 3회 클릭 → 3회 모두 재요청(기존엔 0회 → 무반응). (네트워크 지연은 T-103 BFF abort 수정으로 별도 해소.)

검증: frontend tsc/lint/build, dev 라이브(#1·#4). dev/prod web 재빌드 배포.

## 2026-06-22: T-103 완료 — BFF 프록시 abort 미전파로 인한 POI 검색 지연/무응답 수정

**버그(사용자 보고)**: 검수 POI 검색이 "처음 한번 빼고는 늦거나 응답이 없음", "검색 중지 후 재호출해도 느림".
**진단**: 백엔드/BFF 직접 연속 호출은 0.3~0.7s로 빠르고, dev `npx next dev`에서는 재현 안 됨. 그러나 **prod 백엔드 로그에서, 브라우저가 중단(abort)시킨 40개 place-search 요청이 전부 백엔드에 도달해 200으로 완료**됨을 확인 → BFF 프록시(`frontend/src/app/api/v1/[...path]/route.ts`)가 `request.signal`을 upstream `fetch`에 전달하지 않는 게 원인. 후보 전환·검색 중지로 react-query가 요청을 취소해도 BFF는 백엔드 작업을 계속하고 응답 스트림을 비우지 않아 **undici 커넥션이 누수**된다. 빠른 전환/중지가 쌓이면 커넥션 풀이 포화돼 이후 검색이 지연·무응답이 된다.
**수정**: BFF 프록시가 `signal: request.signal`(+ `cache: "no-store"`)을 upstream `fetch`에 전달하고, abort는 `499`로 흡수한다 → 클라이언트가 끊으면 upstream도 즉시 취소돼 백엔드 낭비·커넥션 누수가 없다. 프런트 `stopSearch`는 `cancelQueries` 후 `removeQueries`로 취소된 쿼리 캐시를 제거해 같은 검색어 재검색이 깨끗하게 재요청되도록 했다.
**검증**: frontend tsc/lint/build. 정상(비중단) 요청에는 영향 없음(signal 미발화). dev/prod web 재빌드 배포. (severe 무응답은 합성 테스트로 재현되지 않아, 배포 후 사용자 재확인 필요 — 재발 시 발생 시점·브라우저 Network 탭 정보 수집.)

## 2026-06-22: T-102 완료 — 재생목록 harvest 후처리 스코프 버그 수정 + 강제 재실행

**버그(사용자 보고)**: 강원도 playlist harvest 실행 중 "예전(부산) 재생목록"을 처리. 진단: 대상 재생목록에서 신규 영상 0개일 때, 후처리(자막·POI)가 그 재생목록이 아니라 DB 전역의 미처리 영상(예전 부산 harvest의 미전사 영상)을 max_videos만큼 처리.
**원인**: worker가 `video_ids = harvest_summary.video_ids or []`(신규 0개면 `[]`)를 넘기고, `postprocess_service._load_target_videos`의 `if video_ids:`가 빈 리스트를 "스코프 없음"으로 오해 → `crawl_status != DONE` 전역을 `limit`만큼 로드.
**수정**: `_load_target_videos`를 `if video_ids is not None:`로 변경 — 빈 리스트는 `in_([])` → 0건(전역 백로그 폴백 금지). 회귀 테스트 추가(`test_..._empty_video_ids_does_not_fall_back_to_backlog`).
**강제 재실행**: `POST /source-targets/{id}/run-now?force=true` → `run_target_now(force=True)`가 증분 워터마크(`last_seen_cursor`, `last_seen_video_published_at`) 리셋 + payload `"force": true`. worker가 force면 대상(재생목록→`youtube_playlist_videos`/채널→`youtube_videos`)의 영상 ID를 모아 후처리 스코프에 합집합으로 포함(루프가 완료분은 건너뛰어 중복 없음 — 미완료/실패분 재시도). 프런트 "강제 재실행" 버튼(지금 진행 옆), `runSourceTargetNow(id, force)`. 정상 "지금 진행"은 신규만(0개면 아무것도 안 함).
**검증**: backend 영향 테스트 54 + 신규 회귀 통과, compileall. frontend tsc/lint/build. dev 라이브: force run-now가 워터마크 리셋 + payload force 확인, 강제 재실행 버튼 표시. (백엔드 fork가 529로 죽어 직접 구현.) dev/prod 배포.

## 2026-06-21: T-101 완료 — 검수 place-search 성능 개선(provider 즉시 + Gemini 의견 비동기 분리)

**문제**: 검수 검색이 매우 느리고(≈20초) 게이트웨이 타임아웃에 취약.
**원인(측정)**: provider 3종(Google/Kakao/Naver)은 ~0.4초로 빠르나, Gemini 의견이 provider 다음에 **직렬**로 await되고 매번 `wait_for(20s)` 상한에 걸림. dev Gemini 키가 **429(쿼터)**를 반환 → ETL용 "사람-유사 느린 재시도"(기본 15초)에 걸려 20초까지 늘어남. 단일 요청 20초+ → 프록시/게이트웨이 타임아웃 위험.
**개선**:
- `GET /place-search`를 **provider-only**(Gemini 호출·필드 제거)로 → ≈0.4초 즉시 반환. provider httpx 타임아웃 15→8초.
- `POST /place-search/opinion`(`{query, hits}`) 신설 — Gemini 의견을 **max_attempts=1(15초 재시도 제거) + 10초 타임아웃 + `wait_for(12s)`**로 단일 시도, 실패 시 `gemini:null`(500 아님). `complete_json`/`gemini_client`에 `max_attempts` 인자 추가.
- 프런트: 검색 버튼 → provider 결과 즉시 표시, Gemini 의견은 별도 비동기 호출(`getPlaceOpinion`, "분석 중…" → 결과/생략). 검색 중지는 둘 다 취소(AbortSignal+cancelQueries).
- **결과**: UI 검색 결과 표시 **~1초(이전 ~20초)**, 게이트웨이 타임아웃 해소.
- 참고: Gemini 의견 자체는 dev/prod 키 **429(쿼터)**로 현재 미표시 — 검색 속도와 무관한 키/쿼터 사안(쿼터 있으면 정상 표시).
- 후속: 의견 실패 사유를 **응답·UI에 노출**(조용히 생략 → 안내). `gemini_place_opinion(raise_on_error=True)`로 에러를 전파하고 opinion 엔드포인트가 `LlmRequestError.status_code==429`면 "Gemini API 쿼터 초과(429) — 검색 결과는 정상", 그 외엔 "일시 오류"로 분류해 `error`에 반환, 프런트는 의견 카드 자리에 그 문구를 표시.
- 후속2: AI(Gemini) 의견을 **자동 호출 → 사용자 수동 요청**으로 변경(쿼터 절약). provider 검색만 자동 실행하고, 결과 아래 "AI(Gemini) 의견 요청" 버튼을 눌러야 opinion 호출(`opinionRequested` state로 게이트). 요청 후 분석 중 → 결과/안내 + "다시 요청"(refetch), 새 후보/검색/검색중지 시 버튼 상태로 초기화.
- 검증: backend 267 pytest·compileall, frontend tsc/lint/build, dev 재측정(GET 0.44s, opinion 분리). dev/prod 배포(prod는 실행 큐 종료 후).

## 2026-06-21: T-100 완료 — 검수 후보·확정 장소 상세 정보 뷰(반응형) + 후보 삭제 + 검색 중지

T-097~099 후속. 백엔드 상세 엔드포인트는 포크로, 반응형 상세 뷰는 스샷 검증하며 구현(ADR-31 범위).

- **상세 정보 뷰(반응형)**: 검수 후보/확정 장소를 클릭하면 **PC=모달, 모바일=새 페이지**(`/review/[id]`·`/place/[id]`)로 상세를 연다. `useIsMobile`(matchMedia + useSyncExternalStore, SSR-safe)로 분기. 공용 뷰(`CandidateDetailView`/`PlaceDetailView`)를 모달·페이지가 공유.
- **검수 후보 상세**: 추출 작업(어느 큐: analysis run type label), 어느 동영상(제목/채널/길이/설명), 동영상 내 근거(구간 timestamp·출처 source_kind·원문 source_text·메모), 같은 동영상의 다른 장소 목록(sibling). + **후보 삭제**("정말 삭제할까요?" 확인 후, `DELETE /destinations/candidates/{id}`; 확정 장소 연결 시 409 안전장치).
- **장소 상세**: 장소 정보 + **언급 횟수·동영상 수·유튜버 수**(중복) + 영상 설명/AI 보강/심층 조사 + 출처 동영상별 **중복 횟수**와 어디에 나왔는지(타임스탬프·근거 텍스트). `GET /destinations/{id}/detail`(stats + grouped source_videos; 근거 텍스트는 `video_place_mappings.ai_summary`).
- **검색 중지**: 검수 페이지 검색 버튼 옆에 진행 중 검색 취소 버튼(react-query AbortSignal + `cancelQueries`). `searchPlaces(query, signal)`.
- **검증**: backend 266 pytest·compileall, frontend tsc/lint/build. 13200 프리뷰에서 후보/장소 상세(모달 + 모바일 페이지), 삭제 확인, 근거(구간 00:32~00:39·transcript 원문), 장소 stats(언급2/동영상2/유튜버2) 확인. dev/prod 배포(prod는 실행 큐 종료 후).

## 2026-06-21: T-099 완료 — 검색/결과 페이지 분리 + 작업 라벨 사람화 + run-now + 내부 스캔 필터

T-097/098 후속 jobs/queue UX 보강. 백엔드(라벨·필터·run-now)는 포크로, 프런트(페이지 분리·표시)는 스샷 검증하며 구현(ADR-31 범위).

- **페이지 분리(req1)**: 기본 `/`(결과)는 상단 `AppNav`(결과/수집/검수 + 운영·설정) + 간단한 실행 큐 상태바 + 장소·지도만. 수집 폼·작업 관리는 `/collect`(수집 폼 | 실행 큐 | 작업 반복/1회성 탭)로 분리. `AppNav`/`CollectWorkspace` 신설, `DestinationWorkspace`는 결과 전용으로 슬림화, `HarvestConsole`은 폼만(헤더 버튼·내부 실행 큐 제거).
- **작업 라벨 사람화(req2/3)**: 백엔드 `_run_dict`/`_source_target_dict`에 `target_type_label`(유튜버/재생목록/검색어/영상)·`target_label`(키워드 텍스트 또는 채널/재생목록/영상 제목, 배치 조회로 N+1 방지)·`job_type_label`(수집/예약 스캔/심층 조사/…) 추가. 카드 1번째 줄=대상(검색어 "…"/유튜버 "…"), 작업유형은 둘째 줄 작은 배지로(가장 중요 정보 아님).
- **run-now(req4)**: `POST /source-targets/{id}/run-now`로 반복 작업 "지금 진행" 즉시 실행(`run_target_now`, 중복 시 created:false). 1회성엔 "다시 시작"(기존 restart).
- **내부 스캔 필터(req5)**: `GET /runs?job_types=harvest,deep_research,video_analysis`로 `source_scan`을 작업 목록·실행 큐에서 제외 → 사용자가 보는 작업이 실제 수집 작업만 남아, 상세의 "누적 수집 영상"이 정상 표시(엔드포인트는 원래 정상, source_scan은 영상 0개라 비어 보였던 것). `/source-targets/{id}/videos`는 채널 타깃도 `youtube_videos.channel_id`로 합쳐 견고화.
- **검증**: backend 265 pytest·compileall, frontend tsc/lint/build. 13200 프리뷰에서 페이지 분리, 라벨(검색어 "korea travel guide vlog"·유튜버 "[빵이네]캠핑&여행TV"), source_scan 제외, "지금 진행"(실행 큐에 즉시 running), 상세 누적 영상 6 확인. dev/prod 배포(단 prod는 진행 중 실행 큐 종료 후).

## 2026-06-21: T-098 완료 — 검수 검색 위치 힌트 결합 + 메인 지도↔리스트 연계(번호 마커·양방향 선택)

T-097 후속 UI 보강. 워크플로(2 기능 병렬 + 빌드 게이트)로 1차 구현 후 스샷으로 시각 검증·튜닝.

- **검수 검색 힌트 결합**: `/review` 자동 검색 쿼리에 후보의 `location_hint`를 이름 앞에 붙인다(예: 힌트 "부산" + "감천문화마을" → "부산 감천문화마을"). `location_hint`가 AI가 쓴 장황한 문장("인천 (영상 설명에 언급)", "불확실함 (…)")인 현실을 반영해 `cleanLocationHint`로 괄호 설명 제거·불확실/미상류 제외·앞 2단어만 사용. 이름에 힌트가 이미 있으면 중복 제거(예: "만월산명주사"+힌트 "만월산" → 그대로). 입력창에서 수정 가능. (`frontend/src/app/review/page.tsx`)
- **지도↔리스트 연계**: 장소 리스트 행과 지도 마커에 동일한 1-based 번호(리스트 순서 기준) 부여. 리스트 클릭 → 지도 `easeTo` 중심 이동 + 선택, 마커 클릭 → 리스트 행 선택 + `scrollIntoView`. 선택 항목은 brand(teal) 강조(마커 확대·elevation, 리스트 행 highlight), 비선택은 muted. 마커 diff 캐싱·VWorld WMTS·min-zoom 유지(props 하위호환). (`VWorldMap.tsx`, `DestinationWorkspace.tsx`)
- **검증**: frontend tsc/lint/build 통과. 13200 프리뷰에서 번호 일치(리스트 64=마커 64), 리스트→지도 중심·선택, 마커→리스트 선택·동기화, 힌트 결합("부산 감천문화마을")·정제(불확실 힌트 제외) 확인. dev/prod 배포.

## 2026-06-21: T-097 완료 — UI 전면 개편(검수 별도 페이지·멀티 provider) + 작업/반복 관리 + 운영·설정 모달 + API 키 DB 관리

대규모 UI 개편 + 신규 기능. 각 단계를 스샷으로 검토받으며 진행하고 완료 후 dev/prod에 배포(ADR-31).

- **메인 레이아웃**: 좌측 수집 사이드바를 접이식(48px 토글)으로, 장소 목록을 지도 왼쪽 좁은 칼럼(`lg:grid-cols-[0.7fr_1.6fr]`)으로, 하단을 **실행 큐 | 작업(반복/1회성 탭)** 2열로 재편. 검수 큐 패널 → 별도 페이지, 운영 패널 → 사이드바 버튼+모달. 사이드바 헤더에 검수·운영·설정 버튼.
- **검수 별도 페이지(`/review`)**: 후보 목록 + 선택 후보 정보 + **Google Places·Kakao·Naver 검색과 Gemini 의견을 한 번에 비교**(결과/지도 마커 클릭→좌표 선택) + 직접 검색 + 지도 + 확정/제외. 백엔드 `GET /api/v1/place-search?q=`(`ktc/etl/place_search.py`: 4 provider 병렬·결함 격리·정규화, Naver mapx/mapy÷1e7, Gemini 의견).
- **작업 표시·상세·제어**: 작업 패널을 반복/1회성 탭으로(모든 작업 표시). 항목 클릭 → **상세 모달**(대상·키워드·최대수·간격·누적 영상; `GET /runs/{id}/videos`, `GET /source-targets/{id}/videos`). 실행 큐 카드에 중지/재시작.
- **반복 수정·횟수**: 반복 작업 **수정 모달**(주기·횟수, `PATCH /source-targets/{id}`). 생성 시 **반복 횟수(0=무한)** 추가, 간격을 1시간·12시간·1일·1주일·2주일·1달·3달로. `source_targets.max_runs/run_count`(migration `20260621_0009`; 기존 DB는 직접 ALTER), `scan_due_targets`가 run_count 증가·max_runs 도달 시 비활성화.
- **자동 완료**: 수집 시작 시 자막→POI→지오코딩→DB까지 자동(자막 생성 확인 단계 제거, `skip_transcript=false`).
- **운영 지표 모달**: `GET /api/v1/metrics`(RustFS 객체/용량/타입별 + DB 카운트: 영상·채널·재생목록·장소·지오코딩·언급매핑·반복작업·후보상태·작업상태).
- **설정 모달 + API 키 DB 관리**: AI 엔진·사전 프롬프트·DeepSeek 키에 더해 **8종 API 키(YouTube/Gemini/Google Places/Naver 검색 id·secret/Kakao/VWorld/DeepSeek)를 UI에서 저장/수정**. `settings_service.get_secret`(system_settings→.env 폴백), `GET /settings`에 `api_keys`(set 여부만 노출), POST는 빈 값 미변경·감사 로그 마스킹. 소비처(harvest youtube, place-search, geocoding postprocess, get_llm_runtime)가 get_secret로 해석.
- **UI 프리미티브**: base-ui 기반 `Dialog`/`Tabs` 추가(검수 페이지/모달/탭 공용).
- **검증**: backend pytest 257 + compileall, frontend lint/type-check/build. dev 백엔드 재빌드 후 4 provider 검색·`/metrics`·반복 PATCH·작업 상세·설정 API 키를 실데이터로 확인. dev/prod 배포.

## 2026-06-21: T-096 완료 — 숏츠/동영상 콘텐츠 유형 필터 + 재생목록 URL 확인

- **콘텐츠 유형 필터**: 수집 폼에 "콘텐츠 유형"(숏츠+동영상/숏츠만/동영상만) 선택을 추가. 백엔드는 `duration_seconds <= SHORTS_MAX_DURATION_SECONDS`(기본 60초)면 숏츠로 보는 휴리스틱으로 `pipeline.filter_candidates_by_content`를 적용한다. 숏츠/동영상 필터 시 `collect_limit`(max_videos×3, 50 상한)로 넉넉히 수집한 뒤 길이로 걸러 `max_videos`로 자른다. `HarvestRequest.content_filter`(`both`/`shorts`/`videos`), `run_harvest(content_filter, shorts_max_seconds)`, `harvest_handler`에서 payload→run_harvest 전달, `config.SHORTS_MAX_DURATION_SECONDS`. 프런트 `HarvestContentFilter` + `lib/api.ts` payload. (반복 수집은 현재 `both` 기본 — source_target에 필터를 저장하지 않음, 향후 보강 여지.)
- **재생목록 URL**: `https://www.youtube.com/playlist?list=PLXQvmY7fb6wrbbCYcjFI4A0j-j9Fx13Xk`는 기존 `parse_playlist_id`로 이미 정상 처리됨을 확인.
- **검증**: backend 전체 pytest(필터 단위 테스트 포함)·compileall, frontend lint/type-check/build. dev 재빌드 후 라이브 검증, dev/prod 배포.

## 2026-06-21: T-095 완료 — percent-encoded 채널 URL handle 디코드 수정

- **증상**: 브라우저 주소창에서 복사한 `https://www.youtube.com/@%EB%B9%B5%EC%9D%B4%EB%84%A4tv`(= `@빵이네tv`) 입력 시 `parse_channel_input`이 `urlparse` path를 디코드하지 않아 handle을 percent-encoded(`@%EB%B9%B5...tv`)로 추출 → forHandle 해석이 불안정(검색 fallback 의존, 100 quota 소모 또는 실패).
- **수정**: `parse_channel_input`이 URL path 세그먼트를 `unquote`로 디코드해 표준 handle/custom 이름으로 되돌린다. encoded URL이 literal `@빵이네tv`와 동일하게 파싱됨을 확인, 회귀 테스트 추가. dev/prod api 재배포.

## 2026-06-21: T-094 완료 — 수집 입력 유연화 + 반복 수집 + 작업 제어 + UI 재구성

- **채널/재생목록 입력 해석**: harvest의 `channel_id`가 채널명/@handle/채널 URL/`UC...`를, `playlist_id`가 `PL...`/재생목록·시청 URL을 받아 표준 ID로 해석한다. `ktc/etl/source_resolve.py`(순수 파서 `parse_channel_input`/`parse_playlist_id` + API 해석 `resolve_channel_id`), `youtube_client`에 `forHandle`/`forUsername`/`search type=channel` 추가. `start_harvest`에서 해석 후 표준 ID로 run/target 저장(해석 실패는 400). 라이브 검증: 채널 URL→UC, 채널명 "빵이네tv"→UC(search), 재생목록 URL→PL.
- **반복 수집**: `HarvestRequest.repeat_interval_minutes`가 있으면 1회 즉시 수집과 함께 `source_target`(scan_interval_minutes, is_active, next_crawl_at=now+interval)로 등록 → 기존 source_scan이 주기 enqueue. `GET /source-targets`(활성·interval 있는 반복 대상), `DELETE /source-targets/{id}`(비활성화, watermark 보존). 프런트는 “반복 검색” 체크박스 + 간격(30분~1주) 선택.
- **작업 중지/재시작**: `RunState.CANCELLED` + `cancel_requested` 컬럼 추가(migration `20260621_0008`; 기존 DB는 alembic_version 없어 직접 ALTER). `POST /runs/{id}/stop`(pending→cancelled, running→협조적 취소 신호), `POST /runs/{id}/restart`(같은 입력 새 run). worker `execute_run`을 handler task + heartbeat/cancel watcher로 리팩터링해 `cancel_requested` 폴링 시 handler를 취소하고 `cancelled`로 마감(외부 취소는 전파).
- **UI 재구성**: 장소 목록을 지도 옆(상단 2열)으로, 검수 큐·반복 작업·운영을 하단의 작은 3열로 재배치. **반복 작업 패널**(타입/간격/다음 실행 + 삭제), **최근 작업/실행 큐 카드 클릭 시 상세 로그 펼침 + 중지/재시작** 버튼. `lib/api.ts`에 `SourceTargetSummary`/`listSourceTargets`/`deleteSourceTarget`/`stopRun`/`restartRun` 추가.
- **검증**: backend 244 pytest 통과·compileall, frontend lint/type-check/build 통과, dev 스택 재빌드 후 Playwright로 레이아웃·폼·반복 등록/삭제·작업 중지/재시작·채널명 해석을 실 도메인 데이터로 확인. prod SSH 접속정보는 gitignore된 `docs/prod-access.local.md`에만 저장.

## 2026-06-21: T-093 완료 — prod 배포 + Next 프로덕션 빌드 전환

- **배경**: T-092(모바일 Select native 폴백, PR #96)을 머지·dev 반영했으나 `concierge.digitie.mywire.org`는 "그대로"였다. 진단 결과 공개 도메인은 dev 머신이 아니라 **별도 LAN prod 호스트(SSH)**가 서빙하며, 이 세션의 재배포는 dev 인스턴스(12605)만 갱신했음을 확인(prod는 `docker save|ssh load` 이미지 운영, 소스 트리 부재).
- **배포**: 사용자 승인 하에 prod 호스트로 concierge 소스를 rsync(`.env*` 제외로 prod 설정 보존)하고 concierge-ui 이미지를 prod에서 재빌드.
- **핵심 발견**: prod UI가 **Next dev 모드(`npm run dev`)**로 떠 있어, 도메인/프록시 원격 접속 시 HMR WebSocket 실패와 함께 **hydration이 안 돼 모든 인터랙티브 컴포넌트가 멈춰** 있었다(같은 코드인데 dev=select 옵션 3 개방, prod=0). 즉 prod의 "Select 미동작"은 모바일 터치 버그가 아니라 prod React 비활성 상태였다.
- **수정**: prod 전용 `docker-compose.override.yml`로 concierge-ui를 **프로덕션 빌드(`next build` + `next start`)**로 전환(dev 로컬은 override 없이 `npm run dev` 유지). 프로덕션 빌드는 HMR WS 비의존이라 프록시 뒤에서 정상 hydration.
- **검증(실 도메인)**: 데스크톱 select 정상 개방, 모바일 터치에서 native `<select>` 렌더+선택 연동(채널→placeholder 전환), VWorld 지도 렌더(키 baked). 사용자 보고 이슈 해소.
- **후속(권장)**: prod 전용 override 대신 docker-manager 베이스 compose에 UI 모드 env 토글을 두면 재현성↑. docker-manager `docs/prod-deployment.md`에 prod 프로덕션 모드 절차 기록.

## 2026-06-20: T-092 완료 — 모바일(삼성 인터넷) Select 미동작 수정 (native 폴백)

- **증상**: 삼성 인터넷 모바일에서 수집 폼의 "대상 유형" 등 Select 드롭다운이 선택 안 됨. 원인은 Base UI(`@base-ui/react/select`) 커스텀 팝업이 모바일 터치(coarse pointer)에서 동작하지 않는 문제(데스크톱 마우스에선 정상).
- **수정**: 공유 `Select` 컴포넌트(`components/ui/select.tsx`)가 **coarse pointer 기기에서 OS 네이티브 `<select>`로 폴백**하도록 변경. `useCoarsePointer`(matchMedia, SSR-safe)로 분기하고, 자식 트리에서 `SelectItem`(값·라벨)을 재귀 추출해 native `<option>`으로 렌더링한다. trigger 공통 스타일을 상수로 추출해 Base UI/native가 공유. 데스크톱(fine pointer)은 Base UI 유지. 호출부(HarvestConsole/DestinationWorkspace/settings) 3곳 코드 변경 없이 자동 적용.
- **검증**: lint/type-check/production build 통과. Playwright 터치 컨텍스트(`hasTouch`)에서 native `<select>` 렌더·옵션 3종 추출·`onValueChange` 연동(채널 선택 시 입력 placeholder 전환) 확인. 데스크톱 fine pointer는 Base UI 정상 동작 회귀 확인. UI 컨테이너 재빌드·재시작으로 배포(api/scheduler 무중단).

## 2026-06-20: T-091 완료 — whisper 폴백 활성화 재실행 + VWorld 지도 키 반영

- **whisper 폴백 활성화**: T-090에서 `youtube-transcript-api` 차단으로 채널·키워드가 0건이던 문제를, `.env`/`.env.production`에 `TRANSCRIPT_WHISPER_ENABLED=true`·`WHISPER_MODEL_SIZE=base`를 더해 faster-whisper 오디오 전사 폴백으로 해결. `.env.example`에 기본 false로 문서화. 코드/이미지 변경 없음(이미 faster-whisper 의존·whisper 경로 존재), env+재시작만으로 적용.
- **재실행 결과**: 깨끗한 DB로 UI E2E(10영상×3소스) 재실행. 자막 확보 영상 3/27 → **11/27**, 지오코딩 장소 **13개(전부 지오코딩)**. **전과 0건이던 키워드(제주 7개)·채널(6개) 소스가 whisper 전사로 장소 추출 성공**. 플레이리스트는 이번 배치에서 captions+오디오 모두 rate-limit으로 0건(가용성 변동성). `docs/e2e-report-2026-06-20-ui-whisper.md`.
- **VWorld 지도 키 반영**: UI 컨테이너가 `NEXT_PUBLIC_VWORLD_SERVICE_KEY`를 docker-manager의 `NEXT_PUBLIC_VWORLD_API_KEY`에서 읽는데 미설정 → 지도 "키 없음". docker-manager `.env`에 키 추가 후 UI 컨테이너만 재시작해 지도 렌더링 정상화(백엔드 지오코딩 키는 정상이었음, 운영 api/scheduler 무중단).
- **정리**: 실행 후 concierge를 운영 dev DB로 복원, e2e DB 삭제.

## 2026-06-20: T-090 완료 — UI 레벨 수집 E2E(10영상×3소스, 깨끗한 DB)

- **배경**: PR #91 머지 후, 5영상이 아니라 10영상으로 **웹 UI를 브라우저로 직접 조작**하는 UI 레벨 E2E를 재실행 요청. dev DB는 3소스가 이미 수집돼 증분 harvest가 0건이라, 사용자 선택에 따라 깨끗한 DB(`kor_travel_concierge_e2e`)로 실행.
- **실행**: T-089 버그 수정 반영 빌드로 concierge 재배포(같은 12601/12605). Playwright로 폼 입력(대상 유형·값·최대 10) → "수집 시작" → "자막 생성 시작". 채널 10·플레이리스트 7·키워드 10 = **27영상 수집**, 자막 작업 3건 모두 완료.
- **결과**: UI 2단계 플로우 end-to-end 검증. **T-089 버그 수정 검증** — 직전에 truncation으로 실패하던 키워드 소스가 정상 완료. 플레이리스트는 9개 장소 추출·전부 지오코딩(부산 명소). 채널·키워드는 0건.
- **한계**: 27개 중 3개 영상만 유효 자막 확보(`youtube-transcript-api` rate-limit/차단 추정, whisper 폴백 미활성). 자막이 비면 POI 단계가 스킵돼 채널·키워드 0건. 영상 설명은 있으나 현 파이프라인은 transcript 없으면 건너뜀.
- **권장**: transcript 비어도 description 단독 POI 추출(#91 데이터 흐름 활용) 또는 whisper 폴백 활성화.
- **정리**: 실행 후 concierge를 운영 dev DB로 복원, e2e DB 삭제. 산출물 `docs/e2e-report-2026-06-20-ui-10videos.md`.

## 2026-06-20: T-089 완료 — POI 타임스탬프 VARCHAR(16) truncation 버그 수정

- **배경**: T-088 라이브 E2E에서 키워드 harvest가 `extracted_place_candidates.timestamp_start/end`(및 `video_place_mappings` 동일 컬럼) `varchar(16)`에 Gemini의 16자 초과 타임스탬프(예: "00:22:00 - 00:35:00")를 적재하다 `StringDataRightTruncationError`로 작업 전체가 롤백·실패했다.
- **수정**: 두 모델의 `timestamp_start/end`를 `String(64)`로 넓히고, `@validates`로 64자 초과 값을 방어적 클립한다(provider 무관 모든 적재 경로 보호). Alembic migration `20260620_0007`로 실제 DB 컬럼도 `VARCHAR(64)`로 확장. raw/보정 분리(ADR-16) 불변.
- **검증**: 클립 회귀 테스트 4종(`test_models_timestamp_clip.py`, DB 불필요) + PostGIS 테스트 DB로 models_spatial/poi/place_service 통과, compileall. fresh DB는 `init_db` create_all로 `VARCHAR(64)` 스키마 생성됨을 확인.

## 2026-06-20: T-088 완료 — 라이브 수집 E2E(3소스×5영상) 실행 및 리포트

- **배경**: 사용자 요청으로 채널 `@빵이네tv`, 플레이리스트 `PLXQvmY7fb6woRMSD8cgk10UIJRt9nmuXl`, 키워드 `제주도 가족여행` 각 5개 영상에 대해 실제 YouTube·Gemini·VWorld API를 호출하는 라이브 harvest E2E를 실행했다.
- **실행**: 포트 정책상 기존 `kor-travel-docker-manager` 인스턴스(host 12601, Gemini 2.5 Flash)를 종료하지 않고 그대로 사용. `POST /api/v1/harvest`로 3개 job(2026/2027/2028) 생성, 전체 파이프라인(수집→자막→Gemini POI→지오코딩) 완주를 폴링.
- **결과**: 채널 ✅(영상5·후보30·장소16, 16/16 지오코딩), 플레이리스트 ✅(영상5·후보44·장소21, 21/21 지오코딩), 키워드 ❌(88.6%에서 실패). 성공 2소스에서 **37개 장소를 전부 좌표·주소까지 확보**.
- **버그 발견**: `extracted_place_candidates.timestamp_start/end`(및 `video_place_mappings` 동일 컬럼)가 `varchar(16)`인데 Gemini가 16자 초과 타임스탬프를 반환해 키워드 job이 truncation 오류로 롤백·실패. 컬럼 확장(varchar(32)/text) + 적재 전 정규화 + per-video 트랜잭션 경계 재검토를 권장(별도 PR 제안).
- **산출물**: `docs/e2e-report-2026-06-20-live-harvest.md`.

## 2026-06-20: T-087 완료 — 영상 설명(description) 기반 POI 추출 보강

- **배경**: 자막에는 음성으로 언급되지 않지만 영상 설명란에만 적혀 있는 장소명·주소·링크가 흔하다. 영상 설명 원문이 Gemini POI 추출에 안정적으로 입력되어, 자막뿐 아니라 영상 설명에서도 장소 후보를 뽑도록 보강하기로 했다.
- **조사 결과(데이터 흐름은 이미 정상)**:
  - `youtube_client.videos_list`는 `part=snippet,statistics,contentDetails`로 호출한다(`backend/ktc/etl/youtube_client.py:127`). `videos.list`의 `snippet.description`은 잘리지 않은 **전체 설명**이다(검색용 `search.list` 스니펫과 달리 truncate 없음).
  - `pipeline.build_candidate`가 `description_raw = snippet.get("description")`을 `videos.list` 항목에서 채운다(`backend/ktc/etl/pipeline.py:90`, 상세 조회는 `pipeline.py:392`). 즉 저장되는 설명은 전체 설명이다.
  - `ingest_service.upsert_video`가 `description_raw`를 멱등 저장하고 Gemini 보정 필드는 건드리지 않는다(`backend/ktc/etl/ingest_service.py:343,352-355`).
  - `summarize_service.summarize_video`가 `extract_pois(..., description_raw=video.description_raw, ...)`로 전달한다(`backend/ktc/etl/summarize_service.py:105`).
  - `poi_extraction.build_prompt`가 `[영상 설명 원문]\n{description_raw or ''}`을 임베드한다(`backend/ktc/etl/poi_extraction.py:80`).
  - `video_analysis_service`의 `_video_context`는 `description_raw`를 포함하므로 `build_url_summary_prompt`/`build_reconcile_prompt`에도 이미 설명이 들어간다(`backend/ktc/etl/video_analysis_service.py:180`).
- **실제 공백(프롬프트 지시)**: 데이터는 전체 설명이 끝까지 흐르지만, POI 프롬프트 지시는 "장소를 추출하고 영상 설명의 오탈자·문맥을 보정하라"로만 되어 있어 설명을 **보정 대상**으로만 취급했다. 설명란에만 있는 장소를 추출하라는 명시 지시가 없었다.
- **수정**: `poi_extraction.build_prompt` 지시를 "타임스탬프 자막과 영상 설명 원문 양쪽에 등장하는 장소(POI)를 모두 추출하라. 영상 설명에만 적혀 있고 자막에는 없는 장소도 빠짐없이 추출하라."로 확장하고, 기존 보정 지시는 유지했다. 원문 `description_raw`는 그대로 두고 보정본은 `description_gemini_corrected`에만 반영하는 ADR-16 분리는 변경하지 않았다.
- **검증**: `build_prompt`가 영상 설명 원문과 추출 지시를 포함하는지, `extract_pois`가 설명을 LLM 프롬프트에 전달하는지 회귀 테스트를 `backend/tests/test_etl_poi.py`에 추가. `python -m compileall ktc` 통과, POI 9건 통과, 디스포저블 PostGIS 테스트 DB(`kor_travel_concierge_test`)로 summarize/ingest/pipeline/video_analysis 30건 + 백엔드 전체 스위트 통과.

## 2026-06-20: T-085 완료 — AI 엔진 다중 provider + 사전 프롬프트 + JSON + 느린 재시도 (ADR-30)

- **배경**: 그동안 ETL·Deep Research의 LLM 호출이 Gemini 단일 provider(ADR-3)에 묶여 있었다. 사용자가 (1) DeepSeek V4를 대안 provider로 추가하고 웹 설정에서 엔진을 전환, (2) 모든 AI 프롬프트 앞에 편집 가능한 공통 지침(사전 프롬프트) 적용, (3) 두 provider 모두 안정적 JSON 출력, (4) 외부 LLM 429/일시 오류에 사람처럼 충분히 느리게 재시도하도록 요청했다.
- **수정**:
  - **DeepSeek provider 디스패치**: `ktc/etl/deepseek_client.py`(OpenAI 호환 chat completion + JSON mode, `base_url=https://api.deepseek.com`), `ktc/etl/llm_client.py`(provider 디스패치 `complete_json` + `LlmRuntime` + 사전 프롬프트 prepend) 추가. `config.py`에 `DEEPSEEK_API_KEY`/`DEEPSEEK_BASE_URL`, `DEEPSEEK_ENGINE_OPTIONS`, 통합 `LLM_ENGINE_OPTIONS`, `is_deepseek_model` 추가. 모델은 `deepseek-v4-flash`/`deepseek-v4-pro`.
  - **웹 설정**: `/settings`에서 엔진을 Gemini/DeepSeek로 전환하고 DeepSeek API 키 저장(평문 미노출, 감사 로그 마스킹).
  - **사전 프롬프트**: 모든 AI 프롬프트 앞에 붙는 사용자 편집 지침을 런타임 설정 `ai_preprompt`(`system_settings`)로 두고 기본 예제 `AI_PREPROMPT_DEFAULT` 제공. 기본값은 "코드펜스 없이 JSON만" 강조.
  - **JSON 출력**: Gemini는 기존 `responseSchema`, DeepSeek는 `response_format=json_object` + 스키마를 프롬프트에 첨부.
  - **느린 재시도**: `LLM_RETRY_*` env(base 15s, max 90s, jitter 0.3, 4회)와 `gemini_client.human_like_retry_delay`를 Gemini·DeepSeek 공용으로 추가. 기존 2/4/8초 백오프를 충분히 늦은 사람 유사 지연으로 교체.
  - **키 비밀 유지**: `.env`/`.env.production`(gitignore)에 `DEEPSEEK_API_KEY=sk-...`, `.env.example`에는 placeholder만. git·감사 로그에 평문 미노출.
- **검증**: provider 디스패치·JSON mode·사전 프롬프트 prepend·재시도 지연 동작을 단위 테스트와 설정 검증으로 확인. DeepSeek 실제 키 라이브 호출은 키·과금을 쓰지 않기 위해 fake LLM로 상태 전이만 검증.

## 2026-06-20: T-086 완료 — 한국어 에러 복구 UI 이식 (kor-travel-geo PR #391)

- **배경**: Next App Router 기본 오류 화면은 영어·정보 부족이라 운영 콘솔 사용자가 복구 행동을 고르기 어려웠다. 형제 프로젝트 `kor-travel-geo` PR #391의 에러 복구 UI를 동등하게 이식하기로 했다.
- **수정**: `frontend/src/app/error.tsx`, `global-error.tsx`, `components/layout/AppErrorPanel.tsx`, `lib/error-recovery.ts`를 추가했다. chunk/RSC/network 런타임 오류는 같은 pathname에서 1회만 hard reload하고(루프 방지), 반복 실패 시 재시도/이전 화면/오류 정보를 한국어로 제공한다. Tailwind + shadcn으로 적용해 기존 디자인 토큰(ADR-29)과 일관되게 맞췄다.
- **검증**: lint/type-check/build 통과, 오류 유발 시 1회 reload·반복 실패 패널 표시 동작을 확인.

## 2026-06-20: T-084 완료 — `kor-travel-geo` UI 지침 채택 + Tailwind v4 전환 (ADR-29)

- **배경**: 사용자 지시로 형제 프로젝트 `kor-travel-geo`의 UI 지침(`kor-travel-geo-ui/docs/DESIGN-RULES.md`, StyleSeed 기반)을 concierge 프런트에 **그대로** 따르고, 빌드 엔진을 **Tailwind v4**로 전환했다. 기존 프런트는 stock shadcn `base-nova` neutral(무채색) 테마였다.
- **디자인 시스템 이식**:
  - `src/app/globals.css` `:root`에 geo semantic 토큰을 단일 출처로 추가(단일 accent `--brand` teal `#0f766e`, 5단계 `--text-*`, `--surface-*`, status, `--shadow-*` 4/6/8/12%, `--duration-*`/`--ease-default`). shadcn 토큰(`--background/--primary/--border/--ring`…)을 brand 팔레트에 매핑 → 기존 컴포넌트가 자동으로 brand+light 채택. `--radius: 0.5rem`(8px 카드). `prefers-reduced-motion` 비활성 규칙 추가.
  - `tailwind.config.ts`에 `text.*/surface.*/brand/info/success/warn/danger` + `shadow-card|button|modal`, `duration-fast|normal`, `ease-default` 토큰 추가.
  - primitive 정렬: `button/input/label/badge/select`에 44px touch(`min-h-11`), 8px radius, 약한 shadow, named motion, label은 12px·`tracking-[0.05em]`·uppercase, brand focus ring.
  - 하드코딩 색 치환: progress `emerald`→`success`, 로그 tone `emerald/amber`→`success/warn`, settings toast `green`→`success`, VWorldMap marker(`#111827/#2563eb`)→선택=brand·비선택=secondary, 색 없는 중립 그림자, fallback bg→surface-muted.
  - `frontend/docs/DESIGN-RULES.md`를 정본으로 추가.
- **Tailwind v3.4 → v4 전환**: `@tailwindcss/postcss` + `@import "tailwindcss"`, 기존 JS config는 `@config "../../tailwind.config.ts"`로 유지하되 v3 전용 `cssVariableColor`(opacity callback)을 제거(v4 native opacity). `tailwindcss-animate` → `tw-animate-css`(`@import`). `@custom-variant dark (&:is(.dark *))`로 light 전용. `autoprefixer`는 postcss config에서 제거(v4 내장).
- **검증**: `npm run lint`/`type-check`/`build`(Next 16 + Turbopack, v4) 모두 통과. `next start` + Playwright로 `/settings`(brand 저장 버튼·uppercase label·44px select)와 `/`(brand 버튼·uppercase 섹션 라벨·8px 카드·brand 선택 카드·`done` success 진행률·KPI metric)을 실제 렌더로 시각 확인. v3 빌드도 사전 통과(엔진만 v4로 교체).
- **참고**: geo-ui 자체는 아직 v3. `hono` advisory는 shadcn CLI(devDep) 전이 의존으로 본 작업과 무관(런타임 미배포).

## 2026-06-20: T-083 완료 — 프로덕션 공개 도메인 구성(리버스 프록시 + TLS), 도메인 비밀 유지 (ADR-28)

- **배경**: 외부 노출 prod에서 5개 공개 도메인(Web, REST API, MCP, RustFS S3 API, RustFS 콘솔)으로 동작해야 한다. 단, 실제 도메인은 외부에 노출하지 않고(git 커밋 금지) gitignore된 `.env`(또는 `.env.production`)에만 둔다.
- **핵심 발견**: 앱은 이미 CORS/인증/RustFS 공개 URL/BFF origin/프록시 헤더가 전부 환경변수 기반이라 **백엔드/프론트 코드 변경이 없다**. prod 도메인 인지는 env + 리버스 프록시로만 처리한다. uvicorn은 `FORWARDED_ALLOW_IPS` env를 직접 읽으므로 CLI 변경도 불필요.
- **수정**:
  - `docker-compose.yml`: 하드코딩돼 있던 `RUSTFS_CONSOLE_URL`(127.0.0.1)을 `${RUSTFS_CONSOLE_URL:-...}`로 env-driven 전환, `NEXT_PUBLIC_API_BASE_URL`도 env-driven, `FORWARDED_ALLOW_IPS`(기본 `127.0.0.1`) 전달 추가. 로컬 기본 동작 불변.
  - `.env.example`: "프로덕션(외부 노출) 배포 예시" 섹션 추가(APP_ENV/API_KEYS/BACKEND_API_KEY/CORS/RustFS 공개 URL/FORWARDED_ALLOW_IPS/Caddy 도메인). **placeholder만**, 실제 도메인 없음.
  - `.env.production`(gitignore): 실제 도메인 + `APP_ENV=production` + 생성한 강한 `API_KEYS`/`BACKEND_API_KEY` + `s3-api`=공개 객체/`s3`=콘솔 매핑 + `MCP_WRITE_ENABLED=false`로 즉시 배포 가능한 prod env.
  - `deploy/Caddyfile`(커밋): Caddy `{$ENV}` 치환 기반 자동 TLS 프록시 샘플. 5개 도메인→고정 포트, MCP는 `flush_interval -1`(SSE off)·`basic_auth` **기본 ON**(미설정 시 커밋된 잠금 기본 해시로 fail-safe). **실제 도메인 없음**(`--envfile`로 `.env`에서 주입).
  - 문서: `docs/dev-environment.md` §11 prod + dev/prod 구분, ADR-28, `docs/tasks.md`, `CLAUDE.md` 현황/ADR 인덱스 갱신.
- **dev/prod 구분(사용자 지시 반영)**: prod는 `kor-travel-docker-manager`가 공식 도메인으로 올리고, dev는 여기에서 `127.0.0.1` + 같은 고정 12xxx 포트로 띄운다. 별도 지시가 없으면 dev를 의미한다.
  - 개발 스크립트 개선: `scripts/stop-fixed-ports.sh`를 "점유 시 새 포트로 바꾸지 않고 강제 종료 여부를 묻고, 거부하면 코드 3으로 중지(비대화형은 `FORCE_KILL_PORTS=1` 없으면 안전 중지)"로 재작성. `scripts/start-live.sh`는 거부 시 깔끔히 중지 + 기동 후 `127.0.0.1`/12xxx dev 주소 배너 출력. `verify-docker-compose.sh` health 체크/`NEXT_PUBLIC_API_BASE_URL`을 `127.0.0.1`로 통일.
- **RustFS 매핑 결정(사용자 확인)**: `s3-api.<base>`=S3 API/공개 객체 URL(`RUSTFS_PUBLIC_BASE_URL`), `s3.<base>`=콘솔(`RUSTFS_CONSOLE_URL`). 백엔드 boto3 연결은 내부 `host.docker.internal:12101` 유지.
- **자체 검증 워크플로(3 렌즈→반박 검증, 8 에이전트)로 발견·수정**:
  1. (medium) Caddyfile MCP `basic_auth`가 주석이라 MCP 읽기 도구가 익명 공개됨 → basic_auth 기본 ON + 잠금 기본 해시(fail-safe) + `.env(.example/.production)`에 `MCP_BASIC_AUTH_USER/HASH` 추가.
  2. (medium) 문서의 `docker compose --env-file .env.production` 대안이 `env_file: .env` 하드코딩 탓에 비밀 키를 누락 → compose `env_file` 경로를 `${APP_ENV_FILE:-.env}`로 override 가능하게 하고 문서를 `cp` 또는 `APP_ENV_FILE=... --env-file ...`로 정정.
  3. (low) Caddyfile `MCP_BASIC_AUTH_*` 변수 출처 미정의 → 두 env 파일에 문서화.
- **검증**: `docker compose config`(기본·prod env)로 substitution 유효성 확인, 커밋 산출물에 실제 도메인 미포함 grep 확인, bcrypt 해시 검증, bash 구문(`bash -n`) 확인. 실제 도메인 라이브 TLS 검증은 인프라(동적 DNS A 레코드·80/443 개방) 준비 후 수행한다.

## 2026-06-15: T-082 완료 — feature export `source_entity_id` 불변성 계약 테스트 (이슈 #84)

- **배경**: kor-travel-map concierge loader 검증 §5의 producer-side 권장(P-01 후속). consumer의 inactivate 매칭이 `source_record.source_entity_id`로 조인하므로, 한 후보의 upsert·reject/tombstone export가 동일 id를 가져야 reject/tombstone가 기적재 feature를 찾는다.
- **수정**: `backend/tests/test_feature_export_api.py`에 회귀 테스트 추가 — 한 후보를 upsert export → reject 전환 → reject export 했을 때 두 export의 `source_record.source_entity_id`가 byte 동일(`== str(candidate.id)`)함을 단언. 기존 `_build_payload`가 모든 operation에서 `str(candidate.id)`로 직렬화하는 불변성을 고정(회귀 방지). 코드 변경 없음(test-only).
- **검증**: backend pytest는 PostgreSQL/PostGIS disposable DB(WSL/Docker)에서 실행 — 기존 `test_changes_emits_reject_after_export`와 동일 전환 패턴.

## 2026-06-15: T-081 완료 — feature export `limit` 범위 검증(422) 추가 (이슈 #82)

- **배경**: `python-kor-travel-map`의 kor-travel-concierge loader conformance 검증(P-01)에서 발견된 producer-side 입력 검증 갭. loader 측 계약 정합(필드/스케일/operation lifecycle)은 모두 OK로 확인됐다.
- **문제**: `GET /api/v1/features/{snapshot,changes}`의 `limit`이 바운드 없는 plain int라, 범위 밖 값을 `feature_export_service.normalize_limit`이 조용히 clamp(`max(1, min(limit, 500))`)했다.
- **수정**: 두 endpoint의 `limit`에 `Query(ge=1, le=FEATURE_EXPORT_LIMIT_MAX)`를 추가해 범위 밖 입력을 명시적 **422**로 거부한다. `normalize_limit`은 방어적으로 유지. 범위 밖 → 422 회귀 테스트 2종 추가(`backend/tests/test_feature_export_api.py`).
- **영향 없음**: 현재 유일 consumer(kor-travel-map)는 limit을 `[1,500]`으로만 보낸다(settings `Field(ge=1, le=500)`).
- **검증**: backend pytest는 PostgreSQL/PostGIS disposable DB(WSL/Docker)에서 실행한다 — 변경은 표준 FastAPI Query 바운드이며 범위 밖 → 422 회귀 테스트로 고정.

## 2026-06-15: T-080 완료 — ETL 견고화: Gemini 503 재시도 + 자막 폴백 + 키워드 Gemini 연동 (이슈 #80)

- **배경**: live 운영에서 (1) Gemini POI 호출이 503(과부하)으로 간헐 실패, (2) yt-dlp/whisper 자막 폴백이 미구현 stub, (3) keyword expansion이 Gemini 키가 있어도 템플릿 폴백만 사용하던 잔여 기술부채.
- **Gemini 503 대책**: 공용 `ktc/etl/gemini_client.post_generate_content`(타임아웃/연결오류/429/5xx 지수 백오프 재시도, 비재시도 4xx 즉시 전파)를 추가하고 POI/deep_research/category/video_analysis(×2) 5개 호출부를 모두 이 헬퍼로 전환.
- **자막 폴백 구현**: `fetch_via_ytdlp`(yt-dlp 자막 다운로드 + WebVTT 파싱, 태그 제거·중복 병합), `transcribe_via_whisper`(faster-whisper 오디오 전사, `TRANSCRIPT_WHISPER_ENABLED`/`WHISPER_MODEL_SIZE` env로 opt-in) 실제 구현. transcript_api → yt-dlp → whisper 순.
- **키워드 Gemini 연동**: `make_gemini_keyword_generator`/`default_keyword_generator` 추가, `run_harvest`가 키 있으면 Gemini로 파생 검색어 생성(실패 시 템플릿 안전 폴백).
- **검증**: 신규 재시도/파서/키워드 회귀 테스트 추가, 영향 받은 ETL+scheduler pytest 77건 통과. compile/import OK.

---

## 2026-06-15: T-079 완료 — Gemini 엔진 옵션에 gemini-2.5-flash 추가 (이슈 #78)

- **배경**: live POI 추출에서 `gemini-flash-latest`(thinking)는 60s 타임아웃, `gemini-2.0-flash`는 429(키 쿼터). 사용자가 `gemini-2.5-flash` 사용을 요청.
- **작업**: `config.py`의 `GEMINI_ENGINE_OPTIONS`에 `gemini-2.5-flash` 추가(설정 검증 통과). api/scheduler 모두 이 목록으로 DB 모델값을 검증하므로 둘 다 재빌드 필요.

---

## 2026-06-15: T-078 완료 — 자막 fetch 복구: youtube-transcript-api 1.x 호환 (이슈 #76)

- **담당자**: Claude
- **증상**: `제주 6월 여행` 수집(job 565) 후 1개 영상 자막 시험에서 모든 영상이 "자막을 찾지 못해" 즉시(~10ms) 실패 → `travel_places` 0개.
- **근본 원인**: `fetch_via_transcript_api`가 `YouTubeTranscriptApi.get_transcript`(정적)를 호출하는데, 설치된 `youtube-transcript-api>=0.6.2`가 1.x로 해석되어 `get_transcript` 제거됨 → `AttributeError` → None. yt-dlp/whisper 폴백은 미구현 stub이라 폴백도 없었다.
- **수정**: `fetch_via_transcript_api`를 1.x 인스턴스 `.fetch()`+`.to_raw_data()` 경로로 갱신(구 `get_transcript`도 호환). 검증: 신 API로 `jBHdf2BpdTU` 22 segments 정상 fetch(일부 영상은 `TranscriptsDisabled`=실제 자막 없음). 신 API 경로 회귀 테스트 추가.
- **후속(선택)**: `fetch_via_ytdlp` 실제 구현으로 자막 비활성·차단 영상 커버리지 보강.

---

## 2026-06-15: T-077 완료 — transcript 부분집합 처리(품질 시험) (이슈 #74)

- **담당자**: Claude
- **배경**: 자막 생성은 비용/시간이 커서, 전체 실행 전에 일부(예: 1개) 영상으로 품질을 시험할 수 있어야 한다.
- **작업 내용**: `POST /api/v1/harvest/{job_id}/transcript`에 선택적 `TranscriptRequest.video_ids` 추가. 주면 수집 결과의 부분집합만 `transcript` 작업으로 만들고(수집에 없는 id는 400), 비우면 기존처럼 전체 처리.
- **운영 맥락**: 통합 스택은 docker-manager `env_file` 픽스(PR #16) 이후 외부 API 키가 주입되어 `제주 6월 여행` 수집(job 565, 영상 10개)이 성공했다. 본 변경으로 그 10개 중 1개만 먼저 자막 시험을 돌릴 수 있다.

---

## 2026-06-15: T-076 완료 — 자막생성 게이팅 + UI progress (이슈 #72)

- **담당자**: Claude
- **배경**: 자막 생성(자막·POI·지오코딩)은 비용/시간이 큰 단계인데, 기존엔 `harvest` 한 crawl_run이 수집 직후 자동으로 자막까지 실행했다. 사용자가 자막 생성 전에 진행 여부를 확인할 수 있어야 한다.
- **작업 내용 (backend)**:
  - `HarvestRequest.skip_transcript` 플래그 추가. `harvest_handler`가 이 플래그면 `process_harvest_videos`(자막)를 건너뛰고 `transcript_skipped`/`video_ids`만 반환.
  - 신규 엔드포인트 `POST /api/v1/harvest/{job_id}/transcript`: 수집된 `video_ids`로 `transcript` job_type crawl_run 생성.
  - scheduler에 `transcript_handler` 추가·등록 → `process_harvest_videos`로 자막/장소 추출 실행(단계별 status-log progress).
- **작업 내용 (frontend)**: `HarvestConsole`이 수집을 `skip_transcript`로 시작하고, 수집 완료 시 "자막 생성 시작" 확인 버튼을 노출. 클릭하면 transcript 작업을 만들고 진행바·현재 메시지·자막 상세 로그를 polling으로 표시. `lib/api`에 `startTranscript` 추가.
- **검증**: backend compile/import, `test_scheduler_worker`(skip_transcript·transcript_handler 신규 테스트 포함)+`test_api` pytest 통과, frontend lint+type-check 통과.

---

## 2026-06-15: T-075 완료 — E2E 안정화: 기동 시 stale Next/Turbopack 캐시 정리 (이슈 #70)

- **담당자**: Claude
- **배경**: Windows 호스트 Playwright E2E(ADR-23 예외)가 4개 스펙 모두 실패. 페이지가 수십 번 reload loop에 빠지고 설정 select가 `disabled`로 고정. 백엔드/BFF/API는 전부 200 정상이었고, 원인은 프론트 dev 서버였다.
- **근본 원인**: 리네임(T-073)·포트(T-074) 변경 churn과 느린 `F:` 드라이브가 겹쳐 `frontend/.next`(Turbopack) 캐시가 손상 → `FATAL ... Next.js package not found` panic → HMR 실패 → 페이지 무한 리로드 → 전 스펙 실패.
- **작업 내용**: `tests/scripts/start-frontend.mjs`가 dev 기동 직전 `frontend/.next`를 정리하도록 보강(hermetic clean 캐시 시작). 이슈 #70 등록.
- **검증**: `.next` 정리 후 즉시 4/4 통과(11.1s) 확인, 이어 수정된 런처(기동 시 자동 정리)로 재실행해 4/4 통과(40.0s, 클린 컴파일 포함). 디스포저블 `kor_travel_concierge_test` DB 대상이라 라이브 DB는 무관.

---

## 2026-06-14: T-074 완료 — 포트 대역을 통합 docker-manager 정책(126xx)으로 정렬

- **담당자**: Claude
- **배경**: `kor-travel-docker-manager`가 TripMate 계열 통합 로컬 인프라의 포트 정책(`docs/ports.md`, `config/docker-targets.yml`)을 정의하며, concierge에는 `conc` 대역 `12600-12699`(API `12601`, MCP `12602`, Web `12605`)가 배정되었다. 통합 스택은 이미 이 포트로 concierge를 빌드·기동하고 있었으나 concierge repo 자체 설정은 이전 `124xx` 값을 사용하고 있었다.
- **작업 내용**:
  - host 고정 포트를 API `12401→12601`(컨테이너 `8000`), MCP host `12402→12602`(컨테이너 내부 bind `12402`는 유지), Web `12405→12605`(컨테이너 `3000`)로 이관했다.
  - 적용 파일: `.env.example`, `docker-compose.yml`, `backend/ktc/core/config.py`, `backend/ktc/cli.py`, `backend/main.py`, `frontend/package.json`, `frontend/src/app/api/v1/[...path]/route.ts`, `scripts/start-live.sh`·`stop-fixed-ports.sh`·`verify-docker-compose.sh`, `README.md`, `SKILL.md`, `AGENTS.md`, `docs/architecture.md`, `docs/dev-environment.md`, `CLAUDE.md`.
  - 컨테이너 내부 MCP bind 포트(`MCP_PORT=12402`)와 참조 서비스 포트(PostgreSQL `5432`, RustFS `12101`/`12105`)는 이미 정책과 일치하여 유지했다.
  - 이력 문서(과거 journal/decisions/tasks 항목과 `CLAUDE.md` T-027/T-056 완료 요약)는 당시 사실이므로 보존하고, 결정은 ADR-27로 기록해 ADR-18/ADR-23의 `124xx` 고정 포트 값을 대체했다.
- **검증**: 전수 grep으로 host 포트 잔존 0건(컨테이너 bind `12402`와 이력 문서만 잔존), `docker compose config` 유효성, `kor-travel-docker-manager` `conc` 타깃 재빌드 기동 후 API `/health`·MCP `12602`·Web `12605` 확인.

---

## 2026-06-13: T-073 완료 — 배포명 및 Python import package 변경

- **담당자**: Codex
- **배경**: 사용자가 시스템 배포명을 `kor-travel-concierge`로 변경하고, GitHub 레포지토리명도 함께 변환하도록 요청했다.
- **작업 내용**:
  - 기존 백엔드 패키지를 `backend/ktc`로 이동하고 모든 내부 import를 `ktc.*`로 정렬했다.
  - 기존 별도 MCP 구현은 `backend/ktc/mcp_server`로 편입하고 `mcp/server.py` 호환 래퍼가 `ktc.mcp_server.server`를 호출하도록 변경했다.
  - 배포명, API title/root message, MCP server name, frontend/test package name, Docker/Compose 설명을 `kor-travel-concierge` 기준으로 맞췄다.
  - 환경 변수 접두사는 `KTC_*`로 정리하고, 기본 DB 이름은 `kor_travel_concierge`, RustFS 기본 버킷과 공개 URL 기준은 `kor-travel-concierge`, feature provider는 `kor-travel-concierge-youtube`, 장소 export 파일명은 `kor-travel-concierge-places-*`로 바꿨다.
  - 운영 CLI `ktcctl`을 추가하고 Docker Compose의 api/mcp/scheduler 실행도 같은 CLI 경로로 맞췄다.
  - `docs/tasks.md`, `README.md`, `SKILL.md`, `AGENTS.md`, `CLAUDE.md`, feature export 문서와 개발 환경 문서를 새 명칭 기준으로 갱신했다.
- **검증**:
  - GitHub REST API로 저장소명을 `digitie/kor-travel-concierge`로 변경하고, 로컬 `origin`도 `https://github.com/digitie/kor-travel-concierge.git`로 갱신했다.
  - `git ls-remote --symref origin HEAD`와 `gh repo view digitie/kor-travel-concierge`로 원격 기본 브랜치 `main` 응답을 확인했다.
  - WSL backend: `compileall`, `pytest -q backend/tests`, `ktc` import smoke → 통과
  - WSL frontend: `npm run lint`, `npm run type-check`, `npm run build` → 통과
  - WSL 정적/Compose: `docker compose config --quiet`, `git diff --check` → 통과
  - Windows host Playwright E2E: `cd tests; npx playwright test` → `4 passed`
  - 설정/문서 및 전체 tracked 파일에서 이전 프로젝트명, 이전 Python 패키지명, 이전 MCP 패키지명, 이전 export/mock bucket 명칭 잔여 검색 → 0건

## 2026-06-13: T-072 보완 — GitHub 저장소명 및 잔여 코드베이스 명칭 정렬

- **담당자**: Codex
- **배경**: 사용자가 GitHub 레포지토리 이름도 당시 중간 명칭으로 변경하는 작업을 진행하도록 요청했다.
- **작업 내용**:
  - 로컬 Git `origin`이 당시 중간 명칭의 GitHub 저장소 URL을 가리키고, 원격 `HEAD`가 정상 응답하는 것을 확인했다.
  - export 기본 파일명과 GPX/KML 생성자 명칭을 당시 중간 명칭 기준으로 정렬했다.
  - 테스트 fixture의 mock RustFS 버킷명과 라이선스 copyright 명칭을 당시 기준으로 보정했다.
  - 최신 문서의 MCP 패키지명 설명을 당시 실제 MCP 패키지와 맞췄다.
- **검증**:
  - `git ls-remote --symref origin HEAD` → `refs/heads/main`, 원격 응답 정상
  - tracked 파일 기준 잔여 이전 프로젝트명과 이전 MCP 패키지명 활성 참조 검색

## 2026-06-12: T-071 완료 — 고정 포트 계약 및 WSL 실행 위치 강제

- **담당자**: Codex
- **배경**: 사용자가 DB 표준 포트, RustFS 고정 포트, 이 repo API/MCP/Web 포트를 최종값으로 고정하고, Git과 Windows Playwright E2E를 제외한 모든 작업 명령을 WSL에서 수행하도록 요청했다.
- **작업 내용**:
  - PostgreSQL/PostGIS는 host `5432`, RustFS 외부 Docker 서비스는 S3 API `12101`·콘솔 `12105`, 이 repo 서비스는 API `12401`·MCP `12402`·Web UI `12405`로 정렬했다.
  - 기본 Compose 실행은 `api`/`mcp`/`scheduler`/`frontend`만 띄우고, RustFS는 `http://host.docker.internal:12101` 외부 서비스를 사용한다. `embedded-rustfs` profile은 선택형으로 남겼다.
  - `scripts/start-live.sh`와 `scripts/verify-docker-compose.sh`가 repo 소유 포트만 회수하도록 고쳤다. 기본 live 실행에서 이전 내장 RustFS 컨테이너가 남아 있으면 중지/제거하되 volume은 삭제하지 않는다.
  - 문서와 ADR을 WSL 실행 위치 강제 규칙으로 정렬했다. 예외는 `git` 명령과 Windows host Playwright E2E뿐이며, `gh`, Docker, Python, Node.js, 테스트, 빌드, 파일 검색은 WSL에서 실행한다.
  - 운영 DB `kor_travel_concierge`는 이미 현재 schema가 존재하지만 `alembic_version`이 없어 `alembic stamp head`로 `20260610_0006` 이력을 맞춘 뒤 `upgrade head` no-op을 확인했다.
- **검증**:
  - WSL backend: `python -m pytest -q backend/tests`, `python -m compileall backend/ktc backend/tests scheduler ktc.mcp_server` → 통과
  - WSL frontend: `npm run lint`, `npm run type-check`, `npm run build` → 통과
  - WSL 정적/Compose: `bash -n`, `docker compose config --quiet`, `git diff --check` → 통과
  - WSL Docker Compose smoke: 외부 RustFS health, API/Web health, MCP TCP, `verify_rustfs.py` 객체 저장 smoke → 통과
  - Windows host Playwright E2E: `npx playwright test` → `4 passed`
  - live Docker: `bash scripts/start-live.sh` 후 API `/health` `ok`, Web `12405`, MCP `12402`, RustFS `12101/health/live` 확인
  - in-app browser: `http://127.0.0.1:12405/`에서 `경주 맛집`·최대 영상 수 `2`로 `수집 시작` 클릭 → 실행 큐 `1`, job_id `13`, 상태 `running`, progress `10%` 표시, console error/warn 없음.

## 2026-06-12: T-069 완료 — 통합 검증과 운영 문서 정리

- **담당자**: Codex
- **배경**: T-061~T-070으로 이어진 PostgreSQL/PostGIS 전환, YouTube metadata/analysis/export, `python-krtour-map` consumer, TripMate feature 연계 POI 소비 흐름을 실제 실행 경로 기준으로 한 번에 검증하고 문서 상태를 완료로 닫는다.
- **작업 내용**:
  - T-062 이후 `youtube_videos.channel_id` FK가 생긴 상태에서도 Windows host Playwright seed가 통과하도록 `tests/scripts/seed_e2e.py`가 `YoutubeChannel` stub을 함께 적재하게 보정했다.
  - WSL Docker PostgreSQL/PostGIS disposable DB 3개(`kor_travel_concierge_t069`, `kor_travel_concierge_t069_compose`, `kor_travel_concierge_t069_e2e`)로 backend/unit/E2E/Compose 검증을 분리했다.
  - `python-krtour-map`은 기존 merged consumer를 수정하지 않고 unit provider smoke와 running `kor-travel-concierge` 대상 live `/api/v1/features/snapshot` pull smoke만 수행했다.
  - TripMate sibling repo는 기존 미커밋 변경을 건드리지 않고, feature 연계 POI와 notice plan POI schema/model이 `kor-travel-concierge-youtube` feature id/snapshot을 받아 snapshot fallback view까지 유지하는지 smoke로 확인했다. 이 과정에서 TripMate `trip_view_builder`가 non-UUID `feature_id`를 fresh fetch 대상으로 파싱하지 못한다는 경고가 출력됐지만, 현재 T-068에서 확정한 수동 선택 + 저장 snapshot fallback 경로는 정상 동작했다.
- **검증**:
  - feature export target: `tests/test_feature_export_api.py` → `9 passed`
  - backend 전체: `python -m pytest` → `198 passed`
  - backend compile: `python -m compileall app ..\scheduler ..\ktc.mcp_server` → 통과
  - shell/Compose 정합성: `bash -n scripts/verify-docker-compose.sh scripts/start-live.sh scripts/stop-fixed-ports.sh`, `docker compose config --quiet` → 통과
  - frontend: `npm run lint`, `npm run type-check`, `npm run build` → 통과
  - Docker Compose smoke: `SKIP_BUILD=1 bash scripts/verify-docker-compose.sh` with override ports → RustFS/API/frontend/MCP/RustFS object smoke 통과
  - Windows host Playwright E2E: `npx playwright test` → `4 passed`
  - `python-krtour-map`: `tests/unit/test_providers_kor_travel_concierge.py` → `9 passed`
  - live pull smoke: running backend `http://0.0.0.0:18082` + WSL consumer transform → `live_pull_ok 1 f_global_p_5894e112b38c3e3a 5 월정리 해변`
  - TripMate POI/notice plan smoke: schema/model/snapshot fallback → `tripmate_poi_notice_smoke_ok f_global_p_5894e112b38c3e3a 월정리 해변`

## 2026-06-11: T-068 TripMate feature 연계 POI/curated plan 소비 흐름 검증

- **담당자**: Codex
- **결론**: `kor-travel-concierge`는 TripMate DB에 직접 붙거나 자동 POI/curated plan 등록을 수행하지 않는다. YouTube 장소 후보는 `/api/v1/features/snapshot`·`/api/v1/features/changes`로 공급되고, `python-krtour-map`이 `kor-travel-concierge-youtube` provider로 이를 pull해 `feature_id`와 최종 `feature_snapshot`을 만든다. TripMate는 이 값을 자체 feature 연계 POI row(`app.trip_day_pois`, `app.notice_pois`)에 저장하고, curated plan은 그 POI row들의 모음으로 구성한다.
- **작업 내용**:
  - 공급자 정본 계약 문서 `docs/feature-export-api.md`를 추가했다. 계획 문서가 아니라 실제 API 계약의 기준 문서이며, top-level `{items,next_cursor,has_more}`, opaque cursor, `upsert`/`reject`/`tombstone`, `X-API-Key`, TripMate 소비 필드를 명문화했다.
  - `backend/tests/test_feature_export_api.py`의 ready 후보 fixture를 YouTube channel/playlist, 장소 설명, `category_code_suggestion`, 도로명 주소, Gemini URL evidence, VWorld/Kakao/Naver evidence까지 포함하도록 보강했다.
  - 새 회귀 테스트가 TripMate feature 연계 POI snapshot까지 이어지는 이름, 좌표, 8자리 카테고리 제안, marker 색상 기준(`P-13`), YouTube 영상·채널·재생목록 근거, transcript/Gemini evidence를 확인한다.
  - `docs/youtube-feature-pipeline-plan.md`, `docs/architecture.md`, `docs/decisions.md`, `README.md`, `CLAUDE.md`, `docs/tasks.md`를 자동 POI/curated plan 등록 없음·수동 선택 흐름 유지 기준으로 정렬했다.
- **검증**:
  - `KTC_TEST_PG_DSN=postgresql+asyncpg://addr:addr@localhost:5432/kor_travel_concierge_t068 backend/.venv/bin/python -m pytest -s backend/tests/test_feature_export_api.py` → `9 passed`
- **후속 상태**:
  - T-069 통합 검증과 운영 문서 정리에서 완료.

## 2026-06-11: T-067 `python-krtour-map` consumer 상태 확인 (이미 머지됨)

- **담당자**: Claude
- **결론**: T-067(krtour-map가 T-066 API를 pull해 `FeatureBundle`로 변환)은 `python-krtour-map` origin/main에 **이미 구현·머지**되어 있다. kor-travel-concierge 측 코드 변경은 없다.
  - PR #346(T-217a/b/f): `kor-travel-concierge-youtube` provider 변환(`kor_travel_concierge_items_to_bundles`, `make_feature_id`, `SourceRecord`/`SourceLink`에 YouTube payload·confidence·primary source role), Dagster fetcher 경로 `/api/v1/features/*` 중립화, `reject`/`tombstone` → feature `status='inactive'` 전환.
  - PR #347(T-217c/d/e), #345(T-217g): 제안 연동 합의·integration-map·RustFS·동기화 신선도 대시보드.
  - fetcher는 snapshot(full)·changes(incremental)를 opaque cursor와 `X-API-Key`로 pull한다.
- **process 메모(반성)**: 본 세션에서 `python-krtour-map`의 **stale·divergent 로컬 main**(origin에 없는 로컬 커밋)에서 분기해 T-217a/b를 처음부터 중복 구현했다. PR 생성 시점에 conflict/CI 미발화로 확인하다 origin/main의 #346과 중복임을 발견하고 중복 PR(#352)을 닫고 브랜치를 삭제했다. **교훈**: 형제 repo 작업 착수 전 반드시 `git fetch origin` 후 `origin/main` 기준으로 분기하고 기존 구현/머지 여부를 먼저 확인한다.
- **후속 상태**: 실제 live pull smoke(running kor-travel-concierge ↔ krtour-map)는 T-069 통합 검증에서 완료.

## 2026-06-11: T-070 후속 — 수동 `create_place` 경로 카테고리 코드 보강

- **담당자**: Claude
- **작업 내용**:
  - T-070은 자동 지오코딩 확정 경로(`geocode_service`)만 `category_code_suggestion`을 채웠다. 검수 큐에서 사용자가 신규 장소를 만드는 수동 `create_place` 경로도 채우도록 보강했다.
  - **주입형 selector로 layering 유지**: `place_service.resolve_candidate`에 `category_code_selector` 파라미터를 추가했다. services 계층이 etl을 직접 import하지 않도록, 실제 Gemini 선택기는 composition root가 주입한다. `category_suggestion.make_default_selector()`(Gemini 키 없으면 `None`)가 `(name, category_label, description, address) -> code|None` callable을 만든다.
  - **composition root 배선**: REST `POST /api/v1/destinations/unmatched/{id}/resolve`(`routes.py`)와 MCP `resolve_candidate`(`ktc.mcp_server/tools.py`)가 `make_default_selector()`를 주입한다. `create_place` 분기에서만 신규 장소에 코드를 채우고, `match_existing`은 기존 장소를 건드리지 않는다.
- **검증**: `localhost:5432` disposable DB에서 backend 전체 pytest **197 passed**(신규 place_service selector 2건 포함), compileall(`ktc.mcp_server` 포함), import 순환참조 없음(routes/MCP→etl 단방향).

## 2026-06-11: T-070 feature export `category_code_suggestion` 채우기

- **담당자**: Claude
- **작업 내용**:
  - **카테고리 코드표 복사**: `python-krtour-map`의 `krtour.map.category`(8자리 `AABBCCDD`, 144개)를 `backend/ktc/data/place_category_codes.json`으로 복사하고 provenance/동기화 기준(2026-05-25)·복사 사유를 헤더에 남겼다. 런타임에 `python-krtour-map`을 참조하면 provider↔consumer 순환참조가 되므로 복사로 끊는다(2026-06-11 결정). 카테고리는 거의 바뀌지 않아 복사본 drift는 수용 가능하다고 판단하며, 변경 시 JSON을 재동기화한다.
  - **카탈로그 로더**: `ktc/etl/category_catalog.py`가 JSON을 읽어 `is_known_code`/`label_for`/`selectable_categories`/`prompt_catalog`를 제공한다.
  - **Gemini 선택기**: `ktc/etl/category_suggestion.py`가 복사된 카탈로그를 Gemini에 보여주고 장소명·카테고리 label·설명·주소를 근거로 8자리 코드 하나를 고르게 한다(`poi_extraction`과 동일한 주입형 `LlmCallable` 패턴). 결과는 카탈로그에 존재하는 코드로 검증하고, 알 수 없는 코드·분류 미지정(`00000000`)·호출 실패는 `None`(제안 없음)으로 둔다(자동 확정 금지).
  - **저장·노출**: `TravelPlace.category_code_suggestion`(`String(16)`) 컬럼과 migration `20260610_0006`를 추가했다. `geocode_service.apply_geocode_to_candidate`가 장소 확정 시 기존 제안이 없을 때 한 번 채우며(생략 시 Gemini 키 유무 기반 기본 선택기, 명시적 `None`이면 제안 비활성), `feature_export_service` payload의 `category_code_suggestion`이 이 값을 노출한다(기존 하드코딩 `null` 대체).
  - **layering**: 선택기는 etl 계층에 두고 services→etl 역의존을 피했다. `feature_id` 생성은 여전히 `python-krtour-map` 책임이며, 수동 `create_place` 경로 보강은 후속으로 남긴다.
- **검증** (`localhost:5432` PostGIS disposable DB):
  - Alembic `upgrade head`(→`0006`), `downgrade 20260610_0005` → `upgrade` round-trip
  - Alembic offline SQL(`0005:head --sql`)에 `category_code_suggestion` 포함 확인
  - backend 전체 pytest → **195 passed**(신규 `test_category_suggestion` 13건, geocode/feature-export 추가 케이스 포함)
  - `compileall`, etl 패키지 import(순환참조 없음), `git diff --check`

## 2026-06-10: T-066 범용 full/incremental feature 수집 API 추가

- **담당자**: Claude
- **작업 내용**:
  - **`feature_exports` export ledger 추가**: `extracted_place_candidates`를 출처로 삼는 export ledger 모델(`ktc/models/feature_export.py`)과 Alembic migration `20260610_0005`를 추가했다. `export_id`(`ytpc_{candidate_id}`), 증가 cursor용 `sequence`(전용 PostgreSQL sequence `feature_export_sequence`), `operation`(`upsert`/`reject`/`tombstone`), `export_state`, `payload_json`, `payload_hash`(`sha256:` prefix), `last_exported_at`, `rejection_reason`, `created_at`/`updated_at`를 보존하고 `(export_state, updated_at, export_id)`·`sequence` unique·`candidate_id` unique·`payload_json` GIN 인덱스를 둔다.
  - **멱등 동기화**: `feature_export_service.sync_feature_exports`가 후보 상태로부터 ledger를 멱등 동기화한다. payload가 의미 있게 바뀐 export에만 `nextval`로 새 sequence를 부여해, 변화가 없으면 cursor가 안정적이다(반복 호출이 churn을 만들지 않음). 확정(`ready`/`exported` + matched place) 후보는 `upsert`, `ignored`/`rejected` 후보는 과거 export가 있을 때만 `reject`, 후보가 사라진 ledger row는 `tombstone`으로 전환한다.
  - **범용 수집 API**: `GET /api/v1/features/snapshot`(현재 활성 `upsert`만)과 `GET /api/v1/features/changes`(`upsert`/`reject`/`tombstone` 모두)를 추가했다. 응답 item은 `export_id`, `operation`, `candidate_id`, place/address/coordinate/category suggestion, YouTube video/channel/playlist evidence, transcript/Gemini evidence, `source_record`(provider `kor-travel-concierge-youtube`, `raw_payload_hash`), `updated_at`를 포함하고, 페이지는 opaque base64 cursor와 `next_cursor`/`has_more`로 노출한다. REST path에는 특정 consumer 이름을 넣지 않고 ADR-24 `X-API-Key` 인증을 그대로 적용한다.
  - **category code 보류**: `python-krtour-map` 8자리 category mapping 확정 전까지 `category_code_suggestion`은 `null`로 두고 `category_label`만 제안한다(`feature_id` 생성은 consumer 책임).
- **검증** (`python-kraddr-geo` PostgreSQL/PostGIS 서버 `localhost:5432`, disposable DB):
  - `DATABASE_URL=...kor_travel_concierge_alembic alembic upgrade head` → `20260610_0005`까지 적용, `downgrade 20260610_0004` → `upgrade head` round-trip 성공
  - Alembic offline SQL(`20260610_0004:head --sql`)에 `feature_exports` 포함 확인
  - T-066 타깃 pytest `tests/test_feature_export_api.py` → `7 passed`
  - backend 전체 pytest → `178 passed`
  - `compileall`, `docker compose config --quiet`, `git diff --check`

## 2026-06-10: T-065 장소 후보 schema 보강 및 외부 API evidence 저장

- **담당자**: Codex
- **작업 내용**:
  - **후보·매핑 provenance schema 추가**: `extracted_place_candidates`와 `video_place_mappings`에 `source_channel_id`, `source_playlist_id`, `analysis_run_id`, `source_kind`, `provider_evidence_json`, `feature_export_status`를 추가하고 Alembic migration `20260610_0004`를 작성했다.
  - **기존 데이터 backfill**: migration에서 기존 후보와 매핑의 `source_channel_id`를 `youtube_videos.channel_id`로 채우고, 이미 확정된 후보·매핑은 export 상태를 `ready`로 보정한다.
  - **transcript evidence 저장**: 자막 기반 후보 생성 시 channel, 첫 playlist, transcript asset/source/timestamp 근거를 JSONB에 저장한다.
  - **지오코딩 evidence 저장**: VWorld/Kakao/Naver 후보 목록, 선택 후보, decision reason/confidence, reverse VWorld 주소 보강 결과를 `provider_evidence_json.geocoding`에 남긴다.
  - **검수·매핑 상태 연결**: 자동/수동 확정 후보와 매핑은 `ready`, 검수 대기 후보는 `pending`, ignore 후보는 `rejected`로 둔다. reconcile 충돌 후보는 analysis run id와 reconcile evidence를 남기고 `pending`으로 유지한다.
  - **API/MCP 응답 보강**: FastAPI 검수 큐와 MCP candidate/mapping serializer가 provenance/evidence/export 필드를 반환한다.
  - **남은 확인 유지**: Google Places API 보강은 과금·저장 정책·라이선스 확인 전까지 구현하지 않았고, `python-krtour-map` 8자리 category mapping은 별도 작업으로 남겼다.
- **검증**:
  - `DATABASE_URL=postgresql+asyncpg://addr:addr@localhost:5432/kor_travel_concierge_test backend/.venv/bin/alembic upgrade head` → `20260610_0004` 적용
  - `DATABASE_URL=postgresql+asyncpg://addr:addr@localhost:5432/kor_travel_concierge_test KTC_TEST_PG_DSN=postgresql+asyncpg://addr:addr@localhost:5432/kor_travel_concierge_test PYTHONPATH=backend:. backend/.venv/bin/python -m pytest -s backend/tests/test_etl_summarize.py backend/tests/test_etl_geocode_service.py backend/tests/test_etl_video_analysis.py backend/tests/test_api.py backend/tests/test_mcp_tools.py` → `39 passed`
  - 같은 실제 PostGIS DSN으로 `PYTHONPATH=backend:. backend/.venv/bin/python -m pytest -s backend/tests` → `171 passed`
  - `backend/.venv/bin/python -m compileall backend/ktc backend/tests ktc.mcp_server backend/alembic scheduler`
  - `DATABASE_URL=postgresql+asyncpg://addr:addr@localhost:5432/kor_travel_concierge_test backend/.venv/bin/alembic upgrade head --sql`
  - `docker compose config --quiet`
  - `git diff --check`
- **다음 작업**:
  - T-066 범용 full/incremental feature 수집 API 추가.

---

## 2026-06-10: T-064 Gemini YouTube URL 요약과 transcript 비교·정리

- **담당자**: Codex
- **작업 내용**:
  - **공식 지원 범위 재확인**: Gemini API video understanding 문서를 2026-06-10 기준 확인했다. 공개 YouTube URL은 preview 기능이며 REST payload에서는 `file_data.file_uri`로 전달한다. 실제 Gemini 호출 smoke는 API 키와 할당량을 쓰지 않기 위해 이번 PR에서는 수행하지 않았다.
  - **URL summary 서비스 추가**: `backend/ktc/etl/video_analysis_service.py`를 추가해 YouTube URL 직접 분석 프롬프트, Gemini REST payload, JSON Schema 응답 파싱, `youtube_video_analysis_runs` 상태 전이를 한 곳에 모았다.
  - **reconcile 절차 추가**: transcript 기반 후보와 URL summary를 Gemini에 다시 비교 요청한다. 충돌·낮은 신뢰도·불확실 후보는 자동 확정하지 않고 `extracted_place_candidates.match_status = needs_review`와 `review_note`에 남긴다.
  - **scheduler 연결**: `video_analysis` handler가 T-063 placeholder를 넘어 `url_summary`와 `reconcile` pending run을 순서대로 실행한다. 실행 결과와 실패는 `youtube_video_analysis_runs`에 남기고, crawl_run 결과에는 실행·실패 건수를 요약한다.
  - **transcript summary 저장**: 기존 자막 기반 POI 추출 결과의 `summary`를 `youtube_videos.transcript_summary`에 저장해 reconcile 프롬프트의 입력으로 재사용한다.
- **검증**:
  - `python-kraddr-geo` PostgreSQL/PostGIS 서버(`localhost:5432`)에 disposable `kor_travel_concierge_test` DB 생성 및 PostGIS extension 확인
  - `DATABASE_URL=postgresql+asyncpg://addr:addr@localhost:5432/kor_travel_concierge_test backend/.venv/bin/alembic upgrade head`
  - `DATABASE_URL=postgresql+asyncpg://addr:addr@localhost:5432/kor_travel_concierge_test KTC_TEST_PG_DSN=postgresql+asyncpg://addr:addr@localhost:5432/kor_travel_concierge_test PYTHONPATH=backend:. backend/.venv/bin/python -m pytest -s backend/tests/test_etl_video_analysis.py backend/tests/test_scheduler_worker.py` → `21 passed`
  - 같은 실제 PostGIS DSN으로 `PYTHONPATH=backend:. backend/.venv/bin/python -m pytest -s backend/tests` → `171 passed`
  - `backend/.venv/bin/python -m compileall backend/ktc/etl/video_analysis_service.py scheduler/worker.py backend/ktc/etl/summarize_service.py backend/tests/test_etl_video_analysis.py backend/tests/test_scheduler_worker.py`
  - `backend/.venv/bin/python -m compileall backend/ktc scheduler backend/tests tests/scripts`
  - `DATABASE_URL=postgresql+asyncpg://addr:addr@localhost:5432/kor_travel_concierge_test backend/.venv/bin/alembic upgrade head --sql`
  - `docker compose config --quiet`
  - `git diff --check`
- **다음 작업**:
  - T-065 장소 후보 schema 보강 및 외부 API evidence 저장.

---

## 2026-06-10: T-063 주기 source_scan job 및 APScheduler persistent job store

- **담당자**: Codex
- **작업 내용**:
  - **source target 스케줄 필드 추가**: `source_targets`에 `video` target type과 `scan_interval_minutes`, `last_seen_cursor`, `last_seen_video_published_at`, `api_budget_group`, `scan_failure_count`, `last_scan_error`, `last_scan_at`를 추가하고 Alembic migration `20260610_0003`을 작성했다.
  - **주기 scan 서비스 추가**: `source_scan` handler가 active due target을 조회해 keyword/channel/playlist는 `harvest`, video는 `video_analysis` crawl_run으로 enqueue한다. 같은 target의 pending/running 작업이 있으면 중복 생성하지 않고 backoff 시각을 잡는다.
  - **분석 실행 row 준비**: `video_analysis` handler는 T-064가 소비할 `youtube_video_analysis_runs`의 `url_summary`/`reconcile` pending row를 중복 없이 만든다.
  - **APScheduler persistent job store 적용**: 기본 scheduler 실행 경로에서 PostgreSQL SQLAlchemyJobStore를 사용해 `crawl-run-worker`와 `source-scan-enqueue` interval job 정의를 `apscheduler_jobs`에 저장한다. 실제 작업 상태와 payload는 계속 `crawl_runs`가 source of truth다.
  - **범용 REST API 명명 정리**: T-066 계획을 `/api/v1/features/snapshot`, `/api/v1/features/changes`, `feature_exports` ledger 기준으로 고쳐 REST path에서 특정 downstream 이름을 제거했다.
- **검증**:
  - `python-kraddr-geo` PostgreSQL/PostGIS 서버(`localhost:5432`)에 disposable `kor_travel_concierge_test` DB 생성 및 PostGIS extension 확인
  - `DATABASE_URL=postgresql+asyncpg://addr:addr@localhost:5432/kor_travel_concierge_test backend/.venv/bin/alembic upgrade head`
  - `DATABASE_URL=postgresql+asyncpg://addr:addr@localhost:5432/kor_travel_concierge_test KTC_TEST_PG_DSN=postgresql+asyncpg://addr:addr@localhost:5432/kor_travel_concierge_test PYTHONPATH=backend:. backend/.venv/bin/python -m pytest -s backend/tests/test_scheduler_worker.py backend/tests/test_postgis_database.py` → `20 passed`
  - 같은 실제 PostGIS DSN으로 `PYTHONPATH=backend:. backend/.venv/bin/python -m pytest -s backend/tests` → `168 passed`
  - APScheduler SQLAlchemyJobStore smoke에서 `apscheduler_jobs_smoke` 테이블 생성 확인 후 제거
  - `backend/.venv/bin/python -m compileall backend/ktc scheduler backend/tests tests/scripts`
  - `DATABASE_URL=postgresql+asyncpg://addr:addr@localhost:5432/kor_travel_concierge_test backend/.venv/bin/alembic upgrade head --sql`
  - `docker compose config --quiet`
  - `git diff --check`
- **다음 작업**:
  - T-064 Gemini YouTube URL 상세 요약과 transcript 비교·정리.

---

## 2026-06-10: T-062 YouTube channel/video/playlist 정규 테이블 및 ingestion upsert

- **담당자**: Codex
- **작업 내용**:
  - **YouTube source 정규화**: `youtube_channels`, `youtube_playlists`, `youtube_playlist_videos`, `youtube_video_analysis_runs` 모델과 Alembic migration `20260610_0002`를 추가했다.
  - **기존 영상 테이블 보강**: `youtube_videos.channel_id`를 `youtube_channels.channel_id` FK로 승격하고, canonical URL, duration, thumbnail, 기본 언어, tags JSONB, Gemini URL summary, transcript summary, reconciled summary 컬럼을 추가했다.
  - **수집 적재 확장**: YouTube Data API의 `channels.list`, `playlists.list`, `playlistItems.list`, `videos.list` 응답을 channel/playlist/video/link metadata로 변환해 멱등 upsert한다.
  - **재생목록 provenance 저장**: playlist에서 발견한 영상은 `youtube_playlist_videos`에 위치, playlist item id, 추가·관측 시각을 남긴다.
  - **분석 이력 기반 준비**: URL summary와 transcript reconcile 작업을 `youtube_video_analysis_runs`에 저장할 수 있도록 run type/state, input asset, summary JSONB, confidence, 오류 필드를 마련했다.
- **검증**:
  - `backend/.venv/bin/python -m compileall backend/ktc backend/tests tests/scripts`
  - `backend/.venv/bin/alembic upgrade head --sql`
  - `backend/.venv/bin/python -m pytest -s backend/tests/test_etl_ingest.py backend/tests/test_etl_pipeline.py` → `7 passed, 14 skipped`
  - `docker compose config --quiet`
  - `git diff --check`
  - `backend/.venv/bin/python -m pytest -s backend/tests` → `60 passed, 102 skipped`
- **다음 작업**:
  - T-063 주기 `source_scan` job 추가.

---

## 2026-06-10: T-061 PostgreSQL/PostGIS 전환 및 Alembic bootstrap

- **담당자**: Codex
- **작업 내용**:
  - **DB runtime 전환**: `backend/ktc/core/database.py`에서 SQLite/SpatiaLite connect event와 경량 `schema_migrations` registry를 제거하고, `asyncpg` 기반 PostgreSQL async engine으로 전환했다.
  - **PostGIS 모델 보강**: `travel_places.geom geometry(Point, 4326)`를 ORM 모델에 추가하고, `sync_place_geometry`를 `ST_SetSRID(ST_MakePoint(...), 4326)` 기준으로 교체했다. 반경 검색은 `ST_DWithin`과 geography 거리 계산으로 바꿨다.
  - **작업 claim 보강**: `crawl_runs` claim을 PostgreSQL `FOR UPDATE SKIP LOCKED` 기준으로 정리했다.
  - **Alembic 도입**: `alembic.ini`, `backend/alembic/env.py`, 초기 migration `20260610_0001_postgres_postgis_bootstrap.py`를 추가했다. migration에는 PostGIS extension, 초기 테이블, GiST/FK/composite index를 포함했다.
  - **환경 정렬**: `.env.example`, local `.env`, Docker Compose, Dockerfile, E2E backend launcher를 PostgreSQL/PostGIS 기준으로 바꿨다. repo 내부 PostgreSQL 컨테이너는 추가하지 않고 `python-kraddr-geo` 서버를 외부 DB로 바라본다.
  - **테스트 경계 정리**: backend pytest fixture는 `KTC_TEST_PG_DSN`이 있을 때 disposable PostGIS DB를 만들고, 없으면 DB 테스트를 skip한다.
- **검증**:
  - `backend/.venv/bin/python -m pip install -r backend/requirements.txt`
  - `backend/.venv/bin/python -m compileall backend/ktc backend/tests tests/scripts`
  - `backend/.venv/bin/alembic upgrade head --sql`
  - `docker compose config --quiet`
  - `backend/.venv/bin/python -m pytest -s backend/tests` → `58 passed, 101 skipped`
- **다음 작업**:
  - T-062 YouTube channel/video/playlist 정규 테이블 및 ingestion upsert.

---

## 2026-06-10: T-060 PostgreSQL/PostGIS 전환 및 YouTube feature 공급 로드맵 문서화

- **담당자**: Codex
- **작업 내용**:
  - **DB 전환 결정 문서화**: ADR-25를 추가해 SQLite + SpatiaLite에서 PostgreSQL + PostGIS로 전환하고, `python-kraddr-geo`가 쓰는 로컬 PostgreSQL/PostGIS 서버를 재사용하되 별도 DB `kor_travel_concierge`를 쓰는 목표를 정리했다.
  - **YouTube feature 공급 계약 문서화**: ADR-26을 추가해 `kor-travel-concierge`가 YouTube 장소 후보 provider가 되고, 범용 `/api/v1/features/*` API를 full/incremental 방식으로 제공해 downstream consumer가 feature로 승격하는 경계를 정리했다.
  - **구현 로드맵 추가**: `docs/youtube-feature-pipeline-plan.md`에 YouTube channel/video/playlist 정규 테이블, `source_scan` job, Gemini YouTube URL 요약과 transcript 비교, 범용 feature export API, TripMate feature 연계 POI/curated plan 소비 흐름, 재확인 필요 사항을 상세히 작성했다.
  - **백로그 분할**: `docs/tasks.md`에 T-061~T-069를 대기 작업으로 추가해 DB 전환, YouTube metadata schema, 주기 scan, Gemini reconcile, 후보 보강, 범용 feature API, sibling repo consumer, TripMate feature 연계 POI/curated plan 검증, 통합 검증 순서로 나눴다.
  - **아키텍처 정렬**: `docs/architecture.md` 상단에 2026-06-10 전환 기준을 추가하고, 목표 DB와 feature 공급 흐름을 최신 결정에 맞춰 보강했다.
- **다음 작업**:
  - T-061 PostgreSQL/PostGIS 전환 및 Alembic bootstrap.

---

## 2026-06-09: T-059 PR #54 리뷰 반영 — same-origin BFF 프록시로 API 키 서버 전용화

- **담당자**: Codex
- **작업 내용**:
  - **BFF 프록시 도입 (P1-2)**: `NEXT_PUBLIC_*`는 빌드 시 브라우저 번들에 인라인되어 보안 경계가 못 되므로, 브라우저가 API 키를 더 이상 보내지 않도록 same-origin Next BFF(catch-all Route Handler `frontend/src/ktc/api/v1/[...path]/route.ts`)를 도입. BFF가 서버 사이드에서 백엔드로 프록시하며 서버 전용 `BACKEND_API_KEY`로 `X-API-Key`를 주입한다. 프록시 대상은 서버 전용 `BACKEND_ORIGIN`(Compose `http://api:8000`, 로컬 기본 `http://localhost:12401`).
  - **인증 환경 export 정상화 (P1-1)**: export 등 top-level navigation 다운로드는 fetch 헤더를 못 붙여 인증 환경에서 401이 발생했는데, BFF 경유로 키가 서버 사이드에서 주입되어 정상 동작한다.
  - **`NEXT_PUBLIC_API_KEY` 제거**: 해당 환경 변수를 삭제. `NEXT_PUBLIC_API_BASE_URL`은 기본 빈 값으로 두어 브라우저가 same-origin(`/api/v1`)으로 호출하게 하고, 백엔드 직접 호출 시에만 설정한다. 직접/외부(비-브라우저) 호출자는 여전히 `X-API-Key`를 직접 보낸다.
  - **문서 정렬**: `docs/decisions.md`(ADR-24 프론트엔드 연동·결과·보강 노트), `README.md`, `docs/dev-environment.md`, `AGENTS.md`, `CLAUDE.md`, `SKILL.md`, `docs/architecture.md`, `docs/tasks.md`를 BFF 기준으로 정렬.
- **다음 작업**:
  - 현재 등록된 대기 작업 없음.

---

## 2026-06-09: T-058 고정 host port 회수 런처 도입

- **담당자**: Codex
- **작업 내용**:
  - **결정 정정 (ADR-23/ADR-18)**: Compose host port를 표준 `8000`/`3000`으로 되돌린다는 이전 서술을 반전. host port는 고정 `12401`(API)/`12405`(Web)를 유지하고 컨테이너 내부는 `8000`/`3000`을 유지(host가 `12401→8000`, `12405→3000` 매핑)하는 것으로 문서를 정렬.
  - **포트 회수 런처 추가**: `python-krtour-map` 프로젝트에서 차용한 `scripts/stop-fixed-ports.sh`를 도입. 고정 포트 `12401`/`12405`를 점유한 리스너(Linux/Docker/WSL/Windows)를 정리한다. `scripts/start-live.sh`는 `docker compose up -d --build` 이전에 이 회수 스크립트를 먼저 실행해 이전 기동이 포트를 점유한 상태에서도 재시작이 성공하도록 보강.
  - **문서 정렬**: `docs/decisions.md`(ADR-23 결정·ADR-18 보강 노트), `docs/dev-environment.md`(§8 health check, start-live 설명, VWorld 도메인), `README.md`, `SKILL.md`, `CLAUDE.md`, `docs/tasks.md`의 host 접속 포트와 라이브 런처 설명을 고정 `12401`/`12405` 기준으로 정렬. 컨테이너 내부 포트(`uvicorn --port 8000`, `next` 3000)와 E2E 포트(`18080`/`13100`)는 그대로 유지.
- **다음 작업**:
  - 현재 등록된 대기 작업 없음.

---

## 2026-06-09: T-057 REST API 버저닝(`/api/v1`)과 외부 호출용 API 인증

- **담당자**: Codex
- **작업 내용**:
  - **버저닝 (ADR-24)**: 모든 REST 엔드포인트를 `APIRouter(prefix="/api/v1")` 아래로 이동. 운영 점검용 `GET /health`와 루트 `GET /`는 버전 없이 유지. 향후 비호환 변경은 같은 패턴으로 `/api/v2`를 추가.
  - **인증 코드 (`X-API-Key`)**: `ktc/core/security.py`의 `require_api_key` 의존성을 라우터 전체에 적용. 설정 `APP_ENV`(기본 `local`)·`API_AUTH_ENABLED`(기본 false)·`API_KEYS`를 추가해 로컬(`local/test/e2e`)은 무인증 우회, 비-local은 유효 키를 강제(키 미설정 시 안전 측 401).
  - **연동 정리**: `docker-compose.yml`이 `APP_ENV`/`API_AUTH_ENABLED`/`API_KEYS`를 전달(기본 로컬 친화). 브라우저는 same-origin Next BFF Route Handler(`/api/v1/*`) 경유로 호출하고 BFF가 서버 전용 `BACKEND_API_KEY`로 `X-API-Key`를 주입(키는 브라우저 비노출). E2E backend는 `APP_ENV=e2e`로 무인증. `main.py` 직접 실행은 host 고정 포트 `12401`에 바인딩(컨테이너 내부 uvicorn은 8000 유지, host `12401→8000` 매핑).
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
  - **host port 유지**: Compose 고정 host port `12401`(API)/`12405`(Web)를 유지(컨테이너 내부는 `8000`/`3000`이며 host가 `12401→8000`, `12405→3000`으로 매핑)하고, 더 이상 Windows 전용이 아닌 OS 중립 표준 host port로 정리. `docker-compose.yml`, `config.py`, `.env.example`의 API base URL·CORS 기본값을 고정 포트 기준으로 정렬.
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
  - **import 정렬**: `place_service`의 표준 라이브러리 import와 `ktc.models` import 순서를 정리.
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
  - **backend 단일 출처 추가**: `backend/ktc/core/config.py`에 `GEMINI_ENGINE_OPTIONS`와 `GEMINI_ENGINE_VERSION_DEFAULT`를 정의하고 `Settings.GEMINI_ENGINE_VERSION` 기본값도 이를 사용하도록 정리.
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
  - **검증**: keyword `publishedAfter` 전달과 playlist pagination 중단 테스트 추가. `backend/tests/test_etl_pipeline.py`, backend 전체 pytest, `python3 -m compileall backend/ktc backend/tests`, `git diff --check` 통과.
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
  - **검증**: 관련 export 테스트, backend 전체 pytest, `python3 -m compileall backend/ktc backend/tests`, `git diff --check` 통과.
- **다음 작업**:
  - PR #30 P2-2 증분 수집 미완 항목을 T-044로 승격해 처리한다.

---

## 2026-06-08: T-042 docker-compose CORS override와 Windows live 포트 종료 안전장치 보강

- **담당자**: Codex
- **작업 내용**:
  - **Compose CORS override 복구**: `docker-compose.yml`의 `CORS_ALLOW_ORIGINS`가 `.env` 값을 우선하도록 바꾸고, 기본값에 Windows live Web 포트(`12405` 또는 `FRONTEND_HOST_PORT` override), 로컬 개발 `3000`, Compose smoke `12405`, Playwright E2E `13100` origin을 포함.
  - **Windows live CORS 우선순위 정리**: `scripts\start-windows-live.ps1`도 현재 PowerShell 환경변수, `.env`, 기본값 순서로 `CORS_ALLOW_ORIGINS`를 적용하도록 변경.
  - **포트 종료 안전장치**: `Stop-PortOwner`가 포트 점유 프로세스의 command line 또는 executable path에서 현재 TripMate 워크트리 경로가 확인되는 경우에만 자동 종료하도록 보강.
  - **명시 강제 옵션 추가**: 다른 프로세스가 `12401` 또는 `12405`를 점유하면 중단하고, 의도한 종료일 때만 `-ForcePortKill`을 명시하도록 안내.
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
  - **기준값 확인**: `python-kraddr-geo-codex`의 RustFS 운영 기준이 S3 API `12101`, console `12105`, 기본 credential `rustfsadmin`, 로컬 운영 주체 `kraddr-geo-rustfs`임을 확인.
  - **로컬 credential 통일**: 현재 워크트리와 `kor-travel-concierge-live-test`의 `.env` RustFS credential을 `python-kraddr-geo` 기본값과 맞추고, 두 워크트리의 RustFS 블록이 동일한지 마스킹 diff로 확인.
  - **설정 표면 정리**: `.env.example`, README, `SKILL.md`, Docker Compose, `Settings`, RustFS init/verify 스크립트, scaffold `etl/media.py`가 호스트 `http://127.0.0.1:12101`, Docker 내부 `http://rustfs:9000`, 단일 `kor-travel-concierge` 버킷, `features/` prefix, public base URL `http://127.0.0.1:12101/kor-travel-concierge`를 쓰도록 정리.
  - **live-test 보강**: `kor-travel-concierge-live-test`에 빠져 있던 `RUSTFS_PUBLIC_BASE_URL`, `RUSTFS_DOCKER_ENDPOINT`, `RUSTFS_OBJECT_PREFIX`, `RUSTFS_REGION`과 관련 테스트 기대값을 반영.
  - **런타임 반영**: 실행 중이던 `kor-travel-concierge-rustfs-1`을 새 `.env` 기준으로 재생성해 컨테이너 credential도 `rustfsadmin`으로 맞춤.
  - **검증**: `docker compose --env-file .env config --quiet`, backend `.venv/bin/pytest --capture=no -q` 137건, `python3 -m compileall`, frontend `npm run lint`, `npm run type-check`, `npm run build`, RustFS `kor-travel-concierge/features/healthcheck/t014-smoke.txt` 객체 smoke, Playwright E2E 4건 통과.
- **다음 작업**:
  - PR #30 리뷰 종합 문서의 P0 후속 항목을 task로 승격해 순차 처리한다.

---

## 2026-06-08: T-032 harvest 후처리 장소 생성 연결 및 RustFS 설정 반영

- **담당자**: Codex
- **작업 내용**:
  - **장소 생성 본수정**: `pipeline.run_harvest`가 적재한 `video_ids`를 반환하고, scheduler `harvest` handler가 신규 영상의 자막 추출, Gemini POI 요약, 지오코딩 적용 후처리를 이어 실행하도록 `postprocess_service`를 추가.
  - **장소 목록 반영 보장**: 후처리에서 확정 가능한 후보는 `travel_places`와 `video_place_mappings`까지 생성하고, 모호하거나 공급자 키가 없는 후보는 `needs_review`로 남기도록 구성.
  - **상세 상태 로그 연결**: 자막 추출, RustFS 저장, Gemini 보정, 후보 생성, 위치 보정, 확정 장소/검수 대기 집계를 scheduler reporter로 기록해 작업 상태 타임라인에 남기도록 연결.
  - **RustFS 개발 설정 반영**: 로컬 venv/브라우저 기준 endpoint를 `http://127.0.0.1:12101`, Docker 내부 endpoint를 `http://rustfs:9000`, 단일 버킷을 `kor-travel-concierge`, object prefix를 `features`, 공개 URL 기준을 `http://127.0.0.1:12101/kor-travel-concierge`로 정리. 로컬 `.env`에는 제공된 개발 접속값을 반영하고, 추적 문서에는 secret placeholder만 유지.
  - **검증**: 관련 ETL/스케줄러 테스트 30건, backend pytest 137건, `compileall`, `docker compose --env-file .env config --quiet`, RustFS `kor-travel-concierge/features/healthcheck/t014-smoke.txt` smoke, Playwright E2E 4건 통과.
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
  - **live test 정리**: API `12401`, Web `12405`, RustFS `12101/12105`, Gemini/YouTube/VWorld/Kakao 키 smoke, Playwright 화면 검증을 clean worktree와 Windows 프로세스 기준으로 재확인.
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
  - **고정 포트 반영**: Windows live API 포트를 `12401`, Web 포트를 `12405`로 정하고 `.env.example`, backend 설정 fallback, frontend API fallback, Docker Compose host port 기본값을 갱신.
  - **실행 스크립트 추가**: `scripts/start-windows-live.ps1`을 추가해 `12401`/`12405` 점유 리스너를 먼저 종료하고 RustFS/API/Web을 고정 포트로 띄우도록 구성.
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
  - **RustFS 보존 설명 보강**: `subtitle`/`transcript` 자산이 `ktc-subtitles` 버킷을 공유한다는 점과 `MEDIA_RETENTION_POLICY`가 `media_assets.retention_policy`의 전역 기본값이라는 점을 명시.
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
  - **PostgreSQL/PostGIS 전환 기준 수립**: 확정 장소 100,000건, 영상-장소 매핑 1,000,000건, 반경 검색 p95 500ms 초과, 최근 7일 `database is locked` 재시도 10회 이상을 전환 검토 트리거로 문서화. 전환 시 변경 범위는 `ktc.core.spatial`과 `ktc.services.place_service` 중심으로 제한.
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
  - **RustFS 네트워크 분리**: Windows 호스트 URL은 `localhost:12101/12105`, 컨테이너 내부 endpoint는 `http://rustfs:9000`으로 분리. RustFS 기본 버킷 환경 변수와 무기한 보존 정책을 Compose 공통 환경에 포함.
  - **MCP Compose 실행**: 로컬 기본값은 `stdio`로 유지하고, Docker Compose에서는 `streamable-http` transport를 `0.0.0.0:12402/mcp`로 실행하도록 설정.
  - **시작 순서 보정**: API healthcheck를 추가하고 MCP/scheduler/frontend는 API healthy 이후 시작하도록 구성해 SQLite DDL race를 방지.
  - **DB 초기화 수정**: `aiosqlite` connect event에서 SpatiaLite extension loading을 `run_async` 경유로 수행하게 수정하고, 공간 컬럼 존재 검사에서 `scalar()`를 두 번 소비하던 버그를 수정.
  - **검증 자동화**: `scripts/verify-docker-compose.ps1`과 `scripts/verify_rustfs.py`를 추가. health, MCP port listening, RustFS 버킷 생성, smoke 객체 업로드·조회를 수행.
  - **빌드 최적화**: 루트와 프론트엔드 `.dockerignore`를 추가해 Docker build context를 root 6.47KB, frontend 1.34KB 수준으로 축소.
  - **실행 검증**: 기존 로컬 서비스가 기본 포트를 사용 중이라 `12101/12105`, `12401`, `12402`, `12405`으로 override하여 `rustfs`, `api`, `mcp`, `scheduler`, `frontend` 전체 실행 확인. RustFS/API/frontend HTTP 200, MCP port listening, RustFS 3개 버킷 smoke 객체 업로드·조회, SQLite DB 파일 생성 확인.
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
  - **패키지 구조 정리**: 외부 MCP SDK 패키지 이름과 로컬 `mcp/` 디렉터리 이름 충돌을 피하기 위해 실제 구현을 `ktc.mcp_server` 패키지로 분리. `mcp/server.py`는 기존 Docker Compose 명령을 보존하는 호환 래퍼로 유지.
  - **FastMCP 서버 등록**: `ktc.mcp_server.server.build_server`가 FastMCP 인스턴스를 만들고, `MCP_WRITE_ENABLED`에 따라 읽기/쓰기 도구를 등록.
  - **읽기 도구**: `get_harvest_status`, `search_existing_places`, `get_place_detail` 구현. 작업 상태 JSON, 장소 검색 결과, 영상 매핑·대표 프레임·후보 근거를 반환.
  - **쓰기 도구**: `harvest_travel_destinations`, `correct_place`, `merge_places`, `trigger_deep_research`, `review_unmatched_place`, `resolve_place_candidate` 구현.
  - **검증/감사/멱등성**: 모든 쓰기 도구에 Pydantic 입력 스키마, 필수 `idempotency_key`, `audit_logs` 기록, 동일 멱등 키 재호출 시 기존 결과 반환 적용.
  - **도메인 서비스 보강**: `place_service`에 장소 검색, 상세 조회 보조, 수동 보정, 중복 병합, 후보 검수 메타데이터 기록, 후보 해결(기존 장소 매칭·신규 장소 생성·제외)을 추가.
  - **실행 구조**: `Dockerfile.python`이 `ktc.mcp_server` 패키지를 복사하도록 갱신하고, MCP 서버는 시작 시 `init_db()` 후 설정된 transport로 실행.
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
  - **RustFS 저장**: 추출한 JPEG를 `AssetType.FRAME`으로 `ktc-frames` 버킷에 저장하고 `media_assets`에 URI·체크섬·크기·무기한 보존 정책 기록. `mapping_id`가 주어지면 `video_place_mappings.frame_asset_id`에 연결.
  - **원본 미디어 보존 helper**: 이미 확보한 원본 동영상 또는 오디오 bytes를 `AssetType.RAW_VIDEO`로 `ktc-raw-videos` 버킷에 저장하는 `store_raw_media` 추가.
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
  - T-009: `yt-dlp` 스트림 URL + FFmpeg Input Seeking 대표 프레임 추출, RustFS `ktc-frames` 저장.

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
  - scheduler가 import해 실행할 수 있도록 비동기 수집 파이프라인을 `backend/ktc/etl/` 패키지로 구현.
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
  - **공간 컬럼 관리(ADR-17)**: `ktc/core/spatial.py`가 `travel_places.geom` Point(4326)와 R-Tree 공간 인덱스를 ORM 밖 SpatiaLite DDL로 멱등 관리. `mod_spatialite` 미로드 환경에서는 graceful skip. `init_db`에 연결.
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
  - **백엔드 구조화**: `backend/ktc/` 패키지 도입.
    - `ktc/core/config.py`: `.env.example`의 모든 환경 변수를 1:1로 매핑한 `pydantic-settings` 기반 `Settings` 로더. (T-003: 환경 변수 이름 동기화 완료)
    - `ktc/core/database.py`: SQLAlchemy 2.0 + `aiosqlite` async 엔진, SpatiaLite 확장 로드와 WAL 모드 적용 지점 정의.
    - `ktc/core/logging.py`: API 키 마스킹 헬퍼.
    - `ktc/models`, `ktc/services`, `ktc/api`: 구현 대상 명시한 패키지 스캐폴드. `main.py`를 팩토리 패턴 + 라우터 조립 구조로 리팩터링.
  - **누락 디렉토리 생성**: `mcp/`(server + 읽기/쓰기 도구 메타데이터), `scheduler/`(단일 실행자 루프), `etl/media.py`(RustFS 저장 계층) 신설.
  - **Docker Compose 초안**: `frontend`, `api`, `mcp`, `scheduler`, `rustfs` 서비스와 SQLite/RustFS 데이터 볼륨, `Dockerfile.python`(공용 Python 이미지), `frontend/Dockerfile` 작성. RustFS는 별도 서비스로 분리(S3 API 12101, 콘솔 12105).
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
  - RustFS는 애플리케이션 컨테이너에 내장하지 않고 별도 로컬 Docker 서비스로 구동하며, S3 API `12101`, 콘솔 `12105` 포트를 기본 후보로 정리.
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
  - `kor-travel-concierge` 프로젝트의 기본 골격을 `maplibre-vworld-js`와 완벽히 호환되는 한글 문서 및 구조로 초기화.
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
    - `main` 브랜치 최초 생성 및 `.gitignore`, `.gitattributes` 커밋 후 원격 저장소(`https://github.com/digitie/kor-travel-concierge`)에 푸시 완료.
    - 현재는 `feature/project-bootstrap` 기능 브랜치에서 셋업 작업 진행 중.
- **다음 작업**:
  - `frontend/`, `backend/`, `etl/`, `tests/` 각각의 뼈대 설정 파일 배치 및 디렉토리 트리 구축 (T-003).
