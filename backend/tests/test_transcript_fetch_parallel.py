"""자막 fetch 병렬화 테스트 (T-172, PR-24).

`process_video_batch`의 1단계는 캡션 fetch만 병렬화한다: fresh fetch가 필요한 영상들을
`CRAWL_MAX_CONCURRENT_VIDEOS` semaphore 아래 동시에 시도하고(Phase 1a), 캡션이 최종
실패한 영상만 whisper로 동시성 1 순차 폴백한다(Phase 1b). 그 외(교정·POI 배치 추출·
지오코딩)는 순차이며 병렬 구간은 공유 `AsyncSession`에 절대 접근하지 않는다.

이 파일은 다음을 검증한다:
1. 캡션 fetch 동시성 상한 가드(`1 < max_concurrent <= CRAWL_MAX_CONCURRENT_VIDEOS`).
2. whisper는 auto/force_whisper 모두 동시성 1을 절대 넘지 않는다.
3. 병렬 구간(Phase 1a/1b)이 공유 세션(`media_store.store_and_record`)에 접근하지 않는다.
4. 무회귀 — 캡션/whisper 사유 코드 분포가 병렬(N>1)과 순차(Semaphore=1) 사이에서 동일하다.
5. 출력 등가성(golden) — 병렬/순차 실행이 이름·순서·grounding·evidence까지 동일한 후보를 만든다.
6. 벽시계 단축(약식) — 병렬 fetch가 순차보다 유의하게 빠르다.
7. stage 이벤트 정합 — `transcript_fetch`가 병렬 실행에서도 영상당 정확히 1건만 기록된다.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from sqlalchemy import select

from ktc.core.config import get_settings
from ktc.etl import batch_poi, batch_poi_service, media_store, postprocess_service, transcript_correction
from ktc.etl.llm_client import LlmRuntime
from ktc.etl.media_store import InMemoryMediaStore
from ktc.etl.transcript import (
    TranscriptAttempt,
    TranscriptOutcome,
    TranscriptResult,
    TranscriptSegment,
)
from ktc.models import EvidenceSourceKind, ExtractedPlaceCandidate, YoutubeVideo

_RUNTIME = LlmRuntime(model="gemini-2.5-flash")

# description-fallback(T-168)을 확실히 유발하는 임계(200자) 초과 설명(≈260자).
_LONG_DESCRIPTION = (
    "이번 여행에서는 성심당 본점에서 튀김소보로를 먹고 대전 스카이로드를 걸었습니다. 오후에는 "
    "한밭수목원을 산책하고 유성온천에서 잠시 발을 담갔어요. 저녁은 대전의 두부두루치기 맛집에서 "
    "마무리했습니다. 이튿날 아침에는 대청호 오백리길을 따라 드라이브를 즐기고 계족산 황톳길을 "
    "맨발로 걸었습니다. 점심은 중앙시장 근처 칼국수 골목에서 해결했고, 오후에는 대전 근현대사 "
    "전시관을 둘러봤습니다. 다음 영상에서는 세종호수공원 코스를 소개할 예정이니 많은 관심과 "
    "기대 부탁드립니다. 구독과 좋아요는 채널에 큰 힘이 됩니다. 감사합니다."
)


async def _seed_videos(session, prefix: str, count: int) -> list[YoutubeVideo]:
    ids = [f"{prefix}{i:02d}" for i in range(count)]
    for vid in ids:
        session.add(
            YoutubeVideo(
                video_id=vid,
                title=f"{prefix} 영상 {vid}",
                url=f"https://youtu.be/{vid}",
                channel_id=f"UC{prefix}",
            )
        )
    await session.commit()
    return [await session.get(YoutubeVideo, vid) for vid in ids]


def _no_candidates_extract():
    async def fake_extract(runtime, items, **kwargs):
        return []

    return fake_extract


def _passthrough_correct():
    async def fake_correct(runtime, *, transcript, description=None, **kwargs):
        return transcript

    return fake_correct


# --- 1. 캡션 fetch 동시성 상한 가드 ------------------------------------------


async def test_caption_fetch_respects_concurrency_semaphore(session, monkeypatch):
    settings = get_settings()
    max_allowed = settings.CRAWL_MAX_CONCURRENT_VIDEOS
    assert max_allowed == 3  # T-172 기본값(4→3) 회귀 가드

    videos = await _seed_videos(session, "ccap", 8)

    current = 0
    peak = 0

    async def caption_fetcher(video_id: str) -> TranscriptResult:
        nonlocal current, peak
        current += 1
        peak = max(peak, current)
        await asyncio.sleep(0.02)
        current -= 1
        return TranscriptResult(
            video_id=video_id,
            source="transcript_api",
            segments=[TranscriptSegment(0.0, "테스트 자막")],
        )

    monkeypatch.setattr(transcript_correction, "correct_transcript", _passthrough_correct())
    monkeypatch.setattr(batch_poi, "extract_batch", _no_candidates_extract())

    summary = await batch_poi_service.process_video_batch(
        session,
        InMemoryMediaStore(),
        videos=videos,
        runtime=_RUNTIME,
        caption_fetcher=caption_fetcher,
        whisper_fetcher=None,
    )

    # 병렬은 되되(1 초과) semaphore 상한(3)은 절대 넘지 않는다.
    assert 1 < peak <= max_allowed
    assert summary["processed_videos"] == 8
    assert summary["created_candidates"] == 0


# --- 2. whisper 동시성 1 가드(auto + force_whisper) --------------------------


async def test_whisper_fetch_never_exceeds_concurrency_one_auto_mode(session, monkeypatch):
    videos = await _seed_videos(session, "cwhi", 4)

    async def caption_fails(video_id: str) -> None:
        return None  # 캡션 전 provider 최종 실패(coerce가 빈 실패 outcome으로 감싼다).

    current = 0
    peak = 0

    async def whisper_fetcher(video_id: str) -> TranscriptAttempt:
        nonlocal current, peak
        current += 1
        peak = max(peak, current)
        await asyncio.sleep(0.01)
        current -= 1
        return TranscriptAttempt(provider="whisper", outcome="disabled", sequence=1)

    monkeypatch.setattr(transcript_correction, "correct_transcript", _passthrough_correct())
    monkeypatch.setattr(batch_poi, "extract_batch", _no_candidates_extract())

    summary = await batch_poi_service.process_video_batch(
        session,
        InMemoryMediaStore(),
        videos=videos,
        runtime=_RUNTIME,
        caption_fetcher=caption_fails,
        whisper_fetcher=whisper_fetcher,
    )

    assert peak == 1
    # 캡션·whisper 모두 실패 + 설명도 짧아 전부 실패 처리된다(제목만 있는 짧은 텍스트).
    assert summary["failed_videos"] == 4


async def test_whisper_fetch_never_exceeds_concurrency_one_force_whisper_mode(
    session, monkeypatch
):
    """force_whisper 재전사(caption_fetcher=None)에서도 whisper 동시성은 1을 넘지 않는다."""
    videos = await _seed_videos(session, "cwhf", 4)

    current = 0
    peak = 0

    async def whisper_fetcher(video_id: str) -> TranscriptAttempt:
        nonlocal current, peak
        current += 1
        peak = max(peak, current)
        await asyncio.sleep(0.01)
        current -= 1
        return TranscriptAttempt(provider="whisper", outcome="disabled", sequence=1)

    monkeypatch.setattr(transcript_correction, "correct_transcript", _passthrough_correct())
    monkeypatch.setattr(batch_poi, "extract_batch", _no_candidates_extract())

    summary = await batch_poi_service.process_video_batch(
        session,
        InMemoryMediaStore(),
        videos=videos,
        runtime=_RUNTIME,
        caption_fetcher=None,
        whisper_fetcher=whisper_fetcher,
    )

    assert peak == 1
    assert summary["failed_videos"] == 4


# --- 3. 병렬 구간 세션 비공유 가드 -------------------------------------------


async def test_parallel_phase_never_touches_session_before_gather_completes(
    session, monkeypatch
):
    """Phase 1a(캡션 fetch, gather)가 전부 끝나기 전에는 공유 세션을 쓰는
    `media_store.store_and_record`가 호출되지 않는다(순서 스파이로 확인)."""
    videos = await _seed_videos(session, "cspy", 3)

    events: list[str] = []

    async def caption_fetcher(video_id: str) -> TranscriptResult:
        events.append(f"fetch:{video_id}")
        await asyncio.sleep(0.01)
        return TranscriptResult(
            video_id=video_id,
            source="transcript_api",
            segments=[TranscriptSegment(0.0, "테스트 자막")],
        )

    real_store_and_record = media_store.store_and_record

    async def spy_store_and_record(*args, **kwargs):
        events.append("store_and_record")
        return await real_store_and_record(*args, **kwargs)

    monkeypatch.setattr(media_store, "store_and_record", spy_store_and_record)
    monkeypatch.setattr(transcript_correction, "correct_transcript", _passthrough_correct())
    monkeypatch.setattr(batch_poi, "extract_batch", _no_candidates_extract())

    await batch_poi_service.process_video_batch(
        session,
        InMemoryMediaStore(),
        videos=videos,
        runtime=_RUNTIME,
        caption_fetcher=caption_fetcher,
        whisper_fetcher=None,
    )

    fetch_indexes = [i for i, e in enumerate(events) if e.startswith("fetch:")]
    store_indexes = [i for i, e in enumerate(events) if e == "store_and_record"]
    assert len(fetch_indexes) == 3
    assert len(store_indexes) == 3 * 2  # 영상당 raw + 교정본 asset 저장 2건.
    # 모든 fetch가 모든 store_and_record보다 먼저 일어난다(병렬 구간이 세션을
    # 건드리기 전에 gather가 전부 완료됨을 보장).
    assert max(fetch_indexes) < min(store_indexes)


# --- 4. 무회귀 — 사유 코드 분포(병렬 vs 순차 baseline) ------------------------

_OUTCOME_PLAN = ["success", "no_captions", "blocked", "rate_limited"]


def _idx_from_id(prefix: str, video_id: str) -> int:
    return int(video_id[len(prefix) :])


def _make_reason_code_fetchers(prefix: str):
    async def caption_fetcher(video_id: str) -> TranscriptOutcome:
        idx = _idx_from_id(prefix, video_id)
        kind = _OUTCOME_PLAN[idx % len(_OUTCOME_PLAN)]
        if kind == "success":
            result = TranscriptResult(
                video_id=video_id,
                source="transcript_api",
                segments=[TranscriptSegment(0.0, "성공 자막")],
            )
            return TranscriptOutcome(
                result=result,
                attempts=[
                    TranscriptAttempt(
                        provider="youtube_transcript_api",
                        outcome="success",
                        sequence=1,
                        result=result,
                    )
                ],
            )
        return TranscriptOutcome(
            result=None,
            attempts=[
                TranscriptAttempt(
                    provider="youtube_transcript_api", outcome=kind, sequence=1
                )
            ],
        )

    async def whisper_fetcher(video_id: str) -> TranscriptAttempt:
        idx = _idx_from_id(prefix, video_id)
        # blocked(idx%4==2)만 whisper 성공으로 승격시켜 병합·success_provider
        # 파생까지 함께 검증한다. 나머지(no_captions/rate_limited)는 disabled.
        if idx % len(_OUTCOME_PLAN) == 2:
            result = TranscriptResult(
                video_id=video_id, source="whisper", segments=[TranscriptSegment(0.0, "w")]
            )
            return TranscriptAttempt(
                provider="whisper", outcome="success", sequence=1, result=result
            )
        return TranscriptAttempt(provider="whisper", outcome="disabled", sequence=1)

    return caption_fetcher, whisper_fetcher


async def test_reason_code_distribution_matches_sequential_baseline(session, monkeypatch):
    n = 8
    videos_par = await _seed_videos(session, "par", n)
    videos_seq = await _seed_videos(session, "seq", n)

    caption_par, whisper_par = _make_reason_code_fetchers("par")
    caption_seq, whisper_seq = _make_reason_code_fetchers("seq")

    recorded_par: dict[str, list[tuple[str, str, int]]] = {}
    recorded_seq: dict[str, list[tuple[str, str, int]]] = {}

    async def recorder_par(video_id, attempts):
        recorded_par[video_id] = [(a.provider, a.outcome, a.sequence) for a in attempts]

    async def recorder_seq(video_id, attempts):
        recorded_seq[video_id] = [(a.provider, a.outcome, a.sequence) for a in attempts]

    monkeypatch.setattr(transcript_correction, "correct_transcript", _passthrough_correct())
    monkeypatch.setattr(batch_poi, "extract_batch", _no_candidates_extract())

    # 병렬(N=8, 기본 semaphore=3).
    await batch_poi_service.process_video_batch(
        session,
        InMemoryMediaStore(),
        videos=videos_par,
        runtime=_RUNTIME,
        caption_fetcher=caption_par,
        whisper_fetcher=whisper_par,
        attempt_recorder=recorder_par,
    )

    # 순차 baseline(semaphore=1로 강제 — batch_poi_service 모듈 한정 patch).
    base_settings = get_settings()
    seq_settings = base_settings.model_copy(update={"CRAWL_MAX_CONCURRENT_VIDEOS": 1})
    monkeypatch.setattr(batch_poi_service, "get_settings", lambda: seq_settings)
    await batch_poi_service.process_video_batch(
        session,
        InMemoryMediaStore(),
        videos=videos_seq,
        runtime=_RUNTIME,
        caption_fetcher=caption_seq,
        whisper_fetcher=whisper_seq,
        attempt_recorder=recorder_seq,
    )

    for idx in range(n):
        par_id = f"par{idx:02d}"
        seq_id = f"seq{idx:02d}"
        # success(idx%4==0)는 attempt_recorder가 호출되지 않는 게 아니라(성공도 기록
        # 대상) 항상 채워진다 — 두 dict 모두에 항목이 있어야 한다.
        assert recorded_par[par_id] == recorded_seq[seq_id], idx
        par_video = videos_par[idx]
        seq_video = videos_seq[idx]
        assert par_video.transcript_source == seq_video.transcript_source, idx
        assert par_video.transcript_failure_code == seq_video.transcript_failure_code, idx

    # 스팟 체크: idx%4==2(blocked→whisper 성공)는 whisper로 success_provider가 승격된다.
    assert videos_par[2].transcript_source == "whisper"
    assert videos_par[2].transcript_failure_code is None
    # idx%4==0(캡션 성공)은 캡션 provider 그대로.
    assert videos_par[0].transcript_source == "youtube_transcript_api"
    # idx%4==1(no_captions + whisper disabled)은 최종 실패, 대표 사유는 no_captions.
    assert videos_par[1].transcript_source is None
    assert videos_par[1].transcript_failure_code == "no_captions"


# --- 5. 출력 등가성(golden) — 병렬/순차가 동일한 후보를 만든다 ----------------


async def test_parallel_and_sequential_produce_equivalent_candidates(session, monkeypatch):
    n = 5

    async def caption_fetcher(video_id: str) -> TranscriptResult:
        # video_id 뒤 2자리(=순번)만 내용에 반영해 par/seq 간 자막 내용을 동일하게
        # 맞춘다(접두사 3자 차이는 evidence 비교와 무관해야 한다).
        idx = video_id[3:]
        return TranscriptResult(
            video_id=video_id,
            source="transcript_api",
            segments=[TranscriptSegment(1.0, f"장소{idx} 근처 맛집을 소개합니다.")],
        )

    async def fake_extract(runtime, items, **kwargs):
        return [
            batch_poi.BatchExtractedPOI(
                video_id=alias,
                official_name=f"장소_{alias}",
                category_code="01050100",
                is_domestic=True,
                evidence_quote=corrected.strip(),
            )
            for alias, corrected in items
        ]

    async def fake_geocode(session_, candidates, *, status_reporter=None):
        return {"matched_places": 0, "needs_review_candidates": len(candidates)}

    monkeypatch.setattr(transcript_correction, "correct_transcript", _passthrough_correct())
    monkeypatch.setattr(batch_poi, "extract_batch", fake_extract)
    monkeypatch.setattr(postprocess_service, "geocode_candidates", fake_geocode)

    videos_par = await _seed_videos(session, "gpa", n)
    await batch_poi_service.process_video_batch(
        session,
        InMemoryMediaStore(),
        videos=videos_par,
        runtime=_RUNTIME,
        caption_fetcher=caption_fetcher,
        whisper_fetcher=None,
    )

    videos_seq = await _seed_videos(session, "gse", n)
    base_settings = get_settings()
    seq_settings = base_settings.model_copy(update={"CRAWL_MAX_CONCURRENT_VIDEOS": 1})
    monkeypatch.setattr(batch_poi_service, "get_settings", lambda: seq_settings)
    await batch_poi_service.process_video_batch(
        session,
        InMemoryMediaStore(),
        videos=videos_seq,
        runtime=_RUNTIME,
        caption_fetcher=caption_fetcher,
        whisper_fetcher=None,
    )

    par_rows = (
        (
            await session.execute(
                select(ExtractedPlaceCandidate)
                .where(ExtractedPlaceCandidate.video_id.like("gpa%"))
                .order_by(ExtractedPlaceCandidate.video_id)
            )
        )
        .scalars()
        .all()
    )
    seq_rows = (
        (
            await session.execute(
                select(ExtractedPlaceCandidate)
                .where(ExtractedPlaceCandidate.video_id.like("gse%"))
                .order_by(ExtractedPlaceCandidate.video_id)
            )
        )
        .scalars()
        .all()
    )

    assert len(par_rows) == n
    assert len(seq_rows) == n
    for par, seq in zip(par_rows, seq_rows, strict=True):
        # alias(video_NNN)는 원본 videos 순서로 부여되므로 병렬/순차 모두 동일하다.
        assert par.ai_place_name == seq.ai_place_name
        assert par.source_kind == seq.source_kind
        assert par.grounding_status == seq.grounding_status
        par_evidence = par.provider_evidence_json["transcript"]
        seq_evidence = seq.provider_evidence_json["transcript"]
        assert par_evidence["evidence_quote"] == seq_evidence["evidence_quote"]
        assert par_evidence["grounding_status"] == seq_evidence["grounding_status"]
        assert par_evidence["category_code"] == seq_evidence["category_code"]


# --- 6. 벽시계 단축(약식) -----------------------------------------------------


async def test_caption_parallel_fetch_is_faster_than_sequential(session, monkeypatch):
    n = 6
    delay = 0.08
    sem = get_settings().CRAWL_MAX_CONCURRENT_VIDEOS  # 3 (병렬 실행 semaphore)

    async def caption_fetcher(video_id: str) -> TranscriptResult:
        await asyncio.sleep(delay)
        return TranscriptResult(
            video_id=video_id,
            source="transcript_api",
            segments=[TranscriptSegment(0.0, "테스트 자막")],
        )

    monkeypatch.setattr(transcript_correction, "correct_transcript", _passthrough_correct())
    monkeypatch.setattr(batch_poi, "extract_batch", _no_candidates_extract())

    videos_par = await _seed_videos(session, "wcp", n)
    started = time.monotonic()
    await batch_poi_service.process_video_batch(
        session,
        InMemoryMediaStore(),
        videos=videos_par,
        runtime=_RUNTIME,
        caption_fetcher=caption_fetcher,
        whisper_fetcher=None,
    )
    parallel_elapsed = time.monotonic() - started

    videos_seq = await _seed_videos(session, "wcs", n)
    base_settings = get_settings()
    seq_settings = base_settings.model_copy(update={"CRAWL_MAX_CONCURRENT_VIDEOS": 1})
    monkeypatch.setattr(batch_poi_service, "get_settings", lambda: seq_settings)
    started = time.monotonic()
    await batch_poi_service.process_video_batch(
        session,
        InMemoryMediaStore(),
        videos=videos_seq,
        runtime=_RUNTIME,
        caption_fetcher=caption_fetcher,
        whisper_fetcher=None,
    )
    sequential_elapsed = time.monotonic() - started

    # 병렬화는 오직 fetch 단계에만 적용된다 — 나머지 Phase 1c(교정·저장·commit) 순차
    # 오버헤드는 두 실행에 동일하게 들어가 벽시계 차이에서 상쇄된다. 따라서 절대 비율
    # 대신 **차이**로 단언하면 상수 오버헤드·시스템 부하에 강건하다(플래키 회피).
    # 이론적 fetch 이득 = (전체 - 병렬 wave 수) × delay. 스케줄 지터 여유로 절반만 요구.
    waves_parallel = (n + sem - 1) // sem  # ceil(n/sem) = 2 (semaphore=3, n=6)
    theoretical_savings = (n - waves_parallel) * delay
    assert parallel_elapsed < sequential_elapsed
    assert sequential_elapsed - parallel_elapsed >= theoretical_savings * 0.5


# --- 7. stage 이벤트 정합 — transcript_fetch는 영상당 정확히 1건 -------------


async def test_transcript_fetch_stage_event_fires_once_per_video_when_parallel(
    session, monkeypatch
):
    n = 4
    videos = await _seed_videos(session, "sevt", n)

    async def caption_fetcher(video_id: str) -> TranscriptResult:
        return TranscriptResult(
            video_id=video_id,
            source="transcript_api",
            segments=[TranscriptSegment(0.0, "테스트 자막")],
        )

    stage_events: list[tuple[str, str, str | None]] = []

    async def stage_reporter(
        stage,
        *,
        outcome,
        provider=None,
        attempt=None,
        item_ref=None,
        elapsed_ms=None,
        detail=None,
    ):
        stage_events.append((stage, outcome, item_ref))

    monkeypatch.setattr(transcript_correction, "correct_transcript", _passthrough_correct())
    monkeypatch.setattr(batch_poi, "extract_batch", _no_candidates_extract())

    await batch_poi_service.process_video_batch(
        session,
        InMemoryMediaStore(),
        videos=videos,
        runtime=_RUNTIME,
        caption_fetcher=caption_fetcher,
        whisper_fetcher=None,
        stage_reporter=stage_reporter,
    )

    fetch_events = [e for e in stage_events if e[0] == "transcript_fetch"]
    assert len(fetch_events) == n
    assert {e[2] for e in fetch_events} == {v.video_id for v in videos}
    assert all(e[1] == "success" for e in fetch_events)


# --- 8. 예외 격리 — raise하는 fetcher (invariant 6, 구 순차 체인 동작 보존) ------


async def test_caption_fetcher_exception_is_isolated_and_reraised(session, monkeypatch):
    """caption_fetcher가 한 영상에서 raise하면 그 영상 transcript_fetch failure 이벤트를
    남기고 예외를 전파한다(구 순차 체인의 `raise` 동작 보존). Phase 1a는
    `gather(return_exceptions=True)`로 per-video 격리하므로 raise한 영상이 앞선 영상의
    캡션 처리를 오염시키지 않는다(원본 순서 소비 = 앞 영상은 정상 success 이벤트)."""
    videos = await _seed_videos(session, "cerr", 3)
    # 원본 순서: cerr00 성공 → cerr01 raise → cerr02(성공이지만 raise 이후 미도달).

    async def caption_fetcher(video_id: str):
        if video_id == "cerr01":
            raise RuntimeError("caption boom")
        return TranscriptResult(
            video_id=video_id,
            source="transcript_api",
            segments=[TranscriptSegment(0.0, "테스트 자막")],
        )

    stage_events: list[tuple[str, str, str | None]] = []

    async def stage_reporter(
        stage,
        *,
        outcome,
        provider=None,
        attempt=None,
        item_ref=None,
        elapsed_ms=None,
        detail=None,
    ):
        stage_events.append((stage, outcome, item_ref))

    monkeypatch.setattr(transcript_correction, "correct_transcript", _passthrough_correct())
    monkeypatch.setattr(batch_poi, "extract_batch", _no_candidates_extract())

    with pytest.raises(RuntimeError, match="caption boom"):
        await batch_poi_service.process_video_batch(
            session,
            InMemoryMediaStore(),
            videos=videos,
            runtime=_RUNTIME,
            caption_fetcher=caption_fetcher,
            whisper_fetcher=None,
            stage_reporter=stage_reporter,
        )

    fetch_events = [e for e in stage_events if e[0] == "transcript_fetch"]
    # 앞선 영상(cerr00)은 캡션이 격리돼 정상 success 이벤트를 남긴다(다른 영상 무영향).
    assert ("transcript_fetch", "success", "cerr00") in fetch_events
    # raise한 영상(cerr01)은 failure 이벤트를 남기고 예외가 전파된다(구 동작 보존).
    assert ("transcript_fetch", "failure", "cerr01") in fetch_events


async def test_whisper_fetcher_exception_falls_through_to_description(session, monkeypatch):
    """whisper_fetcher가 raise해도 배치 전체가 죽지 않고(Finding-1 fix), 해당 영상은
    구 순차 체인 `_run_provider`와 동일하게 분류된 whisper 실패 attempt를 얻어
    description-fallback으로 이어진다(캡션 실패 후 whisper 예외 → parse_error)."""
    video = YoutubeVideo(
        video_id="wexc0",
        title="설명 영상",
        url="https://youtu.be/wexc0",
        channel_id="UCwexc",
        description_raw=_LONG_DESCRIPTION,
    )
    session.add(video)
    await session.commit()
    await session.refresh(video)

    async def caption_fails(video_id: str):
        return None  # 캡션 최종 실패(coerce가 빈 실패 outcome으로 감싼다).

    async def whisper_raises(video_id: str) -> TranscriptAttempt:
        raise RuntimeError("whisper boom")

    recorded: dict[str, list[tuple[str, str, int]]] = {}

    async def recorder(video_id, attempts):
        recorded[video_id] = [(a.provider, a.outcome, a.sequence) for a in attempts]

    async def fake_extract(runtime, items, **kwargs):
        alias = items[0][0]
        return [
            batch_poi.BatchExtractedPOI(
                video_id=alias,
                official_name="성심당 본점",
                category_code="01050100",
                is_domestic=True,
                evidence_quote="성심당 본점에서 튀김소보로를 먹고",
            )
        ]

    async def fake_geocode(session_, candidates, *, status_reporter=None):
        return {"matched_places": 0, "needs_review_candidates": len(candidates)}

    monkeypatch.setattr(transcript_correction, "correct_transcript", _passthrough_correct())
    monkeypatch.setattr(batch_poi, "extract_batch", fake_extract)
    monkeypatch.setattr(postprocess_service, "geocode_candidates", fake_geocode)

    # 예외 없이 완료된다(no batch-wide abort).
    summary = await batch_poi_service.process_video_batch(
        session,
        InMemoryMediaStore(),
        videos=[video],
        runtime=_RUNTIME,
        caption_fetcher=caption_fails,
        whisper_fetcher=whisper_raises,
        attempt_recorder=recorder,
    )

    assert summary["created_candidates"] == 1
    assert summary["failed_videos"] == 0
    # raise된 whisper 예외가 분류된 whisper 실패 attempt로 흡수된다(RuntimeError→parse_error,
    # 구 _run_provider 예외 분기와 동일 매핑). caption None은 빈 attempts라 whisper 1건만.
    assert recorded["wexc0"] == [("whisper", "parse_error", 1)]
    refreshed = await session.get(YoutubeVideo, "wexc0")
    assert refreshed.transcript_source is None
    assert refreshed.transcript_failure_code == "parse_error"
    # description-fallback 후보가 생성된다(자막·whisper 모두 실패 → 설명 단독 경로).
    candidate = (
        await session.execute(select(ExtractedPlaceCandidate))
    ).scalar_one()
    assert candidate.source_kind == EvidenceSourceKind.DESCRIPTION.value
