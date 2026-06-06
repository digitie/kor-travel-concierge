"""Playwright E2E용 SQLite fixture 데이터 적재."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from sqlalchemy import delete

from app.core.database import async_session_factory, init_db
from app.models import (
    AuditLog,
    CrawlRun,
    ExtractedPlaceCandidate,
    MatchStatus,
    MediaAsset,
    RunSource,
    RunState,
    SystemSetting,
    TravelPlace,
    VideoPlaceMapping,
    YoutubeVideo,
)


async def main() -> None:
    await init_db()
    async with async_session_factory() as session:
        for model in (
            VideoPlaceMapping,
            ExtractedPlaceCandidate,
            MediaAsset,
            TravelPlace,
            YoutubeVideo,
            CrawlRun,
            AuditLog,
            SystemSetting,
        ):
            await session.execute(delete(model))

        video = YoutubeVideo(
            video_id="e2e-video-1",
            title="제주 월정리 여행",
            url="https://youtu.be/e2e-video-1",
            channel_id="UC_E2E",
            channel_name="E2E 여행",
            description_raw="월정리 해변과 성산 일출봉 카페를 다녀온 영상",
            description_gemini_corrected="월정리 해변과 성산 일출봉 카페를 소개하는 영상",
        )
        place = TravelPlace(
            name="월정리 해변",
            description="제주 동쪽의 해변",
            gemini_enriched_description="에메랄드빛 바다와 카페 거리로 알려진 제주 동쪽 해변",
            official_address="제주특별자치도 제주시 구좌읍 월정리",
            road_address="제주특별자치도 제주시 구좌읍 해맞이해안로",
            latitude=33.5563,
            longitude=126.7958,
            category="해변",
            api_source="vworld",
            is_geocoded=True,
        )
        candidate = ExtractedPlaceCandidate(
            video_id="e2e-video-1",
            source_text="성산 일출봉 근처 카페",
            ai_place_name="성산 일출봉 카페",
            location_hint="제주 서귀포 성산읍",
            timestamp_start="00:02:10",
            candidate_category="카페",
            match_status=MatchStatus.NEEDS_REVIEW,
        )
        run = CrawlRun(
            job_type="harvest",
            source=RunSource.MCP,
            target_type="keyword",
            target_id="제주 여행",
            state=RunState.DONE,
            progress=1.0,
            result_json=json.dumps({"inserted": 1}, ensure_ascii=False),
            finished_at=datetime.now(UTC),
        )
        audit = AuditLog(
            actor_type="mcp",
            action="place.correct",
            target_type="travel_place",
            target_id="1",
            payload_json=json.dumps({"name": "월정리 해변"}, ensure_ascii=False),
        )
        asset = MediaAsset(
            asset_type="frame",
            video_id="e2e-video-1",
            storage_provider="rustfs",
            bucket="tripmate-frames",
            object_key="e2e-video-1/frame.jpg",
            object_uri="s3://tripmate-frames/e2e-video-1/frame.jpg",
            content_type="image/jpeg",
            size_bytes=1024,
            retention_policy="infinite",
        )

        session.add_all([video, place, candidate, run, audit, asset])
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
