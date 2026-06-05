"""영상 요약·POI 적재 오케스트레이션 (ETL 2단계).

자막 확보 → RustFS 저장(`media_assets`) → Gemini POI 추출 → 영상 설명 보정본
저장 → 매칭 후보(`extracted_place_candidates`) 생성을 연결한다
(`docs/architecture.md` 4.3·4.4, ADR-16).

영상 설명 원문(`description_raw`)은 보존하고, Gemini 보정본은 별도 필드에 쓴다.
추출한 장소는 자동 확정하지 않고 `needs_review` 후보로 남긴다(ADR-16).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.etl import media_store, poi_extraction
from app.etl.poi_extraction import LlmCallable
from app.etl.transcript import TranscriptResult
from app.models import (
    AssetType,
    CrawlStatus,
    ExtractedPlaceCandidate,
    MatchStatus,
    YoutubeVideo,
)


async def summarize_video(
    session: AsyncSession,
    store: media_store.MediaStore,
    *,
    video: YoutubeVideo,
    transcript: TranscriptResult | None,
    llm: LlmCallable,
    max_retries: int = 2,
) -> dict[str, Any]:
    """단일 영상에 대해 자막 저장·POI 추출·후보 생성을 수행한다."""
    if transcript is None or not transcript.segments:
        video.crawl_status = CrawlStatus.FAILED
        await session.commit()
        return {"video_id": video.video_id, "status": "no_transcript", "candidates": 0}

    # 1) 자막/전사 결과를 RustFS에 저장하고 media_assets에 기록
    asset = await media_store.store_and_record(
        session,
        store,
        asset_type=AssetType.TRANSCRIPT,
        object_key=f"{video.video_id}/transcript_{transcript.source}.txt",
        data=transcript.to_timestamped_text().encode("utf-8"),
        content_type="text/plain; charset=utf-8",
        video_id=video.video_id,
    )

    # 2) Gemini POI 추출 (파싱 실패 시 재시도)
    result = poi_extraction.extract_pois(
        timestamped_transcript=transcript.to_timestamped_text(),
        description_raw=video.description_raw,
        llm=llm,
        max_retries=max_retries,
    )

    # 3) 영상 설명 보정본 저장 (원문 description_raw 보존)
    if result.description_gemini_corrected:
        video.description_gemini_corrected = result.description_gemini_corrected
        video.description_gemini_corrected_at = datetime.now(timezone.utc)
        video.description_gemini_model = get_settings().GEMINI_ENGINE_VERSION

    # 4) 추출 장소를 needs_review 후보로 생성 (자동 확정 금지)
    created = 0
    for poi in result.places:
        candidate = ExtractedPlaceCandidate(
            video_id=video.video_id,
            source_text=poi.gemini_enriched_description or poi.name,
            ai_place_name=poi.name,
            speaker_note=poi.speaker_note,
            location_hint=poi.location_hint,
            timestamp_start=poi.timestamp_start,
            timestamp_end=poi.timestamp_end,
            candidate_category=poi.category,
            match_status=MatchStatus.NEEDS_REVIEW,
        )
        session.add(candidate)
        created += 1

    video.crawl_status = CrawlStatus.SUMMARIZED
    await session.commit()

    return {
        "video_id": video.video_id,
        "status": "summarized",
        "summary": result.summary,
        "transcript_asset_id": asset.id,
        "candidates": created,
    }
