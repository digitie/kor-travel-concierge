"""Playwright E2E용 SQLite fixture 데이터 적재."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

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
        session.add_all([video, place])
        await session.flush()

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
            finished_at=datetime.now(timezone.utc),
        )
        queue_run = CrawlRun(
            job_type="harvest",
            source=RunSource.WEB,
            target_type="keyword",
            target_id="부산 맛집",
            state=RunState.RUNNING,
            progress=0.42,
            current_message='YouTube에서 "부산 맛집" 검색을 실행 중입니다.',
            status_log_json=json.dumps(
                [
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "level": "info",
                        "message": "작업 실행자가 작업을 시작했습니다.",
                        "progress": 0.05,
                    },
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "level": "info",
                        "message": 'YouTube에서 "부산 맛집" 검색을 실행 중입니다.',
                        "progress": 0.42,
                    },
                ],
                ensure_ascii=False,
            ),
            started_at=datetime.now(timezone.utc),
            heartbeat_at=datetime.now(timezone.utc),
        )
        audit = AuditLog(
            actor_type="mcp",
            action="place.correct",
            target_type="travel_place",
            target_id=str(place.place_id),
            payload_json=json.dumps({"name": "월정리 해변"}, ensure_ascii=False),
        )
        asset = MediaAsset(
            asset_type="frame",
            video_id="e2e-video-1",
            storage_provider="rustfs",
            bucket="krtour-map",
            object_key="features/e2e-video-1/frame.jpg",
            object_uri="http://127.0.0.1:9003/krtour-map/features/e2e-video-1/frame.jpg",
            content_type="image/jpeg",
            size_bytes=1024,
            retention_policy="infinite",
        )
        mapping = VideoPlaceMapping(
            video_id="e2e-video-1",
            place_id=place.place_id,
            ai_summary="월정리 해변을 산책하고 카페 거리로 이동한다.",
            timestamp_start="00:00:45",
            timestamp_end="00:01:20",
        )

        session.add_all([candidate, run, queue_run, audit, asset, mapping])
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
