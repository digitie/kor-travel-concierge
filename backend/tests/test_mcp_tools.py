"""TripMate MCP 도구 runtime 테스트."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models import (  # noqa: E402
    AuditLog,
    ExtractedPlaceCandidate,
    FeatureExportStatus,
    MatchStatus,
    MediaAsset,
    RunSource,
    TravelPlace,
    VideoPlaceMapping,
    YoutubeVideo,
)
from app.services import crawl_run_service  # noqa: E402
from tripmate_mcp.tools import ToolRuntime, tool_metadata  # noqa: E402


def _runtime(session_factory, *, write_enabled: bool = True) -> ToolRuntime:
    return ToolRuntime(session_factory=session_factory, write_enabled=write_enabled)


async def _add_place(session, name: str, lat: float, lng: float, **kwargs):
    place = TravelPlace(name=name, latitude=lat, longitude=lng, **kwargs)
    session.add(place)
    await session.commit()
    await session.refresh(place)
    return place


async def _add_video_and_candidate(session):
    video = YoutubeVideo(video_id="video-1", title="부산 여행", url="https://youtu.be/1", channel_id="ch")
    session.add(video)
    await session.commit()
    candidate = ExtractedPlaceCandidate(
        video_id=video.video_id,
        source_text="해운대 해변을 산책합니다.",
        ai_place_name="해운대",
        speaker_note="바다 산책",
        location_hint="부산 해운대구",
        timestamp_start="00:01:00",
        candidate_category="beach",
        match_status=MatchStatus.NEEDS_REVIEW,
    )
    session.add(candidate)
    await session.commit()
    await session.refresh(candidate)
    return video, candidate


async def test_harvest_travel_destinations_creates_mcp_run_and_is_idempotent(session_factory):
    runtime = _runtime(session_factory)

    first = await runtime.harvest_travel_destinations(
        idempotency_key="harvest-key-1",
        query="부산 맛집",
        max_videos=7,
    )
    second = await runtime.harvest_travel_destinations(
        idempotency_key="harvest-key-1",
        query="부산 맛집",
        max_videos=7,
    )

    assert first["job_id"] == second["job_id"]
    assert first["idempotent"] is False
    assert second["idempotent"] is True
    async with session_factory() as session:
        run = await crawl_run_service.get_run(session, int(first["job_id"]))
        assert run.source == RunSource.MCP
        assert run.target_type == "keyword"
        assert run.target_id == "부산 맛집"
        logs = (await session.execute(select(AuditLog))).scalars().all()
        assert len(logs) == 1
        assert logs[0].action == "harvest.create"


async def test_get_harvest_status_returns_result_payload(session_factory):
    async with session_factory() as session:
        run = await crawl_run_service.create_run(
            session,
            job_type="harvest",
            source=RunSource.MCP,
            target_type="playlist",
            target_id="PL123",
        )
        await crawl_run_service.append_status_log(
            session, run.id, "YouTube 재생목록을 확인 중입니다.", progress=0.4
        )
        await crawl_run_service.mark_done(session, run.id, result={"created": 2})

    status = await _runtime(session_factory).get_harvest_status(job_id=run.id)

    assert status["state"] == "done"
    assert status["result"] == {"created": 2}
    assert status["current_message"] == "작업을 완료했습니다."
    assert any("YouTube 재생목록" in log["message"] for log in status["status_logs"])


async def test_search_existing_places_supports_query_category_and_radius(session_factory):
    async with session_factory() as session:
        await _add_place(session, "해운대 해수욕장", 35.1587, 129.1604, category="beach", is_geocoded=True)
        await _add_place(session, "광안리 해수욕장", 35.1532, 129.1186, category="beach", is_geocoded=True)
        await _add_place(session, "서울숲", 37.5444, 127.0374, category="park", is_geocoded=True)

    result = await _runtime(session_factory).search_existing_places(
        query="해수욕장",
        latitude=35.1587,
        longitude=129.1604,
        radius_meters=5_000,
        category="beach",
    )

    names = [place["name"] for place in result["places"]]
    assert names == ["해운대 해수욕장", "광안리 해수욕장"]
    assert result["places"][0]["distance_meters"] == 0


async def test_correct_place_updates_fields_and_records_audit(session_factory):
    async with session_factory() as session:
        place = await _add_place(session, "해운대", 35.1587, 129.1604)

    result = await _runtime(session_factory).correct_place(
        idempotency_key="correct-key-1",
        place_id=place.place_id,
        name="해운대 해수욕장",
        official_address="부산 해운대구 우동",
        category="beach",
    )

    assert result["place"]["name"] == "해운대 해수욕장"
    async with session_factory() as session:
        refreshed = await session.get(TravelPlace, place.place_id)
        assert refreshed.official_address == "부산 해운대구 우동"
        logs = (await session.execute(select(AuditLog))).scalars().all()
        assert logs[0].action == "place.correct"


async def test_merge_places_moves_mappings_and_deletes_source(session_factory):
    async with session_factory() as session:
        target = await _add_place(session, "해운대 해수욕장", 35.1587, 129.1604)
        source = await _add_place(session, "해운대", 35.1588, 129.1605, description="중복 설명")
        video = YoutubeVideo(video_id="video-merge", title="t", url="u", channel_id="c")
        session.add(video)
        await session.commit()
        mapping = VideoPlaceMapping(
            video_id=video.video_id,
            place_id=source.place_id,
            ai_summary="요약",
        )
        asset = MediaAsset(
            asset_type="frame",
            video_id=video.video_id,
            place_id=source.place_id,
            bucket="tripmate-frames",
            object_key="video-merge/frame.jpg",
            object_uri="http://localhost:9003/tripmate-frames/video-merge/frame.jpg",
        )
        session.add_all([mapping, asset])
        await session.commit()

    result = await _runtime(session_factory).merge_places(
        idempotency_key="merge-key-1",
        source_place_id=source.place_id,
        target_place_id=target.place_id,
    )

    assert result["target_place"]["place_id"] == target.place_id
    async with session_factory() as session:
        assert await session.get(TravelPlace, source.place_id) is None
        moved = (await session.execute(select(VideoPlaceMapping))).scalars().one()
        assert moved.place_id == target.place_id
        moved_asset = (await session.execute(select(MediaAsset))).scalars().one()
        assert moved_asset.place_id == target.place_id
        refreshed_target = await session.get(TravelPlace, target.place_id)
        assert refreshed_target.description == "중복 설명"


async def test_idempotency_key_rejects_parameter_mismatch(session_factory):
    runtime = _runtime(session_factory)

    await runtime.harvest_travel_destinations(
        idempotency_key="harvest-key-2",
        query="부산 맛집",
    )

    with pytest.raises(ValueError, match="다른 요청 파라미터"):
        await runtime.harvest_travel_destinations(
            idempotency_key="harvest-key-2",
            query="제주 맛집",
        )


async def test_trigger_deep_research_creates_pending_run(session_factory):
    async with session_factory() as session:
        place = await _add_place(session, "감천문화마을", 35.0975, 129.0106)

    result = await _runtime(session_factory).trigger_deep_research(
        idempotency_key="research-key-1",
        place_id=place.place_id,
        prompt="역사와 포토존 중심",
        max_sources=5,
    )

    assert result["state"] == "pending"
    async with session_factory() as session:
        run = await crawl_run_service.get_run(session, int(result["job_id"]))
        assert run.job_type == "deep_research"
        assert run.target_type == "place"
        assert run.target_id == str(place.place_id)


async def test_review_unmatched_place_updates_review_metadata(session_factory):
    async with session_factory() as session:
        _, candidate = await _add_video_and_candidate(session)

    result = await _runtime(session_factory).review_unmatched_place(
        idempotency_key="review-key-1",
        candidate_id=candidate.id,
        reviewed_by="tester",
        review_note="좌표 확인 필요",
    )

    assert result["candidate"]["reviewed_by"] == "tester"
    assert result["candidate"]["review_note"] == "좌표 확인 필요"


async def test_resolve_place_candidate_create_place_adds_mapping(session_factory):
    async with session_factory() as session:
        _, candidate = await _add_video_and_candidate(session)

    result = await _runtime(session_factory).resolve_place_candidate(
        idempotency_key="resolve-key-1",
        candidate_id=candidate.id,
        action="create_place",
        corrected_name="해운대 해수욕장",
        latitude=35.1587,
        longitude=129.1604,
        category="beach",
        reviewed_by="tester",
    )

    assert result["candidate"]["match_status"] == MatchStatus.USER_CORRECTED
    assert result["candidate"]["feature_export_status"] == FeatureExportStatus.READY
    assert result["place"]["name"] == "해운대 해수욕장"
    async with session_factory() as session:
        mappings = (await session.execute(select(VideoPlaceMapping))).scalars().all()
        assert len(mappings) == 1
        assert mappings[0].place_candidate_id == candidate.id
        assert mappings[0].feature_export_status == FeatureExportStatus.READY


async def test_resolve_place_candidate_can_ignore_candidate(session_factory):
    async with session_factory() as session:
        _, candidate = await _add_video_and_candidate(session)

    result = await _runtime(session_factory).resolve_place_candidate(
        idempotency_key="ignore-key-1",
        candidate_id=candidate.id,
        action="ignore",
        reviewed_by="tester",
        review_note="장소 아님",
    )

    assert result["candidate"]["match_status"] == MatchStatus.IGNORED
    assert result["candidate"]["feature_export_status"] == FeatureExportStatus.REJECTED
    assert result["place"] is None
    assert result["mapping"] is None


async def test_write_disabled_blocks_write_tools(session_factory):
    runtime = _runtime(session_factory, write_enabled=False)

    with pytest.raises(PermissionError):
        await runtime.harvest_travel_destinations(
            idempotency_key="blocked-1",
            query="제주",
        )

    metadata = tool_metadata(write_enabled=False)
    assert [tool["name"] for tool in metadata] == [
        "get_harvest_status",
        "search_existing_places",
        "get_place_detail",
    ]
