"""PinVi MCP 도구 runtime 테스트."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ktc.models import (  # noqa: E402
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
from ktc.etl import admin_region_service  # noqa: E402
from ktc.mcp_server import tools as mcp_tools  # noqa: E402
from ktc.services import crawl_run_service, place_service, settings_service  # noqa: E402
from ktc.mcp_server.tools import (  # noqa: E402
    CorrectPlaceInput,
    HarvestTravelDestinationsInput,
    MergePlacesInput,
    ResolvePlaceCandidateInput,
    ReviewUnmatchedPlaceInput,
    ToolRuntime,
    TriggerDeepResearchInput,
    tool_metadata,
)


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
        assert logs[0].idempotency_key == "harvest-key-1"
        assert logs[0].idempotency_state == "final"


async def test_concurrent_same_key_first_write_creates_one_run_and_audit(
    session_factory,
    monkeypatch,
):
    real_create_run = crawl_run_service.create_run
    create_started = asyncio.Event()
    resume_create = asyncio.Event()
    created_run_ids: list[int] = []

    async def pause_first_create(*args, **kwargs):
        run = await real_create_run(*args, **kwargs)
        created_run_ids.append(run.id)
        create_started.set()
        await resume_create.wait()
        return run

    monkeypatch.setattr(crawl_run_service, "create_run", pause_first_create)
    runtime = _runtime(session_factory)
    request = {
        "idempotency_key": "harvest-concurrent-key-1",
        "query": "동시 멱등 수집",
    }
    first_task = asyncio.create_task(runtime.harvest_travel_destinations(**request))
    second_task = None
    try:
        await asyncio.wait_for(create_started.wait(), timeout=10)
        second_task = asyncio.create_task(
            runtime.harvest_travel_destinations(**request)
        )
        await asyncio.sleep(0.1)
        assert len(created_run_ids) == 1
        resume_create.set()
        first, second = await asyncio.wait_for(
            asyncio.gather(first_task, second_task),
            timeout=10,
        )
    finally:
        resume_create.set()
        pending_tasks = [first_task]
        if second_task is not None:
            pending_tasks.append(second_task)
        for task in pending_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending_tasks, return_exceptions=True)

    assert first["job_id"] == second["job_id"]
    assert {first["idempotent"], second["idempotent"]} == {False, True}
    async with session_factory() as session:
        logs = (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "harvest.create")
            )
        ).scalars().all()
        assert len(logs) == 1
        assert logs[0].idempotency_key == request["idempotency_key"]
        assert logs[0].idempotency_state == "final"


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


async def test_correct_place_coordinates_enrich_after_mcp_audit_commit(
    session_factory,
    monkeypatch,
):
    async with session_factory() as session:
        place = await _add_place(session, "해운대", 35.1587, 129.1604)
    observed: list[int] = []

    async def fake_isolated(factory, place_id, **_kwargs):
        async with factory() as verify_session:
            logs = (await verify_session.execute(select(AuditLog))).scalars().all()
            assert any(log.action == "place.correct" for log in logs)
        observed.append(place_id)
        return False

    monkeypatch.setattr(
        admin_region_service,
        "enrich_place_admin_codes_isolated",
        fake_isolated,
    )

    result = await _runtime(session_factory).correct_place(
        idempotency_key="correct-coordinate-key-1",
        place_id=place.place_id,
        latitude=35.159,
        longitude=129.161,
    )

    assert result["place"]["latitude"] == 35.159
    assert result["place"]["longitude"] == 129.161
    assert observed == [place.place_id]


async def test_correct_place_does_not_return_deleted_place_after_admin_wait(
    session_factory,
    monkeypatch,
):
    async with session_factory() as session:
        place = await _add_place(session, "삭제될 장소", 35.1587, 129.1604)

    async def delete_during_admin(factory, place_id, **_kwargs):
        async with factory() as delete_session:
            current = await delete_session.get(TravelPlace, place_id)
            assert current is not None
            await delete_session.delete(current)
            await delete_session.commit()
        return False

    monkeypatch.setattr(
        admin_region_service,
        "enrich_place_admin_codes_isolated",
        delete_during_admin,
    )
    runtime = _runtime(session_factory)
    request = {
        "idempotency_key": "correct-delete-during-admin-1",
        "place_id": place.place_id,
        "latitude": 35.159,
        "longitude": 129.161,
    }

    result = await runtime.correct_place(**request)
    retried = await runtime.correct_place(**request)

    assert result["place"] is None
    assert retried["place"] is None
    assert retried["idempotent"] is True


async def test_pending_correct_audit_recovers_current_place_after_process_crash(
    session_factory,
):
    async with session_factory() as session:
        place = await _add_place(
            session,
            "crash 뒤 보존된 장소",
            35.1587,
            129.1604,
            official_address="부산광역시 해운대구",
        )
        kwargs = {
            "idempotency_key": "correct-pending-crash-1",
            "place_id": place.place_id,
            "name": "crash 뒤 보존된 장소",
        }
        request = CorrectPlaceInput.model_validate(kwargs).model_dump(
            exclude_none=True
        )
        pending = AuditLog(
            actor_type="mcp",
            action="place.correct",
            target_type="travel_place",
            target_id=str(place.place_id),
            idempotency_key=kwargs["idempotency_key"],
            idempotency_state="pending",
            payload_json=json.dumps(
                {
                    "idempotency_key": kwargs["idempotency_key"],
                    "idempotency_state": "pending",
                    "pending_owner": "crashed-correct-owner",
                    "lease_expires_at": "2000-01-01T00:00:00+00:00",
                    "postprocess_place_id": None,
                    "request": request,
                    # crash 전 임시 snapshot은 재생되면 안 된다.
                    "result": {
                        "place": {"place_id": place.place_id, "name": "stale"},
                        "idempotent": False,
                    },
                },
                ensure_ascii=False,
            ),
        )
        session.add(pending)
        await session.commit()
        pending_id = pending.id

    recovered = await _runtime(session_factory).correct_place(**kwargs)

    assert recovered["idempotent"] is True
    assert recovered["audit_log_id"] == pending_id
    assert recovered["place"]["name"] == "crash 뒤 보존된 장소"
    assert recovered["place"]["official_address"] == "부산광역시 해운대구"
    async with session_factory() as session:
        log = await session.get(AuditLog, pending_id)
        payload = json.loads(log.payload_json)
        assert log.idempotency_state == "final"
        assert payload["idempotency_state"] == "final"
        assert payload["result"]["place"]["name"] == "crash 뒤 보존된 장소"


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
            bucket="ktc-frames",
            object_key="video-merge/frame.jpg",
            object_uri="http://localhost:12101/ktc-frames/video-merge/frame.jpg",
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


async def test_indexed_idempotency_lookup_ignores_205_newer_payload_rows(
    session_factory,
):
    async with session_factory() as session:
        final_place = await _add_place(session, "final 원본", 35.1, 129.1)
        pending_place = await _add_place(session, "pending 원본", 35.2, 129.2)
        final_kwargs = {
            "idempotency_key": "correct-old-final-key",
            "place_id": final_place.place_id,
            "name": "실행되면 안 되는 final 보정",
        }
        pending_kwargs = {
            "idempotency_key": "correct-old-pending-key",
            "place_id": pending_place.place_id,
            "name": "실행되면 안 되는 pending 보정",
        }
        final_request = CorrectPlaceInput.model_validate(final_kwargs).model_dump(
            exclude_none=True
        )
        pending_request = CorrectPlaceInput.model_validate(
            pending_kwargs
        ).model_dump(exclude_none=True)
        session.add_all(
            [
                AuditLog(
                    actor_type="mcp",
                    action="place.correct",
                    target_type="travel_place",
                    target_id=str(final_place.place_id),
                    idempotency_key=final_kwargs["idempotency_key"],
                    idempotency_state="final",
                    payload_json=json.dumps(
                        {
                            "idempotency_key": final_kwargs["idempotency_key"],
                            "idempotency_state": "final",
                            "request": final_request,
                            "result": {
                                "place": {"name": "200행 뒤 final 결과"},
                                "idempotent": False,
                            },
                        },
                        ensure_ascii=False,
                    ),
                ),
                AuditLog(
                    actor_type="mcp",
                    action="place.correct",
                    target_type="travel_place",
                    target_id=str(pending_place.place_id),
                    idempotency_key=pending_kwargs["idempotency_key"],
                    idempotency_state="pending",
                    payload_json=json.dumps(
                        {
                            "idempotency_key": pending_kwargs["idempotency_key"],
                            "idempotency_state": "pending",
                            "pending_owner": "still-active-owner",
                            "lease_expires_at": mcp_tools._new_pending_lease()[1],
                            "postprocess_place_id": None,
                            "request": pending_request,
                            "result": {"place": {"name": "stale"}},
                        },
                        ensure_ascii=False,
                    ),
                ),
            ]
        )
        for index in range(205):
            if index == 0:
                payload_json = "{"
            elif index == 1:
                payload_json = "[]"
            else:
                payload_json = json.dumps(
                    {"idempotency_key": f"newer-noise-{index}"}
                )
            session.add(
                AuditLog(
                    actor_type="mcp",
                    action="place.correct",
                    target_type="travel_place",
                    target_id=str(final_place.place_id),
                    payload_json=payload_json,
                )
            )
        await session.commit()

    runtime = _runtime(session_factory)
    final_replay = await runtime.correct_place(**final_kwargs)
    pending_replay = await runtime.correct_place(**pending_kwargs)

    assert final_replay["idempotent"] is True
    assert final_replay["place"]["name"] == "200행 뒤 final 결과"
    assert pending_replay["status"] == "pending"
    assert pending_replay["recoverable"] is False
    assert "place" not in pending_replay
    async with session_factory() as session:
        assert (await session.get(TravelPlace, final_place.place_id)).name == "final 원본"
        assert (await session.get(TravelPlace, pending_place.place_id)).name == "pending 원본"
        logs = (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "place.correct")
            )
        ).scalars().all()
        assert len(logs) == 207
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            (
                await session.execute(
                    text(
                        """
                        EXPLAIN (COSTS OFF)
                        SELECT *
                        FROM audit_logs
                        WHERE actor_type = 'mcp'
                          AND action = 'place.correct'
                          AND idempotency_key = :idempotency_key
                        """
                    ),
                    {"idempotency_key": final_kwargs["idempotency_key"]},
                )
            ).scalars()
        )
        assert "uq_audit_logs_actor_action_idempotency_key" in plan


async def test_indexed_idempotency_with_corrupt_payload_fails_closed(
    session_factory,
):
    async with session_factory() as session:
        place = await _add_place(session, "손상 payload 원본", 35.3, 129.3)
        kwargs = {
            "idempotency_key": "correct-corrupt-payload-key",
            "place_id": place.place_id,
            "name": "실행되면 안 되는 보정",
        }
        session.add(
            AuditLog(
                actor_type="mcp",
                action="place.correct",
                target_type="travel_place",
                target_id=str(place.place_id),
                idempotency_key=kwargs["idempotency_key"],
                idempotency_state="final",
                payload_json="{",
            )
        )
        await session.commit()

    with pytest.raises(ValueError, match="payload JSON이 손상"):
        await _runtime(session_factory).correct_place(**kwargs)

    async with session_factory() as session:
        current = await session.get(TravelPlace, place.place_id)
        assert current.name == "손상 payload 원본"


async def test_idempotency_column_payload_state_drift_fails_closed(
    session_factory,
):
    async with session_factory() as session:
        place = await _add_place(session, "state drift 원본", 35.4, 129.4)
        kwargs = {
            "idempotency_key": "correct-state-drift-key",
            "place_id": place.place_id,
            "name": "실행되면 안 되는 drift 보정",
        }
        request = CorrectPlaceInput.model_validate(kwargs).model_dump(
            exclude_none=True
        )
        session.add(
            AuditLog(
                actor_type="mcp",
                action="place.correct",
                target_type="travel_place",
                target_id=str(place.place_id),
                idempotency_key=kwargs["idempotency_key"],
                idempotency_state="final",
                payload_json=json.dumps(
                    {
                        "idempotency_key": kwargs["idempotency_key"],
                        "idempotency_state": "pending",
                        "request": request,
                        "result": {"place": {"name": "stale"}},
                    }
                ),
            )
        )
        await session.commit()

    with pytest.raises(ValueError, match="전용 column과 payload"):
        await _runtime(session_factory).correct_place(**kwargs)

    async with session_factory() as session:
        current = await session.get(TravelPlace, place.place_id)
        assert current.name == "state drift 원본"


@pytest.mark.parametrize(
    "lease_expires_at",
    (
        None,
        123,
        "not-a-datetime",
        "2026-07-13T01:02:03",
        "0001-01-01T00:00:00+14:00",
    ),
)
def test_missing_malformed_or_overflowing_pending_lease_is_recoverable(
    lease_expires_at,
):
    assert (
        mcp_tools._pending_lease_expired(
            {"lease_expires_at": lease_expires_at}
        )
        is True
    )


def test_pending_lease_timezone_oserror_is_recoverable(monkeypatch):
    class ExplodingAwareDatetime:
        tzinfo = object()

        @staticmethod
        def utcoffset():
            return 0

        @staticmethod
        def astimezone(_timezone):
            raise OSError("timezone conversion failed")

    class ExplodingDatetime:
        @staticmethod
        def fromisoformat(_value):
            return ExplodingAwareDatetime()

    monkeypatch.setattr(mcp_tools, "datetime", ExplodingDatetime)

    assert mcp_tools._pending_lease_expired({"lease_expires_at": "valid"}) is True


def test_pending_lease_only_accepts_bounded_future_window():
    now = mcp_tools.datetime.now(mcp_tools.timezone.utc)
    active = now + mcp_tools.timedelta(seconds=30)
    expired = now - mcp_tools.timedelta(seconds=1)
    far_future = now + mcp_tools.timedelta(
        seconds=(
            mcp_tools._IDEMPOTENCY_PENDING_LEASE_SECONDS
            + mcp_tools._IDEMPOTENCY_PENDING_LEASE_TOLERANCE_SECONDS
            + 30
        )
    )

    assert (
        mcp_tools._pending_lease_expired(
            {"lease_expires_at": active.isoformat()}
        )
        is False
    )
    assert (
        mcp_tools._pending_lease_expired(
            {"lease_expires_at": expired.isoformat()}
        )
        is True
    )
    assert (
        mcp_tools._pending_lease_expired(
            {"lease_expires_at": far_future.isoformat()}
        )
        is True
    )


@pytest.mark.parametrize(
    ("input_model", "kwargs"),
    (
        (HarvestTravelDestinationsInput, {"query": "부산"}),
        (CorrectPlaceInput, {"place_id": 1, "name": "보정"}),
        (MergePlacesInput, {"source_place_id": 1, "target_place_id": 2}),
        (TriggerDeepResearchInput, {"place_id": 1}),
        (ReviewUnmatchedPlaceInput, {"candidate_id": 1}),
        (
            ResolvePlaceCandidateInput,
            {"candidate_id": 1, "action": "ignore"},
        ),
    ),
)
def test_all_write_inputs_enforce_db_idempotency_key_limit(
    input_model,
    kwargs,
):
    accepted = input_model.model_validate(
        {"idempotency_key": "k" * 255, **kwargs}
    )
    assert len(accepted.idempotency_key) == 255

    with pytest.raises(ValueError):
        input_model.model_validate(
            {"idempotency_key": "k" * 256, **kwargs}
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


async def test_review_unmatched_place_rejects_resolved_candidate_without_audit(
    session_factory,
):
    async with session_factory() as session:
        _, candidate = await _add_video_and_candidate(session)
        candidate_id = candidate.id
        await place_service.resolve_candidate(
            session,
            candidate_id=candidate_id,
            action="ignore",
            reviewed_by="first-reviewer",
            review_note="먼저 제외",
        )

    with pytest.raises(place_service.CandidateResolveConflictError):
        await _runtime(session_factory).review_unmatched_place(
            idempotency_key="review-resolved-key-1",
            candidate_id=candidate_id,
            reviewed_by="stale-reviewer",
            review_note="뒤늦은 검수",
        )

    async with session_factory() as session:
        current = await session.get(ExtractedPlaceCandidate, candidate_id)
        assert current is not None
        assert current.match_status == MatchStatus.IGNORED.value
        assert current.reviewed_by == "first-reviewer"
        assert current.review_note == "먼저 제외"
        review_audits = (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "candidate.review")
            )
        ).scalars().all()
        assert review_audits == []


async def test_resolve_place_candidate_create_place_adds_mapping(
    session_factory,
    monkeypatch,
):
    async with session_factory() as session:
        _, candidate = await _add_video_and_candidate(session)
    observed: list[int] = []

    async def fake_isolated(factory, place_id, **_kwargs):
        async with factory() as verify_session:
            logs = (await verify_session.execute(select(AuditLog))).scalars().all()
            assert any(log.action == "candidate.resolve" for log in logs)
        observed.append(place_id)
        return False

    monkeypatch.setattr(
        admin_region_service,
        "enrich_place_admin_codes_isolated",
        fake_isolated,
    )

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
    assert observed == [result["place"]["place_id"]]
    async with session_factory() as session:
        mappings = (await session.execute(select(VideoPlaceMapping))).scalars().all()
        assert len(mappings) == 1
        assert mappings[0].place_candidate_id == candidate.id
        assert mappings[0].feature_export_status == FeatureExportStatus.READY


async def test_resolve_returns_postcommit_force_exclude_state_and_replays_it(
    session_factory,
    monkeypatch,
):
    async with session_factory() as session:
        video, candidate = await _add_video_and_candidate(session)
        video_id = video.video_id
        candidate_id = candidate.id
    forced: list[int] = []

    async def force_exclude_after_audit(_session, *, place_id, **_kwargs):
        async with session_factory() as force_session:
            summary = await place_service.exclude_video(
                force_session,
                video_id,
                reason="resolve 응답 전 강제 제외",
                excluded_by="concurrent-reviewer",
            )
        assert summary is not None
        forced.append(place_id)
        return None

    monkeypatch.setattr(
        place_service,
        "enrich_place_admin_codes_postcommit",
        force_exclude_after_audit,
    )
    runtime = _runtime(session_factory)
    request = {
        "idempotency_key": "resolve-force-exclude-1",
        "candidate_id": candidate_id,
        "action": "create_place",
        "corrected_name": "응답 전 제외 장소",
        "latitude": 35.1587,
        "longitude": 129.1604,
        "reviewed_by": "tester",
    }

    result = await runtime.resolve_place_candidate(**request)
    retried = await runtime.resolve_place_candidate(**request)

    assert len(forced) == 1
    assert result["candidate"]["matched_place_id"] is None
    assert result["place"] is None
    assert result["mapping"] is None
    assert retried["candidate"]["matched_place_id"] is None
    assert retried["place"] is None
    assert retried["mapping"] is None
    assert retried["idempotent"] is True


async def test_active_pending_resolve_retry_waits_and_replays_post_exclude_state(
    session_factory,
    monkeypatch,
):
    async with session_factory() as session:
        video, candidate = await _add_video_and_candidate(session)
        video_id = video.video_id
        candidate_id = candidate.id

    admin_started = asyncio.Event()
    resume_admin = asyncio.Event()

    async def pause_admin(_session, *, place_id, **_kwargs):
        admin_started.set()
        await resume_admin.wait()
        return None

    monkeypatch.setattr(
        place_service,
        "enrich_place_admin_codes_postcommit",
        pause_admin,
    )
    runtime = _runtime(session_factory)
    request = {
        "idempotency_key": "resolve-pending-admin-retry-1",
        "candidate_id": candidate_id,
        "action": "create_place",
        "corrected_name": "pending admin 장소",
        "latitude": 35.1587,
        "longitude": 129.1604,
        "reviewed_by": "tester",
    }
    original_task = asyncio.create_task(
        runtime.resolve_place_candidate(**request)
    )
    try:
        await asyncio.wait_for(admin_started.wait(), timeout=10)
        async with session_factory() as session:
            log = (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == "candidate.resolve")
                )
            ).scalars().one()
            pending_payload = json.loads(log.payload_json)
            assert log.idempotency_state == "pending"
            assert pending_payload["idempotency_state"] == "pending"
            assert pending_payload["pending_owner"]
            assert pending_payload["lease_expires_at"]
            assert pending_payload["postprocess_place_id"] is not None

        # 활성 owner의 lease 동안 재시도는 임시 core snapshot을 확정하지 않는다.
        active_retry = await runtime.resolve_place_candidate(**request)
        assert active_retry["status"] == "pending"
        assert active_retry["code"] == "idempotency_pending"
        assert active_retry["recoverable"] is False
        assert "candidate" not in active_retry
        assert "place" not in active_retry
        assert "mapping" not in active_retry
        async with session_factory() as session:
            log = (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == "candidate.resolve")
                )
            ).scalars().one()
            assert json.loads(log.payload_json)["idempotency_state"] == "pending"

        # 원 요청이 admin에서 멈춘 동안 별도 사용자 결정이 core 결과를 제거한다.
        async with session_factory() as force_session:
            excluded = await place_service.exclude_video(
                force_session,
                video_id,
                reason="pending retry 전 강제 제외",
                excluded_by="concurrent-reviewer",
            )
            assert excluded is not None

        resume_admin.set()
        original = await asyncio.wait_for(original_task, timeout=10)
        final_retry = await runtime.resolve_place_candidate(**request)
    finally:
        resume_admin.set()
        if not original_task.done():
            original_task.cancel()
        await asyncio.gather(original_task, return_exceptions=True)

    for result in (original, final_retry):
        assert result["candidate"]["matched_place_id"] is None
        assert result["place"] is None
        assert result["mapping"] is None
    assert original["idempotent"] is False
    assert final_retry["idempotent"] is True
    async with session_factory() as session:
        log = (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "candidate.resolve")
            )
        ).scalars().one()
        payload = json.loads(log.payload_json)
        assert log.idempotency_state == "final"
        assert payload["idempotency_state"] == "final"
        assert "pending_owner" not in payload
        assert "lease_expires_at" not in payload
        assert payload["result"]["candidate"]["matched_place_id"] is None
        assert payload["result"]["place"] is None
        assert payload["result"]["mapping"] is None


async def test_pending_resolve_audit_recovers_authoritative_mapping_after_crash(
    session_factory,
    monkeypatch,
):
    postprocessed: list[int] = []

    async def fake_postprocess(_session, *, place_id, **_kwargs):
        postprocessed.append(place_id)
        return None

    monkeypatch.setattr(
        place_service,
        "enrich_place_admin_codes_postcommit",
        fake_postprocess,
    )
    async with session_factory() as session:
        video, candidate = await _add_video_and_candidate(session)
        place = await _add_place(
            session,
            "crash 복구 장소",
            35.1587,
            129.1604,
            is_geocoded=True,
        )
        candidate.match_status = MatchStatus.USER_CORRECTED
        candidate.matched_place_id = place.place_id
        candidate.feature_export_status = FeatureExportStatus.READY.value
        mapping = VideoPlaceMapping(
            video_id=video.video_id,
            place_id=place.place_id,
            place_candidate_id=candidate.id,
            ai_summary=candidate.source_text,
            feature_export_status=FeatureExportStatus.READY.value,
        )
        session.add(mapping)
        kwargs = {
            "idempotency_key": "resolve-pending-crash-1",
            "candidate_id": candidate.id,
            "action": "match_existing",
            "place_id": place.place_id,
            "reviewed_by": "tester",
        }
        request = ResolvePlaceCandidateInput.model_validate(kwargs).model_dump(
            mode="json", exclude_none=True
        )
        pending = AuditLog(
            actor_type="mcp",
            action="candidate.resolve",
            target_type="extracted_place_candidate",
            target_id=str(candidate.id),
            idempotency_key=kwargs["idempotency_key"],
            idempotency_state="pending",
            payload_json=json.dumps(
                {
                    "idempotency_key": kwargs["idempotency_key"],
                    "idempotency_state": "pending",
                    "pending_owner": "crashed-resolve-owner",
                    "lease_expires_at": "not-a-datetime",
                    "postprocess_place_id": place.place_id,
                    "request": request,
                    "result": {
                        "candidate": {"candidate_id": candidate.id},
                        "place": None,
                        "mapping": None,
                        "idempotent": False,
                    },
                },
                ensure_ascii=False,
            ),
        )
        session.add(pending)
        await session.commit()
        pending_id = pending.id
        candidate_id = candidate.id
        place_id = place.place_id

    recovered = await _runtime(session_factory).resolve_place_candidate(**kwargs)

    assert recovered["idempotent"] is True
    assert recovered["audit_log_id"] == pending_id
    assert recovered["candidate"]["candidate_id"] == candidate_id
    assert recovered["candidate"]["matched_place_id"] == place_id
    assert recovered["place"]["place_id"] == place_id
    assert recovered["mapping"]["place_id"] == place_id
    assert postprocessed == [place_id]
    async with session_factory() as session:
        log = await session.get(AuditLog, pending_id)
        payload = json.loads(log.payload_json)
        assert log.idempotency_state == "final"
        assert payload["idempotency_state"] == "final"
        assert payload["result"]["mapping"]["place_id"] == place_id


async def test_stolen_owner_cannot_apply_late_admin_result_after_new_owner_final(
    session_factory,
    monkeypatch,
):
    async with session_factory() as session:
        video, candidate = await _add_video_and_candidate(session)
        place = await _add_place(
            session,
            "owner fence 장소",
            35.1587,
            129.1604,
            is_geocoded=True,
        )
        candidate.match_status = MatchStatus.USER_CORRECTED
        candidate.matched_place_id = place.place_id
        candidate.feature_export_status = FeatureExportStatus.READY.value
        session.add(
            VideoPlaceMapping(
                video_id=video.video_id,
                place_id=place.place_id,
                place_candidate_id=candidate.id,
                ai_summary=candidate.source_text,
                feature_export_status=FeatureExportStatus.READY.value,
            )
        )
        kwargs = {
            "idempotency_key": "resolve-owner-fence-1",
            "candidate_id": candidate.id,
            "action": "match_existing",
            "place_id": place.place_id,
            "reviewed_by": "tester",
        }
        request = ResolvePlaceCandidateInput.model_validate(kwargs).model_dump(
            mode="json", exclude_none=True
        )
        pending = AuditLog(
            actor_type="mcp",
            action="candidate.resolve",
            target_type="extracted_place_candidate",
            target_id=str(candidate.id),
            idempotency_key=kwargs["idempotency_key"],
            idempotency_state="pending",
            payload_json=json.dumps(
                {
                    "idempotency_key": kwargs["idempotency_key"],
                    "idempotency_state": "pending",
                    "pending_owner": "crashed-owner",
                    "postprocess_place_id": place.place_id,
                    "request": request,
                    "result": {"place": None, "idempotent": False},
                },
                ensure_ascii=False,
            ),
        )
        session.add(pending)
        await session.commit()
        audit_log_id = pending.id
        place_id = place.place_id

    owner_b_active_lease = mcp_tools._new_pending_lease()[1]
    leases = iter(
        (
            ("owner-a", "2000-01-01T00:00:00+00:00"),
            ("owner-b", owner_b_active_lease),
        )
    )
    monkeypatch.setattr(mcp_tools, "_new_pending_lease", lambda: next(leases))
    monkeypatch.setattr(
        admin_region_service,
        "get_settings",
        lambda: SimpleNamespace(KOR_TRAVEL_GEO_V2_BASE_URL="http://geo.test"),
    )

    async def fake_secret(_session, _key):
        return "test-key"

    owner_a_http_started = asyncio.Event()
    resume_owner_a_http = asyncio.Event()
    resolve_calls = 0

    async def fake_resolve_admin(_snapshot, **_kwargs):
        nonlocal resolve_calls
        resolve_calls += 1
        if resolve_calls == 1:
            owner_a_http_started.set()
            await resume_owner_a_http.wait()
            return admin_region_service.AdminRegion(
                sigungu_code="99999",
                sigungu_name="늦은 owner A",
                legal_dong_code="9999999999",
                legal_dong_name="늦은 owner A 결과",
            )
        if resolve_calls == 2:
            # owner B는 place/xmin을 바꾸지 않은 채 pre-admin 상태를 final로 확정한다.
            return None
        raise AssertionError("예상하지 않은 admin 조회 횟수")

    monkeypatch.setattr(settings_service, "get_secret", fake_secret)
    monkeypatch.setattr(
        admin_region_service,
        "resolve_admin_region",
        fake_resolve_admin,
    )
    runtime = _runtime(session_factory)
    owner_a_task = asyncio.create_task(runtime.resolve_place_candidate(**kwargs))
    try:
        await asyncio.wait_for(owner_a_http_started.wait(), timeout=10)
        owner_b = await runtime.resolve_place_candidate(**kwargs)
        assert owner_b["place"]["sigungu_code"] is None
        assert owner_b["place"]["legal_dong_code"] is None

        resume_owner_a_http.set()
        owner_a = await asyncio.wait_for(owner_a_task, timeout=10)
    finally:
        resume_owner_a_http.set()
        if not owner_a_task.done():
            owner_a_task.cancel()
        await asyncio.gather(owner_a_task, return_exceptions=True)

    assert resolve_calls == 2
    assert owner_a["place"] == owner_b["place"]
    assert owner_a["idempotent"] is True
    assert owner_b["idempotent"] is True
    async with session_factory() as session:
        current = await session.get(TravelPlace, place_id)
        assert current.sigungu_code is None
        assert current.sigungu_name is None
        assert current.legal_dong_code is None
        assert current.legal_dong_name is None
        audit_log = await session.get(AuditLog, audit_log_id)
        payload = json.loads(audit_log.payload_json)
        assert audit_log.idempotency_state == "final"
        assert payload["idempotency_state"] == "final"
        assert payload["result"]["place"]["sigungu_code"] is None
        assert payload["result"]["place"]["legal_dong_code"] is None


async def test_resolve_place_candidate_returns_nearby_choices_and_retries(session_factory):
    async with session_factory() as session:
        existing = await _add_place(
            session,
            "기존 장소",
            35.1587,
            129.1604,
            is_geocoded=True,
        )
        _, candidate = await _add_video_and_candidate(session)

    runtime = _runtime(session_factory)
    first = await runtime.resolve_place_candidate(
        idempotency_key="resolve-nearby-key-1",
        candidate_id=candidate.id,
        action="create_place",
        corrected_name="별도 장소",
        latitude=35.1588,
        longitude=129.1604,
        reviewed_by="tester",
    )

    assert first["status"] == "confirmation_required"
    assert first["code"] == "nearby_place_confirmation_required"
    assert first["nearby_places"][0]["place_id"] == existing.place_id

    retried = await runtime.resolve_place_candidate(
        idempotency_key="resolve-nearby-key-1",
        candidate_id=candidate.id,
        action="create_place",
        corrected_name="별도 장소",
        latitude=35.1588,
        longitude=129.1604,
        duplicate_resolution="create_new",
        reviewed_by="tester",
    )

    assert retried["place"]["place_id"] != existing.place_id
    assert retried["candidate"]["match_status"] == MatchStatus.USER_CORRECTED


async def test_resolve_place_candidate_rejects_invalid_selected_hit_timestamps(
    session_factory,
):
    runtime = _runtime(session_factory)
    selected_hit = {
        "provider": "kakao",
        "native_id": "kakao-timestamp-1",
        "query": "타임스탬프 검증",
        "searched_at": "2026-07-13T01:00:00Z",
        "selected_at": "2026-07-13T01:00:01Z",
        "name": "타임스탬프 검증 장소",
        "latitude": 37.0,
        "longitude": 127.0,
    }
    request = {
        "idempotency_key": "resolve-timestamp-1",
        "candidate_id": 999999,
        "action": "create_place",
        "corrected_name": "타임스탬프 검증 장소",
        "latitude": 37.0,
        "longitude": 127.0,
    }

    for invalid_hit in (
        {**selected_hit, "searched_at": "2026-07-13T01:00:00"},
        {**selected_hit, "selected_at": "2026-07-13T01:00:01"},
    ):
        with pytest.raises(ValueError, match="timezone"):
            await runtime.resolve_place_candidate(
                **request,
                selected_hit=invalid_hit,
            )

    with pytest.raises(ValueError, match="선택 시각은 검색 시각보다"):
        await runtime.resolve_place_candidate(
            **request,
            selected_hit={
                **selected_hit,
                "searched_at": "2026-07-13T01:00:02Z",
                "selected_at": "2026-07-13T01:00:01Z",
            },
        )


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
