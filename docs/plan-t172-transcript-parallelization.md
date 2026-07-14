# T-172 (PR-24) 자막 fetch 병렬화 — 착수 계획서 [게이트 대기]

> **상태: 게이트 대기 — 지금 구현하지 않는다.** 아래 게이트 판정(부록 A)이 GO일 때만 착수한다.
> 이 문서는 게이트가 열리는 즉시 다른 에이전트가 그대로 실행할 수 있도록 작성된 실행 계획서다.
> 2렌즈 검증 결과: **정확도 partial**. 착수 전 부록 B의 반영 항목을 먼저 적용한다.

---

## T-172 / PR-24 — 자막 fetch 병렬화 착수 계획서 [게이트]

> 상태: **게이트 대기**. 아래 §1의 GO 판정이 통과할 때만 착수한다. NO-GO면 백로그에 유지하고 관측 창을 넓혀 재판정한다.
> 소유: **Agent A** (`backend/ktc/etl/*`, `scheduler/*`, `backend/ktc/core/config.py`, 정책/문서). 브랜치 `codex/t-172-transcript-fetch-parallel` 1개 = PR 1개(squash). 병합 전 2렌즈 적대적 리뷰(§5).

---

### 1. 게이트 판정 (GO / NO-GO)

**기준**: PR-04/05(= 실행 기준 T-161·T-162 등) 배포 후 실운영 poi_batch 벽시계에서 **자막 fetch 단계 합이 배치 전체 벽시계의 30% 이상**이면 GO. 미만이면 NO-GO(병렬화 이득이 리스크 대비 낮음).

**데이터 원천** (실제 스키마, 모두 확인함):
- 분모 = `crawl_run_stage_events` 중 `stage='poi_batch_total'`의 `elapsed_ms` — poi_batch 배치 **전체 벽시계** 1건/런. `scheduler/worker.py:451-459`가 `try/finally`로 성공·보류·실패 모든 경로에서 monotonic 실측으로 기록한다. (세부 4단계 합이 아니라 total을 분모로 쓰는 이유는 worker.py:419-423 주석에 명시 — 단계 사이 RustFS 업로드·commit·dedup 시간까지 포함해야 자막 비율이 과대 계상되지 않는다.)
- 분자 = 같은 런의 `stage='transcript_fetch'` 이벤트 `elapsed_ms` **합**(영상당 1건, 다건). 성공/실패 모두 실 비용이므로 포함. 캐시 재사용(`outcome='skipped'`)은 `started` 미전달로 `elapsed_ms≈0`이라 자연히 무시된다(`batch_poi_service.py:256-263`, `_report_stage`가 `started=None`이면 elapsed=None → `record_stage_event`가 0으로 저장).
- 런 스코프 = `crawl_runs.job_type='poi_batch'` (`backend/ktc/models/crawl_run.py:104`), 관측 창은 `crawl_run_stage_events.started_at`.

**실행 SQL (GO/NO-GO 판정)** — `gate_query` 필드 참조. 판정 규칙:
- `sample_batches >= 20` (표본 최소치; 20 미만이면 관측 창을 30~60일로 넓혀 재수집, 그래도 미달이면 트래픽 부족으로 NO-GO 유지).
- 1차 지표 `fetch_pct_weighted`(시간가중, Σfetch/Σtotal) `>= 30.0` → **GO**. `fetch_pct_median`/`fetch_pct_avg`도 함께 보고해 분포 편중(소수 긴 배치가 끄는 경우)을 확인한다. weighted와 median이 크게 갈리면(예: weighted≥30, median<20) 실사용 프로파일을 한 번 더 관측 후 결정.
- 관측 기간: 배포 후 **최소 2주** 실운영 poi_batch. 표본이 20배치 미만이면 기간 연장.

**NO-GO 처리**: 착수하지 않고 PR-24를 백로그에 유지. 단, 죽은 설정 정리(§3-E의 `HTTP_MAX_CONCURRENT_REQUESTS` 삭제)만은 무해하므로 별도 소형 위생 PR로 분리 가능(선택).

---

### 2. 범위·파일 소유·선행

**변경 파일 (모두 Agent A 소유)**:
- `backend/ktc/etl/batch_poi_service.py` — 1단계 루프를 prefetch(병렬) + 순차 적재로 재구성.
- `backend/ktc/etl/transcript.py` — 캡션 전용 체인 헬퍼 + 캡션/whisper 분리 진입점.
- `backend/ktc/etl/postprocess_service.py` — 기본 캡션 fetcher / whisper fetcher 배선.
- `scheduler/worker.py` — `poi_batch_handler`의 fetcher 주입부(현 `transcript_fetcher=` 단일 → 캡션+whisper 2개) 수정.
- `backend/ktc/core/config.py` — `CRAWL_MAX_CONCURRENT_VIDEOS` 소생(기본 4→3), `HTTP_MAX_CONCURRENT_REQUESTS` 삭제.
- `.env.example`(204-205), `docs/dev-environment.md`(234-235) — 위 설정 동기화.
- `backend/tests/test_etl_batch_poi_service.py`, `test_etl_description_path.py`, `test_crawl_run_stage_events.py` — 주입 시그니처 갱신 + 신규 병렬/가드 테스트.
- 문서: `docs/journal.md`, `docs/tasks.md`(T-172), 필요 시 `docs/provider-policy.md` 각주(whisper 동시성 1 정책).

**Agent B 무관**: frontend·검수/공급 라우트 직렬화 미변경. 응답 계약·stage 라벨 불변.

**선행 충족 확인 (모두 완료)**: T-158(provider 정책/kill switch), T-161(llm_client 게이트웨이 — 교정·LLM은 그대로 리미터 소관), T-162(`crawl_run_stage_events` = 게이트/§6 데이터 원천), T-164(`transcript_attempts` = 무회귀·G8 원천). alembic head `20260713_0025` — **이 PR은 신규 마이그레이션 없음**(설정만 변경, DB 스키마 불변).

---

### 3. 단계별 구현 (코드 앵커)

**핵심 제약 (반드시 준수)**:
- 병렬 구간은 **순수 네트워크 I/O뿐** — 주입 fetcher는 `(video_id) -> TranscriptOutcome`이며 `AsyncSession`을 절대 받지 않는다. 확인: 기본 fetcher `postprocess_service._default_transcript_fetcher`(`postprocess_service.py:370`) → `fetch_transcript_async`(`transcript.py:854`) → `asyncio.to_thread(fetch_transcript, ...)`. DB 세션 미접근.
- **whisper는 캡션과 같은 semaphore로 gather 금지.** 현재 whisper는 `DEFAULT_PROVIDERS`(`transcript.py:732-736`) 체인의 3번째 provider로 **fetch 내부에서** 실행된다(auto는 env `TRANSCRIPT_WHISPER_ENABLED` 게이트로 기본 off→`disabled`; force는 `_whisper_forced_transcript_fetcher`가 whisper-only 체인 주입). 병렬화하려면 fetch 진입 단계에서 **캡션 체인과 whisper를 분리**해야 한다.

**A. `transcript.py` — 캡션/whisper 분리 진입점 추가**
1. 상수 `CAPTION_PROVIDERS = (fetch_via_transcript_api, fetch_via_ytdlp)` 추가(whisper 제외).
2. `def caption_provider_chain() -> tuple[TranscriptProvider, ...]`: `_resolve_provider_chain()` 결과에서 `transcribe_via_whisper`를 제거해 반환(설정 순서 존중, whisper만 배제). 비면 `CAPTION_PROVIDERS`로 폴백.
3. `async def fetch_captions_async(video_id) -> TranscriptOutcome`: `to_thread(fetch_transcript, providers=caption_provider_chain())`. 캡션 attempts만 담긴 outcome 반환(순수 I/O).
4. whisper 단건: 기존 `transcribe_via_whisper`(auto 게이트)와 `whisper_forced_provider`(force) 재사용. `async def transcribe_whisper_async(video_id, *, force, model_size)`: `to_thread(transcribe_via_whisper, force=force, model_size=model_size)` 얇은 래퍼 추가.
5. attempts 병합 헬퍼 `merge_outcomes(caption: TranscriptOutcome, whisper_attempt: TranscriptAttempt | None) -> TranscriptOutcome`: caption.attempts + whisper_attempt를 sequence 재부여해 이어붙이고, whisper 성공 시 `result`를 whisper로 승격. 이로써 `TranscriptOutcome.success_provider`/`failure_code` 파생(§transcript.py:141-165)과 `transcript_attempts` 기록 형태가 **순차 체인과 동일**하게 유지된다(무회귀 핵심).

**B. `postprocess_service.py` — 배선**
- `_default_caption_fetcher(video_id)` = `fetch_captions_async(video_id)` 추가.
- `_default_whisper_fetcher(video_id)` = `transcribe_whisper_async(video_id, force=False, model_size=None)`; force 경로용 `_whisper_forced_fetcher(model_size)` 추가(기존 `_whisper_forced_transcript_fetcher`는 whisper-only 전체 체인이었으므로, 신 계약에선 whisper 단건만 담당).

**C. `batch_poi_service.process_video_batch` — 시그니처 변경 (`batch_poi_service.py:186`)**
- `transcript_fetcher` 단일 파라미터를 다음으로 대체:
  - `caption_fetcher: CaptionFetcher | None`(None이면 캡션 단계 skip = force_whisper 모드),
  - `whisper_fetcher: WhisperFetcher | None`(None이면 whisper 폴백 없음).
- 하위호환 shim은 두지 않는다(파일·테스트 모두 Agent A 소유). 기존 2개 테스트 콜사이트(`test_etl_batch_poi_service.py:68-74`, `test_etl_description_path.py:111`)를 신 시그니처로 갱신.

**D. 1단계 루프 재구성 (`batch_poi_service.py:217-471`)** — 3-페이즈로 분리:
- **Phase 1a (병렬, Semaphore=`CRAWL_MAX_CONCURRENT_VIDEOS`)**: fresh fetch가 필요한 영상 집합을 먼저 결정한다. `start_stage=='poi'`/`'correction'`이면서 저장 asset이 있는 영상은 **기존 캐시 경로 그대로 순차**(DB read이므로 병렬 대상 아님) — 현행 `batch_poi_service.py:229-290`의 캐시 분기 로직을 그대로 두되, "raw_text is None"(=새로 받아야 하는) 영상만 prefetch 대상으로 모은다. `sem = asyncio.Semaphore(get_settings().CRAWL_MAX_CONCURRENT_VIDEOS)`; `async def _one(vid): async with sem: return await caption_fetcher(vid)`; `results = await asyncio.gather(*[_one(v.video_id) for v in fresh], return_exceptions=True)`. **결과는 `dict[video_id -> TranscriptOutcome|Exception]`에 저장**하고, 이후 반드시 **원본 `videos` 순서로** 소비한다(gather 완료 순서 비의존 — alias `f"video_{index:03d}"`는 입력 순서에 묶여야 한다).
- **Phase 1b (whisper, Semaphore(1) 또는 순차)**: 캡션이 최종 실패(`outcome.result is None`)한 영상 중 whisper 대상만 골라 **동시성 1**로 실행: `wsem = asyncio.Semaphore(1)`(모듈 상수 `WHISPER_MAX_CONCURRENT=1`). `whisper_fetcher`가 None이면 skip. `caption_fetcher is None`(force_whisper 모드)이면 전 영상을 Phase 1b로만 처리. 각 영상 결과를 `merge_outcomes`로 캡션 outcome과 합쳐 최종 outcome 확정. whisper는 CPU 집약이라 gather 금지 — 반드시 순차 소비.
- **Phase 1c (순차, 공유 세션)**: 현행 루프 본문(`batch_poi_service.py:294-470`)에서 `fetched = await transcript_fetcher(...)`(295) 호출만 제거하고, prefetch dict에서 해당 영상 outcome을 꺼내 쓰도록 바꾼다. **이후 전부 순차 유지**: `attempt_recorder`(309-310, 독립 세션), `video.transcript_source/failure_code` ORM 변경(311-312), description fallback 분기(333-364), `media_store.store_and_record`(384, **공유 세션**), 교정 LLM `transcript_correction.correct_transcript`(408, 리미터 소관 — 순차 유지), 교정본 저장(454). `stage_reporter`의 `transcript_fetch` 이벤트는 Phase 1c에서 **실측 elapsed로** 기록하되, 병렬로 겹친 벽시계가 아니라 **개별 fetch 소요**를 남긴다(게이트 분자 정의와 정합 유지를 위해, prefetch 시 각 task의 monotonic 소요를 outcome과 함께 dict에 저장해 1c에서 그대로 보고). Phase 1a에서 예외로 온 영상은 현행 `except Exception … raise`(296-305)와 동일하게 fetch 실패 이벤트를 남기고 전파.
- **세션 비공유 보장**: Phase 1a/1b 동안 공유 `session`에 대한 어떤 접근도 없어야 한다(`media_store.store_and_record`·ORM flush·`session.execute`는 전부 1c). `record_stage_event`/`attempt_recorder`는 `async_sessionmaker(session.bind)`로 **독립 세션**을 쓰지만(`crawl_run_service.py:210-213`), 그래도 병렬 구간에서 호출하지 않고 1c에서 순차 호출한다(부분 커밋·race 여지 제거).

**E. `config.py` 설정 정리**
- `CRAWL_MAX_CONCURRENT_VIDEOS: int = 3` (269행, 4→3 — yt-dlp 동시 다연발 IP 스로틀 위험 완화; 캡션 Semaphore 크기).
- `HTTP_MAX_CONCURRENT_REQUESTS` 삭제(270행) + `.env.example:205` + `docs/dev-environment.md:235` 동기화. (지오코딩 병렬화는 PR-21이 대체하여 이 설정은 영구 사문화 — 참조 0회 확인함.)
- whisper 동시성은 신설 설정 없이 모듈 상수 `WHISPER_MAX_CONCURRENT=1`로 고정(정책상 1, 노출 불필요).

**F. 교정·LLM·지오코딩은 불변**: 2단계 POI 배치(`:477-578`), 3단계 후보 생성(`:580-745`), 4단계 지오코딩(`:747-795`)은 전혀 손대지 않는다. 병렬화는 오직 1단계 캡션 fetch에 국한.

---

### 4. 테스트

`KTC_TEST_PG_DSN` 격리 disposable DB, conftest `create_all`, pytest **foreground**.

1. **동시성 상한 가드 (캡션)**: fresh 영상 N=8, `caption_fetcher`가 공유 카운터를 증가시키고 `await asyncio.sleep(0.02)` 후 감소. 관측 `max_concurrent`가 `1 < max_concurrent <= CRAWL_MAX_CONCURRENT_VIDEOS(3)`임을 단언(병렬은 되되 semaphore 상한 준수).
2. **whisper 미병렬 가드**: 전 영상 캡션 실패로 두고 `whisper_fetcher`가 동시성 카운터 증가. `max_concurrent == 1`을 단언(어떤 N에서도). force_whisper 모드(`caption_fetcher=None`)에서도 동일.
3. **세션 비공유 가드**: `caption_fetcher`/`whisper_fetcher`가 `video_id: str`만 받고 세션 인자를 안 받음을 시그니처로 보장 + 병렬 구간에서 `media_store.store_and_record` 호출이 **한 건도 gather 이전에 발생하지 않음**을 순서 스파이(호출 타임스탬프 수집)로 단언. 또는 fetcher 내부에서 `session.in_transaction()` 접근 불가함을 클로저 캡처 부재로 확인.
4. **무회귀 — 사유 코드 분포 (transcript_attempts 활용, T-164)**: 캡션 결과 혼합(success / no_captions / blocked / rate_limited)을 주입하고, 병렬 경로가 기록한 `transcript_attempts`의 `(provider, outcome, sequence)` 집합이 **순차 baseline(N=1 강제)과 동일**함을 단언. whisper 폴백 병합 후 `success_provider`/`failure_code` 파생값 동일성도 확인.
5. **출력 등가성 (golden)**: 동일 입력에 대해 병렬(N>1) 결과 후보와 순차(Semaphore=1 강제) 결과 후보가 이름·순서·`provider_evidence_json`·grounding_status까지 동일. alias/순서 비의존 회귀 방지.
6. **벽시계 단축(약식)**: fetcher가 각 50ms sleep, N=6일 때 병렬 총 fetch 소요가 순차 대비 유의하게 짧음(정확한 배수 대신 `parallel_elapsed < sequential_elapsed * 0.6` 같은 느슨한 상한 — 플래키 회피).
7. **stage 이벤트 정합**: `test_crawl_run_stage_events.py` 갱신 — `transcript_fetch` 이벤트가 여전히 영상당 1건, `poi_batch_total`이 전체 벽시계 1건으로 남는지(게이트 분모/분자 정의 유지) 확인.

전체 backend pytest + 변경 Python Ruff. E2E는 자막 fetch 미경유라 영향 없음(회귀 스모크만).

---

### 5. 위험·금지·적대적 리뷰 포커스

- **[금지] whisper가 캡션 semaphore에 섞이는 회귀**: 리뷰어는 `caption_provider_chain()`이 whisper를 확실히 배제하는지, Phase 1a에 whisper 경로가 스며들지 않는지 확인. force_whisper 모드가 캡션 Semaphore를 타지 않는지(§D Phase 1b 전용) 검증.
- **[위험] yt-dlp 동시 다연발 → YouTube IP 스로틀/봇 탐지(BLOCKED/RATE_LIMITED 급증)**: 기본 동시성 3으로 하향. §6 G8에서 전후 `blocked`/`rate_limited` 비율을 **반드시** 비교하고, 착수 후 증가하면 동시성을 2로 재하향하거나 whisper처럼 yt-dlp만 별도 저동시성 레인으로 격리하는 후속을 연다.
- **[위험] 세션 race / 부분 커밋**: `AsyncSession`은 비동기 태스크 간 공유 불가(SQLAlchemy 계약). Phase 1a/1b에서 `session`·`media_store.store_and_record`·ORM flush를 절대 호출하지 않음을 리뷰에서 라인 단위로 확인. 독립 세션(`record_stage_event`/`attempt_recorder`)도 병렬 구간 밖(1c)에서만 호출.
- **[위험] 순서 의존**: gather 완료 순서로 alias/후보가 흔들리면 dedup·evidence가 어긋난다. 결과를 `video_id` 키 dict에 담아 **원본 `videos` 순서**로 소비하는지 확인. `existing_by_pair` dedup(`:591-604`)은 1c 순차라 불변.
- **[위험] 예외 전파 손실**: `gather(return_exceptions=True)`로 받은 영상별 예외가 1c에서 현행과 동일하게 fetch-실패 stage 이벤트를 남기고 처리되는지(전 배치가 1개 실패로 죽지 않도록, 그러나 실패는 관측되도록).
- **[위험] rate limiter 이중화**: 교정·POI(LLM)는 게이트웨이 리미터(T-161) 소관이므로 병렬화 대상 아님 — 캡션 fetch에만 Semaphore 적용했는지 확인(LLM 호출은 순차 유지).

---

### 6. G8 전후 비교 지표 (필수)

배포 경계(`:deploy_ts`) 전/후 창을 나눠 아래를 비교하고 PR 본문·journal에 표로 남긴다.

**(a) provider별 실패율·429·지연 — `transcript_attempts`(T-164)**:
```sql
SELECT provider,
       count(*)                                    AS attempts,
       round(100.0*avg((outcome<>'success')::int),1) AS failure_pct,
       sum((outcome='rate_limited')::int)          AS rate_limited_429,
       sum((outcome='blocked')::int)               AS blocked,
       round(avg(duration_ms))                     AS avg_ms
FROM transcript_attempts
WHERE started_at >= :window_start AND started_at < :window_end
GROUP BY provider ORDER BY provider;
```
before/after 각각 실행. **판정 회귀 신호**: after에서 `yt_dlp`의 `rate_limited_429`/`blocked` 비율이 유의 상승하면 동시성 재하향.

**(b) 자막 단계 벽시계 단축 — `crawl_run_stage_events`**: §1 게이트 SQL을 before/after 실행해 `fetch_pct_weighted`(자막 비율)와 배치당 `total_wall_ms` 중앙값 하락 확인(완료 기준: 자막 단계 2~3배 단축).

**(c) queue latency**: poi_batch 런의 대기시간(enqueue→claim) 변화를 `crawl_runs`의 상태 전이 타임스탬프로 집계(정확한 컬럼명은 executor가 `crawl_run.py`에서 확인 — created_at 기준 최소 상한). 병렬화가 배치 벽시계를 줄여 배치 레인 점유가 짧아지면 후속 런 대기시간이 감소해야 한다.

**(d) CPU**: whisper 병렬 금지가 핵심 방어. after 창에서 한 배치를 실행하며 `docker stats`(또는 호스트 관측)로 CPU 피크를 기록해 whisper 동시성 1이 유지되는지(피크가 whisper 1코어 수준) 확인. 캡션 병렬은 I/O 바운드라 CPU 영향 미미해야 한다.


---

## 부록 A — 게이트 판정 SQL (실행 가능)

아래 쿼리를 실운영 데이터에 실행해 GO/NO-GO를 판정한다(판정 규칙은 본문 §1).

```sql
-- T-172 GO/NO-GO 게이트: poi_batch 배치 벽시계 대비 자막 fetch 비율 (>=30% & 표본>=20 이면 GO)
-- 데이터 원천: crawl_run_stage_events (T-162), crawl_runs.job_type (poi_batch)
WITH batch AS (
    SELECT e.run_id, e.elapsed_ms AS total_ms
    FROM crawl_run_stage_events e
    JOIN crawl_runs r ON r.id = e.run_id
    WHERE e.stage = 'poi_batch_total'
      AND e.outcome = 'success'                    -- 완주한 배치만(보류/실패 분모 왜곡 제거)
      AND r.job_type = 'poi_batch'
      AND e.started_at >= now() - interval '14 days'
      AND e.elapsed_ms > 0
),
fetch AS (
    SELECT run_id, SUM(elapsed_ms) AS fetch_ms      -- 영상당 transcript_fetch 이벤트 합(skipped≈0)
    FROM crawl_run_stage_events
    WHERE stage = 'transcript_fetch'
    GROUP BY run_id
)
SELECT
    count(*)                                                                          AS sample_batches,
    sum(b.total_ms)                                                                   AS total_wall_ms,
    sum(coalesce(f.fetch_ms, 0))                                                      AS total_fetch_ms,
    round(100.0 * sum(coalesce(f.fetch_ms,0)) / nullif(sum(b.total_ms),0), 1)         AS fetch_pct_weighted,
    round(100.0 * avg(coalesce(f.fetch_ms,0)::numeric / nullif(b.total_ms,0)), 1)     AS fetch_pct_avg,
    round(100.0 * percentile_cont(0.5) WITHIN GROUP (
        ORDER BY coalesce(f.fetch_ms,0)::numeric / nullif(b.total_ms,0)), 1)          AS fetch_pct_median,
    CASE WHEN count(*) >= 20
              AND (100.0 * sum(coalesce(f.fetch_ms,0)) / nullif(sum(b.total_ms),0)) >= 30.0
         THEN 'GO' ELSE 'NO-GO' END                                                   AS verdict
FROM batch b
LEFT JOIN fetch f USING (run_id);
```


## 부록 B — 2렌즈 검증 반영 (착수 전 필수)

검증 정확도: **partial**. 아래는 착수 시 반드시 반영할 정정·보강이다.

### 정정 (corrections)

- [§2 변경 파일 목록 / 테스트 열거] process_video_batch 시그니처 변경과 poi_batch_handler 재배선(_default_transcript_fetcher → 신 caption/whisper fetcher)이 §2에 열거되지 않은 두 테스트를 깨뜨린다. 실측: backend/tests/test_transcript_attempts.py:115가 postprocess_service._default_transcript_fetcher를 monkeypatch하고 poi_batch 경로를 실행한다(재배선 시 no-op/파손). backend/tests/test_whisper_force.py:116이 postprocess_service._whisper_forced_transcript_fetcher("medium")를 직접 호출·검증한다(§B가 이 심볼을 whisper 단건용 _whisper_forced_fetcher로 재정의/개명하면 파손). 참고로 §C가 'process_video_batch 직접 콜사이트 2개'라 한 것은 정확하다(test_etl_batch_poi_service.py:68, test_etl_description_path.py:111만 직접 호출; test_etl_postprocess.py:93/309는 process_video_batch가 아니라 process_harvest_videos 호출이라 무관).
  FIX: §2 변경 파일에 backend/tests/test_transcript_attempts.py와 backend/tests/test_whisper_force.py를 추가하고, _whisper_forced_transcript_fetcher를 유지할지 개명(_whisper_forced_fetcher)할지 명확히 해 두 테스트의 갱신 범위를 확정한다.
- [§2 소유 헤더 — 'backend/ktc/core/config.py'] 제공된 파일 소유 규약(Agent A = etl/*, models/*, services/파이프라인·export·상태, scheduler/*, alembic/*, 정책·ADR 문서)에는 backend/ktc/core/config.py가 명시적으로 열거되어 있지 않다. config.py는 백엔드 기반 공유 설정 파일이며 Agent B(프런트/검수·공급 라우트 직렬화) 영역은 아니라 Agent A 편집이 합당하나, 규약 목록에 없어 경계가 모호하다.
  FIX: core/config.py가 Agent A 소유임을 규약(로드맵 §4)에서 명시 확인하거나, 공유 설정 파일 편집이 Agent B 동시작업과 충돌하지 않음을 착수 전 확인한다.
- [§B 3~4 — 'whisper-only 전체 체인' 표현] 기존 _whisper_forced_transcript_fetcher/whisper_forced_chain(transcript.py:724)은 '전체 체인'이 아니라 whisper 1개짜리 단일-provider 체인이다(whisper_forced_chain은 1-튜플을 반환하고 fetch_transcript가 1회 시도로 실행). 계획서의 '전체 체인'은 경미한 오기다.
  FIX: 'whisper-only 단일-provider 체인'으로 표현을 바로잡는다(구현에는 영향 없음).


### 누락 안전 규약 (missing safety)

없음 — 안전 규약은 대체로 보존됨. 확인 결과: (1) T-168 description 단독 후보의 자동확정 금지 경로(batch_poi_service.py:333-364)와 needs_review 유지가 §F/§D에서 손대지 않음, (2) 교정·POI LLM 호출은 게이트웨이 리미터(T-161) 소관으로 순차 유지(병렬 제외)해 비용·rate-limit 상한 보존, (3) whisper CPU 폭주 방어(Semaphore=1)와 yt-dlp IP 스로틀 위험(동시성 3 하향 + G8 blocked/rate_limited 전후 비교)이 §5/§6에 명시됨. 추가 누락 안전 규약은 발견되지 않음.

