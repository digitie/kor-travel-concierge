"""영상 요약·POI 적재 오케스트레이션 (ETL 2단계).

자막 확보 → RustFS 저장(`media_assets`) → Gemini POI 추출 → 영상 설명 보정본
저장 → 매칭 후보(`extracted_place_candidates`) 생성을 연결한다
(`docs/architecture.md` 4.3·4.4, ADR-16).

영상 설명 원문(`description_raw`)은 보존하고, Gemini 보정본은 별도 필드에 쓴다.
추출한 장소는 자동 확정하지 않고 `needs_review` 후보로 남긴다(ADR-16).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ktc.core.config import get_settings
from ktc.etl import category_catalog, media_store, poi_extraction
from ktc.etl.poi_extraction import LlmCallable
from ktc.etl.transcript import TranscriptResult
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


async def _report(
    status_reporter: StatusReporter | None,
    message: str,
    progress: float | None = None,
) -> None:
    if status_reporter is not None:
        await status_reporter(message, progress)


def _short_text(value: str, *, limit: int = 80) -> str:
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    return f"{value[:limit]}..."


async def summarize_video(
    session: AsyncSession,
    store: media_store.MediaStore,
    *,
    video: YoutubeVideo,
    transcript: TranscriptResult | None,
    llm: LlmCallable,
    gemini_model: str | None = None,
    max_retries: int = 2,
    status_reporter: StatusReporter | None = None,
    default_category_code: str | None = None,
) -> dict[str, Any]:
    """단일 영상에 대해 자막 저장·POI 추출·후보 생성을 수행한다."""
    video_label = video.title or video.video_id
    if transcript is None or not transcript.segments:
        await _report(
            status_reporter,
            f"{video_label}의 자막을 찾지 못해 영상 처리를 중단했습니다.",
            None,
        )
        video.crawl_status = CrawlStatus.FAILED
        await session.commit()
        return {"video_id": video.video_id, "status": "no_transcript", "candidates": 0}

    transcript_text = transcript.to_timestamped_text()

    # 1) 자막/전사 결과를 RustFS에 저장하고 media_assets에 기록
    await _report(
        status_reporter,
        f"{video_label}의 자막을 추출했습니다. 추출 경로는 {transcript.source}입니다.",
        None,
    )
    await _report(status_reporter, f"{video_label}의 자막을 RustFS에 저장 중입니다.", None)
    asset = await media_store.store_and_record(
        session,
        store,
        asset_type=AssetType.TRANSCRIPT,
        object_key=f"{video.video_id}/transcript_{transcript.source}.txt",
        data=transcript_text.encode("utf-8"),
        content_type="text/plain; charset=utf-8",
        video_id=video.video_id,
    )
    await _report(status_reporter, f"{video_label}의 자막을 RustFS에 저장했습니다.", None)

    # 2) Gemini POI 추출 (파싱 실패 시 재시도)
    try:
        await _report(status_reporter, f"Gemini에서 {video_label}의 장소 후보를 추출 중입니다.", None)
        result = await asyncio.to_thread(
            poi_extraction.extract_pois,
            timestamped_transcript=transcript_text,
            description_raw=video.description_raw,
            llm=llm,
            max_retries=max_retries,
        )
    except poi_extraction.POIExtractionError as exc:
        await _report(
            status_reporter,
            f"Gemini에서 {video_label}의 장소 후보 추출에 실패했습니다: {exc}",
            None,
        )
        video.crawl_status = CrawlStatus.FAILED
        await session.commit()
        return {
            "video_id": video.video_id,
            "status": "poi_extraction_failed",
            "error": str(exc),
            "transcript_asset_id": asset.id,
            "candidates": 0,
        }

    video.transcript_summary = result.summary

    # 3) 영상 설명 보정본 저장 (원문 description_raw 보존)
    if result.description_gemini_corrected:
        video.description_gemini_corrected = result.description_gemini_corrected
        video.description_gemini_corrected_at = datetime.now(timezone.utc)
        video.description_gemini_model = gemini_model or get_settings().GEMINI_ENGINE_VERSION
        await _report(
            status_reporter,
            f"Gemini에서 영상 설명을 보정했습니다. 보정 결과는 \"{_short_text(result.description_gemini_corrected)}\" 입니다.",
            None,
        )

    # 4) 추출 장소를 needs_review 후보로 생성 (자동 확정 금지)
    created = 0
    source_playlist_id = await _source_playlist_id_for_video(session, video.video_id)
    normalized_default_category = category_catalog.normalize_code(default_category_code)
    for poi in result.places:
        category_code = (
            poi.category_code
            or normalized_default_category
            or category_catalog.UNKNOWN_CATEGORY_CODE
        )
        category_label = category_catalog.label_for_or_unknown(category_code)
        candidate = ExtractedPlaceCandidate(
            video_id=video.video_id,
            source_channel_id=video.channel_id,
            source_playlist_id=source_playlist_id,
            source_kind=EvidenceSourceKind.TRANSCRIPT.value,
            source_text=poi.gemini_enriched_description or poi.name,
            ai_place_name=poi.name,
            speaker_note=poi.speaker_note,
            location_hint=poi.location_hint,
            timestamp_start=poi.timestamp_start,
            timestamp_end=poi.timestamp_end,
            candidate_category=category_label,
            match_status=MatchStatus.NEEDS_REVIEW,
            provider_evidence_json={
                "transcript": {
                    "source": transcript.source,
                    "asset_id": asset.id,
                    "summary": result.summary,
                    "timestamp_start": poi.timestamp_start,
                    "timestamp_end": poi.timestamp_end,
                    "speaker_note": poi.speaker_note,
                    "location_hint": poi.location_hint,
                    # POI 추출 단계에서 함께 받은 8자리 카테고리 코드(검증 통과분).
                    # 확정 시 별도 Gemini 호출 없이 이 값을 장소에 복사한다(호출 절감, A안).
                    "category_code": category_code,
                    "category_source": "llm"
                    if poi.category_code
                    else ("default" if normalized_default_category else "unknown"),
                }
            },
            feature_export_status=FeatureExportStatus.PENDING.value,
        )
        session.add(candidate)
        created += 1

    video.crawl_status = CrawlStatus.SUMMARIZED
    await session.commit()
    await _report(
        status_reporter,
        f"{video_label}에서 장소 후보 {created}개를 추출해 검수 큐에 저장했습니다.",
        None,
    )

    return {
        "video_id": video.video_id,
        "status": "summarized",
        "summary": result.summary,
        "transcript_asset_id": asset.id,
        "candidates": created,
    }


async def _source_playlist_id_for_video(
    session: AsyncSession,
    video_id: str,
) -> str | None:
    result = await session.execute(
        select(YoutubePlaylistVideo.playlist_id)
        .where(YoutubePlaylistVideo.video_id == video_id)
        .order_by(YoutubePlaylistVideo.first_seen_at, YoutubePlaylistVideo.playlist_id)
        .limit(1)
    )
    return result.scalar_one_or_none()
