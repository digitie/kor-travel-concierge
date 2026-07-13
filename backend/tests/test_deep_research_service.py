"""Deep Research 결과 적용의 export 일관성·동시 보정 우선순위 테스트."""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import select

from ktc.etl import deep_research_service
from ktc.models import (
    ExportDirtyOutbox,
    ExtractedPlaceCandidate,
    FeatureExport,
    FeatureExportStatus,
    GroundingStatus,
    MatchStatus,
    TravelPlace,
    YoutubeChannel,
    YoutubeVideo,
)
from ktc.services import feature_export_service, place_service


async def _seed_co_matched_ready_candidates(session):
    """같은 장소를 공유하는 export 가능 후보 2건을 만든다."""
    channel = YoutubeChannel(channel_id="UC-deep-research", title="심층 여행 채널")
    video = YoutubeVideo(
        video_id="v-deep-research",
        title="골목 여행",
        url="https://www.youtube.com/watch?v=v-deep-research",
        canonical_url="https://www.youtube.com/watch?v=v-deep-research",
        channel_id=channel.channel_id,
        channel_name=channel.title,
        transcript_summary="오래된 장소 설명",
    )
    place = TravelPlace(
        name="검수 골목",
        description="기본 소개",
        gemini_enriched_description="기존 보강 설명",
        detailed_research_content="기존 상세 조사",
        latitude=37.571,
        longitude=126.991,
        category="거리",
    )
    session.add_all([channel, video, place])
    await session.flush()
    candidates = [
        ExtractedPlaceCandidate(
            video_id=video.video_id,
            source_channel_id=channel.channel_id,
            source_text=f"골목 근거 {index}",
            ai_place_name="검수 골목",
            match_status=MatchStatus.MATCHED.value,
            matched_place_id=place.place_id,
            grounding_status=GroundingStatus.VERIFIED_RAW.value,
            feature_export_status=FeatureExportStatus.READY.value,
            candidate_category="거리",
        )
        for index in range(2)
    ]
    session.add_all(candidates)
    await session.flush()
    candidate_ids = [candidate.id for candidate in candidates]
    await feature_export_service.mark_candidates_dirty(
        session,
        candidate_ids,
        reason="deep_research_test_seed",
    )
    await session.commit()
    return place.place_id, candidate_ids


async def test_deep_research_marks_all_co_matched_candidates_dirty(session):
    place_id, candidate_ids = await _seed_co_matched_ready_candidates(session)

    # Deep Research 전 ledger를 현재 상태로 맞춰, 이후 changed 건수가 오직 새 설명에서
    # 발생하도록 한다.
    assert await feature_export_service.sync_dirty(session) == 2
    assert await feature_export_service.sync_feature_exports(session) == 0
    place = await session.get(TravelPlace, place_id)
    assert place is not None

    async def fake_llm(_prompt: str) -> str:
        return json.dumps(
            {
                "detailed_research_content": "최신 동선과 방문 팁을 담은 상세 조사",
                "gemini_enriched_description": "최신 심층 조사 설명",
                "source_notes": ["테스트 근거"],
            },
            ensure_ascii=False,
        )

    result = await deep_research_service.research_place(
        session,
        place,
        prompt="동선 중심",
        llm=fake_llm,
    )

    assert result["status"] == "researched"
    assert result["stale_input"] is False
    assert result["applied"] is True
    assert result["changed"] is True
    dirty_ids = set(
        (
            await session.execute(
                select(ExportDirtyOutbox.candidate_id).order_by(
                    ExportDirtyOutbox.candidate_id
                )
            )
        ).scalars()
    )
    assert dirty_ids == set(candidate_ids)

    assert await feature_export_service.sync_dirty(session) == 2
    exports = list(
        (
            await session.execute(
                select(FeatureExport)
                .where(FeatureExport.candidate_id.in_(candidate_ids))
                .order_by(FeatureExport.candidate_id)
            )
        ).scalars()
    )
    assert len(exports) == 2
    assert {
        row.payload_json["place"]["gemini_enriched_description"]
        for row in exports
    } == {"최신 심층 조사 설명"}
    # dirty 증분 동기화가 전량 정합 상태와 정확히 같아야 한다(golden 불변식).
    assert await feature_export_service.sync_feature_exports(session) == 0


async def test_deep_research_discards_stale_result_after_human_correction(
    session_factory,
):
    async with session_factory() as seed_session:
        place = TravelPlace(
            name="사람 우선 장소",
            description="원래 기본 설명",
            gemini_enriched_description="원래 보강 설명",
            detailed_research_content="보존할 기존 상세 조사",
            latitude=35.18,
            longitude=129.08,
            category="명소",
        )
        seed_session.add(place)
        await seed_session.commit()
        place_id = place.place_id

    llm_started = asyncio.Event()
    release_llm = asyncio.Event()

    async def paused_llm(_prompt: str) -> str:
        llm_started.set()
        await release_llm.wait()
        return json.dumps(
            {
                "detailed_research_content": "사람 보정 전에 생성한 stale 상세 조사",
                "gemini_enriched_description": "사람 보정을 덮으면 안 되는 AI 설명",
                "source_notes": [],
            },
            ensure_ascii=False,
        )

    async def run_research() -> dict[str, object]:
        async with session_factory() as worker_session:
            worker_place = await worker_session.get(TravelPlace, place_id)
            assert worker_place is not None
            return await deep_research_service.research_place(
                worker_session,
                worker_place,
                prompt="동시성 검증",
                llm=paused_llm,
            )

    research_task = asyncio.create_task(run_research())
    try:
        await asyncio.wait_for(llm_started.wait(), timeout=5)
        async with session_factory() as reviewer_session:
            corrected = await place_service.correct_place(
                reviewer_session,
                place_id=place_id,
                updates={
                    "description": "사람이 고친 기본 설명",
                    "gemini_enriched_description": "사람이 확정한 보강 설명",
                },
            )
            human_revision = corrected.state_revision
        release_llm.set()
        result = await asyncio.wait_for(research_task, timeout=5)
    finally:
        release_llm.set()
        if not research_task.done():
            research_task.cancel()
        await asyncio.gather(research_task, return_exceptions=True)

    assert result["status"] == "stale_input"
    assert result["stale_input"] is True
    assert result["applied"] is False
    assert result["current_state_revision"] == human_revision
    assert result["current_state_revision"] != result["expected_state_revision"]

    async with session_factory() as check_session:
        current = await check_session.get(TravelPlace, place_id)
        assert current is not None
        assert current.state_revision == human_revision
        assert current.description == "사람이 고친 기본 설명"
        assert current.gemini_enriched_description == "사람이 확정한 보강 설명"
        assert current.detailed_research_content == "보존할 기존 상세 조사"
