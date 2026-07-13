"""수집 영상 후처리 오케스트레이션 테스트."""

from __future__ import annotations

import json

from sqlalchemy import select

from ktc.etl import geocode_service
from ktc.etl.geocode_service import CandidateStateChangedError
from ktc.etl.geocoding import GeocodeCandidate, GeocodeDecision
from ktc.etl.media_store import InMemoryMediaStore
from ktc.etl.postprocess_service import (
    _GeocodeContext,
    _apply_geocoding,
    process_harvest_videos,
)
from ktc.etl.transcript import TranscriptResult, TranscriptSegment
from ktc.models import (
    CrawlStatus,
    ExtractedPlaceCandidate,
    MatchStatus,
    TravelPlace,
    VideoPlaceMapping,
    YoutubeVideo,
)
from ktc.services import place_service


async def test_process_harvest_videos_legacy_summary_stays_fail_closed(session):
    video = YoutubeVideo(
        video_id="busan-1",
        title="부산 맛집 투어",
        url="https://youtu.be/busan-1",
        channel_id="UC_BUSAN",
        description_raw="부산역 근처 돼지국밥집을 소개합니다.",
    )
    session.add(video)
    await session.commit()

    async def fetch_transcript(video_id: str):
        assert video_id == "busan-1"
        return TranscriptResult(
            video_id=video_id,
            source="transcript_api",
            segments=[TranscriptSegment(12.0, "부산역 국밥집에 왔습니다.")],
        )

    llm_payload = json.dumps(
        {
            "summary": "부산 맛집 요약",
            "description_gemini_corrected": "부산역 근처 돼지국밥집 소개",
            "places": [
                {
                    "name": "부산역 국밥집",
                    "location_hint": "부산 동구 초량동",
                    "category": "음식점",
                    "timestamp_start": "00:00:12",
                }
            ],
        },
        ensure_ascii=False,
    )
    geocode_queries: list[str] = []

    async def geocode_decider(candidate: ExtractedPlaceCandidate):
        geocode_queries.append(f"{candidate.location_hint} {candidate.ai_place_name}")
        return GeocodeDecision(
            status="matched",
            candidate=GeocodeCandidate(
                latitude=35.1151,
                longitude=129.0423,
                place_name="부산역 국밥집",
                road_address="부산광역시 동구 중앙대로",
                source="fake",
            ),
            confidence=1.0,
            reason="single_result",
            candidate_count=1,
        )

    reported: list[str] = []

    async def reporter(message: str, progress: float | None = None) -> None:
        reported.append(message)

    summary = await process_harvest_videos(
        session,
        video_ids=["busan-1"],
        limit=1,
        store=InMemoryMediaStore(),
        llm=lambda _: llm_payload,
        transcript_fetcher=fetch_transcript,
        geocode_decider=geocode_decider,
        status_reporter=reporter,
    )

    assert summary["processed_videos"] == 1
    assert summary["summarized_videos"] == 1
    assert summary["failed_videos"] == 0
    assert summary["created_candidates"] == 1
    assert summary["matched_places"] == 0
    assert summary["needs_review_candidates"] == 1
    assert geocode_queries == ["부산 동구 초량동 부산역 국밥집"]

    places = (await session.execute(select(TravelPlace))).scalars().all()
    assert places == []

    candidates = (await session.execute(select(ExtractedPlaceCandidate))).scalars().all()
    assert len(candidates) == 1
    assert candidates[0].match_status == MatchStatus.NEEDS_REVIEW
    assert candidates[0].matched_place_id is None
    assert candidates[0].review_note == "ungrounded"

    mappings = (await session.execute(select(VideoPlaceMapping))).scalars().all()
    assert mappings == []

    refreshed_video = await session.get(YoutubeVideo, "busan-1")
    assert refreshed_video.crawl_status == CrawlStatus.SUMMARIZED
    assert any("자막·장소 추출을 시작합니다" in message for message in reported)
    assert any("검수 큐에 남겼습니다" in message for message in reported)


async def test_process_harvest_videos_empty_video_ids_does_not_fall_back_to_backlog(
    session,
):
    """빈 video_ids는 '처리 대상 없음'으로 스코프돼야 한다.

    미완료 영상이 DB에 있어도 전역 백로그로 폴백하지 않는다(재생목록 harvest가
    신규 0개일 때 다른 재생목록의 예전 영상을 처리하던 회귀 방지).
    """
    session.add(
        YoutubeVideo(
            video_id="backlog-1",
            title="예전 부산 영상",
            url="https://youtu.be/backlog-1",
            channel_id="UC_OLD",
            description_raw="...",
            crawl_status=CrawlStatus.DISCOVERED,
        )
    )
    await session.commit()

    summary = await process_harvest_videos(
        session,
        video_ids=[],
        limit=20,
        store=InMemoryMediaStore(),
        llm=lambda _: "{}",
    )

    assert summary["processed_videos"] == 0
    assert summary["summarized_videos"] == 0


async def test_apply_geocoding_counts_state_changed_separately(session):
    session.add(
        YoutubeVideo(
            video_id="race-video",
            title="race",
            url="https://youtu.be/race-video",
            channel_id="race-channel",
        )
    )
    await session.commit()
    candidate = ExtractedPlaceCandidate(
        video_id="race-video",
        source_text="월정리 카페",
        ai_place_name="월정리 카페",
        candidate_category="카페",
        match_status=MatchStatus.NEEDS_REVIEW,
    )
    session.add(candidate)
    await session.commit()
    await session.refresh(candidate)

    async def decide(_candidate: ExtractedPlaceCandidate) -> GeocodeDecision:
        return GeocodeDecision("needs_review", None, 0.0, "no_result", 0)

    seen_versions: list[int] = []

    async def apply(_session, _candidate, _decision, expected_version):
        seen_versions.append(expected_version)
        raise CandidateStateChangedError(candidate.id)

    reported: list[str] = []

    async def reporter(message: str, _progress: float | None = None) -> None:
        reported.append(message)

    summary = {"matched_places": 0, "needs_review_candidates": 0}
    geocoded_any = await _apply_geocoding(
        session,
        [candidate],
        context=_GeocodeContext(decide, apply),
        summary=summary,
        status_reporter=reporter,
    )

    assert geocoded_any is False
    assert summary["matched_places"] == 0
    assert summary["needs_review_candidates"] == 0
    assert summary["skipped_state_changed_candidates"] == 1
    assert len(seen_versions) == 1
    assert seen_versions[0] > 0
    assert any("이미 처리되어" in message for message in reported)


async def test_apply_geocoding_provider_missing_rechecks_latest_state(
    session_factory,
    monkeypatch,
):
    async with session_factory() as seed_session:
        seed_session.add(
            YoutubeVideo(
                video_id="provider-missing-race",
                title="provider missing",
                url="https://youtu.be/provider-missing-race",
                channel_id="provider-missing-channel",
            )
        )
        await seed_session.commit()
        candidate = ExtractedPlaceCandidate(
            video_id="provider-missing-race",
            source_text="월정리 카페",
            ai_place_name="월정리 카페",
            candidate_category="카페",
            match_status=MatchStatus.NEEDS_REVIEW,
        )
        seed_session.add(candidate)
        await seed_session.commit()
        await seed_session.refresh(candidate)
        candidate_id = candidate.id

    original_is_current = geocode_service.candidate_geocode_snapshot_is_current

    async def ignore_then_check(session, checked_id, expected_version):
        async with session_factory() as reviewer_session:
            await place_service.resolve_candidate(
                reviewer_session,
                candidate_id=checked_id,
                action="ignore",
                reviewed_by="provider-missing-reviewer",
            )
        return await original_is_current(session, checked_id, expected_version)

    monkeypatch.setattr(
        geocode_service,
        "candidate_geocode_snapshot_is_current",
        ignore_then_check,
    )

    async def unused_applier(_session, _candidate, _decision, _expected_version):
        raise AssertionError("provider가 없으면 applier를 호출하지 않아야 한다")

    summary = {"matched_places": 0, "needs_review_candidates": 0}
    async with session_factory() as worker_session:
        worker_candidate = await worker_session.get(
            ExtractedPlaceCandidate, candidate_id
        )
        assert worker_candidate is not None
        geocoded_any = await _apply_geocoding(
            worker_session,
            [worker_candidate],
            context=_GeocodeContext(None, unused_applier),
            summary=summary,
            status_reporter=None,
        )

    assert geocoded_any is False
    assert summary["matched_places"] == 0
    assert summary["needs_review_candidates"] == 0
    assert summary["skipped_state_changed_candidates"] == 1


async def test_process_harvest_videos_keeps_candidate_when_geocoder_needs_review(session):
    video = YoutubeVideo(
        video_id="busan-2",
        title="부산 카페",
        url="https://youtu.be/busan-2",
        channel_id="UC_BUSAN",
    )
    session.add(video)
    await session.commit()

    async def fetch_transcript(video_id: str):
        return TranscriptResult(
            video_id=video_id,
            source="transcript_api",
            segments=[TranscriptSegment(20.0, "부산 카페를 소개합니다.")],
        )

    llm_payload = json.dumps(
        {
            "summary": "부산 카페 요약",
            "places": [{"name": "부산 바다 카페", "category": "카페"}],
        },
        ensure_ascii=False,
    )

    async def geocode_decider(candidate: ExtractedPlaceCandidate):
        return GeocodeDecision("needs_review", None, 0.0, "no_result", 0)

    summary = await process_harvest_videos(
        session,
        video_ids=["busan-2"],
        store=InMemoryMediaStore(),
        llm=lambda _: llm_payload,
        transcript_fetcher=fetch_transcript,
        geocode_decider=geocode_decider,
    )

    assert summary["created_candidates"] == 1
    assert summary["matched_places"] == 0
    assert summary["needs_review_candidates"] == 1
    assert (await session.execute(select(TravelPlace))).scalars().all() == []

    candidate = (await session.execute(select(ExtractedPlaceCandidate))).scalars().one()
    assert candidate.match_status == MatchStatus.NEEDS_REVIEW
