# JOURNAL — 2026-07 과거 기록

과거 기록 아카이브이며 새 일지는 [현재 일지](../journal.md)에 추가한다.

| 파일 | 기간 | 항목 수 |
| --- | --- | --- |
| [journal-2026-07.md](journal-2026-07.md) | 2026-07-01 ~ 2026-07-24 | 46 |

---

## 2026-07-24: 의존성 업데이트 — maplibre-gl 6, react 19.2.8 패치, python-vworld-api pin 갱신 (PR #213)

- **범위**: 사용자 지시로 `maplibre-gl`/`python-vworld-api`/`react`를 최신으로 업데이트. 로드맵
  작업이 아닌 유지보수성 의존성 업데이트라 별도 T-번호 없이 `codex/deps-maplibre-react-vworld`
  브랜치로 진행했다.
- **변경**: `maplibre-gl` 5.0.0→6.0.0(MAJOR — v6가 ESM-only 배포로 전환되며 default export가
  사라져 `VWorldMap.tsx`의 `import maplibregl, {...}`를 `import * as maplibregl from "maplibre-gl"`
  namespace import로 마이그레이션). `react`/`react-dom` 19.2.7→19.2.8 패치. `python-vworld-api`
  git-archive pin을 최신 main 커밋(a1fea84)으로 갱신 — upstream diff 확인 결과 코드 변경 없음
  (Codex agent/skill 문서만 추가).
- **2렌즈 적대적 리뷰(find→verify, 11 agent)에서 확정 결함 1건 발견·수정**: maplibre-gl 6가
  전이 의존성 `@mapbox/jsonlint-lines-primitives`를 2.0.2→2.0.3로 끌어올렸는데 신버전이
  `engines.node >=22`를 요구했다. 기존 `frontend/Dockerfile`은 `node:20-slim`, `package.json`
  `engines.node`는 `>=20.9.0`로 남아 있어 정합성이 깨졌음을 확인 — 둘 다 Node 22로 올려 해소했다.
- **검증**: frontend lint/type-check/vitest(330/330)/`next build --webpack` 통과, `npm audit`
  신규 취약점 0건(기존 9건과 동일 — next/shadcn 전이 의존성 무관 부채). backend는 새 vworld pin을
  격리 venv에 설치해 `AsyncVworldClient`/`VworldError`/`VworldNoDataError` import와 메서드
  표면이 그대로임을 확인. 공식 Playwright E2E는 세션 중 발생한 개발 머신 디스크 위기(C: 0바이트,
  F: 98% 사용 — 무관한 다른 프로젝트 worktree 수백 개 누적, WSL vhdx 462GB)로 인해 생략하고,
  대신 실제 production build(`next start`)를 로컬 기동해 실 로그인 플로우로 인증한 뒤
  `#vworld-map-container`에 `<canvas>` 1개가 정상 렌더되고 확대/축소·나침반 컨트롤이 동작하며
  maplibre 관련 콘솔 에러가 0건임을 스크린샷으로 확인했다.
- **디스크 위기 대응**: WSL2 Docker 미사용 이미지·볼륨·빌드 캐시, apt/journal 캐시를 정리(약
  7GB 회수)했다. `wsl --manage --set-sparse`는 데이터 손상 경고가 있는 실험 기능이라 보류했고,
  `diskpart compact vdisk`는 관리자 권한이 없어 실행하지 못했다 — 사용자가 직접 관리자 권한으로
  수행해야 한다. F: 드라이브 대부분은 수십 개 프로젝트의 실제 작업 worktree(orphan/backup 표시
  다수)였고, 캐시가 아니라 판단 근거 없이 삭제할 수 없어 손대지 않았다.
- **prod 배포**: PR #213 머지 후 n150 prod에 배포(backend+frontend 모두 재빌드 — UI 소스
  변경 포함).

## 2026-07-14: T-173 — 프레임 비전/OCR 실험 경로 (PR-19, 게이트 off)

- **범위**: `docs/plan-t173-vision-ocr.md`(부록 B 반영본) 기준 Agent A(백엔드) 전용 구현. 미디어
  asset 바이트 서빙·검수 썸네일 UI(Agent B §2.2)는 이번 범위 밖 — 플래그가 off라 서빙 라우트가
  있어도 프레임이 노출되지 않으므로 후속 태스크로 분리했다. 게이트 판정(§1)·G9 post-deploy 지표는
  측정 작업이라 이번 코드에서 제외했다 — 사용자 지시로 **플래그 off 상태로 구현만** 진행한다.
- **대안 비교(§1.5 의무 절차, journal 기록)**: 착수 전 대안(제3안: Gemini URL 분석 승격,
  `video_analysis_service`가 이미 보유한 `url_summary` 경로 재사용)과 비교했다. 비용 측면에서
  본안(프레임 비전 1콜, 영상당 6~8장 inline image)이 URL 분석의 장영상 토큰 폭증(263 tok/s ×
  10~30분 = 26만~47만 토큰, `llm_client.py` 문서 주석)보다 상한이 명확하고, 품질 측면에서
  간판·하드섭 자막·지도 라벨 OCR이 자막 실패 영상의 실질 화면 텍스트를 회수하는 반면 URL 분석은
  이미 T-064에서 시도되고도 낮은 신뢰도로 남아 있던 경로라 새 신호를 더하지 않는다는 판단으로
  본안(PR-19 프레임 비전)을 택했다. 구현량·저장 정책(ADR-15/B4) 긴장은 본안이 더 크므로
  `VISUAL_EXTRACTION_ENABLED` 격리와 B4 승인 게이팅으로 상쇄한다.
- **구현**:
  - 신규 `backend/ktc/etl/visual_extraction.py`: 자막·whisper 최종 실패
    (`transcript_source IS NULL AND transcript_failure_code IS NOT NULL`) + 아직 visual
    후보/프레임 asset이 없는 영상을 대상 선별(`select_visual_targets`, 새 컬럼 없이 기존
    `extracted_place_candidates`/`media_assets`로 idempotent 재선별). `frame_extraction`
    인프라(스트림 URL 1회 확보 + FFmpeg input seeking, 다운로드 없음)를 재사용해 균등 간격
    프레임(`compute_frame_timestamps`, 앞뒤 5% 트림)을 추출·RustFS 저장하고, `generate_multimodal`
    **영상당 정확히 1콜**(N장 inline_data + 프롬프트 1개, `VISUAL_FRAME_MAX`로 clip)로 화면 텍스트
    OCR + 장소명 후보를 뽑는다. 진입점 `run_visual_extraction`이 **플래그 확인이 첫 동작**이고
    (off면 스트림 취득·비전 호출·프레임 저장 전부 미수행, 로그 1줄만), 그다음 DeepSeek 엔진
    가드(`generate_multimodal`은 Gemini 전용이라 DeepSeek에서 `ValueError`를 던진다 —
    `llm_client.py` 문서·`video_analysis_service.make_youtube_url_llm`과 동일 제약)를 확인해
    엔진이 Gemini가 아니면 no-op한다(부록 B 안전 가드 ①).
  - `batch_poi_service.py` refactor: 후보 dedup·grounding·evidence·dirty outbox 조립 로직을
    `_persist_candidates` 공용 헬퍼로 추출해 description(inline, `process_video_batch`)과
    visual(신규 job)이 공유한다. **부록 B 안전 가드 ②**: 이 헬퍼가 source_kind==VISUAL이면
    `grounding.evaluate_transcript_grounding` 호출 자체를 건너뛰고
    `GroundingStatus.NOT_APPLICABLE`로 고정한다 — OCR 텍스트를 transcript raw segment 대조로
    잘못 missing/unverified 판정하는 것을 막는다. description/transcript 경로의 grounding 평가는
    무회귀(회귀 테스트로 pin).
  - `geocode_service.py` **핵심 수리**: 자동확정 recall 예외를
    `if candidate.source_kind == EvidenceSourceKind.DESCRIPTION.value:` 단일 조건에서
    `_RECALL_SOURCE_KINDS = {DESCRIPTION, VISUAL}` 집합 조건으로 일반화했다. 이 예외가 없으면
    VISUAL 후보는 grounding 게이트(`_grounding_blocks_autoconfirm`, transcript 전용이라 VISUAL을
    막지 않는다)를 그대로 통과해 자동확정·export까지 흐를 수 있었다(치명 리스크, 회귀 테스트로
    못박음). review_note는 국내 확정 시 `"visual_only"`(미확인 시 기존과 동일하게
    `"domestic_unverified"`)로 세팅한다. `_prepare_reverse_vworld`의 조기 종료 조건도 같은
    recall 집합으로 일반화해 VISUAL 후보에서 불필요한 reverse geocoding HTTP를 막는다.
  - `llm_client.py` 비용 가드: `_estimate_gemini_tokens`에 `inline_data`(정지 이미지) 전용
    저-가산 상수(`INLINE_IMAGE_TOKEN_ESTIMATE=1,300`)를 추가했다. 기존
    `MULTIMODAL_MEDIA_TOKEN_SURCHARGE`(65,536)는 `file_data`(스트리밍 영상) 하한 추정이라
    정지 이미지에 그대로 적용하면 8프레임 비전 1콜이 524,288 토큰을 예약해 무료 티어
    TPM(250k)을 구조적으로 초과한다(부록 B 비용 리스크). `file_data` 소비자(URL 분석)는 영향 없음.
  - `config.py`/`.env.example`: `VISUAL_EXTRACTION_ENABLED`(기본 **false**),
    `VISUAL_FRAME_COUNT_DEFAULT`(계획서 8 대신 **6**, 비용 가드 반영), `VISUAL_FRAME_MAX`(8),
    `VISUAL_MIN_DURATION_SECONDS`(60) 추가.
  - `scheduler/worker.py`: `visual_extraction` job type 등록. `crawl_run_service.create_run`
    기본 lane이 이미 `LANE_BATCH`라 별도 override 없이 whisper 수동 재전사와 동일하게 대화형
    레인을 잠식하지 않는다. handler는 payload를 풀어 `visual_extraction.run_visual_extraction`에
    그대로 위임하는 얇은 wrapper다(플래그·엔진 가드는 그 함수 진입부가 소유).
- **마이그레이션 결정**: **불필요**. source_kind='visual'·AssetType.FRAME 모두 String 컬럼의
  기존 python enum 값이라 DDL 변경이 없고, 대상 재선별 idempotency는 새 컬럼 없이 기존
  `extracted_place_candidates`(source_kind=visual)/`media_assets`(asset_type=frame) EXISTS
  체크로 구현했다. Alembic head는 변경 전후 동일하게 `20260714_0028` 단일 head를 유지한다
  (`test_migration_graph.py` 통과로 확인).
- **테스트**: 신규 `backend/tests/test_etl_visual_extraction.py` 12건 — 프레임 샘플링(균등
  간격·경계 트림·짧은 영상 스킵·이미 시도된 영상 재선별 제외), **후보 격리(자동확정 차단)
  회귀 핵심**(geocode_service의 VISUAL recall 예외가 없으면 실패하도록 pin), **플래그 off
  완전 무개입**(stream resolver·vision caller·store_and_record 호출 0회, 후보·media_asset
  0건), **DeepSeek 엔진 가드**(`generate_multimodal` 미호출), **비전 1콜 상한**(프레임 6장 시
  parts=7, N>MAX면 8로 clip), **evidence 보존**(frames[].asset_id·timestamp_seconds 실제 저장
  asset과 일치), **grounding_status=not_applicable**(VISUAL은 `evaluate_transcript_grounding`
  미호출, description/transcript는 그대로 호출되는 무회귀 확인), **dedup 비대칭**(transcript가
  미검수 visual 후보를 supersede).
- **검증**: 로컬 disposable PostgreSQL/PostGIS DB(`kor_travel_concierge_test_t173`)에서 신규
  12건 + 기존 관련 파일(batch_poi_service·description path·geocode·frame_extraction 등) 포함
  타깃 111건, backend 전체 pytest **804건 전부 통과**(3개 chunk로 분할 실행 — Windows 호스트
  10분 tool timeout 제약 때문이며 실패 0건, chunk 간 상태 공유 없음), 변경 Python 8개 파일
  Ruff clean, `alembic heads`가 변경 전후 동일한 단일 head(`20260714_0028`)임을 확인(마이그레이션
  미추가 결정과 정합).

---

## 2026-07-14: T-172 — 자막 fetch 병렬화 (PR-24)

- **범위**: poi_batch 1단계 **자막 캡션 fetch만** 병렬화. 교정·POI 배치 추출·지오코딩(2~4단계)은 순차
  불변(LLM은 T-161 게이트웨이 리미터 소관). 게이트(§1 판정·§6 G8 측정)는 배포 후 관측이라 이번 코드에서 제외 —
  사용자 지시로 미측정 상태에서 구현만 진행.
- **구현**:
  - `transcript.py`: 캡션 전용 진입점 신설 — `CAPTION_PROVIDERS` 상수(transcript_api+ytdlp, whisper 제외),
    `caption_provider_chain()`(설정 순서 존중·whisper만 배제·비면 폴백), `async fetch_captions_async(video_id)`
    (순수 네트워크 I/O, DB 세션 미접근), `async transcribe_whisper_async(video_id, *, force, model_size)`
    (whisper 단건 얇은 래퍼), `merge_outcomes(caption, whisper_attempt)`(sequence 재부여 이어붙임 + whisper
    성공 시 result 승격 → `success_provider`/`failure_code` 파생과 `transcript_attempts` 형태를 순차 체인과
    **동일**하게 유지 = 무회귀 핵심).
  - **whisper 예외 격리(2렌즈 리뷰 Finding-1)**: `transcribe_whisper_async`가 `to_thread` 밖으로 튀는
    예외를 삼켜 분류된 whisper 실패 attempt로 변환하고 **절대 re-raise 하지 않는다**(구 순차 체인
    `_run_provider`의 예외 분기와 동일 `_classify_exception` 매핑 — 공용 `whisper_failure_attempt()` 헬퍼로
    단일화). Phase 1b도 임의 주입 fetcher가 raise해도 caption Phase 1a와 동일하게 per-video 격리한다.
    이로써 병렬화 후에도 whisper 예외 하나가 poi_batch 전체를 죽이지 않고 description-fallback으로 이어진다.
  - `postprocess_service.py`: poi_batch용 `_default_caption_fetcher`/`_default_whisper_fetcher`(auto,
    `force=False`) 배선. `_whisper_forced_transcript_fetcher`는 **이름 유지**하되 semantics를 whisper 단건
    (`TranscriptAttempt` 반환)으로 변경(force_whisper 경로 전용). harvest 후처리용 `_default_transcript_fetcher`
    (캡션+whisper 순차)는 불변.
  - `batch_poi_service.process_video_batch`: 단일 `transcript_fetcher` → `caption_fetcher: CaptionFetcher|None`
    (None=캡션 skip=force_whisper) + `whisper_fetcher: WhisperFetcher|None`로 교체(하위호환 shim 없음). 1단계
    루프를 **Phase 0(순차 캐시 판정)** → **Phase 1a(병렬 캡션, `asyncio.Semaphore(CRAWL_MAX_CONCURRENT_VIDEOS)`
    + `gather(return_exceptions=True)`)** → **Phase 1b(whisper 순차, `WHISPER_MAX_CONCURRENT=1` 모듈 상수,
    gather 금지)** → **Phase 1c(순차·공유 세션: attempt 기록·ORM·RustFS 저장·LLM 교정)**로 3분할. 결과는
    `dict[video_id→outcome]`에 담아 **원본 videos 순서**로 소비(alias `video_{index:03d}`가 gather 완료 순서에
    묶이지 않도록). 각 task의 monotonic elapsed를 캡처해 `transcript_fetch` stage 이벤트에 실측 소요로 보고
    (병렬 대기시간 오염 방지 — `_report_stage`에 `elapsed_ms` 직접 주입 경로 추가).
  - `scheduler/worker.py`: `poi_batch_handler`가 단일 fetcher 대신 caption+whisper 2개 주입. force_whisper는
    `caption_fetcher=None` + `_whisper_forced_transcript_fetcher(model)`.
  - `config.py`: `CRAWL_MAX_CONCURRENT_VIDEOS` 소생·기본값 4→3(yt-dlp 동시 다연발 IP 스로틀 완화),
    사문화 설정 `HTTP_MAX_CONCURRENT_REQUESTS` 삭제(참조 0회 확인). `.env.example`·`docs/dev-environment.md`
    동기화. whisper 동시성은 신설 설정 없이 모듈 상수 고정.
- **세션 비공유·입력 순서 불변**(최고위험 회귀 방어): Phase 1a/1b는 공유 `session`·`media_store.store_and_record`·
  ORM flush·`record_stage_event`·`attempt_recorder`를 절대 호출하지 않는다(전부 1c). 후보 alias/dedup은 원본
  순서 소비로 gather 완료 순서와 무관.
- **테스트**: 기존 콜사이트 갱신(`test_etl_batch_poi_service.py`·`test_etl_description_path.py` 새 시그니처,
  `test_transcript_attempts.py`·`test_crawl_run_stage_events.py` caption/whisper 분리 배선,
  `test_whisper_force.py` whisper 단건 semantics). 신규 `test_transcript_fetch_parallel.py` 8건: 캡션 동시성
  상한 가드(1<peak≤3), whisper 동시성 1(auto+force_whisper), 세션 비공유(fetch 전부 → store_and_record),
  사유코드 분포 병렬==순차 baseline(Semaphore=1), 출력 등가성 golden(이름·순서·evidence·grounding), 벽시계
  단축(loose), stage 이벤트 영상당 1건.
- **검증**: 격리 disposable Postgres DB에서 타깃 6파일 53 passed, backend 전체 pytest 통과(신규 8건 포함),
  변경 `.py` 전부 Ruff clean. E2E는 자막 fetch 미경유라 영향 없음.

- **문제**: 작업 표면이 `/status` 작업 테이블·`/collect` 진행 패널·`/jobs/[id]` 상세에 흩어지고, `/collect`에
  죽은 `detailRun` 상태가 남아 있었다.
- **구현(통합·축소, 신규 화면 남발 아님)**: **`/jobs` 인덱스 신설**(`JobsDashboard`) — 상단 진행 중·대기 큐
  (T-181 `['run-queue']` 재사용), 하단 이력 테이블(T-177 `listRunsPage` cursor pagination·`total` 재사용) +
  상태·유형·attention 필터 + 더 보기, 행 액션은 상세+`RunActionButtons`(PR-03) 재사용. `jobs-history.ts`는
  UI filter→`/runs` params 매핑만(`user_jobs_only⊕job_types` 상호배제 존중, 계약 **재구현 없음**). **nav 재편**
  (AppShell): 주 그룹 결과·수집·검수·**작업**·설정 / 보조 상태·API, `/jobs` 하이라이트(`nav.ts`), `JobStatusLink`·
  attention 배지 → `/jobs`·`/jobs?attention=open`. **`/status` 축소**: 작업 테이블/탭 제거(→/jobs), 운영 요약·
  저장소·검수 후보·감사/로그인 유지, 검수 후보 MetricCard→`/review`. **`/collect` 축소**: 죽은 `detailRun`·로컬
  액션·mutation 제거, 진행=1줄 요약+`/jobs` 링크. **홈 배너**(`HomeActionBanner`): 검수 대기 N(unmatched
  total·limit=1)→검수 시작, `open_attention_count>0`이면 확인 필요 K→`/jobs?attention=open`. 대시보드 전면
  개편·`/`→`/places` 이동 없음.
- **적대적 리뷰(PR 전, 2렌즈) — 확정 BLOCKER/MAJOR 0**: 계약 재사용 정확(상호배제·terminal/attention/state
  매핑·cursor/total·RunActionButtons 재사용), IA 축소 기능 유실 없음(중지/재시작 /jobs 완전 이관·죽은 코드
  잔존 0·배너 count 정본·nav 활성 판정·모바일 도달), E2E heading/nav 정합. known-MINOR(문서화·후속): ①
  state 드롭다운+attention 대조 조합(예: 완료+확인필요만)이 무음 빈 이력(UX 엣지·정확성 아님), ② 구 /status
  `runs_by_state` 집계 뷰가 /jobs로 재이관 안 됨(상태는 /jobs 필터·행으로 확인 가능·backend는 여전히 반환→
  재노출 용이), ③ /status 실행 큐 MetricCard 텍스트 E2E 어서션 축소(근저 count는 JobStatusLink aria-label로 유지).
- **금지 준수**: `/runs` 필터·pagination·total·run-queue·attention·failed_recent 재추가 없음(소비만), backend
  `routes.py` 무변경, 자동 승인·다이얼로그 증설 없음, 대시보드 전면 개편 없음.
- **검증**: frontend vitest **330 passed**(신규 jobs-history·nav·home-banner), lint/type-check/build green,
  backend 무변경(migration 없음). E2E heading/nav 어서션 전수 갱신 후 n150 이연. origin/main(#209) 0 behind.

## 2026-07-14: T-187 — 검수 키보드 단축키 + 처리 모드(triage) + provenance facet (U5/U1)

- **게이트**: PR-16은 건당 인터랙션 측정 게이트(모호 시 본안 채택). 라이브 측정 없음 → 모호 → **본안(처리 모드)
  채택**. 단축키 + triage 모드 모두 구현.
- **구현(T-186 분해 컴포넌트 위 배선)**: `useReviewKeyboard.ts` 전역 keydown — J/K 다음·이전(pickCandidate),
  1~9 검색 hit(**선택 가능 hit 기준 번호**, 행 배지·aria-keyshortcuts), Enter 저장(canSave), X 제외, U 마지막
  undo(T-184), / 검색 포커스, ? 도움말. **확장 포커스 가드**(defaultPrevented·repeat·ctrl/meta/alt·IME
  isComposing/229·input/textarea/select/contenteditable·button/a·role=dialog/menu/listbox/option/textbox/
  combobox/searchbox/menuitem/alertdialog·컨테이너). **triage 모드**(URL `?mode=triage|table`, 기본 triage) —
  mode는 뷰 concern이라 ReviewListState/scopeKey/candidates 쿼리키와 분리(모드 전환이 큐 재조회·선택 초기화
  안 함). 진행 레일(n/m·남은 수·최근 처리+undo) + 중앙 후보 카드(T-186 컴포넌트 재사용) + 지도. table=기존
  테이블/필터/bulk(T-185). 저장·제외 후 자동 다음(PR-02/T-179)·debounce·abort·generation·undo·bulk·URL 정본
  **배선만 재사용**. **서버 facet**: `list_review_source_facets` + `GET /destinations/review-facets`(admin,
  read-scope 미포함) — 후보 provenance(channel/playlist/keyword)별 count, **확정 장소 없는 출처도 노출**,
  현재 filter 반영. 기존 결과보기 `/destinations/facets`(place 기반) 보존. n/m·"모두 처리"는 T-182 filtered
  total.
- **적대적 리뷰(PR 전, 2렌즈) — 확정 BLOCKER/MAJOR 0**: 단축키 서수/배지 정합·Enter/X/U 게이트·triage 무재조회·
  facet count(목록 total과 동일 base stmt·distinct·no-place 노출)·auth 경계(admin) 검증. MINOR 3 정리 —
  ① 1~9 배지/키보드/지도 번호를 **선택 가능 hit 단일 정본**(`searchHitNumber.ts`)으로 통일(좌표 없는 행 배지
  없음), ② 포커스 가드 role allowlist에 listbox/option/alertdialog 보강, ③ 그룹값 라벨 facet lookup 실패 시
  raw 값 fallback(공백 방지).
- **금지 준수**: T-186 동작 계약·table·bulk 보존(재사용·배선만), 자동 승인 없음, migration 없음(facet 쿼리 전용).
- **검증**: backend pytest 782 passed(실패 0, 신규 `test_review_source_facets` 3건), frontend vitest 314 passed
  (신규 useReviewKeyboard·searchHitNumber·reviewGroupFacets·review-list-state·api facet 스펙), lint/type-check/
  build green. E2E는 기존 스펙 `?mode=table` 배선 + triage/단축키 시나리오 추가 후 n150 이연. origin/main(#208) 0 behind.

## 2026-07-14: T-186 — review 페이지 구조 분해 (S8, 동작 보존)

- **문제**: `frontend/src/app/review/page.tsx`가 단일 컴포넌트 **5065줄**로 선택/URL/딥링크/큐/mutation/undo/
  bulk/검색/폼 상태가 refs·generation·epoch로 촘촘히 얽혀 후속 검수 작업의 수정 단가가 컸다.
- **경위(codex 완전판 인수)**: 착수 시 codex(Agent B)가 main 워크트리에서 **동일 태스크의 더 완전한 분해**를
  미커밋 진행 중임을 발견(page.tsx 19줄 조립 전용, 전 컴포넌트 추출). 병렬로 만든 부분 분해 대신 **사용자
  결정으로 codex 완전판을 인수** — 그 스냅샷을 현행 main(review 파일이 codex base와 동일) 위로 clean 적용,
  frontend gate로 완전성 검증 후 채택했다.
- **구현(동작 보존 리팩터·UX 무변경)**: page.tsx **5065→19줄**(Suspense→`<ReviewWorkspace/>`). 상태 소유 분해 —
  `components/review/useReviewQueue`(큐·필터·선택·mutation·undo·URL 정본)·`useCandidateSearch`(provider·opinion
  검색 reducer·300ms debounce·abort·generation/searchNonce)·`ConfirmForm`(확정 폼)·`CandidateTable`·
  `SearchResultsPanel`·`types`·`ReviewWorkspace`(조립 루트). `lib/transcript.ts`로 cleanTranscript·근거
  스크롤 공용 유틸 추출(CandidateDetailView·PlaceDetailView 중복 제거). startTransition은 후보 강조·폼
  초기화(urgent) 뒤 **provider query 활성화만** 분리하는 경계로 신설(로드맵 요구).
- **적대적 리뷰(PR 전, 2렌즈) — 확정 BLOCKER/MAJOR 0**: 원본 5065줄 page.tsx와 신규 추출을 line-level 대조 —
  6개 동작 계약(300ms debounce·abort·generation 동일검색 재실행·후보 강조 urgent/provider transition·자동 다음
  후보 T-179·undo T-184·bulk T-185·URL 단일 정본/딥링크·removed provider 0회) **전부 보존** 확인. mutation
  scope fencing(candidatesKeyRef·queueScopeRef·epoch)도 원본과 동일 지점. codex 신규 테스트 1건의 기대값 오류
  (Google 저장 정책 제외를 미반영) 1줄 정정(`isPlaceHitStorageAllowed`가 provider!=="google" 제외 — 원본
  allHits와 정합). known-MINOR(문서화·미수정): hook effect 배선(startTransition/debounce useEffect) 단위
  테스트 부재(repo가 jsdom/RTL 미사용·순수함수 테스트 관례 → E2E n150이 정본 가드), React Query 후보 전환
  시 캐시 엔트리 누적(gcTime GC로 유한, 회귀 아님).
- **검증**: frontend **lint·type-check·build green**, **vitest 256/256**(신규 useCandidateSearch·transcript
  스위트 포함). E2E는 n150 회귀로 이연(로컬은 vitest+build 가드). backend 무변경. origin/main(#207) 0 behind.

## 2026-07-14: T-190 — themes 공급 API 마감 (A3)

- **문제**: `/themes/places`·`/themes/video/{id}/places`가 `limit=None` 전량 반환이고 `source_videos`를
  상시 포함해 무거웠다. `/themes` 목록 envelope는 T-177에서 완료.
- **구현**: 두 엔드포인트를 **PR-32 공통 envelope**(items/next_cursor/has_more/total/newest_id/newer_than)로
  전환 — cursor·limit(기본 200·상한 500)은 T-188 `list_place_summaries_page`(sort=mention_count)를 **재사용**.
  동영상 테마 `sufficient` 게이트(전체수 `page.total >= 5`)와 미공개 사유(빈 items + sufficient/min_required/
  poi_count, next_cursor/has_more 숨김) 보존(ADR-35). `source_videos` **기본 제외 + `include=sources` opt-in**.
  `docs/themes-api.md`(엔드포인트 3종·파라미터·게이트·envelope·예시·마이그레이션 노트) 신설, frontend
  `/api-test` 갱신. **파괴적 변경**(places→items·source_videos 기본 제거)이나 **외부 소비자 0**(kor-travel-map은
  `/features/*`만, 테마는 /api-test만) — "지금이 마지막 기회" 근거로 문서화.
- **적대적 리뷰(PR 전, 2렌즈) — 확정 BLOCKER/MAJOR 0**: envelope·cursor round-trip·sufficient 게이트 무회귀·
  source_videos opt-in 누출 없음·파괴적 변경 안전·T-188 재사용 정합 검증. MINOR 3 정리 — `wants_sources`
  대소문자 무시(`include.lower()`), themes-api.md 산문의 min_required/sufficient top-level 정정, video 게이트
  docstring 정확화(동일 snapshot 하 일관·동시 삭제 시 graceful degradation).
- **금지 준수**: `/themes` 목록(T-177)·`list_place_summaries`/`_page`(T-188)·feature export(T-189)·sufficient
  게이트 미변경(재사용만), migration 없음.
- **검증**: 격리 disposable DB backend 전체 pytest ~779 passed(실패 0), theme+pagination 23 passed, frontend
  lint/type-check/build 통과, 단일 head, origin/main(#206) 0 behind.

## 2026-07-14: T-189 — features 계약 마감 (A5, G10)

- **문제**: feature export payload의 address 행정코드(`sido_code`/`sigungu_code`/`legal_dong_code`)가 하드코딩
  None이고, `/features/*` 목록에 response_model이 없어 OpenAPI 스키마가 비었으며, 미검증 좌표가 GPX export로
  유출될 수 있었다.
- **구현(additive 마감)**: `_build_payload`에서 `sigungu_code`·`legal_dong_code`를 place 실데이터 주입,
  `sido_code`는 전용 컬럼이 없어 `sigungu_code[:2]`(없으면 `legal_dong_code[:2]`, 둘 다 없으면 None) 유도
  규칙으로 계약화(스키마 변경 없음). `schema_version=1`을 payload 본문 top-level로(hash 반영 → 배포 후 전 item
  재발행). `/features/snapshot`·`changes`에 `FeatureExportPageResponse` response_model — item은 `extra=allow`
  개방형이라 place/youtube/evidence/source_record 등 기존 필드가 응답에서 탈락하지 않는다. cursor 오류를
  `InvalidCursorError`로 분리해 routes가 한국어 detail을 `{code,message}`(invalid_cursor·invalid_params)로 감싼다.
  `/destinations/export`에 `geocoded_only: bool | None` — 미지정 시 **포맷 기반**(gpx/kml=True 미검증 좌표 제외,
  xlsx=False 전체 포함), 명시 true/false는 포맷 무관 존중.
- **재발행**: 행정코드·schema_version 주입으로 전 payload_hash가 바뀐다 → T-171 dirty outbox + 시간당 전량
  reconcile 안전망이 최대 1h 내 전 item을 새 sequence로 재발행. cursor·operation·sequence 계약 불변이라
  krtour-map은 재수신만 하면 되고 cursor는 계속 유효. canary/cursor-drain/rollback·저트래픽 배포 권고는
  `docs/feature-export-api.md`에 문서화(코드 canary 미구현).
- **적대적 리뷰(PR 전, 2렌즈) — 확정 BLOCKER/MAJOR 0**: additive 비파괴(response_model extra=allow·operation/
  cursor/sequence 불변), sido 유도 정확성, geocoded_only push down, 재발행 reconcile 실효 검증. 병합 전 보강 —
  ① `geocoded_only` 기본값을 **포맷 기반**으로(리뷰가 xlsx 강제 True의 조용한 확정-미지오코딩 행 탈락을 지적 →
  gpx/kml만 True, xlsx는 False), ② `sido_code` legal_dong fallback(sigungu 없고 legal_dong만 있는 place 회복),
  ③ schema_version이 payload_hash에 실제 반영됨을 강제하는 단위 테스트. known-MINOR(문서화): 에러 body
  string→object(로드맵 요구·정상 소비자 미도달), 배포 시 전량 reconcile이 advisory lock을 잡아 GET 잠깐 대기
  (저트래픽 배포 권고), 재발행의 reconcile 활성 의존.
- **금지 준수**: 응답 additive만(새 필드·code), operation/base64 cursor/sequence 불변, 자동확정·grounding·T-171
  outbox/reconcile 로직 미변경, 테마 엔드포인트(T-190)·place_service 목록(T-188) 미변경. migration 없음.
- **검증**: 격리 disposable DB backend 전체 pytest 774 passed(실패 0), 신규 테스트(schema_version hash·sido
  legal_dong 유도·geocoded_only 포맷 기본값·재발행 hash), `compileall` clean, T-188 위 rebase 후 origin/main
  (#204) 0 behind.

## 2026-07-14: T-172·T-173 게이트 착수 계획서 작성 (구현 아님)

- **배경**: Agent A 구현 트랙(T-158~T-171) 완료 후 남은 T-172(자막 fetch 병렬화)·T-173(프레임 비전/
  OCR)은 `[게이트]` 태스크로, 실측·정책 승인 없이 착수하면 로드맵의 게이트 규율(필수 절차)을 어긴다.
  게이트가 열리는 즉시 다른 에이전트가 그대로 실행할 수 있는 **실행 계획서 + 게이트 판정 SQL**을 미리
  작성했다(구현 코드는 아직 없음).
- **산출물**: `docs/plan-t172-transcript-parallelization.md`, `docs/plan-t173-vision-ocr.md`. 각 문서는
  게이트 판정 기준·**실행 가능한 SQL**(부록 A), 범위·파일 소유(Agent A), 코드 앵커 기반 단계별 구현,
  테스트, 위험·금지·적대적 리뷰 포커스, 2렌즈 검증 반영(부록 B)을 담는다.
- **게이트 판정 요약**: T-172 = 실운영 poi_batch에서 `transcript_fetch` 단계 합이 `poi_batch_total`
  벽시계의 ≥30%(T-162 `crawl_run_stage_events` 집계, 표본 ≥20배치·2주+). T-173 = 2주 지표 "유효 원료
  전무 영상 비율" >20% ∧ B4(PR-29 provider 정책) 승인 ∧ T-158·T-161 선행(`transcript_attempts`·
  `youtube_videos.transcript_source/failure_code`·후보 테이블 집계), 착수 시 Gemini URL 분석 승격안과
  비용·품질 비교표를 journal에 기록.
- **작성 방식**: 워크플로(draft 2 + verify 2, 실코드 대조)로 계획을 코드 앵커에 근거해 작성·검증.
  검증 정정 반영 — T-172(partial): 재배선이 깨는 테스트(`test_transcript_attempts.py`·`test_whisper_
  force.py`) 범위 추가, `_whisper_forced_transcript_fetcher` 개명 여부 확정, whisper 단일-provider 체인
  표현 정정. T-173(accurate): route 핸들러 `list_unmatched_candidates` 명명 정정, **VISUAL 후보는
  `grounding_status=not_applicable`**(transcript grounding 오판 방지), **DeepSeek 엔진에서 `generate_
  multimodal` ValueError → 엔진 가드로 no-op**(안전).
- **미구현·게이트 유지**: 두 태스크는 게이트 판정 전까지 착수하지 않는다. 이 항목은 계획 산출물 기록일
  뿐 T-172/T-173 완료가 아니다.
## 2026-07-14: T-188 — /destinations SQL 푸시다운 (S5, G8)

- **문제**: `/destinations` 목록 `list_place_summaries`가 확정 장소·mention을 Python으로 **전량** 로드·
  집계·정렬한 뒤 잘라 O(전체). `_list_mentions_by_place`가 limit **전** 전량 join을 로드하는 게 최대 비용.
- **구현(SQL 푸시다운)**: 필터(category/q/district)를 WHERE(category coalesce 동치·q=`strpos(lower(concat_ws(
  ...)))`·district=주소 앞2토큰 regexp)로, `mention_count=count(distinct video_id)`·`source_channel_count=
  count(distinct channel_id)`(inner join youtube_videos)를 group-by 서브쿼리로, 정렬 4종·LIMIT을 SQL로. 문자열
  비교는 **`COLLATE "C"`**(UTF-8 바이트순=Python 코드포인트순)로 Python 정렬과 일치, 모든 정렬은 place_id(PK)
  최종 tiebreak로 전순서. **`_list_mentions_by_place`를 정렬·LIMIT 후 페이지 대상 place만 IN 단일 쿼리로 이동**
  (핵심 이득·N+1 아님). `list_place_summaries_page`(cursor·watermark(MAX)·total·newer_than·keyset OR-chain)도
  SQL화, cursor scope `destinations-python-v1`→`destinations-sql-v2`. 시그니처·반환형(PlaceSummary·source_videos)
  불변, `limit=None` 전량 경로(theme_service 2곳)·place_ids·video_id 보존. 유지된 Python 정본(`_place_matches_
  result_filters`·`_list_mentions_by_place`·`_place_summary_sort_key`)을 golden 오라클로 씀.
- **EXPLAIN(ANALYZE,BUFFERS)** (시드 장소 3,000·mapping 34,867·영상 1,500): 기본 latest 페이지 = Index Scan
  Backward pkey + Limit **101행 0.085ms**(O(limit)); 페이지 mentions 전송 **34,867→1,107행(~31×↓)**; 장소
  hydration **3,000→101(~30×↓)**; total count 0.49ms; snapshot MAX 0.078ms. mention_count 정렬만 전역 랭킹이라
  GroupAggregate(65.9ms)이나 DB측 정수 집계로 옮기고 전송은 101행. **migration 없음**(인덱스 불필요·단일 head).
- **적대적 리뷰(PR 전, 2렌즈) — 확정 BLOCKER/MAJOR 0**: golden SQL-vs-Python 동치(COLLATE·keyset 음수튜플
  복원·집계 inner join·watermark/total/newer_than·limit=None·post-limit mentions 재조회·필터 coalesce/nullif
  전부 검증), bind 파라미터(injection 없음), REPEATABLE READ 단일 스냅샷, source_videos 보류 정당성 확인.
  known-MINOR(한국어/ASCII 도메인 무해·문서화만): ① district regexp `\s`가 비-ASCII 공백(NBSP)에서 Python
  `str.split()`(유니코드 공백)과 갈릴 수 있음(지오코더 정규화 주소라 저확률), ② `lower()` 비-ASCII 케이스폴딩
  로케일 차이(COLLATE "C"는 정렬 비교에만·lower ctype엔 미적용), ③ mention_count 정렬 전량 GroupAggregate(수용
  트레이드오프·구 Python-load 대비 개선·대규모 전환 시 인덱스 재검토 인지). 국제 주소로 도메인이 바뀌면 ①②
  재검토.
- **범위 경계**: source_videos 목록 payload 배열 제거는 보류(선배포=상세가 서빙 확인까지만). frontend
  (`DestinationWorkspace`·`lib/api.ts`)·frontend cursor 에러 리셋은 Agent B 영역이고 거의 모든 미머지 codex
  브랜치와 경합해 미변경(응답 스키마 불변).
- **검증**: 격리 disposable DB backend 전체 pytest 737 passed(실패 0), golden 매트릭스(정렬4×필터16×limit·
  place_ids·cursor page·snapshot 격리·구 cursor 거부) 통과, 단일 head, origin/main(#202) 0 behind.
## 2026-07-14: T-185 — 검수 bulk filter snapshot·receipt ledger

- **서버 계약**: 로그인한 same-origin BFF 전용
  `POST /api/v1/destinations/unmatched/bulk/preview|execute`를 추가했다. preview는 명시 선택 최대 500건
  또는 cursor·sort·딥링크를 제외한 canonical filter를 `REPEATABLE READ`에서 고정한다. filter는
  `LIMIT 10001`로 초과를 판별해 최대 10,000건만 허용하며 절대 일부를 잘라 실행하지 않는다.
  operation/item/receipt ledger와 migration `20260714_0028`을 추가하고, 확인 token은 actor·action·scope·
  만료 시각에 결합해 SHA-256 digest만 저장한다.
- **실행·멱등·원자성**: execute는 candidate ID 순서로 최대 100건씩 처리한다. 같은
  `(operation_id, request_id, cursor)`는 저장 receipt를 그대로 재생하고, 소비된 cursor나 request ID
  변조는 409로 거부한다. 최초 실행 전 5분 TTL을 통과하면 이후 chunk는 계속할 수 있다. item savepoint가
  성공·revision/상태 충돌·실패를 분리하며, 후보 mutation·후보별 감사·item 결과·chunk 감사·receipt를
  같은 transaction에서 commit한다. lifecycle→export→candidate 잠금 순서를 유지하고 ignore/delete/reopen의
  기존 장소 정리·RustFS 보존·dirty outbox 계약을 재사용한다.
- **검수 UX**: 불러온 후보의 선택 제외·삭제, removed 후보 선택 복구, 현재 URL filter의
  `is_domestic=false` 후보 전체 제외를 정확한 preview 건수와 확인 dialog로 제공한다. 선택은 500건에서
  멈추고 filter action은 10,000건까지 서버 snapshot을 사용한다. 100건 chunk 진행률, 응답 유실의 동일
  request/cursor 재전송, conflict 자동 재실행 금지, failed ID만 새 selection preview, 0건 취소, 실행 중
  dialog 닫기/재열기와 390×667 focus를 처리한다. 확인 bearer는 메모리에만 존재하며 hard reload 뒤에는
  최신 목록을 다시 확인하도록 안내한다.
- **적대적 검토 1차(backend·상태 머신·성능/모바일 3개 agent)**: 단일 receipt slot의 동시성 결함,
  filter 공백 정규화 편차, timer overflow, 실행 driver 세대 인계, partial 재시도 범위, 701건 실규모와
  hard reload 안내 누락을 찾아 operation별 receipt ledger·canonical filter·분할 timer·driver resume·
  failed-only preview·규모/E2E 테스트로 보강했다.
- **적대적 검토 2차(담당 교차 배치)**: filter A→B settlement가 이전 query key를 갱신할 수 있는 ABA,
  bulk 성공 후보별 감사 누락, schema가 어긋난 HTTP 200을 성공 건수로 표시할 위험, 로드맵의 구 단일
  transaction/500건 계약, lifecycle/export lock 역순을 확인했다. 최신 key ref, 후보 감사 savepoint,
  응답 UUID/token/chunk/total runtime 검증, 문서 정합화, 잠금 순서 통일과 회귀 테스트를 반영했다.
- **적대적 검토 3차와 delta 재감사**: 문서가 요구한 실제 PostgreSQL 10,000/10,001 경계를 축소 상수
  테스트만으로 완료 처리한 증거 공백을 MAJOR로 확인했다. 실제 10,001건을 seed해 10,000건 operation/item
  전체 집합과 10,001건 413·무생성을 검증하고, 첫 item savepoint 실패 뒤 다음 item 성공, source/q mock
  membership, delete execute 정산, action별 filter status 판별 union과 `tsc` 포함 type contract를 보강했다.
  최종 delta 재감사는 BLOCKER 0·MAJOR 0·MINOR 0이었다.
- **n150 검증**: 전용 Docker network·PostGIS·API·UI와 비충돌 host port만 사용했다. Alembic 단일 head와
  `upgrade head → downgrade 20260713_0027 → upgrade head`, T-185 backend 30건, backend 전체 761건,
  변경 Python Ruff를 통과했다. frontend lint·type-check·Vitest 229건·Next.js production build가
  통과했다. Playwright는 격리 backend URL을 명시한 전체 CI 실행에서 기능 44건을 완료했다(41건 즉시,
  기존 T-184 timing 경로 3건 retry, live 전용 4건 skip). 해당 3건은 n150 production build 서버에서
  별도 실행해 재시도 없이 3/3 통과했고, 신규 T-185 경로는 전체 실행에서 모두 첫 시도에 통과했다.

## 2026-07-14: T-171 — feature export durable dirty outbox (S6/A2)

- **문제**: `get_snapshot`/`get_changes`가 매 GET마다 전 후보 `sync_feature_exports`(O(후보수)) 호출 +
  `_read_page`가 `last_exported_at`를 매 GET write-commit. 소비자 폴링 비용이 후보 수에 비례하고 GET이
  상시 쓰기. 원 PR-22의 process-local 스로틀·워터마크·플래그는 API/scheduler 2프로세스·재시작에서 정본
  불가(개정).
- **구현(durable outbox)**: `export_dirty_outbox`(candidate_id BIGINT PK·reason·marked_at, FK ondelete
  CASCADE, migration 0025). `mark_candidates_dirty(session, ids, reason)`=변경과 **같은 트랜잭션**에서
  `on_conflict_do_update` upsert(last-reason-wins). 배선: resolve/reject/reopen·soft_delete(tombstone,
  기존 동기 tombstone 위 이중안전)·apply_geocode(자동확정/needs_review)·merge_places·correct_place·batch
  신규 후보·delete_place(삭제 전 후보 id 수집)·exclude_video(soft_delete 경유). `sync_dirty`가 outbox를
  `DELETE...RETURNING`으로 원자 claim→그 후보만 `_sync_scope`(전량 sync와 **동일** 분류·upsert·후보소멸
  tombstone 로직 공유→golden)→consume(빈 outbox면 쓰기 0). GET은 sync_dirty(순수 읽기), 안전망은 process
  시작 1회 + scheduler 시간당 전량 `sync_feature_exports`(`FEATURE_EXPORT_RECONCILE_ENABLED/INTERVAL`,
  기본 3600s). `_read_page`의 last_exported_at write 제거(소비처 진단뿐 확인). 응답 스키마·base64 cursor·
  operation(upsert/reject/tombstone) 계약 불변.
- **적대적 리뷰(PR 전, 2렌즈) — 확정 결함 1클래스(3지점) 수정**: place의 payload 관련 필드(description·
  gemini_enriched_description·official/road_address·category·category_code_suggestion·detailed_research)를
  바꾸는 mutation이 **그 place에 이미 매칭된 co-후보**를 dirty로 표시하지 않아, 그 후보들의 export가
  payload_hash 변경에도 안전망(≤1h) 전까지 stale → **golden 불변식(dirty sync == full sync) 위반**. ①
  MAJOR `merge_places`: target 필드 backfill 후 moved(source) 후보만 dirty, target co-후보 누락. ②③ MINOR
  `apply_geocode_to_candidate`·`resolve_candidate`: 근접 재사용 place category 채울 때 현재 후보만 dirty.
  → 공용 헬퍼 `mark_place_candidates_dirty(place_id)`(`matched_place_id==place_id AND deleted_at IS NULL`
  후보 전부)를 세 지점 + `correct_place`(기존 인라인 패턴)에 일원화, **실제 필드 변경 시에만**(churn 방지).
  golden 테스트 2건(merge target-resident 후보·resolve 재사용 co-후보 → 병합/확정 직후 전량 sync
  changed==0 fixpoint). 리뷰의 나머지 probe(consume 원자성·트랜잭션 순서·FK cascade·GET 순수읽기)는 결함
  없음 판정.
- **rebase 코디네이션**: 착수 중 origin/main이 T-183(#196)로 전진해 alembic head가 `0023`(down_revision
  0024)이 됨. T-183 위 rebase(무텍스트충돌 auto-merge, geocode/place 배선 지점 함수 단위 검증으로 T-171/
  T-183 양쪽 보존 확인)·migration `0025` down_revision을 `0024`→`0023`으로 reparent(체인 0022→0024→0023→
  0025, 단일 head). T-183가 xmin fencing·개별삭제 needs_review 선행조건을 추가해 golden 테스트의 tombstone
  생성 수단을 장소 삭제로 교체(불변식 불변).
- **금지 준수**: 응답 스키마·payload 불변, 자동확정 게이트(T-165/166)·soft delete tombstone(T-160)·
  grounding export 게이트 로직 불변(outbox 배선만 추가).
- **검증**: 격리 disposable DB backend 전체 pytest 675 passed(실패 0), migration upgrade/downgrade
  round-trip 단일 head, `test_migration_graph` 통과, origin/main(#196) 0 behind.

## 2026-07-13: T-184 — 검수 undo/reopen·제외 목록·참조 기반 장소 생명주기

- **복구 계약**: IGNORED와 soft delete를 합친 `removed` 목록을 추가하고, IGNORED·삭제·MATCHED·
  USER_CORRECTED를 서버 발급 opaque descriptor로 `needs_review`에 복귀시킨다. resolve/delete는
  `expected_revision`, reopen은 candidate/place revision을 확인한다. forward 응답 유실은 요청 전에 만든
  `client_operation_id`와 exact detail의 최신 operation이 같을 때만 성공으로 인정한다. resolve의 operation
  표식은 core/audit commit과 행정구역 보강 뒤 final candidate/place revision에 결합하고, 기대 상태인데
  표식만 아직 없는 finalization 구간은 제한된 backoff 재조회로만 기다린다.
- **장소·미디어 보존**: 장소 origin을 `candidate_created|persistent|legacy_unknown`으로 명시한다.
  후보 생성 장소는 origin 후보의 소유물이 아니라 provenance이며, 어느 후보가 마지막 참조를 끊든
  활성 후보와 mapping이 모두 0일 때만 정리한다. persistent·legacy·공유 장소는 보존하고,
  `MediaAsset`은 장소 링크만 해제하며 RustFS 객체는 삭제하지 않는다. 영상 제외도 reopen과 독립 유지한다.
- **동시성·export**: 후보/장소 모든 UPDATE의 revision을 DB trigger가 소유한다. writer 잠금 순서를
  lifecycle 174→export 175→candidate→place→mapping→asset으로 고정하고, targeted tombstone·후보 전이·
  감사 로그를 한 commit에 묶었다. 빈 feature snapshot/changes도 선행 sync를 commit한다.
- **T-171 통합 재감사**: rebase 뒤 feature payload를 쓰는 경로를 전수 대조했다. reverse address 보강,
  채널/재생목록/영상 metadata upsert, 영상 transcript·URL·reconcile summary, deep research, 설명 보정은
  export advisory lock 뒤 최신 row를 잠그고 실제 공급 필드가 바뀔 때 같은 영상·장소를 공유하는 활성
  후보 전체를 durable dirty로 표시한다. stale identity map·빈 cursor page·co-match 후보를 포함한 golden
  회귀에서 incremental sync 뒤 전량 sync 변경 0건을 요구한다. 외부 LLM 전 read transaction을 닫고
  apply 때 입력 snapshot/revision을 다시 확인하며, 영상 제외·사람 변경이 먼저면 AI 결과를 버린다.
- **영상 분석 owner fence**: analysis run에 parent crawl ID·retry generation·claim token을 별도 migration
  `0027`로 추가했다. parent heartbeat/retry와 token을 `_mark_running`·LLM 실패·성공 apply·stale 재시도
  소진마다 `parent→analysis` 순서로 잠가 검증한다. 이전 attempt는 새 generation의 analysis와 parent
  DONE/FAILED/heartbeat를 바꾸지 않는다. 중복 run은 first canonical 결과 이후 `superseded`로 종결하고,
  실제 입력 drift만 같은 owner가 최대 3회 재시도한다. 사람 review/audit 후보는 reconcile이 상태·메모를
  덮지 않고 AI 의견만 evidence에 보존한다(ADR-41).
- **UX**: 마지막 단건 snackbar는 시간 제한 없이 유지하고 다음 성공이 대체한다. removed 행은 복구와
  상세 확인만 허용하고 외부 장소 provider·AI 의견·VWorld map을 mount하지 않는다. 모바일 상세은
  생성 시각·operation ID가 포함된 descriptor를 5분 동안 목록으로 한 번만 handoff하며, consume-before-
  parse·scope·workflow epoch·modal generation으로 오래되거나 늦은 응답을 막는다.
- **반복 검토**: backend·frontend·동시성·E2E 렌즈로 3회 이상 적대 검토했다. 1차에서 export 늦은
  upsert, create_all trigger 누락, 감사 원자성, lock inversion, 빈 page sync rollback, modal ABA,
  복구 화면 외부 API 호출, response-loss 타인 결과 오인을 찾아 수정했다. 2·3차에서 reconcile stale
  overwrite, batch supersede 경합, merge/export lock 역전, sibling 중복, candidate/place operation ABA,
  DELETE 반사 응답 신뢰, mobile handoff 만료, finalizer 대기 구간을 추가로 찾아 수정했다. T-171 통합
  4차에서는 빈 export cursor write skew, 공유 metadata/요약 dirty 누락, LLM transaction 장기 점유,
  reconcile 사람 판정 덮기, 중복 first-wins 역전, stale parent·child split-brain, RUNNING orphan과 migration
  불변성을 찾아 수정했다. 알려진 transcript 고정 object key의 evidence 재현성 부채는 T-191에 P1
  acceptance로 편입했고, 전역 export lock p95·bounded claim은 T-189에서 n150 수치로 마감한다.
- **n150 최종 검증**: Alembic 단일 head `20260713_0027` clean upgrade와 `0025` downgrade→head
  round-trip, backend 전체 731 passed(환경 설치 여부를 암묵 가정하던 transcript 2건을 명시적 미설치
  격리로 수정하고 advisory lock 관측 timing flake도 10초 deadline으로 고정), 변경 Python Ruff 통과.
  frontend lint·type-check·Vitest 191 passed·production build 통과. Playwright는 fresh DB와 새 서버만 쓰는
  `CI=1` 격리 실행에서 31 passed·live 전용 4 skipped·실패/재시도 0(7.6분). 이 과정에서 신규 place→origin
  candidate FK를 고려하지 않은 E2E seed 삭제 순서, backend에 누락된 E2E admin proxy secret, page append 뒤
  자동 검색 timer 취소 race, 제거 화면 중복 상태 안내를 발견해 수정했다. 자동 검색은 후보·workflow epoch에
  묶인 300ms debounce로 quota 완충과 stale 방지를 함께 보장한다. lifecycle advisory key 174의 정확한 대기와
  `FeatureExport` ledger 생성 후 재시드도 별도 검증했다. 종료 뒤 테스트 포트·컨테이너·DB·임시 wrapper
  잔존 수는 모두 0이다.

## 2026-07-13: T-170 — 지오코딩 provider별 캐시 (S7)

- **문제**: 같은 장소가 여러 영상에 반복 등장하면 VWorld/Kakao/Naver를 매번 재호출(S7). 100m 반경
  재사용은 API 호출 **후** dedup이라 호출 자체는 안 줄인다.
- **핵심 제약(정책 allowlist)**: `docs/provider-policy.md` 매트릭스 정본으로 **캐싱 허용 provider만**
  저장. `PROVIDER_CACHE_POLICY`(감사가능 dict)로 **Kakao만 cacheable**(제5조 반대해석 UX cache 허용+
  최신 유지 의무, positive 14일/negative 1일). **VWorld**(지오코더 가이드 "별도 저장장치/DB 저장 불가",
  실시간)·**Naver NCP Maps**(제7조⑨⑪ 저장 금지 + 사용자 결정 2026-07-13 캐시·저장 제외)·**Naver
  Local Search**(7.3.③ 캐시 포함 금지)·**Google Places**(메인 지오코딩 경로 밖)는 **deny-by-default**
  — lookup·store 모두 no-op, 캐시 코드 미개입.
- **구현**: `geocode_cache`(query_hash PK·provider·response_class·results_json JSONB·created_at,
  migration 0024 down_revision 0022). canonical key `sha256(provider|endpoint|canonical_params|
  NORMALIZATION_VERSION)` — 공통 60일 TTL 철회, 정규화 로직 변경 시 version bump로 key 버스트. 응답
  4분류(success_nonempty|success_empty|transient_error|permanent_error): `raise_for_status`가 429/5xx/4xx를
  classify 이전에 던져 **error는 캐시 안 함**(success만 store), positive(nonempty)/negative(empty, 짧게)
  TTL 분리. lazy 만료(정리 스케줄러 없음 — 로드맵 명시), 캐시 히트도 provider_evidence 동일 형식(계약
  불변, allowed_fields 화이트리스트가 source·result_kind·좌표 등 전 필드 포함), force_refresh 훅. Kakao
  `search_address`/`search_keyword` HTTP 호출만 `run_with_geocode_cache`로 감쌈. 별도 세션 팩토리
  (`session.bind` 파생, 메인 트랜잭션과 분리), `on_conflict_do_update`로 2프로세스 동시 upsert 멱등.
- **적대적 리뷰(PR 전, 2렌즈) — 확정 MAJOR 2**: ① **캐시 best-effort화**(수정): `run_with_geocode_cache`가
  `cache.store`를 try/except 없이 await하고 store 성공 후에만 후보 반환 → store/lookup 예외(pool timeout·
  DB hiccup)가 이미 fetch된 후보를 폐기·전파 → `geocode_service`의 광역 `except Exception: kakao_results=[]`
  가 삼켜 matched(1.0)를 needs_review 'no_result'로 **조용히 강등**(캐시 투명성 불변식 위배) → lookup/store를
  try/except로 감싸 로그 후 진행(lookup 실패=miss 폴백, store 실패=후보 그대로 반환), 캐시 예외가 지오코딩
  결과를 절대 안 바꾸게. 테스트 2건 추가. ② **migration fork**(미수정·문서화): Agent B T-183의 0023도
  0022에서 갈라져 둘 다 머지되면 alembic multiple heads. **origin/main에 0023 미존재**라 0024←0022가 현재
  단일·정확 — 0023으로 재부모화하면 미존재 revision 참조로 즉시 깨짐. fork는 T-183 rebase에서 0023을
  0024 뒤로 재부모화(또는 merge revision)해 해소(Agent B 조정 사안).
- **MINOR(미수정)**: 캐시 무한 성장은 로드맵 설계(lazy 만료·스케줄러 없음), Kakao 14일 stale은 보수적
  트레이드오프(<30일, 만료 시 재fetch).
- **VWorld 캐시 정책 긴장**: 약관 전문 미확보(지오코더 가이드 문면만)로 보수적 캐시 제외. 공공데이터
  라이선스로 완화 여지 있으나 확인 전 단정 안 함 — 전문 확보 시 `PROVIDER_CACHE_POLICY["vworld"].
  cacheable` 한 줄로 재검토 가능하게 구조화.
- **금지 준수**: 캐시 금지 provider 저장 없음(deny-by-default), error를 success로 캐시 안 함, evidence/
  export 형식 불변, 자동확정 게이트(T-165/166)·100m 재사용 미변경.
- **검증**: 격리 disposable DB backend 전체 pytest 596 passed(pre-existing 1건 외 0), 캐시 테스트 24 passed,
  migration upgrade/downgrade round-trip 단일 head, `compileall`·`git diff --check` 통과, origin/main(#199) 0 behind.

- **후속 해소(T-183)**: 병렬 작업에서 예상한 migration fork는 T-183의 `0023`을 T-170의 `0024`
  뒤로 재부모화해 `0022→0024→0023` 단일 chain으로 합쳤다.

## 2026-07-13: T-183 — 검수 서버 검색·정렬·snapshot cursor·URL 상태

- **서버가 소유하는 검수 큐**: `GET /destinations/unmatched`에 후보명·위치 단서의 escaped
  `ILIKE` literal 검색, `oldest|newest`, strict `is_domestic`, `reason`, `source_kind`, `grounding`,
  `needs_review|ignored`를 추가했다. Grounding 5상태는 T-165 enum column을 직접 사용하고 items·`total`·
  `newer_than`·첫 snapshot watermark에 모든 조건을 동일 적용한다. filter fingerprint와 마지막 ID를
  묶은 `unmatched-v4` opaque cursor로 오래된 순은 `id > last_id`, 최신 순은 `id < last_id`를 쓴다.
  목록·상세의 `grounding_status`와 유한 confidence 계약을 맞추고 모든 후보 path ID를 PostgreSQL
  INTEGER 범위로 제한했다.
- **FIFO 검수 UX와 URL 단일 정본**: 화면은 oldest 기본 300건 `useInfiniteQuery`로 append하고,
  60초 `newer_than` probe로 새 후보·다른 사용자 처리에 따른 큐 변화를 알린다. 검색·정렬·국내 여부·
  사유·출처·원문 근거·그룹·상태는 실제 browser URL을 `useSyncExternalStore`로 구독하며 최초 정규화와
  control 변경도 동기 writer 하나만 사용한다. 일반 행 선택은 URL 소음을 만들지 않고 명시적
  `?candidate=`만 page 밖 단건 상세를 유지한다. filter 밖 맥락·필터 해제, 한국어 Grounding filter와
  행 배지를 제공한다.
- **권위 재검증과 ABA 방어**: 성공 시 page/newer 요청을 취소하고 전체 scope에서 처리 ID와 checkbox를
  제거한 뒤 active snapshot을 재검증한다. 실패·응답 유실·409·500은 목록뿐 아니라 단건 상세를 다시
  읽어 404, 다른 검수자가 처리한 상태, 아직 actionable인 상태를 구분한다. A→B→A workflow epoch,
  page 밖 후보, 지연 응답, retained error, cache resurrection에서도 현재 B의 선택을 보존하고 처리된
  A만 정리한다.
- **장소 lifecycle 동시성**: geocode 외부 I/O는 transaction 밖에서 수행하고 후보 `xmin` snapshot을
  필수 fencing token으로 사용한다. 자동/수동 확정·장소 병합/삭제·영상 제외는 lifecycle advisory 뒤
  candidate→place→mapping→asset ID 순으로 잠근다. commit 뒤 후보·장소·매핑을 다시 읽어 응답하며,
  장소 제거 시 `MediaAsset.place_id`만 해제하고 RustFS 객체와 asset 행은 삭제하지 않는다. T-168
  description 후보의 forward 지오코딩 evidence는 유지하되 reverse VWorld 선호출과 자동확정은 막고,
  T-169 강제 Whisper의 batch lane·model·duration 계약도 재배치 뒤 보존했다.
- **MCP 멱등·감사 원자성**: `audit_logs`에 멱등 key/state 전용 column, pair CHECK, actor/action/key
  partial unique index를 추가했다(Alembic `0022→0024→0023` 단일 chain). 손상 legacy JSON·중복 최신 행을 안전 backfill하고
  pending이 있으면 downgrade를 중단한다. 외부 admin 보강은 pending owner/lease 인계와 전후 fencing을
  거쳐 최신 도메인 snapshot과 final을 같은 transaction에 확정한다. auto-match audit은 `FOR UPDATE`
  아래 `pending`에서 한 번만 전이하고 후보 판정과 감사 INSERT를 원자 commit/rollback한다.
- **반복 적대 검토·n150 검증**: backend/UX/cache-race/migration/E2E 렌즈로 2회 이상 반복 검토하며
  상세 Grounding 누락, lifecycle lock과 모순된 concurrency barrier, 의도된 500 console 기대 모순,
  lease 손상·미래 시각, stale owner, audit 재판정·부분 commit, migration 중복 승격·pending downgrade,
  RustFS 보존과 post-commit stale 응답을 보완했다. 최신 T-170 위 재배치 뒤에도 2회 교차 검토해 cache
  I/O 이후 `xmin` fencing과 lifecycle lock, migration 단일 chain을 재확인했고 최종 P0/P1/P2 0건이다.
  n150 disposable PostGIS에서 backend 타깃 273건·변경 Python 31개 Ruff·Alembic
  `head→0024→0022→head` 왕복, frontend ESLint·type-check·Vitest 159건·production build,
  Playwright 22건 통과(live 전용 4건 skip)를 검증했다. 매 실행 후 `cleanup_db_exists=0`·
  `cleanup_container_exists=0`·E2E listener 0을 확인했다. backend 전체는 664건 통과했으며 실패 2건은
  n150에 선택 자막 library가 설치돼 `not_configured` 가정과 다른 기존 환경 차이(`download_error`,
  `no_captions`)다.

## 2026-07-13: T-169 — whisper 수동 재전사 액션 (D1 STT, 선별 실행)

- **문제**: 자막 최종 실패 영상의 STT 보강 수단이 없다. whisper 기본 ON은 N150 CPU에서 1건 수 분~수십
  분이라 단일 배치 레인을 장시간 독점(T-121-E)하므로 기본화 기각(§2.2 ③) — 대신 운영자 선별 실행.
  현행 env 게이트가 `transcribe_via_whisper` 함수 내부라 provider 지정만으론 force 불가, model도 env뿐.
- **사용자 결정(2026-07-13)**: prod 자동 전사(`TRANSCRIPT_WHISPER_ENABLED`)는 의도된 현행 ON 유지 —
  **auto 동작·기본값 불변**, 이번 작업은 **수동 force + model 인자 + 상한(caps)만** 구현.
- **구현**: `transcribe_via_whisper`에 `force`/`model_size`(keyword-only). `force=True`는 env 게이트 우회
  (`if not force and os.getenv(...)`), `force=False`는 기존 동작 byte-for-byte 불변. model 미지정 시 env
  `WHISPER_MODEL_SIZE` 기본. 체인 빌더 `whisper_forced_chain(model_size)`, `postprocess_service.
  _whisper_forced_transcript_fetcher(model_size)` 신설. `worker.poi_batch_handler`가 payload `force_whisper`/
  `whisper_model`을 읽어 whisper 강제 fetcher 주입(없으면 `_default_transcript_fetcher` 불변). API는 기존
  `/destinations/reprocess` 재사용 — `ReprocessRequest`에 additive `force_whisper`/`whisper_model`, force 시
  **batch lane**·model `small` 기본(`WHISPER_MANUAL_MODEL_SIZE`)·duration cap
  (`TRANSCRIPT_WHISPER_FORCE_MAX_DURATION_SECONDS=1200`, 초과 시 400+위반 video_ids). 스키마 변경 없음
  (payload 파라미터). `transcript_source='whisper'` 유지. concurrency 1은 batch 레인 단일 워커로 구조적
  보장(하드 리미터 미구현 — 사용자 결정: 상한만).
- **적대적 리뷰(PR 전, 2렌즈)**: 확정 BLOCKER/MAJOR 0. 정확성 렌즈 — auto 불변·force 게이트 실제 우회·
  payload 키 정합·lane·model 전달·테스트 실효 정확 판정. 렌즈 이견 1건 **병합 전 보강**: duration cap이
  `duration_seconds` NULL/0/음수를 상한 없이 통과 → 라이브 다시보기·프리미어(duration NULL)에 whisper
  강제 시 wall-clock 타임아웃 없고 `to_thread` 비취소라 수 시간 단일 영상이 batch 단일 레인을 무한 점유
  (harvest/스캔 기아, T-121-E) → **known positive duration ≤ cap만 통과, NULL/비양수는 400**(테스트 2건
  추가). 알려진 MINOR(문서화·미수정): 요청당 whisper 건수 상한 부재(기존 reprocess `[:200]` 공통 상한),
  검수자/운영자 역할 분리 없음(기존 admin-proxy 신뢰 모델과 동일).
- **범위 경계**: 프런트 "whisper로 재전사" 버튼은 `frontend/*` Agent B 소유이고 codex가 `/jobs/[jobId]`를
  활발히 수정 중이라 이번 범위에서 제외(Agent B 후속). 필요한 API 계약: `POST /api/v1/destinations/
  reprocess {video_ids, force_whisper: true, whisper_model?}`.
- **금지 준수**: auto whisper 동작/기본값 불변, 전 영상 무제한 whisper 없음(선별+duration cap), 기본
  파이프라인 경로 불변(force=False), routes.py 최소 additive(Agent B 미머지 브랜치 15개와 reprocess
  영역 미충돌 확인), 스키마 변경 없음.
- **검증**: 격리 disposable DB backend 전체 pytest 571 passed(pre-existing 1건 외 0), whisper-force
  테스트 10 passed, `compileall`·`git diff --check` 통과, migration 불필요, 최신 origin/main(#198) 0 behind.

## 2026-07-13: T-168 — description 단독 후보 경로 (D1 recall)

- **문제**: 자막 3 provider가 전부 실패한 영상은 POI 후보 없이 폐기돼 수율 손실(§1.3 D1). 자막 실패가
  일시적 차단·비활성일 수 있는데 그 영상의 설명(제목·태그)에 이미 장소가 언급된 경우가 많다.
- **구현**: `process_video_batch`에서 자막 최종 실패(T-164 판정: transcript None or not segments) 시
  영상을 FAILED로 버리는 대신, `_build_description_text`(제목+`description_raw`+태그)가
  `DESCRIPTION_POI_MIN_LENGTH`(기본 200자) 이상이면 그 텍스트를 단일 배치 아이템으로 POI 추출에 투입
  (`source_kind='description'`, 미달이면 기존대로 FAILED+`description_too_short`). 자막 성공 시 이 경로를
  타지 않는다(자막 우선, fallback 전용). **자동확정 절대 금지**: `apply_geocode_to_candidate` 초입에서
  description 후보는 게이트 통과 무관 needs_review·`review_note`·`feature_export_status=PENDING`·
  장소 미생성(return None) → feature snapshot/changes에서 자연 제외. grounding은 raw description 대조로
  관측만. recall은 `source_kind` 태깅으로 T-182 audit 필터가 분리 측정(후보 수↑를 신뢰성↑로 계상 안 함).
  스키마 변경 없음(기존 enum 재사용).
- **적대적 리뷰(PR 전, 2렌즈) — MAJOR 1 확정 수정**: 재처리 시 dedup이 `(video_id, 정규화 이름)`만
  키로 쓰고 `source_kind`를 무시 → run1 자막 실패로 만든 저품질 description 후보(영구 needs_review·export
  제외)가 run2 자막 복구·재처리로 나온 고품질 transcript 후보를 `continue`로 영구 차단(자막 우선순위
  역전, 스펙 위배). 수정: **source_kind 우선순위 비대칭 dedup**(`_source_kind_priority`: transcript 등
  실제 소스=1 > description/visual=0). 같은/상위 우선순위 후보 존재 시 새 후보 억제(멱등+자막 우선),
  미검수(`NEEDS_REVIEW`) 하위 후보만 있으면 T-160 `soft_delete_candidates`(reason=
  `superseded_by_higher_priority_source`)로 supersede 후 상위 후보 생성, 사람이 손댄(user_corrected/
  ignored/matched) 후보는 보존. MINOR: 200자 게이트는 신호 밀도 필터가 아닌 최소 컷임을 config 주석에
  명시, description 후보 `is_domestic` None(미확인)은 `review_note=domestic_unverified`로 두어
  queue_reason이 FOREIGN 버킷으로 가게(T-166 fail-closed 대칭, DESCRIPTION_ONLY가 국내여부 미확인을
  가리지 않게), 회귀 테스트 5건 추가.
- **금지 준수**: 자막 우선순위 역전 없음(수정으로 회복), description 후보 자동확정·export 노출 없음,
  YouTube metadata 신규 취득 없음(저장된 `description_raw` 재활용), queue_reason 파생 로직(T-182 소유)
  직접 변경 없음, 스키마 변경 없음.
- **검증**: 격리 disposable DB backend 전체 pytest 561 passed(pre-existing 1건 외 0), 신규
  `test_etl_description_path.py` 10 passed, 타깃 스위트 112 passed(pre-existing 1건 외 0), `compileall`·
  `git diff --check` 통과, 최신 main(#197) 0 behind.
## 2026-07-13: T-167 — 병합 제안 + auto-match audit (D6/G9)

- **문제**: dedup이 `(video_id, official_name)` 완전일치라 "성심당/성심당 본점"이 별개 후보(D6).
  자동확정(T-165/166 게이트 통과분)은 MATCHED로 큐에서 사라져 정밀도(오확정률) 측정 표본이 없다(G9).
- **구현**: 공용 `place_name.py`(정규화·pairwise names_match 단일 출처 — 게이트·dedup·병합 제안 공유),
  배치 dedup `(video_id, 정규화 이름)` 완화, 병합 "제안"만(자동 병합 금지) + `merge-suggestions` API,
  근접 재사용 반경 100→300m(이름 게이트 통과 전제). **auto-match audit 표본**(migration 0022:
  audit_status/reviewed_by/at/note + 부분 인덱스, 결정적 후보 id 해시 표본, 오확정률 집계) — MATCHED·
  export 상태 불변(사후 관측 전용, 되돌리기는 reopen T-160/184 위임). G9의 "auto-match audit 표본
  오확정률"로 T-166 정밀도 트레이드오프 실측 가능.
- **적대적 리뷰(PR 전, 2렌즈)**: BLOCKER/MAJOR 0. 정밀도 정정 — **`N호점` 정규화 제외**: 두 렌즈가
  "롯데리아 1호점"·"2호점"이 둘 다 "롯데리아"로 정규화돼 서로 다른 번호 지점이 뭉개짐을 지적(로드맵
  PR-14 정규식은 `[0-9]+호점` 포함했으나 정밀도를 해침). 본점/본관/직영점(같은 장소 표기)만 유지하고
  ADR-39로 편차 기록. MINOR: audit reviewed_by를 클라이언트 body 대신 검증 proxy actor로(G9 provenance),
  audit 표본을 결정적(후보 id 해시)으로, 병합 스캔 limit 완화, migration/import 정리.
- **금지 준수**: pg_trgm GIN(§2.3 기각)·자동 병합 실행·광범위 …점 제거 안 함.
- **검증**: 격리 DB backend pytest pre-existing 1건 외 0(549 passed), 타깃 5파일 전부 통과, alembic
  0022 round-trip 단일 head, 최신 main(#195) 리베이스 0 behind, `git diff --check` 통과.

## 2026-07-13: T-166 — 자동확정 identity gate (B3/D2/D4)

- **문제**: 지오코딩 자동확정이 Kakao 키워드 단일 결과면 무조건 matched/1.0, 신규 장소 생성 경로는
  이름 무검증 통과(D2), `_names_compatible`가 any-pair true(C8), 좌표-행정구역 교차검증 없음(D4),
  is_domestic None→true 간주(D7). T-113 라이브 점검에서 쓰레기 POI 자동확정 대량 발견 전력.
- **구현**: result_kind(poi|address|coordinate) 구분, pairwise 이름 게이트(신규 장소 강제),
  행정구역 게이트(region_gate.py 17개 시도 명시 alias·최장 surface 우선·reverse 추가 호출 없음),
  is_domestic fail-closed, ambiguous 단일 게이트 통과 자동확정. **자동확정 = grounding(T-165) + 이름 +
  행정구역 + is_domestic 네 불리언 AND**, 합성 점수 없음(§2.4-4). ADR-38로 ADR-16 경계 좁힘 명문화.
- **적대적 리뷰(PR 전, 2렌즈) — MAJOR 2건**: ① VWorld(최우선 지오코더)가 정제 **주소**(address kind)를
  반환하는데 address kind가 이름 게이트를 skip해 이름 무검증으로 confidence 1.0 자동확정 → G4 위반·D2
  부분 해소. 수정: **신규 장소 자동확정은 POI identity 검증(poi kind 이름 통과 또는 근접 재사용 기존명
  대조)을 요구**하고, address/coordinate 신규 결과는 needs_review(name_unverified)로 격상. ② ambiguous
  경로가 `refined` 미확인으로 VWorld unrefined 좌표 echo를 재승격(단건은 vworld_unrefined_single로 차단)
  → poi-only 제한 + 명시 refined 가드로 대칭 차단. MINOR(FOREIGN 라벨 vs 벌크 제외 대상 불일치는
  ADR-38 인지 기록, 벌크는 PR-10 Agent B 소유라 보류) 반영.
- **소급 없음**: 게이트는 apply_geocode_to_candidate(신규 지오코딩 시점)에만 적용, 기존 MATCHED 재평가
  sweep 없음(T-165 legacy 보존 원칙 준수).
- **검증**: 격리 DB backend pytest pre-existing 1건 외 0, 타깃 73 passed, `git diff --check` 통과.
- **동작 변화·후속**: VWorld address 결과 신규 장소가 needs_review로 가 검수 큐가 늘 수 있음(의도된
  정밀도 우선 트레이드오프). 근본 수리(VWorld get_coord 주소 전용 API에 장소명 질의를 넣는 설계
  부정합 → POI 검색 경로 우선순위화)는 로드맵 백로그, 자동확정률 하락 폭은 T-169 baseline live yield로 실측.

## 2026-07-13: T-165 — raw grounding 게이트 (B3)

- **문제**: 원 PR-13은 `evidence_quote`를 LLM 교정 자막에서 검사했으나 교정본도 생성 모델 산출물이라
  원문 증거가 아니다(§10 B3). grounding 실패를 배지로만 표시하고 자동확정을 안 막던 것도 문제(§1.3 D3).
- **구현**: batch POI 스키마에 evidence_quote·confidence 추가, `grounding.py`가 quote를 **raw 자막
  segment**(T-164 보존, 교정본 아님)와 대조해 `grounding_status` enum(migration 0021)으로 저장.
  transcript 후보는 verified_raw 아니면 **자동확정 차단**(geocode MATCHED 직전)·**export 제외**
  (feature_export)·queue_reason ungrounded. LLM 자가 confidence는 기록만(§2.4-3).
- **적대적 리뷰(PR 전, 2렌즈) — MAJOR 3건**: ① migration이 기존 export된 transcript 후보를
  legacy_unknown으로 backfill → export 게이트가 이들을 tombstone 회수 → **PinVi curated plan POI 대량
  소실 위험**. 수정: export·queue 게이트를 재처리로 실제 판정된 unverified/missing에만 적용, legacy는
  재처리 전까지 기존 노출·사유 유지(legacy UPSERT 유지 신규 테스트). ② queue_reason UNGROUNDED가 기존
  후보 전부를 덮어 진짜 사유(name/region_mismatch·reconcile) 마스킹 → legacy 제외. ③ POI 추출 LLM은
  교정본만 입력받아 evidence_quote가 교정본 표기인데 grounding은 raw 대조 → 장소명 띄어쓰기 교정
  (`부산역 국밥집`→`부산역국밥집`)으로 정상 POI 대량 오차단 → CJK 인접 공백 제거 정규화로 흡수(영문
  단어 경계 보존). MINOR 4(haystack 메모이즈·not_applicable 기본값·summarize 주석·raw 부재 인지) 반영.
- **게이트 일관성**: 자동확정·export·queue 세 게이트가 "legacy는 기존 상태 유지, 새 확정만 verified_raw
  요구"로 정합. 자동확정 게이트는 legacy도 needs_review 보존(재지오코딩 미재진입).
- **검증**: 격리 DB backend pytest 505 passed(pre-existing 1건 외 0), alembic 0021 round-trip,
  최신 main(#193) 리베이스 0 behind, `git diff --check` 통과.
- **후속**: raw-vs-corrected 근본 해결(추출 LLM에 raw 인용 원천 제공)은 T-169 baseline live yield로
  잔여 오차단율 실측 후 재검토. raw asset 없이 저장된 과거 자막 캐시 재처리는 전량 unverified(fail-safe).

## 2026-07-13: T-181 — run-queue 단일 폴링·attention 이력

- **작고 정확한 queue snapshot**: `GET /api/v1/runs/queue`를 동적 `/runs/{job_id}`보다 먼저
  등록하고, 서버 정본 `USER_JOB_TYPES`만 running 우선·상태별 FIFO로 조회한다. 10초 전역 poll이
  backlog 크기에 비례하지 않도록 항목은 100건으로 제한하되 `COUNT() FILTER ... OVER()`로
  running/pending 전체 수와 `has_more`를 정확히 반환한다. 종료 상태의 open attention은 별도 partial
  index 경로로 집계하고 두 SELECT는 `REPEATABLE READ` snapshot에 묶었다. `status_log_json`과
  `result_json`은 `defer(..., raiseload=True)`로 읽지 않으며 queue 직렬화도 빈 상세만 내보낸다.
- **한 cache·한 poll 소유자**: `JobStatusLink`, 수집 화면, 상태 화면을 `['run-queue']` 하나로
  통일하고 shell의 `JobStatusLink`만 응답 완료 시점 기준 10초 poll을 소유한다. 다른 observer는 fresh
  cache만 소비한다. 페이지 remount는 남은 deadline을 이어받고, fetch·offline pause 중 timer를 끄며,
  오류 cache도 mount마다 즉시 재요청하지 않아 장애 중 화면 이동이 요청 폭주로 번지지 않는다. 수집,
  재처리, Deep Research, poi batch, 반복 실행, 중지·재시작 등 사용 중인 작업 mutation은 성공 즉시
  queue를 invalidate한다.
- **막다른 attention 제거**: 정확한 open attention 배지는 `/status?tab=history&attention=open`으로
  이동한다. `/runs`에 `terminal`, `attention`, 서버 소유 `user_jobs_only` filter를 추가해 활성 full
  summary 중복을 없애고 queue endpoint만 실패해도 이력을 독립 조회한다. 이력은 80건 cursor page를
  계속 append하므로 81번째 미확인 작업에도 도달하며 60초 safety refresh를 유지한다. 활성 ID 소멸은
  이력과 destination facet을 즉시 invalidate하고, 결과·검수 facet은 10분 safety poll과 수동 새로고침,
  장소 생성·병합·삭제 직후 invalidate를 함께 사용한다.
- **반복 적대 검토·검증**: backend snapshot/SQL·UX/접근성·테스트/계약 세 렌즈로 3회 이상
  재검토했다. 무제한 payload, facet 영구 stale, attention 링크의 최신 80건 절단, page remount cadence,
  overdue 1ms timer, queue 부분 장애 결합, 81건 pagination, terminal/attention filter 독립성, deferred
  column 회귀, 빠른 응답 시 상태 화면 hydration 불일치를 차례로 보완해 최종 P0/P1/P2 0건을
  확인했다. 최신 main의 T-164와 Alembic 0020 위 n150에서 관련 backend 125건·변경 Python Ruff,
  frontend lint·type-check·Vitest 106건·production build, Playwright 14건 통과(live 4건 skip)를
  검증했다. backend 전체 기준선은 474건 통과·3건 실패로, 기존 postprocess category 기대 1건과
  T-164 테스트의 선택 provider 미설치 가정이 n150 설치 환경과 다른 2건뿐이며 T-181 신규 실패는
  없다.

## 2026-07-13: T-164 — transcript_attempts 관측 (D1)

- **문제**: 자막 3 provider(youtube-transcript-api·yt-dlp·faster-whisper)가 전부
  `except Exception: return None`으로 IP 차단·자막 비활성·파손을 "자막 없음" 한 가지로 뭉개
  실패 원인이 소실됐다(§1.3 D1, 실측 수율 11~40%). 이 데이터가 T-169 선별·T-172/173 게이트의 원천.
- **구현**: `transcript_attempts` durable 테이블(provider별 시도·outcome 8종·language·duration,
  성공 전 실패도 보존, migration 0020), `fetch_transcript`가 `TranscriptResult`를 wrap한
  `TranscriptOutcome` 반환(segments·`to_timestamped_text` 무손상 — 후보 timestamp 원천),
  예외 유형별 outcome 분류, `TRANSCRIPT_PROVIDER_ORDER` 실제 연결(사문화 해소), yt-dlp 언어·절단
  로그(D7), `youtube_videos.transcript_source/failure_code` 요약 캐시(우선순위 기반 대표 코드 —
  whisper=disabled가 no_captions를 가리지 않게). stage 이벤트(요약)와 attempts(상세) 역할 분리.
- **적대적 리뷰(PR 전, 2렌즈)**: 정확성·회귀·명세 / 데이터 정합·migration·성능 — segments 보존·
  소비처 회귀·provider order·migration 정합 판정. **MAJOR**: yt-dlp `ignoreerrors=True`가 차단·429를
  내부에서 삼켜 `no_captions`로 오분류 → T-169 선별 오염 → `ignoreerrors=False` + `_YtdlpErrorCollector`
  logger 이중 방어(삼켜진 에러 문자열 검사해 blocked/rate_limited만 lift, benign 경고는 no_captions
  유지)로 수정, 실동작 모사 테스트 3종. MINOR 4(빈 segment 단락→no_captions, provider 라벨 canonical
  통일, 캐시 자막 경로 요약 갱신, 테스트 우선순위 케이스) 반영.
- **검증**: 격리 DB backend pytest 466 passed(pre-existing 1건 외 0), transcript 단위 35 passed,
  alembic 0020 round-trip, 최신 main(#191) 리베이스 0 behind, `git diff --check` 통과.
- **후속 권장**: yt-dlp가 worktree에 미설치라 MAJOR 수정은 문서화 동작+모사 테스트로 검증 — 실
  prod 컨테이너에서 실제 차단/429 로그 문자열이 분류 키워드와 맞는지 smoke 확인 권장.

## 2026-07-13: T-180 — 실패 작업 재시작·실행 중지 UX

- **일관된 작업 제어**: `/status` 이력과 `/jobs/[jobId]` 헤더에 공용 `RunActionButtons`를 배선했다.
  terminal 작업은 확인 후 재시작하고 running 작업은 확인 후 중지를 요청하며, 요청 중에는 중복 클릭을
  막는다. mutation 성공·실패 안내는 행 내부가 아니라 상위 `role=status` live 영역에 보존해 invalidate
  직후 행이 큐에서 사라져도 결과를 읽을 수 있다. 재시작이 기존 active child를 돌려준 경우도 서버의
  `created` 값을 그대로 안내하고 상세 화면은 해당 child로 이동한다.
- **결과·주의·계보 분리**: API와 표시 helper의 상태를 exact union으로 좁히고, 실행 state와 실제
  outcome을 분리했다. `done`이어도 `quota_deferred is true`이면 성공색 대신 경고색과 "쿼터로 처리
  보류"를 표시한다. `attention`은 별도 badge로, `restart_of_run_id`와 `restarted_by_run_id`는 원본·
  후속 작업 링크로 노출해 실패를 단순 성공/실패 한 칸으로 뭉개지 않는다.
- **경쟁 조건 보강**: stop은 대상 row를 `FOR UPDATE`로 잠근 뒤 pending이면 `cancelled`, running이면
  `cancel_requested`로 전이하고, 잠금 안에서 만든 불변 snapshot으로 응답과 audit의 이전 상태를
  결정한다. worker claim 또는 즉시 취소 완료와 경합해도 허용된 한 가지 전이만 관측한다. restart는
  동시 요청에서도 원본당 active child 하나만 만들며, 쿼터 보류 child를 다시 시작한 descendant가
  성공하면 cycle-safe lineage 순회로 조상의 미해소 attention까지 정리한다. worker와 service는
  `quota_deferred is True`만 보류로 인정한다.
- **반복 적대 검토·검증**: backend 상태 머신/동시성, UX/접근성, 계약/E2E 세 렌즈로 2회 이상
  재검토하고 stop snapshot, deferred lineage, strict bool, exact type, 경고색, 행 unmount 피드백,
  동시 재시작 회귀를 보완해 최종 P0/P1 0건을 확인했다. 최신 main의 T-163 레인 분리 위로 재배치해
  원본 lane 복사와 stop-vs-lane claim 잠금 결합을 다시 검토하고, n150에서 관련 backend 113건과 변경 파일
  Ruff, frontend lint·type-check·Vitest 104건·production build, Playwright 11건 통과(live 4건 skip)를
  검증했다. backend 전체는 434건 중 433건이 통과했고, 남은 1건은 기존
  `test_process_harvest_videos_creates_place_from_summarized_poi`의 category 기대(`음식점` 대
  `unknown`)로 T-180 변경 범위와 무관하다.

## 2026-07-13: T-163 — 워커 레인 분리 (S1)

- **문제**: 단일 실행자 큐라 긴 poi_batch가 완주할 때까지 사용자가 방금 누른 재처리·deep research가
  전부 뒤에 줄 섰다(§1.2 S1). claim은 이미 `FOR UPDATE SKIP LOCKED`인데 컨슈머가 1개였다.
- **구현**: `crawl_runs.lane`(interactive|batch, CHECK+`(lane,state,id)` 인덱스, migration 0019).
  lane은 job_type이 아니라 **enqueue 지점 기준**(같은 poi_batch라도 사용자 재처리=interactive,
  harvest splitter child=batch) — 12지점 매핑, restart는 원본 lane 복사(G6). `claim_next_pending(lane)`
  격리, 스케줄러 레인당 interval job 2개(`-interactive`/`-batch`, 각 max_instances=1) + 구
  `crawl-run-worker` 제거(start() 후 register). stale 재투입 lane 보존.
- **적대적 리뷰(PR 전, 2렌즈)**: 정확성·회귀·명세 / 데이터 정합·migration·성능 — BLOCKER/MAJOR 0.
  lane 매핑 12지점·claim 격리·restart 복사·stale 보존·구 job 제거 전부 정확 판정. MINOR:
  2 워커 동시 requeue_stale 경합 방지 `skip_locked` 하드닝, child payload `source_job_id` lineage,
  단일 워커를 서술하던 문서 3종(architecture/decisions ADR-13/dev-environment) 갱신.
- **핵심 목적 검증**: 긴 batch 백로그가 있어도 interactive 워커가 batch 행을 술어에서 제외해 즉시
  claim — 테스트로 확인.
- **검증**: 격리 DB backend pytest 421 passed(pre-existing 1건 외 0), alembic 0019 round-trip 단일
  head, 최신 main(#189) 리베이스 0 behind, `git diff --check` 통과.

## 2026-07-13: T-182 — 검수 행 판단 정보와 안정 대기 사유

- **경량 목록 보강**: 검수 후보를 `youtube_videos`·`youtube_channels`와 항상 outer join해 영상 제목,
  정규 채널 제목, 매칭 신뢰도, 출처, 생성 시각을 짧은 scalar로 반환한다. `source_text`,
  `review_note`, `provider_evidence_json`은 계속 상세 API에만 둔다. 300건 n150 fixture에서 기존 필드
  환산 64,456 byte 대비 122,656 byte로 항목당 약 194 byte만 늘었고, 후보 evidence에 100KB 문자열이
  있어도 목록 응답에 포함되지 않았다.
- **신뢰 가능한 사유 계약**: `queue_reason`을 저장 컬럼으로 중복하지 않고 evidence에서 파생한다.
  장소명·지역 불일치, URL/자막 대조의 충돌·저신뢰·불확실, 지오코딩 모호·무결과·미정제, 해외,
  설명/시각 전용, provider 구조 누락, 추출 대기의 우선순위를 정본 문서에 고정했다. reason·source
  filter는 items·total·newer_than과 cursor fingerprint에 동일 적용하며 scope를 `unmatched-v2`로
  올렸다. grounding은 T-165 raw 근거 저장 전에는 산출·filter하지 않는다.
- **오염 데이터 fail-safe**: 별도 confidence 컬럼은 유한한 0..1만 JSON으로 내보내고 NaN·Infinity·
  범위 밖은 `null`로 바꾼다. schema 없는 reconcile JSONB 점수는 JSON number일 때만 PostgreSQL
  `NUMERIC`으로 변환해 문자열·객체·거대 숫자 한 건이 목록 전체를 실패시키지 않게 했다. 정상·미래
  geocoding reason도 `provider_missing`으로 오분류하지 않는다.
- **행 UX·검증**: 후보명 옆에 매칭 신뢰도와 사유 badge, 출처 칸에 영상 제목·채널·위치, 상태 칸에
  출처와 등록 시각을 표시하고 raw video ID는 tooltip/detail로 강등했다. 적대적 검토를 세 단계로
  반복해 최종 P0/P1 0건을 확인했다. n150에서 PostgreSQL 타깃 8건·변경 파일 Ruff, backend 전체
  385건(기존 postprocess category 기대 1건 실패), frontend lint·type-check·전체 Vitest·production
  build, Playwright 9건을 검증했다. 전체 Ruff의 기존 미사용 import/변수 12건은 변경 범위 밖으로
  분리했다.

## 2026-07-13: T-162 — durable stage events + restart lineage·attention (B6)

- **문제**: `status_log_json` parser가 timestamp/level/message/progress 4필드만 보존·80건 절단
  (§1.5 C7)이라 단계별 구조화 측정을 status_log 주입으로 달성 불가. 재시작은 lineage·멱등 없이 복제.
- **구현**: `crawl_run_stage_events`(stage/provider/attempt/item_ref/started/finished/elapsed_ms/
  outcome/detail, monotonic 실측, 독립 세션 best-effort commit) — poi_batch 4단계 + 배치 총소요
  경계, harvest 2단계. `crawl_runs.restart_of_run_id`(self FK, FOR UPDATE 멱등 — 원본당 active 1,
  lane 복사는 T-163)와 `attention`(4상태, CHECK+partial index) + `acknowledge` API. run 응답 additive
  노출(#185 envelope items·단건 양쪽). status_log parser는 불변(요약 view). migration 0018.
- **적대적 리뷰(PR 전, 2렌즈)**: 정확성·회귀·명세 / 데이터 정합·migration·성능 — BLOCKER/MAJOR 0.
  MINOR: G7 provider별 관측은 이 계측 범위 밖(T-164 transcript_attempts 소관)으로 docstring 정정,
  T-172 게이트 분모 왜곡 방지용 `poi_batch_total` 경계 이벤트 추가. 전이 소유 단독성·멱등 동시성·
  status_log 불변·envelope additive 생존 전수 확인.
- **리베이스**: 작업 중 main이 #185(envelope)·#186(cursor)·#187(검수 자동 진행)로 전진 —
  crawl_run_service import 블록 결합 해소, envelope items에 attention 필드 생존 회귀 어서션 추가.
- **검증**: 격리 disposable DB backend pytest 405 passed(pre-existing 1건만 실패 —
  `test_destinations_reflect_db`는 격리 DB에서 통과해 공유 DB fixture 경합 flake로 확정), alembic
  0017→0018 round-trip, `test_migration_graph` 단일 head, envelope 회귀. `git diff --check` 통과.

## 2026-07-13: T-179 — 검수 자동 다음 후보와 근거 시각 링크

- **연속 검수 흐름**: 저장·제외·개별 행/상세 삭제 성공 시 처리 시작 시점의 visible 후보 순서와
  로드된 page 수를 snapshot으로 보존한다. 같은 인덱스의 다음 후보, 없으면 이전 후보를 고르고,
  미로드 page가 있으면 숨김 후보만 있는 page도 건너뛰어 첫 visible 후보 또는 마지막 page까지
  자동 탐색한다. 마지막 page의 현재 표시 조건에 후보가 없을 때만 완료로 표시한다.
- **사용자 조작 우선**: 최초·딥링크 프리셀렉트는 `autoSearch: false`, 처리 성공 뒤 이동은 자동
  검색으로 구분했다. 사용자가 행을 직접 고르면 진행 중 page 탐색과 과거 `?candidate=`를 취소해
  늦은 응답이 입력을 덮지 않는다. polling이 선택 후보를 현재 page 밖으로 밀어도 후보·폼·검색
  근거 snapshot을 유지하고, scope 변경·대량 삭제·완료 시에만 명시적으로 해제한다.
- **경쟁 조건·실패 복구**: resolve/delete 성공 전에 검수 query의 in-flight 응답을 취소하고 scope·
  candidate identity를 확인한다. 상세 삭제는 시작 시 snapshot을 잡고 pending 동안 modal close와
  다른 상세 action을 잠근다. 첫 page·다음 page·cursor 계약·딥링크 탐색 실패는 빈 큐로 숨기지
  않고 오류와 재시도를 제공하며, 늦은 실패는 후보 이름과 함께 queue 수준에 귀속한다.
- **근거 링크·검증**: `MM:SS`, `HH:MM:SS`, 범위 문자열의 첫 시각만 엄격히 파싱하고 잘못된 분·초·
  괄호·prefix는 거절한다. 목록과 상세 YouTube URL은 기존 query/hash를 보존한 채 `t=<초>s`를
  `URLSearchParams`로 넣는다. 적대적 검토를 세 차례 반복해 최종 P0/P1 0건을 확인했고, n150에서
  frontend lint·type-check·Vitest·production build와 Playwright 저장·제외·개별 삭제·숨김 page
  자동 탐색 시나리오를 검증했다.

## 2026-07-13: T-178 — 장소 101/501번째 cursor 접근과 page 밖 상세

- **결과 화면 page 전환**: 기존 첫 100개 배열 조회를 `useInfiniteQuery`와
  `listDestinationsPage(limit=100)`로 교체했다. `has_more/next_cursor`를 그대로 이어 붙이고 sort·
  group·video·category·district·검색어를 query identity에 포함해 조건 변경 시 첫 page로 돌아간다.
  `place_id` 중복은 첫 위치를 유지하되 뒤 page의 최신 payload로 갱신한다.
- **완료를 거짓말하지 않는 UX**: 표시 수와 live `total`을 분리하고, 다음 page 로딩 중 중복 클릭을
  막는다. 초기 실패는 다시 시도, page 실패는 기존 행을 보존한 재시도, 비정상 cursor는 명시적
  오류로 표시한다. cursor가 끝나도 dedupe 수와 total이 다르면 “모두”로 단정하지 않고 목록 변경과
  새로고침을 안내한다. `전체 선택`은 실제 동작에 맞춰 “표시된 N개 선택”으로 좁혔다.
- **속도·신선도 절충**: 첫 paint는 100행·marker로 유지한다. 단일 page는 60초 polling, 둘 이상을
  불러온 뒤에는 T-188 전 page별 전체 Python 재집계를 자동 반복하지 않고 명시적 새로고침을 쓴다.
  SQL pushdown과 `source_videos` 목록 제거는 T-188에서 EXPLAIN으로 마감한다.
- **page 밖 상세·검증**: `/?place={id}`는 현재 filter나 첫 page를 지우거나 순회하지 않고 detail
  endpoint를 직접 열며, 데스크톱 modal을 닫으면 query를 제거한다. n150 Playwright에서 100×5+1
  cursor chain, 101/501번째, 501개 unique, 종료, page 밖 상세를 검증한 신규 2건과 기존 5건이 모두
  통과했다. frontend lint·type-check·Vitest 34건·production build도 n150에서 통과했다.

## 2026-07-13: T-177 — 목록 공통 envelope와 안정 cursor 계약

- **공통 공급 계약**: 검수·작업·장소·테마 목록을
  `{items,next_cursor,has_more,total,newest_id,newer_than}`으로 통일했다. 첫 page watermark와 전체
  정렬 key를 가진 URL-safe cursor, endpoint·정렬·정규화 filter fingerprint, 동률 ID tiebreak를
  적용하고 잘못된 version·범위·filter·문자열 길이는 400/422로 거절한다. 301/501번째 항목은 cursor
  순회로 접근하며 후보·장소·작업·테마는 page 밖에서도 단건 상세 조회가 가능하다.
- **snapshot 일관성**: 공개 read key cache miss에서 인증 SELECT가 먼저 실행될 때 같은 FastAPI
  session이 `READ COMMITTED`로 시작되는 문제를 2차 적대적 리뷰에서 발견했다. 인증 `get_session`과
  별도인 목록 dependency를 추가해 네 route가 첫 statement 전 `REPEATABLE READ` transaction을
  시작하도록 고쳤고, 실제 production dependency와 `SHOW transaction_isolation`을 쓰는 회귀 테스트로
  고정했다.
- **호환·후속 경계**: backend 응답 변경은 breaking 계약으로 문서화하고 프런트 API wrapper가 기존
  배열과 테마 그룹 shape를 임시 복원한다. features snapshot/changes의 sequence cursor·3필드 응답은
  불변이다. 장소·테마의 전체 Python 재집계 비용은 숨기지 않고 T-188/T-190 SQL pushdown으로
  이관했으며, unsigned 조회 cursor는 T-185 일괄 검수 승인 token으로 재사용하지 않는다.
- **검증**: PostgreSQL skill의 MVCC·index 기준으로 신규 migration이 불필요함을 확인하고 적대적
  리뷰를 두 차례 이상 반복해 최종 P0/P1 0건을 확인했다. n150에서 backend 전체 pytest와 Ruff,
  frontend lint·type-check·Vitest 34건·production build, Playwright 5건을 통과했다.

## 2026-07-13: T-161 — LLM async/multimodal 게이트웨이 (B6)

- **문제**: rate limiter가 자막 교정·batch POI 2곳만 커버하고 deep research·키워드 확장·검수
  의견·카테고리·POI 추출·video_analysis(직접 HTTP 호출)는 quota 예약을 우회했다(§1.5 C6). 동기
  LLM 호출의 이벤트 루프 차단 사고(T-101/105/111/121-E)도 호출부별 격리로 반복 땜질 중이었다.
- **구현**: `llm_client`를 단일 async 게이트웨이로 — quota reservation(Gemini)·`to_thread` 격리·
  timeout/retry per-call 옵션·usage 실측(`llm_usage` 구조화 로그, 추정식 보정 데이터 원천)·
  multimodal(`parts`/`file_data` pass-through, media당 65,536 floor 가산)을 한 계약으로. 호출부
  11곳 이관, 기존 semantics(교정 max_attempts=1·240s, batch 파싱 재시도, 키워드 템플릿 폴백,
  의견 12s 흡수, video_analysis 페이로드 동등) 함수 단위 보존. direct SDK guard 테스트로 재발 방지.
- **적대적 리뷰(PR 전)**: async 정확성(await 누락 전수 0)·B6 명세·semantics 3렌즈 — BLOCKER 0.
  MAJOR 2: ① 대화형 검수 의견이 배치 쿼터 소진 시 리미터 대기로 12초를 태우고 오도성 timeout
  메시지 → `acquire(max_wait_seconds)`+`GeminiQuotaBusy` 신설, 의견 경로는 무대기(quota_max_wait=0)
  +"쿼터 윈도우 대기 중" 정확 메시지. ② guard가 DeepSeek 헬퍼·openai import 미검출 → 패턴·스캔
  범위(scheduler/mcp/etl) 확장. MINOR 7(진단 메시지·TPM 하한 주석·stale 주석·floor 표현·리미터
  한계 명시·RPD 비대칭 주석·dev-environment §12 절차) 전부 반영.
- **검증**: backend 전체 pytest 336 passed(pre-existing 2건 외 0) — 공유 test DB 경합을 피해 격리
  disposable DB로 실행(병렬 트랙 검증 시 세션별 DB 분리 권장 사항으로 기록). rebase 후 핵심 스위트
  재실행 통과. `git diff --check` 통과.

## 2026-07-13: T-176 — 소비자 read key 회전 및 운영 권한 분리

- **선행 migration 복구**: T-175와 T-160이 동시에 사용하던 Alembic revision `0016`을
  scope `0016` → candidate soft delete `0017`의 단일 선형 graph로 복구하고 PR #182를 병합했다.
  n150 prod write 서비스를 중지하고 장기 transaction이 없음을 확인한 뒤 유한 lock/statement
  timeout으로 `0015→0017`을 적용했다. scope 컬럼·CHECK, soft delete 3컬럼·CHECK·partial index
  3종, 현재 revision `0017`을 확인한 후 API·MCP·scheduler·UI를 재생성했다.
- **consumer 최소 권한 전환**: 관리자 BFF로 DB `read` key를 발급하고, docker-manager를 비밀의
  단일 원천으로 삼아 `kor-travel-map` Dagster·daemon에만 주입했다. Map API에는 이 인증 정보를
  주입하지 않으며, 기존 값 제거를 보장하기 위해 컨테이너를 재생성해 환경에 남지 않음을 확인했다.
  Map 소비자 계약·테스트는 `kor-travel-map` PR #664, 배선·runbook은 docker-manager PR #51에
  반영했다.
- **실데이터 검증**: snapshot/changes 각각 `limit=1`로 두 페이지의 opaque cursor 전진을 먼저
  검증한 뒤 `limit=200`으로 8페이지·1,416개를 끝까지 순회했다. 실제 Dagster 가져오기 경로도 두
  endpoint에서 각각 1,416개를 반환했다. export ID 중복이 없고 read key 공급 GET은 200,
  장소 삭제와 설정 조회는 403임을 확인했다.
- **구 정적 admin 인증 정보 폐기**: 새 BFF/operator admin 인증 정보와 구 인증 정보의
  짧은 중첩 기간에 UI를 먼저 전환한 뒤 구 값을 allowlist에서 제거했다. 최종 검증은 구 key 401,
  새 admin 설정 GET 200, admin key 관리 경로의 직접 접근 403, read key 공급 200·write 403이다.
  UI 로그인 POST 200+`Set-Cookie`, session BFF 200, 틀린 비밀번호 401도 재확인했다. UI 재생성
  직후 준비 시간 중 한 차례 503은 재시도 후 정상화됐으며 최종 최근 로그의 오류 패턴 검색은 0건이었다.
- **보안 마감**: 평문 key는 임시 `0600` 파일로만 전달하고 출력·문서화하지 않았다. 전환용
  백업, cookie, DB 복원 지점, 임시 key 파일을 성공 검증 뒤 제거했다. 실제 값·접속 정보가
  없는 재현 절차는 각 저장소의 추적 문서에, 민감 운영 이력은 gitignore된 배포 runbook에 남겼다.

## 2026-07-13: T-176 선행 — Alembic 0016 revision 충돌 해소

- **원인**: T-175 공개 API key scope와 뒤이어 병합된 T-160 candidate soft delete migration이
  모두 `20260713_0016`/`down_revision=20260710_0015`를 선언해 `upgrade head`가 중복 revision과
  multiple heads로 중단됐다. n150은 0015에서 transaction 적용 전에 안전하게 멈췄다.
- **해결**: 먼저 병합·배포 가능한 T-175 scope migration은 0016으로 유지하고, 아직 prod에 적용되지
  않은 T-160 migration을 `20260713_0017`/`down_revision=20260713_0016`으로 선형화했다. 이미 T-175
  0016을 적용한 환경도 다음 upgrade에서 T-160만 적용할 수 있다.
- **n150 검증**: prod 0015 restore point를 disposable database에 복원해 단일 head 0017,
  0015→0016(scope)→0017(soft delete) upgrade, scope column/CHECK, soft delete 3컬럼/CHECK·partial
  index 3종을 확인했다. 0017→0016 downgrade에서 scope는 보존되고 soft delete 컬럼만 제거되며,
  재upgrade가 0017로 복원되는 round-trip도 통과했다. PR/CI green 후 prod에 재적용한다.
- **재발·운영 방지**: revision ID 유일성과 single head를 검사하는 test gate를 추가했다. prod에서는
  write 서비스 중지·장기 transaction 확인·유한 lock/statement timeout 뒤 0017을 적용한다. 첫 soft
  delete write 뒤에는 `deleted_at`을 모르는 구 앱 또는 0016 schema로 rollback하지 않고 forward-fix나
  migration 전 snapshot 복원만 허용한다. 과거 candidate-only 0016은 schema fingerprint로 차단한다.

## 2026-07-13: T-160 — candidate soft delete 상태 모델 (B1)

- **문제**: `FeatureExport.candidate_id`가 non-null·unique·NO ACTION FK라 후보 삭제·영상 제외가
  ledger 행을 먼저 지웠고, tombstone은 잔존 ledger 행에만 발행 가능해 **이미 export된 feature가
  downstream에서 조용히 잔존**했다(§10 B1 — Codex 리뷰 확정, 코드 검증 완료).
- **구현**: soft delete 3필드+CHECK+검수 큐 partial index 3종(20260713_0017, up/down round-trip
  검증), `soft_delete_candidates`(FOR UPDATE, 매핑 삭제·matched 해제·같은 트랜잭션
  `tombstone_candidate_exports` — 새 sequence, export 안 된 후보는 무동작), 후보 삭제 라우트와
  `exclude_video`(force)를 helper로 교체(ledger DELETE 코드 전소멸), 활성 조회 10여 곳
  `deleted_at IS NULL` 전수 적용, `reopen` 엔드포인트(deleted/ignored→NEEDS_REVIEW+pending,
  reviewed_by/at clear), sync에 tombstone freeze 가드(재발행 소음 제거).
- **적대적 리뷰(PR 전)**: 정확성·회귀/B1·G1 명세/데이터 정합·migration 3렌즈 — BLOCKER 0.
  MAJOR 2(B1 절차 5 회귀 테스트 3건 공백, MATCHED/USER_CORRECTED reopen 이연의 기록 의무)와
  MINOR 6(공백 reason 500, soft delete 무락 race, provider identity 방어 필터, reopen 메타
  clear, tombstone 재발행 소음, downgrade 경고)을 전부 머지 전 반영. T-174 리베이스 결합·인덱스
  대체·dedup 재등장 정책은 3렌즈 모두 무결 판정(feature-export-api.md 계약 위반 없음).
- **이연(T-184 명문화)**: MATCHED/USER_CORRECTED reopen(장소 정리 정책 포함), 영상 제외 undo.
- **검증**: G1 통합 테스트(export→삭제→changes tombstone→전량 sync 2회 golden 재시작 등가→
  reopen 409 재확인→재확정 후 같은 export_id upsert 재발행→cursor 단조·중복 없음), 영향 테스트
  40+42 passed, backend 전체 pytest pre-existing 2건 외 실패 0, `git diff --check` 통과.

## 2026-07-13: T-175 — 공개 API 키 read/admin scope 분리

- **DB·인증 경계**: `public_api_keys.scope`에 `read|admin` NOT NULL·CHECK를 추가하고 기존
  행은 `read`로 backfill했다. scope는 발급 뒤 변경하지 않고 폐기 후 재발급한다. 활성 키 cache는
  hash 집합에서 `key_hash → scope` mapping으로 바꿨고, create/revoke 무효화 generation을
  비교해 DB SELECT 뒤 stale snapshot이 재게시되는 race를 차단했다. 공급용 장소·feature·theme·
  category GET 11경로만 exact/제한 정규식 allowlist로 열고, 내부 GET과 모든 write는
  deny-by-default 403으로 막았다. query `key`는 DB read만, DB/static admin은 header만 허용하며,
  신뢰 CIDR 무키 우회는 read, `/admin/*`는 scope와 무관하게 BFF proxy 전용이다.
- **관리·UX·계약**: 발급 요청·응답·목록·감사 로그에 scope를 포함하고 기본 `read` select, 목록
  scope 표시, admin 위험 HelpTip을 설정 화면에 추가했다. 외부 curl은 session BFF가 아닌 실제 REST
  API origin과 read header를 안내한다. key create/revoke와 audit를 한 transaction에 묶어 audit
  실패 시 활성 admin key가 고아로 남지 않게 했다. ADR-36, architecture, feature export 정본,
  README/env/dev/agent 문서를 같은 계약으로 정렬했다. T-175는 capability 완료이며 production
  `kor-travel-map` key 발급·교체·구 consumer static entry 제거는 T-176 대기다.
- **반복 적대적 검토**: 1차 route·계약 감사와 2차 수정 후 재검토에서 빈 header+admin query
  source 오판, cache refill/invalidation race, key/audit 비원자성, Web/BFF origin을 가리키는 외부
  curl, query 전달 도움말, HEAD 405 문서 모순, T-176 완료 전환 오표기를 발견해 모두 보강했다.
  최종 P0/P1은 없고, 프로세스 로컬 cache는 현 단일 Uvicorn worker 계약에서 유지하되 다중 replica
  전환 시 DB epoch/pub/sub 무효화를 선행하도록 ADR에 기록했다.
- **n150 검증**: 일회성 PostGIS DB에서 auth 42건과 기존 기준선 실패 2건을 제외한 backend 전체가
  통과했다. Alembic `0015→0016` upgrade, 기존 active 행 read backfill, invalid scope CHECK 거부,
  `0016→0015` downgrade 뒤 행 보존·column 제거를 검증했다. frontend lint/type-check/Vitest 33건/
  production build와 Playwright 설정 scope 시나리오가 통과했다.

## 2026-07-13: T-158 — Phase -1 외부 provider 정책·데이터 권리 게이트

- **산출물**: `docs/provider-policy.md` 신설 — YouTube/Google Places/NCP Maps/Naver Local
  Search/Kakao/VWorld × (표시/지도/영구 저장/임시 cache/attribution/외부 export/허용 TTL/약관
  버전·확인일) matrix를 전부 공식 원문 대조로 작성. 핵심: YouTube audiovisual 다운로드·저장은
  서면 승인 필요(III.E.1)·metadata 30일(III.E.4, 통계 예외는 Authorized Data 한정이라 적용 불가),
  Google Places는 비-Google 지도 표시 금지(SST §14.2)·No Scraping/No Caching(ToS §3.2.3),
  NCP Maps는 "즉시 1회 사용"(제7조⑪), Naver Local Search는 저장·DB화 금지(7.3.③), Kakao는
  조건부 cache(최신성 의무). 현행 코드 충돌 C-1~C-7, ADR-15 재검토 초안(옵션 4종), release gate
  선언, 인벤토리(dev RustFS 버킷 부재, env 플래그 상태 — 비밀 미기록) 포함.
- **kill switch**: `RAW_MEDIA_STORE_ENABLED`(RustFS 원본 저장 게이트), `GOOGLE_PLACE_SEARCH_ENABLED`
  (`/place-search`의 google provider 게이트 — off면 빈 목록+`errors.google`) — 기본 true(현행 유지,
  사용자 승인). 테스트 4건(off 시 스킵·무HTTP·기본값 고정).
- **적대적 리뷰(PR 전)**: 3렌즈(정책 원문 재대조·코드/비밀 스캔·명세 완결성)에서 BLOCKER 1건
  (prod 호스트 IP가 문서에 기록 — 푸시 전 제거)·MAJOR 5건(YouTube 통계 예외 오적용, 플래그
  이름/범위 불일치→`RAW_MEDIA_STORE_ENABLED` 개명, Kakao release gate 누락, 기본값 스펙 이탈의
  사용자 승인 기록, journal/tasks 미갱신)·MINOR 6건을 전부 머지 전 반영.
- **사용자 결정(2026-07-13)**: ① Google 결과의 VWorld 지도 표시는 의도된 현행 유지(인지된 정책
  리스크로 기록), ② prod whisper 자동 전사 현행 유지 — 자막 품질 개선은 신규 T-193(조건부)으로
  분리, ③ NCP Maps 결과는 캐시·저장 대상에서 제외(T-170에서 matrix 기반 처리).
- **검증**: compileall, kill switch·place_search 테스트 10 passed 2 skipped, backend 전체 pytest
  305 passed(+pre-existing 2 failed), 문서 비밀 재스캔 clean, `git diff --check` 통과.

## 2026-07-13: T-174 — 검수 선택 provenance·근접 중복 결정 보강

- **선택 근거 보존**: Google/Kakao/Naver 검색 결과에 provider native ID와 저장 capability,
  검색 완료 시각을 추가했다. 프런트는 선택 hit 전체를 후보 ID와 결박된 typed state로 유지하고,
  주소·provider·native ID·query·검색/선택 시각·원본 이름/좌표/카테고리를 resolve에 보낸다.
  백엔드는 기존 transcript/geocoding 등 JSONB namespace를 보존하면서 버전된
  `review.resolutions[]`에 원본 snapshot, 실제 `TravelPlace` 최종값, reviewer, 근접 결정을
  누적하고 동일 snapshot을 영상 매핑에도 복사한다. `api_source`는 selected provider에서 서버가
  도출하며 신뢰 proxy가 없는 웹 호출은 `unverified-web`으로 구분한다.
- **정책·오판 차단**: T-158 정책 확정 전 Google hit은 카드에서 사유와 함께 비활성화하고
  VWorld marker·Gemini 의견 입력·REST/MCP 영속화에서 제외했다. 신규 좌표 100m 안의 장소는
  이름·provider ID·30m 거리까지 모두 맞는 단일 후보만 자동 병합하며, 나머지는 409로 기존
  장소 병합/새 장소 생성을 사용자에게 묻는다. 과거 resolution은 실제 최종 place ID가 현재
  매칭과 같은 경우에만 identity로 재사용한다.
- **동시성·UX 신뢰성**: 후보 resolve는 row lock, 신규 장소 중복 조회·생성은 transaction
  advisory lock으로 직렬화했다. 409 재시도는 현재 화면값이 아니라 최초 요청 snapshot을
  보존하며, 필터/refetch 뒤에는 폼 소유 후보가 다르면 저장을 막고 초기화한다. category match는
  AbortSignal·request/candidate identity로 늦은 응답을 폐기한다. 제한 provider는 지도에서도
  선택할 수 없고, 근접 다이얼로그는 이름/provider ID의 일치·불일치·비교 불가를 모두 표시한다.
  MCP도 구조화 근접 후보 반환과 `merge_existing`/`create_new` 재시도를 지원한다.
- **반복 리뷰**: 백엔드와 프런트 적대적 리뷰를 병행해 MCP 재시도 불가, 동시 resolve 유실,
  과거 provider ID 오귀속, `api_source` 기본값 모순, 409 snapshot 유실, 후보-폼 소유권 혼선,
  Google→Gemini 저장 우회, 다이얼로그 근거·접근성 누락을 확인하고 전부 보강했다. 공개 API key
  read/admin 경계는 별도 schema·정책 PR인 T-175에서 처리하며, provider 검색 receipt는 공유
  secret/다중 프로세스 계약 없이 임시 도입하지 않고 T-158 정책 결정과 연계한다. 반영 뒤 2차
  적대적 재검토에서 새 P0/P1이 없음을 확인했고, 잔여 P2였던 검색/선택 시각의 순서·timezone
  검증과 409 대화상자의 충돌 당시 장소명 문맥도 추가로 보강했다.
- **n150 검증**: Docker Python 3.11 이미지와 일회성 PostGIS DB에서 `compileall`, T-174
  backend 타깃 17건, 전체 backend suite 중 기준선 실패 2건 제외 전건 통과. 제외 2건
  (`mention_count` 2 기대/1 반환, legacy category `음식점` 기대/`unknown` 반환)은 n150의 현
  `latest-main` 이미지에서도 각각 동일 재현했다. frontend `npm run lint`, `npm run type-check`,
  Vitest 33건, production build와 n150 cached Chromium Playwright 5건이 통과했다. 2차 리뷰
  보완 뒤에도 관련 backend 66건(기준선 `mention_count` 1건 제외), frontend 전 검증, provider
  provenance/409 E2E를 n150에서 다시 통과했다.

## 2026-07-13: T-159 — exclude_video 컬럼 버그 hotfix

- **수정**: `place_service.exclude_video`의 고아 장소 판정 루프가 모델에 없는
  `ExtractedPlaceCandidate.place_id`를 참조해 매핑 보유 영상 제외 시 AttributeError로 크래시하던
  문제를 실제 컬럼 `matched_place_id`로 수정했다(1줄, 로드맵 PR-30/§1.5 C2). ledger 선삭제·
  tombstone 미발행 문제는 T-160 소관으로 보존.
- **테스트**: 수정 전 코드로 AttributeError 재현을 확인한 회귀 테스트 추가 — 제외 영상의 고아
  장소는 삭제되고, 타 영상 매핑 공유 장소와 타 영상 matched 후보가 참조하는 장소는 보존.
- **검증**: backend compileall, `test_place_service.py` 11 passed, backend 전체 pytest
  302 passed / 2 failed — 실패 2건(`test_destinations_reflect_db`,
  `test_process_harvest_videos_creates_place_from_summarized_poi`)은 pristine HEAD에서도 동일
  실패하는 기존 결함으로 확인(T-159 무관, 별도 조사 필요). `git diff --check` 통과.

## 2026-07-13: T-157 후속 — Codex 리뷰 검증·본문 통합·Agent A/B 작업 등재

- **검증**: Codex 리뷰(§10)의 사실 주장 22건(FeatureExport FK NO ACTION·후보 삭제의 ledger
  선삭제·`exclude_video`의 `place_id` AttributeError·tombstone이 잔존 ledger 행에만 발행
  가능·provenance 유실·`api_source='manual'` 고정·create_place 무검증 병합·category race·
  리미터 acquire 2곳뿐·row lock은 admission만·status_log 4필드 절단·`_names_compatible`
  any-pair·수율 3/27→11/27·`sido_code` 부재·`/runs` 필터 기존재 등)을 독립 검증 에이전트
  3개가 코드 대조로 전부 확인했다. CONFIRMED 22건 / REFUTED 0건 — 이견 없이 전건 수용.
- **본문 통합**: 로드맵 §0~§9에 반영 — 기준 커밋 정정(bc514cd=T-154), 수율 수치 정정,
  §1.5(추가 확정 문제 C1~C10), §2.4(반영 판단 12항), §3 목표 상태 보강(raw grounding 게이트·
  soft delete·envelope·rollout 완결), §4 전면 교체(10단계 실행 순서 + Agent A/B 트랙 분배 +
  교차 선행), §5에 신규 PR-29~34(Phase -1 정책·exclude_video hotfix·provenance·envelope·
  key 회전·stage events)와 28개 전 PR "개정(2026-07-13)" 항목 삽입, §6 금지 5항 추가,
  §7.1 acceptance gate G1~G10, §8·§9 갱신, §10에는 반영 완료 표기(원문 보존, 본문 우선).
- **작업 등재**: `docs/tasks.md` 대기 섹션에 T-158~T-192(35건)를 두 트랙으로 등재 —
  **Agent A**(T-158~T-173): Phase -1 정책, hotfix, soft delete 상태 모델, LLM 게이트웨이,
  stage events·lineage·attention, 레인, transcript 관측, raw grounding, identity gate,
  병합 제안, description/whisper, 캐시, outbox, [게이트] 병렬화·vision. **Agent B**(T-174~
  T-192): provenance, 키 스코프+소비자 회전, envelope 계약, 목록 수리, 검수 UX 시리즈
  (자동 다음·재시작·폴링·payload·검색·undo·bulk·분해·triage), SQL 푸시다운, features/themes/
  MCP/IA. 교차 선행(T-180·181←T-162, T-182 grounding←T-165, T-184·185←T-160 등)은
  로드맵 §4.2에 명시.
- **검증(문서)**: `git diff --check`, §2.2 번호·상호참조 정합 재확인.

## 2026-07-12: T-157 후속 — 개선 로드맵 Codex 상세 리뷰

- **검토 기준**: 최신 `origin/main` `52e64d2`를 받은 뒤
  `docs/improvement-roadmap-2026-07.md`와 프런트엔드·FastAPI·ETL·scheduler·PostgreSQL 모델,
  ADR·과거 실측·형제 소비자 계약을 대조했다.
- **반복 검토**: 사용 편의성/job 운영, 데이터 신뢰성/외부 API, 코드 사실성/DB 제약의
  적대적 검토 3건을 독립 수행하고, 각 검토가 다른 결론을 반박하는 2회차 교차 검증을 수행했다.
  NCP Maps와 NAVER Local Search 약관 혼용, Kakao cache 전면 금지, geocoding 호출 자체의
  grounding 선행 주장처럼 과도한 1차 의견은 철회·완화했다.
- **판정**: 방향은 유효하나 실행계획은 수정 후 승인으로 판정했다. candidate hard delete와
  export tombstone/undo의 모순, 검수 선택 address/provider provenance 유실, raw grounding의
  자동확정 차단 누락, 외부 정책 Phase -1, 실제 소비자 read-key rotation, LLM gateway/lane 순서,
  목록 pagination envelope 등 BLOCKER 7건을 확정했다.
- **산출물**: 원문을 수정하지 않고 같은 파일 하단 §10에 유지할 판단, BLOCKER 근거,
  PR-01~28(+20a)별 수정 의견, 최대 10단계 재정렬, acceptance gate를 상세히 덧붙였다.
  사용자 리뷰 전에는 §9의 T-158 이후 backlog와 ADR을 선반영하지 않는다.
- **검증**: Markdown 문서 변경만 수행했으며 `git diff --check`와 문서 구조·링크 검사를 통과했다.

## 2026-07-12: T-157 — 개선 로드맵 문서 작성 (적대적 검토 기반)

- **방법**: 서브시스템 이해 분석 4건(프런트엔드/파이프라인/공급 API/문서 이력) → 적대적 검토
  3건(사용 편의성·속도·데이터 신뢰성+외부 API 실용성) → 검토별 사실 검증·가치 검증 교차 반박
  6건 → 최종 판단 → 문서 자체 반복 리뷰 2회(비평 에이전트 6건)로
  `docs/improvement-roadmap-2026-07.md`를 작성했다.
- **핵심 진단**: (1) 검수 큐가 "큐 처리"가 아닌 "목록 브라우징"으로 설계돼 T-150~156 연속 땜질의
  근원, (2) 워커·작업 내부 I/O·rate limiter의 직렬 3중 구조가 속도 병목, (3) 자막 실패 원인
  소실(수율 11~30%)과 지오코딩 무검증 자동확정(T-113 전력)이 신뢰성 급소, (4) 공급 키 무스코프
  인증이 공개 노출 prod의 P0 보안 리스크.
- **산출물**: 7 Phase / 28 PR(+PR-20a) 실행 계획 — 각 PR에 변경 파일·작업 절차·검증·완료 기준을
  다른 에이전트가 단독 수행 가능한 수준으로 명시. 측정 게이트(PR-16 triage 재설계 / PR-19 프레임
  비전 / PR-24 자막 병렬화), 채택·수정·기각 판단 사유, 하지 말아야 할 것, 측정 지표, 백로그 포함.
- **문서 리뷰**: 1회차(완결성·방향·실행가능성 3렌즈)에서 BLOCKER 2건(PR-22의 존재하지 않는
  `extracted_place_candidates.updated_at` 전제, PR-24 게이트용 단계별 로그 누락)과 MAJOR 10건을,
  2회차(반영 검증·신규 코드 대조·전체 재독)에서 MAJOR 6건(PR-01 화이트리스트 prefix 모순,
  PR-04 restart lane 누락·구 job id 잔존 등)을 발견해 전부 반영했다. 코드 인용은 리뷰
  에이전트들이 실코드 대조로 확인(구조적 오류 0건).
- **후속**: 사용자 리뷰 후 문서 §9에 따라 tasks.md 대기 작업 등재(T-158~)와 ADR 3건 보강을 진행한다.

## 2026-07-12: T-156 — 검수 큐 행 전체 클릭 선택 보강

- **증상 재확인**: n150에서 검수 큐 행을 직접 계측하니 후보명/위치 힌트 텍스트 위를 누르면 선택되지만,
  같은 행의 여백, 출처 칸 오른쪽, 상태 칸을 누르면 선택이 바뀌지 않았다. 사용자가 보기에는 같은 검수
  아이템을 눌렀는데 한 번에 안 되거나 늦게 반응하는 것처럼 느껴지는 상태였다.
- **수정**: 검수 후보 행 전체를 선택 표면으로 확장했다. 후보명/위치 힌트는 별도 버튼 대신 행 클릭으로
  선택되며, 체크박스·재처리 선택·상세·삭제 같은 명시 액션은 `data-row-action`으로 분리해 기존 동작을
  유지한다. 키보드 사용자는 행에 포커스를 둔 뒤 Enter/Space로 후보를 선택할 수 있다.
- **검증**: frontend `npm run lint`, `npm run type-check`, `npm run build`, `npm run test`
  (vitest 29 passed), `git diff --check` 통과.

## 2026-07-12: T-155 — 검수 큐 후보 클릭 응답성 개선

- **증상**: n150 배포 후 검수 페이지에서 후보를 클릭해도 반응이 늦고, 특히 검수 큐의 위치/출처 칸을
  눌렀을 때 클릭이 한참 뒤 처리되는 것처럼 보였다. 자동 장소 검색·지도 갱신이 후보 선택과 같은
  이벤트에서 바로 시작되고, 위치/출처 칸은 후보 선택이 아니라 재처리 장바구니 토글이라 사용자가
  기대한 선택 동작과 어긋났다.
- **수정**: 후보명뿐 아니라 위치/출처 텍스트 클릭도 같은 후보 선택 동작을 하도록 바꿨다. 영상
  재처리 선택은 위치 텍스트 아래의 작은 명시적 버튼으로 분리해, 위치를 눌렀는데 장바구니 패널이
  생기며 레이아웃이 밀리는 혼란을 없앴다.
- **응답성 보강**: 후보 선택 시 진행 중 장소 검색 취소와 새 자동 검색 시작을 모두 120ms 뒤로 미뤘다.
  이렇게 후보 선택 표시와 확정 정보 폼 초기화가 먼저 렌더링되고, Google/Kakao/Naver 검색과 지도
  후보 갱신은 그 다음 틱에서 시작된다. 검색 버튼 수동 실행과 검색 중지는 기존처럼 즉시 동작한다.
- **검증**: frontend `npm run lint`, `npm run type-check`, `npm run build`, `npm run test`
  (vitest 29 passed), `git diff --check` 통과.

## 2026-07-10: T-154 — 검수 큐 첫 진입 성능 개선과 Google Places 403 재진단

- **검수 큐 병목**: T-152에서 payload는 줄였지만 프런트가 여전히 첫 진입부터
  `/destinations/unmatched?limit=2000` 전체를 받아 2,000행을 DOM에 올리고, 15초마다 같은 큰 목록을
  자동 갱신했다. n150 기준 기존 응답은 2,000건/약 541KB/약 0.13초로 서버보다는 브라우저 JSON 파싱과
  행 렌더링 부담이 컸다.
- **프런트 개선**: 검수 페이지 초기 조회를 최신 300개로 낮추고, 필요하면 "후보 더 불러오기"로 300개씩
  최대 2,000개까지 확장하게 했다. 그룹 필터를 바꾸면 다시 300개부터 조회한다. 자동 refetch는
  15초에서 60초로 완화해 화면 조작 중 큰 목록이 자주 교체되지 않게 했다.
- **백엔드 개선**: `extracted_place_candidates`에 검수 큐 최신순/출처 필터용 복합 인덱스
  (`match_status,id`, `source_channel_id,match_status,id`, `source_playlist_id,match_status,id`)를
  추가하고, 검색어별 필터 join을 위해 `youtube_videos.source_search_query` 인덱스를 추가했다.
  Alembic revision은 `20260710_0015`다.
- **Google Places 403 분석**: prod에서 `google_places_api_key`는 DB 저장값 없이 env fallback으로 실제
  설정되어 있었고, 같은 검색에서 Kakao/Naver는 각각 5건을 반환했다. Google만
  `Google Places 403: ... PERMISSION_DENIED ... The caller does not have permission`을 반환하므로
  호출 코드 형식 문제가 아니라 Cloud Console의 key application restriction 또는 API restriction
  설정 문제로 재확인했다. 백엔드 테스트에는 Google 오류 본문 보존 케이스를 추가했다.
- **검증**: backend compileall, `pytest --capture=no` 전체 133 passed/170 skipped, frontend
  `npm ci`/audit 0, type-check, lint, vitest 29 passed, `next build --webpack`, Alembic head 확인,
  `git diff --check` 통과.

## 2026-07-06: T-153 — 수집 페이지 전폭 활용(콘텐츠 래퍼 flex-col 버그 수정)

- **근본 원인**: 수집 페이지 `AppShell` 콘텐츠 래퍼가 `flex`(row)라 자식 `CollectWorkspace`가 교차축
  stretch를 못 받아 콘텐츠 폭이 아니라 내부 grid의 내재 폭(≈997px)으로만 잡혔다. 1920px에서 콘텐츠
  영역은 1648px인데 반복 작업 표가 981px에 머물고 우측이 ~650px 비었다(검수 페이지는 `flex-col`이라
  전폭이었다). T-152의 grid 재조정만으로는 이 래퍼 버그를 못 고쳤다.
- **수정**: collect 페이지 `contentClassName`에 `flex-col`을 추가(검수 페이지와 동일 패턴)하고
  `CollectWorkspace` 루트에 `w-full min-w-0`를 더해 워크스페이스가 콘텐츠 폭 100%를 채우게 했다.
  반복 작업 표가 981→1583px로 전폭 확장(라이브 DOM 측정으로 확인). frontend tsc/build 통과.
  n150 UI 배포 후 시각·로그인 검증.

## 2026-07-05: T-152 — 수집 폭 활용·검수 payload 경량화·테마 POI API·API 테스트 페이지

- **수집 페이지 폭 활용**: 상단 밴드 grid를 `minmax(24rem,38rem)_1fr`(폼 좌측 캡 + 우측 대형 여백)에서
  `minmax(0,1.7fr)_minmax(20rem,1fr)`로 재조정하고, 수집 폼 필드를 넓은 화면에서 2열로 배치(핵심
  입력인 대상 유형·대상값·기본 카테고리만 전폭)해 좌측 폼 영역이 폭을 채우게 했다.
- **검수 큐 payload 경량화**: `/destinations/unmatched?limit=2000` 응답을 실측하니 3.8MB 중 57%가
  리스트 UI가 쓰지 않는 `provider_evidence_json`이었다(서버 쿼리 자체는 ~49ms로 빠름 — 병목은
  payload 크기·네트워크·클라 파싱). 리스트 전용 경량 payload `_candidate_list_payload`를 추가해
  원본 evidence는 빼고 파생값(8자리 카테고리 코드)만 서버에서 계산해 넣는다. 응답 3.8MB→~1.3MB.
  상세 근거는 후보 상세 엔드포인트에서 그대로 개별 조회한다.
- **테마 중심 POI 공급 API(ADR-35)**: 외부 소비자가 "특정 테마 중심으로 POI를" 가져가도록
  `ktc/services/theme_service.py`와 3개 엔드포인트를 추가했다. `GET /api/v1/themes`(테마 목록+POI
  수), `GET /api/v1/themes/places?kind=channel|playlist|keyword&value=`(유튜버/재생목록/보정 검색어
  테마 POI), `GET /api/v1/themes/video/{video_id}/places`(동영상 테마 — **매치/검수 완료 POI 5개
  이상일 때만** `places`를 채우고 미만이면 `sufficient=false`+빈 목록). 확정 POI/근거 계산은
  `place_service.list_place_summaries`(결과 보기와 같은 출처 필터)를 재사용한다. X-API-Key
  규약(ADR-24)을 그대로 상속한다. `tests/test_theme_service.py` 6케이스 통과.
- **외부 API 테스트 페이지**: 관리 nav에 `API`를 추가하고 `/api-test`에서 features·themes 엔드포인트를
  골라 파라미터를 넣고 호출해 상태·지연·건수·응답 본문을 확인한다(same-origin BFF 경유로 서버 키
  자동 주입). 외부 호출용 curl 예시(공개 키 placeholder)도 복사 제공한다.
- **검증**: frontend eslint/tsc/vitest/build, backend compileall + `test_theme_service`(6)·
  `test_place_service`·`test_feature_export_api` 통과. n150 배포 후 live UI E2E(API 테스트 페이지
  실행+HTTP 200 확인 포함)와 테마 API 라이브 스모크로 확인.

## 2026-07-04: T-150 — 유지보수 UI/UX 개편 (공용 컴포넌트·validation 강화·툴팁 도움말)

- **shadcn 프리미티브 확장**: `@base-ui/react` 기반으로 `ui/checkbox`, `ui/switch`, `ui/textarea`,
  `ui/popover`, `ui/alert-dialog`를 추가했다(kor-travel-map admin primitive와 동일 규칙,
  DESIGN-RULES 5의 hit area 보강 포함). 화면 곳곳의 raw `<input type="checkbox">`·`<textarea>`를
  전부 교체했다.
- **확인 다이얼로그 통일**: `window.confirm` 3곳(검수 선택/개별 삭제, 작업 상세 재실행)을
  공용 `ConfirmActionButton`(AlertDialog)으로 교체하고, 확인 없이 즉시 지워지던 수집 반복 작업
  삭제와 설정 공개 API 키 폐기에도 같은 확인 흐름을 추가했다.
- **중복 컴포넌트 공용화**: StatusDashboard/JobDetailView/작업 상세 페이지/다이얼로그에 복붙돼
  있던 `MetricCard`/`Panel`/`Section(DashboardGroup)`/`Metric`/`CountList`/`EmptyState`/`PanelHeader`를
  `components/panels.tsx`로, `DetailSection`/`DetailRow`를 `components/detail.tsx`로,
  복사 버튼을 `components/CopyButton.tsx`로 모았다. 날짜·용량·간격 포맷터도 `lib/format.ts`
  단일 출처로 정리했다. 사용처가 없던 `AppNav`/`SettingsDialog`/`OpsMetricsDialog`(설정 화면과
  중복되는 사장 코드 약 1,000줄)를 삭제했다.
- **validation·assist 강화**: 수집 폼에 backend `source_resolve.classify_source_input`을 이식한
  `lib/youtube.ts`(vitest 단위 테스트 포함)를 붙여 "자동 인식: 재생목록/영상/채널/검색어" 미리보기와
  유형별 형식 검증(영상 ID·재생목록 URL)을 추가했다. 검수 확정 정보에는 위도·경도 숫자 검증과
  대한민국 범위 경고를, 설정 사전 프롬프트에는 backend 상한(4,000자)과 같은 글자 수 카운터를
  추가했다. 수집 시작 성공 시 작업 링크("진행 상황 보기")를 보여준다.
- **간결한 카피 + 툴팁 도움말**: 화면에 상시 노출되던 긴 설명 문구를 걷어내고, 상세 설명이 필요한
  필드(대상 유형, 최대 영상 수, 강제 다운로드, 반복 검색/횟수, 기본 카테고리, 사전 프롬프트,
  공개 API 키)는 라벨 옆 `HelpTip`(클릭형 popover — 터치에서도 동작)으로 옮겼다.
- **backend 견고성(부수)**: 리뷰에서 발견한 P1 — 수집 입력에 불균형 `[`가 들어오면
  `urlparse`가 `ValueError`로 500을 내던 문제를 `_safe_urlparse` 폴백(비URL 취급)으로 수정했다.
  frontend 판별과 legacy custom URL(`youtube.com/이름/videos`) 채널 판별도 backend와 일치시켰다.
- **E2E 정리**: live 스펙은 checkbox role(`getByRole('checkbox')`)과 AlertDialog 확인 흐름으로
  갱신했고, 로컬 시드 스펙(`ktc.spec.ts`)에 live 모드 skip 게이트를 넣어 n150에서
  `npx playwright test`가 live 스펙만 실행하게 했다(이 저장소 E2E에는 백업/리스토어 스펙이 없음 —
  해당 시나리오는 docker-manager 쪽 하니스 소관).
- **검수 큐 성능 회귀 수정**: 첫 live E2E에서 검수 큐(실데이터 2,000행) 선택/버튼 클릭이
  수 초 이상 멈추는 회귀를 발견했다. 행마다 `ConfirmActionButton`(AlertDialog root)을 두고
  memo 없이 전 행이 재렌더된 것이 원인 — 행을 `CandidateRow`(`React.memo` + `useCallback`
  안정화)로 추출하고 행 삭제 확인은 페이지 공용 단일 AlertDialog로 바꿔 해결했다.
  live 스펙 기본 30초는 실데이터·실제 provider 검색 기준으로 빠듯해 60초로 상향했다.
- **검증**: vitest(신규 youtube 판별 테스트 포함) / eslint / tsc / `next build --webpack` 통과,
  자체 적대 리뷰 워크플로(4렌즈 → 반박 검증)로 확인된 11건(P1 1건 포함)을 모두 수정 또는
  코드 주석으로 문서화. n150 배포(런북 절차: env 재적용 + 로그인 POST 200/401 + 공개 도메인
  200) 후 live UI E2E 4/4 통과 (이 저장소 하니스에는 백업/리스토어 스펙 없음).
- **E2E 실행 위치(ADR-33 fallback 기록)**: n150 직접 실행은 OS가 Ubuntu 26.04로 올라가
  Playwright가 `chromium on ubuntu26.04-x64` 미지원을 선언하고 기존 캐시 브라우저도
  `libatk-1.0.so.0` 결손으로 기동 불가 → Windows 호스트에서 같은 live 스위트를
  `E2E_FRONTEND_URL=http://<n150>:12605`로 fallback 실행했다(검증 대상은 동일하게 n150
  live 인스턴스). n150에서 재실행하려면 Playwright의 Ubuntu 26.04 지원 또는 컨테이너
  기반 하니스가 필요하다.

## 2026-07-01: T-151 — Google Places 403 진단 강화 (부수 수정)

- 검수 장소 검색의 Google Places 호출이 403일 때 `raise_for_status()`가 Google 에러 본문
  (`SERVICE_DISABLED`/`API_KEY_HTTP_REFERRER_BLOCKED` 등 원인)을 버리던 것을, 본문 일부를 예외
  메시지에 실어 `/place-search` 응답 `errors.google`로 노출하도록 수정했다. prod 진단으로 실제
  원인이 API 키 제한(`PERMISSION_DENIED`, details 없음)임을 확인 — Cloud Console 키 설정
  (Application restrictions/API restrictions)에서 해결할 항목.
