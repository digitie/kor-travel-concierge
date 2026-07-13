# 개선 로드맵 2026-07 — 사용 편의성·속도·데이터 신뢰성·외부 API 실용성

- **작성일**: 2026-07-12 / **개정**: 2026-07-13 — Codex 리뷰(§10) 검증·반영
- **기준 코드**: 원 작성 `bc514cd`(§10 정정 — 이 커밋은 T-154 시점이며 T-155/156 미포함), Codex 리뷰 기준 `52e64d2`, 개정판 기준 `6fd63cc`
- **작성 방법**: 서브시스템 이해 분석 4건(프런트엔드·파이프라인·공급 API·문서 이력) → 적대적 검토 3건(① 사용 편의성, ② 속도, ③ 데이터 신뢰성+외부 API) → 검토별 사실 검증·가치 검증 교차 반박 6건 → 최종 판단 → 문서 자체 반복 리뷰 2회. 이후 **Codex 독립 리뷰**(§10 — 적대 3렌즈 + 교차 검증 2회)를 받아 그 사실 주장 22건을 별도 검증 에이전트 3개가 코드 대조로 전부 확인(CONFIRMED)했고, 2026-07-13에 본문(§0~§9)과 `docs/tasks.md`에 반영했다.
- **판단 원칙**: 사용자 지시대로 "최소 수정·기존 계약 유지보다 이상적인 방향"을 우선하되, (a) 사실 검증에서 확인된 코드 현실, (b) 1~2인 운영 소형 프로젝트 규모, (c) prod가 저사양 N150 호스트에 공개 노출돼 있고 실소비자(`python-krtour-map`)가 features API를 pull 중이라는 운영 현실은 존중한다. 큰 재설계는 채택하되 "측정 게이트"를 달아 낭비를 막는다.
- **문서 내 파일:라인 인용**은 기준 코드 시점의 값이다. 착수 시점에 라인이 밀렸을 수 있으므로 함수·식별자 이름을 우선 기준으로 삼는다.

---

## 0. 요약 (TL;DR)

**핵심 진단 4가지:**

1. **검수는 이 도구의 핵심 노동인데 "큐 처리"가 아니라 "목록 브라우징"으로 설계돼 있다.** 저장해도 다음 후보로 진행되지 않고, 행에 영상 제목·신뢰도·판정 사유가 없고, 검색·정렬이 없어 백로그를 소진할 수단이 없다. T-150→T-152→T-154→T-155/156의 4연속 수정은 전부 이 모델의 증상을 하나씩 누른 땜질이었다.
2. **느림의 원인은 직렬 3중 구조다.** 워커 1개가 작업을 직렬로(긴 poi_batch가 사용자 트리거 작업을 수십 분 막음), 작업 내부가 I/O를 직렬로(`asyncio.gather`가 제품 코드에 1곳뿐), rate limiter가 무료 티어 가정 기본값(RPM 10)으로 LLM을 필요 이상 직렬로 처리한다. 프런트는 "전량 로드 + 고빈도 중복 폴링"이 이를 증폭한다.
3. **데이터 신뢰성의 두 급소는 자막 수율과 자동확정 정밀도다.** 자막 실패 원인이 전부 `except Exception: return None`으로 소실돼 개선 근거를 못 만들고(실측 수율: no-whisper 3/27=11.1%, whisper 재실행 11/27=40.7% — 통제 A/B 아님, 현 production 수율 미확인), 지오코딩 단일 결과는 이름 검증 없이 confidence 1.0으로 자동확정된다(T-113 쓰레기 POI 전력). 시각 근거(OCR/비전)는 0이다.
4. **공급 API의 최대 리스크는 무스코프 인증이다.** 외부 공급용 키 하나로 `DELETE /destinations/{id}`, `POST /settings`, `POST /harvest`까지 전부 열린다. prod는 공개 도메인으로 노출돼 있다(ADR-28). 그다음이 `GET /features/snapshot`의 매 호출 전량 재동기화(O(N) 쓰기 부작용)다.

Codex 교차 리뷰(§10)가 추가 확정하고 코드 검증까지 마친 P0 두 가지: **후보 hard delete가 export tombstone·undo와 양립 불가**(FK가 ledger 선삭제를 강제해 tombstone 발행 경로가 원천 차단 — B1), **검수에서 선택한 provider 결과의 주소·출처가 저장 직전 유실되고 `api_source='manual'`로 남는다**(B2). 전체 추가 문제는 §1.5.

**최우선 착수(2026-07-13 개정)**: ① Phase -1 provider 정책·기준선(T-158) + 정확성 hotfix(exclude_video 컬럼 버그 T-159, 검수 provenance 보존 T-174, 목록 접근 수리 T-178), ② candidate soft delete 상태 모델(T-160), ③ API 키 스코프 + 소비자 read key 회전(T-175·T-176), ④ 원 Phase 0 항목(자동 다음 후보·재시작·레인·리미터·폴링 — 각 PR '개정' 항목 반영판). 순서 상세는 §4.

**전체 구성(개정)**: 10단계 / 독립 PR 35개(원 PR-01~28 + PR-20a + 신규 PR-29~34) — **Agent A/B 2트랙 병렬**(`docs/tasks.md` T-158~T-192와 1:1). 실행 순서·분배는 §4, 개별 지시는 §5(각 PR 블록의 "개정(2026-07-13)" 항목이 원 절차보다 우선).

---

## 1. 진단 — 무엇이 문제인가

아래 문제는 전부 적대적 검토 후 별도 사실 검증 에이전트가 코드를 직접 열어 재확인한 것이다. 구조적 주장에서 반증된 것은 없었고, 검증이 잡아낸 세부 수치·표현 오류(재시도 대기 상한, 리미터 env 조정 가능성, staleTime 예외 개수 등)와 과장 표현은 아래 표와 각주에 정정해 반영했다. Codex 리뷰가 추가 확정한 문제(전건 재검증 완료)는 §1.5에 통합했다.

### 1.1 사용 편의성 (검수·job·정보구조)

| # | 심각도 | 문제 | 근거 |
|---|---|---|---|
| U1 | P0 | **저장/제외 후 다음 후보로 진행되지 않고 선택이 목록 맨 위로 튄다.** `resolveMutation.onSuccess`가 `setSelectedId(null)` → `selected`가 `candidates[0]` fallback. 자동 검색·카테고리 프리필은 행을 다시 클릭해야(`pickCandidate`) 발동. 건당 3클릭이 실제로는 4~5 인터랙션 | `frontend/src/app/review/page.tsx:541-548`, `:298`, `:412-437` |
| U2 | P0 | **후보 행에서 영상을 식별할 수 없다.** 경량 payload에 영상 제목·채널명·신뢰도·생성일이 없고 raw `video_id`만 노출. 신뢰도·판정 사유가 안 보여 "쉬운 것부터/의심스러운 것부터" 전략이 불가능 | `frontend/src/lib/api.ts:121-132`, `review/page.tsx:1181`, `backend/ktc/api/routes.py:2304-2318` |
| U3 | P0 | **검수 큐에 텍스트 검색·정렬 선택이 없고 최신순 고정.** 오래된 후보는 영원히 묻힌다(FIFO 소진 불가). "더 불러오기"는 append가 아닌 limit 재조회(300→600이면 기존 300건 재전송) | `backend/ktc/services/place_service.py:903-937`, `review/page.tsx:95-97,172-179` |
| U4 | P0 | **실패한 job을 다시 실행할 방법이 UI에 없다.** `RunActionButtons`의 "다시 시작" 분기는 `running ?? pending`만 선택하는 `ActiveRunPanel`에만 마운트돼 실패 순간 사라진다. `restartRun` API와 mutation까지 전부 있는데 배선만 끊긴 죽은 코드 | `frontend/src/components/CollectWorkspace.tsx:111-114,541-572`, `frontend/src/lib/api.ts:688` |
| U5 | P0 | **키보드로 처리할 수 없다.** 행 Enter/Space 선택 외에 다음/이전·저장·제외 단축키 전무 | `review/page.tsx:1144-1149` |
| U6 | P1 | **undo가 없다.** 저장/제외는 낙관적으로 즉시 사라지고 IGNORED 후보를 되살릴 경로가 UI에 없다(reopen 엔드포인트 부재) | `review/page.tsx:520-535`, `place_service.py:699-` |
| U7 | P1 | **근거 컨텍스트 접근이 비싸다.** `timestamp_start`가 payload에 있는데 영상 링크에 `&t=`를 안 붙인다. 자막 근거 위치는 문자 비율 근사 스크롤 | `api.ts:129`, `review/page.tsx:815-822`, `CandidateDetailView.tsx:88-99` |
| U8 | P1 | **일괄 처리는 삭제뿐이고 그마저 개별 DELETE N회.** 일괄 제외·해외 정리 불가. 해외 숨김은 클라이언트 표시 필터라 limit 예산을 그대로 소모 | `review/page.tsx:250-254,216-222` |
| U9 | P1 | **job 실패가 조용히 사라진다.** 사이드바 배지는 running+pending만 집계 — 실패하면 배지가 오히려 줄어든다 | `frontend/src/components/JobStatusLink.tsx:32-34` |
| U10 | P1 | **`/jobs` 인덱스가 없다.** 목록은 `/status`의 탭(limit 80 고정, 필터 없음)이 담당하고 nav는 `/jobs/*`를 "상태"로 하이라이트 | `frontend/src/app/jobs`(디렉터리), `StatusDashboard.tsx:78`, `AppShell.tsx:33-35` |
| U11 | P1 | **필터·진행 상태가 URL에 없다.** sessionStorage+useState뿐이라 북마크·뒤로가기·탭 복제 불가. `?candidate=` 딥링크는 필터를 강제 해제 | `review/page.tsx:144-151,249,284-294` |
| U12 | P1 | **"다음 행동"을 안내하는 화면이 없다.** "검수 대기 N건"은 `/status`의 링크 없는 MetricCard 텍스트일 뿐 | `StatusDashboard.tsx:162-169`, `panels.tsx:86-98` |
| U13 | P2 | `/api-test`(개발자 도구)가 일상 nav 6칸 중 하나를 차지. `/status`는 시스템 건강+job+감사 로그 3역할 겸직 | `AppShell.tsx:20-27` |

**job 생성 축 판정**: 사용자가 지목한 4개 축 중 "job 생성"의 폼 자체(자동 인식 미리보기 + zod 형식 검증, `HarvestConsole.tsx:95-122`)는 적대적 검토에서도 "잘 만들어졌다"로 판정돼 **변경하지 않는다**. 남은 것은 생성 이후의 생명주기 문제(U4 재시작, U9 실패 가시성, U10 목록 홈)이며, P2 잔결함 2건은 기존 PR에 편입한다 — 죽은 `detailRun` 상태 제거는 PR-28 절차 4, run-queue 이중 폴링은 PR-06.

**구조 판정**: T-146이 limit을 500→2000으로 올렸다가 T-154가 300으로 되돌린 진동, 클릭 표면을 3회(T-140/155/156) 재정의한 이력은 "수천 행을 클라이언트로 가져와 테이블로 그린다"는 모델 자체가 원인임을 보여준다. 행 렌더를 아무리 최적화해도 **건당 처리 인터랙션 수는 한 번도 줄지 않았다.** 방향은 "서버가 큐를 소유하고, 처리하면 다음 항목이 온다"이다.

### 1.2 속도

| # | 심각도 | 문제 | 근거 |
|---|---|---|---|
| S1 | P0 | **단일 워커 + tick당 1건 claim.** 긴 poi_batch가 완주할 때까지 사용자가 방금 누른 재처리·deep research가 전부 뒤에 줄 선다. claim은 이미 `FOR UPDATE SKIP LOCKED`라 멀티 컨슈머 준비 완료인데 컨슈머가 1개 | `scheduler/worker.py:782-793,832-839`, `backend/ktc/services/crawl_run_service.py:147-152` |
| S2 | P0 | **파이프라인 I/O 100% 순차.** 제품 코드에 `asyncio.gather` 1곳(검수 place-search)뿐. 자막 fetch(영상당 5~30초)가 N회 순차, 지오코딩도 후보별 순차. `CRAWL_MAX_CONCURRENT_VIDEOS`/`HTTP_MAX_CONCURRENT_REQUESTS`는 참조 0회 사문화 설정 | `backend/ktc/etl/batch_poi_service.py:90-191`, `postprocess_service.py:178-208`, `config.py:210-211` |
| S3 | P0 | **rate limiter가 무료 티어 가정 기본값 + 60초 양자화 대기.** RPM 10/TPM 250k 기본값에, 토큰 추정(`chars//2+2048`)이 크면 잔여 윈도우 전체(최대 60초)를 통째로 대기. 유료 티어면 실쿼터 대비 최대 100배 보수적. env(`GEMINI_RATE_*`)로 조정 가능하지만 `.env.example`에 항목이 없어 사실상 아무도 조정하지 않음 | `backend/ktc/etl/gemini_rate_limiter.py:41,119`, `config.py:147-149` |
| S4 | P0 | **모든 화면에서 run-queue를 3초마다 2회 HTTP 폴링, `/collect`는 쿼리키가 달라 2초 주기로 이중 폴링.** mutation 성공 후 invalidate 없이 폴링 주기에 의존(재처리 반영이 최대 2초+) | `JobStatusLink.tsx:26-31`, `api.ts:547-558`, `CollectWorkspace.tsx:75-78`, `review/page.tsx:202-207` |
| S5 | P0 | **`/destinations`가 매 요청 전 테이블+전 매핑 로드 후 Python 필터·정렬 — 10초마다 refetch.** 응답은 기본 limit 100으로 잘리므로 **101번째 장소부터 결과 화면에서 아예 안 보이는 기능 버그**이기도 하다 | `place_service.py:153-200`, `routes.py:1035-1038`, `DestinationWorkspace.tsx:156` |
| S6 | P0 | **`GET /features/snapshot·changes`마다 후보·ledger 전량 재동기화 + 쓰기 커밋.** 소비자가 폴링할수록 서버가 자신을 공격. GET 멱등성 위반 | `backend/ktc/services/feature_export_service.py:313-326,453-458,473,486` |
| S7 | P1 | **지오코딩 캐시 전무.** 같은 장소가 영상 20개에 나오면 VWorld/Kakao/Naver를 20회씩 재호출. 100m 반경 재사용은 API 호출 후의 dedup | `backend/ktc/etl/geocoding.py`(캐시 없음), `place_service.py:94-109` |
| S8 | P1 | **120ms 지연 해킹.** 후보 선택 하이라이트가 검색 시작 렌더에 밀리는 것을 setTimeout(120)+nonce로 가림 — 근본 원인은 1,371줄 단일 컴포넌트의 상태 결합 | `review/page.tsx:414,428-434` |
| S9 | P2 | 전역 `staleTime 5s`로 정적 카탈로그성 데이터까지 화면 전환마다 refetch(1h 예외는 3곳뿐) | `QueryProvider.tsx:14` |

**정정 반영 사항**: (a) LLM 재시도 최대 대기는 195초가 아니라 ~105초(마지막 시도 후 sleep 없음, `gemini_client.py:113-117`), (b) T-121-E의 51분 실측은 240초 타임아웃 도입 전 hung 사고라 현행 배치 소요 근거로는 부적절 — 다만 직렬 큐 구조 문제 자체는 유효.

### 1.3 데이터 신뢰성

| # | 심각도 | 문제 | 근거 |
|---|---|---|---|
| D1 | P0 | **자막 확보가 단일 실패점인데 실패 원인이 전부 소실된다.** 3개 provider 모두 `except Exception: return None` — IP 차단, 자막 비활성, yt-dlp 파손이 전부 "자막 없음"으로 뭉개짐. 자막 없으면 영상 통째로 FAILED(설명 단독 경로 없음). E2E 실측 수율 27개 중 3개(11%). `TRANSCRIPT_PROVIDER_ORDER` 설정은 파서만 있고 미연결 사문화 | `backend/ktc/etl/transcript.py:86-87,178-179,240-241,255-256,265-269`, `batch_poi_service.py:134-139`, `docs/e2e-report-2026-06-20-ui-10videos.md:38` |
| D2 | P0 | **지오코딩 자동확정이 이름을 확인하지 않는다.** Kakao 키워드 검색 단일 결과면 무조건 matched/1.0. `_names_compatible` 검증은 100m 내 기존 장소가 있을 때만 발동 — **신규 장소 생성 경로는 무검증 통과.** T-113 라이브 점검에서 쓰레기 POI 자동확정 대량 발견 전력. FP가 export를 타고 downstream(PinVi)까지 전파 | `geocoding.py:393-401`, `geocode_service.py:117-131,139-163`, `docs/journal.md`(T-113) |
| D3 | P1 | **신뢰도 점수가 사실상 3단 enum, 추출 단계 신뢰도는 0.** 배치 POI 스키마에 confidence 없음. `confidence_score`는 지오코딩만 채움(1.0/0.7/0.3/1÷n). 임계선을 어디에 둬도 정밀도/재현율 조절 불가 | `backend/ktc/etl/batch_poi.py:47-70`, `geocode_service.py:101` |
| D4 | P1 | **좌표–행정구역 교차 검증 부재.** location_hint가 "대구 동성로"인데 서울 좌표로 확정돼도 경보 없음. LLM이 준 가장 싼 독립 검증 신호를 버리는 중 | `geocode_service.py:87-178`(location_hint 검증 참조 0회) |
| D5 | P1 | **시각 근거 축 실질 미가동.** 프레임은 OCR 없는 JPEG 1장(그마저 확정 매핑에만 연결, 검수 후보 시점엔 대체로 부재). 하드섭·간판·지도 오버레이 정보를 전부 버림. 리포 전체 OCR/vision 코드 0건 | `backend/ktc/etl/frame_extraction.py:75-81,163-208`, `models/video_place_mapping.py:76` |
| D6 | P1 | **변형 표기 병합 취약.** dedup이 `(video_id, official_name)` 완전 문자열 일치. "성심당/성심당 본점"이 별개 후보·별개 장소가 되고 언급 수가 흩어짐 | `batch_poi_service.py:244-262`, `geocode_service.py:181-203` |
| D7 | P2 | 자잘한 정합성 결함: yt-dlp 임의 vtt 폴백 시 실제 언어 무관 `language="ko"` 기록, `is_domestic` 불확실 시 true(해외 장소가 국내 지오코딩으로 흘러 D2와 결합 시 FP), 350k자 절단의 미통지 | `transcript.py:186-196`, `batch_poi.py:40-42`, `batch_poi_service.py:44,204-208` |

### 1.4 외부 API 실용성

| # | 심각도 | 문제 | 근거 |
|---|---|---|---|
| A1 | P0 | **공급용 키 하나로 파괴적 쓰기 전체가 열린다.** `require_api_key`가 라우터 전역 단일 의존성이고 키에 스코프가 없다. 키 유출 = `DELETE /destinations`·`POST /settings`·`POST /harvest` 전부 개방. prod는 공개 노출(ADR-28) | `routes.py:69`, `backend/ktc/services/public_api_key_service.py`(scope 컬럼 부재) |
| A2 | P1 | **`GET /features/snapshot`이 읽기가 아니다.** S6과 동일 — O(N) 재동기화+쓰기 커밋 | `feature_export_service.py:313-326,453-458` |
| A3 | P1 | **테마 API는 `limit=None` 전량 덤프.** 커서·updated_since·문서 없음. 수천 POI 규모부터 실사용 불가 | `backend/ktc/services/theme_service.py:101-124` |
| A4 | P1 | **공간·카테고리·기간 질의가 REST에 없다.** PostGIS 반경 검색은 구현돼 있으나 MCP 내부 도구로만 노출. bbox·8자리 코드·updated_since 파라미터 전무 → **처리: 백로그(§8)** — 실소비자 부재 + additive 추가라 지연 비용 0(§3.4) | `place_service.py:67-91`, `mcp_server/tools.py:29-31` |
| A5 | P2 | **계약 잔결.** export payload의 행정코드 3종이 하드코딩 None(실데이터는 존재 — themes는 노출하는데 features는 누락), item `schema_version` 없음, 공급 엔드포인트 전부 `dict[str, Any]` 반환이라 OpenAPI 응답 스키마 공백, 에러가 한국어 detail 문자열뿐, 키별 rate limit·last_used 없음, `is_geocoded=false` 장소도 export 포함 | `feature_export_service.py:170-173`, `routes.py:2043,2071,2092` |
| A6 | P2 | **MCP에 검수 후보 목록 조회 도구가 없다.** `resolve_place_candidate`가 있는데 candidate_id를 알아낼 방법이 MCP에 없어 단독 사용 불가 | `mcp_server/tools.py:23-36` |

---

### 1.5 Codex 교차 리뷰가 추가 확정한 문제 (2026-07-13, 전 항목 코드 재검증 완료)

| # | 심각도 | 문제 | 근거 |
|---|---|---|---|
| C1 | P0 | **후보 hard delete가 export tombstone·undo와 양립 불가.** `FeatureExport.candidate_id`는 non-null·unique·`ondelete="NO ACTION"` FK라 후보 삭제·영상 제외가 ledger 행을 먼저 지우는데, tombstone 발행 경로는 남아 있는 ledger 행만 순회한다 — 이미 export된 feature가 downstream에서 조용히 잔존하고 undo도 불가능 | `models/feature_export.py:73-78`, `routes.py:1425-1428`, `place_service.py:981-992`, `feature_export_service.py:395-404` |
| C2 | P0 | **`exclude_video`가 존재하지 않는 컬럼 `ExtractedPlaceCandidate.place_id`를 참조** — 매핑 있는 영상 제외 시 AttributeError 크래시(실제 컬럼 `matched_place_id`) | `place_service.py:1007` |
| C3 | P0 | **검수 선택 hit의 주소·provider가 저장 직전 유실.** `selectHit()`은 이름·좌표만 복사, resolve는 `api_source` 미전송 → 항상 `'manual'` 기록. Google/Kakao/Naver 결과가 VWorld 지도에 표시되고 `TravelPlace`로 영구 승격되는데 출처·주소가 안 남는다("검수 참고용" 전제 정정) | `review/page.tsx:438-444`, `api.ts:618-640`, `routes.py:171`, `place_service.py:777` |
| C4 | P0 | **사용자 `create_place`가 100m 내 첫 장소에 이름 검증 없이 병합.** `_names_compatible` 방어는 자동 geocode 경로에만 있다 | `place_service.py:752-767` |
| C5 | P1 | **category match 지연 응답이 다음 후보 폼을 덮어쓰는 race**(취소 토큰·identity 확인 없음) | `review/page.tsx:447-458` |
| C6 | P1 | **rate limiter가 교정·batch POI 2곳만 커버** — deep research·키워드 확장·검수 의견·카테고리·video analysis는 quota 예약 우회(모듈 docstring과 코드 괴리). row lock은 admission 카운팅만 하고 network call을 직렬화하지 않음 — PR-04의 "배치 레인 2개 금지" 원 근거 불성립 | `batch_poi.py:147`, `transcript_correction.py:34`, `gemini_rate_limiter.py:84-120` |
| C7 | P1 | **status_log parser가 timestamp/level/message/progress 4필드만 보존·80건 절단** — 단계별 구조화 측정(stage/elapsed_ms)을 status_log 주입으로는 달성 불가 | `crawl_run_service.py:24,31-83` |
| C8 | P1 | **`_names_compatible(a,b,c)`는 아무 한 쌍만 호환이면 true**(provider 결과 이름이 틀려도 통과 가능), `_normalize_name`은 공백+casefold만(특수문자 제거 없음 — §5 원 서술 정정) | `geocode_service.py:181-203` |
| C9 | P1 | **외부 provider 정책 게이트 부재** — YouTube 미디어 취득·저장(개발자 정책), Google Places 결과의 VWorld 지도 표시·영구 저장(표시·저장 정책), Naver NCP/Developers 제품 구분, provider별 cache 허용·TTL이 미확정인 채 PR-18/19가 취득을 확대 | §10 B4(공식 정책 링크 포함) |
| C10 | P2 | 사실 정정 모음: 자막 수율 실측은 3/27(11.1%)·11/27(40.7%)이며 "11~30%"는 무근거(통제 A/B 아님) · `TravelPlace`에 `sido_code` 컬럼 없음(sigungu·legal_dong만) · `GET /runs`에는 state·job_types 필터 기존재 · `GET /destinations` 실효 상한 500(프런트 limit 확장만으론 501번째 접근 불가) | `journal.md`(T-090/091), `travel_place.py:61-66`, `routes.py:631-647,1057` |

---

## 2. 최종 판단 — 채택·수정·기각

3개 적대적 검토의 제안을 사실 검증·가치 검증과 대조해 내린 결론이다. 쟁점이 있었던 항목은 판단 사유를 남긴다.

### 2.1 채택 (검토·검증 합의)

| 항목 | 반영 PR |
|---|---|
| 검수 저장 후 자동 다음 후보 + 자동 검색 (visibleCandidates 기준) | PR-02 |
| 영상 링크 `&t=` 타임스탬프 부여 | PR-02 |
| 실패 작업 재시작 배선(`restartRun` 기존재) | PR-03 |
| 워커 레인 분리(대화형/배치 2레인, 레인당 1 인스턴스) | PR-04 |
| rate limiter env 티어 현실화 + usage metadata 실측 로깅 | PR-05 |
| run-queue 단일 엔드포인트 + 쿼리키 통일 + mutation invalidate | PR-06 |
| 검수 목록 payload에 제목·채널·신뢰도·사유 스칼라 확장 | PR-07 |
| 검수 큐 서버 검색(`q`)·정렬(oldest/newest)·커서 append | PR-08 |
| reopen 엔드포인트 + 마지막 1건 undo + IGNORED 조회 | PR-09 |
| bulk ignore/delete 배치 API | PR-10 |
| 자막 실패 사유 코드 + `TRANSCRIPT_PROVIDER_ORDER` 연결 | PR-11 |
| 지오코딩 자동확정 이름·행정구역 불리언 게이트 | PR-12 |
| `evidence_quote` grounding 기계 검증 | PR-13 |
| 이름 정규화·dedup 완화·병합 반경 조정 | PR-14 |
| `startTransition`으로 120ms 해킹 제거 + 컴포넌트 분해 | PR-15 |
| description 단독 후보 경로(검수 전용) | PR-17 |
| `/destinations` SQL 푸시다운(101번째 버그 동시 수리) | PR-20 |
| 지오코딩 캐시 테이블 | PR-21 |
| API 키 read/admin 스코프 분리 | PR-01 |
| features 계약 마감(행정코드·schema_version·response_model) | PR-25 |
| themes limit 상한 + `include=sources` opt-in + 문서 | PR-26 |
| MCP `list_review_candidates` 읽기 도구 | PR-27 |
| LLM 호출 단일 async 게이트웨이 일원화(동기 호출 사고 4회 반복의 근본 수리) | PR-23 |
| 정적 카탈로그성 쿼리 staleTime 상향(S9) | PR-06 |

### 2.2 수정 채택 (쟁점 조정 — 판단 사유 포함)

**① 검수 "처리 모드(triage)" 재설계 + 키보드 흐름** — *채택하되 측정 게이트 부여* (PR-16).
UX 검토는 2모드 재설계를 본체로 제안했고, 가치 검증은 "PR-02(자동 다음 후보)가 핵심 가치를 이미 달성하므로 기각"을 주장했다. 최종 판단: **사용자가 명시적으로 '이상적 방향의 대대적 개편 허용'을 지시했고, 검수 큐를 4번 연속 땜질한 이력은 근본 재설계의 근거로 충분하다.** 다만 가치 검증의 회귀 위험 경고(가장 업무 크리티컬한 1,371줄 화면의 L 사이즈 재작성)는 타당하므로: Phase 0~1(PR-02~10) 적용 후 §7의 "건당 인터랙션 수·체감 소요"를 재측정하고, 그 결과로 PR-16의 범위를 "전체 triage 모드" 또는 "키보드 단축키만"으로 결정한다. 판정 기준: 건당 평균 인터랙션이 2를 초과하거나 마우스 왕복(목록↔폼↔결과)이 여전히 지배적이면 본안. **판단이 모호하면 본안(처리 모드) 채택이 기본값이다** — 사용자의 "이상적 방향 우선" 지시에 따라 게이트가 보수적 축소의 뒷문이 되지 않게 한다. 어느 쪽이든 키보드 단축키(포커스 가드 필수)는 수행한다.

**② 프레임 OCR/비전 보강** — *재설계 후 조건부 채택* (PR-19).
데이터 검토는 "POI 타임스탬프 프레임 vision 1콜"을 제안했고, 가치 검증은 논리 결함을 정확히 지적했다: **자막 없는 영상에는 POI도 타임스탬프도 없으므로 기존 프레임 추출로는 보완이 성립하지 않는다.** 그러나 사용자가 "이미지 OCR 보완"을 명시적 관심사로 지목했으므로 기각 대신 재설계한다 — 자막 최종 실패 영상 한정, 균등 샘플링 프레임 N장 → Gemini flash vision 1콜로 화면 텍스트(간판·하드섭·오버레이) 추출 → description 경로와 같은 검수 전용 후보 생성. 실험 플래그로 격리하고, PR-11이 만들 "원료 전무 영상 비율" 지표가 높게 유지될 때 착수한다(게이트). **게이트 시점에는 제3의 대안 — 기존 `video_analysis_service`(Gemini YouTube URL 직접 입력, T-064)를 자막 실패 영상의 원료 경로로 승격하는 안 — 과 반드시 비교 평가한다**: URL 분석은 영상+음성을 Gemini가 직접 처리해 CPU 비용 0·영상당 1콜로 같은 목적을 더 싸게 달성할 수 있는 기존 인프라이며, PR-05(유료 티어)로 쿼터 제약이 풀리면 유력해진다(실 키 smoke 미수행이 선행 과제).

**③ whisper 활용** — *기본화 기각, 수동 액션 채택* (PR-18).
whisper 기본 ON은 prod N150급 CPU에서 영상 1건 전사에 수 분~수십 분이 걸려 단일 배치 레인을 장시간 독점한다(T-121-E 유형 재발 위험). 대신 PR-11의 실패 사유 코드로 "자막 비활성 확정" 영상을 선별해 사용자가 명시적으로 실행하는 "whisper 재전사" 액션으로 노출한다. duration 상한(기본 20분)·model small 고정. 참고: STT 노동 없이 같은 공백을 메울 수 있는 Gemini URL 분석 승격안(위 ②의 제3안)이 PR-19 게이트 시점의 공동 평가 대상이며, 그 평가에서 URL 분석이 채택되면 whisper 액션의 역할은 축소될 수 있다.

**④ 합성 가중 신뢰도 점수(`0.4*name+0.3*region+...`)** — *기각, 불리언 게이트 + 2축 정렬로 대체* (PR-12/13).
가중치를 보정할 라벨 데이터가 없는 상태의 가중 합성은 가짜 정밀도다. 이름 호환(불리언)·행정구역 일치(불리언)·grounding 통과(불리언) 3개 게이트 + 기존 지오코딩 confidence로 자동확정과 검수 정렬 요구를 모두 충족한다. LLM 자가 보고 confidence는 기록만 하고 게이트에 쓰지 않는다. 검수 이력(승인/수정/제외)이 수백 건 쌓인 뒤 점수 구간별 승인율 테이블로 임계선을 재론한다.

**⑤ feature export sync 최적화** — *쓰기 지점 분산(sync_one) 기각, 스로틀+더티 필터 채택* (PR-22).
`sync_one`을 상태 전이 지점 4~5곳에 흩뿌리면 호출 누락 = 조용한 export 드리프트라는 정합성 리스크와 교환하게 된다. 실소비자가 pull 중인 정본 계약에서 자가 치유(전량 sync) 성질은 지켜야 한다. 대신 (a) GET 재진입 스로틀, (b) `updated_at` 워터마크 기반 더티 후보만 재해시, (c) 주기 전량 sync 안전망으로 같은 효과를 정합성 모델 불변으로 얻는다.

**⑥ 배치 내부 I/O 병렬화** — *자막 fetch만, 측정 게이트 후* (PR-24).
LLM이 지배항인 동안 자막 fetch 병렬화의 벽시계 효과는 제한적이고(Amdahl), yt-dlp 동시 다연발은 YouTube IP 스로틀을 자극해 수집 신뢰성을 해칠 수 있다. PR-04/05 적용 후 실측에서 비-LLM 시간이 여전히 지배적일 때만 Semaphore 2~3으로 자막 prefetch만 병렬화한다. 지오코딩 병렬화는 기각(PR-21 캐시가 더 싸게 같은 효과).

**⑦ `/jobs` 인덱스 신설 + IA 재편** — *채택* (PR-28).
가치 검증은 "기존 `/status` 보강으로 80% 효용"을 주장했으나, job 표면이 3화면(`/collect` 진행 패널, `/status` 탭, `/jobs/[id]` 상세)에 흩어져 있고 nav 하이라이트까지 왜곡된 현 IA는 사용자의 "이상적 방향" 지시 하에서 정리할 가치가 있다. 단 대시보드 전면 개편(`/`→`/places` 이동)은 검토자 스스로 제시한 차선책(기존 `/` 상단 행동 배너 1줄)을 채택하고 본안은 기각한다 — 근육기억·북마크·E2E 파괴 비용 대비 효용이 낮다.

**⑧ 해외 후보 일괄 제외** — *조건부 채택* (PR-10).
`is_domestic`은 LLM 판정이라 오판 위험이 있으나, PR-09(reopen + IGNORED 조회)가 가역성을 제공하고 건수 명시 확인 다이얼로그를 유지하는 조건으로 채택. 추가로 추출 단계에서 `is_domestic=false`를 자동 "보류"(IGNORED + review_note) 적재하는 파이프라인 옵션을 백로그에 둔다(자동 "확정"이 아니므로 ADR-16 위반 아님).

**⑨ URL 상태화** — *단독 PR 기각, PR-08에 편승*.
필터·정렬을 searchParams로 싣는 것은 PR-08 구현 시 거의 공짜다. 선택 후보 id는 URL에서 제외(저장마다 URL 갱신은 소음). `?candidate=` 진입 시 필터 강제 해제는 "필터 밖 후보" 배너로 완화.

### 2.3 기각 (사유 포함)

| 제안 | 기각 사유 |
|---|---|
| WebSocket/SSE 실시간 인프라 | 폴링 통합(PR-06)이 같은 체감을 1/10 비용으로 제공. 1~2인 운영에 연결 관리·프록시 설정 비용 부당 |
| 버전 카운터(`/events/version`) 폴링 | seq 증가를 전 쓰기 지점에 심어야 하고 한 곳 놓치면 UI가 조용히 갱신을 멈춘다. 폴링의 미덕은 멍청해서 안 틀리는 것 |
| LLM provider 이원 라우팅(교정=DeepSeek) | 유료 Gemini 티어(PR-05)면 효용 0. 이중 운영(과금·장애 도메인·한국어 교정 품질 미검증)은 유지보수 세금. PR-04/05 후 실측으로 Gemini 쿼터가 여전히 구속 조건일 때만 백로그에서 부활 |
| rate limiter 슬라이딩 윈도우 전환 | fixed-window의 "잔여 대기"는 Google 측 계산과 정합하는 정확한 최소 대기. 슬라이딩 전환은 과승인→429 위험 |
| `_ensure_row` startup 이동 | LLM 콜 10~60초 대비 수 ms 절약 — 측정 불가능한 마이크로 최적화 |
| Celery/Redis/PgQueuer 도입 | claim은 이미 SKIP LOCKED. 부족한 건 브로커가 아니라 컨슈머 레인 수. ADR-20 수치 트리거 원칙 유지 |
| 검수 큐 가상화(react-virtual) | 커서 append 후 1,000행+를 실제로 쌓는 패턴이 관측되고 버벅임이 보고될 때만. 지금 넣으면 PR-15 분해와 순서가 꼬임 |
| 검수 통계 페이지·저장 필터 프리셋·다인 협업 기능 | 사용자 1명. URL 파라미터+기본 정렬+검색 입력으로 충분 |
| 신뢰도 임계값 완화식 자동 확정 | 현행 점수는 변별력이 없어 임계 완화 = FP 직행. ADR-16(매칭 실패 자동 확정 금지)은 사용자 명시 결정 — 게이트(PR-12/13)로 자동확정의 "정밀도"를 올리는 방향만 허용 |
| MCP 자동 승인 에이전트 워크플로 | ADR-16 충돌 + 상시 LLM 비용. 검수는 사람이 있어야 할 유일한 자리. 목록 도구(PR-27)까지만 |
| Google Places 파이프라인 승격 | prod 403(Cloud Console 키 제한, 코드 외부 문제) + 재이용 약관·과금. 검수 화면 참고용 현 위치 유지 |
| features 에러 envelope 전면 재설계(`{"error":{...}}`) | 실소비자가 pull 중인 계약의 파괴적 변경. `code` 필드 additive 추가로 대체(PR-25) |
| LLM 다단 자기검증 체인(추출→검증→재검증) | 영상당 콜 수 증가는 처리량 붕괴. 검증은 비-LLM 신호(grounding·행정구역 대조) 우선 |
| pg_trgm GIN 인덱스 병합 | 확정 장소 수백 건 규모에 과잉. 정규화 개선(PR-14)이 대부분을 잡고, 중복 실측치가 남을 때만 재론 |
| 전 영상 whisper 무제한 전사 / 전 프레임 OCR 스캔 | N150 CPU·비용·단일 레인 점유 — §2.2 ②③의 게이트 방식으로만 |


### 2.4 Codex 리뷰 반영 판단 (2026-07-13)

Codex 리뷰(§10)의 BLOCKER B1~B7과 PR별 수정 의견을 **전건 수용**한다(사실 주장 22건을 검증 에이전트 3개가 코드 대조로 전부 확인 — 이견 없음). 이에 따른 판단 변경:

1. **PR-09(undo)**: hard delete 후 undo는 DB 제약상 불가(C1) → **candidate soft delete 상태 모델(T-160)이 선행**하고 undo/reopen은 그 위에 재설계.
2. **PR-22(export sync)**: process-local 스로틀·워터마크·플래그는 2프로세스·재시작에서 정본 불가 → **DB durable dirty outbox**로 재설계, B1 tombstone transaction 선행.
3. **PR-13(grounding)**: 교정본 대조·배지 표시 → **raw segment 대조 + `grounding_status` enum + 자동확정/export 차단 게이트**로 격상. 순서는 `PR-11 → PR-13 → PR-12 → PR-14`.
4. **PR-12(자동확정 게이트)**: `result_kind`(poi|address|coordinate) 구분 없이는 주소 결과가 이름 게이트를 오판(C8의 any-pair 문제 포함) → kind별 pairwise gate + `is_domestic` fail-closed + 명시적 지역 alias asset.
5. **PR-14(병합)**: 접미 제거·300m **자동** 병합 금지 → 병합 "제안" + 오병합률 표본 측정 후 provider ID·주소 일치의 좁은 경우만 자동화. auto-match audit 표본 큐를 함께 만들어 자동확정 정밀도 지표를 실측 가능하게 한다.
6. **PR-23(게이트웨이)**: Phase 5 → **실행 기반 단계로 이동**(PR-05와 통합). 리미터가 전 호출을 커버하지 않음(C6)이 확인됐으므로 gateway가 quota reservation까지 흡수한다. PR-04의 "배치 레인 2개 금지" 원 근거는 철회하되, 레인당 1은 운영 단순성·N150 사유로 초기 유지(게이트웨이+실측 후 재론).
7. **PR-03(재시작)**: 단순 배선이 아니다 — terminal 한정·멱등·`restart_of_run_id` lineage·attention 모델이 필요하고, ADR-34에 따라 `ConfirmActionButton`을 적용한다("확인 다이얼로그 없음" 철회). `failed_recent`는 attention 모델로 대체.
8. **PR-01(키 스코프)**: DB CHECK 제약·`key_hash→scope` cache·`?key=` read 한정을 추가하고, **완료 기준을 소비자(kor-travel-map) read key 회전·구 static key 제거까지**로 확장(B5). `/api/v1/admin/*`은 proxy 전용 유지("admin 키면 전부 200" 기대에서 제외).
9. **B7 목록 envelope**: `{items, next_cursor, has_more, total, newest_id}` + filter fingerprint cursor를 검수/작업/장소/테마 목록의 공통 계약으로 채택(features 기존 계약 불변). "새 후보 N건"은 `newer_than` count로.
10. **Phase -1(B4) 신설**: provider별 표시/저장/cache/attribution/TTL 정책 matrix와 kill switch가 PR-18/19·제한 provider 영구 저장의 release gate. 관측·보안·일반 UX 작업은 병행 가능.
11. **PR-21(캐시)**: 공통 60일 TTL 철회 → provider·endpoint·canonical params 키, 응답 4분류, positive/negative TTL 분리, 정책 matrix 허용 필드만.
12. **긴급 hotfix 신설**: `exclude_video` 컬럼 버그(C2, T-159), 검수 provenance 보존(C3~C5, T-174)은 로드맵 진행과 무관하게 최우선.

기각 유지 항목(§2.3)은 변동 없다. Codex도 2회차 교차 검증에서 자체 과잉 주장(NCP/Developers 약관 혼용, Kakao cache 전면 금지, grounding의 geocoding 선행 강제, YouTube 30일 규칙 확대해석)을 철회했다 — §10.1 참조.

---

## 3. 목표 상태 (이상적 설계)

### 3.1 검수: 브라우징에서 큐 처리로

- **서버가 큐를 소유한다.** 정렬 기본 선택지에 oldest(FIFO)를 제공하고, 커서 기반 append 페이지네이션으로 "전부 불러와 전부 렌더" 모델을 폐기한다. 자동 refetch 대신 "새 후보 N건" 배너(`newer_than` count)로 큐를 안정시킨다. 목록 응답은 공통 envelope(`total`·`newest_id` 포함)로 "끝"을 계약한다 — n/m·"모두 처리"가 거짓말하지 않게(B7).
- **처리하면 다음 항목이 온다.** 저장/제외/삭제 직후 다음 후보가 자동 선택되고 자동 검색이 발동한다. 마지막 1건은 항상 undo 가능하다.
- **행에서 판정에 필요한 정보가 보인다.** 영상 제목·채널·신뢰도·판정 사유(no_result/ambiguous/name_mismatch/region_mismatch/해외/description_only)·grounding 여부.
- **키보드로 1건을 끝낼 수 있다.** J/K(이동), 1~9(검색 hit), Enter(저장), X(제외), U(undo), /(검색 포커스) — 입력 필드 포커스 가드 필수.
- **근거가 한 클릭 안에 있다.** 영상 링크는 해당 타임스탬프로 열리고, 자막 발췌는 선택된 후보에 대해 지연 로드한다.

### 3.2 파이프라인: 직렬 3중 구조 해소

- **레인 2개**: interactive(사용자 버튼/API 발원 — 재처리·deep research·수동 transcript·수동 분석 트리거) / batch(스케줄러 발원 전부 — source_scan·harvest·poi_batch·스캔 발원 video_analysis). **기준은 job_type이 아니라 enqueue 지점이다**(같은 job_type이라도 발원에 따라 레인이 다르다 — 상세 매핑은 PR-04). 사용자 트리거 작업은 배치 뒤에 줄 서지 않는다. 프로세스 추가 없이 같은 스케줄러 안의 asyncio 태스크 2개.
- **LLM 쿼터가 유일한 진짜 병목이 되도록**: 실제 결제 티어 값을 env로 반영하고, usage metadata 실측을 로그로 남겨 추정 계수를 데이터로 보정한다. 그 후에도 비-LLM I/O가 지배적이면 자막 prefetch만 제한 병렬화한다.
- **읽기 경로는 SQL로**: 필터·정렬·집계·limit을 Python에서 하는 곳(`list_place_summaries`, `sync_feature_exports`)을 SQL로 내린다. PostGIS·인덱스는 이미 있다.
- **폴링은 통합·완화하고 mutation은 즉시 invalidate**: 유휴 요청을 ~1/6로 줄이면서 반영 지연은 오히려 없앤다.
- **LLM 호출은 단일 async 게이트웨이로**: 동기 SDK 호출이 이벤트 루프를 막는 사고(T-101/105/111/121-E 4회 반복)를 호출부 격리 반복이 아니라 `llm_client` 단일 경로 강제로 근절한다. 게이트웨이는 quota reservation(현 리미터는 교정·배치 2곳만 커버 — C6)·usage 실측·timeout·retry·multimodal 입력까지 한 계약으로 처리하며, **lane 처리량 조정·vision 확장보다 먼저** 완성한다(B6).

### 3.3 신뢰도: 2신호 게이트와 관측 가능성

- **자동확정 = 게이트 전부 통과**: 지오코딩 결과 존재 + 이름 호환(result_kind 구분 후 pairwise gate) + 행정구역 일치(location_hint 대조 — 검증 신호가 있을 때만 적용) + **raw grounding `verified_raw`**(교정본이 아닌 원본 자막 segment 대조 — B3). 어느 하나라도 실패하면 needs_review에 사유 코드를 남기고, transcript 후보는 verified_raw가 아니면 export도 차단한다(규칙 상세는 PR-12/13 개정판). 목표: **자동확정 정밀도 상승과 needs_review 비율 하락을 동시에** (지금은 ambiguous 다건도 전부 검수로 가지만, 이름+행정구역이 맞는 최상위 후보는 자동확정 가능).
- **모든 실패는 사유 코드를 남긴다**: 자막 provider별 실패 코드, 지오코딩 판정 코드, grounding 실패 — "왜 안 됐는지"가 곧 다음 개선의 우선순위 데이터다.
- **원료 다단화**: 자막(2단) → [수동 whisper] → description 단독 → [실험: 프레임 vision]. 자막 이외 원료 후보는 자동확정 금지·검수 전용으로 격리한다.
- **hallucination은 기계로 검증**: LLM에게 원문 인용(`evidence_quote`)을 강제하고 **raw 자막 segment**에 실존하는지 대조해 `grounding_status`(verified_raw|unverified|missing|not_applicable|legacy_unknown)로 저장한다. LLM 자가 confidence는 기록만.
- **후보는 감사 가능한 도메인 기록이다**: 물리 삭제 대신 soft delete(`deleted_at`·사유·행위자)와 같은 트랜잭션의 export tombstone 전이(B1). **ledger(`feature_exports`) 행 선삭제 금지.**

### 3.4 공급 API: 읽기 스코프와 계약 마감

- **키 스코프 read/admin 분리**가 외부 노출 prod의 최소 요건. 공급 GET은 read, 그 외 전부 admin. 완료 기준은 코드 merge가 아니라 **실소비자(kor-travel-map) read key 회전·구 static key 제거까지**다(B5).
- **GET은 읽기다**: snapshot/changes에서 상시 전량 재동기화를 제거(스로틀+더티 필터+주기 안전망), 응답 형식은 불변.
- **계약의 구멍을 막는다**: 행정코드 주입, `schema_version`, snapshot 페이징 중 재등장 규칙 문서화, response_model로 OpenAPI를 실계약 문서로.
- **themes는 성장 준비만**: limit 상한과 `include=sources` opt-in. bbox·updated_since·keyset은 소비자가 등장하면 additive로 추가(백로그).

### 3.5 정보구조(IA)

- nav 주 그룹: **결과 / 수집 / 검수 / 작업 / 설정**, 보조 그룹(하단): 상태, API 테스트.
- `/jobs` 인덱스 신설: 큐+이력(상태·유형 필터, 페이지네이션)+행 액션(중지/재시작). `/status`는 시스템 건강+감사 로그로 축소. `/collect` 진행 패널은 요약+링크로 축소.
- `/` 상단에 행동 배너 1줄: "검수 대기 N건 → [처리 시작]", "실패 작업 K건 → [보기]".

---

## 4. 실행 계획 — 단계·트랙·의존 관계 (2026-07-13 개정)

Codex 리뷰(§10.5)의 10단계 순서를 실행 계약으로 채택하고, 사용자 지시에 따라 **Agent A / Agent B 두 트랙**으로 분배한다. 태스크는 `docs/tasks.md` 대기 섹션(T-158~T-192)과 1:1이다. (원판의 7 Phase 구성은 이 절로 대체된다.)

### 4.1 실행 순서 — 10단계

| 순서 | 작업 묶음 | 핵심 산출물·종료 조건 | 태스크 |
|---|---|---|---|
| 1 | Phase -1 정책·기준선 | provider 정책 matrix·kill switch·RustFS/prod 키/Whisper runtime 인벤토리·기준선 정정 | T-158 |
| 2 | 정확성 hotfix | `exclude_video` 컬럼 수정, 검수 선택 provenance 보존, 101/501번째 목록 접근 수리 | T-159, T-174, T-178 |
| 3 | candidate 상태 모델 | soft delete·transactional tombstone·undo/reopen 백엔드·video exclude 통합(G1) | T-160 |
| 4 | API scope·rollout | read/admin DB 제약·cache·정확 경로 정책(G2), 소비자 read key 회전 | T-175, T-176 |
| 5 | job·LLM 실행 기반 | multimodal gateway·quota 실측, durable stage events·lineage·attention, 워커 레인 | T-161, T-162, T-163 |
| 6 | 서버 목록 계약 | envelope(total·newest_id·안정 cursor·fingerprint)·new count·filter snapshot bulk 원칙 | T-177 |
| 7 | 검수 UX | 자동 다음·타임스탬프·재시작 UI·폴링 통합·payload·서버 검색·undo UI·bulk·분해·단축키/triage | T-179 ~ T-187, T-180·T-181 |
| 8 | 자막 관측·raw evidence | transcript_attempts·수율 기준선 재설정·raw grounding 상태·whisper 정책·description 경로 | T-164, T-165, T-168, T-169 |
| 9 | 자동확정·identity gate | result_kind·pairwise name/region gate·fail-closed domestic·병합 제안·auto-match audit | T-166, T-167 |
| 10 | 측정 후 확장·성능·공급 마감 | 지오코딩 캐시·export outbox·자막 병렬화·OCR/vision·SQL 푸시다운·features/themes/MCP/IA | T-170~T-173, T-188~T-192 |

**고정 선행 관계** (병렬 시에도 불변):

- Phase -1(T-158)은 T-169(whisper)·T-173(vision)과 제한 provider 영구 저장의 **release gate**다.
- candidate 상태 모델(T-160)은 undo UI(T-184)·bulk(T-185)·export outbox(T-171)보다 먼저다.
- gateway·durable events(T-161·T-162)는 lane 처리량 조정·vision(T-173)보다 먼저다.
- `T-164(PR-11) → T-165(raw grounding) → T-166(identity gate) → 보수적 T-167(병합 제안)` 순서를 지킨다.
- 목록 계약(T-177)은 대규모 UI 재작성(T-183·T-187·T-192)보다 먼저다.

### 4.2 Agent A / Agent B 트랙 분배

| 트랙 | 담당 영역(파일 소유) | 태스크 순서 |
|---|---|---|
| **Agent A** — 백엔드 상태 모델·파이프라인·정책 | `backend/ktc/etl/*`, `backend/ktc/models/*`, `backend/ktc/services/`(파이프라인·export·상태 모델 함수), `scheduler/*`, `backend/alembic/*`, 정책·ADR 문서 | T-158 → T-159 → T-160 → T-161 → T-162 → T-163 → T-164 → T-165 → T-166 → T-167 → T-168 → T-169 → T-170 → T-171 → [게이트] T-172 → [게이트] T-173 |
| **Agent B** — 검수 UX·공급 API·보안 표면 | `frontend/*` 전체, `backend/ktc/api/routes.py`(검수·공급·목록 라우트와 직렬화), `backend/ktc/core/security.py`, `public_api_key_service`, `backend/ktc/mcp_server/*`, 계약 문서 | T-174 → T-175 → T-176 → T-177 → T-178 → T-179 → T-180 → T-181 → T-182 → T-183 → T-184 → T-185 → T-186 → [게이트] T-187 → T-188 → T-189 → T-190 → T-191 → T-192 |

**교차 선행(트랙 간 대기 지점)**:

- T-180(재시작 UI)·T-181(폴링 통합)의 lineage·attention 표시는 **T-162(A) 머지 후**.
- T-182(payload)의 grounding 노출은 **T-165(A) 머지 후**(그 전에는 나머지 필드만 먼저 가능).
- T-184(undo UI)·T-185(bulk)는 **T-160(A) 머지 후**.
- T-173(A, vision)은 T-158(A)·T-161(A)와 B4 승인 후.
- T-172(A, 병렬화)의 게이트 데이터는 T-162(A)의 stage events가 원천.

**파일 조정 규칙**: `place_service.py`·`routes.py`는 양 트랙이 겹친다 — 상태 모델·파이프라인 함수(resolve 내부 로직·geocode·export·삭제)는 **A**, 목록/검수/공급 라우트와 응답 직렬화는 **B** 소유로 하고, 같은 파일을 만질 때는 상대 트랙의 미머지 브랜치 유무를 확인한 뒤 착수한다. 한 에이전트가 순차 실행할 때는 §4.1의 10단계 순서를 그대로 따른다.

### 4.3 공통 실행 규약

- 각 태스크 = 하나의 `codex/*` 브랜치 = 하나의 PR(스택 금지), 머지 후 다음 착수.
- §5의 PR 사양을 따르되, **각 PR 블록의 "개정(2026-07-13)" 항목이 원 절차와 충돌하면 개정이 우선한다.**
- §7.1의 acceptance gate(G1~G10)가 해당 태스크의 완료 조건에 포함된다.

---

## 5. PR 단위 상세 작업 지시

각 PR의 공통 규약:

- **브랜치**: `codex/<pr-슬러그>` (예: `codex/api-key-scope`). main 직접 푸시 금지.
- **검증 기본셋**(해당 영역만): backend — `python -m compileall backend`, disposable DB(`kor_travel_concierge_test`) 기준 `pytest`; frontend — `npm run lint`, `npm run type-check`, `npm run test`(vitest), `npm run build`; 공통 — `git diff --check`. 명령은 WSL2(Ubuntu) bash에서 실행(ADR-33).
- **E2E**: 검수·수집·상태·작업 화면의 동작/셀렉터를 바꾸는 PR(특히 PR-02·03·06·08·09·10·15·16·28)은 `tests/e2e` 해당 스펙을 실행하고 필요 시 갱신한다(n150 live/Linux 우선, 불가 시 Windows 호스트 fallback — ADR-33).
- **schema 변경 시**: Alembic revision 추가 + upgrade/downgrade 검증(`alembic upgrade head`), 모델과 migration 양쪽 반영.
- **문서 의무**(각 PR마다): `docs/journal.md` 역시간순 항목, `docs/tasks.md` 완료 항목(T-NNN 채번), 계약 변경 시 `docs/feature-export-api.md`, 결정 변경 시 ADR.
- **금지**: features API 응답 형식·cursor 의미 변경, `source_entity_id` 불변성 위반, RustFS 객체 자동 삭제, 매칭 실패 후보의 무게이트 자동 확정.
- **개정 우선**: 각 PR 블록의 "**개정(2026-07-13)**" 항목은 해당 블록의 원 절차와 충돌 시 우선한다(§10 반영). ledger 행 선삭제·raw grounding 미확인 자동확정은 어떤 PR에서도 금지(§6-13·14).

---

### 신규 항목 — Phase -1·긴급 hotfix·실행 기반 (2026-07-13 추가)

#### PR-29. Phase -1 — 외부 provider 정책·데이터 권리 게이트 `[정책 P0]` `[M]` — T-158

- **해결**: C9/B4. **T-169(whisper)·T-173(vision)·제한 provider 영구 저장의 release gate.**
- **산출물**: (a) provider(YouTube / Google Places / Naver — NCP Maps와 Developers Local Search 구분 / Kakao / VWorld)별 `표시 / 지도 / 영구 저장 / 임시 cache / attribution / 외부 export / 허용 TTL / 약관 버전·확인일` matrix 문서(`docs/provider-policy.md` 신설, §10 B4의 공식 링크 근거 사용). (b) production kill switch — 원본 미디어 다운로드·Google 결과 표시/저장·provider cache 각각 env 플래그(기본 안전측). (c) 인벤토리 — RustFS 기존 asset 목록, prod `API_KEYS`/`BACKEND_API_KEY` 사용 주체, `TRANSCRIPT_WHISPER_ENABLED`·`WHISPER_MODEL_SIZE` runtime 값(.env.production은 gitignore — **사용자 확인 필요 항목으로 표시**). (d) ADR-15(원본 미디어 무기한 보존) 재검토 ADR 초안 — **기존 객체 삭제는 하지 않는다**(사용자 결정 사항).
- **완료 기준**: matrix에 근거 링크·확인일 기재, G10 항목 개시.

#### PR-30. `exclude_video` 컬럼 버그 hotfix `[버그 P0]` `[S]` — T-159

- **해결**: C2. `place_service.py:1007`의 `ExtractedPlaceCandidate.place_id` → `matched_place_id` 수정.
- **테스트**: 매핑 보유 영상 제외 시 AttributeError 재현 → 수정 후 통과. 이 경로의 ledger 선삭제 문제는 건드리지 않는다(T-160 소관 — 크래시만 수리).

#### PR-31. 검수 선택 provenance 보존 `[신뢰성 P0]` `[M]` — T-174

- **해결**: C3·C4·C5/B2.
- **작업 절차**: (a) 선택된 `PlaceSearchHit` 전체를 typed state로 보존(폼 숨은 문자열 금지). (b) provider native ID·검색 query·검색/선택 시각·원본 이름/주소/좌표/카테고리·reviewer를 resolution evidence(JSONB)에 기록 — provider 원본과 사용자 수정 최종값 분리. (c) 허용 provider에 한해 `official_address`/`road_address`/`api_source`를 resolve payload에 전달(**Google은 PR-29 정책 결정 전 저장 차단이 기본**). (d) `create_place` 근접(100m) 병합에 identity gate — 이름·provider ID·좌표 비교, 불확실하면 "기존에 합치기 / 새로 만들기"를 사용자가 선택. (e) category match 응답에 candidate/request identity 확인 또는 abort — 늦은 응답이 다음 후보 폼을 덮어쓰는 race(C5) 제거.
- **완료 기준**: G3.

#### PR-32. 목록 공통 envelope 계약 `[UX·속도 P1]` `[M]` — T-177

- **완료(2026-07-13)**: 네 목록에 `newer_than`을 포함한 공통 envelope, watermark keyset·filter
  fingerprint cursor, page 밖 상세 조회와 별도 `REPEATABLE READ` session을 적용했다. 프런트 호환
  wrapper는 기존 화면을 보존하고 features 계약은 변경하지 않았다. 301/501건 acceptance와 n150
  backend·frontend·Playwright 검증을 통과했다.
- **해결**: B7. features의 기존 `{items,next_cursor,has_more}` 계약은 **불변**.
- **작업 절차**: 검수(unmatched)·작업(runs)·장소(destinations)·테마(themes) 목록에 `{items, next_cursor, has_more, total, newest_id}` envelope 적용(backend 계약 + 테스트 PR — 프런트 전환은 각 후속 태스크). `total`은 cursor 적용 전 현재 filter 전체 건수. 정렬은 동률 tiebreak 포함 안정 keyset, cursor에 sort·filter fingerprint를 넣어 다른 filter에 재사용 불가. "새 항목 N건"은 `newer_than_id` count. page 밖 대상은 detail 단건 직접 조회 보장.
- **완료 기준**: G5(301/501건 fixture).

#### PR-33. 소비자 read key 회전 rollout `[보안 P0 운영]` `[S]` — T-176

- **완료(2026-07-13)**: DB read key를 Map Dagster·daemon에만 주입하고 Map API에서는 제거했다.
  n150에서 snapshot/changes 각각 8페이지·1,416개 전체 순회와 실제 Dagster 가져오기 경로, read 공급 GET 200·
  write/내부 GET 403, 구 정적 admin 401·신규 BFF/operator admin 200을 확인한 뒤 구 값을 제거했다.
- **해결**: B5 완결(A1의 실질 해소). 선행: PR-01(T-175).
- **절차**: DB read key 발급 → `kor-travel-map`(형제 저장소 — 과거 문서의 `python-krtour-map` 명칭 정정, `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_API_KEY` 사용) 인증 정보 교체 → snapshot/changes 다중 페이지 확인 → read key로 write 403 확인 → 구 consumer 정적 key를 `API_KEYS`에서 제거 → BFF/operator key와 consumer key 분리 확인. runbook에 되돌리기 가능 구간·제거 시점 기록(키 값은 문서·로그에 쓰지 않는다).
- **완료 기준**: G2 마감.

#### PR-34. durable stage events + restart lineage·attention `[관측 P0]` `[M]` — T-162

- **해결**: C7/B6. §7 지표·T-172 게이트의 데이터 원천이며 T-180·T-181의 선행.
- **작업 절차**: (a) `crawl_run_stage_events`(run_id FK, stage, provider, attempt, started_at, finished_at, elapsed_ms, outcome, detail) 테이블 + poi_batch/harvest handler 계측. `status_log_json`은 4필드 요약 view로 유지(parser 불변 — C7 검증). (b) `crawl_runs.restart_of_run_id` self FK + index — 재시작 lineage, 같은 원본의 중복 클릭 멱등(원본당 active 1). (c) attention 모델 — 최신 leaf attempt 기준 `open|acknowledged|superseded|resolved|none`, 재시작 성공 시 원본 실패를 superseded/resolved로 전이, 별도 acknowledge API.
- **완료 기준**: G6·G7의 데이터 기반 성립.

---

### Phase 0 — 즉효·안전 (원판 — 각 PR의 "개정" 항목 우선)

#### PR-01. 공개 API 키 read/admin 스코프 분리 `[보안 P0]` `[S/M]`

> **개정(2026-07-13, §10 반영)**: B5 반영 — scope는 TEXT+CHECK(또는 동등 DB 제약), 현행 hash 집합 cache를 `key_hash → scope` cache로 교체(+revoke·scope 변경 시 무효화), `?key=` 쿼리 파라미터는 read 전용(admin은 header/proxy만), `/api/v1/admin/*`은 proxy 전용 유지 — "admin 키면 전부 200" 테스트 기대에서 제외. read 표면은 명시적 policy/dependency 등록 + deny-by-default 테스트. **완료 기준은 T-176(소비자 read key 회전·구 static key 제거)까지** — static key 호환은 migration window이지 최종 상태가 아니다.

- **해결**: A1 (키 유출 = 전체 파괴 가능).
- **변경 파일**: `backend/ktc/models/public_api_key.py`, `backend/alembic/versions/`(신규), `backend/ktc/core/security.py`, `backend/ktc/services/public_api_key_service.py`, `backend/ktc/api/routes.py`, `frontend/src/components/SettingsPanel.tsx`, `frontend/src/lib/api.ts`, `backend/tests/`, `docs/feature-export-api.md`.
- **작업 절차**:
  1. `public_api_keys`에 `scope VARCHAR(16) NOT NULL DEFAULT 'read'` 컬럼 추가(migration). **기존 행도 `read`로 백필** — 현재 발급된 공개 키의 실사용은 features pull(읽기)이므로 이상적 기본값을 택한다. env `API_KEYS`(=`BACKEND_API_KEY` 포함)는 코드에서 `admin`으로 취급.
  2. `security.py`의 `require_api_key`가 인증 통과 시 caller scope(`admin`|`read`)를 판별해 `request.state.api_scope`에 저장하도록 확장. 스코프 규칙은 **read 화이트리스트 방식**(공급 표면만 read에 개방 — "GET 전면 read 허용"은 `/runs`·`/destinations/unmatched` 같은 내부 운영 데이터까지 노출하므로 뒤집는다):
     - `read` 키로 허용하는 것은 `GET`/`HEAD` 중 공급 계열만이며, **prefix가 아니라 정확 경로 + 패턴 목록**으로 정의한다(순진한 prefix 매칭은 `/destinations` 하위 내부 경로까지 열어 자기모순이 된다): 정확 경로 `/api/v1/destinations`, `/api/v1/destinations/facets`, `/api/v1/destinations/export`, 패턴 `^/api/v1/destinations/\d+/detail$`, prefix `/api/v1/features/`, `/api/v1/themes`, `/api/v1/categories`. 이 목록을 `security.py`에 상수로 유지.
     - 그 외 전부는 `admin`: 모든 쓰기 + 내부 운영 GET — `/runs*`, **`/destinations/unmatched*`**, **`/destinations/candidates/*`**(자막 원문·evidence 등 검수 내부 데이터), `/settings`, `/metrics`, `/storage/*`, `/audit-logs`, `/harvest/*` 등. **평가 규칙: read 목록에 일치하지 않으면 admin이다**(deny-by-default — allow/deny 우선순위 모호성 제거).
     - 조기 return 우회 2경로의 스코프를 명시: 관리자 proxy(`resolve_admin_proxy_actor`) 통과 = `admin`, 신뢰 CIDR 우회(`api_trusted_client_bypass_active`) = `read`(admin이 필요하면 키를 쓰라는 의미 — CIDR 하나로 스코프 분리가 무력화되지 않게 한다).
     - 무인증 우회(`APP_ENV=local/test/e2e`)는 기존 동작 유지(스코프 검사도 우회).
  3. 발급 API(`POST /admin/public-api-keys`)에 `scope` 파라미터 추가(기본 `read`), 목록 응답에 scope 노출. `SettingsPanel`의 발급 UI에 read/admin select(기본 read)와 목록 scope 배지 추가. admin 키 발급 시 HelpTip으로 위험 고지.
  4. 감사 로그에 scope 포함.
- **테스트**: read 키로 `GET /features/snapshot` 200 / `GET /destinations` 200 / `POST /harvest` 403 / `DELETE /destinations/{id}` 403 / `GET /settings` 403 / **`GET /destinations/unmatched` 403 / `GET /destinations/candidates/{id}/detail` 403**(화이트리스트 경계 부정 테스트). admin 키로 전부 200. e2e env 우회 회귀 확인.
- **완료 기준**: 공급 문서에 "외부 소비자에게는 read 키만 발급" 명시. 기존 소비자(krtour-map) pull 경로 무중단.

#### PR-02. 검수 저장 후 자동 다음 후보 + 타임스탬프 링크 `[UX P0]` `[S]`

> **개정(2026-07-13, §10 반영)**: timestamp 파서는 `HH:MM:SS`뿐 아니라 범위 문자열("12:34-13:00")의 첫 시각·비정상 값·기존 query/hash를 처리하고, URL 조립은 문자열 연결 대신 `URL`/`URLSearchParams`. 자동 다음 후보는 미로드 page가 있으면 prefetch 후 종료 상태를 판단(마지막 page에서만 "모두 처리"). 최초 진입 프리셀렉트의 검색 억제는 `pickCandidate(c, { autoSearch: false })` 옵션 신설로.

> **구현 완료(2026-07-13, T-179)**: 저장·제외·개별 삭제는 처리 시작 visible 순서와 page 수 snapshot으로 자동 진행하고, 숨김-only page 연속 탐색·수동 선택 우선·polling page 이동 중 입력 보존·deep link/scope·상세 삭제 mutex·실패 재시도를 포함했다. 검수 화면은 `listUnmatchedCandidatesPage(limit=300)`를 직접 소비한다. 서버 검색·정렬·새 후보 배너는 예정대로 T-183 범위다.

- **해결**: U1, U7(a). **가장 높은 ROI — 최우선.**
- **변경 파일**: `frontend/src/app/review/page.tsx`, `frontend/src/lib/format.ts`(유틸), `frontend/src/lib/__tests__/`(vitest), `frontend/src/components/CandidateDetailView.tsx`.
- **작업 절차**:
  1. `resolveMutation`(저장·제외)과 개별 삭제 mutation의 `onSuccess`에서: 처리 직전의 `visibleCandidates`(해외 숨김 필터 적용 목록, `review/page.tsx:216-222`) 기준 현재 인덱스를 기억해 두고, 낙관적 제거 후 **같은 인덱스(=다음 후보)** 를 `pickCandidate()`로 선택한다. 마지막 항목이었다면 이전 항목, 목록이 비면 선택 해제 + "검수 큐를 모두 처리했습니다" 빈 상태 표시.
  2. 현재의 `setSelectedId(null)` → `candidates[0]` fallback(`:298,541-548`) 동작을 제거한다. `pickCandidate`가 폼 리셋·카테고리 프리필·자동 검색을 이미 수행하므로 재사용만 하면 된다. **최초 진입 시 동작을 명시**: 첫 후보를 자동 선택하되 자동 검색은 발동시키지 않는 소극적 프리셀렉트(헤더 반쪽 상태 방지) — 현행 `pickCandidate`는 항상 120ms 후 자동 검색을 발동하므로(`:428-434`) **검색 억제 옵션(예: `pickCandidate(c, { autoSearch: false })`) 신설이 필요하다.** `?candidate=` 딥링크 effect(`:284-294`)가 최초 프리셀렉트보다 우선한다. 모바일 경로(`router.push('/review/'+id)`)는 자동 진행 대상이 아니다.
  3. `lib/format.ts`에 `timestampToSeconds("HH:MM:SS"|"MM:SS") → number|null` 유틸 추가(vitest 포함). 검수 행/상세의 "영상 보기" 링크(`review/page.tsx:815-822`, `CandidateDetailView`)에 `timestamp_start`가 있으면 `&t=<초>s`를 부여.
- **테스트**: vitest(유틸). 수동 시나리오: 후보 3건 연속 저장 시 클릭이 "hit 선택→저장"만으로 진행되는지, 마지막 후보 처리 후 빈 상태. `tests/e2e` 검수 스펙 실행·필요 시 갱신.
- **완료 기준**: 후보 1건 처리 = 2인터랙션(hit 선택→저장), 행 재클릭 불필요.

#### PR-03. 실패 작업 재시작 배선 `[UX P0]` `[S]`

> **개정(2026-07-13, §10 반영)**: "파괴적이지 않아 확인 없음" 철회 — ADR-34에 따라 `ConfirmActionButton` 적용. terminal run만 허용, 같은 원본의 중복 클릭 멱등(원본당 active 재시작 1). restart lineage·attention 표시는 PR-34(T-162) 산출물 위에 배선. `done` 내 `quota_deferred` 같은 비성공 outcome을 구분 표시해 재시작 사유를 보여준다. 크기 S → S/M.

- **해결**: U4. `restartRun`(`api.ts:688`)과 mutation은 기존재 — 배선만 한다.
- **변경 파일**: `frontend/src/components/StatusDashboard.tsx`, `frontend/src/app/jobs/[jobId]/page.tsx`.
- **작업 절차**:
  1. `/status` 작업 이력 테이블 행(`StatusDashboard.tsx:413-418` 인근)에 terminal 상태(`failed`/`cancelled`/`done`) 대상 "다시 시작" 버튼 추가 — `restartRun` 호출 후 `["runs"]`·`["run-queue"]` invalidate. running 행에는 "중지"(`stopRun`) 버튼.
  2. `/jobs/[jobId]` 헤더에 같은 조건의 작업 단위 재시작 버튼 추가(현재는 영상 단위 재처리만 존재).
  3. 버튼은 pending 상태 표시(`disabled` + 스피너), `ConfirmActionButton` 확인, 행이 즉시 제거돼도 유지되는 상위 live feedback을 제공한다. 중지·재시작 성공 뒤 `["runs"]`·`["run-queue"]`와 관련 단건 query를 invalidate한다.
- **완료 기준**: 실패 작업 복구가 어느 job 표면에서든 1클릭.
- **구현 완료(2026-07-13, T-180)**: 공용 작업 액션, exact state/outcome 계약, `quota_deferred` 경고 표시, attention·lineage 링크를 `/status`와 `/jobs/[jobId]`에 적용했다. backend는 stop-vs-claim 원자성, 응답/audit transition snapshot, 동시 restart 멱등, 보류 child 이후 성공 descendant의 조상 attention 해소를 보강했다. 최신 main의 T-163 위로 재배치한 뒤 n150 관련 backend 113건·frontend Vitest 104건·Playwright 11건과 3렌즈 반복 적대 검토 최종 P0/P1 0건으로 마감했다.

#### PR-04. 워커 레인 분리 (대화형/배치) `[속도 P0]` `[S]`

> **개정(2026-07-13, §10 반영)**: 크기 S → **M**. lane 매핑은 `create_run` 호출 전수 표를 만들어 확정 — 문서 열거 외에 **MCP `harvest_travel_destinations`/`trigger_deep_research`**(tools.py), 수동 transcript가 낳는 `poi_batch` child(worker.py:271-284)도 포함하고 parent→child에 `lane`·`parent_run_id`를 명시 전파한다. 절차 5(단계 로그)는 status_log 주입으로 불가(C7 — 4필드 재구성·80건 절단) → **PR-34의 `crawl_run_stage_events`로 대체**. "배치 레인 2개 금지"의 원 근거(리미터가 직렬화)는 철회(C6 — 리미터는 admission 카운팅만): 레인당 1은 운영 단순성·N150 사유로 초기 유지하고 gateway·실측 후 재론(§8). lane 공정성·starvation·process 재시작 테스트 추가.

- **해결**: S1. claim은 이미 `FOR UPDATE SKIP LOCKED`(`crawl_run_service.py:147-152`) — 컨슈머 레인만 늘린다.
- **변경 파일**: `backend/ktc/models/crawl_run.py`, `backend/alembic/versions/`(신규), `backend/ktc/services/crawl_run_service.py`, `scheduler/worker.py`, enqueue 호출부(`backend/ktc/api/routes.py`의 harvest/reprocess/deep-research/transcript 생성 지점, `backend/ktc/services/source_scan_service.py`), `backend/tests/test_crawl_run_service.py`.
- **작업 절차**:
  1. `crawl_runs.lane VARCHAR(16) NOT NULL DEFAULT 'batch'` 컬럼 + `(lane, state, id)` 인덱스 추가(migration). job_type 목록 하드코딩 대신 lane 컬럼을 쓰는 이유: 재처리는 `poi_batch` job_type이면서 대화형이므로 유형만으론 구분 불가.
  2. lane은 **job_type이 아니라 enqueue 지점 기준**으로 지정한다(같은 job_type이라도 발원에 따라 다르다): **interactive** = 사용자 버튼/API가 직접 만든 작업 — `/destinations/reprocess`의 재처리, `/destinations/{id}/deep-research`, 수동 `transcript` 후처리, 수동 등록 video 대상 분석 트리거; **batch** = 스케줄러 발원 전부 — `source_scan`, `harvest`, harvest가 낳는 `poi_batch`, 백로그 재투입, **source_scan이 자동 enqueue하는 `video_analysis`**(이를 interactive로 두면 스캔 발원 작업이 대화형 레인을 점유해 목적이 훼손된다). whisper 재전사(PR-18)는 CPU 점유가 크므로 batch. 누락하기 쉬운 enqueue 지점 3곳: **`POST /runs/{job_id}/restart`(routes.py:813-839)는 기존 run을 복제해 새 run을 만들므로 원본 run의 lane을 복사**해야 한다(기본값 batch로 두면 interactive 작업 재시작이 배치 레인으로 떨어진다 — PR-03이 이 경로를 상시 사용). `POST /jobs/poi-batch`(수동 백로그 등록, :354-390)는 대량 배치 성격이므로 batch. `POST /source-targets/{id}/run-now` → `run_target_now`(source_scan_service.py:370-446, harvest/video_analysis 생성)는 수집 성격이므로 전부 batch.
  3. `claim_next_pending(lane: str)`에 `WHERE lane = :lane` 추가. `scheduler/worker.py`의 interval job을 레인당 1개씩 2개 등록(`run_once(lane="interactive")` / `run_once(lane="batch")`, job id는 `crawl-run-worker-interactive`/`-batch`로 분리), 각 `max_instances=1` 유지. persistent jobstore 분기(`worker.py:827-831`)는 현재 kwargs가 빈 dict이므로 **양쪽 분기 모두에 lane kwarg를 추가**한다(직렬화 가능 값). **prod의 persistent SQLAlchemyJobStore에는 구 job id `crawl-run-worker` 행이 잔존해 lane 미지정 `run_once`를 계속 실행할 수 있다 — 기동 시 구 id를 `scheduler.remove_job`(부재 시 무시)으로 제거**한다. **배치 레인 2개 이상 금지** — 둘 다 DB 단일 행 rate limiter에서 직렬화돼 처리량이 늘지 않고 stale/heartbeat 상호작용 변수만 는다(단 이 논거는 무료 티어 가정이다 — PR-05로 유료 티어가 반영되고 단계별 로그에서 LLM 구간이 지배적이면 §8의 'LLM 구간 병렬화' 재론 조건을 따른다).
  4. stale 재투입·heartbeat 로직은 lane 무관 공통 유지.
  5. **poi_batch handler에 단계별 소요 구조화 로그 추가**: 자막 fetch/교정/LLM 추출/지오코딩 각 구간의 시작·종료와 소요 초를 작업 상태 로그에 기록한다. 이 로그는 §7 "poi_batch 단계별 소요" 지표와 **PR-24 게이트의 유일한 판단 근거**다 — 누락하면 게이트가 작동 불능이 된다.
- **테스트**: lane별 claim 격리(대화형 pending이 배치 running과 무관하게 claim되는지), 기존 claim 테스트 회귀.
- **완료 기준**: 배치 실행 중 사용자 재처리 대기시간이 "배치 완주"에서 "수 초"로.

#### PR-05. Gemini rate limiter 티어 현실화 + 토큰 실측 로깅 `[속도 P0]` `[S]`

> **개정(2026-07-13, §10 반영)**: PR-23(T-161)과 통합 실행 — 순서: 실제 결제 티어 확인 → gateway 전 호출 강제 → usage 실측 수집 → 추정식 조정. `.env.example`의 무료/Tier1 숫자는 **예시**로만 표기(모델·티어·계정 상태에 따라 상이 — 실제 한도는 AI Studio에서 확인, §10 B6).

- **해결**: S3.
- **변경 파일**: `.env.example`, `backend/ktc/etl/gemini_client.py`, `docs/dev-environment.md`(또는 운영 문서).
- **작업 절차**:
  1. `.env.example`에 `GEMINI_RATE_RPM`/`GEMINI_RATE_TPM`/`GEMINI_RATE_RPD` 항목을 주석과 함께 추가: 무료 티어(10/250k/1,500 — 현 기본값)와 유료 Tier1(gemini-2.5-flash 기준 1,000/1,000k/10,000) 값 표기. **실제 결제 티어 확인 전에는 기본값을 올리지 말 것**을 명시(429 폭주 = T-101/T-105 재발). 사용자(운영자)가 티어를 확인해 `.env.production`에 반영하는 절차를 문서화 — 이 항목만은 코드가 아니라 운영 액션이다.
  2. `gemini_client`의 응답 처리에서 `usage_metadata`(prompt/candidates token count)를 작업 상태 로그 또는 구조화 로거로 기록한다. 목적: 추정식 `chars//2+2048`(`gemini_rate_limiter.py:41`)의 한국어 실측 계수 보정 근거 수집. **추정식 자체는 이번에 바꾸지 않는다**(실측 없이 추정으로 추정을 고치지 않는다 — 한국어는 문자당 ~1토큰이라 현행이 과소일 가능성도 있음).
  3. 양자화 대기·`_ensure_row` 구조는 변경하지 않는다(§2.3 기각 사유 참조).
- **완료 기준**: env만으로 티어 반영 가능함이 문서화되고, 2주 뒤 실측 토큰 분포를 뽑을 수 있는 로그가 쌓인다.

#### PR-06. run-queue 폴링 통합 + 실패 배지 `[속도 P0]` `[S/M]`

> **개정(2026-07-13, §10 반영)**: queue 통합 endpoint는 기존 `USER_JOB_TYPES` filter semantics를 유지(내부 source_scan 숨김). `failed_recent`(24h)는 임시 — PR-34의 attention 모델이 머지되면 그것으로 교체. PR-28 후 `JobStatusLink` 클릭 대상도 `/jobs`로 변경.

- **해결**: S4, U9. 의존: PR-03.
- **변경 파일**: `backend/ktc/api/routes.py`(신규 엔드포인트), `backend/ktc/services/crawl_run_service.py`, `frontend/src/lib/api.ts`, `frontend/src/components/JobStatusLink.tsx`, `CollectWorkspace.tsx`, `StatusDashboard.tsx`, `frontend/src/app/review/page.tsx`.
- **작업 절차**:
  1. backend에 `GET /api/v1/runs/queue` 신설: `state IN ('running','pending')`을 **1쿼리**로 반환 + `failed_recent`(최근 24시간 failed 수) 필드 동봉. 기존 2회 호출(`api.ts:547-558`) 대체. **라우트 등록 순서 주의**: FastAPI 경로 매칭상 `GET /runs/{job_id}`(routes.py:1943)보다 먼저 등록해야 한다.
  2. frontend `listRunQueue`를 신규 엔드포인트 1회 호출로 교체. 쿼리키를 `["run-queue"]` **하나로 통일**해 `JobStatusLink`(shell)/`CollectWorkspace`(user)/`StatusDashboard`(status)가 캐시를 공유. `refetchInterval`은 10초로 완화.
  3. 반영 지연은 invalidate로 상쇄: 수집 시작·중지·재시작·재처리(`review/page.tsx:202-207`의 `reprocessMutation` 포함) 등 run을 만들거나 바꾸는 모든 mutation `onSuccess`에 `["run-queue"]`(및 해당 시 `["runs"]`) invalidate를 추가.
  4. `JobStatusLink` 배지: running+pending 수 옆에 `failed_recent > 0`이면 destructive 색 보조 배지(클릭 시 `/status` 이력 탭, PR-28 이후 `/jobs?state=failed`). "최근 24h" 윈도우라 자연 해제된다(영구 빨간 배지 방지).
  5. **staleTime 정비(S9)**: 정적 카탈로그성 쿼리(categories는 기존 1h — facets, 8자리 코드 목록 등 변경 빈도가 낮은 것)에 `staleTime` 10분~1h를 명시 지정한다. 전역 기본(5s)은 유지.
- **테스트**: backend 신규 엔드포인트 단위 테스트(상태 혼합 fixture). 수동: 유휴 상태 네트워크 탭에서 요청 빈도 확인(기존 화면당 2req/3s → 1req/10s).
- **완료 기준**: 유휴 폴링 요청 ~1/6, 재처리 후 큐 반영 즉시.

---

### Phase 1 — 검수 큐 서버화

#### PR-07. 검수 목록 payload 확장 (제목·채널·신뢰도·사유) `[UX P0]` `[S]`

> **개정(2026-07-13, §10 반영)**: `queue_reason`은 파생 문자열이 아니라 **안정 enum + 우선순위 규칙 문서화**(ungrounded > name_mismatch > region_mismatch > ambiguous > no_result > foreign > description_only > visual_only 등). reason·source_kind·grounding을 서버 필터로도 노출(grounding 값은 T-165 후).

> **구현 완료(2026-07-13, T-182)**: 목록 scalar·안정 사유 우선순위·`reason`/`source_kind` filter와 `unmatched-v2` cursor를 적용했다. grounding은 T-165 raw 저장 계약 전에는 산출·filter하지 않는 것으로 명시 이연했다. 상세 evidence 비노출과 300건 응답 증가분을 n150에서 측정했고, 오염 confidence/JSONB fail-safe를 추가했다.

- **해결**: U2, D3(표시 측).
- **변경 파일**: `backend/ktc/services/place_service.py`, `backend/ktc/api/routes.py`(`_candidate_list_payload`), `frontend/src/lib/api.ts`, `frontend/src/app/review/page.tsx`, `backend/tests/`.
- **작업 절차**:
  1. `list_unmatched_candidates`(`place_service.py:903-937`)의 `YoutubeVideo` 조인을 상시(outer join)로 바꾼다 — 현재는 channel/keyword 필터 시에만 조건부 조인(`:919-923`). 채널 제목은 `youtube_channels` outer join으로 확보.
  2. `_candidate_list_payload`(`routes.py:2304-2318`)에 **짧은 스칼라만** 추가: `video_title`, `channel_title`, `confidence_score`, `created_at`, `queue_reason`. `queue_reason`은 서버에서 `provider_evidence_json.geocoding.decision`·`is_domestic`·`source_kind`로부터 파생하는 단일 문자열 코드(`no_result | ambiguous | vworld_unrefined_single | name_mismatch | region_mismatch | foreign | provider_missing | extraction_only`) — evidence JSON 원본은 절대 목록에 싣지 않는다(T-152 경량화 원칙). 자막 발췌 등 긴 텍스트도 금지(상세 API 소관).
  3. frontend `UnmatchedCandidate` 타입 확장. 행 표시 재구성: 1행차 = 후보명 + 신뢰도 배지 + 사유 배지, 2행차 = 영상 제목·채널명(말줄임), 위치 힌트. raw `video_id`는 툴팁/상세로 강등. `confidence_score`가 null인 후보(지오코딩 미도달)는 배지 생략.
- **테스트**: payload 필드 회귀 테스트(무필터 조회에서도 제목이 채워지는지), 응답 크기 측정 기록(300건 기준 증가분이 스칼라 수준인지).
- **완료 기준**: 상세 모달 없이 행에서 영상 식별·우선순위 판단 가능.

#### PR-08. 검수 큐 서버 검색·정렬·커서 + URL 상태화 `[UX P0]` `[M]`

> **개정(2026-07-13, §10 반영)**: PR-32(T-177)의 envelope 계약 기반으로 구현 — `total`·`newest_id`·filter fingerprint cursor, "새 후보 N건"은 `limit=1` 비교가 아니라 `newer_than_id` count, `?candidate=`가 page 밖이어도 detail 단건 직접 조회. "3초 내 도달" 완료 기준은 측정 조건(server latency vs 첫 paint vs debounce) 명시.

- **해결**: U3, U11, S8의 데이터 측면. 의존: PR-07.
- **변경 파일**: `backend/ktc/services/place_service.py`, `backend/ktc/api/routes.py`, `frontend/src/lib/api.ts`, `frontend/src/app/review/page.tsx`, `backend/tests/`.
- **작업 절차**:
  1. `GET /destinations/unmatched` 파라미터 확장:
     - `q`: `ai_place_name`/`location_hint` ILIKE(양측 `%`). trigram 인덱스는 두지 않는다(수천 행 규모, §2.3).
     - `sort`: `newest`(기본, 현행 유지) | `oldest`. keyset 커서: `cursor_id`(마지막 행 id) — newest면 `id < :cursor_id`, oldest면 `id > :cursor_id`. 기존 `(match_status,id)` 인덱스를 그대로 사용. `confidence` 정렬은 넣지 않는다(null 다수 + 커서 복잡 — grounding·사유 배지가 우선순위 요구를 대체).
     - `is_domestic`: true|false|전체 — 해외 필터를 서버로 내려 limit 예산 낭비(U8) 제거.
     - `status`: `needs_review`(기본)|`ignored` — PR-09의 제외 목록 조회 준비.
  2. frontend를 `useInfiniteQuery`로 전환: 300건 페이지 append(현재의 "limit 재조회" 폐기). **자동 refetch(60초) 제거** — 대신 첫 페이지 신규 후보 감지용 경량 쿼리(같은 엔드포인트 `limit=1`+최신 id 비교, 60초)로 "새 후보 N건 — 불러오기" 배너를 띄운다. 큐가 조작 중 흔들리는 문제(U3)가 구조적으로 사라진다.
  3. 필터·정렬(`group`, `q`, `sort`, `is_domestic`)을 `useSearchParams` 기반으로 이관(`router.replace`, 선택 후보 id는 URL 제외). sessionStorage는 최초 진입 기본값으로만. `?candidate=` 딥링크는 필터 강제 해제 대신 "현재 필터 밖 후보입니다 — [필터 해제]" 배너로 완화(`review/page.tsx:284-294` 대체).
  4. 검색 입력(디바운스 300ms)과 정렬 select를 목록 헤더에 추가. oldest 선택 상태는 URL로 보존.
  5. **PR-02 자동 진행 로직의 기준 목록 교체**: 해외 필터가 서버로 내려가므로 클라이언트 `visibleCandidates`(구 `review/page.tsx:216-222`) 파생을 제거하고, 자동 다음 후보 선택은 useInfiniteQuery의 평탄화된 페이지 목록 기준으로 바꾼다.
  - 크기 조절 옵션: backend(파라미터·커서)와 frontend(useInfiniteQuery·URL·배너)를 2개 PR로 분할해도 된다(M 상한이므로).
- **테스트**: backend — q/sort/cursor/is_domestic/status 파라미터 조합 단위 테스트(경계: 커서 마지막 페이지, 빈 결과). frontend — 타입·빌드, 수동으로 append·배너·URL 복원 시나리오. `tests/e2e` 검수 스펙 실행·갱신(자동 refetch 제거·배너 도입으로 기존 흐름이 바뀐다).
- **완료 기준**: 2,000건 백로그에서 특정 후보를 텍스트 검색으로 3초 내 도달, oldest로 FIFO 소진 가능, 새 후보가 조작 중 행 위치를 흔들지 않음.

#### PR-09. 검수 되돌리기(reopen) + 마지막 1건 undo + 제외 목록 `[UX P1]` `[M]`

> **개정(2026-07-13, §10 반영)**: **재설계(B1)** — hard delete에 대한 undo는 DB 제약상 불가(C1 검증): **T-160(soft delete 상태 모델)이 선행**하고, reopen은 `deleted_at` 해제+NEEDS_REVIEW 복귀로 구현한다. "고아 장소 정리"는 `delete_place` 전체 helper 재사용 금지 — reference count·매핑 기준으로 공유 장소를 보호하는 별도 helper.

- **해결**: U6. 의존: PR-08(`status=ignored` 조회).
- **변경 파일**: `backend/ktc/services/place_service.py`, `backend/ktc/api/routes.py`, `frontend/src/lib/api.ts`, `frontend/src/app/review/page.tsx`, `backend/tests/`.
- **작업 절차**:
  1. backend `POST /destinations/unmatched/{candidate_id}/reopen`:
     - `IGNORED` → `NEEDS_REVIEW`, `feature_export_status='pending'` 복귀.
     - `USER_CORRECTED` → `NEEDS_REVIEW`. 후보가 만든/연결한 장소 처리는 기존 `delete_place`의 역전이 로직(`place_service.py:860-900` — 다른 매핑이 없는 고아 장소면 함께 정리, 후보를 NEEDS_REVIEW로 되돌림)을 함수로 추출해 재사용. 다른 영상 매핑이 남아 있으면 장소는 보존하고 해당 후보 매핑만 제거.
     - `MATCHED`(시스템 자동확정)도 동일 규칙 허용 — 자동확정 오류를 사람이 되돌리는 경로.
     - ledger 정합: 상태 복귀 후 다음 `sync_feature_exports`가 tombstone/재발행을 자동 처리함을 테스트로 확인(수동 ledger 조작 금지).
     - 감사 로그 기록.
  2. frontend: 저장/제외/삭제 성공 토스트에 "되돌리기" 버튼(마지막 처리 1건만 유지, 다음 처리 시 대체). 클릭 시 reopen 호출 + 해당 후보 재선택. 최근 5건 스택·U 단축키는 여기서 하지 않는다(단축키는 PR-16).
  3. 목록 헤더에 상태 select(검수 대기/제외됨). `ignored` 뷰의 행 액션은 "복구"(reopen) 단일.
- **테스트**: 상태 전이 3종(ignore→reopen, create_place→reopen 고아 정리, match_existing→reopen 장소 보존) + ledger 동기화 회귀 + 멱등(이미 NEEDS_REVIEW인 후보 reopen 시 409 또는 no-op 명시). `tests/e2e` 검수 스펙 실행(상태 select 추가분 갱신).
- **완료 기준**: 어떤 검수 실수도 1클릭 내 복구, 제외 후보 열람 가능.

#### PR-10. 검수 일괄 처리 배치 API `[UX P1]` `[S/M]`

> **개정(2026-07-13, §10 반영)**: 상한 500과 "모두"의 충돌 해소(B7) — 로드된 id 목록이 아니라 **filter snapshot을 서버 bulk 액션에 전달**하고 preview count + 확인 token + 크기·분할·retry 계약을 둔다(장시간 단일 트랜잭션 lock 금지). 해외 일괄 제외는 T-160·T-184(가역성) 후.

- **해결**: U8. 의존: PR-08(is_domestic 서버 필터), PR-09(가역성).
- **변경 파일**: `backend/ktc/api/routes.py`, `backend/ktc/services/place_service.py`, `frontend/src/app/review/page.tsx`, `backend/tests/`.
- **작업 절차**:
  1. backend `POST /destinations/unmatched/bulk` `{action: "ignore"|"delete"|"reopen", candidate_ids: [...]}`(상한 500, 단일 트랜잭션, 감사 로그 1건에 건수·id 목록 기록). 부분 실패 시 전체 롤백 + 실패 id 반환.
  2. frontend 선택 툴바에 "선택 제외" 추가, 기존 다중 삭제(`Promise.all` 개별 DELETE, `review/page.tsx:250-254`)를 bulk 1콜로 교체.
  3. "해외 후보 모두 제외" 버튼: `is_domestic=false` 서버 조회로 대상 id 수집 → **건수 명시 확인 다이얼로그**("해외 판정 후보 N건을 제외합니다. 제외 목록에서 복구할 수 있습니다.") → bulk ignore. `is_domestic`은 LLM 판정이므로 실행 전 고지 문구에 명시.
- **테스트**: bulk 3액션 + 상한 초과 400 + 트랜잭션 롤백. `tests/e2e` 검수 스펙 실행(선택 툴바 변경분 갱신).
- **완료 기준**: 노이즈 후보 수백 건 정리가 1분 내.

---

### Phase 2 — 데이터 신뢰성 코어

#### PR-11. 자막 실패 사유 코드 + provider 관측 `[신뢰성 P0]` `[S/M]`

> **개정(2026-07-13, §10 반영)**: **재설계** — `youtube_videos` 최종 2컬럼만으로는 provider 개선 판단 불가: `transcript_attempts`(video_id, run_id, provider, 순서, 시작/종료, duration, outcome, language, detail, tool version) durable 기록으로 교체(성공 전 실패도 보존; 최종 2컬럼은 요약 캐시로 유지 가능). 수율 기준선 정정: no-whisper 3/27=11.1%, whisper 재실행 11/27=40.7%(통제 A/B 아님) — 현 production 수율·whisper 활성 여부는 T-158 인벤토리 전 미확인.

- **해결**: D1, D7(언어 오기록). **PR-17/18/19의 대상 선별과 §7 지표의 데이터 기반.**
- **변경 파일**: `backend/ktc/etl/transcript.py`, `backend/ktc/etl/batch_poi_service.py`, `backend/ktc/etl/postprocess_service.py`(`_default_transcript_fetcher` 배선), `scheduler/worker.py`(fetcher 주입 확인), `backend/ktc/models/youtube_video.py`, `backend/alembic/versions/`(신규), `backend/ktc/core/config.py`(연결만), `backend/tests/`.
- **작업 절차**:
  1. `transcript.py`의 반환 구조를 `TranscriptOutcome`(dataclass)로 재설계: **성공 시 기존 `TranscriptResult` 객체를 그대로 내장(wrap)하고**(segments·`to_timestamped_text()`가 후보 `timestamp_start`의 원천이므로 평문으로 바꾸면 타임스탬프 근거가 유실된다), 실패 시 provider별 `TranscriptFailure(provider, code, detail)` 목록을 담는다. 실패 코드 enum: `no_captions | blocked | rate_limited | download_error | parse_error | disabled | not_configured`. 각 provider의 `except Exception: return None`을 예외 유형별 코드 매핑으로 교체(알 수 없는 예외는 `parse_error`+detail 보존). **예외를 삼키되 분류해서 삼킨다.** 소비처(`batch_poi_service`의 `transcript.segments` 판정, `postprocess_service._default_transcript_fetcher`, `worker.py`의 fetcher 배선)를 새 구조에 맞춰 갱신.
  2. `youtube_videos`에 `transcript_source VARCHAR(32)`(성공 provider), `transcript_failure_code VARCHAR(32)`(최종 실패 시 대표 코드) nullable 컬럼 추가(migration). 컬럼을 두는 이유: PR-17/18/19가 "자막 비활성 확정 영상"을 SQL로 선별해야 하고, §7 수율 지표를 집계해야 한다 — 로그만으로는 불가.
  3. `batch_poi_service`의 자막 실패 처리(`:134-139`)에서 작업 상태 로그에 provider별 코드를 남기고 위 컬럼을 기록. 상세 실패 목록은 crawl_run status log로 충분(별도 JSON 컬럼 불요).
  4. `TRANSCRIPT_PROVIDER_ORDER`(`config.py:165`, 파서 `:278-280`)를 실제 체인 구성(`DEFAULT_PROVIDERS` 하드코딩, `transcript.py:265-269`)에 연결 — 사문화 해소.
  5. yt-dlp 임의 vtt 폴백 시 실제 트랙 언어를 기록(D7, `transcript.py:186-196`).
  6. 350k자 절단(`batch_poi_service.py:44,158`)·토큰 예산 sub-batch 절단(`:204-208`) 발생 시 작업 상태 로그에 절단 사실(원 길이→절단 길이)을 1줄 남긴다(D7 미통지 해소).
- **테스트**: provider 실패 코드 매핑(mock으로 차단/비활성/파손 3케이스), provider order 설정 반영, 언어 기록, 성공 경로 segments 보존 회귀.
- **완료 기준**: "자막 없음"과 "차단"이 구분돼 작업 로그·DB에서 조회 가능. `SELECT transcript_failure_code, count(*) FROM youtube_videos GROUP BY 1`이 곧 개선 우선순위 표가 된다.

#### PR-12. 지오코딩 자동확정 2중 게이트 (이름·행정구역) `[신뢰성 P0]` `[S/M]`

> **개정(2026-07-13, §10 반영)**: **착수 전 T-165(raw grounding) 선행** — 순서 `PR-11 → PR-13 → PR-12 → PR-14`. provider 결과를 `result_kind=poi|address|coordinate`로 구분하고 kind별 gate 적용(Kakao 주소검색·VWorld 정제 결과의 `place_name`은 주소일 수 있음). `_names_compatible(a,b,c)`는 any-pair 통과(C8 검증)이므로 **비교 목적별 pairwise gate로 분리**. `is_domestic` 미확인은 fail-closed(true 간주 중단). 행정구역 축약 alias parser는 현재 없음(검증) — 명시적 alias asset + fixture 신설.

- **해결**: D2, D4. **FP가 downstream까지 전파되는 것을 막는 신뢰성 최우선 수리.**
- **변경 파일**: `backend/ktc/etl/geocoding.py`, `backend/ktc/etl/geocode_service.py`, `backend/tests/`.
- **작업 절차**:
  1. **이름 게이트**: `apply_geocode_to_candidate`의 신규 장소 생성 경로(`geocode_service.py:139-163`)에서 확정 전에 `_names_compatible(candidate.ai_place_name, selected.place_name)`을 강제한다(기존 함수 재사용, `:181-203`). 불일치 시 `needs_review`, decision 코드 `name_mismatch`, `confidence_score` 0.4. 지오코더가 place_name을 안 주는 경우(주소 지오코딩 결과)는 게이트를 통과시키되 decision에 `name_unverified`를 남긴다.
  2. **행정구역 게이트**: 선택된 결과의 주소 문자열(road/parcel address — provider 응답에 이미 포함)에서 시도·시군구 토큰을 뽑아 `location_hint`의 지역 토큰과 대조한다. **토큰 정규화 규칙을 고정한다**(구현자마다 다른 게이트가 나오지 않도록): 시도명은 접미사(`광역시|특별시|특별자치시|특별자치도|남도|북도|도|시`) 제거 후 전방일치("대구"↔"대구광역시", "전북"↔"전라북도"의 축약 별칭 표는 기존 `admin_region_service.py`의 파싱 인프라를 재사용 또는 참조). hint에 지역 토큰이 없으면 게이트 통과(검증 신호 부재), 있는데 불일치하면 `needs_review` + `region_mismatch`. 별도 역지오코딩 API 추가 호출은 하지 않는다(주소 문자열로 충분).
  3. **ambiguous 개선(검수량 감소 측)**: 다건 결과에서 이름 게이트+행정구역 게이트를 모두 통과하는 후보가 **정확히 1개**면 `matched(0.7)`로 자동확정한다 — 지금은 다건이면 좌표 근접 외엔 전부 검수행이라, 이 변경이 needs_review 유입을 줄이면서 정밀도는 게이트가 지킨다. **이 항목은 ADR-16("매칭 실패는 자동 확정하지 않는다")의 적용 경계를 좁히는 결정 변경이므로, 이 PR에서 ADR-16 보강 ADR(§9의 (a))을 반드시 함께 작성한다** — 기록 없이는 후속 에이전트가 위반으로 오판해 되돌릴 수 있다.
  4. 가중 합성 점수는 도입하지 않는다(§2.2 ④). decision 코드는 `provider_evidence_json.geocoding`에 기존 형식으로 누적하고 PR-07의 `queue_reason` 파생에 연결.
- **테스트**: T-113 패턴 fixture(부분일치 오매칭, 동명 타지역)로 게이트 차단 확인, 게이트 통과 자동확정 회귀, ambiguous→단일 통과 자동확정 케이스.
- **완료 기준**: "검색 이름과 다른 장소가 1.0으로 자동확정"이 불가능해지고, 지역 불일치가 사유 코드로 검수 큐에 표시된다.

#### PR-13. POI 추출 grounding (`evidence_quote`) `[신뢰성 P1]` `[S]`

> **개정(2026-07-13, §10 반영)**: **재설계(B3)** — 교정본 대조·배지 표시가 아니라: raw timestamp segment에서 quote·segment ID를 대조해 `grounding_status`(verified_raw|unverified|missing|not_applicable|legacy_unknown)로 저장하고, **transcript 후보는 verified_raw가 아니면 자동확정·export를 차단**한다. description은 raw description substring, visual은 frame asset ID·timestamp·bounding region 기준. 기존 후보는 legacy_unknown으로 두어 재처리 또는 검수 요구.

- **해결**: D3(추출 단계 신호 0). 의존: PR-07(배지 표시).
- **변경 파일**: `backend/ktc/etl/batch_poi.py`, `backend/ktc/etl/batch_poi_service.py`, `backend/ktc/api/routes.py`(queue_reason 파생 확장), `frontend/src/app/review/page.tsx`(배지), `backend/tests/`.
- **작업 절차**:
  1. `BATCH_RESPONSE_SCHEMA`(`batch_poi.py:47-70`)에 `evidence_quote`(string — 해당 장소가 언급된 자막 원문 인용, 20자 이상)와 `confidence`(number 0~1) 추가. system instruction에 인용 규칙 1항 추가(원문 그대로, 창작 금지).
  2. `parse_batch`에서 quote가 입력 자막(교정본, 공백 정규화 후)에 부분 문자열로 존재하는지 검증 → `grounded: bool`. 결과를 `provider_evidence_json.transcript`에 `evidence_quote`/`grounded`/`llm_confidence`로 기록. **grounding 실패 후보는 폐기하지 않는다** — 저신뢰 마킹만(사유 표시).
  3. `queue_reason` 파생에 `ungrounded` 우선순위 추가(지오코딩 사유보다 앞). 검수 행에 "인용 확인됨/인용 불일치" 배지.
  4. `llm_confidence`는 기록·표시만 하고 어떤 자동확정 게이트에도 사용 금지(주석으로 명문화).
- **테스트**: grounding 판정(정확 인용/변형 인용/창작 인용), 스키마 하위 호환(quote 없는 응답 허용 — 구 응답 재처리 대비).
- **완료 기준**: hallucination 후보가 검수 큐에서 기계 판별 배지로 식별된다.

#### PR-14. 이름 정규화·중복 병합 개선 `[신뢰성 P1]` `[S]`

> **개정(2026-07-13, §10 반영)**: 접미 제거·300m **자동** 병합 금지(게이트 안정·표본 측정 전) — 정규화는 병합 "제안"에만 쓰고, 자동 병합은 provider native ID·주소·좌표가 일치하는 좁은 경우만 후속 도입. `_normalize_name` 현행은 공백+casefold만(원 서술 "특수문자 제거 유지" 정정). **auto-match audit 표본 큐**를 함께 만들어 자동확정 정밀도(G9)를 실측 가능하게 한다.

- **해결**: D6.
- **변경 파일**: `backend/ktc/etl/geocode_service.py`, `backend/ktc/etl/batch_poi_service.py`, `backend/tests/`.
- **작업 절차**:
  1. `_normalize_name`(`geocode_service.py:202-203` 인근)에 지점 접미 처리 추가: 정규식 `\s*(본점|본관|직영점|[0-9]+호점)$` 제거(보수적 목록 — 광범위한 `…점$` 제거는 오병합 위험으로 금지). 공백·특수문자 제거는 현행 유지.
  2. 배치 dedup 키(`batch_poi_service.py:244-262`)를 `(video_id, official_name 완전일치)`에서 `(video_id, 정규화 이름)`으로 완화.
  3. 병합 반경을 100m→300m로 상향하되 **이름 게이트(PR-12) 적용 후에만** — 이름 검증 없는 반경 확대는 오병합을 늘린다(의존 명시). 반경은 config 상수화.
  4. pg_trgm·유사도 병합 제안 UI는 도입하지 않는다(§2.3 — 중복 실측치가 남을 때 재론).
- **테스트**: 정규화 케이스(본점/1호점/공백 변형), dedup 완화 멱등성, 300m 병합 + 이름 불일치 시 needs_review 회귀.
- **완료 기준**: "성심당/성심당 본점"이 같은 장소로 병합되고 언급 수가 합산된다.

---

### Phase 3 — 검수 재설계 본체

#### PR-15. review 페이지 구조 분해 + 120ms 해킹 제거 `[속도 P1·위생]` `[M]`

> **개정(2026-07-13, §10 반영)**: `startTransition`은 debounce·abort의 대체가 아님 — provider 요청은 250~400ms debounce + abort + candidate identity 유지(PR-31의 race 방지와 정합). 동작 보존 커밋과 UX 변경 커밋을 분리한다.

- **해결**: S8, PR-16의 기반. 의존: PR-08(useInfiniteQuery 전환 후의 코드 기준).
- **변경 파일**: `frontend/src/app/review/page.tsx` → 분해: `frontend/src/components/review/`(신규 디렉터리) `useReviewQueue.ts`, `useCandidateSearch.ts`, `CandidateTable.tsx`, `SearchResultsPanel.tsx`, `ConfirmForm.tsx`(+ 기존 지도·다이얼로그 배선 정리).
- **작업 절차**:
  1. **1단계(선행 커밋)**: 분해 전에 `setActiveQuery` 호출을 `startTransition`으로 감싸고 120ms setTimeout+nonce(`review/page.tsx:414,428-434`)를 제거해 본다. React 19 기준 선택 하이라이트 페인트가 검색 쿼리 발동과 분리되는지 수동 확인 — 이 ~10줄로 해결되면 그대로 확정.
  2. **2단계**: 상태 소유를 분리한다 — `useReviewQueue`(목록 쿼리·필터·선택·mutation·undo), `useCandidateSearch`(activeQuery·provider 결과·abort), `ConfirmForm`(폼 로컬 상태). page.tsx는 조립만(목표 300줄 이하). 낙관적 업데이트·자동 다음 후보(PR-02) 동작을 그대로 보존한다.
  3. `PlaceDetailView`/`CandidateDetailView`에 중복된 `cleanTranscript`/타임스탬프 스크롤 로직을 공용 유틸로 추출(기존 중복 확인됨). 추출하면서 현행 "문자 비율 근사 스크롤"(U7b)의 정확도를 판단한다 — 타임스탬프 문자열 위치 기반 앵커로 개선이 싸면 이 PR에서, 아니면 현행 유지를 명시하고 종료.
- **테스트**: frontend 4종 + 기존 E2E 검수 스펙 통과(동작 보존 리팩터링 — E2E가 회귀 가드). 수동: 클릭→하이라이트 즉시, 검색 후행.
- **완료 기준**: 타이머/nonce 제거, 후속 검수 작업의 수정 단가 하락.

#### PR-16. 키보드 단축키 + 처리 모드(triage) `[UX P0]` `[M~L, 측정 게이트]`

> **개정(2026-07-13, §10 반영)**: 포커스 가드 확장 — input 계열뿐 아니라 button/link/dialog 포커스, IME composition 중, modifier 조합, 반복 keydown. `1~9`는 allHits 서수+번호 배지+로딩 중 재정렬 방지(기확정). n/m·"모두 처리"는 filtered `total`(PR-32) 기준. 모바일 상세 route에서 처리 후 다음 후보·undo가 끊기지 않는 acceptance 추가.

- **해결**: U5, U1의 완성형. 의존: PR-02, 08, 09, 15.
- **게이트(필수 절차)**: PR-02~10 배포 후 실사용 1주 기준으로 §7의 "건당 인터랙션 수·체감 소요"를 측정한다. **건당 평균 인터랙션 > 2 또는 마우스 왕복이 여전히 지배적이면 본안(처리 모드), 명백히 충분히 빠르면 축소안(단축키만). 판단이 모호하면 본안이 기본값이다(§2.2 ①).** 어느 쪽이든 아래 1은 수행한다.
- **작업 절차**:
  1. **단축키(공통)**: 전역 keydown 핸들러(포커스 가드 — `document.activeElement`가 input/textarea/select/contenteditable이면 무시): `J`/`K` 다음/이전 후보(`pickCandidate`), `1~9` 검색 hit 선택 — **서수는 평탄 목록 `allHits`(렌더 순서와 동일) 기준으로 정의하고, 각 hit 행에 번호 배지를 표시**해 사용자가 "5번"을 알 수 있게 한다(`selectHit` 재사용), `Enter` 저장(폼 유효 시), `X` 제외, `U` 마지막 처리 undo(PR-09), `/` 검색 입력 포커스. 단축키 안내는 `HelpTip` 또는 `?` 오버레이.
  2. **처리 모드(본안 채택 시)**: `/review`에 모드 토글(URL `?mode=triage|table`, 기본 triage). triage 모드 = 좌측 얇은 진행 레일(현재 위치 n/m, 남은 수, 최근 처리 1건+undo) + 중앙 현재 후보 카드(영상 제목·채널·`&t=` 링크·근거 자막 발췌 지연 로드·신뢰도/사유/grounding 배지·provider 검색 결과·확정 폼) + 우측 지도. **기존 중앙 패널 컴포넌트(PR-15 분해 산출물)를 재사용**하고 신규는 진행 레일과 레이아웃뿐. table 모드 = 기존 테이블(관리·일괄 작업 담당). 저장/제외 시 자동 다음+자동 검색은 PR-02 동작 그대로.
  3. E2E: 검수 스펙에 모드 전환·단축키 시나리오 추가, heading 어서션 갱신.
- **완료 기준**: 마우스 없이 후보 1건 처리 가능. 본안 시 건당 처리 시간 50% 단축 목표.

---

### Phase 4 — 원료 확장 (자막 너머)

#### PR-17. 자막 없는 영상 description 단독 경로 `[신뢰성 P1]` `[M]`

> **개정(2026-07-13, §10 반영)**: description은 **recall 경로** — 후보 수 증가를 신뢰성 향상으로 계상하지 말고 검수 승인율·중복률·후보당 처리시간을 별도 측정(G9). description의 refresh/delete·provenance는 PR-29(Phase -1) 결정 준수.

- **해결**: D1의 수율 측면(자막 실패 = 영상 폐기 문제). 의존: PR-11.
- **변경 파일**: `backend/ktc/etl/batch_poi_service.py`, `backend/ktc/etl/batch_poi.py`(프롬프트 소폭), `backend/ktc/api/routes.py`(queue_reason), `backend/tests/`.
- **작업 절차**:
  1. 자막 전 provider 최종 실패 시 영상을 FAILED로 버리는 대신, `description_raw`(+제목·태그)가 임계 길이(기본 200자, config) 이상이면 해당 텍스트를 단일 아이템으로 batch POI 추출에 투입한다. 미달이면 기존대로 실패(사유 코드 `description_too_short` 추가).
  2. 생성 후보는 `source_kind='description'`으로 표기하고 evidence에 원문 출처를 기록. **지오코딩은 수행하되 자동확정은 금지** — `apply_geocode_to_candidate`에서 `source_kind='description'`이면 게이트 통과 여부와 무관하게 `needs_review` 유지, `queue_reason='description_only'`. 검수 행 배지로 구분.
  3. grounding(PR-13)은 description 텍스트 기준으로 동일 적용.
- **테스트**: 자막 실패→description 경로 전환, 임계 미달 스킵, 자동확정 차단 회귀.
- **완료 기준**: 자막 수율에 묶여 있던 영상들이 "0건 폐기" 대신 검수 가능한 후보를 생산한다.

#### PR-18. whisper 수동 재전사 액션 `[신뢰성 P1]` `[M]`

> **개정(2026-07-13, §10 반영)**: env 게이트가 `transcribe_via_whisper` 함수 내부(off면 무조건 None — 검증)이므로 체인 구성 레벨로 이동 + `force`·model 인자 신설. `AUTO_ENABLED`(자동 폴백)와 manual force를 분리하고 auto 기본값·model·duration 상한·일일 CPU 예산·concurrency 1을 **운영 결정으로 명시** — T-091은 과거 auto ON(base 모델)으로 3/27→11/27을 기록했으므로 "기본 경로 불변" 문구는 T-158 인벤토리로 현 상태 확인 후 확정.

- **해결**: D1의 STT 측면 — 기본화 아닌 선별 실행(§2.2 ③). 의존: PR-11, PR-04.
- **변경 파일**: `backend/ktc/api/routes.py`, `scheduler/worker.py`(transcript handler 파라미터), `backend/ktc/etl/transcript.py`, `frontend/src/app/jobs/[jobId]/page.tsx`, `frontend/src/components/CandidateDetailView.tsx`(또는 검수 상세), `backend/tests/`.
- **작업 절차**:
  1. backend: 명시 요청 시 `TRANSCRIPT_WHISPER_ENABLED`와 무관하게 whisper를 실행할 수 있는 파라미터 경로를 추가한다. **주의: env 게이트가 `transcribe_via_whisper` 함수 내부에 있어(off면 무조건 None 반환, `transcript.py:210-215`) provider 지정만으로는 작동하지 않는다** — 게이트를 체인 구성 레벨로 옮기거나(PR-11 절차 4와 함께) `force` 인자를 추가한다. model 크기도 현재 env(`WHISPER_MODEL_SIZE`)뿐이므로 함수 시그니처에 인자를 추가한다. 흐름 주의: 현행 `transcript` job은 poi_batch로 분할하는 splitter(`worker.py:241-` 인근)이므로, whisper 강제는 결국 **poi_batch의 `transcript_fetcher` 주입 파라미터**(예: `params.transcript_providers=["whisper"]`)로 흘러야 한다. 안전 상한: `youtube_videos.duration_seconds ≤ 1200`(초과 시 400 + 안내), model `small` 고정, **batch 레인**으로 enqueue(CPU 점유가 대화형 레인을 막지 않도록).
  2. frontend: `/jobs/[jobId]` 영상 행과 검수 상세에서 `transcript_failure_code`가 있는 영상에 "whisper로 재전사" 버튼 노출(수 분 소요 고지). 성공 시 poi_batch 재처리로 이어지는 기존 재처리 흐름 재사용.
  3. whisper 결과에는 `transcript_source='whisper'` 기록(PR-11 컬럼) — 품질 추적 근거.
- **테스트**: 파라미터 게이트(길이 초과 400), enqueue lane, opt-in env와의 독립성.
- **완료 기준**: 운영자가 실패 사유를 보고 선별적으로 STT를 태울 수 있다. 파이프라인 기본 경로는 불변.

#### PR-19. 프레임 비전(OCR) 실험 경로 `[신뢰성 P1]` `[L, 게이트]`

> **개정(2026-07-13, §10 반영)**: **2실험 분리** — ① corroboration: 기존 후보 timestamp 주변 프레임 OCR/vision으로 이름·간판 일치를 확인해 검수 근거 강화(검수 횟수 감소 목표), ② source recovery: 자막 없는 영상의 균등 프레임에서 후보 발굴(recall — visual-only 검수 증가를 별도 계상). 변경 파일에 `EvidenceSourceKind.VISUAL`, job type/handler, config, **multimodal gateway(T-161) 경유**, media asset API/BFF, 썸네일 UI 포함. **PR-29(B4) 승인 + T-161 후에만 배포.**

- **해결**: D5. 의존: PR-11(게이트 지표), PR-17(검수 전용 후보 격리 규약 재사용).
- **게이트(필수 절차)**: PR-11~14·17·18 적용 후 2주 지표에서 **"유효 원료 전무 영상 비율"(자막·whisper·description 모든 경로가 원료 확보에 실패한 영상 — description이 후보를 냈다면 품질과 무관하게 원료 확보로 집계해 게이트 왜곡을 막는다)이 20%를 상회**하면 착수. 미만이면 백로그 유지. **착수 결정 시 §2.2 ②의 제3안(Gemini URL 분석 승격)과 비용·구현량·품질을 표로 비교해 택일하고 결과를 journal에 남긴다.**
- **작업 절차**:
  1. 신규 모듈 `backend/ktc/etl/visual_extraction.py`: 대상 = 자막 최종 실패 영상(사유 코드로 선별). 기존 `frame_extraction.py`의 스트림 URL 확보·FFmpeg input seeking 인프라를 재사용해 **균등 간격 프레임 N장(기본 8장, duration 기반)** 을 추출(다운로드 없이 seek). RustFS에 저장(`media_assets`).
  2. Gemini flash 멀티이미지 **1콜/영상**: "각 프레임의 화면 내 텍스트(간판·자막·오버레이·지도 라벨)를 추출하고 장소명 후보를 JSON으로" — responseSchema 강제, rate limiter 통과. 로컬 PaddleOCR은 2순위(N150 CPU 부담 + 한국어 튜닝 비용)로 백로그에만 기록.
  3. 추출 텍스트를 description 경로(PR-17)와 동일 규약으로 batch POI에 투입: `source_kind='visual'`, 자동확정 금지, `queue_reason='visual_only'`, evidence에 프레임 asset id·프레임 타임스탬프 기록. 검수 상세에서 해당 프레임 썸네일 표시(이 경로의 후보는 프레임이 실존하므로 표시 가능 — BFF 경유 서명 URL 또는 프록시).
  4. 전체를 `VISUAL_EXTRACTION_ENABLED`(기본 false) 실험 플래그로 격리. 영상당 비용 상한(vision 1콜)을 코드로 강제.
- **테스트**: 프레임 샘플링(길이별 개수), 후보 격리(자동확정 차단), 플래그 off 시 완전 무개입.
- **완료 기준**: 자막 없는 영상에서 간판·하드섭 기반 후보가 검수 큐에 도달한다. 상시 비용 0(플래그·대상 한정).

---

### Phase 5 — 속도 심화

#### PR-20. `/destinations` SQL 푸시다운 `[속도 P0]` `[M]`

> **개정(2026-07-13, §10 반영)**: PR-20a(절차 0)는 backend 실효 상한 500 때문에 프런트 limit 확장만으론 불완전(C10) — **cursor/offset 계약을 포함**해야 501번째가 보인다(T-177 envelope과 정렬). `source_videos` 제거는 UI·서비스 호출부 사용 전수 확인 → detail lazy-load 선배포 → 제거 순. "O(전체)→O(limit)"은 count/facets/정렬 aggregate까지 `EXPLAIN (ANALYZE, BUFFERS)`로 증명(G8).

> **PR-20a 완료(2026-07-13, T-178)**: 프런트가 T-177 cursor를 100개 단위로 직접 소비해
> 101/501번째를 append하고, total·종료·retry·목록 변경 상태와 page 밖 상세를 처리한다. 501건
> browser mock acceptance를 통과했으며 SQL pushdown·목록 payload 축소는 본 PR-20(T-188)에 남긴다.

- **해결**: S5(101번째 미표시 기능 버그 포함). themes API 자동 수혜.
- **변경 파일**: `backend/ktc/services/place_service.py`(`list_place_summaries`, `_list_mentions_by_place`), `backend/ktc/api/routes.py`, `frontend/src/lib/api.ts`, `frontend/src/components/DestinationWorkspace.tsx`, `backend/tests/test_place_service.py`.
- **작업 절차**:
  0. **최소 수리 선행분 "PR-20a"(별도 미니 PR, S — Phase 1 시점에 병행 가능, 브랜치 `codex/destinations-limit-hotfix`, 별도 T-NNN 채번)**: frontend가 `limit`을 명시(100)하고 "더 보기"(limit 확장)를 추가해 **101번째 이후 장소가 보이지 않는 기능 버그**를 즉시 수리한다. 서버 최적화 없이도 버그는 사라지므로 Phase 5를 기다리지 않는다. 본 PR-20은 PR-20a 머지를 전제로 한다.
  1. `list_place_summaries`(`place_service.py:153-201`)를 SQL로 재작성: `category`/`q`/`district` 필터를 `WHERE`(ILIKE)로, `mention_count`·`source_channel_count`를 `video_place_mappings`/`youtube_videos` 기반 count 서브쿼리(LEFT JOIN LATERAL 또는 group-by 서브쿼리)로, 정렬 4종(언급/최신/이름/카테고리)과 `LIMIT`/`OFFSET`(또는 keyset)을 SQL로. **가장 큰 비용인 `_list_mentions_by_place`의 limit 적용 전 전량 join 로드(`:204-232`)를 limit 적용 후 대상 장소만 조회하도록 이동.** **기존 함수 시그니처와 호출부 호환을 유지한다**: `limit: int | None = 100`(`limit=None` 전량 경로 포함 — `theme_service`가 3곳에서 `limit=None`으로 호출), `place_ids`, `video_id` 파라미터 의미 불변. `theme_service`·`place_export_service` 호출부 회귀 확인 필수.
  2. 목록 응답에서 `source_videos` 배열을 제거하고 상세 엔드포인트로 이관(T-152에서 검증된 수술 패턴). `DestinationWorkspace`가 목록에서 실제 사용하는 필드(마커·행 표시·언급 수)를 사전 확인해 유지.
  3. frontend: `limit`을 명시(기본 100)하고 "더 보기" 버튼으로 확장. 101번째 이후 장소가 보이는지 확인(버그 수리 검증). 10초 자동 refetch는 60초로 완화(폴링 다이어트 연장).
  4. ILIKE용 신규 인덱스는 두지 않는다(현 규모, §2.3). 정렬 회귀 테스트 필수(기존 vitest·pytest의 정렬 semantics — T-152에서 한 번 깨진 전력).
- **테스트**: 필터·정렬·limit 조합 회귀(특히 `mention_count` 고유 영상 수 semantics), 응답에서 source_videos 부재, facets 무회귀.
- **완료 기준**: 요청 비용 O(전체)→O(limit), 장소 수와 무관한 결과 화면 응답 속도, 101번째 장소 표시.

#### PR-21. 지오코딩 캐시 테이블 `[속도 P1]` `[S]`

> **개정(2026-07-13, §10 반영)**: "공통 60일 TTL" 철회 — cache key는 provider·endpoint·canonical parameter 전체·normalization version. 응답을 `success_nonempty|success_empty|transient_error|permanent_error`로 구분해 **error를 빈 성공으로 cache하지 않고** positive/negative TTL 분리. PR-29 정책 matrix에서 허용된 필드만 cache. 선행: T-158.

- **해결**: S7.
- **변경 파일**: `backend/ktc/models/`(신규 `geocode_cache.py`), `backend/alembic/versions/`(신규), `backend/ktc/etl/geocoding.py`, `backend/tests/`.
- **작업 절차**:
  1. 테이블 `geocode_cache(query_hash TEXT PK, provider VARCHAR(16), results_json JSONB, created_at TIMESTAMPTZ)` — key는 `sha256(provider + normalized_query)`. DB 테이블인 이유: API/scheduler 2프로세스가 공유.
  2. `geocoding.py`의 각 provider 호출 앞단에서 조회, 성공 응답(0건 포함)을 적재. TTL 60일 — **만료 정리는 lazy**(조회 시 오래된 행 무시·덮어쓰기), 정리 스케줄러는 두지 않는다.
  3. 캐시 히트도 evidence JSONB에는 동일 형식으로 기록(계약 불변). 재처리 시 `force_refresh` 옵션 훅만 남긴다.
- **테스트**: 히트/미스/만료, evidence 형식 불변.
- **완료 기준**: 시리즈물 채널 재처리에서 반복 장소의 외부 API 호출 0회.

#### PR-22. feature export sync 스로틀 + 더티 필터 `[속도 P1]` `[S/M]`

> **개정(2026-07-13, §10 반영)**: **재설계(B1·§10.4)** — process-local 스로틀·워터마크·플래그는 API/scheduler 2프로세스·재시작에서 정본 불가: 관련 엔터티(candidate·place·video·channel·playlist) 변경을 **같은 트랜잭션의 DB durable dirty outbox**에 기록하고 GET은 outbox consume + 주기 full reconciliation은 안전망으로만. **T-160(tombstone transaction)이 선행.** 원 절차 2~3(updated_at 워터마크·hard delete 플래그)은 outbox로 대체.

- **해결**: S6/A2 — 응답 형식 불변(§2.2 ⑤의 수정안).
- **변경 파일**: `backend/ktc/services/feature_export_service.py`, `backend/ktc/models/extracted_place_candidate.py`, `backend/alembic/versions/`(신규), `scheduler/worker.py`(주기 sync job), `backend/tests/`(기존 `test_feature_export_api.py` 확장 + 필요 시 서비스 테스트 신규 생성).
- **작업 절차**:
  1. **스로틀**: GET 진입 시 마지막 sync 완료 시각(모듈 상태)이 30초 이내면 sync를 건너뛰고 `_read_page`만 수행.
  2. **더티 필터의 전제 컬럼부터 만든다**: `extracted_place_candidates`에는 현재 `updated_at`이 **없다**(`TimestampMixin`은 `created_at`만 제공, `backend/ktc/models/base.py:24-29` — `reviewed_at`만 별도 존재). `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()` + `onupdate=func.now()` 컬럼과 migration(기존 행은 `created_at`으로 백필)을 이 PR에 포함한다. **함정 주의**: SQLAlchemy `onupdate`는 ORM UPDATE에서만 발화한다 — 후보를 갱신하는 경로 중 raw/bulk `update()` 구문이 있는지 grep으로 전수 확인하고, 있으면 해당 지점에서 `updated_at`을 명시 세팅한다.
  3. **더티 필터**: sync 대상을 전 후보에서 "`updated_at` > 마지막 sync 워터마크"인 후보로 축소하고, ledger 로드도 해당 후보 id의 행만(`WHERE candidate_id IN`). 워터마크는 sync 시작 시각 기준으로 갱신(경계 중복 허용 — 멱등이므로 안전). **hard delete 예외 처리**: 삭제는 행 자체가 사라져 `updated_at` 필터에 잡히지 않는다 — hard delete 경로는 **3곳**이다: 후보 삭제(`DELETE /destinations/candidates/{id}` — `routes.py:1414-1444` **인라인**, ledger 행까지 함께 삭제), 장소 삭제(`place_service.delete_place`, `:860-900`), 영상 제외(`exclude_video`, `place_service.py:950-1022` — 후보·고아 장소 raw DELETE). 세 경로 모두에서 feature_export_service의 "전량 sync 필요" 플래그(모듈 상태)를 세워 **다음 GET의 sync 1회를 전량으로 승격**한다(순환 import 없음 확인됨). 플래그 세팅을 놓쳐도 시간당 전량 sync가 최대 1시간 내 보정한다(자가 치유 유지).
  4. **안전망**: 프로세스 시작 시 1회 + 스케줄러 시간당 1회 전량 sync(자가 치유 성질 보존). `sync_one` 분산은 하지 않는다(§2.2 ⑤ 기각 사유).
  5. `_read_page`의 `last_exported_at` 갱신+commit(`:453-458`): 코드베이스 내 소비처를 grep으로 확인하고, 진단 외 용도가 없으면 갱신을 제거해 GET을 순수 읽기로 만든다(컬럼은 유지).
- **테스트**: 스로틀 동작, 더티 필터가 상태 전이(resolve/reopen)를 다음 GET에서 반영하는지, **삭제(tombstone)가 전량 승격 플래그로 다음 GET에서 반영되는지**, 전량 sync 대비 결과 동일성(golden 비교), 응답 스키마 불변.
- **완료 기준**: 소비자 폴링 비용이 후보 수와 무관해지고, GET에서 상시 쓰기 커밋이 사라진다.

#### PR-23. LLM 호출 async 게이트웨이 일원화 `[신뢰성·속도 P1]` `[M]`

> **개정(2026-07-13, §10 반영)**: Phase 5 → **실행 기반 단계(T-161)로 이동**, PR-05와 통합. gateway는 text/json뿐 아니라 향후 video/multi-image 입력·timeout·retry·**quota reservation**(C6 — 우회 중인 deep research·키워드·의견·카테고리·video analysis 포함)·usage·provider/model·결과 상태를 한 계약으로. direct SDK guard는 계약 확정 후 적용.

- **해결**: 문서 이력이 확인한 반복 사고 패턴(T-101/105/111/121-E — 동기 LLM 호출이 이벤트 루프/워커를 막아 매번 호출부 격리로 땜질).
- **변경 파일**: `backend/ktc/etl/llm_client.py`, 호출부 정리(`transcript_correction.py`, `batch_poi_service.py`, `keyword_expansion.py`, `place_search.py`(opinion), `deep_research_service.py`, `video_analysis_service.py`, `category_suggestion.py`), `backend/tests/`.
- **작업 절차**:
  1. `llm_client`에 단일 진입점(`complete_json`/`complete_text`)을 확정하고, 내부에서 `asyncio.to_thread` 격리 + 타임아웃 + 재시도 + rate limiter 통과를 **한 곳에서** 처리한다. 호출부에 흩어진 개별 `to_thread`/timeout/재시도 wrapper를 제거하고 게이트웨이 호출로 통일.
  2. 회귀 방지 가드 테스트: `backend/ktc/etl` 내에서 `genai`/OpenAI SDK를 게이트웨이 밖에서 직접 호출하는 코드를 grep으로 검출해 실패시키는 테스트를 추가(허용 목록: `gemini_client.py`, `deepseek_client.py`, `llm_client.py`).
  3. 동작 보존 리팩터링임을 전제로 기존 파이프라인 테스트 전체 통과가 회귀 가드.
- **완료 기준**: "새 LLM 호출부가 이벤트 루프를 막는" 사고 계열이 구조적으로 재발 불가.

#### PR-24. 자막 fetch 병렬화 `[속도 P1]` `[M, 게이트]`

> **개정(2026-07-13, §10 반영)**: caption network I/O(youtube-transcript-api·yt-dlp)만 제한 병렬화하고 **whisper는 별도 queue 또는 concurrency 1** — 전체 `transcript_fetcher`를 같은 semaphore로 gather하지 않는다. 병렬 task 간 SQLAlchemy session 공유 금지(기확정). 게이트 데이터는 PR-34의 stage events. 전후 provider별 실패율·429·CPU·queue latency 비교(G8).

- **게이트(필수 절차)**: PR-04/05 배포 후 poi_batch 단계별 소요 로그(§7)에서 자막 fetch가 여전히 배치 시간의 30% 이상일 때만 착수.
- **작업 절차**: `batch_poi_service`의 1단계 루프에서 **자막 fetch만** `asyncio.gather` + Semaphore로 선행 prefetch(교정·LLM은 순차 유지 — 리미터 소관). 동시성 값은 사문화 설정 `CRAWL_MAX_CONCURRENT_VIDEOS`(`config.py:210`)를 소생시켜 사용하되 기본값을 4→3으로 하향(yt-dlp 동시 다연발의 YouTube IP 스로틀 위험). 나머지 사문화 설정 `HTTP_MAX_CONCURRENT_REQUESTS`(`:211`)는 지오코딩 병렬화 기각(PR-21이 대체)에 따라 **이 PR에서 삭제**해 죽은 설정을 정리한다. DB 세션은 병렬 구간에서 공유 금지 — fetch는 순수 I/O만, 결과 적재는 순차.
- **완료 기준**: 배치 벽시계에서 자막 단계 2~3배 단축, 수집 실패율 무회귀(前後 사유 코드 분포 비교 — PR-11 데이터 활용).

---

### Phase 6 — 공급 API·IA 마감

#### PR-25. features 계약 마감 `[공급 P2]` `[S]`

> **개정(2026-07-13, §10 반영)**: `TravelPlace`에 `sido_code` 컬럼 없음(C10 검증) — 유도 규칙(`sigungu_code` 앞 2자리) 계약화 또는 컬럼 추가를 먼저 결정. JSON은 Pydantic response_model, GPX 등 binary는 OpenAPI content schema 별도. 전 payload hash 재발급은 consumer canary·cursor drain·rollback 계획 포함. `geocoded_only`가 적용될 endpoint와 기본값 변경 영향 명시.

- **해결**: A5의 features 측.
- **변경 파일**: `backend/ktc/services/feature_export_service.py`, `backend/ktc/api/routes.py`, `docs/feature-export-api.md`, `backend/tests/test_feature_export_api.py`.
- **작업 절차**:
  1. `_build_payload`의 address에 `sigungu_code`/`legal_dong_code`/`sido_code`를 place 실데이터에서 주입(`feature_export_service.py:170-173`의 하드코딩 None 제거). **주의: payload_hash가 전부 바뀌어 전 item이 재발급(sequence 전진)된다** — `docs/feature-export-api.md`와 PR 본문에 소비자 고지(krtour-map은 재수신하면 됨, 계약상 정상 동작).
  2. item에 `schema_version: 1` 필드 추가(additive). snapshot 페이징 중 갱신 item 재등장(중복 가능·유실 없음) 규칙을 문서에 명기.
  3. features/themes/export 목록 엔드포인트에 Pydantic `response_model` 부여 — OpenAPI 응답 스키마 공백 해소. 에러는 기존 `detail`(한국어)을 유지하면서 `code` 필드를 additive로 추가(`invalid_cursor`, `invalid_params` 등 최소 셋).
  4. export 쿼리에 `geocoded_only=true` 기본 파라미터 추가(미검증 좌표의 GPX 유출 방지, false로 opt-out 가능).
- **테스트**: 스냅샷 회귀(행정코드 포함), schema_version 존재, 재발급 동작, geocoded_only 필터.

#### PR-26. themes API 보강 `[공급 P1]` `[S]`

> **개정(2026-07-13, §10 반영)**: offset 대신 **PR-32 envelope** 적용. `source_videos` 기본 제거는 파괴적 변경 — 실소비자 0을 운영 inventory로 확인하거나 additive version/opt-in 전환 기간을 둔다.

- **해결**: A3의 최소 안전판. bbox/updated_since/keyset은 백로그(소비자 등장 시 additive).
- **변경 파일**: `backend/ktc/services/theme_service.py`, `backend/ktc/api/routes.py`, `docs/feature-export-api.md`(테마 섹션 추가 또는 `docs/themes-api.md` 신설), `backend/tests/test_theme_service.py`.
- **작업 절차**:
  1. `/themes/places`·`/themes/video/{id}/places`에 `limit`(기본 200, 상한 500)과 `offset`을 추가 — `limit=None` 전량 반환(`theme_service.py:101-124`) 제거.
  2. `source_videos`를 기본 제외하고 `include=sources` opt-in으로 전환(T-152 경량화 철학). **이 변경은 기존 응답을 줄이는 파괴적 변경이므로** 문서에 마이그레이션 노트를 남기고, `/api-test` 페이지 기본값도 갱신한다(테마 API는 출시 직후·외부 소비자 0이라 지금이 마지막 기회다).
  3. 소비자용 계약 문서 작성: 엔드포인트 3종, 파라미터, `sufficient` 게이트 규칙, 예시 응답.
- **테스트**: limit/offset/include 조합, 기존 `test_theme_service.py`(5케이스) 갱신.

#### PR-27. MCP 검수 목록 도구 `[공급 P2]` `[S]`

> **개정(2026-07-13, §10 반영)**: 경량 목록만으론 "근거 확인" 미완결 — `get_review_candidate_detail(candidate_id)`(raw evidence·provider 판정·영상 링크)를 함께 추가. docstring 의존 금지 — resolve의 감사 actor·필요 review evidence를 **서버에서 검증**.

- **해결**: A6.
- **변경 파일**: `ktc.mcp_server/tools.py`(리포 레이아웃 기준 `backend/ktc/mcp_server/tools.py`), `backend/tests/`.
- **작업 절차**:
  1. READ_TOOLS에 `list_review_candidates(limit≤100, status=needs_review|ignored, sort=oldest|newest, channel_id?, playlist_id?, q?)` 추가 — `place_service.list_unmatched_candidates`(PR-08 확장판) 재사용. 반환은 PR-07 경량 payload와 동일 필드.
  2. 자동 승인 워크플로는 만들지 않는다 — 도구 docstring에 "확정은 반드시 사람 판단을 거친 `resolve_place_candidate` 호출로" 명시(ADR-16).
- **완료 기준**: MCP 단독으로 "목록 조회 → 근거 확인 → resolve" 워크플로가 완결된다.

#### PR-28. 작업 IA 정리 (`/jobs` 인덱스·nav 재편·홈 행동 배너) `[UX P1]` `[M~L]`

> **개정(2026-07-13, §10 반영)**: `/runs`의 state·job_types 필터는 기존재(C10 검증) — 재추가 금지. 실제 작업: 안정 pagination·`total`(PR-32), attention 필터(PR-34), `JobStatusLink` 이동, 모바일 job action. PR-03/06의 임시 `failed_recent` 전제를 복제하지 않는다.

- **해결**: U10, U12, U13. 의존: PR-03, 06.
- **변경 파일**: `frontend/src/app/jobs/page.tsx`(신규), `frontend/src/components/AppShell.tsx`, `StatusDashboard.tsx`, `CollectWorkspace.tsx`, `frontend/src/app/page.tsx`(배너), `tests/e2e/`(heading 어서션 갱신), `backend/ktc/api/routes.py`(`/runs` 필터 파라미터 확장 필요 시).
- **작업 절차**:
  1. `/jobs` 인덱스 신설: 상단 = 진행 중/대기 큐(통합 run-queue 재사용), 하단 = 이력 테이블(상태·유형 select 필터 + "더 보기" 페이지네이션 — backend `/runs`에 `state`/`job_type` 파라미터가 없으면 추가). 행 액션: 상세 링크·중지·재시작(PR-03 컴포넌트 재사용).
  2. nav 재편(`AppShell.tsx:20-27`): 주 그룹 = 결과·수집·검수·**작업**·설정, 하단 보조 그룹 = 상태·API 테스트. `/jobs/*` 하이라이트를 "작업"으로 수정(`:33-35`).
  3. `/status` 축소: 작업 테이블 탭 제거(→ `/jobs`), 시스템 메트릭·RustFS·감사/로그인 로그만 유지. "검수 후보" MetricCard에 `/review` 링크 부여(U12).
  4. `/collect`의 진행 중 패널을 "현재 작업 요약 1줄 + `/jobs` 링크"로 축소(죽은 `detailRun` 상태 제거 포함).
  5. `/` 상단 행동 배너 1줄: "검수 대기 N건 → [검수 시작]" + `failed_recent > 0`이면 "실패 작업 K건 → [보기]". 대시보드 전면 개편·`/`→`/places` 이동은 하지 않는다(§2.2 ⑦).
  6. E2E: nav·heading 어서션 전수 갱신(E2E는 heading을 어서트하므로 필수 체크리스트로 PR 본문에 명시).
- **완료 기준**: job 관련 표면이 `/jobs`(목록·이력·액션)와 `/jobs/[id]`(상세)로 수렴, 아침 첫 화면에서 다음 행동이 1클릭.

---

## 6. 하지 말아야 할 것 (전 검토 종합)

1. **2,000행 클라이언트 전체 로드로의 회귀** — T-146이 시도했고 T-154가 되돌렸다. 필터는 서버로 내린다.
2. **신뢰도 임계값 완화식 자동 확정 / MCP 자동 승인** — ADR-16 위반. 자동화는 게이트 정밀도 향상·정렬·프리필·일괄 도구까지만.
3. **WebSocket/SSE, 버전 카운터, Celery/Redis/PgQueuer** — 이 규모에서 폴링 통합과 asyncio 레인으로 충분. ADR-20 수치 트리거 원칙.
4. **RPM/재시도 상수를 실측 없이 공격적으로 조정** — T-101/T-105 429 폭주 재발 경로. 순서는 반드시 "레인 분리 → 티어 확인 → 실측 반영".
5. **features 계약의 형식·cursor 의미 변경** — 실소비자가 pull 중인 정본. 변경은 additive만(행정코드 주입의 hash 재발급은 계약상 정상 동작이므로 예외적 허용 + 고지).
6. **전 영상 whisper / 전 프레임 OCR 상시 가동** — N150 CPU·비용·레인 점유. 게이트와 플래그 뒤에서만.
7. **rate limiter 슬라이딩 윈도우 전환·부분 슬롯 회수** — Google 측 계산과 어긋나 과승인→429 위험.
8. **화면 추가로 문제 풀기(검수 통계 페이지·필터 빌더·프리셋 CRUD·다인 협업)** — 사용자 1명. IA는 축소·행동 중심 재배치 방향.
9. **가중 합성 신뢰도 점수** — 보정 데이터 없는 가중치는 가짜 정밀도. 불리언 게이트 + 검수 이력 사후 검증.
10. **`sync_one` 쓰기 지점 분산·seq 카운터 심기** — 한 곳 놓치면 조용한 드리프트/갱신 정지. 자가 치유(전량 sync 안전망·멍청한 폴링) 성질을 지킨다.
11. **Google Places 파이프라인 승격** — 403은 Cloud Console 키 제한(코드 외부). 검수 참고용 유지.
12. **확인 다이얼로그 증설로 안전 확보** — 반복 노동에서 다이얼로그는 무의식 클릭으로 무력화된다. 안전은 undo(PR-09)로. (단 ADR-34가 명시한 재실행·파괴적 액션의 확인은 유지 — §2.4-7.)
13. **ledger(`feature_exports`) 행을 먼저 삭제하는 코드** — tombstone 발행 경로가 원천 차단된다(C1 검증). 삭제는 soft delete + 같은 트랜잭션의 전이로만.
14. **raw grounding 미확인 transcript 후보의 자동확정·export** — 게이트는 배지가 아니라 상태 전이 차단이다(B3).
15. **접미 제거·반경 확대 기반 "자동" 병합** — 게이트 안정·오병합률 표본 측정 전에는 병합 "제안"까지만(§10.4 PR-14).
16. **Phase -1 정책 확정 전 제3자 미디어 취득 확대·제한 provider 결과의 영구 저장 배포** (B4).
17. **provider 검색 결과를 이름·좌표만으로 저장** — 원본 hit·출처·주소를 evidence로 남기지 않는 단일 필드 덮어쓰기(C3). provider 원본과 사용자 수정값은 분리 보존한다.

---

## 7. 측정 지표와 검증 루프

각 Phase 완료 시점에 아래를 기록해 다음 게이트 판단(PR-16/19/24)에 쓴다. 측정 인프라가 없는 항목은 해당 PR에 로깅 추가가 포함돼 있다.

| 지표 | 측정 방법 | 현재(추정) | 목표 |
|---|---|---|---|
| 검수 후보 1건 처리 인터랙션 수·체감 소요 | 수동 계수(행 재클릭 포함) + 연속 10건 처리 소요 시간 | 4~5 인터랙션 | 2 (PR-02), 키보드 단독 (PR-16) — PR-16 게이트 판정 근거 |
| 검수 백로그 소진 가능성 | oldest 정렬 존재 여부 + 잔량 추이 | 불가(최신순 고정) | FIFO 소진 가능 |
| 사용자 트리거 작업 대기시간(배치 실행 중) | 작업 로그 timestamp(enqueue→claim) | 배치 완주까지(수십 분) | 수 초 (PR-04) |
| poi_batch 단계별 소요 | handler에 단계 로그(PR-04에서 자막/교정/추출/지오코딩 구간 로그 추가) | 미측정 | PR-24 게이트 데이터 |
| 자막 수율·실패 사유 분포 | `transcript_attempts` 집계 (PR-11 개정판) | no-whisper 3/27=11.1%, whisper 재실행 11/27=40.7%(통제 A/B 아님) — 현 production 수율·whisper 설정 미확인 | T-158 runtime 인벤토리로 기준선 확정 후 사유별 개선 재측정 |
| 유효 원료 전무 영상 비율 | 자막·whisper·description 전 경로 실패 영상 / 전체 (PR-11+17 데이터) | 미측정 | PR-19 게이트 판정 근거(20% 기준) |
| 자동확정 정밀도 | auto-match audit 표본 큐(T-167)의 오확정률 — MATCHED는 큐에서 사라지므로 audit 표본 없이는 측정 불가(§10.4) | 미측정(T-113 사고 전력) | 게이트 후 오확정률 하락 추이(G9) |
| needs_review 유입 비율 | 후보 생성 대비 needs_review 비율 | 사실상 100%(자동확정 제외 전부) | ambiguous 단일 통과 자동확정(PR-12)으로 하락 |
| 유휴 폴링 요청 수 | 브라우저 네트워크 탭 1분 계수 | 화면당 ~2req/3s | ~1req/10s (PR-06) |
| `/features/snapshot` GET 비용 | 응답 시간 + DB 쓰기 유무 | O(후보 수)+쓰기 | 스로틀 내 O(limit)·무쓰기 (PR-22) |
| 결과 화면 101번째 장소 | 수동 확인 | 미표시(버그) | 표시 (PR-20) |

### 7.1 필수 acceptance gate (G1~G10 — §10.6 채택)

| Gate | 통과 조건 |
|---|---|
| G1 삭제 정합성 | export된 후보를 삭제·영상 제외한 뒤 process를 재시작해도 changes가 tombstone을 전달하고, undo 후 새 upsert가 전달된다. |
| G2 인증 | read key로 snapshot/changes 다중 page 200, 모든 쓰기와 내부 검수 GET 403, 구 consumer static key 제거 확인. |
| G3 provenance | provider hit 선택 후 주소·provider·native ID·query·원본값·수정값이 감사 가능하며 제한 provider 데이터는 정책대로 차단된다. |
| G4 자동확정 | 신규 transcript auto-match 100%가 raw grounding verified이며 address result·unknown domestic·이름/지역 불일치는 export되지 않는다. |
| G5 queue 완결성 | 301/501건 fixture에서 total·has_more·cursor·new count가 정확하고 page 밖 deep link와 "모두 처리"가 거짓말하지 않는다. |
| G6 job 복구 | 중복 restart 1회만 생성, lineage·lane 유지, 원본 실패 attention 해소, 모든 재실행에 확인 UI(ADR-34)가 적용된다. |
| G7 자막 관측 | 각 provider 시도·latency·outcome이 보존되고 현재 runtime 기준 수율을 재현할 수 있다. |
| G8 성능 | p50/p95, queue latency, stage duration, 429/실패율을 전후 비교하며 "O(limit)"은 query plan(EXPLAIN)과 부하 fixture로 증명한다. |
| G9 검수 품질 | auto-match audit 표본의 오확정률과 source별 사람 승인율을 기록한다. OCR source recovery는 검수 증가량도 함께 보고한다. |
| G10 외부 계약 | provider 정책 확인일·버전, attribution, cache 만료, downstream canary와 rollback 결과가 runbook/ADR에 남는다. |

**검증 루프**: 데이터 품질 계열(PR-12/13/14/17/19)은 머지 후 실데이터 라이브 점검(T-113 방법론 — 특정 키워드 전수 수집 후 후보 품질 검사)을 1회 수행하고 결과를 journal에 기록한다. 자동화된 품질 게이트가 없는 현 상태에서 라이브 점검이 유일하게 실질 버그를 잡아 온 수단이다.

---

## 8. 백로그 (이번 로드맵 범위 밖, 조건 명시)

| 항목 | 재론 조건 |
|---|---|
| poi_batch LLM 구간 병렬화(sub-batch 동시 실행 또는 배치 레인 증설) | gateway(T-161)·stage events(T-162) 후 LLM 구간이 지배적이고 리미터 대기 ~0으로 실측될 때 — 직렬 3중 구조의 마지막 축(§2.4-6) |
| LLM provider 이원 라우팅(교정=DeepSeek) | PR-04/05 후에도 Gemini 쿼터가 실측 구속 조건일 때 |
| 공급 API bbox·`updated_since`·keyset 커서 표준화 | themes/공간 질의의 실소비자 등장 시(additive라 늦게 붙여도 비용 동일) |
| 키별 rate limit·last_used 통계 | 외부 소비자 2곳 이상 또는 남용 징후 |
| 검수 큐 가상화(react-virtual) | append로 1,000행+ 축적 사용 패턴 + 버벅임 보고 |
| pg_trgm 유사도 병합 제안 | PR-14 후에도 중복 장소 실측치가 유의미할 때 |
| 추출 단계 해외 후보 자동 보류(is_domestic=false → IGNORED 적재) | PR-10 운용 후 해외 노이즈가 여전히 반복될 때 |
| 영상 간 교차 언급(corroboration) 신뢰 신호화 | PR-14 병합 정확화 이후 |
| Gemini URL 분석(video_analysis) 실 키 smoke + 자막 실패 영상 원료 경로 승격 | T-064 잔여 — 쿼터 여유 확보(PR-05) 후. **PR-19 게이트 시점에 vision 경로와 의무 비교(§2.2 ③)** |
| 확정 매핑 대표 프레임의 검수/상세 UI 표시 | "프레임이 있었으면 판정이 달라졌을" 운영 사례 수집 후 (RustFS 객체 브라우저 노출 경로 필요) |
| 지오코딩 질의 구성 재검토(주소 지오코더 vs 키워드 검색 질의 분리) | PR-12 게이트 운용 후에도 `name_unverified`·오매칭 잔존 시 — VWorld `get_coord`(주소 전용)에 장소명 질의를 넣는 현행 설계 부정합의 근본 수리 |
| E2E n150 컨테이너 하니스(Ubuntu 26.04 Playwright 미지원 우회) | 운영 부채 — 별도 태스크로 |
| 세션·공개 키 캐시의 프로세스 메모리 탈피(DB화) | 멀티 replica 필요 시(ADR 자인 한계) |
| 대시보드 전면 개편(`/`→`/places`) | PR-28 배너 운용 후에도 필요가 증명될 때 |
| ledger/candidate 물리 purge(archive table 또는 detached ledger) | soft delete 운용 후 저장량이 실측 문제일 때(§10 B1-6) |

---

## 9. 기존 문서 반영 포인트

- `docs/tasks.md`: **반영 완료(2026-07-13)** — T-158~T-192를 Agent A/B 트랙으로 대기 등재(§4.2와 1:1).
- `docs/decisions.md`: ADR 후보 — (a) candidate soft delete·export tombstone 상태 모델(T-160, ADR-16 보강), (b) 자동확정 게이트와 ADR-16 경계 재정의(T-166에서 작성 의무), (c) 워커 레인·LLM 게이트웨이(T-161·T-163, ADR-13 보강), (d) API 키 스코프·소비자 회전(T-175·T-176, ADR-24 보강), (e) Phase -1 provider 정책·ADR-15 무기한 보존 재검토(T-158). 기각 결정(§2.3)도 해당 ADR에 "고려 후 기각"으로 남긴다.
- `CLAUDE.md`: "현재 작업"·"다음 착수 대상"에 로드맵 실행(T-158~)을 반영 — 각 태스크 완료 시 갱신.
- `docs/feature-export-api.md`: T-175(read 키)·T-189(schema_version·재등장 규칙)·T-190(테마 섹션) 시점에 각각 갱신.

---

## 10. Codex 상세 리뷰 — 3개 적대적 검토·2회 교차 검증 (2026-07-12)

> **최종 판정: 수정 후 승인.** 문제 정의와 큰 방향은 채택할 가치가 높지만, 현재 문서를 그대로
> 작업 계약으로 삼으면 삭제 복구·export tombstone·자동확정 신뢰성·외부 provider 정책에서
> 회복하기 어려운 오류를 만들 수 있다. 아래 BLOCKER가 문서에 반영되기 전에는 §9의
> `T-158` 이후 작업 등록과 구현 PR 착수를 보류한다. 이 절은 원문을 보존한 채 덧붙인 리뷰이며,
> 원문과 충돌할 때는 이 절의 정정이 우선한다.

> **반영 상태 (2026-07-13)**: 이 리뷰의 사실 주장 22건을 독립 검증 에이전트 3개가 코드 대조로 전부 확인(CONFIRMED — `FeatureExport` FK·`exclude_video` 컬럼 버그·provenance 유실·리미터 커버리지·수율 수치 등)했고, B1~B7·PR별 수정 의견·10단계 순서·acceptance gate를 §0~§9 본문(각 PR "개정" 항목 포함)과 `docs/tasks.md`(T-158~T-192, Agent A/B 트랙)에 반영 완료했다. 이하 원문은 리뷰 기록으로 보존한다. 본문 개정판과 차이가 있으면 **본문이 우선**한다(아래 원문 blockquote의 우선 규칙은 반영 완료로 소임을 다했다).

### 10.1 검토 범위와 반복 방법

- **검토 기준**: 최신 `origin/main` `52e64d2`에서 문서·프런트엔드·FastAPI·ETL·scheduler·
  SQLAlchemy 모델·Alembic·형제 소비자 계약을 대조했다.
- **1회차 독립 적대적 검토**:
  1. 사용 편의성·검수 동선·job 생명주기 관점
  2. 데이터 신뢰성·자막·grounding·OCR·외부 API 정책 관점
  3. 코드 사실성·DB 제약·의존 순서·PR 실행 가능성 관점
- **2회차 교차 검토**: 각 검토자가 다른 두 관점의 BLOCKER를 반박하고 코드·ADR·운영 문서로
  다시 확인했다. 이 과정에서 근거가 약한 주장은 아래처럼 완화하거나 철회했다.
  - NCP Maps Geocoding에 NAVER Developers Local Search 약관을 그대로 적용한 주장은
    **제품이 다르므로 철회**한다. NCP 계정에 적용되는 별도 약관을 확인해야 한다.
  - geocoding 조회 자체가 grounding보다 반드시 늦어야 한다는 주장은 **완화**한다.
    조회는 먼저 또는 병렬로 할 수 있지만, 자동확정·export 전에는 raw grounding이 필수다.
  - 외부 소비자 static key 교체는 PR-01 코드 merge의 선행 조건이 아니라
    **production 보안 목표 완료 조건**으로 정정한다.
  - YouTube 30일 규칙을 모든 파생 POI 삭제로 확대하는 해석과 Kakao cache 전면 금지 해석은
    **철회**한다. API Data 범위와 provider별 허용 조건을 구분해야 한다.
- **확정된 반증**: 원문의 “구조적 오류 0건” 판단은 유지할 수 없다. 아래 B1~B7은 코드와
  제약으로 재현 가능한 구조 오류 또는 실행계획 누락이다.

문서 상단의 기준 커밋도 정정이 필요하다. `bc514cd`는 T-154이며, T-156 반영 커밋은
`ead57bb`다. 이 문서를 추가한 최신 커밋은 `52e64d2`다. 또한 번호상 PR-01~28에
PR-20a가 별도 PR로 추가되므로 실제 독립 PR 수는 29개다. “Phase 0 전부 독립”도
PR-06이 PR-03에 의존한다고 문서 자체가 명시하므로 사실과 다르다.

### 10.2 유지할 판단

다음 방향은 세 검토 모두에서 유효했다.

1. 검수를 “목록 브라우징”에서 서버 소유 queue와 연속 처리 흐름으로 바꾸는 것
2. 검색·필터·정렬·페이지네이션을 서버 계약으로 내리고 URL에 상태를 남기는 것
3. 실패를 숨기지 않고 provider별 자막 시도·단계별 소요·판정 사유를 관측 가능하게 만드는 것
4. 자동확정 임계값을 낮추지 않고 이름·지역·원문 근거를 독립 gate로 쓰는 것
5. 외부 API 키를 read/admin으로 분리하고 공급 API를 명시적 계약으로 다듬는 것
6. LLM 호출을 단일 async gateway로 수렴하고 실제 사용량을 측정한 뒤 병렬도를 조정하는 것
7. 큰 기능을 PR 단위로 나누고 각 PR에 완료 기준과 회귀 테스트를 두는 문서 형식

문제는 방향이 아니라 **상태 모델, 정책 gate, 의존 순서와 완료 기준**이다.

### 10.3 승인 전 BLOCKER

| ID | BLOCKER | 현재 문서의 문제 | 승인 조건 |
|---|---|---|---|
| B1 | 삭제·undo·tombstone 상태 모델 | PR-09와 PR-22가 현재 hard delete와 양립하지 않는다. ledger를 먼저 지우면 다음 full sync가 tombstone을 만들 수 없다. | candidate soft delete와 같은 transaction의 tombstone 전이를 먼저 설계한다. |
| B2 | 검수 선택 provenance 유실 | provider hit의 주소·provider가 저장 직전에 사라지고, 수동 확정은 근처 첫 장소에 이름 검증 없이 합쳐질 수 있다. | 선택 hit 원본과 수동 수정값을 분리 저장하고 사용자 확정 경로에도 identity gate를 둔다. |
| B3 | raw grounding이 자동확정 gate가 아님 | PR-13은 교정본을 검사하고 배지만 표시한다. 그럴듯한 hallucination이 PR-12를 통과할 수 있다. | raw segment grounding을 상태로 저장하고 미확인·불일치 후보의 자동확정/export를 차단한다. |
| B4 | 외부 미디어·provider 정책 gate 부재 | PR-18/19는 YouTube 미디어 취득을 확대하고 Google 결과는 실제로 VWorld 지도·영구 저장에 쓰인다. | Phase -1에서 provider별 표시·저장·cache·export 계약과 production flag를 확정한다. |
| B5 | read key rollout 미완결 | static `API_KEYS`를 admin으로 남긴 채 실제 소비자가 계속 쓰면 A1은 해소되지 않는다. | read 키 발급→소비자 secret 회전→write 403→구 consumer key 제거까지 완료 기준에 넣는다. |
| B6 | LLM gateway·lane·측정 순서 오류 | rate limiter는 모든 호출을 감싸지 않고 network call을 직렬화하지도 않는다. lane 전파와 구조화 측정도 빠졌다. | gateway와 durable event를 먼저 만들고 모든 parent/child enqueue에 lane·lineage를 전달한다. |
| B7 | 목록 완료 여부를 알 수 없는 pagination | PR-08의 list 응답과 `limit=1` 비교만으로 “새 후보 N건”, n/m, 마지막 page를 정확히 알 수 없다. | 검수·작업·장소·테마 목록에 일관된 envelope와 filter 기준 total을 정의한다. |

#### B1. 삭제·undo·feature export는 하나의 상태 전이여야 한다

현재 `FeatureExport.candidate_id`는 non-null, unique, `ON DELETE NO ACTION` FK다.
후보 삭제와 영상 제외는 FK 충돌을 피하려고 `feature_exports` 행을 먼저 삭제한다.
반면 `sync_feature_exports()`의 tombstone 복구는 **남아 있는 ledger 행**만 순회한다.
즉 ledger를 지운 순간 `export_id`, 마지막 payload, sequence와 downstream 비활성화 수단이
함께 사라진다. 모듈 메모리의 “전량 sync 필요” flag나 시간당 full sync로는 복구할 수 없다.

원문의 hard delete 3경로 설명도 정정해야 한다.

- 후보 삭제와 영상 제외는 candidate hard delete다.
- 장소 삭제는 candidate를 삭제하지 않고 `needs_review`로 되돌리는 별도 상태 전이다.
- `exclude_video()`에는 존재하지 않는
  `ExtractedPlaceCandidate.place_id`를 조회하는 현재 코드 결함도 있다. 실제 컬럼은
  `matched_place_id`이며, 이 문제는 로드맵보다 앞선 hotfix로 분리해야 한다.

이상적 방향은 candidate를 감사 가능한 도메인 기록으로 보고 물리 삭제를 중단하는 것이다.

1. `extracted_place_candidates`에 `deleted_at`, `deletion_reason`, `deleted_by`를 추가한다.
2. queue·dedup·자동 처리 조회는 `deleted_at IS NULL`을 명시하고, 실제 access path에 맞는
   partial/composite index를 migration에 함께 둔다.
3. 삭제 transaction에서 mapping과 `matched_place_id`를 해제하고, 이미 export된 ledger는
   같은 transaction에서 tombstone·새 sequence·사유로 전환한다. export된 적 없는 후보에는
   의미 없는 tombstone을 만들지 않는다.
4. undo/reopen은 삭제 필드를 지우고 `needs_review`로 되돌린다. 영상 제외도 같은 helper를 쓴다.
5. `deleted_at IS NOT NULL`이면 삭제 사유가 필수라는 CHECK와 FK/index 회귀 테스트를 둔다.
6. 물리 purge가 실제로 필요해질 때만 archive table 또는 nullable `candidate_id` +
   `ON DELETE SET NULL` detached ledger를 별도 설계한다.

필수 검증은 “export 완료 후보 삭제”, “영상 bulk 제외”, “process 재시작”, “changes cursor 소비”,
“undo 후 재발행”을 한 시나리오로 묶어 downstream이 조용히 stale 상태에 남지 않음을 확인하는 것이다.

#### B2. 검수에서 선택한 출처가 영구 데이터가 되기 전에 사라진다

`PlaceSearchHit`에는 `provider`, `address`, `road_address`가 있고 화면에도 주소가 보인다.
그러나 `selectHit()`은 이름·위도·경도만 form에 복사하고, resolve 요청은
`api_source`를 보내지 않는다. backend 기본값은 `manual`이다. 따라서 사용자가 provider 결과를
선택해도 확정 장소에는 주소가 null이고 출처는 manual로 남는다. 원문의
“Google/Kakao/Naver는 검수 참고용” 전제도 틀렸다. hit은 VWorld 지도에 표시되고 선택한
이름·좌표가 `TravelPlace`로 영구 승격될 수 있다.

또한 사용자 `create_place` 경로는 100m 내 후보가 있으면 이름 검증 없이 첫 장소에 합친다.
자동 geocode 경로만 고쳐서는 사용자 검수로 생기는 오병합을 막지 못한다.

별도 Phase 0 PR로 다음을 먼저 수행해야 한다.

- 선택된 `PlaceSearchHit` 전체를 form의 숨은 문자열이 아니라 typed state로 보존한다.
- provider native ID, 검색 query, 검색·선택 시각, 원본 이름·주소·좌표·카테고리,
  reviewer를 resolution evidence에 기록한다.
- provider 원본과 사용자가 수정한 최종값을 분리한다. 최종값만 덮어쓰면 감사와 재검증이 불가능하다.
- 허용된 provider에 한해 `official_address`, `road_address`, `api_source`를 resolve에 전달한다.
- 사용자 확정의 근접 중복도 이름·provider ID·좌표를 함께 비교하고, 불확실하면
  “기존 장소에 합치기”와 “새 장소 만들기”를 사용자가 고르게 한다.
- category match의 늦은 응답이 다음 후보 form을 덮어쓰지 않도록 candidate/request identity를
  확인하거나 abort한다.

#### B3. 신뢰성 gate는 “표시”가 아니라 상태 전이를 막아야 한다

원문의 PR-13은 `evidence_quote`를 LLM 교정 자막에서 검사한다. 교정본 역시 생성 모델 산출물이므로
원문 증거가 아니다. 더 큰 문제는 grounding 실패를 badge로만 표시하고 같은 실행의 geocoding·
자동확정을 막지 않는다는 점이다.

권장 상태는 boolean 하나가 아니라 다음과 같이 source별 의미를 보존해야 한다.

- `verified_raw`: raw timestamp segment에서 quote와 segment ID를 확인
- `unverified`: quote/segment 불일치
- `missing`: 모델이 근거를 주지 않음
- `not_applicable`: source 특성상 별도 규칙 적용
- `legacy_unknown`: 기존 데이터

순서는 `PR-11 → PR-13 → PR-12 → PR-14`로 바꾼다. geocoding API 조회는 먼저 해도 되지만,
transcript 후보는 `grounding_status=verified_raw`가 아니면 자동확정과 export가 불가능해야 한다.
description은 raw description substring, visual은 frame asset ID·timestamp·OCR bounding region을
증거로 쓴다. 기존 후보는 자동으로 신뢰하지 말고 `legacy_unknown`으로 두어 재처리 또는 사람 검수를
요구한다.

PR-12의 이름 gate도 그대로 구현하면 대량 오판한다. Kakao 주소검색과 VWorld 주소 정제 결과는
`place_name`에 POI명이 아니라 주소가 들어갈 수 있다. 먼저 result를
`result_kind=poi|address|coordinate`로 구분하고 각 kind에 다른 gate를 적용해야 한다.
현재 `_names_compatible(a,b,c)`는 세 값 중 아무 한 쌍만 맞아도 true라서 provider 결과 이름이
틀려도 기존 장소명과 AI명이 같으면 통과한다. 비교 목적별 pairwise gate로 분리한다.
`is_domestic` 미확인을 true로 간주하는 현행도 fail-closed로 바꾼다. 문서가 재사용한다고 한
행정구역 축약 alias parser는 현재 그 형태로 존재하지 않으므로 명시적 alias asset과 fixture가 필요하다.

PR-14의 지점 접미 제거와 반경 300m 자동 병합은 이 gate가 안정되기 전 금지한다.
“본점”, “1호점”은 실제 다른 지점일 수 있다. 정규화는 후보 제안에만 쓰고 provider native ID,
주소와 좌표가 없으면 자동 병합하지 않는다. 현재 `_normalize_name`은 공백만 제거하므로
원문의 “특수문자 제거는 현행 유지”도 사실 정정이 필요하다.

#### B4. Phase -1 — 외부 정책과 데이터 권리

이 절은 법률 자문이 아니라, 공식 정책과 현재 기술 흐름의 충돌 가능성을 release gate로 명시하는
검토다. 보안·queue·일반 UX 작업은 병행할 수 있지만, 아래 결론 전에는 제3자 미디어 취득 확대와
제한 provider의 영구 저장을 배포하지 않는다.

- **YouTube**: 공식 [YouTube API Developer Policies](https://developers.google.com/youtube/terms/developer-policies)는
  사전 서면 승인 없는 audiovisual content 다운로드·cache·저장과 비공식 기술을 통한 content 접근을
  제한한다. 현재의 원본 미디어 무기한 보존 계약과 PR-18/19의 `yt-dlp`·오디오·프레임 경로는
  compliance audit, 서면 승인 또는 권리가 확인된 사용자 제공 원본 경로 중 하나가 선행돼야 한다.
  30일 refresh/delete는 YouTube API metadata 범위로 정확히 한정하고, 파생 POI 전체 삭제로
  과도하게 확대하지 않는다.
- **Google Places**: 공식 [Places API 정책](https://developers.google.com/maps/documentation/places/web-service/policies)은
  Places content 저장을 허용된 예외로 제한하고, Places 결과를 지도에 표시할 때 Google Map과
  attribution을 요구한다. 현재 Google hit은 VWorld 지도에 표시되고 선택·저장 가능하다.
  prod 403을 안전장치로 보지 말고 기본 off로 둔 뒤 제거, Google 전용 표면, place ID 중심 재조회,
  비선택 reference 중 하나를 결정한다.
- **Naver**: PR-21의 NCP Maps Geocoding과 검수 화면의 NAVER Developers Local Search를
  구분한다. 공개 [NAVER API 서비스 이용약관](https://developers.naver.com/products/terms/)이
  적용되는 Local Search 결과는 별도 DB 관리 제한을 검토해야 한다. NCP Maps cache는 실제 계정에
  적용되는 제품별 약관을 확인하기 전 기본 off로 둔다.
- **Kakao/VWorld**: [Kakao Developers 운영정책](https://developers.kakao.com/terms/ko/site-policies)은
  UX 개선 목적 cache를 전면 금지하지 않지만 최신성 의무가 있다. “모든 provider 60일” 같은
  공통값 대신 계정·API별 허용 필드와 TTL을 확인한다. VWorld도 발급 시 동의한 조건과 데이터
  라이선스를 운영 기록으로 남긴다.

Phase -1 산출물은 provider별 `표시 / 지도 / 영구 저장 / 임시 cache / attribution / 외부 export /
허용 TTL / 약관 버전·확인일` matrix, production kill switch, 기존 RustFS asset inventory,
ADR-15 보존 결정의 재검토다. 기존 객체 삭제는 현재 계약을 조용히 어기지 말고 사용자 결정과 ADR을
거쳐야 한다.

#### B5. API scope는 코드 merge가 아니라 소비자 회전까지가 완료다

이 저장소의 과거 문서는 소비자를 `python-krtour-map`으로 적었지만, 로컬의 현재 형제 저장소는
`kor-travel-map`이며 `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_API_KEY`를
Concierge의 static `API_KEYS` 중 하나로 설명하고 실제 `X-API-Key`로 보낸다.
실제 production 값은 저장소만으로 단정할 수 없으므로 inventory가 필요하다.

PR-01은 다음을 보강한다.

1. `public_api_keys.scope`는 TEXT + CHECK 또는 동등한 DB 제약으로 `read|admin`만 허용한다.
2. 현재 hash 집합 cache는 scope를 반환할 수 없으므로 `key_hash → scope` cache로 바꾸고
   revoke·scope 변경 시 무효화한다.
3. `?key=`는 공유 링크용 read에만 허용하고 admin key는 header/proxy 경로만 허용한다.
4. `/api/v1/admin/*`는 기존 계약대로 admin proxy 전용이다. “admin key면 전부 200”이라는
   원문의 테스트 기대를 이 경로에 적용하면 안 된다.
5. route 문자열의 우연한 prefix에 권한이 붙지 않도록 read 공급 표면을 명시적 policy/dependency로
   등록하고 deny-by-default 테스트를 둔다.
6. DB read key 발급→`kor-travel-map` 인증 정보 교체→snapshot/changes 다중 페이지 확인→
   read key write 403→구 consumer 정적 key 제거 순으로 배포한다.
7. BFF/operator 정적 key와 consumer key가 같으면 먼저 분리한다. 되돌리기 가능 구간과 제거 시점을
   runbook에 남기되 키 값은 문서·로그에 쓰지 않는다.

#### B6. job lifecycle·LLM gateway·lane을 같은 순서 문제로 다룬다

현재 `gemini_rate_limiter.acquire()` 호출은 자막 교정과 batch POI에만 있고, Deep Research,
키워드 확장, 장소 의견, 카테고리, video analysis 등은 같은 quota 예약을 우회한다.
DB row lock은 quota 숫자를 갱신하는 짧은 transaction 동안만 유지되며 network call을 직렬화하지
않는다. 따라서 “DB 단일 행 때문에 batch lane을 늘려도 처리량이 늘지 않는다”는 PR-04의 근거는
철회해야 한다. 공식 [Gemini API rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)도
모델·tier·계정 상태에 따라 달라지고 실제 한도는 AI Studio에서 확인하도록 안내하므로
PR-05의 숫자는 계약값이 아니라 예시로만 둔다.

PR-23을 Phase 5가 아니라 lane·vision보다 앞으로 옮긴다. gateway는 text/json뿐 아니라 향후
video/multi-image 입력, timeout, retry, quota reservation, usage, provider/model, 결과 상태를
한 계약으로 처리해야 한다. direct SDK guard는 이 계약이 준비된 뒤 적용한다.

PR-04는 모든 `create_run` 호출을 표로 만들고 parent→child에 `lane`과
`parent_run_id/restart_of_run_id`를 명시적으로 전달해야 한다. 특히 수동 transcript가 만드는
`poi_batch` child와 MCP Deep Research를 누락하면 대화형 작업이 다시 batch에 떨어진다.

재시작은 단순 버튼 배선이 아니다.

- terminal run만 restart 허용하고 원본 lane과 입력 snapshot을 복사한다.
- `restart_of_run_id` self FK와 index로 lineage를 남기고 같은 원본의 중복 click을 멱등 처리한다.
- `failed_recent 24h` 대신 최신 leaf attempt의
  `attention=open|acknowledged|superseded|resolved|none`을 관리한다.
- 재시작 성공은 원본 실패 attention을 superseded/resolved로 바꾸고, 별도 acknowledge API를 둔다.
- ADR-34는 재실행을 확인 대상으로 명시한다. PR-03의 “파괴적이지 않아 확인 없음”은 철회하고
  `ConfirmActionButton`을 사용한다.

PR-04가 요구하는 단계별 구조화 시간은 현재 `status_log_json`에 임의 필드를 넣는 것으로
달성되지 않는다. parser가 timestamp·level·message·progress만 남기고 최근 80건으로 자른다.
`crawl_run_stage_events` 또는 동등한 durable event에 stage, provider, attempt, elapsed_ms,
outcome을 저장하고 UI 로그는 그 요약 view로 둔다.

PR-24는 전체 `transcript_fetcher`를 같은 semaphore로 gather하지 않는다. network caption/yt-dlp
경로만 제한 병렬화하고 Whisper는 별도 queue 또는 concurrency 1을 유지한다. 병렬 task 사이에
SQLAlchemy session을 공유하지 않는다.

#### B7. queue·목록의 “끝”을 계약으로 정의한다

features API의 기존 `{items,next_cursor,has_more}`는 실소비자가 있으므로 변경하지 않는다.
그 외 검수·작업·장소·테마 목록은 다음 최소 envelope를 공통 원칙으로 삼는다.

```json
{
  "items": [],
  "next_cursor": null,
  "has_more": false,
  "total": 0,
  "newest_id": null
}
```

`total`은 cursor 적용 전 현재 filter 전체 건수다. newest/oldest 정렬은 동률을 포함한 안정 keyset을
정의하고, cursor에는 sort·filter fingerprint 또는 버전을 넣어 다른 filter에 재사용하지 못하게 한다.
“새 후보 N건”은 `limit=1` 결과 비교가 아니라 `newer_than_id` count 또는 동등한 경량 endpoint로
계산한다. `?candidate=`가 현재 page 밖이어도 detail 1건을 직접 가져올 수 있어야 한다.

이 계약은 다음 문제도 함께 해결해야 한다.

- triage 기본은 oldest로 두고 queue reason·source kind·grounding·channel·playlist·keyword를
  서버 filter와 URL 상태로 제공한다.
- n/m은 현재 loaded item 수가 아니라 filtered total을 사용하며 `has_more=false`일 때만
  “모두 처리”를 표시한다.
- “해외 후보 모두 제외”는 최대 500 ID만 가져와 all이라고 부르면 안 된다. filter snapshot을
  server bulk action에 넘기고 preview count·확인 token·상한/분할 규칙을 정의한다.
- `/destinations`의 frontend limit 확장만으로는 backend 상한 500을 넘어갈 수 없다.
  PR-20a는 cursor/offset 계약까지 포함하거나 501번째가 여전히 사라진다.
- `/runs`는 이미 state·job_types filter가 있다. PR-28은 이를 다시 추가하지 말고 cursor·total과
  `USER_JOB_TYPES` 보존을 구현한다.
- themes의 `sufficient`와 `poi_count`는 page가 아니라 filter 전체 집합 기준이어야 한다.

### 10.4 PR별 상세 수정 의견

#### Phase 0 / PR-01~06

- **PR-01**: B5의 DB 제약·scope cache·query-key 제한·cross-repo rotation을 완료 기준에 추가한다.
  static key 호환은 migration window이지 최종 상태가 아니다.
- **PR-02**: timestamp parser는 `HH:MM:SS`뿐 아니라 실제 범위 문자열의 첫 시각,
  잘못된 값, 기존 YouTube query/hash를 다뤄야 한다. URL 문자열 연결보다 `URL`/
  `URLSearchParams`를 쓴다. 자동 다음 후보는 아직 불러오지 않은 page가 있을 때 prefetch한 뒤
  종료 상태를 판단한다.
- **PR-03**: B6의 lineage·terminal state·attention·멱등·ADR-34 확인 없이는 S 크기 “배선”이 아니다.
  `done` 안에서도 quota deferred 같은 비성공 outcome을 분리해 사용자에게 재시작 이유를 보여준다.
- **PR-04**: schema, 모든 enqueue call site, parent/child propagation, scheduler stale job 제거,
  durable stage event까지 포함하면 S가 아니라 최소 M이다. lane 공정성·starvation과 process 재시작
  테스트를 추가한다.
- **PR-05/23**: 실제 quota 확인→gateway 전 호출 강제→usage 수집→추정식 조정 순으로 합친다.
  hardcoded 무료/유료 숫자를 `.env.example`의 신뢰 가능한 기본 계약처럼 쓰지 않는다.
- **PR-06**: queue query는 `USER_JOB_TYPES` filter semantics를 유지한다. `failed_recent`는
  attention 모델로 교체하고, PR-28 뒤 `JobStatusLink`의 링크도 `/jobs`로 바꾼다.

#### Phase 1 / PR-07~10

- **PR-07**: `queue_reason`은 파생 문자열 하나로 끝내지 말고 안정 enum과 우선순위 규칙을
  문서화한다. 목록 filter에 reason·source kind·grounding을 함께 노출한다.
- **PR-08**: B7의 envelope·total·new count·page 밖 deep link를 포함한다. backend와 frontend를
  분리한다면 contract PR을 먼저 머지한다. “2,000건에서 3초”는 server latency, 첫 paint,
  검색 debounce 중 무엇인지 측정 조건을 명시한다.
- **PR-09**: hard delete 성공에 대한 undo는 불가능하다. B1 soft delete가 선행돼야 한다.
  “후보가 만든 고아 장소”와 여러 후보가 공유하는 장소를 reference count와 mapping 기준으로
  분리하고, place 전체 삭제 helper를 그대로 재사용하지 않는다.
- **PR-10**: 현재 상한 500과 “모두” 표현이 충돌한다. filter snapshot bulk action과 preview count를
  쓰고, 실패 ID 때문에 전체 transaction이 장시간 lock되지 않도록 크기·retry 계약을 정한다.

#### Phase 2 / PR-11~14

- **PR-11**: `youtube_videos`의 마지막 source/failure 두 컬럼만으로는 provider 개선이 불가능하다.
  영상·run·provider·순서·시작/종료·duration·outcome·language·detail·tool version을 담는
  `transcript_attempts` 또는 durable event를 둔다. 성공 전 실패도 보존한다.
- **수율 수치**: 역사적 no-Whisper 실행은 `3/27=11.1%`, 별도 Whisper 재실행은
  `11/27=40.7%`다. “11~30%”는 근거가 없고 두 실행은 통제 A/B도 아니다. 현재 production 수율과
  Whisper 활성 여부는 runtime 확인 전 미확인으로 표시한다.
- **PR-12/13**: B3 순서와 state gate를 따른다. raw segment ID를 먼저 보존하고 주소 결과와 POI
  결과를 같은 name gate에 넣지 않는다.
- **PR-14**: 접미 제거·300m 자동 병합 대신 중복 **제안**부터 시작한다. 오병합률을 수동 표본으로
  측정한 뒤 provider ID·주소가 일치하는 좁은 경우에만 자동화한다.

#### Phase 3 / PR-15~16

- **PR-15**: `startTransition`은 network debounce나 request cancellation의 대체가 아니다.
  선택 highlight는 transition으로 분리하되 provider 요청은 250~400ms debounce·abort·candidate
  identity를 유지한다. component 분해는 동작 보존 commit과 UX 변경 commit을 분리한다.
- **PR-16**: shortcut guard는 input 계열뿐 아니라 button/link/dialog, IME composition,
  modifier key, 반복 keydown을 다룬다. `1~9`는 provider별 번호 충돌과 loading 중 재정렬을 막는다.
  모바일 상세 route에서도 처리 후 다음 후보와 undo가 끊기지 않는 별도 acceptance test가 필요하다.
- **정밀도 측정**: MATCHED 후보는 현재 queue에서 사라져 뒤집힘 표본을 만들기 어렵다.
  reopen 가능한 result link 또는 소량의 auto-match audit queue를 먼저 만들어야 자동확정 정밀도
  지표가 실제로 계산된다.

#### Phase 4 / PR-17~19

- **PR-17**: description은 recall 경로다. 후보 수가 늘어나는 것을 신뢰성 향상으로 계산하지 말고
  검수 승인율·중복률·후보당 처리시간을 별도 측정한다. YouTube API description의 refresh/delete와
  provenance 상태도 Phase -1 결정에 맞춘다.
- **PR-18**: T-091은 과거 `TRANSCRIPT_WHISPER_ENABLED=true`, model base로 실행해 3/27→11/27을
  기록했지만 현재 production env는 gitignored라 확인되지 않는다. `AUTO_ENABLED`와 manual force를
  분리하고 auto 기본값, model, duration, 일일 CPU 예산, concurrency 1을 운영 결정으로 명시한다.
  “기본 경로 불변”이라는 현재 문구는 역사 문서와 충돌한다.
- **PR-19**: 하나의 OCR 기능을 두 실험으로 나눈다.
  1. 기존 candidate timestamp 주변 frame을 OCR/vision으로 확인하는 **corroboration** —
     이름·간판이 일치하면 검수 근거를 강화해 검수 횟수를 줄일 수 있다.
  2. 자막 없는 영상의 균등 frame에서 후보를 찾는 **source recovery** —
     recall은 늘지만 visual-only 검수도 늘므로 검수 감소 지표와 분리한다.
  `EvidenceSourceKind.VISUAL`, job type/handler, config, multimodal gateway, media asset API/BFF,
  썸네일 UI, 비용·quota, source별 grounding을 변경 파일에 포함한다. B4 승인과 PR-23 이후에만
  배포한다.

#### Phase 5 / PR-20~24

- **PR-20a/20**: frontend limit 확장은 backend 상한 500 때문에 완전한 hotfix가 아니다.
  pagination contract를 Phase 1로 올린다. `source_videos`는 현재 UI와 service 호출부 사용을
  전수 확인하고 detail lazy-load를 먼저 배포한 뒤 제거한다. O(전체)→O(limit)는 count/facets/
  정렬 aggregate까지 `EXPLAIN (ANALYZE, BUFFERS)`로 확인한 뒤 주장한다.
- **PR-21**: 공통 60일 cache를 철회한다. key에는 provider·endpoint·전체 canonical parameter·
  normalization version을 넣고, response를 `success_nonempty|success_empty|transient_error|
  permanent_error`로 구분한다. error를 빈 성공으로 60일 cache하지 않고 positive/negative TTL을
  분리한다. provider policy matrix에서 허용된 필드만 cache한다.
- **PR-22**: process-local throttle/watermark/dirty flag는 API·scheduler 두 process와 재시작에서
  정본이 될 수 없다. candidate뿐 아니라 연결된 place·video·channel·playlist 변경도 payload를
  바꾼다. DB durable dirty queue/outbox에 관련 candidate ID와 reason을 같은 transaction으로 쓰고,
  주기 full reconciliation은 안전망으로만 둔다. B1 tombstone transaction이 선행이다.
- **PR-23**: Phase 0~1로 이동하고 multimodal까지 포함하는 gateway 계약을 먼저 확정한다.
- **PR-24**: caption network I/O와 Whisper CPU 작업을 분리하고 각 semaphore를 따로 둔다.
  처리량뿐 아니라 provider별 실패율, 429, CPU load, queue latency를 전후 비교한다.

#### Phase 6 / PR-25~28

- **PR-25**: `TravelPlace`에는 현재 `sigungu_code`와 `legal_dong_code`만 있고
  `sido_code` 컬럼은 없다. 유도 규칙을 계약으로 정하거나 schema/migration을 추가해야 한다.
  JSON endpoint에는 Pydantic response model을, GPX/기타 binary export에는 OpenAPI content schema를
  별도로 둔다. 전체 payload hash 재발급은 consumer canary·cursor drain·rollback까지 계획한다.
  `geocoded_only`가 적용될 정확한 endpoint와 기존 기본값 변경 영향을 명시한다.
- **PR-26**: offset만 추가하지 말고 B7 envelope를 따른다. `source_videos` 기본 제거는 파괴적
  변경이므로 실제 소비자 0을 운영 inventory로 확인하거나 additive version/opt-in 전환 기간을 둔다.
- **PR-27**: 목록만으로는 “근거 확인”이 완결되지 않는다. 경량 목록과 별도로
  `get_review_candidate_detail(candidate_id)`를 추가해 raw evidence·provider 판정·영상 링크를
  읽을 수 있어야 한다. docstring만으로 사람 검수를 강제할 수 없으므로 resolve 감사 actor와
  필요한 review evidence를 서버에서 검증한다.
- **PR-28**: `/runs`의 state·job_types는 이미 구현돼 있다. 실제 누락은 안정 pagination·total,
  attention filter, `JobStatusLink` 이동, 모바일 job action이다. PR-03/06의 잘못된 전제를
  그대로 복제하지 않는다.

### 10.5 수정된 실행 순서 — 최대 10단계

| 순서 | 작업 묶음 | 핵심 산출물과 종료 조건 |
|---|---|---|
| 1 | **Phase -1 정책·기준선** | YouTube/Google/Naver/Kakao/VWorld matrix, kill switch, RustFS inventory, production key·Whisper runtime inventory, 기준 커밋·수치 정정 |
| 2 | **현재 정확성 hotfix** | `exclude_video` 잘못된 컬럼 수정, 선택 hit provenance 보존, 101/501번째 장소 접근 가능한 목록 contract 최소 수리 |
| 3 | **candidate 상태 모델** | soft delete, mapping 해제, transactional tombstone, undo/reopen, video exclude 통합 테스트 |
| 4 | **API scope와 rollout** | read/admin DB 제약·cache·route policy, `kor-travel-map` read-key 회전, 구 consumer key 제거 |
| 5 | **job·LLM 실행 기반** | restart lineage·attention·ADR-34, durable stage events, 전 호출 async/multimodal gateway, quota 실측, lane 상속 |
| 6 | **서버 목록 계약** | review/runs/destinations/themes envelope, stable cursor, filtered total, new count, filter snapshot bulk |
| 7 | **검수 UX** | 자동 다음·timestamp·URL filter·reason/source/grounding·undo·안전한 shortcut·모바일 E2E |
| 8 | **자막 관측과 raw evidence** | provider attempt history, 정확한 baseline, raw segment ID, grounding state, manual/auto Whisper 정책 |
| 9 | **자동확정·identity gate** | result kind, raw grounding block, pairwise name·region·domestic gate, auto-match audit 표본, 보수적 dedup |
| 10 | **측정 후 확장·성능·공급 마감** | SQL pushdown, durable export outbox, provider별 cache, 승인된 OCR/vision, features/themes/MCP/IA 계약 |

병렬화는 가능하지만 다음 선행 관계는 고정한다.

- Phase -1은 PR-18/19와 제한 provider 영구 저장의 release gate다.
- candidate 상태 모델은 PR-09/10/22보다 먼저다.
- gateway·durable metrics는 lane 처리량 조정과 vision보다 먼저다.
- `PR-11 → raw PR-13 → PR-12 → 보수적 PR-14` 순서를 지킨다.
- 목록 contract는 table/triage 대규모 UI 재작성보다 먼저다.

### 10.6 수정 문서의 필수 acceptance gate

| Gate | 통과 조건 |
|---|---|
| G1 삭제 정합성 | export된 후보를 삭제·영상 제외한 뒤 process를 재시작해도 changes가 tombstone을 전달하고, undo 후 새 upsert가 전달된다. |
| G2 인증 | read key로 snapshot/changes 다중 page 200, 모든 쓰기와 내부 검수 GET 403, 구 consumer static key 제거 확인. |
| G3 provenance | provider hit 선택 후 주소·provider·native ID·query·원본값·수정값이 감사 가능하며 제한 provider 데이터는 정책대로 차단된다. |
| G4 자동확정 | 신규 transcript auto-match 100%가 raw grounding verified이며 address result·unknown domestic·이름/지역 불일치는 export되지 않는다. |
| G5 queue 완결성 | 301/501건 fixture에서 total·has_more·cursor·new count가 정확하고 page 밖 deep link와 “모두 처리”가 거짓말하지 않는다. |
| G6 job 복구 | 중복 restart 1회만 생성, lineage·lane 유지, 원본 failure attention 해소, 모든 재실행에 확인 UI가 적용된다. |
| G7 자막 관측 | 각 provider 시도·latency·outcome이 보존되고 현재 runtime 기준 수율을 재현할 수 있다. |
| G8 성능 | p50/p95, queue latency, stage duration, 429/실패율을 전후 비교하며 “O(limit)”은 query plan과 부하 fixture로 증명한다. |
| G9 검수 품질 | auto-match audit 표본의 오확정률과 source별 사람 승인율을 기록한다. OCR source recovery는 검수 증가량도 함께 보고한다. |
| G10 외부 계약 | provider 정책 확인일·버전, attribution, cache 만료, downstream canary와 rollback 결과가 runbook/ADR에 남는다. |

### 10.7 최종 판단

이 문서는 문제를 넓게 발견하고 PR 단위로 쪼갠 **좋은 초안**이다. 특히 queue 중심 검수,
실패 사유 관측, read/admin 분리, LLM gateway라는 축은 유지해야 한다. 다만 현재 상태는
다음 세 이유로 실행 계약으로 승인할 수 없다.

1. undo와 tombstone이 hard delete 뒤에도 복구될 것이라는 전제가 DB 제약상 성립하지 않는다.
2. “신뢰성 개선”의 핵심인 raw grounding이 자동확정을 막지 않고, 검수자가 선택한 provider
   provenance도 실제 저장 직전에 사라진다.
3. 미디어·provider 정책과 실제 소비자 key rotation이 rollout 밖에 있어 보안·외부 API
   실용성 완료 기준이 닫히지 않는다.

따라서 **방향 승인 / 실행계획 수정 요구**로 판정한다. §10.3의 B1~B7, §10.5의 순서,
§10.6의 gate를 원문 계획에 반영한 뒤 사용자 리뷰를 받아야 하며, 그 전에는 §9에 따라
`tasks.md`와 ADR을 선반영하지 않는다.
