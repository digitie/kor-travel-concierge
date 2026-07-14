# TASKS — 백로그

작업 항목은 `T-NNN` 형식의 ID로 관리한다. 새 작업은 "대기"의 우선순위 순서대로 들어가고, 진행 중이 되면 담당자를 표시한다. 완료된 작업은 "완료" 섹션 상단에 누적한다.

---

## 진행 중

없음.

---

## 대기 (우선순위 순)

개선 로드맵(`docs/improvement-roadmap-2026-07.md`, Codex 리뷰 §10 반영판) 실행 작업이다. **Agent A / Agent B 두 트랙이 병렬 진행**하며, 트랙 내 순서·교차 선행·파일 소유는 로드맵 §4를 따른다. 각 태스크는 해당 PR 블록의 "개정(2026-07-13)" 항목과 §7.1 acceptance gate(G1~G10)를 완료 조건에 포함한다.

### Agent A — 백엔드 상태 모델·파이프라인·정책 (T-158~T-173)

- [ ] **T-193**: [조건부] 자막 품질 개선 — 사용자 결정(2026-07-13)으로 신설: prod whisper 자동 전사는
  의도된 현행 유지이며, 품질 개선 필요성이 확인되면 착수한다. whisper 모델 크기 상향 평가(base→small
  등), 전사 품질 스코어링, 재전사 정책 개선. T-164의 transcript_attempts 데이터로 필요성 판단.
  (T-158 결정 ⑧ 파생)

### Agent B — 검수 UX·공급 API·보안 표면 (T-174~T-192)
- [ ] **T-191**: MCP 검수 도구 — `list_review_candidates` + `get_review_candidate_detail`, resolve 감사 actor·review evidence 서버 검증(자동 승인 경로 금지). 강제 Whisper 재전사·재교정의 transcript/media asset은 content hash가 같을 때만 재사용하고, 내용이 바뀌면 versioned object key와 새 asset row를 발급해 candidate evidence가 실제 추출 원문을 가리키도록 한다(기존 RustFS 객체 무기한 보존). (PR-27 개정판)
---

## 완료

- [x] **T-173**: 프레임 비전/OCR 실험 경로 — **게이트 off로 착수**(사용자 지시, `docs/plan-t173-vision-ocr.md`
  §1 게이트 판정·G9 post-deploy 지표는 측정 작업이라 제외). Agent A(백엔드)만 구현 — Agent B(media asset
  서빙 BFF/프록시·검수 썸네일 UI, 계획서 §2.2)는 이번 범위 밖(플래그 off라 서빙 라우트가 있어도 프레임이
  노출되지 않음, 후속 태스크 필요). 착수 전 §1.5 대안 비교(제3안 Gemini URL 분석 승격 대비)를 journal에
  기록하고 본안(프레임 비전)을 택했다. 신규 `visual_extraction.py`: 자막·whisper 최종 실패 영상 대상
  선별(새 컬럼 없이 기존 candidates/media_assets로 idempotent 재선별) → 균등 간격 프레임 추출(`frame_extraction`
  인프라 재사용, 다운로드 없음) → `generate_multimodal` **영상당 정확히 1콜**(N장 inline_data, `VISUAL_FRAME_MAX`
  clip)로 OCR + 장소명 후보. 진입점이 **플래그 확인을 첫 동작**으로 두고(off면 완전 무개입) 그다음 DeepSeek
  엔진 가드(`generate_multimodal`은 Gemini 전용, 부록 B 안전장치 ①)를 확인한다. `batch_poi_service.py`의
  후보 persist 로직을 `_persist_candidates` 공용 헬퍼로 refactor해 description/visual이 공유하며, VISUAL은
  grounding 평가를 건너뛰고 `GroundingStatus.NOT_APPLICABLE`로 고정한다(부록 B 안전장치 ②, OCR을 transcript
  grounding으로 오판정 방지). **핵심 수리**: `geocode_service.py`의 자동확정 recall 예외를 DESCRIPTION
  단일 조건에서 `{DESCRIPTION, VISUAL}` 집합으로 일반화 — 없으면 VISUAL 후보가 자동확정·export까지 흐를
  수 있었다(회귀 테스트로 pin). `llm_client.py`에 `inline_data` 전용 저-가산 토큰 추정(1,300, 기존
  `file_data` 65,536 하한과 분리)을 추가해 8프레임 비전 1콜의 TPM 과대예약을 막았다. `config.py`:
  `VISUAL_EXTRACTION_ENABLED`(기본 **false**)·`VISUAL_FRAME_COUNT_DEFAULT`(6, 계획서 8 대신 비용 가드
  반영)·`VISUAL_FRAME_MAX`(8)·`VISUAL_MIN_DURATION_SECONDS`(60). `scheduler/worker.py`에 `visual_extraction`
  job type 등록(기본 `LANE_BATCH`, whisper 수동 재전사와 동일 운영 결정). 마이그레이션 불필요(String 컬럼
  기존 enum 값 재사용, Alembic head `20260714_0028` 유지 확인). 신규 `test_etl_visual_extraction.py` 12건
  (프레임 샘플링·**후보 격리 자동확정 차단 회귀 핵심**·플래그 off 완전 무개입·DeepSeek 엔진 가드·비전 1콜
  상한+clip·evidence 보존·grounding not_applicable 무회귀·dedup 비대칭). 검증: 로컬 disposable PostgreSQL
  DB에서 타깃 111건 + backend 전체 **804건 전부 통과**(Windows 호스트 10분 tool timeout 제약으로 3개 chunk
  분할 실행, 실패 0건), 변경 Python 8개 파일 Ruff clean. prod 활성화는 B4/PR-29 provider 정책 승인과 §1
  게이트 GO 판정이 모두 선행돼야 한다(코드는 병합돼도 플래그 off + 미배포로만 존재). (2026-07-14, 로드맵
  PR-19 개정판)
- [x] **T-172**: 자막 fetch 병렬화 (PR-24, G8) — poi_batch 1단계 **캡션 fetch만** 병렬화하고 교정·POI
  배치 추출·지오코딩(2~4단계)은 순차 불변으로 두었다(LLM은 T-161 게이트웨이 리미터 소관). 게이트(§1
  GO/NO-GO·§6 G8)는 배포 후 관측 지표라 코드에서 제외 — 사용자 지시로 미측정 상태에서 구현만 진행.
  `transcript.py`에 캡션 전용 진입점 신설(`CAPTION_PROVIDERS`·`caption_provider_chain()`·
  `fetch_captions_async`·`transcribe_whisper_async`·`merge_outcomes`) — merge는 sequence 재부여·whisper
  성공 승격으로 `success_provider`/`failure_code` 파생과 `transcript_attempts` 형태를 순차 체인과 동일하게
  유지(무회귀 핵심). `process_video_batch`는 단일 `transcript_fetcher`를 `caption_fetcher|None`
  (None=force_whisper) + `whisper_fetcher|None`로 교체(shim 없음)하고, 1단계를 Phase 0(순차 캐시 판정)→
  1a(병렬 캡션 `Semaphore(CRAWL_MAX_CONCURRENT_VIDEOS)`+`gather`)→1b(whisper 순차 `WHISPER_MAX_CONCURRENT=1`)→
  1c(순차·공유 세션)로 3분할했다. 결과를 `dict[video_id]`에 담아 **원본 videos 순서**로 소비(alias가 gather
  완료 순서에 안 묶임), task별 monotonic elapsed로 `transcript_fetch` stage 이벤트 실측 보고. 병렬 구간은
  공유 `session`·`store_and_record`·ORM·`record_stage_event`·`attempt_recorder`를 절대 호출하지 않는다(전부
  1c). `worker.poi_batch_handler`는 caption+whisper 2개 주입(force_whisper=caption None). `config.py`는
  `CRAWL_MAX_CONCURRENT_VIDEOS` 소생·기본 4→3, 사문화 `HTTP_MAX_CONCURRENT_REQUESTS` 삭제(참조 0회),
  `.env.example`·`docs/dev-environment.md` 동기화. `_whisper_forced_transcript_fetcher`는 **이름 유지**·whisper
  단건 semantics로 변경. **2렌즈 리뷰 Finding-1(whisper 예외 격리)**: `transcribe_whisper_async`가 예외를
  삼켜 분류된 whisper 실패 attempt로 변환(공용 `whisper_failure_attempt` 헬퍼, 구 `_run_provider` 동일 매핑,
  절대 re-raise 금지) + Phase 1b per-video 격리로 whisper 예외가 배치 전체를 죽이지 않고 description-fallback
  으로 이어진다. 신규 `test_transcript_fetch_parallel.py` 10건(캡션 동시성 상한·whisper 동시성 1 auto+force·
  세션 비공유·사유코드 분포 병렬==순차·출력 등가 golden·벽시계 단축·stage 영상당 1건 + caption raise 격리·
  전파·whisper raise→description fallback) + 기존 5파일 콜사이트/배선 갱신. 검증: 격리 disposable Postgres에서
  타깃 6파일 **55 passed**, backend 전체 **792 passed**(1 warning), 변경 `.py` 전부 Ruff clean. migration
  없음. E2E는 자막 fetch 미경유라 무영향. (2026-07-14, PR-24 개정판)
- [x] **T-192**: 작업 IA 정리 (/jobs 인덱스·nav 재편·홈 배너) (U10/U12/U13) — 작업 표면을 `/jobs`(목록·이력·
  액션)로 통합/축소했다. **`/jobs` 인덱스**(JobsDashboard): 상단 진행중·대기 큐(T-181 run-queue 재사용) + 하단
  이력 테이블(T-177 `listRunsPage` cursor·total 재사용) + 상태/유형/attention 필터 + 더 보기, 행 액션=상세+
  `RunActionButtons`(PR-03). `jobs-history.ts`는 UI filter→`/runs` params 매핑만(`user_jobs_only⊕job_types`
  상호배제, 계약 재구현 없음). **nav 재편**(주 결과·수집·검수·작업·설정 / 보조 상태·API, `JobStatusLink`→
  `/jobs`). **`/status` 축소**(작업 테이블→/jobs, 검수 후보 MetricCard→/review). **`/collect` 축소**(죽은
  `detailRun` 제거·1줄 요약+/jobs). **홈 배너**(검수 대기 N→검수 시작·attention K→/jobs?attention=open). 2렌즈
  적대적 리뷰: 확정 BLOCKER/MAJOR 0(계약 재사용·기능 유실 없음·죽은 코드 0·배너 count 정본·E2E 정합). MINOR
  3(문서화·후속): 대조 필터 조합 무음 빈 이력(UX), 구 `runs_by_state` 집계 뷰 미이관(backend 반환 유지·재노출
  용이), /status 카드 텍스트 E2E 커버리지 축소(count는 aria-label로 유지). 불변: `/runs`·run-queue·attention
  계약 재추가 없음, backend routes.py 무변경, migration 없음. 검증: frontend vitest 330 passed·lint/type-check/
  build green, E2E heading 갱신 후 n150 이연. (2026-07-14, 로드맵 PR-28 개정·U10/U12/U13)
- [x] **T-187**: 검수 키보드 단축키 + 처리 모드(triage) + provenance facet (U5/U1) — 게이트(건당 인터랙션
  측정) 모호 → **본안(처리 모드) 채택**. `useReviewKeyboard.ts` 전역 keydown(J/K·1~9 번호 배지·Enter·X·U·/·?)
  + **확장 포커스 가드**(IME·modifier·repeat·input/button/role=dialog/menu/listbox/option/combobox/searchbox/
  alertdialog…). **triage 모드**(URL `?mode=triage|table`, 기본 triage — mode를 뷰 concern으로 분리해 전환 시
  큐 재조회·선택 초기화 없음): 진행 레일+중앙 후보 카드(T-186 컴포넌트 재사용)+지도, table=기존 테이블/bulk.
  저장·제외 후 자동 다음(PR-02)·debounce·abort·undo·bulk·URL 정본 **배선만 재사용**. **서버 facet 전환**:
  `list_review_source_facets`+`GET /destinations/review-facets`(admin)로 후보 provenance별 count·**확정 장소
  없는 출처 노출**·현재 filter 반영, 기존 결과보기 `/destinations/facets`(place) 보존, n/m·모두 처리=T-182
  filtered total. 2렌즈 적대적 리뷰: 확정 BLOCKER/MAJOR 0, MINOR 3 정리(1~9 번호를 선택 가능 hit 단일 정본으로
  통일·배지/키보드/지도 정합, 포커스 role 보강, 그룹 라벨 raw fallback). 불변: T-186 동작 계약·table·bulk
  보존, 자동 승인 없음, migration 없음. 검증: backend 782 passed(신규 facet 3건), frontend vitest 314 passed·
  lint/type-check/build green, E2E n150 이연. (2026-07-14, 로드맵 PR-16 개정·U5/U1)
- [x] **T-186**: review 페이지 구조 분해 (S8, 동작 보존) — `review/page.tsx`(단일 5065줄)를 **19줄 조립
  전용**으로 축소하고 상태 소유를 `components/review/`로 완전 분해했다. **codex 완전판 인수**(착수 시 codex가
  main 워크트리에서 더 완전한 분해를 미커밋 진행 중임을 발견 → 사용자 결정으로 codex 완전판을 현행 main
  위로 인수·검증). 분해: `useReviewQueue`(큐·필터·선택·mutation·undo·URL 정본)·`useCandidateSearch`(provider·
  opinion 검색 reducer·300ms debounce·abort·generation)·`ConfirmForm`·`CandidateTable`·`SearchResultsPanel`·
  `types`·`ReviewWorkspace`(조립 루트), `lib/transcript.ts`(cleanTranscript·근거 스크롤 공용 유틸, 상세 뷰
  중복 제거). startTransition은 후보 강조·폼 초기화 뒤 provider query 활성화만 분리. **UX 무변경·순수 동작
  보존**. 2렌즈 적대적 리뷰: 원본과 line-level 대조로 6개 동작 계약(debounce/abort/generation·startTransition
  경계·자동 다음 후보 T-179·undo T-184·bulk T-185·URL 딥링크·removed provider 0회) 전부 보존 확인, 확정
  BLOCKER/MAJOR 0. codex 신규 테스트 1건 기대값 오류(Google 저장 정책 제외 미반영) 1줄 정정. known-MINOR
  (문서화): hook effect 배선 단위 테스트 부재(repo jsdom/RTL 미사용→E2E n150 가드), React Query 캐시 엔트리
  누적(gcTime GC로 유한·회귀 아님). 검증: frontend lint·type-check·build green, vitest 256/256, backend
  무변경. E2E n150 이연. (2026-07-14, 로드맵 PR-15 개정·S8)
- [x] **T-190**: themes 공급 API 마감 (A3) — `/themes/places`·`/themes/video/{id}/places`를 `limit=None`
  전량 반환에서 **PR-32 공통 envelope**(items/next_cursor/has_more/total/newest_id/newer_than)로 전환했다.
  cursor·limit(기본 200·상한 500)은 T-188 `list_place_summaries_page`(sort=mention_count) 재사용. 동영상 테마
  `sufficient` 게이트(`page.total>=5`)와 미공개 사유(빈 items+sufficient/min_required/poi_count, next_cursor/
  has_more 숨김) 보존(ADR-35). `source_videos` 기본 제외 + `include=sources` opt-in. `docs/themes-api.md`
  계약 문서 신설, frontend `/api-test` 갱신. 파괴적 변경(places→items·source_videos 기본 제거)이나 외부
  소비자 0(kor-travel-map은 `/features/*`만). 2렌즈 적대적 리뷰: 확정 BLOCKER/MAJOR 0, MINOR 3 정리
  (`include` 대소문자 무시·themes-api.md 산문 정정·video 게이트 docstring 정확화). 불변: `/themes` 목록
  (T-177)·`list_place_summaries`/`_page`(T-188)·feature export(T-189)·sufficient 게이트 미변경(재사용만).
  검증: 격리 DB backend ~779 passed(실패 0), theme+pagination 23 passed, frontend build 통과, migration 없음.
  (2026-07-14, 로드맵 PR-26 개정·A3)
- [x] **T-189**: features 계약 마감 (A5, G10) — feature export payload·목록 계약을 additive로 마감했다.
  `_build_payload` address block의 하드코딩 None을 제거해 `sigungu_code`·`legal_dong_code`를 place
  실데이터로 주입하고, `sido_code`는 컬럼이 없어 `sigungu_code[:2]`(없으면 `legal_dong_code[:2]`) 유도
  규칙으로 계약화(migration 없음). item에 `schema_version=1`(payload 본문·hash 반영), `/features/snapshot`·
  `changes`에 `FeatureExportPageResponse` response_model(item은 `extra=allow` 개방형이라 기존 필드 보존),
  cursor 오류를 `{code,message}`(invalid_cursor·invalid_params, 한국어 message 유지)로. `/destinations/export`에
  `geocoded_only` 파라미터 — 미지정 시 **포맷 기반 기본값**(gpx/kml=True 미검증 좌표 제외, xlsx=False 전체
  포함), 명시값 존중. 재발행: 행정코드·schema_version으로 전 payload_hash가 바뀌어 T-171 시간당 reconcile
  안전망이 최대 1h 내 새 sequence로 재발행(cursor·operation·sequence 계약 불변). 2렌즈 적대적 리뷰: 확정
  BLOCKER/MAJOR 0. 병합 전 보강 — geocoded_only 포맷 기반(xlsx 조용한 행 탈락 방지)·sido legal_dong
  fallback·schema_version hash 테스트. 문서화: 에러 body 형태·저트래픽 배포 권고·reconcile 의존
  (`docs/feature-export-api.md`). 검증: 격리 DB backend 전체 pytest 774 passed(실패 0), migration 없음·단일
  head. (2026-07-14, 로드맵 PR-25 개정·A5·G10)
- [x] **T-174**: 검수 선택 provenance 보존 — 선택 `PlaceSearchHit`을 typed state로 유지하고 provider native ID·query·검색/선택 시각·원본 이름/주소/좌표/카테고리와 실제 확정값을 `provider_evidence_json.review.resolutions[]`에 분리 누적한다. 허용 provider의 주소와 서버 도출 `api_source`를 전달하며 Google 저장·VWorld marker·Gemini 우회는 차단한다. 100m 근접 장소는 이름·provider ID·거리 identity gate와 명시적 병합/신규 결정으로 처리하고, 후보 row lock+신규 생성 advisory lock으로 동시 검수 중복을 방지한다. 웹 409는 최초 요청 snapshot으로 재시도하고 MCP도 같은 구조화 후보/결정 계약을 지원한다. category 요청 abort·candidate identity, 폼 소유 후보 검증, 원본/수정 표시와 접근성 근거를 보강했다. n150에서 backend 타깃 17건, 기준선 실패 2건 제외 전체 회귀, frontend lint/type-check/Vitest 33건/build, Playwright 5건 통과. (2026-07-13, PR-31, §10 B2, G3)
- [x] **T-175**: API 키 read/admin 스코프 — `public_api_keys.scope`를 기존 행 `read` backfill·NOT NULL·CHECK로 추가하고, immutable scope(변경은 revoke+재발급), generation-safe `key_hash→scope` cache, create/revoke+audit 단일 transaction을 적용했다. 공급 GET 11경로만 read exact allowlist로 열고 내부 GET·모든 write는 deny-by-default 403, `?key=`는 DB read만, DB/static admin은 header만, CIDR 우회는 read, `/admin/*`는 proxy 전용으로 유지했다. 발급 UI 기본 read·admin 위험 안내·scope 표시, 직접 API origin curl, ADR-36·공급 계약을 함께 갱신했다. production 소비자 key rotation은 후속 T-176에서 완료했다. n150에서 auth 42건, 기준선 2건 제외 backend 전체, migration upgrade/backfill/CHECK/downgrade, frontend lint/type-check/Vitest 33건/build, 설정 scope E2E 통과. (2026-07-13, PR-01 개정판, §10 B5)
- [x] **T-176**: 소비자 read key 회전 rollout — DB read key를 발급해 docker-manager 단일 원천에서 kor-travel-map Dagster·daemon에만 주입하고 Map API에서는 제거했다. snapshot/changes는 n150 prod 실데이터를 `limit=1` 2페이지 cursor 확인 후 `limit=200` 8페이지·1,416개 전체 순회했으며 실제 Dagster 가져오기 경로도 각 1,416개를 확인했다. read 공급 GET 200·write/내부 GET 403, 구 정적 admin key 401·신규 BFF/operator admin GET 200, UI 로그인 POST 200+Set-Cookie/session BFF 200·틀린 비밀번호 401을 검증했다. 중첩 전환 뒤 구 값을 제거하고 평문 임시 파일·백업·복원 지점을 삭제했으며 key 값은 문서화하지 않았다. Concierge PR #182, kor-travel-map PR #664, docker-manager PR #51. (2026-07-13, PR-33, §10 B5, G2)
- [x] **T-177**: 목록 공통 envelope 계약 — 검수/작업/장소/테마에 `{items,next_cursor,has_more,total,newest_id,newer_than}`와 watermark keyset·filter fingerprint cursor를 적용했다. 네 목록은 인증 세션과 분리된 `REPEATABLE READ` transaction에서 envelope를 만들고, 입력·cursor domain을 제한하며 page 밖 상세 조회를 보장한다. 프런트 호환 wrapper와 테마 regroup로 기존 화면을 보존하고 features 계약은 불변으로 고정했다. 301/501건·filter 오사용·동률·신규 수·인증 cache miss 회귀를 n150 PostgreSQL에서 검증하고, frontend lint/type-check/Vitest 34건/build와 Playwright 5건을 통과했다. (2026-07-13, PR-32, §10 B7, G5)
- [x] **T-178**: `/destinations` 접근 최소 수리 — 결과 화면을 `listDestinationsPage` 기반 100개 `useInfiniteQuery`로 전환해 101/501번째를 cursor append로 노출했다. 불러온 수/기준 total, 더 보기·중복 클릭 방지·초기 retry·수동 새로고침·완료/목록 변경 불일치 상태를 구분하고, `place_id` dedupe는 최초 순서와 최신 payload를 보존한다. page 밖 `?place=`는 filter를 지우지 않고 단건 상세를 직접 연다. n150 Playwright 100×5+1 및 deep link 2건을 포함한 7건과 frontend lint/type-check/Vitest 34건/build를 통과했다. backend 계약은 변경하지 않았다. (2026-07-13, PR-20a 확장판)
- [x] **T-179**: 검수 저장 후 자동 다음 후보 + 타임스탬프 링크 — 검수 목록을 300개 단위 `useInfiniteQuery`로 전환하고 저장·제외·개별 삭제 성공 시 처리 시작 snapshot의 visible 순서로 다음 후보를 선택한다. 뒤 page가 있으면 숨김 후보 page를 포함해 첫 visible 후보 또는 마지막 page까지 자동 탐색하며, 수동 선택은 진행 중 탐색과 딥링크를 취소한다. 최초·딥링크 선택은 자동 검색을 억제하고 이후 자동 진행만 검색을 시작한다. polling 중 선택 후보가 page 밖으로 이동해도 입력 snapshot을 보존하며 scope·늦은 응답·상세 삭제 mutex·오류/재시도를 격리했다. `MM:SS`/`HH:MM:SS`/범위 첫 시각 파서와 `URL`/`URLSearchParams` 기반 YouTube `t=` 링크, 비정상 값 단위 테스트를 추가했다. n150에서 frontend lint/type-check/Vitest/production build와 Playwright 저장·제외·개별 삭제·숨김 page 연속 탐색을 검증했다. 적대적 검토를 3회 반복해 최종 P0/P1 0건을 확인했다. (2026-07-13, PR-02 개정판)
- [x] **T-180**: 실패 작업 재시작 UI — `/status`와 `/jobs/[jobId]`에 terminal 재시작·running 중지용 공용 `RunActionButtons`를 배선하고 `ConfirmActionButton`, pending 잠금, 행이 즉시 사라져도 유지되는 상위 live feedback을 적용했다. 상태·outcome·attention·lineage를 분리해 `done+quota_deferred`를 성공과 다르게 표시하고 원본/후속 작업 링크를 제공한다. 백엔드는 중지-vs-claim을 `FOR UPDATE`로 직렬화하고 응답/audit용 전이 snapshot을 고정했으며, 재시작 동시 멱등과 보류 child를 거친 성공 descendant의 조상 attention 해소, worker의 `quota_deferred is True` 계약을 보강했다. 적대적 검토를 backend·UX·테스트 3렌즈로 2회 이상 반복해 최종 P0/P1 0건을 확인했다. 최신 main의 T-163 레인 분리 위로 재배치한 뒤 n150에서 관련 backend 113건·변경 파일 Ruff, frontend lint·type-check·Vitest 104건·build, Playwright 11건 통과(live 4건 skip), backend 전체 434건 중 433건 통과(기존 postprocess category 기대 1건 실패)를 검증했다. (2026-07-13, PR-03 개정판, G6)
- [x] **T-181**: run-queue 폴링 통합 — `GET /runs/queue`가 서버 정본 `USER_JOB_TYPES`의 running→pending FIFO 항목을 최대 100건만 반환하면서 window 집계로 정확한 상태별 수·`has_more`, 종료된 open attention 수를 같은 `REPEATABLE READ` snapshot에서 제공한다. 큰 status/result 컬럼은 `raiseload`로 배제하고 static route를 동적 job route보다 먼저 등록했다. 세 화면은 `['run-queue']` 하나를 공유하며 `JobStatusLink`만 완료 시점 기준 10초 poll을 소유하고, remount·오류·paused 중 timer 폭주를 막는다. 모든 작업 mutation은 즉시 invalidate하고 active 소멸 시 이력·facet을 갱신하며 facet은 10분 safety poll+수동 갱신을 둔다. `/runs`의 `terminal`·`attention`·서버 소유 `user_jobs_only` cursor 이력은 queue 부분 장애와 81건 이상 attention에서도 독립 조회·append된다. backend·UX·계약 세 렌즈를 3회 이상 적대 검토해 최종 P0/P1/P2 0건을 확인했고, 최신 T-164/Alembic 0020 위 n150에서 관련 backend 125건·변경 파일 Ruff, frontend lint·type-check·Vitest 106건·build, Playwright 14건 통과(live 4건 skip)를 검증했다. backend 전체 기준선은 474건 통과, 기존 category 기대 1건과 T-164의 선택 provider 미설치 가정이 n150 설치 환경과 다른 2건만 실패했다. (2026-07-13, PR-06 개정판)
- [x] **T-182**: 검수 목록 payload 확장 — 후보→영상→정규 채널을 상시 outer join하고 목록에 `video_title`, `channel_title`, 유효한 `confidence_score`, `source_kind`, `created_at`, 파생 `queue_reason`만 추가했다. 긴 evidence·원문은 상세에 유지한다. 사유는 mismatch·reconcile conflict/저신뢰/불확실·geocoding·foreign·description/visual·provider 누락·추출 대기를 안정 enum과 명시 우선순위로 고정하고, `reason`·`source_kind`를 items/total/newer_than/cursor fingerprint에 동일 적용해 `unmatched-v2`로 전환했다. NaN/Infinity/범위 밖 신뢰도와 손상·객체·거대 JSONB 점수를 fail-safe 처리한다. grounding은 T-165 raw 저장 전 가짜 filter를 만들지 않고 당시 명시 이연했으며 T-183에서 5상태 계약으로 마감했다. UI는 후보명·매칭 신뢰도·사유, 영상 제목·채널·위치, 출처·생성일을 행에서 바로 보여준다. 300건 응답은 n150 fixture에서 기존 필드 환산 64,456 byte→122,656 byte(항목당 약 +194 byte)였고 100KB evidence 비례 증가가 없음을 검증했다. n150에서 PostgreSQL 타깃 8건·변경 파일 Ruff, backend 전체 385건(기존 postprocess category 기대 1건 실패), frontend lint/type-check/전체 Vitest/build, Playwright 9건을 검증하고 3단계 적대 검토 최종 P0/P1 0건을 확인했다. 전체 Ruff의 기존 미사용 import/변수 12건은 이 PR에 섞지 않았다. (2026-07-13, PR-07 개정판)
- [x] **T-183**: 검수 서버 검색·정렬·cursor + URL 상태화 — 후보명·위치 단서 `q` literal 검색,
  strict 국내 여부·사유·출처·상태·Grounding 5상태 filter, oldest/newest snapshot keyset
  (`unmatched-v4`)과 정확한 `total`·`newer_than`을 구현했다. UI는 oldest FIFO 300건 append, URL 단일
  정본, 명시적 page 밖 `?candidate=` 상세, 큐 변경 배너와 filter 밖 맥락을 제공한다. mutation 실패는
  단건 상세를 권위 재조회해 404/이미 처리/여전히 actionable을 구분하고 A→B→A ABA·checkbox/cache
  resurrection·다른 검수자의 선처리 409를 방어한다. 장소 변경은 lifecycle advisory→candidate→place→
  mapping→asset 순서와 후보 `xmin` fencing으로 직렬화하며 `MediaAsset`/RustFS 객체를 보존한다. MCP는
  감사 로그 멱등 전용 column·partial unique index, pending owner/lease 인계·fencing으로 외부 보강 뒤
  최신 결과를 확정하고, auto-match audit은 `pending` 단일 전이와 후보+로그 원자 commit을 보장한다.
  T-170 재배치에서 Alembic을 `0022→0024→0023` 단일 chain으로 합쳤다. 2회 이상 적대 검토 최종
  P0/P1/P2 0건. 최신 T-170 위 재배치 후 n150에서 backend 타깃 273건·변경 Python 31개 Ruff·
  Alembic `head→0024→0022→head` 왕복,
  frontend lint/type-check/Vitest 159건/build, Playwright 22건 통과(live 4건 skip)를 검증했다. backend
  전체는 664건 통과, n150 optional transcript library 설치 상태와 가정이 다른 기존 2건만 실패했다.
  (2026-07-13, PR-08 개정판, G5)

- [x] **T-188**: `/destinations` SQL 푸시다운 (S5, G8) — 목록 `list_place_summaries`가 확정 장소·mention을
  Python으로 전량 로드·집계·정렬 후 자르던 것을 **SQL 푸시다운**으로 O(전체)→O(limit)로 바꿨다. 필터
  (category/q/district)를 WHERE(ILIKE·strpos·regexp)로, `mention_count`/`source_channel_count`를 group-by
  집계 서브쿼리로, 정렬 4종(mention_count/latest/name/category)·LIMIT을 SQL로(문자열은 `COLLATE "C"`로
  Python 코드포인트순 일치), `_list_mentions_by_place`를 **정렬·LIMIT 후 페이지 대상 place만 IN 단일 쿼리**로
  이동(핵심 이득·N+1 아님). `list_place_summaries_page`(cursor·watermark·total·newer_than·keyset)도 SQL화,
  cursor scope `destinations-python-v1`→`destinations-sql-v2`(구 cursor 배포 경계 1회 400, T-178 in-memory
  토큰이라 격리). 시그니처 호환(`limit: int|None=100`·`limit=None` theme_service 2곳·place_ids·video_id 불변).
  **EXPLAIN(ANALYZE,BUFFERS)**(시드 장소 3천·mapping 34,867): 기본 latest 페이지 = PK 인덱스 backward scan
  101행 0.085ms, 페이지 mentions 전송 34,867→1,107(~31×↓), 장소 hydration 3,000→101(~30×↓). migration 없음
  (인덱스 불필요·단일 head 유지). source_videos 목록 배열 제거는 **보류**(backend 이미 O(limit)·상세는 서빙=
  선배포 조건 충족, frontend 제거는 거의 모든 미머지 codex 브랜치와 경합해 follow-up). 2렌즈 적대적 리뷰:
  **확정 BLOCKER/MAJOR 0**(golden SQL-vs-Python 동치 — COLLATE·keyset·집계·watermark·limit=None 전부 검증).
  known-MINOR(한국어/ASCII 도메인 무해·문서화): district regexp가 비-ASCII 공백(NBSP)에서 `str.split()`과
  갈릴 수 있음(지오코더 정규화 주소라 저확률), `lower()` 비-ASCII 케이스폴딩 로케일 차이, mention_count 정렬은
  전량 GroupAggregate(수용 트레이드오프·전송은 101행). 검증: 격리 DB backend 전체 pytest 737 passed(실패 0),
  golden 매트릭스(정렬4×필터16×limit) 통과. (2026-07-14, 로드맵 PR-20 개정·S5·G8)
- [x] **T-185**: 검수 bulk — 로그인 BFF 전용 `preview`·`execute` 계약과 durable operation/item/receipt
  ledger를 추가했다. 명시 선택은 최대 500건, filter snapshot은 정확한 최대 10,000건이며 10,001번째를
  확인하면 일부를 자르지 않고 413으로 거부한다. preview는 `REPEATABLE READ`에서 revision·상태를
  고정하고 5분 확인 token은 actor·action·scope·만료에 결합해 digest만 저장한다. execute는 100건
  chunk, operation/cursor 잠금, `(request_id,cursor)` exact receipt 재생, stale cursor 409, item savepoint,
  candidate별 감사와 chunk 감사·receipt 원자 commit을 적용했다. ignore/delete/reopen은 기존 lifecycle·
  export dirty 계약을 재사용하며 상태 충돌과 처리 실패를 분리한다. UI는 선택 제외·삭제·복구, 현재
  filter의 해외 후보 전체 제외, 정확한 건수 확인, 진행률, 응답 유실 동일 chunk 재시도, 실패 ID만 새
  preview, 500건 상한, 0건·모바일·focus 안전 경로를 제공하고 bearer token은 메모리에만 둔다. 3개
  적대적 검토 agent를 3회 교차 배치해 cache-key ABA, 후보 감사 누락, 잘못된 200 응답 신뢰, 문서 계약
  불일치, lock 역순과 실제 10,000/10,001 경계 증거 공백을 수정했다. action별 filter 상태 type 계약,
  source filter mock, delete 정산과 혼합 savepoint 회귀도 보강하고 delta 재감사에서
  BLOCKER/MAJOR/MINOR 0건을 확인했다. n150 격리 환경에서 Alembic 단일 head
  `20260713_0027↔20260714_0028` 왕복, T-185 backend 30건·backend 전체 761건·변경 Python Ruff,
  frontend lint·type-check·Vitest 229건·production build, Playwright 기능 44건과 기존 timing 경로
  production 재검증 3/3 통과(4건 live 전용 skip)를 확인했다.
  (2026-07-14, PR-10 개정판, ADR-42, G1)
- [x] **T-171**: export durable dirty outbox (S6/A2) — feature export GET이 매 요청 전 후보
  `sync_feature_exports`(O(후보수)) + `_read_page` `last_exported_at` write-commit 하던 것을 **DB durable
  dirty outbox**로 대체(PR-22 개정: process-local 스로틀·워터마크·플래그는 2프로세스·재시작 정본 불가).
  `export_dirty_outbox`(candidate_id BIGINT PK·reason·marked_at, FK ondelete CASCADE, migration 0025 →
  T-183 위 rebase로 down_revision 0023). `mark_candidates_dirty`(변경과 같은 트랜잭션 on_conflict upsert)를
  resolve/reject/reopen·soft_delete(tombstone)·apply_geocode(자동확정)·merge·correct·batch 신규 후보·
  delete_place·exclude_video에 배선. `sync_dirty`가 outbox를 `DELETE...RETURNING`으로 원자 claim→그 후보만
  `_sync_scope`(전량과 동일 분류·upsert·tombstone 공유, golden)→consume. GET은 sync_dirty(빈 outbox면 쓰기
  0, 순수 읽기), 안전망은 process 시작 1회 + scheduler 시간당 전량 reconcile(`FEATURE_EXPORT_RECONCILE_*`).
  응답 스키마·cursor·operation 계약 불변. 2렌즈 적대적 리뷰: **확정 결함 1클래스(3지점) 수정** — place의
  payload 필드(description·주소·category 등)를 바꾸는 mutation이 **그 place에 이미 매칭된 co-후보**를 dirty
  로 표시 안 해 golden 불변식(dirty==full sync) 위반·안전망 전까지 stale → 공용 헬퍼
  `mark_place_candidates_dirty(place_id)`(그 place 매칭 후보 전부)를 merge_places(target backfill)·geocode
  재사용·resolve 재사용에 적용(correct_place 패턴 일원화, 실제 필드 변경 시만). golden 테스트 2건 추가.
  리뷰의 나머지 probe(consume 원자성·FK cascade·트랜잭션 순서·GET 순수읽기)는 결함 없음. 검증: 격리 DB
  backend 전체 pytest 675 passed(실패 0 — T-183가 기존 pre-existing 수정), migration round-trip 단일 head
  0025. **rebase 코디네이션**: 착수 중 origin/main이 T-183(#196)로 전진해 0023(down 0024)이 head가 됨 →
  T-183 위 rebase(무텍스트충돌 auto-merge, 함수 단위 검증)·migration 0025 down_revision 0023 reparent.
  (2026-07-14, 로드맵 PR-22 개정·S6/A2·G1)
- [x] **T-184**: undo/reopen UI + 제외 목록 — IGNORED와 soft delete를 합친 `removed` 서버 목록과
  복구 전용 UI, 마지막 단건 무기한 snackbar, 모바일 상세 handoff를 구현했다. IGNORED·삭제·MATCHED·
  USER_CORRECTED를 opaque descriptor로 `needs_review`에 복귀시키고, candidate/place DB trigger revision과
  final candidate/place snapshot에 결합한 필수 `client_operation_id`로 stale·ABA·응답 유실 뒤 타 검수자
  결과 오인을 차단했다. 장소에는
  `candidate_created|persistent|legacy_unknown` origin을 도입해 전역 활성 후보·mapping 참조가 모두 0인
  후보 생성 장소만 정리하며 공유·persistent·legacy 장소와 `MediaAsset` 행·RustFS 객체를 보존한다.
  reopen 후 영상 제외는 독립 유지하고, lifecycle→export→candidate→place→mapping→asset 잠금과 감사·
  tombstone 단일 transaction을 적용했다. removed 화면은 외부 장소 검색·AI 의견·VWorld 호출을 하지
  않는다. T-171 rebase 뒤 모든 공유 payload writer를 다시 감사해 주소 역보강·채널/재생목록/영상 metadata·
  영상 summary/reconcile·deep research·요약 적용을 export lock+dirty golden 계약에 편입했다. 영상 분석은
  parent retry generation+claim token fence, stale bounded retry, 중복 first-wins, 사람 review/audit 우선권을
  적용하고 별도 migration 0027로 소유권 컬럼을 추가했다. backend/UX/동시성/E2E 렌즈로 4회 이상 적대
  검토했다. n150에서 migration round-trip, backend 731 passed, 변경 Python Ruff, frontend lint·type-check·
  Vitest 191 passed·build, Playwright 31 passed(4 live 전용 skipped, 실패·재시도 0)를 통과했다.
  (2026-07-13, PR-09 개정판, ADR-40·41, G1)
- [x] **T-170**: 지오코딩 provider별 캐시 (S7) — 반복 장소 provider 재호출을 DB 캐시로 감소.
  **provider-policy allowlist 준수가 핵심**: `PROVIDER_CACHE_POLICY`(감사가능 dict, `{cacheable,
  positive/negative TTL, allowed_fields}`)로 **Kakao만 캐시**(UX cache 허용+최신 유지 의무, positive
  14일/negative 1일), **VWorld·Naver(NCP)·Naver Local Search·Google Places는 deny-by-default**(약관상
  DB 저장 금지 + 사용자 결정 NCP 제외 — 캐시 코드 미개입). `geocode_cache`(query_hash PK·provider·
  response_class·results_json JSONB·created_at, migration 0024, down_revision 0022). canonical key
  `sha256(provider|endpoint|canonical_params|NORMALIZATION_VERSION)`(공통 60일 TTL 철회). 응답 4분류
  (success_nonempty|success_empty|transient_error|permanent_error) — **error를 빈 성공으로 캐시 안 함**,
  positive/negative TTL 분리. lazy 만료(스케줄러 없음 — 로드맵 명시), 캐시 히트도 evidence JSONB 동일
  형식(계약 불변), force_refresh 훅. Kakao `search_address`/`search_keyword` HTTP 호출을
  `run_with_geocode_cache`로 감쌈(별도 세션 팩토리, on_conflict_do_update 멱등). 2렌즈 적대적 리뷰:
  **확정 MAJOR 2**. ① **캐시 best-effort화**(수정): store/lookup 예외가 이미 fetch된 후보를 폐기·전파
  → 상위 광역 `except`가 삼켜 matched(1.0)를 needs_review 'no_result'로 강등 → lookup/store를
  try/except로 감싸 로그 후 진행(결과 불변). ② **migration fork**(당시 미수정·후속 해소): T-183의
  0023이 0022에서 갈라지면 multiple heads가 되므로, T-183 최종 rebase에서 0023을 0024 뒤로
  재부모화해 `0022→0024→0023` 단일 chain으로 합쳤다. MINOR
  (미수정): 캐시 무한 성장은 로드맵 설계(lazy만), 14일 stale은 보수 트레이드오프(<30일). **VWorld 캐시
  정책 긴장**: 약관 전문 미확보로 보수적 제외 — 전문 확보 시 정책 dict 한 줄로 재검토 가능. 검증: 격리
  DB backend 전체 pytest 596 passed(pre-existing 1건 외 0), 캐시 테스트 24 passed, migration round-trip
  단일 head. (2026-07-13, 로드맵 PR-21 개정·S7, docs/provider-policy.md)
- [x] **T-169**: whisper 수동 재전사 액션 — 자막 최종 실패 영상을 운영자가 명시적으로 whisper 재전사
  (선별 실행, 기본화 아님, §2.2 ③). **사용자 결정(2026-07-13)**: prod 자동 전사(`TRANSCRIPT_WHISPER_
  ENABLED`)는 현행 ON 유지 — auto 동작·기본값 불변, **수동 force·model 인자·상한만** 구현. `transcript.py`
  `transcribe_via_whisper`에 `force`/`model_size`(keyword-only): `force=True`면 env 게이트 우회(auto 경로는
  `if not force and env` 프리픽스로 byte-for-byte 불변), model 인자 미지정 시 env `WHISPER_MODEL_SIZE`
  기본. 체인 빌더 `whisper_forced_chain(model_size)` + `postprocess_service._whisper_forced_transcript_
  fetcher` 신설, `worker.poi_batch_handler`가 payload `force_whisper`/`whisper_model`을 읽어 주입(없으면
  `_default_transcript_fetcher` 불변). API는 기존 `/destinations/reprocess` 재사용 — `ReprocessRequest`에
  additive `force_whisper`/`whisper_model`, force 시 **batch lane**(interactive 아님)·model `small` 기본
  (`WHISPER_MANUAL_MODEL_SIZE`)·**duration cap**(`TRANSCRIPT_WHISPER_FORCE_MAX_DURATION_SECONDS=1200`).
  스키마 변경 없음(payload 파라미터). 2렌즈 적대적 리뷰: 확정 BLOCKER/MAJOR 0. 렌즈 이견 1건 **병합 전
  보강** — duration cap이 `duration_seconds` NULL/0/음수를 통과시켜 라이브 아카이브(무한 whisper·비취소
  `to_thread`)가 batch 단일 레인을 무한 점유(T-121-E 재발) → **known positive duration ≤ cap만 통과,
  NULL/비양수는 400**. 알려진 MINOR(문서화·미수정): 요청당 whisper 건수 상한 부재(기존 reprocess `[:200]`
  공통), 검수자/운영자 역할 분리 없음(기존 admin-proxy 신뢰 모델). **프런트 "whisper로 재전사" 버튼은
  Agent B 후속**(API: `POST /api/v1/destinations/reprocess {video_ids, force_whisper, whisper_model?}`).
  검증: 격리 DB backend 전체 pytest 571 passed(pre-existing 1건 외 0), whisper-force 테스트 10 passed,
  migration 불필요, routes.py 변경은 additive(Agent B 미머지 브랜치 15개와 reprocess 영역 미충돌 확인).
  (2026-07-13, 로드맵 PR-18 개정·§10 B3·§2.2 ③)
- [x] **T-168**: description 단독 후보 경로 — 자막 전 provider 최종 실패(T-164 판정) 시 영상을
  폐기하던 것을 막고(§1.3 D1 수율), 저장된 영상 설명(제목·태그 포함)이 `DESCRIPTION_POI_MIN_LENGTH`
  (기본 200자) 이상이면 그 텍스트로 **검수 전용** 후보를 추출한다(`source_kind='description'`).
  **자동확정 절대 금지**: `apply_geocode_to_candidate` 초입에서 description 후보는 게이트 통과 무관
  needs_review·`feature_export_status=PENDING`·장소 미생성(return None) → snapshot/changes에서 자연
  제외. grounding은 raw description 대조로 관측만(자동확정 미사용). recall은 `source_kind` 태깅으로
  audit 분리 측정(후보 수 증가를 신뢰성 향상으로 계상 안 함). 스키마 변경 없음(기존
  `EvidenceSourceKind.DESCRIPTION`·`QueueReason.DESCRIPTION_ONLY` 재사용). 2렌즈 적대적 리뷰:
  **MAJOR 1 확정 수정** — 재처리 시 dedup이 `(video_id, 정규화 이름)`만 키로 써 저품질 description
  후보가 나중 온 고품질 transcript 후보를 영구 차단(자막 우선순위 역전) → **source_kind 우선순위
  비대칭 dedup**(transcript>description): 같은/상위 소스 존재 시 새 후보 억제, 미검수 하위(description)
  후보만 있으면 T-160 soft delete로 supersede 후 상위 후보 생성, 사람이 손댄 후보는 보존.
  MINOR: 200자 게이트 트레이드오프 주석, description 후보 `is_domestic` None→`review_note=
  domestic_unverified`로 FOREIGN 버킷 보존(T-166 fail-closed 대칭), 회귀 테스트 5건(supersede 재현·
  역방향 억제·export 제외·domestic 버킷·`_build_description_text` 경계). 검증: 격리 DB backend 전체
  pytest 561 passed(pre-existing 1건 외 0), 신규 10 passed, migration 불필요. (2026-07-13, 로드맵
  PR-17 개정·§10 B3·§1.3 D1)
- [x] **T-167**: 병합 제안 + auto-match audit — 신뢰성 코어 마지막 조각(§10 D6·G9). 공용
  `place_name.py`(정규화·pairwise `names_match` 단일 출처)로 자동확정 게이트·배치 dedup·병합 제안이
  같은 규칙 공유, 배치 dedup을 `(video_id, 정규화 이름)`으로 완화("성심당/성심당 본점" 통합, D6).
  병합 "제안"만(자동 병합 금지) `GET /destinations/{id}/merge-suggestions`, 근접 재사용 반경
  100→300m(이름 게이트 통과 전제). **auto-match audit 표본**(migration 0022, AUTO_MATCH_AUDIT_
  SAMPLE_RATE·결정적 후보 id 해시 선택, 오확정률 집계 — MATCHED·export 상태는 불변, 사후 관측
  전용) → T-166 정밀도 트레이드오프를 실측 가능하게(G9). 2렌즈 적대적 리뷰: BLOCKER/MAJOR 0, MINOR
  다수(정밀도 정정: **`N호점` 정규화 제외** — "롯데리아 1호점/2호점"이 뭉개지는 것 방지, ADR-39로
  PR-14 편차 기록; audit reviewed_by를 검증 proxy actor로; 결정적 표본; 병합 스캔 limit) 반영.
  pg_trgm·자동 병합·광범위 …점 제거는 금지 준수. 검증: 격리 DB backend pytest pre-existing 1건 외 0,
  alembic 0022 round-trip. (2026-07-13, 로드맵 PR-14 개정·§10 D6·G9, ADR-39)
- [x] **T-166**: 자동확정 identity gate — T-165 grounding과 함께 자동확정 조건을 완성했다(§10 B3, G4).
  지오코딩 결과를 `result_kind`(poi|address|coordinate)로 구분(`GeocodeResultKind`), any-pair
  `_names_compatible`를 pairwise `_names_match`로 분리해 신규 장소 경로에 이름 게이트 강제(D2/C8 해소),
  행정구역 게이트(`region_gate.py` — 17개 시도 명시 alias, 최장 surface 우선 매칭, 역지오코딩 추가
  호출 없음, D4 해소), `is_domestic` None/False fail-closed(D7), 게이트 통과 후보 정확히 1개면
  ambiguous 자동확정(ADR-38로 ADR-16 경계 좁힘). **자동확정 = grounding + 이름 + 행정구역 + is_domestic
  네 불리언 게이트 AND** — 가중 합성 점수 미도입(§2.4-4). 2렌즈 적대적 리뷰: **MAJOR 2**(① VWorld
  주경로의 address kind가 이름 무검증 자동확정 → G4 위반 → **address/coordinate 신규 장소는 identity
  검증 불가로 needs_review 격상**; ② ambiguous 경로가 unrefined 좌표 echo 재승격 → 단건 가드와 대칭
  차단)·MINOR 반영. 검증: 격리 DB backend pytest pre-existing 1건 외 0, 타깃 73 passed. **동작 변화**:
  VWorld address 결과 신규 장소가 needs_review로 가 검수 큐가 늘 수 있음(의도된 정밀도 우선, 근본
  수리=POI 검색 경로 우선순위화는 백로그, 자동확정률은 T-169 실측). (2026-07-13, 로드맵 PR-12 개정·§10 B3·G4·§1.3 D2/D4, ADR-38)
- [x] **T-165**: raw grounding 게이트 — 원 PR-13이 교정본(생성 모델 산출물)을 검사하던 것을 T-164가
  보존한 **raw 자막 segment** 대조로 격상했다(§10 B3). batch POI 스키마에 `evidence_quote`·`confidence`
  추가, `grounding.py`가 quote를 raw(교정 이전)와 대조해 `grounding_status` enum(verified_raw|unverified|
  missing|not_applicable|legacy_unknown, migration 0021)으로 저장. **transcript 후보는 verified_raw
  아니면 자동확정 차단**(geocode MATCHED 직전 게이트)·export 제외(feature_export _classify)·queue_reason
  `ungrounded`. LLM 자가 confidence는 기록만(§2.4-3 가짜 정밀도 방지). 2렌즈 적대적 리뷰: **MAJOR 3**
  (①기존 export된 legacy 후보의 대량 tombstone 회수 → legacy는 재처리 전까지 노출 유지, ②queue_reason
  UNGROUNDED가 기존 사유 마스킹 → legacy 제외, ③교정본 띄어쓰기 교정으로 정상 POI 오차단 → CJK 공백
  정규화)·MINOR 4 반영, legacy UPSERT 유지 신규 테스트 포함. 게이트 3개가 "legacy는 기존 상태 유지,
  새 확정만 verified 요구"로 일관. 검증: 격리 DB backend pytest 505 passed(pre-existing 1건 외 0),
  alembic round-trip. raw-vs-corrected 잔여 오차단율은 T-169 baseline live yield로 실측 후 재검토.
  (2026-07-13, 로드맵 PR-13 개정·§10 B3·G4·§1.3 D3)
- [x] **T-164**: transcript_attempts 관측 — 자막 3 provider가 `except Exception: return None`으로
  실패 원인을 소실하던 문제(§1.3 D1)를 해소했다. `transcript_attempts` durable 테이블(provider별
  시도·outcome 코드 8종(no_captions/blocked/rate_limited/download_error/parse_error/disabled/
  not_configured/success)·language·duration·tool_version, 성공 전 실패도 전부 보존, migration 0020),
  `fetch_transcript`가 `TranscriptResult`를 wrap한 `TranscriptOutcome` 반환(segments·timestamp 무손상),
  예외 유형별 outcome 분류(`_classify_exception`), `TRANSCRIPT_PROVIDER_ORDER` 실제 체인 연결(사문화
  해소), yt-dlp 실제 언어 기록·절단 로그(D7), `youtube_videos.transcript_source/failure_code` 요약
  캐시(T-169 선별 원천, 우선순위 기반 대표 코드). 2렌즈 적대적 리뷰: MAJOR 1(yt-dlp `ignoreerrors=True`가
  차단·429를 no_captions로 오분류 → `ignoreerrors=False` + error collector 이중 방어로 수정, D1 회복)·
  MINOR 4(빈 segment 단락·provider 라벨 canonical 통일·캐시 자막 요약 갱신·테스트 우선순위 케이스)
  반영. 검증: 격리 DB backend pytest 466 passed(pre-existing 1건 외 0), alembic round-trip.
  (2026-07-13, 로드맵 PR-11 개정·§10 B3/G7·§1.3 D1)
- [x] **T-163**: 워커 레인 분리 — 긴 배치 작업이 사용자 트리거 작업을 막던 단일 큐(§1.2 S1)를
  해소했다. `crawl_runs.lane`(interactive|batch, CHECK+`(lane,state,id)` 인덱스, migration 0019),
  enqueue 지점 기준 lane 매핑 12곳(재처리·deep research·수동 transcript=interactive / 수집·source_scan·
  poi_batch child·run-now·MCP harvest=batch / restart=원본 lane 복사 — G6), `claim_next_pending(lane)`
  격리(`FOR UPDATE SKIP LOCKED`), 스케줄러 레인당 interval job 1개씩 2개(`-interactive`/`-batch`,
  각 max_instances=1) + 구 `crawl-run-worker` job 제거. stale 재투입은 lane 무관·원 lane 보존.
  2렌즈 적대적 리뷰: BLOCKER/MAJOR 0, MINOR(requeue_stale skip_locked 하드닝·child payload
  source_job_id lineage·문서 3종 갱신) 반영. 핵심 목적(긴 배치 중 interactive 즉시 claim) 테스트
  검증. 검증: 격리 DB backend pytest 421 passed(pre-existing 1건 외 0), alembic round-trip 단일 head.
  (2026-07-13, 로드맵 PR-04 개정·§10 B6)
- [x] **T-162**: durable stage events + restart lineage·attention — `status_log_json`(4필드·80건 절단,
  UI 계약) 불변 유지하면서 `crawl_run_stage_events`(stage/provider/attempt/elapsed_ms/outcome, monotonic
  실측) 별도 durable 기록을 신설했다. poi_batch 4단계(transcript_fetch/correction/poi_extract/geocode)
  + 배치 총소요(`poi_batch_total`) 경계, harvest 2단계 계측(§7 지표·T-172 게이트 원천). `crawl_runs`에
  `restart_of_run_id`(self FK, 재시작 lineage·FOR UPDATE 멱등 — 원본당 active 1)와 `attention`
  (open|acknowledged|superseded|resolved, CHECK+partial index, 전이는 crawl_run_service 단독 소유),
  `POST /runs/{id}/acknowledge` API, run 목록/상세 응답에 additive 노출(#185 envelope와 결합).
  migration 20260713_0018. stage_reporter 주입으로 ETL의 crawl_run 비의존 유지. 2렌즈 적대적 리뷰:
  BLOCKER/MAJOR 0, MINOR(G7 역할 표기·T-172 분모 경계 이벤트) 반영. 검증: 격리 DB backend pytest
  405 passed(pre-existing 1건만 실패 — 나머지는 공유 DB flake 확정), alembic round-trip, envelope 회귀
  어서션. G7 provider별 관측은 T-164 소관으로 명시. (2026-07-13, 로드맵 PR-34·§10 B6, G6·G7 데이터)
- [x] **T-161**: LLM async/multimodal 게이트웨이 — 모든 LLM 호출을 `llm_client` 단일 계약으로 수렴
  (`generate/complete_json/complete_text/generate_multimodal` + `LlmResult` usage 실측). quota 예약
  우회 6곳(deep research·키워드 확장·검수 의견·카테고리·POI 추출·video_analysis 직접 호출)을 전부
  게이트웨이 경유로 이관(§10 B6/C6 해소)하고, 동기 SDK 호출은 게이트웨이 내 `to_thread`로 격리
  (T-101/105/111/121-E 계열 근절). direct SDK guard 테스트(genai·post_generate_content·acquire·
  DeepSeek 헬퍼·openai import, backend/ktc+scheduler+mcp+etl 스캔). 적대적 리뷰 3렌즈: BLOCKER 0,
  MAJOR 2(대화형 의견 경로의 리미터 대기 → `GeminiQuotaBusy`+`quota_max_wait=0` 무대기 옵션과 정확한
  메시지, guard DeepSeek/openai 미검출) ·MINOR 7 전부 머지 전 반영. 기존 semantics(교정 240s·batch
  재시도·폴백·12s 상한) 함수 단위 보존 확인. PR-05 통합: `.env.example` GEMINI_RATE_* 예시 표기+TPM
  하한 주석, `docs/dev-environment.md` §12 티어 반영 절차, `llm_usage` 실측 로그. 검증: backend 전체
  pytest 336 passed(pre-existing 2건 외 0, 격리 disposable DB). (2026-07-13, 로드맵 PR-23+PR-05, §10 B6)
- [x] **T-160**: candidate soft delete 상태 모델 — hard delete가 export tombstone·undo를 원천
  차단하던 구조(§10 B1, FK NO ACTION + ledger 선삭제)를 해소했다. `deleted_at/deletion_reason/
  deleted_by` 컬럼+CHECK+검수 큐 partial index 3종(migration 20260713_0017, T-175 0016 이후), `soft_delete_candidates`
  helper(매핑 삭제·matched 해제·**같은 트랜잭션 tombstone 전이**, ledger DELETE 전소멸, FOR UPDATE
  락), 후보 삭제 라우트·`exclude_video`(force) 교체, 활성 조회 `deleted_at IS NULL` 전수 적용,
  `POST /destinations/unmatched/{id}/reopen`(deleted/ignored→NEEDS_REVIEW, MATCHED/USER_CORRECTED는
  T-184 이연 400), sync의 tombstone freeze(재발행 소음 제거). G1 통합 테스트(export→삭제→tombstone→
  재시작 등가→reopen→재발행→cursor 단조) 포함. 적대적 리뷰 3렌즈: BLOCKER 0, MAJOR 2·MINOR 6 전부
  머지 전 반영. 검증: alembic up/down round-trip, backend 전체 pytest pre-existing 2건 외 실패 0.
  (2026-07-13, 로드맵 §10 B1·PR-09 백엔드, G1)
- [x] **T-158**: Phase -1 외부 provider 정책·데이터 권리 게이트 — `docs/provider-policy.md` 신설:
  provider 6열(YouTube/Google Places/NCP Maps/Naver Local Search/Kakao/VWorld)×8열 정책 matrix(전부
  공식 원문 확인·확인일 기재), 현행 코드 충돌 지점 C-1~C-7, ADR-15 재검토 초안(옵션 4), release
  gate 선언, dev RustFS·env 플래그 인벤토리(비밀 미기록), prod 확인 필요 표. kill switch 2종
  (`RAW_MEDIA_STORE_ENABLED`·`GOOGLE_PLACE_SEARCH_ENABLED`, 기본 true=현행 유지 — 사용자 승인) 배선
  +테스트 4건. 적대적 리뷰 3렌즈(정책 원문 대조·비밀 스캔·명세 완결성)로 BLOCKER 1(prod IP 기록)·
  MAJOR 5·MINOR 6을 머지 전 수정. 사용자 결정 3건 반영: Google 표시 현행 유지(의도적), prod whisper
  현행 유지(자막 품질 개선은 T-193 분리), NCP Maps는 캐시·저장 제외(T-170). (2026-07-13, 로드맵
  PR-29·G10)
- [x] **T-159**: `exclude_video` 컬럼 버그 hotfix — 고아 장소 판정 루프의 존재하지 않는
  `ExtractedPlaceCandidate.place_id` 참조를 `matched_place_id`로 수정(1줄). 수정 전 코드에서
  AttributeError 재현을 실제 확인한 회귀 테스트(고아 장소 삭제, 타 영상 매핑·matched 후보 참조
  장소 보존)를 추가했다. 검증: backend compileall, `test_place_service.py` 11 passed, backend 전체
  pytest 302 passed(실패 2건 — `test_destinations_reflect_db`,
  `test_process_harvest_videos_creates_place_from_summarized_poi` — 은 pristine HEAD에서도 동일
  실패하는 기존 결함으로 확인, 별도 조사 필요), `git diff --check`. (2026-07-13, 로드맵 PR-30)
- [x] **T-157 후속(반영)**: Codex 리뷰 검증·본문 통합·작업 등재 — §10의 사실 주장 22건을 3개 검증
  에이전트가 코드 대조로 전부 확인(CONFIRMED, 이견 없음)하고, B1~B7·PR별 수정 의견·10단계
  순서·acceptance gate(G1~G10)를 로드맵 본문 §0~§9에 통합했다(각 PR "개정(2026-07-13)" 항목,
  신규 PR-29~34, §1.5 추가 문제 C1~C10, §2.4 반영 판단, §4 Agent A/B 트랙). 대기 작업
  T-158~T-192를 Agent A(백엔드 상태 모델·파이프라인·정책 16건)/Agent B(검수 UX·공급 API·보안
  표면 19건) 트랙으로 등재했다. (2026-07-13)
- [x] **T-157**: 개선 로드맵 문서 작성(적대적 검토 기반) — 서브시스템 이해 분석 4건 → 적대적 검토
  3건(사용 편의성 / 속도 / 데이터 신뢰성+외부 API 실용성) → 검토별 사실·가치 교차 검증 6건 →
  최종 판단 → 문서 자체 반복 리뷰 2회(비평 6건)를 거쳐 `docs/improvement-roadmap-2026-07.md`를
  작성했다. 산출물은 7 Phase / 28 PR(+PR-20a) 실행 계획으로, 각 PR에 변경 파일·작업 절차·검증
  방법·완료 기준을 명시하고 측정 게이트(PR-16/19/24), 채택·수정·기각 판단과 사유, 측정 지표,
  백로그를 단일 문서로 통합했다. 리뷰에서 나온 BLOCKER 2건(존재하지 않는 `updated_at` 컬럼 전제,
  PR-24 게이트용 단계별 로그 누락)과 MAJOR 다수를 반영했다. 사용자 리뷰 후 tasks/ADR 반영
  예정(문서 §9). 후속 Codex 검토에서는 독립 적대적 검토 3건과 2회차 교차 검증을 거쳐
  삭제/undo/tombstone 상태 모델, 검수 provenance, raw grounding gate, 외부 정책, API key rollout,
  LLM/lane 순서, pagination 계약의 BLOCKER 7건을 확정하고 같은 문서 §10에 상세 리뷰를 덧붙였다.
  최종 판정은 “방향 승인 / 실행계획 수정 요구”이며 사용자 리뷰 전 T-158 이후 항목은 등록하지 않는다.
  (2026-07-12)
- [x] **T-156**: 검수 큐 행 전체 클릭 선택 보강 — n150 계측에서 후보명/위치 힌트 텍스트 위는 선택되지만
  같은 행의 여백, 출처 칸 오른쪽, 상태 칸은 선택되지 않는 것을 확인했다. 검수 후보 행 전체를 선택
  표면으로 넓히고, 체크박스·재처리 선택·상세·삭제는 `data-row-action`으로 분리해 기존 액션을 유지했다.
  키보드 Enter/Space 선택도 추가했다. 검증: frontend lint, type-check, build, vitest 29 passed,
  `git diff --check` 통과. (2026-07-12)
- [x] **T-155**: 검수 큐 후보 클릭 응답성 개선 — 검수 페이지에서 위치/출처 칸 클릭이 후보 선택이
  아니라 재처리 장바구니 토글로 동작해 사용자 기대와 어긋나고, 자동 장소 검색이 후보 선택과 같은
  이벤트에서 바로 시작되어 클릭 반응이 늦게 보이던 문제를 개선했다. 위치/출처 텍스트 클릭도 후보
  선택으로 통일하고, 재처리 선택은 별도 작은 버튼으로 분리했다. 후보 선택 시 진행 중 검색 취소와
  새 자동 검색을 모두 120ms 뒤로 미뤄 선택 표시와 확정 정보 폼 초기화가 먼저 렌더링되도록 했다.
  검증: frontend lint, type-check, build, vitest 29 passed, `git diff --check` 통과. (2026-07-12)
- [x] **T-154**: 검수 큐 첫 진입 성능 개선 + Google Places 403 재진단 — 검수 페이지가 첫 진입부터
  `limit=2000` 전체를 받아 DOM에 올리던 흐름을 최신 300개 초기 조회와 300개 단위 "후보 더 불러오기"로
  바꿨고, 자동 refetch를 15초에서 60초로 완화했다. 백엔드는 `needs_review` 최신순 조회와 출처 필터에
  맞춰 `extracted_place_candidates(match_status,id)`,
  `extracted_place_candidates(source_channel_id,match_status,id)`,
  `extracted_place_candidates(source_playlist_id,match_status,id)`,
  `youtube_videos(source_search_query)` 인덱스를 추가했다. Google Places 403은 prod에서 env key가 실제로
  사용되는 상태에서도 Google만 `PERMISSION_DENIED`를 반환하고 Kakao/Naver는 정상이라 Cloud Console의
  API 키 application/API restriction 설정 문제로 재확인했다. (2026-07-10)
- [x] **T-152**: 수집 폭 활용 + 검수 payload 경량화 + 테마 POI API + API 테스트 페이지 —
  (a) 수집 상단 밴드 grid 재조정과 폼 2열 배치로 좌측 폼이 폭을 채우게 함. (b)
  `/destinations/unmatched` 응답을 리스트 전용 경량 payload(`_candidate_list_payload`)로 바꿔
  3.8MB→~1.3MB(리스트가 안 쓰는 provider_evidence_json 제외, 파생 카테고리 코드는 서버 계산).
  (c) 테마 중심 POI 공급 API 3종(`/themes`, `/themes/places`, `/themes/video/{id}/places` — 동영상
  테마는 매치/검수완료 POI ≥5일 때만 공개) + `theme_service` + 테스트(ADR-35). (d) 관리 nav `API`와
  `/api-test` 페이지로 외부 공급 API를 파라미터 넣어 호출·검사. 부수로 stale해진
  `test_list_place_summaries_sorts_by_mention_count`(고유 영상 수 semantics 미반영)를 바로잡음.
  (2026-07-05, ADR-35)
- [x] **T-150**: 유지보수 UI/UX 개편 — `@base-ui/react` 기반 shadcn 프리미티브 확장
  (checkbox/switch/textarea/popover/alert-dialog), `window.confirm`·raw input 전면 교체와
  파괴적 액션 확인 다이얼로그 통일(`ConfirmActionButton`), 중복 대시보드 조각 공용화
  (`components/panels.tsx`·`detail.tsx`·`CopyButton`·`lib/format.ts`), 사장 코드
  (AppNav/SettingsDialog/OpsMetricsDialog) 삭제, 수집 폼 자동 인식 미리보기와 유형별 형식
  검증(`lib/youtube.ts` + vitest), 검수 좌표 검증·설정 프롬프트 글자 수 카운터, 긴 설명의
  `HelpTip`(popover) 이관. 부수로 backend `source_resolve`의 불균형 `[` 입력 500 크래시를
  `_safe_urlparse`로 수정하고 legacy custom URL 채널 판별 패리티를 맞췄다. live E2E 스펙을
  새 확인 흐름에 맞게 갱신하고 로컬 시드 스펙에 live 모드 skip 게이트를 추가했다. (2026-07-04, ADR-34)
- [x] **T-151**: Google Places 403 진단 강화 — 검수 장소 검색의 Google 403 응답 본문(원인 코드)을
  `/place-search` `errors.google`에 노출. prod 진단으로 원인이 API 키 제한임을 확정(코드 정상,
  Cloud Console 키 설정 사안). (2026-07-01)
- [x] **T-149**: 화면 타이틀 섹션 컴팩트화 — `AppShell` 헤더를 얇은 한 줄 바로 축소하고 페이지
  설명 문구·섹션 배지·경로 표시와 반복 부제를 제거(내부 도구 기준). E2E가 검증하는 제목
  heading과 실동작 안내 문구는 유지. (2026-06-29)
- [x] **T-148**: 개발 명령 Linux 전용과 Playwright n150 우선 정책 문서화 — 개발·검증·리포지토리
  작업 명령은 `git`/`gh`/codegraph 계열 분석까지 모두 WSL2(Ubuntu)를 포함한 Linux bash에서
  실행하도록 정리했다. E2E Playwright는 n150 live/Linux 환경에서 우선 실행하고, n150 접근·브라우저·
  환경 제약으로 불가할 때만 Windows 호스트 fallback을 허용한다. `AGENTS.md`, `README.md`, `SKILL.md`,
  `CLAUDE.md`, `docs/dev-environment.md`, `docs/architecture.md`, ADR-33, 작업 일지를 갱신했다.
  (2026-06-28)
- [x] **T-147**: 결과 지도 크기와 장소 클릭 재중심 보정 — 결과 페이지도 데스크톱 viewport lock을
  적용해 지도 영역이 화면 높이에 맞게 안정적으로 잡히도록 했다. MapLibre 지도는 ResizeObserver로
  컨테이너 크기 변화를 감지해 `resize()`를 호출하고, 장소 목록/마커 클릭마다 focus key를 증가시켜
  같은 장소를 다시 눌러도 선택 좌표로 재중심 이동이 실행되게 했다. `/jobs/*` 세부 정보에서는
  중복되는 현재 메시지·오류·결과·최대 영상 수를 제거하고 작업 상세 페이지에서 1열로 정리했다.
  기본 카테고리는 영상 처리 요약 카드 쪽으로 옮겼다.
  (2026-06-28)
- [x] **T-146**: 검수 지도 높이 폭주 수정과 작업 상세·수집 반복 테이블 정리 — 검수 화면의 3분할
  grid에서 가운데 패널이 콘텐츠 높이만큼 grid 전체를 밀어 올려 우측 VWorld 지도 높이가 수만 px로
  계산되던 문제를 데스크톱 `AppShell` viewport lock과 `min-h-0`/`overflow-hidden` 경계로 수정했다.
  검수 후보와 수집 반복 작업은 화면을 꽉 채우되 넘치는 행은 테이블 영역만 스크롤하도록 조정했다.
  작업 상세 페이지는 `/status`와 같은 운영 콘솔 룩앤필의 요약 카드·패널·테이블 구조로 정리하고,
  헤더의 상태 badge를 제거한 뒤 `뒤로`를 outline 버튼으로 바꿨다. 검수 큐 후보 조회 기본 limit은
  500에서 2000으로 올렸고, 수집 화면의 반복 작업 테이블은 전체 폭을 쓰도록 아래 영역으로 분리했다.
  (2026-06-28)
- [x] **T-145**: 공용 메뉴·수집/상태/작업 상세 UI 밀도 정리 — 공용 메뉴의
  `Korea Travel Concierge` 옆에 작업 상태 아이콘과 로그아웃 아이콘을 고정 배치하고, 모바일 좁은 폭에서
  순서가 흔들리지 않도록 브랜드 텍스트만 줄어들게 했다. 수집 페이지는 수집 작업 입력과 반복 작업
  2분할로 줄이고, 실행 큐는 진행 중 1행만 표시하며 전체 이력은 상태 페이지 탭으로 이동했다. 반복 작업
  테이블의 원시 `PL_*`/`UC_*` 값 노출을 줄이고, 실행 상태·검수 후보 상태·카테고리 `unknown` 표시는
  공통 한글 라벨로 통일했다. 상태 페이지는 진행 중/완료 이력 탭과 고정 높이 스크롤 테이블로 수집
  페이지 수준의 작업 상세 정보를 보여주며, 작업 상세 페이지는 중요도 기준 카드 배치로 재정리했다.
  검증: frontend type-check/lint/vitest/build 통과. (2026-06-28)
- [x] **T-144**: 헤더 로그아웃·작업 상태·탭·상태 페이지 정리 — 공통 `AppShell`에서 로그아웃
  버튼을 타이틀이 있는 헤더 라인의 우측 최상단으로 배치하고, 작업 상태 링크는 타이틀 바로 옆의
  작은 pill 형태로 줄였다. 공용 `Tabs` primitive가 실제 `orientation`을 Root에 전달하고
  `data-orientation` 기준 variant를 쓰도록 고쳐 보정 자막, 실행/검수 큐 계열 탭이 좌측이 아니라
  상단에 배치되게 했다. 로그인 기록은 설정에서 상태 페이지로 옮겼고, 상태 페이지는 작업/데이터/보안
  섹션으로 재배치했다. 작업·검수 후보·로그인 결과 등 raw enum은 짧은 한글 라벨로 표시한다. 검증:
  frontend type-check/lint/vitest/build 통과. (2026-06-28)
- [x] **T-143 / PR-F**: 통합 n150 live UI E2E와 최종 배포 — T-138~T-142 기능을
  `tests/e2e/live-shell.spec.ts`의 n150 live spec 4건으로 고정했다. 메뉴/상단 작업 상태/상태/설정,
  수집 반복 작업 테이블과 수정 다이얼로그, 검수 큐 테이블·3분할·상세, 결과 필터와 출처 동영상 상세
  확장을 한 파일에서 검증한다. n150 배포 후 API health 200, UI 인증 환경변수 non-zero, 로그인
  GET 200, 로그인 POST 200 + Set-Cookie 1개, Windows 호스트 Playwright live spec 4건 통과를 확인했다.
  (2026-06-27)
- [x] **T-142 / PR-E**: 카테고리 강제화 + `kor-travel-geo` v2 행정코드 보강 — 수집 작업에 기본
  카테고리를 추가하고 자동 저장·검수 큐 수동 검색 확정·반복 작업 실행 payload에 적용했다. 카테고리
  매칭 실패와 Concierge 카테고리 외 값은 `unknown`/코드 `0`으로 정규화한다. `travel_places`에는
  법정동/시군구 코드·이름과 보강 출처/시각을 추가하고, 자동/수동 매칭 저장 시 `kor-travel-geo`
  v2 reverse API로 채운다. 산·해안처럼 reverse가 일부 코드만 주는 좌표는 v2 `regions/within-radius`
  fallback으로 보완한다. n150 기존 장소 856건을 백필해 누락 0건을 확인했고, 결과 시군구 필터는
  코드 기반 facet을 사용한다. backend 전체 pytest, frontend type-check/lint/vitest/build, n150
  live UI E2E 4건을 통과했다. (2026-06-27)
- [x] **T-141 / PR-D**: 결과 뷰 필터와 출처 동영상 상세 확장 — 결과 탭에 카테고리 필터, 텍스트
  검색, 시군구 필터를 추가했다. 시군구는 T-142 행정코드 보강 전까지 주소 문자열의 앞 두 토큰으로
  보수적으로 구성하고, T-142에서 코드 기반 dropdown으로 대체한다. 장소 상세의 출처 동영상을 클릭하면
  같은 다이얼로그 안에서 동영상 메타데이터, 등장 근거 목록, 보정 자막 원문/정리본 탭, 근거 위치
  이동 버튼을 보여주도록 확장했다. 출처 동영상 제목은 목록과 상세 모두 줄바꿈되게 했다. n150 API/UI
  재빌드와 Windows 호스트 Playwright live spec 4건을 통과했다. (2026-06-27)
- [x] **T-140 / PR-C**: 검수 큐 테이블·3분할 레이아웃·삭제/상세 UX 개선 — 검수대기 후보를
  후보/출처/상태/액션 컬럼의 테이블로 바꾸고 테이블/검수 패널/지도 3분할 레이아웃으로 재구성했다.
  후보 삭제 후 목록 캐시가 남는 문제를 보정하고 다중 선택 `선택 삭제`를 추가했다. "검수 후보 상세"는
  같은 동영상의 다른 장소 링크, 보정 자막 원문/정리본 탭, 근거 시간 스크롤, 긴 출처 제목 줄바꿈을
  제공한다. n150 임시 후보로 상세 API/UI와 선택 삭제를 검증하고 PR #154를 squash merge했다.
  (2026-06-27)
- [x] **T-139 / PR-B**: 수집 실행 큐 테이블화 + 반복 작업 수정 다이얼로그 개선 — 수집 화면의 실행
  큐, 반복 작업, 1회성 작업 목록을 `kor-travel-map` curated features 패턴의 테이블로 변경하고,
  row별 대상/진행/누적/일정/상태/액션 정보를 컬럼으로 분리했다. 반복 작업 수정 다이얼로그는
  원시 ID 대신 `target_label`/`display_name` 기반 제목(`XXX 작업 수정`)을 사용하고, 누적 수집 영상
  수·실행 횟수·마지막 수집일·마지막 영상 날짜·마지막 스캔·다음 실행 요약을 파라미터 위에 배치했다.
  `강제 다운로드 (전체 재수집)`은 저장 직후 한 번만 `run-now?force=true`를 호출하도록 1회성 UI로
  추가했다. n150 API/UI 재빌드와 Windows 호스트 Playwright live spec 2건을 통과하고 PR #153을
  squash merge했다. (2026-06-27)
- [x] **T-138 / PR-A**: `kor-travel-map`형 운영 셸·상태·설정 페이지 분리 — PC 좌측 메뉴와
  모바일 상단 메뉴, 페이지 상부 헤더, 모든 페이지 상단의 간단 작업 상태 링크를 `kor-travel-map`의
  `AdminShell` 레이아웃에 맞춰 이식했다. 수집 페이지에 있던 작업 상태와 우측 상단 "운영" 상세는
  별도 `/status` 페이지로 옮기고, 설정도 메뉴의 별도 `/settings` 페이지로 정리했다. n150 live UI
  E2E로 메뉴 전환·상태 링크·상태 상세·설정 진입을 검증하고 PR #152를 squash merge했다.
  (2026-06-27)
- [x] **T-137**: `kor-travel-map` UI primitive/폰트 정렬 + VWorld 마커 위치 버그 수정 — 전역
  CSS font stack과 `kor-travel-map-admin`의 green/warm-gray token을 적용하고,
  button/input/badge/select/tabs/dialog/label primitive의 font size·weight·height·brand ring을
  참조 UI에 맞췄다. 검수 검색 결과 클릭 후 두 번째 선택부터 지도 마커가 엉뚱한 위치로 보이던
  원인은 `VWorldMap.syncMarkerElement`가 MapLibre marker root의 `transform`을 덮어써 좌표 배치
  transform을 깨던 것이다. root transform은 건드리지 않고 내부 badge만 lift하도록 고쳤고,
  같은 `selectedPlaceId`에서 좌표만 바뀌어도 `easeTo`가 다시 실행되도록 공용 `VWorldMap`을
  보강해 검수 지도와 결과 지도 모두에 반영했다. 검증: frontend type-check/lint/build/vitest(15/15).
  (2026-06-27)
- [~] **T-121**: 수집 입력 자동분류 + 결과 출처별 그룹화 + 자막교정 hung 방지 — A: 링크/검색어를 붙여넣으면 재생목록/유튜버/영상/키워드 자동 판별(`source_resolve.classify_source_input`), `/harvest` auto/video 경로 + 단일영상 harvest(`run_harvest.direct_video_ids`), 프런트 "자동" 기본·"영상" 옵션. B: `/destinations` 출처 필터(channel/playlist/keyword) + `/destinations/facets`, 결과 보기 그룹 셀렉터(유튜버별/재생목록별/검색어별). E: 자막 교정 영상당 타임아웃(`LLM_TRANSCRIPT_CORRECTION_TIMEOUT_SECONDS`=240s)으로 단일 워커 hung 방지(prod 1557 강릉 51분 점유 원인). source_resolve 단위테스트·compileall·n150 facet SQL·frontend type-check/lint/build/vitest(15/15) 통과. C(작업 상세 대상필드)·D(누적 수집수)는 후속. (2026-06-25)
- [x] **T-120**: feature export source title/provenance 추가 + PinVi 명칭 정리 — `youtube_videos`에
  `source_target_type`/`source_target_value`/`source_search_query`를 추가하고, keyword 수집이 실제 보정
  검색어를 영상별 source provenance로 보존하게 했다. `/api/v1/features/snapshot`의 `youtube` block은
  `source_type`/`source_value`/`source_title`/`source_search_query`/`corrected_search_query`를 노출한다.
  현재 계약 문서와 테스트 표면의 TripMate 문구는 PinVi로 정리했다. 검증:
  `backend/tests/test_feature_export_api.py` + `backend/tests/test_etl_pipeline.py` 26건, backend 전체 pytest,
  backend `compileall` 통과. backend venv에 ruff/mypy가 없어 별도 lint/type gate는 실행하지 못했다.
  (2026-06-25)
- [~] **T-119**: 공개 도메인 로그인 403(INVALID_ORIGIN) 수정 — 라이브 브라우저 E2E가 발견. 운영 TLS 프록시(라우터 192.168.1.1 HAProxy)가 `X-Forwarded-Proto: https` 미주입 → same-origin(CSRF) 검사가 http로 재구성돼 https 공개 도메인 로그인 403(LAN-http는 정상). 라우터 직접 수정이 막혀(SSH 자격 불일치) `auth.ts`에 신뢰 origin 화이트리스트 `KTC_UI_PUBLIC_ORIGINS` 추가(브라우저 Origin 대조, CSRF 유지) + prod `.env` 설정. HAProxy XFProto 주입도 별도 권장(이중 안전망). vitest 15/15·type-check·lint·build. (2026-06-24)
- [~] **T-118**: docker-manager PR #37/#38 보안 수정 concierge 이식 — 형제 프로젝트 관리자 인증 사후 리뷰의 해당 항목 이식. AUTH-5(username 열거 타이밍: 항상 PBKDF2+상수시간 username 비교), AUTH-1(`login_events` 보존 상한 `LOGIN_AUDIT_MAX_ROWS`=5000), AUTH-4(CORS stray `*` 제거), APIKEY 해시 주석, FE-5(비밀번호 autofocus)·FE-6(생성 키 지우기). durable rate-limit·trusted-proxy-secret(#38)은 분리(인메모리 충분/기존 secret 커버), `datetime.utcnow`·캐시 TTL·모달 a11y는 이미 적용/무관. frontend type-check/lint/build/vitest(10/10)·backend compileall 통과. (2026-06-24)
- [x] **T-117**: PR #124(T-116) 인증 기능 사후 보안 리뷰 + High/Medium 보강 (prod 배포·검증 완료) — 다중 에이전트 보안 리뷰(원시 32→확정 26: High 1/Medium 5/Low 16/Nit 4)를 PR #124에 코멘트하고 High·Medium을 코드로 보강했다. High(운영 `FORWARDED_ALLOW_IPS=*`에서 `request.client.host`가 X-Forwarded-For로 위조되는 CIDR 신뢰)는 키 없는 우회를 `API_TRUSTED_CLIENT_BYPASS_ENABLED`(기본 false)로 게이트 + 기동 경고 + `.env.example` 가이드(프록시 IP 고정)로 보강. Medium: 비-local `init_db` create_all 비활성(Alembic 단독 소유), `?key=` 누출 가이드, LoginForm 오류 노출, rate-limit 계정+IP 키링, 프런트 vitest 도입(`auth.ts` 10건)+backend auth 음성 테스트. 검증: frontend type-check/lint/build/vitest(10/10)·audit 0, backend compileall. **운영 검증/배포는 prod SSH 접근 확보 후 진행 예정**. (2026-06-24)
- [x] **T-116**: 관리자 로그인·세션·공개 API 키 관리 — 단일 관리자 계정(`admin`) 로그인 화면과 httpOnly `SameSite=Strict` HMAC 세션 쿠키, user-agent fingerprint, 로그아웃 폐기, 실패 rate-limit을 추가했다. 초기 비밀번호는 PBKDF2-SHA256 해시로 gitignore된 `.env`에만 저장하고 커밋 파일에는 placeholder만 둔다. 로그인 시도/성공/실패/로그아웃은 `login_events`에 저장하고 설정 UI에서 조회한다. VWorld 호환 32자 공개 API 키를 UI에서 생성·목록·폐기하며 DB에는 hash와 hint만 저장하고 활성 키 hash는 짧은 TTL로 메모리 캐시한다. 관리자 API는 Next BFF가 주입한 actor+shared secret+trusted proxy peer로만 허용하고, 공개 API는 `X-API-Key` 또는 `?key=`를 검증하되 신뢰 CIDR은 우회 가능하다. `kor_travel_geo_v2_api_key` 설정을 추가하고 미설정 시 `VWORLD_SERVICE_KEY`로 폴백한다. `kor-travel-geo` PR #399의 후속 리뷰(X-Forwarded-For 미신뢰 기본값, admin proxy secret 음성 테스트, 401 로그인 리다이렉트, 로그인 오류 접근성)를 반영했다. (2026-06-23)
- [x] **T-102**: 재생목록 harvest 후처리 스코프 버그 수정 + 강제 재실행 — 재생목록 harvest가 신규 0개일 때 후처리가 대상이 아닌 DB 전역 미처리 영상(예전 부산 영상)을 처리하던 버그(원인: `_load_target_videos`의 `if video_ids:`가 빈 리스트를 "스코프 없음"으로 오해)를 `if video_ids is not None:`으로 수정 + 회귀 테스트. "강제 재실행"(`run-now?force=true`): 워터마크 리셋 + payload force, worker가 대상 재생목록/채널 영상을 재처리 스코프에 포함(완료분 skip→중복 없음). 프런트 강제 재실행 버튼. dev 라이브 검증(워터마크 리셋·payload force·버튼), dev/prod 배포. (2026-06-22)
- [x] **T-101**: 검수 place-search 성능 개선 — 검색이 ≈20초·게이트웨이 타임아웃에 취약하던 문제. 측정 결과 provider 3종은 ~0.4초, Gemini 의견이 직렬 await + dev 키 429(쿼터)+15초 재시도로 20초까지 늘어남이 원인. `GET /place-search`를 provider-only(≈0.4초)로, `POST /place-search/opinion`(max_attempts=1+10초 타임아웃+wait_for 12초)을 분리해 Gemini는 비동기·빠른 단일 시도(실패 시 null). 프런트 2단계 fetch("분석 중…"/생략), 검색 중지로 둘 다 취소. UI 결과 표시 ~1초로 단축. (Gemini 의견 자체는 dev 키 429라 생략 — 별개 쿼터 사안.) backend 267 pytest·frontend tsc/lint/build, dev/prod 배포. (2026-06-21)
- [x] **T-100**: 검수 후보·확정 장소 상세 정보 뷰(반응형) + 후보 삭제 + 검색 중지 — 검수 후보/확정 장소 클릭 시 PC=모달, 모바일=새 페이지(`/review/[id]`·`/place/[id]`)로 상세. `useIsMobile`(useSyncExternalStore) 분기, 공용 `CandidateDetailView`/`PlaceDetailView`. 후보 상세=추출 작업·동영상·근거(구간·source_kind·source_text)·sibling + 삭제(확인 후 `DELETE /candidates/{id}`, 확정 연결 시 409). 장소 상세=언급/동영상/유튜버 수 + 출처 동영상별 중복 횟수·근거(`GET /destinations/{id}/detail`). 검수 검색 옆 "검색 중지"(AbortSignal+cancelQueries). backend 266 pytest·frontend tsc/lint/build, dev/prod 배포(ADR-31). (2026-06-21)
- [x] **T-099**: 검색/결과 페이지 분리 + 작업 라벨 사람화 + run-now + 내부 스캔 필터 — 기본 `/`(결과: AppNav + 간단 실행 큐 + 장소·지도)와 `/collect`(수집 폼 | 실행 큐 | 작업 반복/1회성)로 분리(`AppNav`/`CollectWorkspace` 신설). 작업 카드를 `target_type_label`(유튜버/재생목록/검색어/영상)+`target_label`(키워드 또는 채널/재생목록/영상 제목, 배치)로 사람이 읽게, `job_type_label`(수집/예약 스캔/…)은 둘째 줄 배지로. 반복 "지금 진행"(`POST /source-targets/{id}/run-now`)+1회성 "다시 시작". `GET /runs?job_types=`로 `source_scan` 제외(상세 누적 영상 정상화), `/source-targets/{id}/videos` 채널 합산 견고화. backend 265 pytest·frontend tsc/lint/build, dev/prod 배포(ADR-31). (2026-06-21)
- [x] **T-098**: 검수 검색 위치 힌트 결합 + 메인 지도↔리스트 연계 — `/review` 자동 검색이 후보 `location_hint`를 이름 앞에 결합("부산"+"감천문화마을"→"부산 감천문화마을"), `cleanLocationHint`로 괄호 설명/불확실류 정제·중복 제거. 메인 장소 리스트·지도 마커에 동일 1-based 번호, 리스트 클릭→지도 `easeTo` 중심+선택, 마커 클릭→리스트 선택+`scrollIntoView`, 선택 brand 강조. 워크플로 2-병렬 구현 + 빌드 게이트, 13200 스샷 검증, dev/prod 배포(ADR-31 범위). (2026-06-21)
- [x] **T-097**: UI 전면 개편 + 검수 별도 페이지(멀티 provider) + 작업/반복 관리 + 운영·설정 모달 + API 키 DB 관리 — 메인을 접이식 사이드바·장소(지도 왼쪽 좁게)·하단 실행 큐/작업(반복·1회성 탭)으로 재편. 검수를 `/review` 별도 페이지로 옮겨 Google Places·Kakao·Naver 검색 + Gemini 의견을 한 번에 비교(`GET /place-search`, `ktc/etl/place_search.py`) + 직접 검색·지도·확정/제외. 작업 상세 모달(`/runs/{id}/videos`·`/source-targets/{id}/videos`), 반복 수정 모달(주기·횟수, `PATCH /source-targets/{id}`, `max_runs/run_count` + migration `20260621_0009`), 반복 횟수(0=무한)·간격 1시간~3달. 자동 완료(skip_transcript=false). 운영 지표 모달(`GET /metrics`). 설정 모달 + 8종 API 키 DB 관리(`settings_service.get_secret`, `api_keys` set 여부, 빈 값 미변경·감사 마스킹, 소비처 env 폴백). base-ui `Dialog`/`Tabs` 추가. backend 257 pytest·frontend lint/build, dev/prod 배포(ADR-31). (2026-06-21)
- [x] **T-096**: 숏츠/동영상 콘텐츠 유형 필터 + 재생목록 URL 확인 — 수집 폼 "콘텐츠 유형"(숏츠+동영상/숏츠만/동영상만). 백엔드 `duration_seconds<=SHORTS_MAX_DURATION_SECONDS`(기본 60초) 휴리스틱으로 `filter_candidates_by_content`, 필터 시 collect_limit로 넉넉히 수집 후 max_videos 컷. `content_filter` end-to-end. 재생목록 URL `?list=PL...`는 기존 파서로 처리됨 확인. 필터 단위 테스트 추가. (2026-06-21)
- [x] **T-095**: percent-encoded 채널 URL handle 디코드 수정 — 주소창 복사 URL(`@%EB%B9%B5...tv`)의 handle을 `parse_channel_input`이 `unquote`로 디코드해 `@빵이네tv`로 정규화(forHandle 안정화). 회귀 테스트 추가, dev/prod api 재배포. (2026-06-21)
- [x] **T-094**: 수집 입력 유연화 + 반복 수집 + 작업 제어 + UI 재구성 — 채널명/@handle/URL·재생목록 URL을 표준 ID로 해석(`source_resolve`, 실패 400), 반복 검색 체크박스+간격→`source_target` 등록·`GET/DELETE /source-targets`, 작업 중지/재시작(`RunState.CANCELLED`+`cancel_requested`, migration `20260621_0008`, worker 협조적 취소, `POST /runs/{id}/stop|restart`). UI: 장소를 지도 옆·검수/반복/운영을 하단 작은 목록, 반복 작업 패널(상태/삭제), 최근 작업 클릭→상세+중지/재시작. backend 244 pytest·frontend lint/build·Playwright 라이브 검증. (2026-06-21)
- [x] **T-093**: prod 배포 + Next 프로덕션 빌드 전환 — T-092(PR #96)를 별도 LAN prod 호스트(SSH)에 소스 rsync(.env 제외)+UI 재빌드로 배포. prod UI가 Next dev 모드(`npm run dev`)라 원격 접속 시 hydration이 안 돼 인터랙티브 전체가 멈춰 있던 것을 발견(dev=옵션3, prod=0), prod 전용 `docker-compose.override.yml`로 `next build`+`next start` 전환(dev는 npm run dev 유지). 실 도메인에서 select 개방·모바일 native select·VWorld 지도 렌더 검증. (2026-06-21)
- [x] **T-092**: 모바일(삼성 인터넷) Select 미동작 수정 — Base UI Select가 터치(coarse pointer)에서 동작 안 하던 문제를, 공유 `Select`가 coarse pointer에서 OS 네이티브 `<select>`로 폴백하도록 수정(데스크톱은 Base UI 유지, 호출부 무변경 자동 적용). lint/type-check/build 통과, Playwright 터치 컨텍스트로 native 렌더·선택 연동 검증. (2026-06-20)
- [x] **T-091**: whisper 폴백 활성화 재실행 + VWorld 지도 키 반영 — `.env`/`.env.production`에 `TRANSCRIPT_WHISPER_ENABLED=true`·`WHISPER_MODEL_SIZE=base`(.env.example 문서화). 깨끗한 DB UI E2E 재실행: 자막 3/27→11/27, 지오코딩 장소 13(전부). 전과 0건이던 키워드(제주 7)·채널(6) 소스가 whisper 전사로 추출 성공. 플레이리스트는 이번 배치 rate-limit으로 0(가용성 변동성). VWorld: docker-manager `.env`에 `NEXT_PUBLIC_VWORLD_API_KEY` 추가+UI 재시작으로 지도 렌더링 정상화. dev DB 복원·e2e DB 삭제. `docs/e2e-report-2026-06-20-ui-whisper.md`. (2026-06-20)
- [x] **T-090**: UI 레벨 수집 E2E(10영상×3소스, 깨끗한 DB) — Playwright로 웹 UI 직접 조작(폼→"수집 시작"→"자막 생성 시작"). T-089 수정 빌드로 재배포, 깨끗한 `kor_travel_concierge_e2e`에서 27영상 수집. UI 2단계 플로우 검증 + T-089 버그 수정 검증(키워드 정상 완료). 플레이리스트 9개 장소 전부 지오코딩. 채널·키워드는 자막 가용성(youtube-transcript-api 차단 추정, whisper 미활성) 때문에 0건 — transcript 비면 POI 스킵. 권장: description 단독 POI 또는 whisper 폴백. 실행 후 dev DB 복원·e2e DB 삭제. `docs/e2e-report-2026-06-20-ui-10videos.md`. (2026-06-20)
- [x] **T-089**: POI 타임스탬프 `VARCHAR(16)` truncation 버그 수정 — T-088 E2E에서 발견. `extracted_place_candidates`/`video_place_mappings`의 `timestamp_start/end`를 `String(64)`로 확장 + `@validates` 방어적 클립(모든 적재 경로 보호), Alembic migration `20260620_0007`. 클립 회귀 테스트 4종 + PostGIS 테스트 DB로 models/poi/place_service 통과. (2026-06-20)
- [x] **T-088**: 라이브 수집 E2E(3소스×5영상) 실행 및 리포트 — 채널 `@빵이네tv`/플레이리스트/키워드 `제주도 가족여행` 각 5영상에 실제 YouTube·Gemini·VWorld 호출. 기존 docker-manager 인스턴스(12601, Gemini 2.5 Flash) 사용. 채널·플레이리스트 ✅(장소 16·21, 전부 지오코딩), 키워드 ❌(`extracted_place_candidates.timestamp_start/end` `varchar(16)` truncation 버그로 88.6%에서 실패). 성공 2소스 37개 장소 좌표·주소 확보. `docs/e2e-report-2026-06-20-live-harvest.md` 작성. 버그 수정(컬럼 확장+정규화+per-video 트랜잭션)은 별도 PR 제안. (2026-06-20)

- [x] **T-087**: 영상 설명(description) 기반 POI 추출 보강 — 영상 설명란에만 있는 장소도 Gemini POI 추출 입력으로 확실히 반영. 조사 결과 데이터 흐름은 이미 정상이었다: `youtube_client.videos_list`가 `part=snippet,...`로 `videos.list` 전체 설명을 받고(`youtube_client.py:127`), `pipeline.build_candidate`가 `description_raw=snippet.description`을 채우고(`pipeline.py:90`), `ingest_service.upsert_video`가 멱등 저장하며(`ingest_service.py:343`), `summarize_service.summarize_video`가 `extract_pois(..., description_raw=video.description_raw)`로 전달(`summarize_service.py:105`)하고, `poi_extraction.build_prompt`가 `[영상 설명 원문]`을 임베드(`poi_extraction.py:80`)한다. 실제 공백은 프롬프트 지시였다 — 설명을 "보정 대상"으로만 취급해, 설명란에만 있는 장소를 추출하라는 명시 지시가 없었다. `build_prompt` 지시를 "자막과 영상 설명 양쪽에 등장하는 장소를 모두 추출, 설명에만 있고 자막에 없는 장소도 빠짐없이 추출"로 확장(기존 오탈자·문맥 보정 지시 유지). 원문/보정본 분리(ADR-16)는 그대로. `test_etl_poi.py`에 설명 임베드·LLM 전달 회귀 테스트 추가, compileall + POI 9건 + PostGIS 테스트 DB로 summarize/ingest/pipeline/video_analysis 30건 + 백엔드 전체 통과. (2026-06-20)
- [x] **T-086**: 한국어 에러 복구 UI 이식 — Next App Router 기본 오류 화면 대신 `frontend/src/app/error.tsx`·`global-error.tsx`·`components/layout/AppErrorPanel.tsx`·`lib/error-recovery.ts`를 추가(kor-travel-geo PR #391 동등). chunk/RSC/network 런타임 오류 시 같은 pathname에서 1회만 hard reload(루프 방지), 반복 실패 시 재시도/이전 화면/오류 정보를 한국어로 제공. Tailwind + shadcn 적용. lint/type-check/build 통과. (ADR-30, 2026-06-20)
- [x] **T-085**: AI 엔진 다중 provider + 사전 프롬프트 + JSON + 느린 재시도 — Gemini 외 DeepSeek V4(`deepseek-v4-flash`/`deepseek-v4-pro`, OpenAI 호환 `https://api.deepseek.com`)를 대안 LLM provider로 추가하고 `/settings`에서 엔진 전환·키 저장(평문 미노출, 감사 로그 마스킹). `ktc/etl/deepseek_client.py`(OpenAI 호환 chat completion + JSON mode), `ktc/etl/llm_client.py`(provider 디스패치 `complete_json`·`LlmRuntime`·사전 프롬프트 prepend), `config.py` `DEEPSEEK_*`/`DEEPSEEK_ENGINE_OPTIONS`/`LLM_ENGINE_OPTIONS`/`is_deepseek_model` 추가. 모든 AI 프롬프트 앞에 편집 가능 사전 프롬프트(`ai_preprompt`, 기본 `AI_PREPROMPT_DEFAULT`). JSON 출력은 Gemini `responseSchema`·DeepSeek `response_format=json_object`+스키마 첨부. 느린 사람 유사 재시도(`LLM_RETRY_*`: base 15s/max 90s/jitter 0.3/4회, `gemini_client.human_like_retry_delay` 공용)로 2/4/8초 대체. DeepSeek 키는 gitignore된 `.env`/`.env.production`, `.env.example`은 placeholder. (ADR-30, 2026-06-20)
- [x] **T-084**: `kor-travel-geo` UI 지침(StyleSeed) 채택 + Tailwind v4 전환 — geo-ui `DESIGN-RULES.md`를 그대로 따라 단일 accent brand(teal `#0f766e`)·5단계 text·surface/status/shadow/motion semantic 토큰을 `globals.css`/`tailwind.config.ts`에 이식하고 shadcn 토큰을 brand에 매핑. primitive(`button/input/label/badge/select`)를 44px·8px·uppercase 12px label·named motion·brand ring으로 정렬, 하드코딩 색(progress/log/toast/marker)을 semantic으로 치환, `frontend/docs/DESIGN-RULES.md` 정본 추가. 엔진을 Tailwind v3.4→v4로 전환(`@tailwindcss/postcss`·`@import "tailwindcss"`·`@config`·`cssVariableColor` 제거·`tw-animate-css`·`@custom-variant dark`로 light 전용). lint/type-check/build 통과, `/settings`·`/` Playwright 시각 검증. (ADR-29, 2026-06-20)
- [x] **T-083**: 프로덕션 공개 도메인 구성 — 외부 노출 prod에서 5개 도메인(Web/API/MCP + RustFS S3 API/콘솔)으로 동작. 앱 코드 변경 없이 env 기반(CORS/`APP_ENV`+`API_KEYS`/RustFS 공개 URL/`FORWARDED_ALLOW_IPS`)으로 처리. `docker-compose.yml` 하드코딩 `RUSTFS_CONSOLE_URL`/`NEXT_PUBLIC_API_BASE_URL` env-driven 전환 + `FORWARDED_ALLOW_IPS` 전달. `.env.example` prod 예시(placeholder), gitignore된 `.env.production`(실제 도메인+생성 API 키), `deploy/Caddyfile`(자동 TLS, `{$ENV}` 치환, MCP SSE-off/basic_auth). 실제 도메인/비밀은 외부 비노출(gitignore된 `.env`에만). RustFS 매핑: `s3-api.<base>`=S3 API/공개객체, `s3.<base>`=콘솔. 추가로 prod=`kor-travel-docker-manager`(공식 도메인)/dev=여기서 `127.0.0.1`+고정 12xxx로 구분하고, dev 기동 스크립트는 점유 포트를 새 포트로 바꾸지 않고 강제 종료를 물어 거부 시 중지(`FORCE_KILL_PORTS`로 무인 회수), compose `env_file`을 `${APP_ENV_FILE:-.env}`로 override 가능, MCP는 Caddy `basic_auth` 기본 ON(fail-safe). 자체 검증 워크플로(3 렌즈)로 MCP 익명 노출·`--env-file` 비밀키 누락을 잡아 수정. (ADR-28, 2026-06-20)
- [x] **T-082**: feature export `source_entity_id` 불변성 계약 테스트 — 한 후보의 upsert·reject export가 동일한 `source_record.source_entity_id`(`= str(candidate.id)`)를 갖는다는 불변성을 회귀 테스트로 고정(`test_feature_export_api.py`). consumer(kor-travel-map) inactivate 조인 전제. test-only, 코드 변경 없음. kor-travel-map concierge loader 검증 P-01 후속 권장. (이슈 #84, 2026-06-15)
- [x] **T-081**: feature export `limit` 범위 검증 — `GET /api/v1/features/{snapshot,changes}`의 `limit`에 `Query(ge=1, le=FEATURE_EXPORT_LIMIT_MAX)` 바운드를 추가해 범위 밖 입력을 silent clamp 대신 422로 거부한다(`normalize_limit`은 방어적 유지). 범위 밖 → 422 회귀 테스트 2종. kor-travel-map concierge loader 검증 P-01 후속. (이슈 #82, 2026-06-15)
- [x] **T-080**: ETL 견고화 — (1) Gemini 503 대책: 공용 `gemini_client.post_generate_content`(지수 백오프 재시도)로 5개 Gemini 호출부 전환. (2) 자막 폴백 실제 구현: `fetch_via_ytdlp`(yt-dlp VTT 파싱), `transcribe_via_whisper`(faster-whisper, env opt-in). (3) keyword expansion 실제 Gemini 연동(`make_gemini_keyword_generator`/`default_keyword_generator`, 실패 시 템플릿 폴백). 회귀 테스트 추가, ETL+scheduler pytest 77건 통과. (이슈 #80, 2026-06-15)

- [x] **T-079**: Gemini 엔진 옵션에 `gemini-2.5-flash` 추가 — `GEMINI_ENGINE_OPTIONS`에 포함해 런타임 설정에서 선택 가능하게 함(설정 검증 400 해소). api/scheduler 재빌드로 적용. (이슈 #78, 2026-06-15)

- [x] **T-078**: 자막 fetch 복구(youtube-transcript-api 1.x) — `fetch_via_transcript_api`가 제거된 정적 `get_transcript`를 호출해 모든 자막 추출이 즉시 실패(→ `travel_places` 0)하던 버그를, 1.x 인스턴스 `.fetch()`+`.to_raw_data()` 경로(구버전 호환 포함)로 수정. 신 API 회귀 테스트 추가, `transcript` pytest 통과. yt-dlp/whisper 폴백은 여전히 stub(후속). (이슈 #76, 2026-06-15)

- [x] **T-077**: transcript 부분집합 처리 — `POST /api/v1/harvest/{job_id}/transcript`에 선택적 `video_ids`(`TranscriptRequest`) 추가. 주면 수집 결과의 부분집합만 자막/POI/지오코딩 처리(수집에 없는 id는 400), 비우면 전체 처리. 전체 실행 전 1개 영상으로 품질/비용 시험 가능. (이슈 #74, 2026-06-15)

- [x] **T-076**: 자막생성 게이팅 + UI progress — 수집과 자막 생성을 분리해 사용자가 자막 전에 확인하도록 했다. backend: `HarvestRequest.skip_transcript`(수집만 실행), `POST /api/v1/harvest/{job_id}/transcript`(수집된 `video_ids`로 `transcript` 작업 생성), scheduler `transcript_handler`(자막/POI/지오코딩 + status-log progress). frontend: `HarvestConsole`이 수집을 skip_transcript로 시작 → 완료 시 "자막 생성 시작" 확인 버튼 → transcript 진행바·현재 메시지·상세 로그 표시, `lib/api.startTranscript` 추가. worker/api pytest(신규 테스트 포함)·frontend lint·type-check 통과. (이슈 #72, 2026-06-15)

- [x] **T-075**: E2E 안정화 — Windows 호스트 Playwright E2E가 stale `frontend/.next`(Turbopack) 캐시 손상으로 `Next.js package not found` panic → 페이지 reload loop → 4개 스펙 전부 실패하던 문제를, `tests/scripts/start-frontend.mjs`가 dev 기동 직전 `.next`를 정리하도록 보강해 해결(hermetic clean 캐시 시작). 백엔드/BFF/API는 정상이었고 원인은 프론트 dev 서버였다. 수정된 런처로 4/4 통과 재검증. (이슈 #70, 2026-06-15)

- [x] **T-074**: 포트 대역을 통합 docker-manager 정책(126xx)으로 정렬 — `kor-travel-docker-manager`의 `docs/ports.md`/`config/docker-targets.yml` 포트 정책에 맞춰 concierge host 포트를 API `12401→12601`(컨테이너 `8000`), MCP host `12402→12602`(컨테이너 내부 bind `12402` 유지), Web `12405→12605`(컨테이너 `3000`)로 이관했다. `.env.example`, `docker-compose.yml`, `config.py`, `cli.py`, `main.py`, frontend(`package.json`·BFF route), `scripts/*.sh`, `README`/`SKILL`/`AGENTS`/`architecture`/`dev-environment`/`CLAUDE` 문서를 갱신했다. 컨테이너 내부 MCP bind와 참조 서비스 포트(PostgreSQL `5432`, RustFS `12101`/`12105`)는 정책과 일치하여 유지했다. 결정은 ADR-27로 기록했고 이력 문서는 보존했다. docker-manager `conc` 타깃 재빌드 기동으로 검증했다. (2026-06-14)

- [x] **T-073**: 배포명 및 파이썬 임포트명 변경 — 시스템 배포명과 GitHub 저장소명을 `kor-travel-concierge`로 변경하고, Python import package를 `ktc`로 정렬했다. 기존 백엔드 패키지는 `backend/ktc`로 이동하고, 기존 별도 MCP 구현은 `ktc.mcp_server` 하위 패키지로 편입했다. 모든 내부 import 경로를 `ktc.*`로 바꾸고, 환경 변수 접두사는 `KTC_*`, 기본 DB 이름은 `kor_travel_concierge`, RustFS 기본 버킷과 공개 URL 기준은 `kor-travel-concierge`, feature provider는 `kor-travel-concierge-youtube`, export 파일명은 `kor-travel-concierge-places-*`로 정렬했다. 운영 CLI는 `ktcctl`로 추가하고 Docker Compose의 api/mcp/scheduler 실행도 같은 CLI 경로로 맞췄다. Docker/Compose/프론트엔드·테스트 package 명칭과 주요 문서를 새 배포명 기준으로 갱신했다. 설정·문서·변수 전수 검색 후 Windows host Playwright E2E `4 passed`를 재확인했다. (2026-06-13)

- [x] **T-072**: GitHub 레포지토리 이름 및 코드베이스 명칭 중간 정렬 — GitHub 저장소명과 로컬 Git origin URL을 당시 중간 명칭으로 연동했다. 루트 문서, 백엔드 엔트리포인트, 패키지 초기화 파일 등 소스코드와 문서 내 이전 프로젝트명과 이전 Python 패키지명 텍스트를 일관성 있게 변경 완료했다. 또한, 테스트용 mock RustFS 버킷명 접두사도 당시 기준으로 보정하여 전체 검증을 통과했다. (2026-06-12)

- [x] **T-071**: 고정 포트 계약 및 WSL 실행 위치 강제 — PostgreSQL/PostGIS host port를 표준 `5432`로 고정하고, 외부 RustFS는 S3 API `12101`·콘솔 `12105`, 이 repo 서비스는 API `12401`·추가 MCP `12402`·Web UI `12405`로 정렬했다. 기본 Compose는 `api`/`mcp`/`scheduler`/`frontend`만 올리고 RustFS는 `http://host.docker.internal:12101`의 외부 고정 Docker 서비스를 사용한다. `start-live.sh`와 `verify-docker-compose.sh`는 repo 소유 포트만 회수하고, 예전 내장 RustFS 컨테이너는 기본 실행에서 중지/제거하되 volume은 보존한다. 문서에는 `git`과 Windows Playwright E2E 외 모든 작업 명령을 WSL2(Ubuntu)에서 실행하는 규칙을 명시했다. 검증: WSL backend pytest/compileall, frontend lint/type-check/build, bash/Compose/diff check, Docker Compose smoke(API/Web/MCP/RustFS 객체), Windows host Playwright E2E `4 passed`, live Docker 기동, in-app browser에서 `경주 맛집`·최대 영상 수 `2` 수집 시작 반응(job_id `13`, running/progress 표시) 확인. (2026-06-12)
- [x] **T-069**: 통합 검증과 운영 문서 정리 — PostgreSQL/PostGIS disposable DB(`kor_travel_concierge_t069*`)로 feature export target pytest `9 passed`, backend 전체 pytest `198 passed`, backend `compileall`, bash script syntax, `docker compose config --quiet`, frontend lint/type-check/build, Docker Compose smoke(`rustfs`/`api`/`frontend`/`mcp`/RustFS 객체 업로드), Windows host Playwright E2E `4 passed`, `python-krtour-map` provider unit smoke `9 passed`, running `kor-travel-concierge` 대상 live `/api/v1/features/snapshot` pull smoke, TripMate POI/notice plan schema·model·snapshot fallback smoke를 완료했다. T-062 이후 `youtube_videos.channel_id` FK를 만족하도록 E2E seed가 `YoutubeChannel` stub을 함께 적재하게 보정했다. README/CLAUDE/architecture/decisions/feature export 문서는 `kor-travel-concierge → python-krtour-map feature → TripMate feature 연계 POI row` 흐름과 PostgreSQL/PostGIS·Linux Docker 실행 모델 기준으로 정렬돼 있음을 재확인했다. (2026-06-12)
- [x] **T-068**: TripMate feature 연계 POI/curated plan 소비 흐름 검증 — TripMate는 `kor-travel-concierge` DB에 직접 붙거나 자동 POI/curated plan 등록을 받지 않고, `python-krtour-map`이 `kor-travel-concierge-youtube` provider로 생성한 feature의 `feature_id`와 `feature_snapshot`을 자체 POI row(`app.trip_day_pois`, `app.notice_pois`)에 저장하는 수동 선택 흐름을 유지한다. Curated plan은 feature 모음이 아니라 그 POI row들의 모음이다. 공급자 정본 계약 문서 `docs/feature-export-api.md`를 추가하고, `docs/youtube-feature-pipeline-plan.md`, `docs/architecture.md`, `docs/decisions.md`, `README.md`를 정렬했다. `backend/tests/test_feature_export_api.py`는 TripMate feature 연계 POI snapshot까지 이어지는 이름, 좌표, 8자리 카테고리 제안, marker 색상 기준(`P-13`), YouTube video/channel/playlist 근거, Gemini URL evidence, provider evidence가 snapshot 응답에 보존되는지 검증한다. 검증: `KTC_TEST_PG_DSN=postgresql+asyncpg://addr:addr@localhost:5432/kor_travel_concierge_t068 backend/.venv/bin/python -m pytest -s backend/tests/test_feature_export_api.py` → `9 passed`. (2026-06-11)
- [x] **T-067**: `python-krtour-map` consumer/import 후속 — `python-krtour-map`에서 이미 구현·머지됨(확인만 수행, kor-travel-concierge 측 코드 변경 없음). `kor-travel-concierge-youtube` provider 변환(`kor_travel_concierge_items_to_bundles`, `make_feature_id`로 `feature_id` 생성, `SourceRecord`/`SourceLink`에 YouTube payload·confidence 보존)과 Dagster fetch/resource/asset/schedule(snapshot=full, changes=incremental, opaque cursor, `X-API-Key`)이 PR #346(T-217a/b/f)·#347(c/d/e)·#345(g)로 `python-krtour-map` origin/main에 머지 완료. T-066 배포로 fetcher 경로가 `/api/v1/features/*`로 정렬됐고, `reject`/`tombstone`은 feature `status='inactive'` 전환으로 처리한다. 실제 live pull smoke(running kor-travel-concierge 대상)는 T-069에서 완료했다. (2026-06-11) (주: 본 세션에서 stale 로컬 main 기준으로 T-217a/b를 중복 구현했다가 origin/main에 이미 있음을 확인하고 중복 PR을 닫음.)
- [x] **T-070**: feature export `category_code_suggestion` 채우기 — `python-krtour-map`의 `krtour.map.category`(8자리 `AABBCCDD`, 144개)를 `backend/ktc/data/place_category_codes.json`으로 **복사**하고(provenance/동기화 기준 헤더 포함), `ktc/etl/category_catalog.py` 로더와 `ktc/etl/category_suggestion.py` Gemini 선택기(주입형 `LlmCallable`, `poi_extraction` 패턴)를 추가했다. Gemini가 복사된 카탈로그에서 장소에 적절한 8자리 코드 하나를 고르고, 카탈로그에 존재하는 코드로 검증하며 미지정(`00000000`)·미상·호출 실패는 `None`으로 둔다(자동 확정 금지). `TravelPlace.category_code_suggestion`(`String(16)`)과 migration `20260610_0006`를 추가하고, `geocode_service.apply_geocode_to_candidate`가 장소 확정 시 기존 제안이 없을 때 한 번 채운다(생략 시 Gemini 키 유무 기반 기본 선택기, 명시적 `None`이면 비활성). `feature_export_service` payload의 `category_code_suggestion`이 이 값을 노출(기존 하드코딩 `null` 대체). 런타임 `python-krtour-map` 참조는 provider↔consumer 순환참조라 복사로 끊었고, 카테고리는 거의 안 바뀌어 drift는 수용 가능하다고 판단(2026-06-11 결정). `feature_id` 생성은 여전히 `python-krtour-map` 책임. 후속으로 수동 `create_place` 경로도 `place_service.resolve_candidate`에 주입형 `category_code_selector`를 추가해 보강했다(REST/MCP composition root가 `make_default_selector()` 주입, services→etl 역의존 회피). 검증: `localhost:5432` disposable DB에서 Alembic upgrade `20260610_0006` 및 downgrade/upgrade round-trip, offline SQL에 `category_code_suggestion` 포함 확인, backend 전체 pytest `195 passed`(신규 `test_category_suggestion` 13건 포함), compileall, etl import 순환참조 없음, `git diff --check`. (2026-06-11)
- [x] **T-066**: 범용 full/incremental feature 수집 API 추가 — `extracted_place_candidates`를 출처로 삼는 export ledger 모델 `feature_exports`(`ktc/models/feature_export.py`)와 Alembic migration `20260610_0005`를 추가했다. `export_id`(`ytpc_{candidate_id}`), 증가 cursor용 `sequence`(전용 PostgreSQL sequence `feature_export_sequence`), `operation`(`upsert`/`reject`/`tombstone`), `export_state`, `payload_json`, `payload_hash`(`sha256:`), `last_exported_at`, `rejection_reason`, `created_at`/`updated_at`와 `(export_state, updated_at, export_id)`·`sequence` unique·`candidate_id` unique·`payload_json` GIN 인덱스를 둔다. `feature_export_service.sync_feature_exports`가 후보 상태로부터 ledger를 멱등 동기화하며 payload가 바뀐 export에만 새 sequence를 부여해 cursor를 안정화한다. `GET /api/v1/features/snapshot`(활성 `upsert`만)과 `GET /api/v1/features/changes`(`upsert`/`reject`/`tombstone`)를 opaque base64 cursor와 `next_cursor`/`has_more`로 노출하고, item에는 place/address/coordinate/category suggestion, YouTube video/channel/playlist evidence, `source_record`(provider `kor-travel-concierge-youtube`, `raw_payload_hash`), `updated_at`를 담는다. REST path에는 downstream 이름을 넣지 않고 ADR-24 `X-API-Key` 인증을 적용한다. `python-krtour-map` 8자리 category mapping 확정 전까지 `category_code_suggestion`은 `null`로 두고 `category_label`만 제안한다. 검증: `localhost:5432` disposable DB에서 Alembic upgrade `20260610_0005` 및 downgrade/upgrade round-trip, offline SQL, T-066 타깃 pytest `7 passed`, backend 전체 pytest `178 passed`, compileall, `docker compose config --quiet`, `git diff --check`. (2026-06-10)
- [x] **T-065**: 장소 후보 schema 보강 및 외부 API evidence 저장 — `extracted_place_candidates`와 `video_place_mappings` 양쪽에 `source_channel_id`, `source_playlist_id`, `analysis_run_id`, `source_kind`, `provider_evidence_json`, `feature_export_status`를 추가하고 Alembic migration `20260610_0004`를 작성했다. transcript 후보 생성은 영상 channel과 첫 playlist provenance, transcript asset/source/timestamp evidence를 저장한다. 지오코딩 결정은 VWorld/Kakao/Naver 후보와 선택 결과를 `provider_evidence_json.geocoding`에 구조화해 남기며, 자동/수동 확정 매핑은 `ready`, 검수 대기 후보는 `pending`, 제외 후보는 `rejected`로 둔다. FastAPI 검수 큐와 MCP serializer도 provenance/evidence/export 필드를 반환한다. Google Places API 보강은 과금·저장 정책·라이선스 확인 전까지 미구현으로 유지하고, `python-krtour-map` 8자리 category mapping은 별도 작업으로 남겼다. 검증: `python-kraddr-geo` PostgreSQL/PostGIS 서버의 `kor_travel_concierge_test` DB에서 Alembic upgrade, T-065 타깃 pytest `39 passed`, backend 전체 pytest `171 passed`, compileall, Alembic offline SQL, `docker compose config --quiet`, `git diff --check`. (2026-06-10)
- [x] **T-064**: Gemini YouTube URL 상세 요약과 transcript 비교·정리 — Gemini 공식 문서의 YouTube URL 입력 경로를 2026-06-10 기준 재확인하고, `file_data.file_uri`에 공개 YouTube URL을 전달하는 `video_analysis_service`를 추가했다. `video_analysis` scheduler handler는 `url_summary`와 `reconcile` pending run을 순서대로 실행하고, 각 실행의 상태·모델·prompt version·요약 JSON·신뢰도·오류를 `youtube_video_analysis_runs`에 남긴다. URL summary는 `youtube_videos.gemini_url_summary*`에 저장하고, transcript 기반 POI 추출은 `youtube_videos.transcript_summary`를 채운다. reconcile은 transcript 후보와 URL summary를 Gemini에 다시 비교 요청하며 충돌·낮은 신뢰도 후보는 자동 확정하지 않고 `needs_review`와 `review_note`로 남긴다. 실제 Gemini URL smoke는 API 키와 할당량을 쓰지 않기 위해 이번 PR에서는 수행하지 않고, REST payload와 DB 상태 전이는 fake LLM으로 검증했다. 검증: `python-kraddr-geo` PostgreSQL/PostGIS 서버의 `kor_travel_concierge_test` DB에서 Alembic upgrade, T-064 타깃 pytest `21 passed`, backend 전체 pytest `171 passed`, compileall, Alembic offline SQL, `docker compose config --quiet`, `git diff --check`. (2026-06-10)
- [x] **T-063**: 주기 `source_scan` job 추가 — `source_targets`에 `video` target type, `scan_interval_minutes`, `last_seen_cursor`, `last_seen_video_published_at`, `api_budget_group`, `scan_failure_count`, `last_scan_error`, `last_scan_at`를 추가하고 Alembic migration `20260610_0003`을 작성했다. `source_scan` handler는 active due target을 API budget group과 `next_crawl_at` 기준으로 스캔해 keyword/channel/playlist는 `harvest`, video는 `video_analysis` follow-up crawl_run으로 enqueue한다. 기존 pending/running 작업이 있으면 중복 생성하지 않고 backoff 시각을 잡는다. APScheduler는 SQLAlchemyJobStore 기반 persistent job store(`apscheduler_jobs`)를 사용하고, `source-scan-enqueue` interval job으로 `source_scan` 작업을 주기적으로 만든다. REST API 계획 문서는 `/api/v1/features/*` 범용 path와 `feature_exports` ledger 기준으로 정리했다. 검증: `python-kraddr-geo` PostgreSQL/PostGIS 서버의 `kor_travel_concierge_test` DB에서 Alembic upgrade, APScheduler job store smoke, backend 전체 pytest `168 passed`, compileall, Alembic offline SQL, `docker compose config --quiet`, `git diff --check`. (2026-06-10)
- [x] **T-062**: YouTube channel/video/playlist 정규 테이블 및 ingestion upsert — `youtube_channels`, `youtube_playlists`, `youtube_playlist_videos`, `youtube_video_analysis_runs` 모델과 Alembic migration `20260610_0002`를 추가했다. 기존 `youtube_videos.channel_id`는 channel stub backfill 후 `youtube_channels.channel_id` FK로 승격했고, canonical URL, duration, thumbnail, 기본 언어, tags JSONB, Gemini URL summary, transcript summary, reconciled summary 컬럼을 보강했다. YouTube Data API의 `channels.list`/`playlists.list`/`playlistItems.list`/`videos.list` 응답에서 channel/playlist/video/link metadata를 upsert하고, playlist 유래 영상은 `youtube_playlist_videos`에 위치·playlist item id·관측 시각을 남긴다. JSONB 분석 필드에는 GIN index, analysis run에는 `(video_id, run_type, state)` composite index를 추가했다. 검증: `compileall`, Alembic offline SQL(PostgreSQL dialect), `docker compose config --quiet`, `git diff --check`, backend pytest `60 passed, 102 skipped`. (2026-06-10)
- [x] **T-061**: PostgreSQL/PostGIS 전환 및 Alembic bootstrap — backend DB runtime을 `asyncpg` 기반 PostgreSQL/PostGIS로 전환하고 `aiosqlite`/SpatiaLite/WAL/SQLite 보정 registry 경로를 제거했다. `TravelPlace.geom geometry(Point, 4326)`와 GiST 인덱스, FK/claim/source scan용 인덱스를 모델과 Alembic 초기 migration에 반영했다. `place_service` 반경 검색은 PostGIS `ST_DWithin`/geography 거리 계산으로 바꾸고, `crawl_runs` claim은 `FOR UPDATE SKIP LOCKED` 기반으로 정리했다. `.env.example`, local `.env`, Docker Compose, Dockerfile, E2E DB env를 PostgreSQL/PostGIS 기준으로 맞췄다. `KTC_TEST_PG_DSN`이 있을 때 real PostGIS 테스트를 돌리도록 fixture를 바꾸고, DSN 없는 현재 환경에서는 DB 테스트를 skip한다. 검증: `pip install -r backend/requirements.txt`, `compileall`, Alembic offline SQL(PostgreSQL dialect), `docker compose config --quiet`, backend pytest `58 passed, 101 skipped`. (2026-06-10)
- [x] **T-060**: PostgreSQL/PostGIS 전환 및 YouTube feature 공급 로드맵 문서화 — ADR-25로 SQLite + SpatiaLite에서 PostgreSQL + PostGIS로 전환하고 `python-kraddr-geo` 로컬 DB 서버를 재사용하는 결정을 추가했다. ADR-26으로 YouTube channel/video/playlist metadata, Gemini URL 요약·transcript 비교, 범용 full/incremental feature pull API, TripMate feature 연계 POI/curated plan 소비 경계를 정리했다. `docs/youtube-feature-pipeline-plan.md`에 AI agent가 순차 구현할 DB 테이블, job, API, 재확인 필요 사항을 상세화하고 T-061~T-069 백로그로 쪼갰다. (2026-06-10)
- [x] **T-059**: PR #54 리뷰 반영 — same-origin BFF 프록시로 API 키 서버 전용화 (ADR-24 보강) — 브라우저가 API 키를 더 이상 보내지 않도록 same-origin Next BFF(catch-all Route Handler `frontend/src/ktc/api/v1/[...path]/route.ts`)를 도입. BFF가 서버 사이드에서 `BACKEND_ORIGIN`(Compose `http://api:8000`, 로컬 기본 `http://localhost:12401`)으로 프록시하며 서버 전용 `BACKEND_API_KEY`로 `X-API-Key`를 주입한다. (P1-2) `NEXT_PUBLIC_*`는 보안 경계가 못 되므로 `NEXT_PUBLIC_API_KEY`를 제거하고 키를 서버 전용화. (P1-1) top-level navigation export 다운로드도 BFF 경유로 인증 환경에서 401 없이 정상 동작. `NEXT_PUBLIC_API_BASE_URL`은 기본 빈 값(브라우저는 same-origin 호출), 직접/외부 호출자는 여전히 `X-API-Key` 직접 전송. `docs/decisions.md`(ADR-24), `README.md`, `docs/dev-environment.md`, `AGENTS.md`, `CLAUDE.md`, `SKILL.md`, `docs/architecture.md`, `docs/journal.md` 정렬. (2026-06-09)
- [x] **T-058**: 고정 host port 회수 런처 도입 — Compose host port를 표준 `8000`/`3000`으로 되돌린다는 이전 서술을 반전하고, host port는 고정 `12401`(API)/`12405`(Web)를 유지(컨테이너 내부 `8000`/`3000`, host가 `12401→8000`·`12405→3000` 매핑)하도록 문서 정렬. `python-krtour-map`에서 차용한 `scripts/stop-fixed-ports.sh`를 추가해 고정 포트 `12401`/`12405`를 점유한 리스너(Linux/Docker/WSL/Windows)를 회수하고, `scripts/start-live.sh`가 `docker compose up -d --build` 이전에 이 회수를 먼저 수행해 이전 기동이 포트를 점유한 상태에서도 재시작이 성공하도록 보강. `docs/decisions.md`(ADR-23·ADR-18), `docs/dev-environment.md`, `README.md`, `SKILL.md`, `CLAUDE.md`, `docs/journal.md`의 host 접속 포트·라이브 런처 설명을 고정 `12401`/`12405` 기준으로 정렬(컨테이너 내부 포트와 E2E `18080`/`13100`은 유지). (2026-06-09)
- [x] **T-057**: REST API 버저닝(`/api/v1`)과 외부 호출용 API 인증(인증 코드) 추가 (ADR-24) — 모든 REST 엔드포인트를 `APIRouter(prefix="/api/v1")` 아래로 이동(`/health`·`/`는 버전 없이 유지)하고, `ktc.core.security.require_api_key` 의존성으로 `X-API-Key` 헤더 인증을 라우터 전체에 적용. 설정 `APP_ENV`(기본 `local`)·`API_AUTH_ENABLED`(기본 false)·`API_KEYS`를 추가해 로컬(`local/test/e2e`)은 무인증 우회, 비-local은 유효 키를 강제(키 미설정 시 안전 측 401). `docker-compose.yml`이 `APP_ENV`/`API_AUTH_ENABLED`/`API_KEYS`를 전달(기본 로컬 친화). 브라우저는 same-origin Next BFF Route Handler(`/api/v1/*`) 경유로 호출하고 BFF가 서버 전용 `BACKEND_API_KEY`로 `X-API-Key`를 주입(T-059에서 보강), E2E backend는 `APP_ENV=e2e`로 무인증. backend pytest(`test_api`·신규 `test_api_auth` 포함) 통과, `py_compile` 통과. (2026-06-09)
- [x] **T-056**: Windows 네이티브 실행 배제와 Linux Docker/WSL 전용 실행 모델 전환 (ADR-23) — `scripts/ensure-windows-ffmpeg.ps1`, `scripts/start-windows-live.ps1`, `scripts/verify-docker-compose.ps1`을 삭제하고 bash `scripts/verify-docker-compose.sh`(Compose smoke)와 `scripts/start-live.sh`(`docker compose up --build` 래퍼)로 대체. FFmpeg을 컨테이너 `/usr/bin/ffmpeg` 단일 경로로 정리(`FFMPEG_PATH` default `/usr/bin/ffmpeg`, `DOCKER_FFMPEG_PATH` 이원화 제거), Compose host port는 고정 `12401`(API)/`12405`(Web)를 유지하고 컨테이너 내부 `8000`/`3000`을 host가 `12401→8000`·`12405→3000`으로 매핑(더 이상 Windows 전용이 아닌 OS 중립 표준 host port). `config.py` API base URL·CORS 기본값, `.gitattributes`(`*.ps1` CRLF 규칙 제거), frontend `dev:live` 스크립트 제거. E2E 런처(`tests/scripts/*.mjs`)는 Windows 호스트에서 실행되므로 OS별 처리(venv interpreter 경로, `taskkill` teardown)를 유지한다(ADR-23 E2E 예외). `AGENTS.md`(DO-NOT #4 반전, 개발 환경 정책·검증), `CLAUDE.md`, `README.md`, `SKILL.md`, `docs/dev-environment.md`, `docs/architecture.md`, `docs/decisions.md`(ADR-23 추가, ADR-6 supersede)를 bash/Docker/WSL2 기준으로 재작성. `py_compile`·`bash -n` 통과. (2026-06-09)
- [x] **T-055**: PR #30 P3-5 Windows Python launcher fallback 정리 — `scripts/start-windows-live.ps1`의 Python 실행기 선택을 `Resolve-PythonCommand`로 분리하고, backend venv가 없을 때 `py -3.12`, `py -3.11`, `py -3.10`, `py -3`, `python` 순서로 Python 3.10+ 실행기만 선택하도록 변경. 3.10 미만 venv 또는 fallback은 명확한 오류로 중단한다. Windows PowerShell parser, 고정 `py -3.10` 제거 확인, `git diff --check` 통과. (2026-06-08)
- [x] **T-054**: PR #30 P3-4 코드 위생 정리 — `place_service` import 순서를 정리하고, FK가 있는 모델의 `ForeignKey`에 현재 기본 동작과 같은 `ondelete="NO ACTION"`을 명시했다. `YoutubeVideo`는 생성 시각보다 마지막 수집 시각이 도메인 상태라 `TimestampMixin` 대신 `crawled_at`을 유지한다는 주석을 추가. legacy `video_place_mappings` 재생성 SQL도 같은 FK delete 정책으로 맞추고 회귀 테스트를 추가했다. 모델/마이그레이션 pytest 13건, backend `compileall` 통과. (2026-06-08)
- [x] **T-053**: PR #30 P3-3 export 파일명 개선 — `/api/destinations/export`의 `Content-Disposition` 파일명을 고정 `kor-travel-concierge-places.*`에서 `kor-travel-concierge-places-{selected|all}-{내보낸개수}-sort-{정렬}-{UTC timestamp}.{확장자}` 형식으로 변경. 선택/전체 export 범위, 실제 내보낸 장소 수, 정렬 기준, 생성 시각을 파일명에 반영한다. API Content-Disposition 회귀 테스트 추가. 관련 API pytest 2건, backend 전체 pytest 152건, compileall 통과. (2026-06-08)
- [x] **T-052**: PR #30 P3-2 FFprobe/FFmpeg 환경변수 사용 범위 정리 — backend runtime 설정과 Docker Compose Python 서비스는 실제 대표 프레임 추출 코드가 사용하는 `FFMPEG_PATH`만 유지하고, `FFPROBE_PATH` runtime 주입을 제거. frontend compose 서비스의 FFmpeg/FFprobe env 주입도 제거했다. `FFPROBE_PATH`는 `scripts/ensure-windows-ffmpeg.ps1`과 Windows live 사전 검증에서 `ffprobe -version`을 확인하기 위한 스크립트 관리 값으로만 문서화. Docker Compose config, PowerShell parser, frame extraction pytest 15건, backend compileall 통과. (2026-06-08)
- [x] **T-051**: PR #30 P3-1 문서 상태 불일치 정리 — `docs/pr-review-2026-06.md`에 남은 P3 후속 항목을 `docs/tasks.md`의 대기 작업 T-052~T-055로 승격해 `tasks.md`의 "대기 없음" 상태와 PR #30 추적 문서가 어긋나지 않도록 정리. `CLAUDE.md`의 다음 착수 대상도 T-052로 갱신하고 P3-1 추적 항목을 완료 표시. 문서 diff 공백 검사 통과. (2026-06-08)
- [x] **T-050**: PR #30 P2-8 `_names_compatible` 부분일치 기준 축소 — 지오코딩 근접 중복 재사용 시 이름 exact match는 유지하되, 포함 관계 alias는 짧은 쪽이 4자 이상이고 긴 쪽 대비 60% 이상인 경우에만 허용하도록 변경. `카페` ↔ `월정리카페`, `성산` ↔ `성산일출봉` 같은 짧은 부분명은 기존 장소 자동 재사용 대신 `nearby_place_name_mismatch` 검수 대기로 남긴다. 짧은 부분명 거부와 구체적 alias 허용 테스트 추가. geocode service pytest 8건, backend 전체 pytest 152건, compileall 통과. (2026-06-08)
- [x] **T-049**: PR #30 P2-7 Gemini engine 모델 설정 단일 출처 정리 — `backend/ktc/core/config.py`에 `GEMINI_ENGINE_OPTIONS`와 `GEMINI_ENGINE_VERSION_DEFAULT`를 두고 `.env.example`, backend 설정 검증, API 응답, frontend 설정 화면이 같은 목록을 사용하도록 정리. `/api/settings`는 `gemini_engine_options`와 `gemini_engine_default`를 반환하고, `settings_service`는 미지원 모델 저장을 400으로 거부한다. POI 후처리와 Deep Research는 DB runtime 설정의 engine 값을 실제 Gemini 호출에 전달한다. backend 설정/API/scheduler 테스트, frontend lint/type-check/build, Playwright 설정 E2E 통과. (2026-06-08)
- [x] **T-048**: PR #30 P2-6 heartbeat task 예외 처리 범위 축소 — scheduler `execute_run()`의 heartbeat task 취소 대기에서 `contextlib.suppress(asyncio.CancelledError, Exception)`을 제거하고 `CancelledError`만 정상 취소로 처리. 이미 실패한 heartbeat task의 예상 밖 예외는 `logger.exception`으로 기록해 조용히 사라지지 않도록 보강했다. heartbeat task 예외가 job 완료를 막지 않되 로그에는 남는 회귀 테스트 추가. scheduler worker pytest, backend 전체 pytest 147건, compileall 통과. (2026-06-08)
- [x] **T-047**: PR #30 P2-5 `suppressHydrationWarning` 범위와 VWorld 키 주입 정리 — 공유 `Input` 컴포넌트의 전역 `suppressHydrationWarning`을 제거해 실제 SSR mismatch가 가려지지 않도록 수정. Windows live 스크립트는 `.env`의 `NEXT_PUBLIC_VWORLD_SERVICE_KEY`를 부모 PowerShell 환경에만 설정하고 frontend child 명령 블록에는 다시 쓰지 않는다. E2E frontend 시작 스크립트도 VWorld fallback용 빈 값을 부모 프로세스에만 설정한 뒤 child는 상속 환경을 사용한다. frontend lint/type-check/build, `node --check` script 검증, PowerShell parser 검증 통과. (2026-06-08)
- [x] **T-046**: PR #30 P2-4 Next 16 후속 정리 — frontend `package.json`에 `engines.node >=20.9.0`을 명시하고, 런타임 기준과 맞지 않던 `@types/node`를 `^25` 계열에서 `^20` 계열로 낮춰 lockfile을 갱신. `tsconfig.json`의 `jsx: preserve` 권고는 실제 `next typegen` 실행 시 Next.js 16.2.7이 `react-jsx`를 mandatory change로 되돌리는 것을 확인해 적용하지 않고 현재 도구 강제값을 유지. `npm install --package-lock-only` audit 0건, frontend lint/type-check/build 통과. (2026-06-08)
- [x] **T-045**: PR #30 P2-3 `next-env.d.ts` 생성물 추적 제거 — `frontend/next-env.d.ts`를 git index에서 제거하고 `.gitignore`에 추가해 Next.js가 `next typegen`/`next build` 중 재생성해도 워크트리가 더러워지지 않도록 정리. 임시 정규화 훅이던 `frontend/scripts/normalize-next-env.mjs`와 `posttype-check`/`postbuild` 스크립트를 제거해 생성물 추적 의존을 없앴다. clean 파일 삭제 상태에서 frontend lint/type-check/build 통과, `git check-ignore -v frontend/next-env.d.ts`로 ignore 확인. (2026-06-08)
- [x] **T-044**: PR #30 P2-2 keyword/playlist 증분 수집 보강 — `source_targets.last_crawled_at`을 keyword와 playlist target의 증분 watermark로 사용. keyword harvest는 이전 성공 시각을 YouTube `search.list`의 `publishedAfter`로 전달하고, playlist harvest는 항목의 영상 공개 시각이 watermark 이하가 되는 지점에서 pagination을 중단한다. 수집 성공 후 keyword/channel/playlist target의 `last_crawled_at`을 현재 실행 시각으로 갱신. keyword `publishedAfter` 전달과 playlist pagination 중단 회귀 테스트 추가. backend 전체 pytest와 compileall 통과. (2026-06-08)
- [x] **T-043**: PR #30 P2-1 장소 export 직렬화 안정화 — `/api/destinations/export`에 기본 500건, 최대 1,000건의 장소 export limit을 적용하고, 지나치게 긴 `ids` 목록은 1,000개 초과 시 400 응답으로 제한. XLSX/GPX/KML 직렬화는 `asyncio.to_thread`로 격리해 이벤트 루프를 막지 않도록 변경하고, XML 1.0에서 허용되지 않는 제어문자를 제거한 뒤 escape하도록 보강. API route thread 실행·limit clamp 테스트와 XLSX/GPX/KML XML sanitizer 테스트 추가. backend 전체 pytest와 compileall 통과. (2026-06-08)
- [x] **T-042**: PR #30 P1-6 docker-compose CORS override와 Windows live 포트 종료 안전장치 보강 — `docker-compose.yml`의 `CORS_ALLOW_ORIGINS`를 `.env` override 우선으로 바꾸고 기본값에 Windows live Web 포트(`12405` 또는 `FRONTEND_HOST_PORT` override), 로컬 개발 `3000`, Compose smoke `12405`, Playwright E2E `13100` origin을 포함. `scripts/start-windows-live.ps1`은 현재 PowerShell 환경변수 또는 `.env`의 CORS 값을 우선 사용하고, 포트 점유 PID가 현재 TripMate 워크트리 경로를 가진 프로세스로 확인될 때만 자동 종료한다. 다른 프로세스는 직접 종료하거나 `-ForcePortKill`을 명시해야 한다. PowerShell parser, `docker compose config`, CORS override/default config 검증 통과. (2026-06-08)
- [x] **T-041**: PR #30 P1-5 FFmpeg 자동 다운로드 무결성 검증과 안정 URL 보강 — `scripts/ensure-windows-ffmpeg.ps1`의 기본 FFmpeg 다운로드 URL을 날짜 고정 패키지에서 gyan.dev 안정 링크 `ffmpeg-release-full.7z`로 변경하고, `.sha256` sidecar 또는 명시 `-ArchiveSha256` 값으로 `Get-FileHash` 검증을 강제. 로컬 7-Zip이 없을 때 받는 portable `7zr.exe`도 버전 고정 GitHub asset과 고정 SHA256으로 검증한 뒤 사용한다. PowerShell 5.1 pipeline 실행 오류를 피하기 위해 압축 해제는 `Start-Process` 종료 코드 검증으로 전환. Windows PowerShell parser 검증과 release essentials 아카이브 smoke 통과. (2026-06-08)
- [x] **T-040**: PR #30 P1-4 지도 marker diff 기반 캐싱과 선택 재중심 보강 — `VWorldMap`이 `places` 또는 선택 변경 때 marker를 전량 teardown하지 않고 `place_id` 기준으로 기존 marker를 갱신·추가·삭제하도록 변경. marker element와 popup, click handler를 cache entry로 관리하고 선택 상태 스타일만 별도 동기화한다. 선택 장소 이동은 현재 marker cache에 있는 항목을 기준으로 `selectedPlaceId` 변경 때만 실행해 데이터 refresh가 사용자의 지도 pan 위치를 강제로 되돌리지 않게 보강. frontend lint/type-check/build와 Playwright E2E 4건 통과. (2026-06-08)
- [x] **T-039**: PR #30 P1-3 스키마 드리프트 경량 migration registry 도입 — `schema_migrations` 테이블과 `run_schema_migrations`를 추가해 기존 SQLite DB 보정 작업을 idempotent helper 호출에만 의존하지 않고 적용 이력으로 추적. 현재 보정 migration으로 `crawl_runs` 상태 로그 컬럼 보강과 `video_place_mappings` 반복 등장 제약 제거를 등록하고, `init_db()`가 `create_all` 이후 migration registry를 실행하도록 변경. 동일 migration id가 두 번 실행되지 않는 테스트를 추가하고 backend DB migration 테스트 통과. (2026-06-08)
- [x] **T-038**: PR #30 P1-2 `claim_next_pending` 원자적 claim 보강 — `crawl_runs` pending 작업 claim을 후보 조회 후 `WHERE state='pending'` 가드가 있는 `UPDATE ... RETURNING`으로 전환해 같은 후보를 여러 실행자가 보더라도 한 실행자만 `running` 전이에 성공하도록 수정. 파일 기반 SQLite 병렬 claim 테스트를 추가해 동시에 두 claim을 시도해도 단일 작업만 claim되는지 검증. scheduler/crawl run 관련 테스트 통과. (2026-06-08)
- [x] **T-037**: PR #30 P1-1 원본 미디어 스트리밍 업로드 경로 추가 — `MediaStore`에 file-like 객체 업로드 메서드를 추가하고, RustFS는 `upload_fileobj` 기반 전송을 사용하도록 보강. `store_stream_and_record`가 업로드 중 읽은 chunk로 SHA256과 크기를 계산해 `media_assets`에 기록하며, `store_raw_media`는 기존 `bytes` 경로와 새 `fileobj` 경로 중 하나를 선택할 수 있게 확장. 원본 동영상 저장 테스트에 streaming 경로를 추가하고 관련 미디어 저장 테스트 통과. (2026-06-08)
- [x] **T-036**: PR #30 P0-3 기존 DB의 stale unique index 제거 — T-028에서 제거한 `video_place_mappings(video_id, place_id)` 반복 등장 제약이 기존 SQLite DB에 남아 있는 경우를 `init_db()` 보정 경로에서 제거. 명시 unique index는 `DROP INDEX IF EXISTS`로 정리하고, 과거 table-level `UniqueConstraint`로 생성된 DB는 현재 스키마로 테이블을 재생성해 데이터를 보존하면서 중복 매핑을 허용한다. legacy unique table 재생성 후 같은 영상·장소 매핑 2건 insert가 가능한 회귀 테스트를 추가하고 backend 검증 통과. (2026-06-08)
- [x] **T-035**: PR #30 P0-2 `deep_research` job handler 등록 — scheduler 기본 handler registry에 `deep_research`를 추가하고, 장소 기준 Deep Research 작업이 Gemini JSON Schema 응답을 받아 `travel_places.detailed_research_content`와 `gemini_enriched_description`을 갱신하도록 `deep_research_service`를 추가. `prompt`와 `max_sources` payload를 검증·clamp하고 작업 상태 로그를 남기며, 기본 scheduler 실행이 unsupported job으로 실패하지 않고 완료되는 단위 테스트를 보강. 관련 scheduler/API/MCP 테스트 통과. (2026-06-08)
- [x] **T-034**: PR #30 P0-1 Tailwind 색상 토큰 alpha modifier 보강 — Tailwind semantic 색상 토큰을 opacity modifier를 받을 수 있는 함수형 토큰으로 전환해 `bg-muted/70`, `ring-ring/50`, `bg-destructive/10`, invalid focus ring 등이 실제 CSS로 생성되도록 보강. 누락된 `--destructive-foreground` CSS 변수와 `--sidebar-ring` 세미콜론도 정리. Tailwind CLI 산출물에서 alpha class 생성을 확인하고, frontend `npm run lint`, `npm run type-check`, `npm run build`, Playwright E2E 4건 통과. (2026-06-08)
- [x] **T-033**: RustFS 로컬 설정 워크트리 동기화 — `python-kraddr-geo-codex`의 RustFS 운영 기준(S3 `12101`, console `12105`, 기본 credential `rustfsadmin`)을 확인하고, 현재 워크트리와 `kor-travel-concierge-live-test`의 `.env` RustFS credential 및 설정 블록을 동일하게 맞춤. 두 워크트리에 `RUSTFS_PUBLIC_BASE_URL`, `RUSTFS_DOCKER_ENDPOINT`, `RUSTFS_OBJECT_PREFIX`, `RUSTFS_REGION` 누락을 보강하고, `.env.example`, README, `SKILL.md`, Docker Compose, `Settings`, RustFS init/verify 스크립트, scaffold `etl/media.py`, live-test 관련 테스트 기대값을 단일 `kor-travel-concierge` 버킷과 `features/` prefix 기준으로 정리. 실행 중인 `kor-travel-concierge-rustfs-1`도 새 `.env` 기준으로 재생성. `docker compose --env-file .env config --quiet`, `compileall`, RustFS 객체 smoke, backend pytest 137건, frontend lint/type-check/build, Playwright E2E 4건 통과. (2026-06-08)
- [x] **T-032**: harvest 후처리 장소 생성 연결 및 RustFS `kor-travel-concierge` 매핑 — scheduler `harvest` handler가 YouTube 영상 적재 후 자막 추출, Gemini POI 요약, VWorld/Kakao/Naver 지오코딩 적용까지 이어 실행하도록 `postprocess_service`를 추가. `pipeline.run_harvest`는 적재한 `video_ids`를 반환하고, 후처리 결과를 작업 summary의 `postprocess`에 포함한다. 후처리 단위 테스트는 Gemini/자막/지오코딩 fake를 주입해 `travel_places`, `extracted_place_candidates`, `video_place_mappings` 생성과 검수 대기 경로를 검증한다. RustFS는 호스트 `http://127.0.0.1:12101`, 컨테이너 `http://rustfs:9000`, 단일 `kor-travel-concierge` 버킷, `features/` prefix, 공개 URL `http://127.0.0.1:12101/kor-travel-concierge` 기준으로 코드·문서·로컬 `.env`를 맞춤. backend pytest 137건, 관련 ETL/스케줄러 테스트 30건, `compileall`, `docker compose --env-file .env config --quiet`, RustFS smoke, Playwright E2E 4건 통과. (2026-06-08)
- [x] **T-031**: 작업 상태 상세 로그·실행 큐 표시 보강 — `crawl_runs`에 `current_message`와 `status_log_json`을 추가하고 기존 SQLite DB에는 `init_db`에서 컬럼을 보강하도록 구성. scheduler와 harvest 파이프라인은 Gemini 검색어 보정, YouTube 검색, 동영상 상세 조회, DB 적재, 완료·실패·stale 재시도 상태를 한국어 상세 로그로 누적. 자막/Gemini POI 요약 서비스도 자막 추출·RustFS 저장·Gemini 보정·후보 생성 로그 reporter를 받을 수 있게 확장. `/api/harvest/{job_id}`, `/api/runs`, MCP `get_harvest_status`는 현재 메시지와 상세 로그를 반환. 웹 작업 상태 패널은 현재 문구와 타임라인 로그를 표시하고, 운영 패널은 `running`/`pending` 작업을 별도 조회해 실행 큐 목록과 진행률을 보여줌. backend pytest 137건, frontend `npm run lint`, `npm run type-check`, `npm run build`, Playwright E2E 4건 통과. (2026-06-08)
- [x] **T-030**: Windows FFmpeg 자동 준비 및 VWorld 지도 축소 안정화 — `scripts/ensure-windows-ffmpeg.ps1`을 추가해 Windows live 시작 전 프로젝트 로컬 `.local\ffmpeg`에 지정된 gyan.dev FFmpeg 빌드가 없으면 내려받고 `.env`의 `FFMPEG_PATH`/`FFPROBE_PATH`를 갱신하도록 구성. 백엔드 대표 프레임 추출은 환경변수 경로를 사용하고 Docker Compose는 컨테이너 내부 경로를 별도 주입. VWorld 지도는 대한민국 WMTS 유효 범위와 최소 zoom을 지정해 대한민국 전체보다 더 멀리 축소할 때 외부 tile 범위 요청으로 발생하던 browser `InvalidStateError` 원인을 차단. Windows Playwright webServer도 `node` PATH 의존 대신 현재 Node 실행 파일을 사용하도록 보강. (2026-06-07)
- [x] **T-029**: Windows live test 후속 보완 — `scripts/start-windows-live.ps1`이 PowerShell PATH에 의존해 Web 기동에 실패하지 않도록 Windows Node.js 실행 파일과 Next.js CLI를 직접 사용하게 보강. 설정 화면은 live `.env`의 `gemini-flash-latest` 값을 선택지로 보존할 수 있게 수정. 공용 `Input`은 native `input` 기반으로 단순화하고 브라우저 주입 속성 차이를 hydration 경고에서 제외. API `12401`, Web `12405`, RustFS `12101/12105`, Gemini/YouTube/VWorld/Kakao 키 smoke와 Playwright 화면 검증을 clean worktree에서 재확인. (2026-06-07)
- [x] **T-028**: 장소 언급 소스·중복 정렬·내보내기 구현 — `video_place_mappings`가 같은 영상의 같은 장소 반복 등장도 보존할 수 있도록 영상-장소 unique 제약을 제거하고, `/api/destinations`에 `mention_count`, `source_channel_count`, `source_videos` 집계를 추가. 웹 장소 목록은 언급 많은 순/최신 등록 순/이름 순/카테고리 순 정렬과 선택 체크박스, 선택 또는 전체 장소 `xlsx`/`gpx`/`kml` 내보내기를 제공. MCP 장소 상세도 언급 수와 유튜버 수를 반환. 카테고리 추정은 Kakao Local 공식 카테고리를 우선하되 Gemini 후보 카테고리와 VWorld/Naver 주소 맥락을 보조 근거로 쓰고 불확실하면 검수 큐에 남기는 정책으로 문서화. backend pytest 130건, frontend `npm run lint`, `npm run type-check`, `npm run build`, Playwright E2E 4건 통과. (2026-06-07)
- [x] **T-027**: Windows live 포트 `12401`/`12405` 고정 — Windows 호스트에서 실제 TripMate 서버를 띄울 때 API는 `12401`, Web은 `12405`를 사용하도록 `.env.example`, 백엔드/프론트 fallback, Docker Compose host port, 검증 스크립트, 문서를 정리. `scripts/start-windows-live.ps1`을 추가해 해당 포트가 점유 중이면 리스너 PID를 종료하고 RustFS/API/Web을 고정 포트로 다시 띄울 수 있게 함. (2026-06-07)
- [x] **T-026**: Next.js route type 생성물 안정화 — Next.js 16의 `next typegen`, `next build`, `next dev`가 `frontend/next-env.d.ts`의 route type import 경로를 `.next/dev/types`와 `.next/types` 사이에서 번갈아 갱신해 검증 후 워크트리가 더러워지는 문제를 정리. `posttype-check`/`postbuild` hook에서 `scripts/normalize-next-env.mjs`를 실행해 route import를 `.next/dev/types/routes.d.ts`로 정규화하도록 구성. (2026-06-05)
- [x] **T-025**: PR #6~19 프론트엔드·E2E·문서 리뷰 반영 — Tailwind v3 호환 class로 shadcn/ui primitive를 보정하고, 설정 페이지와 검수 큐를 React Hook Form/Zod/TanStack Query 흐름에 맞춰 정리. VWorld 지도 fallback overlay와 접근성 region을 추가하고 marker 갱신과 선택 위치 이동을 분리. E2E는 Python 3.10 호환 시간대 처리, 외부 VWorld 타일 비활성화, shadcn Select 실제 클릭 흐름, 관련 console error 필터링으로 안정화. ADR-20과 아키텍처 전환 후보 표는 sqlite-vec/PostGIS/PgQueuer 도입 기준을 관측 가능한 수치 트리거로 보강. (2026-06-05)
- [x] **T-024**: PR #6~19 ETL·동영상·지오코딩 리뷰 반영 — YouTube Data API 키를 query string 대신 `X-goog-api-key` 헤더로 전달하고 오류 메시지에서 키를 마스킹, 429/5xx/네트워크 재시도와 per-run quota budget, `videos.list` 50개 chunking을 적용. 채널 harvest는 DB 워터마크를 사용해 uploads playlist를 조기 종료. RustFS 업로드와 POI 추출은 executor로 격리하고, 같은 bucket/object_key `media_assets`는 재사용. Gemini REST `LlmCallable` 팩토리를 추가해 JSON response schema를 실제 호출에 전달. 프레임 추출 timeout 래핑과 오디오 전용 스트림 조기 제외, VWorld 오류 fallback·road/parcel 후보 병합, 자동 지오코딩 매핑 생성과 근접 이름 불일치 검수 대기 처리를 반영. backend pytest 128건 통과. (2026-06-05)
- [x] **T-023**: PR #6~19 백엔드 코어·MCP·스케줄러 리뷰 반영 — Python 3.10 호환을 위해 `StrEnum` 의존을 제거하고 `str, Enum` 기반으로 모델 enum을 정리. `search_keywords`, `source_targets`, `video_place_mappings` 중복 방지 제약과 `media_assets.size_bytes` `BigInteger`, `travel_places.description_review_status` non-null 계약을 반영. `/api/settings`는 허용 키 whitelist와 단일 트랜잭션 저장으로 제한. SQLite 연결에 `foreign_keys`/`busy_timeout`을 적용하고 SpatiaLite graceful path에 debug 로그를 남김. 장소 병합 시 `media_assets`도 target으로 이전하고, MCP 쓰기 도구의 도메인 변경·감사 로그를 같은 commit으로 묶으며 idempotency key 요청 불일치를 명시 오류로 처리. scheduler 즉시 실행은 `next_run_time`으로 옮겨 단일 실행자 race를 제거. backend pytest 114건 통과. (2026-06-05)
- [x] **T-022**: PR #1~5 리뷰 정합성 반영 — `.env.example`과 `Settings`의 MCP 쓰기 기본값을 안전 모드(`false`)로 낮추고, README와 개발 환경 문서의 env 예시는 `dotenv` 기준으로 정리. RustFS `transcript` 자산의 버킷 매핑과 `MEDIA_RETENTION_POLICY`/행 단위 보존 정책 관계를 명시. ADR-9의 YouTube Data API/`yt-dlp` 역할을 ADR-11과 맞추고, README 라이선스 문구에 맞춰 MIT `LICENSE` 파일 추가. frontend Dockerfile은 lockfile 재현성을 위해 `npm ci`를 사용하도록 변경. (2026-06-05)
- [x] **T-020**: Next.js 메이저 업그레이드 및 npm audit 대응 — frontend를 Next.js `16.2.7`, React / React DOM `19.2.7`, `eslint-config-next` `16.2.7`, ESLint `9.39.4`로 업그레이드. `next lint` 제거에 맞춰 `eslint.config.mjs` flat config와 `npm run lint = eslint .`로 전환하고, `npm run type-check`는 `next typegen && tsc --noEmit`으로 clean checkout route type 생성을 보장. Next 16 Turbopack의 package CSS import 해석에 맞춰 Tailwind v4용 `tw-animate-css` / `shadcn/tailwind.css` import를 제거하고 Tailwind v3 호환 `tailwindcss-animate` plugin과 v3 arbitrary class 표기로 대체. Next 내부 `postcss@8.4.31` audit 항목은 npm `overrides`로 root `postcss@8.5.15`를 사용하도록 정리. React Compiler lint 경고는 `form.watch`를 `useWatch`로 교체해 해소. ADR-21과 개발 문서 갱신. `npm audit` 0건, `npm run lint`, clean `.next` 기준 `npm run type-check`, `npm run build`, Playwright E2E 4건 통과. (2026-06-05)
- [x] **T-016**: 고도화 후보 검토 — sqlite-vec / SQLite Vec1 의미론적 검색, PostgreSQL/PostGIS 전환, PgQueuer, APScheduler + PostgreSQL advisory lock 후보를 공식 문서 기준으로 검토. 현재 소형 프로젝트 단계에서는 선제 도입하지 않고, 의미론적 검색은 `place_embeddings` optional feature, PostGIS는 확정 장소 100,000건·매핑 1,000,000건·반경 검색 p95 500ms 초과·최근 7일 `database is locked` 재시도 10회 이상, PgQueuer는 PostgreSQL 전환 이후 pending 대기 작업 최고 연령 5분 초과 3회 연속 또는 단일 worker 24시간 처리량 부족 시 검토하는 것으로 ADR-20에 결정. 아키텍처 대규모 전환 후보 표와 wrapper 최소화 원칙을 갱신. (2026-06-05)
- [x] **T-015**: Playwright E2E 검증 — `tests/playwright.config.ts`가 backend `127.0.0.1:18080`과 frontend `127.0.0.1:13100` 개발 서버를 자동 기동하도록 구성. `tests/scripts/seed_e2e.py`로 SQLite E2E DB에 장소, 검수 후보, MCP 감사 로그, RustFS 대표 프레임 메타데이터를 매 테스트마다 재시드. 메인 화면의 VWorld 지도 fallback/패널 렌더링, 수집 시작 `job_id`/`pending` 표시, Deep Research 트리거, 매칭 실패 후보 수동 보정 후 장소 목록 반영, 설정 페이지 Gemini 엔진 저장을 브라우저에서 검증. CORS 허용 origin 설정, E2E 산출물 ignore, 공용 `Input` ref 전달 보정, 검수/장소/운영 패널 접근성 이름을 추가. Browser plugin은 현재 세션에 없어 일반 Playwright로 검증. `npm test` 4건, `npm run lint`, `npm run type-check`, `npm run build`, backend `compileall`, backend pytest, `docker compose --env-file .env config --quiet` 통과. (2026-06-05)
- [x] **T-021**: VWorld 우선 지오코딩 및 Kakao 키워드 장소 검색 보강 — 지오코딩 기본 우선순위를 VWorld → Kakao → Naver로 조정하고, VWorld는 `python-vworld-api`의 `AsyncVworldClient`를 직접 사용하도록 `VWorldGeocoder`/`VWorldReverseGeocoder` 내부 wrapper class를 제거. `backend/requirements.txt`에 `python-vworld-api` GitHub archive commit pin 추가, 로컬 검증은 `F:\dev\python-vworld-api` editable 설치로 수행. Kakao Local은 주소 검색 결과가 없을 때 공식 `GET /v2/local/search/keyword.json` 키워드 장소 검색 fallback을 사용해 POI명·도로명 주소·지번 주소·카테고리를 후보로 저장. `.env.example`, README, 아키텍처, 개발 환경, ADR-19, 에이전트 문서를 최신 정책으로 갱신. 지오코딩 단위 테스트 15건, backend 전체 pytest, `compileall`, `docker compose config --quiet`, Python Compose image build, API 컨테이너 `AsyncVworldClient` import, RustFS smoke, `npm run lint`, `npm run type-check`, `npm run build` 통과. (2026-06-05)
- [x] **T-014**: Windows 및 Docker Compose 통합 검증 — Compose를 `.env` optional 구성과 host port 변수(`RUSTFS_HOST_PORT`, `API_HOST_PORT`, `MCP_HOST_PORT`, `FRONTEND_HOST_PORT`) 가능 구조로 보강. RustFS는 호스트 `12101/12105`, 컨테이너 내부 `rustfs:9000/9001`로 분리하고, API health 이후 MCP/scheduler/frontend가 시작되도록 `depends_on.condition` 적용. Docker Compose MCP는 `streamable-http` transport(`12402/mcp`)로 실행. `.dockerignore` 추가로 Docker build context를 root 6.47KB, frontend 1.34KB 수준으로 축소. `aiosqlite` SpatiaLite extension loading을 `run_async` 경유로 보정하고 공간 컬럼 검사 버그를 수정. `scripts/verify-docker-compose.ps1`와 `scripts/verify_rustfs.py`로 health, MCP port, RustFS 버킷 생성, 객체 업로드·조회 smoke 검증 자동화. WSL Docker CLI에서 현재 고정 포트 `12101/12105`, `12401`, `12402`, `12405`로 `rustfs/api/mcp/scheduler/frontend` 전체 실행, HTTP health 200, RustFS 3개 버킷 smoke 객체 업로드·조회, SQLite DB 생성 확인. Windows PowerShell은 현재 세션 PATH에서 Docker CLI를 찾지 못해 래퍼 preflight 메시지까지만 확인. backend pytest 105건, `npm run lint`, `npm run type-check`, `npm run build`, `docker compose config --quiet` 통과. (2026-06-05)
- [x] **T-013**: 지도·리스트·운영 패널 구현 — `maplibre-gl` 기반 VWorld WMTS raster style과 장소 marker 표시, 장소 리스트/선택 동기화, Deep Research 트리거, 매칭 실패 후보 검수 큐(신규 장소 생성·제외), 최근 작업/실패 작업/MCP·웹 감사 로그/RustFS 객체·헬스 요약 운영 패널 구현. `/api/runs`, `/api/audit-logs`, `/api/storage/rustfs`, 장소 보정, 후보 해결, Deep Research REST endpoint 추가. 공개 npm 패키지 `maplibre-vworld`/`maplibre-vworld-js`가 없어 T-013 구현은 `maplibre-gl` 직접 WMTS 구성으로 진행. backend pytest 105건, `npm run lint`, `npm run type-check`, `npm run build` 통과. dev server `http://127.0.0.1:3001/` 응답 및 패널 렌더링 확인. (2026-06-05)
- [x] **T-012**: Next.js 프론트엔드 스택 정비 — shadcn/ui 초기화(`components.json`, `Button`, `Input`, `Select`, `Field`, `Badge`, `cn`), Tailwind semantic token 구성, React Hook Form + Zod 수집 폼, TanStack Query provider 및 수집 시작 mutation/상태 polling 구현. `maplibre-vworld` npm 의존성은 공개 패키지가 없어 제거하고 `maplibre-gl`은 유지. Next 14 호환을 위해 ESLint 8 + `eslint-config-next@14.2.35` 설정 추가. `npm run lint`, `npm run type-check`, `npm run build` 통과. dev server `http://127.0.0.1:3001/` 응답 확인. (2026-06-05)
- [x] **T-011**: MCP 서버 읽기/쓰기 UX 구현 — 외부 MCP SDK와 로컬 `mcp/` 실행 디렉터리 이름 충돌을 피하기 위해 실제 구현을 `ktc.mcp_server` 패키지로 분리하고 `mcp/server.py`는 Docker Compose 호환 래퍼로 유지. FastMCP 서버 등록, 읽기 도구(`get_harvest_status`, `search_existing_places`, `get_place_detail`), 쓰기 도구(`harvest_travel_destinations`, `correct_place`, `merge_places`, `trigger_deep_research`, `review_unmatched_place`, `resolve_place_candidate`) 구현. 쓰기 도구는 Pydantic 스키마 검증, 필수 `idempotency_key`, `audit_logs` 기록을 적용. `place_service`에 장소 보정, 병합, 후보 검수/해결 도메인 함수 추가. pytest 103건 통과. (2026-06-05)
- [x] **T-019**: 채널·재생목록 harvest 오케스트레이션 보강 — `pipeline.run_harvest`가 `seed_keyword`/`channel_id`/`playlist_id` 입력을 모두 처리하고, channel은 `channels.list`로 uploads playlist를 찾아 `playlistItems.list`로 video_id를 수집하며, playlist는 직접 `playlistItems.list`를 사용. 모든 target은 기존 `videos.list` 상세 조회, ranking, `ingest_service` 멱등 적재 경로를 재사용하고 `target_type`/`target_id`/`quota_used`/`uploads_playlist_id`를 결과에 기록. scheduler 기본 `harvest` handler도 keyword/channel/playlist를 모두 전달. pytest 93건 통과. (2026-06-05)
- [x] **T-010**: APScheduler 단일 실행자 구현 — `scheduler.worker`: `run_once`가 stale running 작업 재투입/격리 후 FIFO pending 작업을 claim하고 handler를 실행, `execute_run`이 heartbeat/progress/done/failed 상태 전이를 일원화, unknown job과 handler 예외를 failed로 격리, 기본 `harvest` handler를 keyword `pipeline.run_harvest`에 연결. `worker_loop`는 APScheduler interval job(`max_instances=1`, `coalesce=True`)으로 `run_once` 반복 실행. scheduler poll/heartbeat/stale/max retry 환경 변수 추가. channel/playlist harvest 오케스트레이션 갭은 T-019로 분리. pytest 90건 통과. (2026-06-05)
- [x] **T-009**: 대표 프레임 추출 구현 — `frame_extraction`: POI 시작 타임스탬프 파싱(`HH:MM:SS`/`MM:SS`/초)과 5~10초 오프셋 적용, `yt-dlp` 지연 import 기반 직접 스트림 URL 선택, FFmpeg Input Seeking(`-ss`를 `-i` 앞에 배치) JPEG 추출, RustFS `ktc-frames` 저장 및 `media_assets` 기록, `video_place_mappings.frame_asset_id` 연결, 원본 동영상/오디오 bytes를 `ktc-raw-videos`에 무기한 보존하는 helper 구현. pytest 82건 통과. (2026-06-05)
- [x] **T-008**: 지오코딩·역지오코딩 초기 구현 — `geocoding`: Kakao Local 1차/Naver 보조 검증/VWorld 역지오코딩, `pyproj always_xy` 좌표 정규화(미설치 graceful), 429 지수 백오프+지터·Semaphore 동시성 상한, `evaluate_geocode`(단일 매칭/Naver 디스앰비규에이션/후보 과다·실패 시 `needs_review`). `geocode_service`: 매칭 시 좌표 근접 중복 재사용 또는 신규 `travel_places` 생성·VWorld 주소 보강, 실패·모호는 needs_review 유지(자동 확정 금지). `kraddr-geo` 미연계. 최신 VWorld 우선 직접 client 사용 기준은 T-021에서 보강. pytest 72건 통과. (2026-06-05)
- [x] **T-007**: 자막·전사·Gemini POI 추출 구현 — `transcript`(youtube-transcript-api→yt-dlp→faster-whisper provider 체인, 지연 import·executor 격리), `poi_extraction`(Gemini JSON Schema·파싱 실패 재시도, 주입형 llm), `media_store`(RustFS 저장 추상화 + `media_assets` 기록, 무기한 보존), `summarize_service`(자막 RustFS 저장→POI 추출→설명 보정본 저장·원문 보존→`needs_review` 후보 생성). pytest 60건 통과. (2026-06-05)
- [x] **T-006**: 공식 YouTube Data API v3 수집 파이프라인 구현 — `backend/ktc/etl/` 비동기 패키지: `youtube_client`(search/playlistItems/channels/videos.list, 쿼터 누적), `keyword_expansion`(주입형 Gemini generator + 결정론적 폴백, `season_context`), `ranking`(업로드 최신성·키워드 유사도·참여도 정규화 점수), `ingest_service`(`video_id` 멱등 upsert, 파생 키워드 저장, 채널 워터마크), `pipeline.run_harvest` 오케스트레이션. httpx `MockTransport` 통합 테스트 포함 pytest 45건 통과. 비공식 크롤러 미사용(ADR-11). (2026-06-05)
- [x] **T-005**: SpatiaLite 공간 데이터 모델 구현 — `search_keywords`/`source_targets`/`youtube_videos`/`travel_places`/`extracted_place_candidates`/`video_place_mappings`/`media_assets` 모델, 설명 원문·Gemini 보정/보강 필드 분리, `match_status`·검수 메타데이터, `media_assets` 무기한 보존. `ktc.core.spatial`이 `geom` Point(4326)·R-Tree를 ORM 밖 SpatiaLite DDL로 관리(ADR-17), `place_service` 근접/중복 탐색(bbox+Haversine, PostGIS 대체 가능)·검수 큐 조회, `/api/destinations`·`/api/destinations/unmatched` 연동. pytest 30건 통과. (2026-06-05)
- [x] **T-004**: FastAPI 비동기 백엔드 기반 구축 — `crawl_runs`/`audit_logs`/`system_settings` SQLAlchemy 2.0 모델, `crawl_run_service`(생성·claim·heartbeat·완료·실패·stale 재투입)/`audit_service`/`settings_service` 도메인 서비스, `get_session` 의존성과 lifespan `init_db`, `/api/harvest` 작업 생성·상태 조회 및 `/api/settings` 연동 구현. REST는 작업 생성만 하고 직접 실행하지 않음. pytest 17건 통과. (2026-06-05)
- [x] **T-003**: 소형 프로젝트 기준 스캐폴딩 정비 — `backend/ktc/`(config·database·logging·models·services·api) 구조화, `mcp/`·`scheduler/`·`etl/media.py` 신설, Docker Compose 초안(`frontend`/`api`/`mcp`/`scheduler`/`rustfs`)과 `Dockerfile.python`·`frontend/Dockerfile`, RustFS 버킷 초기화 스크립트, 컴포넌트별 requirements, 프론트 App Router 스캐폴드 작성. `.env.example`과 `Settings` 환경 변수 이름 동기화 완료. (Docker/Playwright 통합 빌드 검증은 T-014로 이관) (2026-06-05)
- [x] **T-018**: RustFS 미디어 저장, 무기한 보존, 매칭 실패 장소 수동 검수, Gemini 설명 보정·보강 필드 요구사항을 개발 계획에 반영. (2026-06-05)
- [x] **T-017**: Google Docs 소형 프로젝트 SpatiaLite 명세 반영 — 공식 YouTube API 중심, SQLite + SpatiaLite, 전면 asyncio, APScheduler 단일 실행자, REST/MCP 분리, 프론트 스택 기준으로 문서 재정렬. (2026-06-05)
- [x] **T-002**: 프로젝트 `docs/` 디렉토리 문서 자산 생성 및 상세 기획서 반영 — `architecture.md`, `decisions.md`, `tasks.md`, `journal.md`, `dev-environment.md` 작성 및 MCP UX 계획 반영 완료. (2026-06-04)
- [x] **T-001**: 프로젝트 루트 문서 자산 생성 — `README.md`, `AGENTS.md`, `CLAUDE.md`, `SKILL.md`, `.env.example` 작성 완료. (2026-06-03)

---

## 사양 참조

- 최신 기준 문서: Google Docs `AI유튜브여행_소형프로젝트_SpatiaLite_명세서`
- 아키텍처 세부: `docs/architecture.md`
- 결정 기록: `docs/decisions.md`
- 작업 일지: `docs/journal.md`
- 개발 환경: `docs/dev-environment.md`

