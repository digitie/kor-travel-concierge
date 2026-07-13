# T-173 (PR-19) 프레임 비전/OCR 실험 경로 — 착수 계획서 [게이트 대기]

> **상태: 게이트 대기 — 지금 구현하지 않는다.** 아래 게이트 판정(부록 A)이 GO일 때만 착수한다.
> 이 문서는 게이트가 열리는 즉시 다른 에이전트가 그대로 실행할 수 있도록 작성된 실행 계획서다.
> 2렌즈 검증 결과: **정확도 accurate**. 착수 전 부록 B의 반영 항목을 먼저 적용한다.

---

# T-173 / 로드맵 PR-19 — 프레임 비전(OCR) 실험 경로 착수 계획서 (게이트 태스크)

> 상태: **게이트 미개방 시 착수 금지**. 본 문서는 게이트가 열리는 즉시 실행 가능한 상세 계획이다.
> 리포지토리 HEAD 기준 실측 확인 결과: 후보 격리 배관(EvidenceSourceKind.VISUAL / QueueReason.VISUAL_ONLY /
> source_kind→visual_only 파생 / `_RECALL_SOURCE_KINDS`)은 **이미 선행 작업(T-182/T-183)에서 대부분 배선되어 있다.**
> 따라서 PR-19의 실제 신규 코드는 (a) 프레임 추출+비전 1콜 모듈, (b) geocode 자동확정 예외에 VISUAL 추가,
> (c) 격리 플래그·비용 상한, (d) 썸네일 서빙(Agent B) 이다.

---

## 0. 실측으로 확인된 현재 상태 (추측 아님)

| 항목 | 상태 | 앵커 |
|---|---|---|
| `EvidenceSourceKind.VISUAL = "visual"` | **이미 존재** | `backend/ktc/models/feature_evidence.py:15` |
| `QueueReason.VISUAL_ONLY = "visual_only"` | **이미 존재** | `backend/ktc/services/place_service.py:128` |
| queue_reason 파생: `source_kind==VISUAL → visual_only` | **이미 배선** | `place_service.py:2038-2041` (`_candidate_queue_reason_expression`) |
| 검수 큐 `source_kind` 필터(=visual) | **이미 존재** | `routes.py:1382,1409` / `list_unmatched_candidates_page` |
| dedup 우선순위 recall 집합 `{description, visual}` | **이미 존재** | `batch_poi_service.py:120-129` (`_RECALL_SOURCE_KINDS`) |
| `MediaAsset` + `AssetType.FRAME` + `media_assets` 테이블 | **이미 존재** | `models/media_asset.py:18-53` |
| 프레임 인프라(스트림 URL·FFmpeg input seeking·RustFS 기록) | **이미 존재** | `etl/frame_extraction.py` |
| 멀티모달 게이트웨이(1콜, responseSchema, rate limiter) | **이미 존재** | `etl/llm_client.py:553` `generate_multimodal` |
| geocode 자동확정 예외 — **DESCRIPTION만** | **VISUAL 누락(수리 대상)** | `etl/geocode_service.py:462` |
| `VISUAL_EXTRACTION_ENABLED` 플래그 | **없음(신규)** | `core/config.py` |
| `visual_extraction.py` 모듈 | **없음(신규)** | — |

핵심 함의: **source_kind/queue_reason/enum에 대한 DB 마이그레이션은 불필요**하다 —
`source_kind`·`asset_type`·`queue_reason` 관련 컬럼은 모두 PG enum이 아니라 `String(32)`이고
(`extracted_place_candidate.py:123`, `media_asset.py:30`) 필요한 값 문자열이 이미 파이썬 enum에 존재한다.

---

## 1. 게이트 판정 (필수 절차)

### 1.1 착수 조건 (GO)
아래 3개가 **모두** 참일 때만 착수한다:
1. **지표 트리거**: PR-11~14·17·18(=T-161~T-171 계열) 배포 후 **2주 관측 창**에서
   **"유효 원료 전무 영상 비율" > 20%**.
2. **정책 승인**: **B4/PR-29 provider 정책(원본 미디어 저장·다운로드 kill switch) 승인 완료**
   (`docs/provider-policy.md` 확정). 미승인 시 배포 금지(§5).
3. **선행 완료**: T-158(kill switch·provider 정책), T-161(멀티모달 게이트웨이) 병합됨. (둘 다 완료)

### 1.2 "유효 원료 전무 영상 비율" 정의 (데이터 원천, 실제 컬럼)
- 분모(processed): 관측 창 안에서 자막/전사 단계에 진입한 영상 = `transcript_attempts`(T-164,
  `models/transcript_attempt.py`)에 시도 row가 존재하는 영상.
- 분자(no-material): 그 중 **자막·whisper 전 provider 실패**(`youtube_videos.transcript_source IS NULL`
  AND `youtube_videos.transcript_failure_code IS NOT NULL`, `models/youtube_video.py:101-102`)
  **이면서 description 경로도 후보를 못 낸**(soft-delete 제외한 `extracted_place_candidates`가 0건) 영상.
  - **왜곡 방지 규약(로드맵 명시)**: description이 후보를 냈으면 품질과 무관하게 "원료 확보"로 집계 →
    `NOT EXISTS (extracted_place_candidates WHERE deleted_at IS NULL)`로 표현. description 후보는
    `source_kind='description'`으로 이미 생성되므로(`batch_poi_service.py:677`) 이 조건이 그 규약을 그대로 구현.
  - whisper는 별도 컬럼이 아니라 `transcript_failure_code`가 "전 provider 최종 실패"를 대표하므로
    (`transcript_attempts`가 provider별 상세) 위 조건이 자막+whisper 실패를 함께 포함한다.

### 1.3 실행 가능한 게이트 SQL (gate_query 필드와 동일)
```sql
WITH processed AS (
    SELECT DISTINCT ta.video_id
    FROM transcript_attempts ta
    WHERE ta.started_at >= now() - interval '14 days'
),
no_material AS (
    SELECT p.video_id
    FROM processed p
    JOIN youtube_videos v ON v.video_id = p.video_id
    WHERE v.transcript_source IS NULL          -- 자막·whisper 전 provider 성공 없음
      AND v.transcript_failure_code IS NOT NULL -- 최종 실패 확정
      AND NOT EXISTS (                          -- description 경로도 후보 0건 → 원료 전무
          SELECT 1 FROM extracted_place_candidates c
          WHERE c.video_id = p.video_id
            AND c.deleted_at IS NULL
      )
)
SELECT
    (SELECT count(*) FROM no_material)                                            AS videos_no_material,
    (SELECT count(*) FROM processed)                                             AS videos_processed,
    round(100.0 * (SELECT count(*) FROM no_material)
          / NULLIF((SELECT count(*) FROM processed), 0), 1)                      AS pct_no_material;
```
착수 임계: `pct_no_material > 20.0` (표본이 유의미하려면 `videos_processed >= 50` 권고).

### 1.4 NO-GO / 백로그 조건
- `pct_no_material <= 20`: 백로그 유지, 착수하지 않는다.
- `videos_processed < 50`: 표본 부족 — 관측 창을 연장하고 재측정(판정 보류).
- **B4/PR-29 미승인**: 지표가 넘어도 착수 금지(정책 선행). 백로그에 "정책 대기" 표시.

### 1.5 착수 결정 시 대안 비교(journal 의무 절차)
착수 전 `docs/journal.md`에 **§2.2 ② 제3안(Gemini URL 분석 승격)** 대비 아래 표를 남긴다(택일 근거):

| 축 | PR-19 프레임 비전(본안) | 제3안: Gemini URL 분석 승격 |
|---|---|---|
| 비용 | 영상당 vision **1콜**(프레임 N장 inline) — 상한 코드 강제 | 영상당 URL 1콜이나 **장영상 토큰 폭증**(263 tok/s, 10~30분 = 26만~47만 토큰; `llm_client.py:64-70` 주석) |
| 구현량 | 신규 모듈+geocode 예외+플래그+썸네일 UI (본 계획 §3) | `video_analysis_service`(이미 존재, `:262-277`) 재사용 — 소규모 |
| 품질 | 간판·하드섭·지도라벨 OCR — 자막 없는 영상의 실질 화면 텍스트 | URL 분석은 이미 T-064에 존재; 자막 실패 영상엔 이미 시도되나 신뢰도 낮음 |
| 저장 정책 | 프레임 추출(스트림 seek, 다운로드 없음) — ADR-15/B4 긴장 (§5) | 원본 미저장, 정책 마찰 최소 |

표를 근거로 택일하고 결과·사유를 journal에 기록한 뒤 착수한다.

---

## 2. 범위 · 파일 소유

### 2.1 Agent A (백엔드 — 본 태스크 소유)
- 신규 `backend/ktc/etl/visual_extraction.py`
- `backend/ktc/core/config.py` — `VISUAL_EXTRACTION_ENABLED`, 프레임 수/상한/모델 config
- `backend/ktc/etl/geocode_service.py` — 자동확정 예외에 VISUAL 추가(핵심 수리)
- `backend/ktc/etl/batch_poi_service.py` — 후보 생성 로직 공용화(refactor, description/visual 공유)
- `scheduler/worker.py` — 신규 job type `visual_extraction` handler 등록 + batch 레인 enqueue
- `backend/ktc/models/feature_evidence.py` — 이미 VISUAL 존재(변경 없음)
- `backend/tests/` — §4
- 문서: `docs/provider-policy.md`(프레임 스트림 취득 게이트 명시), `docs/decisions.md`(신규 ADR), `docs/journal.md`, `docs/tasks.md`

### 2.2 Agent B (프런트/서빙 경계 — 별도 조율)
- **media asset 서빙 BFF/프록시**: 현재 프레임을 서빙하는 엔드포인트가 **없다**(routes.py에 media asset GET 없음,
  `MediaStore`는 `get_object`만 노출, `media_store.py:71`). Agent B가 `require_admin_proxy`(routes.py:2734 계열)
  경유 프레임 바이트 프록시 또는 서명 URL 라우트를 추가.
- 검수 상세 화면의 **프레임 썸네일 UI**(`provider_evidence_json.visual.frames[].asset_id` + timestamp 소비).
- 검수 큐 `source_kind=visual` 배지/필터 노출(직렬화는 이미 queue_reason=visual_only 반환).

> 경계 원칙: Agent A는 후보·evidence·asset_id까지만 만든다. asset_id→바이트 서빙과 UI는 Agent B.
> B4/PR-29 승인 전에는 배포하지 않으므로 A/B 병합은 게이트+정책 승인 뒤 동시 배포.

---

## 3. 단계별 구현 (코드 앵커)

### 단계 1 — 신규 `backend/ktc/etl/visual_extraction.py`
- **대상 선별(SQL)**: `youtube_videos.transcript_source IS NULL AND transcript_failure_code IS NOT NULL`
  (자막 최종 실패, `youtube_video.py:101-102`) + 아직 visual 후보/시도가 없는 영상. `duration_seconds`
  (`youtube_video.py:49`)로 프레임 간격 산정.
- **프레임 추출(인프라 재사용)**: `frame_extraction.resolve_stream_url_ytdlp(video_url)` 1회
  (`frame_extraction.py:143`) → 균등 간격 timestamp N개 계산(기본 8, duration 기반, 앞뒤 5% 트림) →
  각 timestamp에 `frame_extraction.extract_jpeg_with_ffmpeg(stream_url, ts)`(`:166`, 다운로드 없이 seek).
  RustFS 저장은 `media_store.store_and_record(asset_type=AssetType.FRAME, ...)`(`media_store.py:174`,
  object_key는 `build_frame_object_key`, `frame_extraction.py:101`), `place_id=None`, `video_id` 세팅.
  - **주의(ADR-15/B4)**: 프레임 JPEG의 RustFS "저장"은 원본 미디어 저장 정책 대상이다. `RAW_MEDIA_STORE_ENABLED`
    (config.py:225)와 별개로 프레임 스트림 취득 게이트가 현재 없음(provider-policy 주석 config.py:221 명시).
    PR-19는 프레임 저장을 `VISUAL_EXTRACTION_ENABLED`로 격리하고, B4 kill switch와의 관계를
    `docs/provider-policy.md`에 명시한다(§5).

### 단계 2 — Gemini flash 멀티이미지 **1콜/영상** (게이트웨이 경유)
- `llm_client.generate_multimodal(runtime, parts=[...], response_schema=VISUAL_OCR_SCHEMA, ...)`
  (`llm_client.py:553`). `parts` = `[{"inline_data": {"mime_type":"image/jpeg","data": <b64>}} × N]` + `[{"text": prompt}]`.
  기존 file_data 소비자(`video_analysis_service.py:271-277`)와 동일 계약, quota reservation·rate limiter 자동 통과.
- 프롬프트: "각 프레임 화면 내 텍스트(간판·하드섭 자막·오버레이·지도 라벨)를 추출하고 장소명 후보를 JSON으로"
  — responseSchema 강제(프레임 index·추출 텍스트·후보명). PaddleOCR 로컬은 2순위 백로그(주석만).
- **1콜 상한을 구조적으로 강제**: 함수는 영상당 `generate_multimodal`을 **정확히 1회** 호출한다
  (반복/재분할 금지). N > `VISUAL_FRAME_MAX`면 N을 상한으로 clip.
- **비용 추정 리스크(적대적, §5)**: `_estimate_gemini_tokens`(`llm_client.py:317`)는 media part당
  `MULTIMODAL_MEDIA_TOKEN_SURCHARGE=65_536`(`:70`)을 더한다 — 이는 **영상 file_data용 하한**이지 정지
  이미지용이 아니다. 8프레임 = 524k 예약 토큰 → 무료 티어 TPM(250k) 초과로 예약 단계 stall 위험.
  대응: (a) 기본 N=6, (b) `llm_client`에 inline image 전용 저-가산(예: 이미지당 ~1,300 tok) 분기를 추가
  (Agent A 소유이므로 가능) — parts에 `inline_data`가 있으면 file_data와 다른 계수 적용.

### 단계 3 — 추출 텍스트를 description과 **동일 규약**으로 batch POI 투입
- description 경로(`batch_poi_service.py:329-352`)와 대칭으로, 비전 추출 텍스트를 batch item으로 구성:
  `{video, source_kind: EvidenceSourceKind.VISUAL.value, corrected: <ocr_text>, raw_text: <ocr_text>,
  transcript_source: "visual", asset_id: None, frames: [{asset_id, timestamp_seconds, frame_index}]}`.
- 후보 생성은 `batch_poi_service`의 후보 생성 루프(`:611-722`)를 **공용 헬퍼로 refactor**하여 재사용
  (예: `_persist_candidates(session, batch, pois, summary)`), description(inline)·visual(신규 job) 공유.
  후보 evidence는 `source_kind==VISUAL` 분기에서 `provider_evidence_json.visual = {source:"video_frame_ocr",
  video_id, frames:[{asset_id, timestamp_seconds}], **common_evidence}` 로 기록(`:677-696` 패턴 대칭).
  `grounding_status`는 visual에 not_applicable 규약(transcript 전용 게이트, `feature_evidence.py:31`).
- **자동확정 금지(핵심 수리)** — `geocode_service.py:462`:
  현재 `if candidate.source_kind == EvidenceSourceKind.DESCRIPTION.value:` 만 recall 예외로 두어
  needs_review 고정한다. **VISUAL은 이 블록을 타지 않아 정상 자동확정 경로로 흘러 자동확정될 수 있다**(치명).
  → 조건을 `if candidate.source_kind in _RECALL_SOURCE_KINDS:`(또는 `in {DESCRIPTION, VISUAL}`)로 일반화하고
  review_note를 `"visual_only"`(국내 미확인 시 `"domestic_unverified"`, `:474-478` 대칭)로 세팅.
  queue_reason 파생은 이미 `source_kind==VISUAL → visual_only`(`place_service.py:2038-2041`)라 추가 배선 불필요.
- 검수 큐/dedup은 무개입(이미 `_RECALL_SOURCE_KINDS`에 visual 포함, `batch_poi_service.py:120-129`).

### 단계 4 — 격리 플래그 · 비용 상한 (config)
- `VISUAL_EXTRACTION_ENABLED: bool = False` (config.py, 기본 false — 상시 비용 0).
- `VISUAL_FRAME_COUNT_DEFAULT: int = 8`, `VISUAL_FRAME_MAX: int = 8`(상한), `VISUAL_MIN_DURATION_SECONDS`(너무 짧은 영상 스킵).
- 플래그 off면 `visual_extraction` handler는 **즉시 no-op 로그 1줄 후 반환**(store_raw_media의 kill switch
  패턴, `frame_extraction.py:230-237` 참조) — 스트림 취득·비전 호출·프레임 저장 전부 미수행.

### 단계 5 — 2실험 구분 · visual-only 검수 별도 계상
- **실험 ①(corroboration)**: 기존 후보의 `timestamp_start` 주변 프레임 OCR로 이름/간판 일치 확인 →
  기존 후보의 `provider_evidence_json.visual_corroboration`에 근거만 append(신규 후보 미생성, 검수 근거 강화).
- **실험 ②(source recovery)**: 자막 없는 영상 균등 프레임 → **신규 visual 후보 생성**(recall).
  visual-only 검수 증가는 `source_kind='visual'` audit 필터로 **별도 계상**(§7 G9, description과 동일 규약).
- 둘은 같은 모듈이되 진입점/대상 선별을 분리한다(② 우선 구현, ①은 후속 서브태스크로 분리 가능).

### 마이그레이션 필요 여부
- **불필요(핵심 경로)**: source_kind='visual', queue_reason='visual_only', AssetType.FRAME 모두
  String 컬럼의 기존 enum 값 → DDL 변경 없음. `media_assets` 테이블 존재.
- **선택적**: 관측용 `youtube_videos.visual_extraction_status`(대상 재선별 idempotency) 컬럼을 원하면
  단일 Alembic revision 추가. 최신 head는 `20260713_0025`(down_revision `20260713_0023`) →
  신규 revision은 `20260713_0025`를 down_revision으로 직렬 연결, 단일 head 유지.

---

## 4. 테스트 (`backend/tests/`, disposable PG, `KTC_TEST_PG_DSN`, conftest create_all)

1. **프레임 샘플링(길이별 개수)**: 주입형 `stream_url_resolver`/`frame_extractor`(frame_extraction Protocol,
   `:34-41`)로 FFmpeg 없이, duration=600 → 8 timestamp 균등·경계 트림, 짧은 영상(< min) 스킵 검증.
2. **후보 격리(자동확정 차단)**: visual 후보가 지오코딩 matched여도 `match_status=NEEDS_REVIEW` 유지,
   `queue_reason=visual_only`, `feature_export_status=PENDING`. **회귀 핵심**: geocode_service의 VISUAL 예외
   부재 시 자동확정되는지 실패 케이스로 못박기(수리 전이면 fail).
3. **플래그 off 완전 무개입**: `VISUAL_EXTRACTION_ENABLED=False` → handler no-op, 스트림 resolver/vision
   콜러블/`store_and_record` 미호출(mock 호출 0회 assert), 후보·media_asset 0건.
4. **비용 상한(1콜)**: `generate_multimodal` 주입 mock이 영상당 **정확히 1회** 호출, N > MAX 시 clip.
   (선택) inline image 토큰 추정 분기 추가 시 `_estimate_gemini_tokens` 저-가산 회귀.
5. **evidence 보존**: `provider_evidence_json.visual.frames[].asset_id`·timestamp가 후보에 기록.
6. **dedup 비대칭**: 자막 복구 후 transcript 후보가 기존 미검수 visual 후보를 supersede
   (`_source_kind_priority`, `batch_poi_service.py:127`) 회귀.

검증: `pytest` foreground, 변경 Python Ruff, Alembic head 왕복(선택 컬럼 추가 시), 병합 전 2렌즈 적대적 리뷰.

---

## 5. 위험 · 금지 · 적대적 리뷰 포커스

1. **자동확정 금지 확실성(최우선)**: `geocode_service.py:462`가 현재 DESCRIPTION만 예외 → VISUAL 누락 시
   **정상 자동확정 경로로 흘러 export까지 전파**. 반드시 `in {DESCRIPTION, VISUAL}`로 일반화하고 회귀 테스트로
   못박는다. grounding 게이트(`:707`)는 transcript 전용이라 visual을 막지 않으므로 이 예외가 유일한 방어선.
2. **비용 폭증**: (a) 영상당 `generate_multimodal` 1회 구조적 강제(반복 금지), (b) inline 8프레임의 65,536×8
   토큰 과예약(§3-2) → 기본 N 축소 + inline image 전용 저-가산 계수. `VISUAL_EXTRACTION_ENABLED` 기본 false로
   상시 비용 0.
3. **원본 미디어 저장 정책(ADR-15 · B4 kill switch)**: 프레임 저장은 저장 정책 대상. 프레임 스트림 취득
   게이트가 현재 부재(config.py:221 주석) → PR-19에서 `VISUAL_EXTRACTION_ENABLED`로 취득·저장 전체를 격리하고
   `docs/provider-policy.md`에 관계를 명시. YouTube Developer Policies III.E.1과의 긴장은 B4 결정을 따른다.
4. **PR-29 미승인 시 배포 금지**: 지표 게이트를 넘어도 B4/PR-29 승인 전에는 병합/배포 금지. 코드가 병합되더라도
   플래그 off + 미배포 상태로만 존재.
5. **격리 누수**: 플래그 off인데 대상 선별 SQL·스트림 취득이 도는 실수 방지 — handler 진입 즉시 플래그 검사·no-op.
6. **frame_extraction 부하**: N프레임 = N회 FFmpeg seek(스트림 URL은 1회 확보 후 재사용). batch 레인 enqueue로
   대화형 레인 잠식 방지(whisper 수동 재전사와 동일 운영 결정, config.py:193).


---

## 부록 A — 게이트 판정 SQL (실행 가능)

아래 쿼리를 실운영 데이터에 실행해 GO/NO-GO를 판정한다(판정 규칙은 본문 §1).

```sql
-- 착수 게이트: 최근 14일 관측 창에서 "유효 원료 전무 영상 비율" > 20% 이면 GO (B4/PR-29 승인·T-158·T-161 선행 별도 충족 전제)
WITH processed AS (
    SELECT DISTINCT ta.video_id
    FROM transcript_attempts ta
    WHERE ta.started_at >= now() - interval '14 days'
),
no_material AS (
    SELECT p.video_id
    FROM processed p
    JOIN youtube_videos v ON v.video_id = p.video_id
    WHERE v.transcript_source IS NULL           -- 자막·whisper 전 provider 성공 없음
      AND v.transcript_failure_code IS NOT NULL  -- 최종 실패 확정
      AND NOT EXISTS (                           -- description 경로도 후보 0건 → 원료 전무(왜곡 방지 규약)
          SELECT 1 FROM extracted_place_candidates c
          WHERE c.video_id = p.video_id
            AND c.deleted_at IS NULL
      )
)
SELECT
    (SELECT count(*) FROM no_material) AS videos_no_material,
    (SELECT count(*) FROM processed)   AS videos_processed,
    round(100.0 * (SELECT count(*) FROM no_material)
          / NULLIF((SELECT count(*) FROM processed), 0), 1) AS pct_no_material;
-- GO 조건: pct_no_material > 20.0 AND videos_processed >= 50
```


## 부록 B — 2렌즈 검증 반영 (착수 전 필수)

검증 정확도: **accurate**. 아래는 착수 시 반드시 반영할 정정·보강이다.

### 정정 (corrections)

- [§0 table / §2.2 — routes.py:1382,1409 / list_unmatched_candidates_page] The route handler at routes.py:1366 is named `list_unmatched_candidates` (source_kind Query param at :1382, passed at :1409); `list_unmatched_candidates_page` is the place_service.py function it delegates to. The plan conflates the two names.
  FIX: Reword to: route handler `list_unmatched_candidates` (routes.py:1366) accepts `source_kind` Query (:1382) and forwards it to `place_service.list_unmatched_candidates_page` (:1409). Both exist; filter is real.
- [§3 단계3 — provider_evidence_json.visual branch reuse of batch_poi_service persist loop] The shared persist loop unconditionally sets `grounding_status = grounded.status.value` from `grounding.evaluate_transcript_grounding(...)` (batch_poi_service.py:653-655,710). If VISUAL flows through the same loop unmodified, OCR text is graded as transcript grounding and yields a misleading `missing`/`unverified` verdict, contradicting the plan's stated `not_applicable` convention.
  FIX: The `_persist_candidates` refactor must branch on source_kind and set `grounding_status=GroundingStatus.NOT_APPLICABLE.value` for VISUAL (skip evaluate_transcript_grounding), per extracted_place_candidate.py:130-132 and feature_evidence.py:31 guidance. State this explicitly in step 3.
- [§3 단계2 / §5.2 — generate_multimodal usage] `llm_client.generate_multimodal` is Gemini-only and raises ValueError under the DeepSeek engine (llm_client.py:571 docstring; sole existing consumer video_analysis_service.py:262 is documented 'Gemini 전용'). The plan reuses it for visual OCR without flagging that visual extraction is unavailable / errors when runtime engine=DeepSeek (ADR-30 multi-provider).
  FIX: Add an engine guard: the visual_extraction handler must check the active engine (is_deepseek_model) and no-op/skip (like the flag-off path) when not Gemini, rather than letting the batch job raise ValueError.


### 누락 안전 규약 (missing safety)

DeepSeek-engine incompatibility: generate_multimodal raises ValueError on DeepSeek (llm_client.py:571). Visual OCR path must guard the active LLM engine (config is_deepseek_model) and skip gracefully, else the batch job errors whenever the runtime engine is set to DeepSeek.
grounding_status handling for VISUAL: the reused persist loop (batch_poi_service.py:653-710) forces transcript grounding evaluation; the refactored helper must explicitly set grounding_status=not_applicable for visual candidates so the transcript-only auto-confirm gate (geocode_service.py:707) and audit surfaces are not fed a spurious missing/unverified verdict.

