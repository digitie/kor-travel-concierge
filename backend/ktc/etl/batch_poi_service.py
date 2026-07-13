"""교정 + 배치 POI 오케스트레이션 (영상 묶음 ETL).

영상 묶음(≤10)에 대해: 각 영상 자막 확보 → 교정(영상 설명 활용) → raw/교정본 RustFS 저장,
교정본을 한 번에 묶어 POI 배치 추출, 결과를 영상별 `needs_review` 후보로 생성한다. 카테고리는
AI가 마스터 코드표에서 고른 8자리 코드를 그대로 후보 evidence에 싣는다(확정 시 복사, 변경 금지).
순차 처리(병렬 없음)이며 Gemini 호출은 키 전역 rate limiter를 통과한다.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ktc.core.config import get_settings
from ktc.etl import (
    batch_poi,
    category_catalog,
    gemini_rate_limiter,
    grounding,
    llm_client,
    media_store,
    transcript_correction,
)
from ktc.etl.transcript import (
    TranscriptAttempt,
    TranscriptOutcome,
    TranscriptResult,
    canonical_provider,
)
from ktc.models import (
    AssetType,
    CrawlStatus,
    EvidenceSourceKind,
    ExtractedPlaceCandidate,
    FeatureExportStatus,
    MatchStatus,
    YoutubePlaylistVideo,
    YoutubeVideo,
)

StatusReporter = Callable[[str, float | None], Awaitable[None]]
# fetcher는 T-164 이후 `TranscriptOutcome`(성공 result + provider별 시도)을 반환한다.
# 구 계약(TranscriptResult|None)도 `TranscriptOutcome.coerce`로 흡수한다(주입 호환).
TranscriptFetcher = Callable[
    [str], Awaitable["TranscriptOutcome | TranscriptResult | None"]
]
# durable 단계 이벤트 콜백(T-162, crawl_run_service.StageReporter 계약과 동일):
# (stage, *, outcome, provider=None, attempt=None, item_ref=None,
#  elapsed_ms=None, detail=None). 주입형으로 두어 ETL 계층이 crawl_run에
# 직접 의존하지 않게 한다(테스트 가능성 포함).
StageReporter = Callable[..., Awaitable[None]]
# transcript 시도 기록 콜백(T-164, crawl_run_service.AttemptRecorder 계약과 동일):
# (video_id, attempts) — provider별 시도를 transcript_attempts에 durable하게 남긴다.
AttemptRecorder = Callable[[str, list[TranscriptAttempt]], Awaitable[None]]


def _attempts_one_line(outcome: TranscriptOutcome) -> str:
    """provider별 시도 요약 1줄(작업 상태 로그용). stage 이벤트와 정합(요약 vs 상세)."""
    return ", ".join(f"{a.provider}={a.outcome}" for a in outcome.attempts)


def _source_from_transcript_asset_key(object_key: str | None) -> str | None:
    """저장된 자막 asset의 object_key(`{video_id}/transcript_{source}.txt`)에서
    성공 provider(레거시 표기)를 되뽑는다. 캐시 자막 재사용 시 요약 캐시 파생용."""
    if not object_key:
        return None
    name = object_key.rsplit("/", 1)[-1]
    if name.startswith("transcript_") and name.endswith(".txt"):
        return name[len("transcript_") : -len(".txt")] or None
    return None


def _apply_cached_transcript_cache(video: YoutubeVideo, raw_asset: Any) -> None:
    """저장된 자막을 재사용해 성공적으로 진행할 때 요약 캐시를 갱신한다(리뷰 MINOR-3).

    fresh fetch 경로에서만 갱신하면 캐시 재처리 시 transcript_source가 stale/NULL로
    남아 §7 수율 지표를 왜곡한다. object_key에서 provider를 되뽑아 canonical로 세팅하고
    (성공이므로) failure_code는 비운다. provider를 못 뽑으면 기존 값을 보존한다."""
    source = _source_from_transcript_asset_key(getattr(raw_asset, "object_key", None))
    if source:
        video.transcript_source = canonical_provider(source)
    video.transcript_failure_code = None

# 단일 영상 자막이 분당 토큰 한도(TPM)를 넘지 않도록 LLM 입력에 적용하는 문자 상한.
# 원본(raw) 자막은 전체를 RustFS에 저장하고, 교정·추출 입력만 절단한다(긴 영상 대응).
_MAX_TRANSCRIPT_CHARS = 350_000


async def _report(reporter: StatusReporter | None, message: str, progress: float | None = None) -> None:
    if reporter is not None:
        await reporter(message, progress)


async def _report_stage(
    reporter: StageReporter | None,
    stage: str,
    *,
    outcome: str,
    started: float | None = None,
    provider: str | None = None,
    attempt: int | None = None,
    item_ref: str | None = None,
    detail: str | None = None,
) -> None:
    """단계 이벤트를 best-effort로 보고한다. `started`는 `time.monotonic()` 시각이며
    elapsed_ms를 monotonic 실측으로 계산한다(§7 지표·T-172 게이트의 정확성 요건)."""
    if reporter is None:
        return
    elapsed_ms = (
        int((time.monotonic() - started) * 1000) if started is not None else None
    )
    await reporter(
        stage,
        outcome=outcome,
        provider=provider,
        attempt=attempt,
        item_ref=item_ref,
        elapsed_ms=elapsed_ms,
        detail=detail,
    )


async def _source_playlist_id_for_video(session: AsyncSession, video_id: str) -> str | None:
    result = await session.execute(
        select(YoutubePlaylistVideo.playlist_id)
        .where(YoutubePlaylistVideo.video_id == video_id)
        .order_by(YoutubePlaylistVideo.first_seen_at, YoutubePlaylistVideo.playlist_id)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def process_video_batch(
    session: AsyncSession,
    store: media_store.MediaStore,
    *,
    videos: list[YoutubeVideo],
    runtime: llm_client.LlmRuntime,
    transcript_fetcher: TranscriptFetcher,
    status_reporter: StatusReporter | None = None,
    stage_reporter: StageReporter | None = None,
    attempt_recorder: AttemptRecorder | None = None,
    start_stage: str = "transcript",
    default_category_code: str | None = None,
) -> dict[str, Any]:
    """영상 묶음(≤10)을 교정→배치 추출→후보 생성까지 처리한다.

    `start_stage`로 어느 단계부터 다시 할지 고른다(검수 재처리):
    - "transcript": 기본. YouTube에서 자막을 새로 받아 교정→POI까지.
    - "correction": 저장된 원본 자막을 재사용해 자막 fetch를 건너뛰고 교정→POI.
    - "poi": 저장된 교정본을 재사용해 fetch·교정을 건너뛰고 POI만 다시 추출.
    저장된 자막/교정본이 없으면 한 단계 앞(없으면 fetch)으로 자동 폴백한다.
    """
    summary = {
        "processed_videos": 0,
        "corrected_videos": 0,
        "created_candidates": 0,
        "failed_videos": 0,
    }
    normalized_default_category = category_catalog.normalize_code(default_category_code)
    # 1) 영상별 자막 확보 → 교정 → raw/교정본 저장. (alias, video, asset_id, corrected) 수집.
    batch: dict[str, dict[str, Any]] = {}
    for index, video in enumerate(videos, start=1):
        alias = f"video_{index:03d}"
        label = video.title or video.video_id
        transcript_source = "cached"
        raw_asset_id: int | None = None
        corrected: str | None = None
        # raw grounding 대조 원천(원본 자막). 교정본이 아니라 저장된 원본 자막을 쓴다
        # (T-165). 모든 경로에서 확보하며, 확보 못 하면 grounding은 UNVERIFIED로 fail-close.
        grounding_raw_text: str | None = None

        # POI부터: 저장된 교정본을 그대로 재사용해 fetch·교정을 건너뛴다.
        if start_stage == "poi":
            corrected = await media_store.load_latest_asset_text(
                session,
                store,
                video_id=video.video_id,
                asset_type=AssetType.TRANSCRIPT_CORRECTED,
            )
            if corrected is not None:
                raw_asset = await media_store.load_latest_asset(
                    session, video_id=video.video_id, asset_type=AssetType.TRANSCRIPT
                )
                raw_asset_id = raw_asset.id if raw_asset is not None else None
                # grounding 대조용 원본 자막을 함께 로드한다(교정본만 재사용하는 경로에서도
                # raw 대조가 가능하도록 — 없으면 None으로 두어 fail-close).
                grounding_raw_text = await media_store.load_latest_asset_text(
                    session,
                    store,
                    video_id=video.video_id,
                    asset_type=AssetType.TRANSCRIPT,
                )
                # 캐시 교정본 재사용도 성공 자막 확보이므로 요약 캐시를 갱신한다(MINOR-3).
                _apply_cached_transcript_cache(video, raw_asset)
                await _report(
                    status_reporter,
                    f"{label} 저장된 교정본으로 POI만 다시 추출합니다.",
                )
                for skipped_stage in ("transcript_fetch", "correction"):
                    await _report_stage(
                        stage_reporter,
                        skipped_stage,
                        outcome="skipped",
                        item_ref=video.video_id,
                        detail="저장된 교정본 재사용(fetch·교정 생략)",
                    )

        # 교정본이 없으면(또는 transcript/correction 단계면) 원본 자막을 확보해 교정한다.
        if corrected is None:
            raw_text: str | None = None
            # 교정부터/POI부터(교정본 없음): 저장된 원본 자막을 재사용해 fetch를 건너뛴다.
            if start_stage in ("correction", "poi"):
                raw_asset = await media_store.load_latest_asset(
                    session, video_id=video.video_id, asset_type=AssetType.TRANSCRIPT
                )
                if raw_asset is not None:
                    raw_bytes = await asyncio.to_thread(
                        store.get_object, raw_asset.bucket, raw_asset.object_key
                    )
                    raw_text = raw_bytes.decode("utf-8")
                    raw_asset_id = raw_asset.id
                    # 캐시 원본 자막 재사용도 성공 확보이므로 요약 캐시를 갱신한다(MINOR-3).
                    _apply_cached_transcript_cache(video, raw_asset)
                    await _report(
                        status_reporter, f"{label} 저장된 자막으로 교정부터 다시 합니다."
                    )
                    await _report_stage(
                        stage_reporter,
                        "transcript_fetch",
                        outcome="skipped",
                        item_ref=video.video_id,
                        detail="저장된 원본 자막 재사용(fetch 생략)",
                    )
            # 자막부터 또는 저장된 자막이 없으면: YouTube에서 새로 가져온다.
            if raw_text is None:
                fetch_started = time.monotonic()
                try:
                    fetched = await transcript_fetcher(video.video_id)
                except Exception as exc:
                    await _report_stage(
                        stage_reporter,
                        "transcript_fetch",
                        outcome="failure",
                        started=fetch_started,
                        item_ref=video.video_id,
                        detail=str(exc),
                    )
                    raise
                # provider별 시도(성공 전 실패 포함)를 durable하게 기록하고, 영상의
                # 요약 캐시(성공 provider·최종 실패 코드)를 attempts에서 파생 갱신한다.
                outcome = TranscriptOutcome.coerce(fetched)
                if attempt_recorder is not None and outcome.attempts:
                    await attempt_recorder(video.video_id, outcome.attempts)
                video.transcript_source = outcome.success_provider
                video.transcript_failure_code = outcome.failure_code
                transcript = outcome.result
                attempts_line = _attempts_one_line(outcome)
                if transcript is None or not transcript.segments:
                    detail = (
                        f"자막 실패(provider별: {attempts_line})"
                        if attempts_line
                        else "자막을 찾지 못함(모든 provider 실패)"
                    )
                    await _report_stage(
                        stage_reporter,
                        "transcript_fetch",
                        outcome="failure",
                        started=fetch_started,
                        item_ref=video.video_id,
                        detail=detail,
                    )
                    video.crawl_status = CrawlStatus.FAILED
                    summary["failed_videos"] += 1
                    await _report(
                        status_reporter,
                        f"{label}의 자막을 찾지 못해 건너뜁니다. 사유: {attempts_line or '없음'}.",
                    )
                    continue
                await _report_stage(
                    stage_reporter,
                    "transcript_fetch",
                    outcome="success",
                    started=fetch_started,
                    # G7 조인 위해 stage 이벤트 provider도 canonical로 통일한다
                    # (transcript_attempts·요약 캐시와 동일 어휘 — 리뷰 MINOR-2).
                    provider=outcome.success_provider,
                    item_ref=video.video_id,
                    detail=f"segments={len(transcript.segments)}; 시도: {attempts_line}",
                )
                # 최종 성공 provider·이전 실패 코드를 작업 상태 로그에도 요약 1줄로 남긴다
                # (stage 이벤트는 요약, transcript_attempts는 provider별 상세 — 정합).
                await _report(
                    status_reporter,
                    f"{label} 자막 확보(provider={transcript.source}). 시도: {attempts_line}.",
                )
                raw_text = transcript.to_timestamped_text()
                transcript_source = transcript.source
                raw_asset = await media_store.store_and_record(
                    session,
                    store,
                    asset_type=AssetType.TRANSCRIPT,
                    object_key=f"{video.video_id}/transcript_{transcript.source}.txt",
                    data=raw_text.encode("utf-8"),
                    content_type="text/plain; charset=utf-8",
                    video_id=video.video_id,
                )
                raw_asset_id = raw_asset.id
            # grounding 대조 원천은 교정 전 원본 자막이다(교정본 아님, T-165).
            grounding_raw_text = raw_text
            await _report(status_reporter, f"{label}의 자막을 교정 중입니다.")
            # 긴 영상 대응 절단(D7 미통지 해소): 원 길이→절단 길이를 작업 로그에 남긴다.
            correction_input = raw_text[:_MAX_TRANSCRIPT_CHARS]
            if len(raw_text) > _MAX_TRANSCRIPT_CHARS:
                await _report(
                    status_reporter,
                    f"{label} 자막이 길어 교정 입력을 "
                    f"{len(raw_text)}자→{_MAX_TRANSCRIPT_CHARS}자로 절단했습니다.",
                )
            correction_timeout = get_settings().LLM_TRANSCRIPT_CORRECTION_TIMEOUT_SECONDS
            correction_started = time.monotonic()
            try:
                corrected = await asyncio.wait_for(
                    transcript_correction.correct_transcript(
                        runtime,
                        transcript=correction_input,
                        description=video.description_raw,
                    ),
                    timeout=correction_timeout,
                )
                summary["corrected_videos"] += 1
                await _report_stage(
                    stage_reporter,
                    "correction",
                    outcome="success",
                    started=correction_started,
                    provider=runtime.model,
                    item_ref=video.video_id,
                )
            except TimeoutError:
                # 한 영상의 교정이 시간예산을 넘으면(긴 자막·느린 LLM) 단일 워커를 무한
                # 점유하지 않도록 원본 자막으로 진행하고 다음 영상으로 넘어간다.
                corrected = raw_text
                await _report_stage(
                    stage_reporter,
                    "correction",
                    outcome="failure",
                    started=correction_started,
                    provider=runtime.model,
                    item_ref=video.video_id,
                    detail=f"교정 시간 초과({correction_timeout}s) — 원본 자막으로 진행",
                )
                await _report(
                    status_reporter,
                    f"{label} 자막 교정 시간 초과({correction_timeout}s) — 원본으로 진행합니다.",
                )
            except Exception as exc:  # 교정 실패는 best-effort: 원본 자막으로 진행
                corrected = raw_text
                await _report_stage(
                    stage_reporter,
                    "correction",
                    outcome="failure",
                    started=correction_started,
                    provider=runtime.model,
                    item_ref=video.video_id,
                    detail=f"교정 실패 — 원본 자막으로 진행: {exc}",
                )
                await _report(status_reporter, f"{label} 자막 교정 실패({exc}) — 원본으로 진행합니다.")
            await media_store.store_and_record(
                session,
                store,
                asset_type=AssetType.TRANSCRIPT_CORRECTED,
                object_key=f"{video.video_id}/transcript_corrected.txt",
                data=corrected.encode("utf-8"),
                content_type="text/plain; charset=utf-8",
                video_id=video.video_id,
            )

        batch[alias] = {
            "video": video,
            "transcript_source": transcript_source,
            "asset_id": raw_asset_id,
            "corrected": corrected,
            "raw_text": grounding_raw_text,
        }
    await session.commit()

    if not batch:
        await _report(status_reporter, "교정 가능한 자막이 없어 POI 추출을 건너뜁니다.")
        return summary

    # 2) 교정본을 묶어 POI 배치 추출. 토큰 예산을 넘으면 sub-batch로 나눈다(긴 영상 대응) —
    #    단일 콜이 분당 토큰 한도(TPM)를 넘지 않도록 보장한다.
    budget = max(20_000, get_settings().POI_BATCH_TOKEN_BUDGET)
    items = [(alias, item["corrected"]) for alias, item in batch.items()]
    sub_batches: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    current_tokens = 0
    max_chars = max(1000, 2 * (budget - 2048))
    for alias, corrected in items:
        # 단일 영상이 예산을 넘지 않도록 절단(rate limiter 무한 보류 방지).
        if len(corrected) > max_chars:
            # D7 미통지 해소: 토큰 예산 절단 사실(원 길이→절단 길이)을 1줄 남긴다.
            item_label = batch[alias]["video"].title or batch[alias]["video"].video_id
            await _report(
                status_reporter,
                f"{item_label} POI 입력을 토큰 예산으로 "
                f"{len(corrected)}자→{max_chars}자로 절단했습니다.",
            )
            corrected = corrected[:max_chars]
        tok = gemini_rate_limiter.estimate_tokens(corrected)
        if current and current_tokens + tok > budget:
            sub_batches.append(current)
            current, current_tokens = [], 0
        current.append((alias, corrected))
        current_tokens += tok
    if current:
        sub_batches.append(current)
    pois = []
    extract_started = time.monotonic()
    sub_index = 0
    try:
        for sub_index, sub in enumerate(sub_batches, start=1):
            await _report(
                status_reporter, f"동영상 {len(sub)}개를 묶어 POI를 추출 중입니다."
            )
            extract_started = time.monotonic()
            extracted = await batch_poi.extract_batch(runtime, sub)
            pois.extend(extracted)
            await _report_stage(
                stage_reporter,
                "poi_extract",
                outcome="success",
                started=extract_started,
                provider=runtime.model,
                attempt=sub_index,
                detail=f"videos={len(sub)}, pois={len(extracted)}",
            )
    except gemini_rate_limiter.GeminiQuotaExceeded as exc:
        # 일일 쿼터 소진 → 하드 실패 대신 보류(교정본은 저장됨, 영상은 DISCOVERED 유지로
        # 다음 PT일/수동 재실행 시 재처리). 후보는 생성하지 않는다.
        await _report_stage(
            stage_reporter,
            "poi_extract",
            outcome="deferred",
            started=extract_started,
            provider=runtime.model,
            attempt=sub_index,
            detail=f"일일 쿼터 보류: {exc}",
        )
        await _report(status_reporter, f"Gemini 일일 한도로 POI 추출을 보류합니다: {exc}")
        summary["quota_deferred"] = True
        return summary
    except llm_client.LlmRequestError as exc:
        # Google 측 429(키 쿼터 소진)도 하드 실패 대신 보류로 처리한다(작업 실패 스팸 방지).
        # 그 외 LLM 오류는 실제 실패로 전파한다.
        message = str(exc)
        if exc.status_code == 429 or "429" in message or "quota" in message.lower():
            await _report_stage(
                stage_reporter,
                "poi_extract",
                outcome="deferred",
                started=extract_started,
                provider=runtime.model,
                attempt=sub_index,
                detail=f"쿼터(429) 보류: {exc}",
            )
            await _report(
                status_reporter, f"Gemini 쿼터(429)로 POI 추출을 보류합니다: {exc}"
            )
            summary["quota_deferred"] = True
            return summary
        await _report_stage(
            stage_reporter,
            "poi_extract",
            outcome="failure",
            started=extract_started,
            provider=runtime.model,
            attempt=sub_index,
            detail=message,
        )
        raise
    except Exception as exc:
        await _report_stage(
            stage_reporter,
            "poi_extract",
            outcome="failure",
            started=extract_started,
            provider=runtime.model,
            attempt=sub_index,
            detail=str(exc),
        )
        raise

    # 3) 결과를 영상별 needs_review 후보로 생성. (영상, 장소명) 중복은 건너뛴다(멱등성:
    #    부분 재실행/재시작 시 중복 후보 방지). soft delete된 후보는 dedup 기준에서
    #    제외한다(T-160/로드맵 B1 절차 2 — 재추출 시 새 후보로 검수 큐에 재등장할 수
    #    있다. 영구 억제는 `ignored` 또는 영상 제외가 담당).
    batch_video_ids = [item["video"].video_id for item in batch.values()]
    existing_pairs: set[tuple[str, str]] = set()
    if batch_video_ids:
        rows = await session.execute(
            select(
                ExtractedPlaceCandidate.video_id,
                ExtractedPlaceCandidate.ai_place_name,
            ).where(
                ExtractedPlaceCandidate.video_id.in_(batch_video_ids),
                ExtractedPlaceCandidate.deleted_at.is_(None),
            )
        )
        existing_pairs = {(str(v), str(n)) for v, n in rows.all()}
    created_candidates: list[ExtractedPlaceCandidate] = []
    for poi in pois:
        item = batch.get(poi.video_id)
        if item is None:
            continue
        video = item["video"]
        if (video.video_id, poi.official_name) in existing_pairs:
            continue
        existing_pairs.add((video.video_id, poi.official_name))
        playlist_id = await _source_playlist_id_for_video(session, video.video_id)
        category_code = (
            poi.category_code
            or normalized_default_category
            or category_catalog.UNKNOWN_CATEGORY_CODE
        )
        category_label = category_catalog.label_for_or_unknown(category_code)
        # raw 자막 대조 grounding(T-165, B3). 교정본이 아니라 원본 자막과 대조한다.
        # 실패(unverified/missing) 후보도 폐기하지 않고 저신뢰로 마킹만 하며(사유 표시),
        # verified_raw가 아니면 아래 지오코딩 자동확정·export가 차단된다.
        grounded = grounding.evaluate_transcript_grounding(
            poi.evidence_quote, item.get("raw_text")
        )
        candidate = ExtractedPlaceCandidate(
            video_id=video.video_id,
            source_channel_id=video.channel_id,
            source_playlist_id=playlist_id,
            source_kind=EvidenceSourceKind.TRANSCRIPT.value,
            source_text=poi.speaker_note or poi.official_name,
            ai_place_name=poi.official_name,
            speaker_note=poi.speaker_note,
            location_hint=poi.location_hint,
            timestamp_start=poi.timestamp_start,
            timestamp_end=poi.timestamp_end,
            candidate_category=category_label,
            match_status=MatchStatus.NEEDS_REVIEW,
            grounding_status=grounded.status.value,
            is_domestic=poi.is_domestic,
            review_note=(
                "해외(국내 아님) — 검수 필요" if poi.is_domestic is False else None
            ),
            provider_evidence_json={
                "transcript": {
                    "source": item["transcript_source"],
                    "asset_id": item["asset_id"],
                    "timestamp_start": poi.timestamp_start,
                    "timestamp_end": poi.timestamp_end,
                    "speaker_note": poi.speaker_note,
                    "location_hint": poi.location_hint,
                    # POI 배치에서 받은 8자리 코드(확정 시 복사, 변경 금지).
                    "category_code": category_code,
                    "category_source": "llm"
                    if poi.category_code
                    else ("default" if normalized_default_category else "unknown"),
                    # raw grounding 근거(T-165). quote·판정·매칭 세그먼트 ref를 보존한다.
                    # llm_confidence는 기록·표시 전용 — 어떤 게이트에도 쓰지 않는다.
                    "evidence_quote": grounded.evidence_quote,
                    "grounding_status": grounded.status.value,
                    "grounded": grounded.status == grounding.GroundingStatus.VERIFIED_RAW,
                    "matched_segment_index": grounded.matched_segment_index,
                    "matched_segment_start_seconds": (
                        grounded.matched_segment_start_seconds
                    ),
                    "llm_confidence": poi.confidence,
                }
            },
            feature_export_status=FeatureExportStatus.PENDING.value,
        )
        session.add(candidate)
        created_candidates.append(candidate)
        summary["created_candidates"] += 1

    for item in batch.values():
        video = item["video"]
        if video.crawl_status != CrawlStatus.FAILED:
            video.crawl_status = CrawlStatus.SUMMARIZED
    summary["processed_videos"] = len(batch)
    await session.commit()
    await _report(
        status_reporter,
        f"POI 배치 추출 완료 — 영상 {len(batch)}개에서 후보 {summary['created_candidates']}개 생성.",
    )

    # 4) 새 후보 지오코딩(자동 확정/검수 큐). 카테고리 8자리 코드는 evidence 값 그대로.
    #    단, 해외(is_domestic=False)는 지오코딩/자동확정을 생략하고 needs_review로만 남긴다
    #    (이 서비스는 국내 여행지만 다룬다 — 기록은 남기고 사용자가 검수에서 재시도/제외).
    geocode_targets = [c for c in created_candidates if c.is_domestic is not False]
    foreign_count = len(created_candidates) - len(geocode_targets)
    if foreign_count:
        await _report(
            status_reporter,
            f"해외로 판정된 후보 {foreign_count}개는 지오코딩을 생략하고 검수 큐에 남깁니다.",
        )
    if geocode_targets:
        from ktc.etl import postprocess_service  # 지연 import(순환 회피)

        geocode_started = time.monotonic()
        try:
            geo = await postprocess_service.geocode_candidates(
                session, geocode_targets, status_reporter=status_reporter
            )
        except Exception as exc:
            await _report_stage(
                stage_reporter,
                "geocode",
                outcome="failure",
                started=geocode_started,
                detail=str(exc),
            )
            raise
        await _report_stage(
            stage_reporter,
            "geocode",
            outcome="success",
            started=geocode_started,
            detail=(
                f"candidates={len(geocode_targets)}, "
                f"matched={geo.get('matched_places', 0)}, "
                f"needs_review={geo.get('needs_review_candidates', 0)}"
            ),
        )
        summary["matched_places"] = geo.get("matched_places", 0)
        summary["needs_review_candidates"] = geo.get("needs_review_candidates", 0)
    return summary
