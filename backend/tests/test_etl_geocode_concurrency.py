"""지오코딩과 사용자 검수가 경합하는 PostgreSQL 회귀 테스트."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select, text

from ktc.core.spatial import sync_place_geometry
from ktc.etl import admin_region_service, geocode_service
from ktc.etl.geocode_service import (
    apply_geocode_to_candidate,
    apply_geocode_to_current_candidate,
    read_candidate_geocode_snapshot,
)
from ktc.etl.geocoding import GeocodeCandidate, GeocodeDecision
from ktc.etl.postprocess_service import _GeocodeContext, _apply_geocoding
from ktc.models import (
    EvidenceSourceKind,
    ExtractedPlaceCandidate,
    GroundingStatus,
    MatchStatus,
    TravelPlace,
    VideoPlaceMapping,
    YoutubeVideo,
)
from ktc.services import place_service


async def test_apply_geocoding_skips_ignore_reopen_aba_by_xmin(session_factory):
    """최종 상태가 다시 needs_review여도 외부 호출 전 row version만 적용한다."""
    async with session_factory() as seed_session:
        seed_session.add(
            YoutubeVideo(
                video_id="geocode-aba",
                title="월정리 카페 영상",
                url="https://youtu.be/geocode-aba",
                channel_id="UC_GEOCODE_ABA",
            )
        )
        await seed_session.commit()
        candidate = ExtractedPlaceCandidate(
            video_id="geocode-aba",
            source_text="월정리 카페를 방문했습니다.",
            ai_place_name="월정리 카페",
            candidate_category="카페",
            match_status=MatchStatus.NEEDS_REVIEW,
            source_kind=EvidenceSourceKind.TRANSCRIPT.value,
            grounding_status=GroundingStatus.VERIFIED_RAW.value,
            is_domestic=True,
        )
        seed_session.add(candidate)
        await seed_session.commit()
        await seed_session.refresh(candidate)
        candidate_id = candidate.id

    decider_entered = asyncio.Event()
    resume_decider = asyncio.Event()
    applied_expected_versions: list[int] = []

    async def decide(_candidate: ExtractedPlaceCandidate) -> GeocodeDecision:
        # _apply_geocoding은 이 callback 전에 xmin snapshot을 읽고 transaction을 닫는다.
        decider_entered.set()
        await resume_decider.wait()
        return GeocodeDecision(
            status="matched",
            candidate=GeocodeCandidate(
                latitude=33.5563,
                longitude=126.7958,
                place_name="월정리 카페",
                road_address="제주특별자치도 제주시 구좌읍",
                source="kakao_keyword",
            ),
            confidence=1.0,
            reason="single_result",
            candidate_count=1,
        )

    async def apply(
        session,
        candidate: ExtractedPlaceCandidate,
        decision: GeocodeDecision,
        expected_candidate_version: int,
    ):
        applied_expected_versions.append(expected_candidate_version)
        return await apply_geocode_to_candidate(
            session,
            candidate,
            decision,
            expected_candidate_version=expected_candidate_version,
        )

    summary = {
        "matched_places": 0,
        "needs_review_candidates": 0,
        "skipped_state_changed_candidates": 0,
    }
    async with session_factory() as worker_session:
        worker_candidate = await worker_session.get(
            ExtractedPlaceCandidate, candidate_id
        )
        assert worker_candidate is not None
        worker_task = asyncio.create_task(
            _apply_geocoding(
                worker_session,
                [worker_candidate],
                context=_GeocodeContext(decide, apply),
                summary=summary,
                status_reporter=None,
            )
        )
        try:
            await asyncio.wait_for(decider_entered.wait(), timeout=10)

            async with session_factory() as reviewer_session:
                ignored, _, _ = await place_service.resolve_candidate(
                    reviewer_session,
                    candidate_id=candidate_id,
                    action="ignore",
                    reviewed_by="aba-reviewer",
                    commit=True,
                )
                assert ignored.match_status == MatchStatus.IGNORED.value

                undo_token = place_service.encode_candidate_undo_token(ignored)
                reopen_result = await place_service.reopen_candidate(
                    reviewer_session,
                    candidate_id=candidate_id,
                    undo_token=undo_token,
                )
                reopened = reopen_result.candidate
                assert reopen_result.reopened_from == "ignored"
                assert reopened.match_status == MatchStatus.NEEDS_REVIEW.value
                await reviewer_session.commit()

                reopened_snapshot = await read_candidate_geocode_snapshot(
                    reviewer_session, candidate_id
                )
                assert reopened_snapshot is not None
                assert reopened_snapshot.eligible is True
                await reviewer_session.commit()

            resume_decider.set()
            geocoded_any = await asyncio.wait_for(worker_task, timeout=10)
        finally:
            resume_decider.set()
            if not worker_task.done():
                worker_task.cancel()
            await asyncio.gather(worker_task, return_exceptions=True)

    assert geocoded_any is False
    assert len(applied_expected_versions) == 1
    assert applied_expected_versions[0] != reopened_snapshot.version
    assert summary["matched_places"] == 0
    assert summary["needs_review_candidates"] == 0
    assert summary["skipped_state_changed_candidates"] == 1

    async with session_factory() as check_session:
        current = await check_session.get(ExtractedPlaceCandidate, candidate_id)
        assert current is not None
        assert current.match_status == MatchStatus.NEEDS_REVIEW.value
        assert current.deleted_at is None
        assert current.matched_place_id is None
        assert "geocoding" not in (current.provider_evidence_json or {})
        assert (await check_session.execute(select(TravelPlace))).scalars().all() == []
        assert (
            await check_session.execute(select(VideoPlaceMapping))
        ).scalars().all() == []


def _matched_decision(
    name: str,
    *,
    latitude: float = 33.5563,
    longitude: float = 126.7958,
):
    return GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(
            latitude=latitude,
            longitude=longitude,
            place_name=name,
            road_address="제주특별자치도 제주시 구좌읍",
            source="kakao_keyword",
        ),
        confidence=1.0,
        reason="single_result",
        candidate_count=1,
    )


async def test_concurrent_auto_matches_share_one_place(
    session_factory,
    monkeypatch,
):
    """서로 다른 후보도 advisory lock 아래 최종 중복 조회→생성을 직렬화한다."""
    async with session_factory() as seed_session:
        seed_session.add_all(
            [
                YoutubeVideo(
                    video_id=f"geocode-auto-{index}",
                    title="월정리 카페 영상",
                    url=f"https://youtu.be/geocode-auto-{index}",
                    channel_id=f"UC_GEOCODE_AUTO_{index}",
                )
                for index in (1, 2)
            ]
        )
        await seed_session.commit()
        candidates = [
            ExtractedPlaceCandidate(
                video_id=f"geocode-auto-{index}",
                source_text="월정리 카페를 방문했습니다.",
                ai_place_name="월정리 카페",
                candidate_category="카페",
                match_status=MatchStatus.NEEDS_REVIEW,
                source_kind=EvidenceSourceKind.TRANSCRIPT.value,
                grounding_status=GroundingStatus.VERIFIED_RAW.value,
                is_domestic=True,
            )
            for index in (1, 2)
        ]
        seed_session.add_all(candidates)
        await seed_session.commit()
        candidate_ids = [candidate.id for candidate in candidates]

    original_lock = geocode_service._lock_current_candidate_for_geocode
    first_candidate_locked = asyncio.Event()
    resume_first = asyncio.Event()
    first_paused = False

    async def pause_first_candidate_lock(session, candidate_id):
        nonlocal first_paused
        current, version = await original_lock(session, candidate_id)
        if (
            current is not None
            and current.match_status == MatchStatus.NEEDS_REVIEW.value
            and not first_paused
        ):
            first_paused = True
            first_candidate_locked.set()
            await resume_first.wait()
        return current, version

    monkeypatch.setattr(
        geocode_service,
        "_lock_current_candidate_for_geocode",
        pause_first_candidate_lock,
    )

    second_pid_ready = asyncio.Event()
    second_pid: int | None = None
    lifecycle_call_count = 0
    original_lifecycle_lock = place_service.acquire_place_lifecycle_lock

    async def capture_second_lifecycle_pid(session):
        nonlocal lifecycle_call_count, second_pid
        lifecycle_call_count += 1
        if lifecycle_call_count == 2:
            # lifecycle lock을 요청할 바로 그 transaction/connection의 PID다.
            # 앞선 snapshot commit이나 pool 재할당과 무관하게 pg_locks 관측
            # 대상이 실제 lock waiter와 일치한다.
            second_pid = int(
                (
                    await session.execute(text("SELECT pg_backend_pid()"))
                ).scalar_one()
            )
            second_pid_ready.set()
        await original_lifecycle_lock(session)

    monkeypatch.setattr(
        place_service,
        "acquire_place_lifecycle_lock",
        capture_second_lifecycle_pid,
    )

    async def apply_one(candidate_id: int):
        async with session_factory() as worker_session:
            candidate = await worker_session.get(ExtractedPlaceCandidate, candidate_id)
            assert candidate is not None
            return await apply_geocode_to_current_candidate(
                worker_session,
                candidate,
                _matched_decision("월정리 카페"),
            )

    first_task = asyncio.create_task(apply_one(candidate_ids[0]))
    second_task: asyncio.Task[TravelPlace | None] | None = None
    try:
        await asyncio.wait_for(first_candidate_locked.wait(), timeout=10)
        second_task = asyncio.create_task(apply_one(candidate_ids[1]))
        await asyncio.wait_for(second_pid_ready.wait(), timeout=10)
        assert second_pid is not None

        # 첫 worker는 lifecycle advisory -> candidate 순서로 잠금을 보유한다. 둘째는
        # candidate row가 서로 달라도 같은 lifecycle lock에서 기다려야 두 요청이 동시에
        # "근접 장소 없음"을 보고 중복 장소를 만들지 않는다.
        second_waits_for_lifecycle = False
        async with session_factory() as monitor_session:
            wait_deadline = asyncio.get_running_loop().time() + 10
            while asyncio.get_running_loop().time() < wait_deadline:
                waits_for_lifecycle = bool(
                    (
                        await monitor_session.execute(
                            text(
                                "SELECT EXISTS ("
                                "SELECT 1 FROM pg_locks "
                                "WHERE pid = :pid AND locktype = 'advisory' "
                                "AND granted = false AND classid::bigint = 0 "
                                "AND objid::bigint = :lock_id AND objsubid = 1"
                                ")"
                            ),
                            {
                                "pid": second_pid,
                                "lock_id": place_service.PLACE_LIFECYCLE_ADVISORY_LOCK_ID,
                            },
                        )
                    ).scalar_one()
                )
                await monitor_session.commit()
                if waits_for_lifecycle:
                    second_waits_for_lifecycle = True
                    break
                await asyncio.sleep(0.02)
        assert second_waits_for_lifecycle is True

        resume_first.set()
        results = await asyncio.wait_for(
            asyncio.gather(first_task, second_task),
            timeout=10,
        )
    finally:
        resume_first.set()
        pending = [first_task]
        if second_task is not None:
            pending.append(second_task)
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    assert all(place is not None for place in results)
    assert len({place.place_id for place in results if place is not None}) == 1
    async with session_factory() as check_session:
        places = (await check_session.execute(select(TravelPlace))).scalars().all()
        mappings = (
            await check_session.execute(select(VideoPlaceMapping))
        ).scalars().all()
        assert len(places) == 1
        assert len(mappings) == 2
        assert {mapping.place_id for mapping in mappings} == {places[0].place_id}


async def test_core_geocode_and_merge_lock_lifecycle_before_candidate_predicate(
    session_factory,
    monkeypatch,
):
    """core geocode가 candidate보다 먼저 lifecycle lock을 잡아 merge predicate-gap을 막는다."""
    async with session_factory() as seed_session:
        seed_session.add(
            YoutubeVideo(
                video_id="geocode-core-merge-lifecycle",
                title="core 지오코딩 병합 경합",
                url="https://youtu.be/geocode-core-merge-lifecycle",
                channel_id="UC_GEOCODE_CORE_MERGE_LIFECYCLE",
            )
        )
        await seed_session.commit()
        source_place = TravelPlace(
            name="월정리 카페",
            latitude=33.5563,
            longitude=126.7958,
            category="카페",
            category_code_suggestion="01010100",
            is_geocoded=True,
        )
        target_place = TravelPlace(
            name="월정리 카페 통합본",
            latitude=37.5665,
            longitude=126.978,
            category="카페",
            category_code_suggestion="01010100",
            is_geocoded=True,
        )
        seed_session.add_all([source_place, target_place])
        await seed_session.flush()
        await sync_place_geometry(
            seed_session,
            source_place.place_id,
            source_place.latitude,
            source_place.longitude,
        )
        await sync_place_geometry(
            seed_session,
            target_place.place_id,
            target_place.latitude,
            target_place.longitude,
        )
        candidate = ExtractedPlaceCandidate(
            video_id="geocode-core-merge-lifecycle",
            source_text="월정리 카페를 방문했습니다.",
            ai_place_name="월정리 카페",
            candidate_category="카페",
            match_status=MatchStatus.NEEDS_REVIEW,
            source_kind=EvidenceSourceKind.TRANSCRIPT.value,
            grounding_status=GroundingStatus.VERIFIED_RAW.value,
            is_domestic=True,
        )
        seed_session.add(candidate)
        await seed_session.commit()
        source_place_id = source_place.place_id
        target_place_id = target_place.place_id
        candidate_id = candidate.id

    core_candidate_locked = asyncio.Event()
    resume_core = asyncio.Event()
    admin_started = asyncio.Event()
    resume_admin = asyncio.Event()
    original_candidate_lock = geocode_service._lock_current_candidate_for_geocode
    paused = False

    async def pause_after_core_candidate_lock(session, locked_candidate_id):
        nonlocal paused
        current, version = await original_candidate_lock(session, locked_candidate_id)
        if (
            current is not None
            and current.match_status == MatchStatus.NEEDS_REVIEW.value
            and not paused
        ):
            paused = True
            core_candidate_locked.set()
            await resume_core.wait()
        return current, version

    async def pause_admin(_factory, _place_id, **_kwargs):
        admin_started.set()
        await resume_admin.wait()
        return False

    monkeypatch.setattr(
        geocode_service,
        "_lock_current_candidate_for_geocode",
        pause_after_core_candidate_lock,
    )
    monkeypatch.setattr(
        admin_region_service,
        "enrich_place_admin_codes_isolated",
        pause_admin,
    )

    merge_pid_ready = asyncio.Event()
    merge_pid: int | None = None

    async def merge_concurrently() -> int:
        nonlocal merge_pid
        async with session_factory() as merge_session:
            merge_pid = int(
                (
                    await merge_session.execute(text("SELECT pg_backend_pid()"))
                ).scalar_one()
            )
            await merge_session.commit()
            merge_pid_ready.set()
            merged = await place_service.merge_places(
                merge_session,
                source_place_id=source_place_id,
                target_place_id=target_place_id,
            )
            return merged.place_id

    async with session_factory() as worker_session:
        worker_candidate = await worker_session.get(
            ExtractedPlaceCandidate, candidate_id
        )
        assert worker_candidate is not None
        worker_task = asyncio.create_task(
            apply_geocode_to_current_candidate(
                worker_session,
                worker_candidate,
                _matched_decision("월정리 카페"),
            )
        )
        merge_task: asyncio.Task[int] | None = None
        try:
            await asyncio.wait_for(core_candidate_locked.wait(), timeout=10)
            merge_task = asyncio.create_task(merge_concurrently())
            await asyncio.wait_for(merge_pid_ready.wait(), timeout=10)
            assert merge_pid is not None

            # geocode는 candidate FOR UPDATE보다 먼저 lifecycle advisory를 잡았다.
            # 따라서 아직 committed predicate가 needs_review여도 merge는 candidate 조회로
            # 진입하지 못하고 advisory에서 대기해야 한다.
            merge_is_waiting = False
            async with session_factory() as monitor_session:
                for _ in range(200):
                    wait_event_type = (
                        await monitor_session.execute(
                            text(
                                "SELECT wait_event_type FROM pg_stat_activity "
                                "WHERE pid = :pid"
                            ),
                            {"pid": merge_pid},
                        )
                    ).scalar_one_or_none()
                    await monitor_session.commit()
                    if wait_event_type == "Lock":
                        merge_is_waiting = True
                        break
                    await asyncio.sleep(0.01)
            assert merge_is_waiting is True

            resume_core.set()
            await asyncio.wait_for(admin_started.wait(), timeout=10)
            merged_place_id = await asyncio.wait_for(merge_task, timeout=10)
            resume_admin.set()
            with pytest.raises(geocode_service.CandidateStateChangedError):
                await asyncio.wait_for(worker_task, timeout=10)
        finally:
            resume_core.set()
            resume_admin.set()
            pending = [worker_task]
            if merge_task is not None:
                pending.append(merge_task)
            for task in pending:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    assert merged_place_id == target_place_id
    async with session_factory() as check_session:
        current_candidate = await check_session.get(
            ExtractedPlaceCandidate, candidate_id
        )
        assert current_candidate is not None
        assert current_candidate.match_status == MatchStatus.MATCHED.value
        assert current_candidate.matched_place_id == target_place_id
        assert await check_session.get(TravelPlace, source_place_id) is None
        mappings = (
            await check_session.execute(
                select(VideoPlaceMapping).where(
                    VideoPlaceMapping.place_candidate_id == candidate_id
                )
            )
        ).scalars().all()
        assert len(mappings) == 1
        assert mappings[0].place_id == target_place_id


async def test_core_geocode_and_exclude_video_serialize_orphan_decision(
    session_factory,
    monkeypatch,
):
    """영상 제외가 uncommitted attach를 건너뛰어 공유 장소를 고아 삭제하지 않는다."""
    async with session_factory() as seed_session:
        seed_session.add_all(
            [
                YoutubeVideo(
                    video_id="geocode-core-exclude-worker",
                    title="지오코딩으로 장소를 연결할 영상",
                    url="https://youtu.be/geocode-core-exclude-worker",
                    channel_id="UC_GEOCODE_CORE_EXCLUDE_WORKER",
                ),
                YoutubeVideo(
                    video_id="geocode-core-exclude-target",
                    title="제외할 legacy mapping 영상",
                    url="https://youtu.be/geocode-core-exclude-target",
                    channel_id="UC_GEOCODE_CORE_EXCLUDE_TARGET",
                ),
            ]
        )
        await seed_session.commit()
        place = TravelPlace(
            name="월정리 카페",
            latitude=33.5563,
            longitude=126.7958,
            category="카페",
            category_code_suggestion="01010100",
            is_geocoded=True,
        )
        seed_session.add(place)
        await seed_session.flush()
        await sync_place_geometry(
            seed_session, place.place_id, place.latitude, place.longitude
        )
        candidate = ExtractedPlaceCandidate(
            video_id="geocode-core-exclude-worker",
            source_text="월정리 카페를 방문했습니다.",
            ai_place_name="월정리 카페",
            candidate_category="카페",
            match_status=MatchStatus.NEEDS_REVIEW,
            source_kind=EvidenceSourceKind.TRANSCRIPT.value,
            grounding_status=GroundingStatus.VERIFIED_RAW.value,
            is_domestic=True,
        )
        seed_session.add(candidate)
        await seed_session.flush()
        seed_session.add(
            VideoPlaceMapping(
                video_id="geocode-core-exclude-target",
                place_id=place.place_id,
                place_candidate_id=None,
                ai_summary="제외 영상의 candidate 없는 legacy mapping",
            )
        )
        await seed_session.commit()
        place_id = place.place_id
        candidate_id = candidate.id

    core_candidate_locked = asyncio.Event()
    resume_core = asyncio.Event()
    original_candidate_lock = geocode_service._lock_current_candidate_for_geocode
    paused = False

    async def pause_after_core_candidate_lock(session, locked_candidate_id):
        nonlocal paused
        current, version = await original_candidate_lock(session, locked_candidate_id)
        if (
            current is not None
            and current.match_status == MatchStatus.NEEDS_REVIEW.value
            and not paused
        ):
            paused = True
            core_candidate_locked.set()
            await resume_core.wait()
        return current, version

    async def skip_admin(_factory, _place_id, **_kwargs):
        return False

    monkeypatch.setattr(
        geocode_service,
        "_lock_current_candidate_for_geocode",
        pause_after_core_candidate_lock,
    )
    monkeypatch.setattr(
        admin_region_service,
        "enrich_place_admin_codes_isolated",
        skip_admin,
    )

    exclude_pid_ready = asyncio.Event()
    exclude_pid: int | None = None

    async def exclude_concurrently() -> dict:
        nonlocal exclude_pid
        async with session_factory() as exclude_session:
            exclude_pid = int(
                (
                    await exclude_session.execute(text("SELECT pg_backend_pid()"))
                ).scalar_one()
            )
            await exclude_session.commit()
            exclude_pid_ready.set()
            result = await place_service.exclude_video(
                exclude_session,
                "geocode-core-exclude-target",
                reason="동시 지오코딩 중 영상 제외",
                excluded_by="concurrent-reviewer",
            )
            assert result is not None
            return result

    async with session_factory() as worker_session:
        worker_candidate = await worker_session.get(
            ExtractedPlaceCandidate, candidate_id
        )
        assert worker_candidate is not None
        worker_task = asyncio.create_task(
            apply_geocode_to_current_candidate(
                worker_session,
                worker_candidate,
                _matched_decision("월정리 카페"),
            )
        )
        exclude_task: asyncio.Task[dict] | None = None
        try:
            await asyncio.wait_for(core_candidate_locked.wait(), timeout=10)
            exclude_task = asyncio.create_task(exclude_concurrently())
            await asyncio.wait_for(exclude_pid_ready.wait(), timeout=10)
            assert exclude_pid is not None

            exclude_is_waiting = False
            async with session_factory() as monitor_session:
                for _ in range(200):
                    wait_event_type = (
                        await monitor_session.execute(
                            text(
                                "SELECT wait_event_type FROM pg_stat_activity "
                                "WHERE pid = :pid"
                            ),
                            {"pid": exclude_pid},
                        )
                    ).scalar_one_or_none()
                    await monitor_session.commit()
                    if wait_event_type == "Lock":
                        exclude_is_waiting = True
                        break
                    await asyncio.sleep(0.01)
            assert exclude_is_waiting is True

            resume_core.set()
            matched, excluded = await asyncio.wait_for(
                asyncio.gather(worker_task, exclude_task),
                timeout=10,
            )
        finally:
            resume_core.set()
            pending = [worker_task]
            if exclude_task is not None:
                pending.append(exclude_task)
            for task in pending:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    assert matched is not None
    assert matched.place_id == place_id
    assert excluded["deleted_mappings"] == 1
    assert excluded["deleted_places"] == 0
    async with session_factory() as check_session:
        assert await check_session.get(TravelPlace, place_id) is not None
        current_candidate = await check_session.get(
            ExtractedPlaceCandidate, candidate_id
        )
        assert current_candidate is not None
        assert current_candidate.match_status == MatchStatus.MATCHED.value
        assert current_candidate.matched_place_id == place_id
        mappings = (
            await check_session.execute(
                select(VideoPlaceMapping).where(
                    VideoPlaceMapping.place_id == place_id
                )
            )
        ).scalars().all()
        assert len(mappings) == 1
        assert mappings[0].place_candidate_id == candidate_id


async def test_final_duplicate_read_preserves_concurrent_place_correction(
    session_factory,
    monkeypatch,
):
    """preflight가 적재한 stale 장소 대신 final lock에서 최신 사용자 보정을 쓴다."""
    async with session_factory() as seed_session:
        seed_session.add(
            YoutubeVideo(
                video_id="geocode-place-refresh",
                title="사용자 보정 경합",
                url="https://youtu.be/geocode-place-refresh",
                channel_id="UC_GEOCODE_PLACE_REFRESH",
            )
        )
        await seed_session.commit()
        place = TravelPlace(
            name="보정 전 이름",
            latitude=33.5563,
            longitude=126.7958,
            category="미지정",
            category_code_suggestion="0",
            is_geocoded=True,
        )
        seed_session.add(place)
        await seed_session.flush()
        await sync_place_geometry(
            seed_session, place.place_id, place.latitude, place.longitude
        )
        candidate = ExtractedPlaceCandidate(
            video_id="geocode-place-refresh",
            source_text="사용자 보정 이름을 방문했습니다.",
            ai_place_name="사용자 보정 이름",
            candidate_category="카페",
            match_status=MatchStatus.NEEDS_REVIEW,
            source_kind=EvidenceSourceKind.TRANSCRIPT.value,
            grounding_status=GroundingStatus.VERIFIED_RAW.value,
            is_domestic=True,
            provider_evidence_json={"transcript": {"category_code": "01010100"}},
        )
        seed_session.add(candidate)
        await seed_session.commit()
        place_id = place.place_id
        candidate_id = candidate.id

    original_lock = geocode_service._lock_current_candidate_for_geocode
    preflight_finished = asyncio.Event()
    resume_final_read = asyncio.Event()
    paused = False

    async def pause_before_final_candidate_lock(session, locked_candidate_id):
        nonlocal paused
        if not paused:
            paused = True
            preflight_finished.set()
            await resume_final_read.wait()
        return await original_lock(session, locked_candidate_id)

    monkeypatch.setattr(
        geocode_service,
        "_lock_current_candidate_for_geocode",
        pause_before_final_candidate_lock,
    )

    async with session_factory() as worker_session:
        worker_candidate = await worker_session.get(
            ExtractedPlaceCandidate, candidate_id
        )
        assert worker_candidate is not None
        task = asyncio.create_task(
            apply_geocode_to_current_candidate(
                worker_session,
                worker_candidate,
                _matched_decision("사용자 보정 이름"),
                vworld=object(),
            )
        )
        try:
            await asyncio.wait_for(preflight_finished.wait(), timeout=10)
            async with session_factory() as reviewer_session:
                current_place = await reviewer_session.get(TravelPlace, place_id)
                assert current_place is not None
                current_place.name = "사용자 보정 이름"
                current_place.category = "사용자 지정 카테고리"
                current_place.category_code_suggestion = "01050100"
                await reviewer_session.commit()
            resume_final_read.set()
            matched = await asyncio.wait_for(task, timeout=10)
        finally:
            resume_final_read.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert matched is not None
    assert matched.place_id == place_id
    assert matched.name == "사용자 보정 이름"
    assert matched.category == "사용자 지정 카테고리"
    assert matched.category_code_suggestion == "01050100"


async def test_post_core_force_exclude_shared_place_becomes_typed_skip(
    session_factory,
    monkeypatch,
):
    """core commit 뒤 후보 매핑만 제거돼도 공유 장소 refresh 성공으로 오판하지 않는다."""
    async with session_factory() as seed_session:
        seed_session.add_all(
            [
                YoutubeVideo(
                    video_id="geocode-force-exclude",
                    title="제외할 영상",
                    url="https://youtu.be/geocode-force-exclude",
                    channel_id="UC_GEOCODE_FORCE_EXCLUDE",
                ),
                YoutubeVideo(
                    video_id="geocode-shared-reference",
                    title="공유 장소 영상",
                    url="https://youtu.be/geocode-shared-reference",
                    channel_id="UC_GEOCODE_SHARED_REFERENCE",
                ),
            ]
        )
        await seed_session.commit()
        place = TravelPlace(
            name="월정리 카페",
            latitude=33.5563,
            longitude=126.7958,
            category="카페",
            category_code_suggestion="01010100",
            is_geocoded=True,
        )
        seed_session.add(place)
        await seed_session.flush()
        await sync_place_geometry(
            seed_session, place.place_id, place.latitude, place.longitude
        )
        candidate = ExtractedPlaceCandidate(
            video_id="geocode-force-exclude",
            source_text="월정리 카페를 방문했습니다.",
            ai_place_name="월정리 카페",
            candidate_category="카페",
            match_status=MatchStatus.NEEDS_REVIEW,
            source_kind=EvidenceSourceKind.TRANSCRIPT.value,
            grounding_status=GroundingStatus.VERIFIED_RAW.value,
            is_domestic=True,
        )
        seed_session.add(candidate)
        await seed_session.flush()
        seed_session.add(
            VideoPlaceMapping(
                video_id="geocode-shared-reference",
                place_id=place.place_id,
                ai_summary="다른 영상의 공유 근거",
            )
        )
        await seed_session.commit()
        place_id = place.place_id
        candidate_id = candidate.id

    admin_started = asyncio.Event()
    resume_admin = asyncio.Event()

    async def pause_admin(_factory, _place_id, **_kwargs):
        admin_started.set()
        await resume_admin.wait()
        return False

    monkeypatch.setattr(
        admin_region_service,
        "enrich_place_admin_codes_isolated",
        pause_admin,
    )

    async with session_factory() as worker_session:
        worker_candidate = await worker_session.get(
            ExtractedPlaceCandidate, candidate_id
        )
        assert worker_candidate is not None
        task = asyncio.create_task(
            apply_geocode_to_current_candidate(
                worker_session,
                worker_candidate,
                _matched_decision("월정리 카페"),
            )
        )
        try:
            await asyncio.wait_for(admin_started.wait(), timeout=10)
            async with session_factory() as reviewer_session:
                excluded = await place_service.exclude_video(
                    reviewer_session,
                    "geocode-force-exclude",
                    reason="검수자가 영상 제외",
                    excluded_by="concurrent-reviewer",
                )
                assert excluded is not None
                assert excluded["deleted_candidates"] == 1
                assert excluded["deleted_places"] == 0
            resume_admin.set()
            with pytest.raises(geocode_service.CandidateStateChangedError):
                await asyncio.wait_for(task, timeout=10)
        finally:
            resume_admin.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async with session_factory() as check_session:
        current_candidate = await check_session.get(
            ExtractedPlaceCandidate, candidate_id
        )
        assert current_candidate is not None
        assert current_candidate.deleted_at is not None
        assert current_candidate.matched_place_id is None
        assert await check_session.get(TravelPlace, place_id) is not None
        candidate_mappings = (
            await check_session.execute(
                select(VideoPlaceMapping).where(
                    VideoPlaceMapping.place_candidate_id == candidate_id
                )
            )
        ).scalars().all()
        assert candidate_mappings == []


async def test_post_core_and_delete_place_keep_candidate_mapping_lock_order(
    session_factory,
    monkeypatch,
):
    """post-core와 장소 삭제가 candidate -> mapping 순서로 직렬화돼 deadlock이 없다."""
    async with session_factory() as seed_session:
        seed_session.add(
            YoutubeVideo(
                video_id="geocode-delete-place-lock-order",
                title="장소 삭제 경합",
                url="https://youtu.be/geocode-delete-place-lock-order",
                channel_id="UC_GEOCODE_DELETE_PLACE_LOCK_ORDER",
            )
        )
        await seed_session.commit()
        place = TravelPlace(
            name="월정리 카페",
            latitude=33.5563,
            longitude=126.7958,
            category="카페",
            category_code_suggestion="01010100",
            is_geocoded=True,
        )
        seed_session.add(place)
        await seed_session.flush()
        await sync_place_geometry(
            seed_session, place.place_id, place.latitude, place.longitude
        )
        candidate = ExtractedPlaceCandidate(
            video_id="geocode-delete-place-lock-order",
            source_text="월정리 카페를 방문했습니다.",
            ai_place_name="월정리 카페",
            candidate_category="카페",
            match_status=MatchStatus.NEEDS_REVIEW,
            source_kind=EvidenceSourceKind.TRANSCRIPT.value,
            grounding_status=GroundingStatus.VERIFIED_RAW.value,
            is_domestic=True,
        )
        seed_session.add(candidate)
        await seed_session.commit()
        place_id = place.place_id
        candidate_id = candidate.id

    admin_started = asyncio.Event()
    resume_admin = asyncio.Event()
    post_core_candidate_locked = asyncio.Event()
    resume_mapping_lock = asyncio.Event()
    original_candidate_lock = geocode_service._lock_current_candidate_for_geocode

    async def pause_admin(_factory, _place_id, **_kwargs):
        admin_started.set()
        await resume_admin.wait()
        return False

    async def pause_after_post_core_candidate_lock(session, locked_candidate_id):
        current, version = await original_candidate_lock(session, locked_candidate_id)
        if (
            current is not None
            and current.match_status == MatchStatus.MATCHED.value
            and not post_core_candidate_locked.is_set()
        ):
            post_core_candidate_locked.set()
            await resume_mapping_lock.wait()
        return current, version

    monkeypatch.setattr(
        admin_region_service,
        "enrich_place_admin_codes_isolated",
        pause_admin,
    )
    monkeypatch.setattr(
        geocode_service,
        "_lock_current_candidate_for_geocode",
        pause_after_post_core_candidate_lock,
    )

    delete_pid_ready = asyncio.Event()
    delete_pid: int | None = None

    async def delete_concurrently() -> list[int]:
        nonlocal delete_pid
        async with session_factory() as delete_session:
            delete_pid = int(
                (
                    await delete_session.execute(text("SELECT pg_backend_pid()"))
                ).scalar_one()
            )
            delete_pid_ready.set()
            reverted = await place_service.delete_place(
                delete_session, place_id=place_id
            )
            await delete_session.commit()
            return [item.id for item in reverted]

    async with session_factory() as worker_session:
        worker_candidate = await worker_session.get(
            ExtractedPlaceCandidate, candidate_id
        )
        assert worker_candidate is not None
        worker_task = asyncio.create_task(
            apply_geocode_to_current_candidate(
                worker_session,
                worker_candidate,
                _matched_decision("월정리 카페"),
            )
        )
        delete_task: asyncio.Task[list[int]] | None = None
        try:
            await asyncio.wait_for(admin_started.wait(), timeout=10)
            resume_admin.set()
            await asyncio.wait_for(post_core_candidate_locked.wait(), timeout=10)

            delete_task = asyncio.create_task(delete_concurrently())
            await asyncio.wait_for(delete_pid_ready.wait(), timeout=10)
            assert delete_pid is not None

            # 삭제 transaction이 worker의 candidate lock에서 실제로 대기할 때까지
            # 확인한다. 수정 전 순서라면 이 시점에 mapping DELETE lock까지 쥔 상태라,
            # 아래 worker 재개가 candidate <-> mapping deadlock을 만든다.
            delete_is_waiting = False
            async with session_factory() as monitor_session:
                for _ in range(200):
                    wait_event_type = (
                        await monitor_session.execute(
                            text(
                                "SELECT wait_event_type FROM pg_stat_activity "
                                "WHERE pid = :pid"
                            ),
                            {"pid": delete_pid},
                        )
                    ).scalar_one_or_none()
                    await monitor_session.commit()
                    if wait_event_type == "Lock":
                        delete_is_waiting = True
                        break
                    await asyncio.sleep(0.01)
            assert delete_is_waiting is True

            resume_mapping_lock.set()
            matched, reverted_ids = await asyncio.wait_for(
                asyncio.gather(worker_task, delete_task),
                timeout=10,
            )
        finally:
            resume_admin.set()
            resume_mapping_lock.set()
            pending = [worker_task]
            if delete_task is not None:
                pending.append(delete_task)
            for task in pending:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    assert matched is not None
    assert matched.place_id == place_id
    assert reverted_ids == [candidate_id]
    async with session_factory() as check_session:
        current_candidate = await check_session.get(
            ExtractedPlaceCandidate, candidate_id
        )
        assert current_candidate is not None
        assert current_candidate.match_status == MatchStatus.NEEDS_REVIEW.value
        assert current_candidate.matched_place_id is None
        assert await check_session.get(TravelPlace, place_id) is None
        mappings = (
            await check_session.execute(
                select(VideoPlaceMapping).where(
                    VideoPlaceMapping.place_candidate_id == candidate_id
                )
            )
        ).scalars().all()
        assert mappings == []


async def test_post_core_and_merge_places_keep_candidate_mapping_lock_order(
    session_factory,
    monkeypatch,
):
    """post-core와 장소 병합이 candidate -> place -> mapping 순서로 직렬화된다."""
    async with session_factory() as seed_session:
        seed_session.add(
            YoutubeVideo(
                video_id="geocode-merge-place-lock-order",
                title="장소 병합 경합",
                url="https://youtu.be/geocode-merge-place-lock-order",
                channel_id="UC_GEOCODE_MERGE_PLACE_LOCK_ORDER",
            )
        )
        await seed_session.commit()
        source_place = TravelPlace(
            name="월정리 카페",
            latitude=33.5563,
            longitude=126.7958,
            category="카페",
            category_code_suggestion="01010100",
            is_geocoded=True,
        )
        target_place = TravelPlace(
            name="월정리 카페 통합본",
            latitude=37.5665,
            longitude=126.978,
            category="카페",
            category_code_suggestion="01010100",
            is_geocoded=True,
        )
        seed_session.add_all([source_place, target_place])
        await seed_session.flush()
        await sync_place_geometry(
            seed_session,
            source_place.place_id,
            source_place.latitude,
            source_place.longitude,
        )
        await sync_place_geometry(
            seed_session,
            target_place.place_id,
            target_place.latitude,
            target_place.longitude,
        )
        candidate = ExtractedPlaceCandidate(
            video_id="geocode-merge-place-lock-order",
            source_text="월정리 카페를 방문했습니다.",
            ai_place_name="월정리 카페",
            candidate_category="카페",
            match_status=MatchStatus.NEEDS_REVIEW,
            source_kind=EvidenceSourceKind.TRANSCRIPT.value,
            grounding_status=GroundingStatus.VERIFIED_RAW.value,
            is_domestic=True,
        )
        seed_session.add(candidate)
        await seed_session.commit()
        source_place_id = source_place.place_id
        target_place_id = target_place.place_id
        candidate_id = candidate.id

    admin_started = asyncio.Event()
    resume_admin = asyncio.Event()
    post_core_candidate_locked = asyncio.Event()
    resume_mapping_lock = asyncio.Event()
    original_candidate_lock = geocode_service._lock_current_candidate_for_geocode

    async def pause_admin(_factory, _place_id, **_kwargs):
        admin_started.set()
        await resume_admin.wait()
        return False

    async def pause_after_post_core_candidate_lock(session, locked_candidate_id):
        current, version = await original_candidate_lock(session, locked_candidate_id)
        if (
            current is not None
            and current.match_status == MatchStatus.MATCHED.value
            and not post_core_candidate_locked.is_set()
        ):
            post_core_candidate_locked.set()
            await resume_mapping_lock.wait()
        return current, version

    monkeypatch.setattr(
        admin_region_service,
        "enrich_place_admin_codes_isolated",
        pause_admin,
    )
    monkeypatch.setattr(
        geocode_service,
        "_lock_current_candidate_for_geocode",
        pause_after_post_core_candidate_lock,
    )

    merge_pid_ready = asyncio.Event()
    merge_pid: int | None = None

    async def merge_concurrently() -> int:
        nonlocal merge_pid
        async with session_factory() as merge_session:
            merge_pid = int(
                (
                    await merge_session.execute(text("SELECT pg_backend_pid()"))
                ).scalar_one()
            )
            await merge_session.commit()
            merge_pid_ready.set()
            merged = await place_service.merge_places(
                merge_session,
                source_place_id=source_place_id,
                target_place_id=target_place_id,
            )
            return merged.place_id

    async with session_factory() as worker_session:
        worker_candidate = await worker_session.get(
            ExtractedPlaceCandidate, candidate_id
        )
        assert worker_candidate is not None
        worker_task = asyncio.create_task(
            apply_geocode_to_current_candidate(
                worker_session,
                worker_candidate,
                _matched_decision("월정리 카페"),
            )
        )
        merge_task: asyncio.Task[int] | None = None
        try:
            await asyncio.wait_for(admin_started.wait(), timeout=10)
            resume_admin.set()
            await asyncio.wait_for(post_core_candidate_locked.wait(), timeout=10)

            merge_task = asyncio.create_task(merge_concurrently())
            await asyncio.wait_for(merge_pid_ready.wait(), timeout=10)
            assert merge_pid is not None

            # 병합이 post-core candidate lock에서 대기해야 한다. 과거 mapping 우선
            # 순서라면 mapping UPDATE lock을 이미 쥐고 대기해 worker 재개 시 deadlock이다.
            merge_is_waiting = False
            async with session_factory() as monitor_session:
                for _ in range(200):
                    wait_event_type = (
                        await monitor_session.execute(
                            text(
                                "SELECT wait_event_type FROM pg_stat_activity "
                                "WHERE pid = :pid"
                            ),
                            {"pid": merge_pid},
                        )
                    ).scalar_one_or_none()
                    await monitor_session.commit()
                    if wait_event_type == "Lock":
                        merge_is_waiting = True
                        break
                    await asyncio.sleep(0.01)
            assert merge_is_waiting is True

            resume_mapping_lock.set()
            matched, merged_place_id = await asyncio.wait_for(
                asyncio.gather(worker_task, merge_task),
                timeout=10,
            )
        finally:
            resume_admin.set()
            resume_mapping_lock.set()
            pending = [worker_task]
            if merge_task is not None:
                pending.append(merge_task)
            for task in pending:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    assert matched is not None
    assert matched.place_id == source_place_id
    assert merged_place_id == target_place_id
    async with session_factory() as check_session:
        current_candidate = await check_session.get(
            ExtractedPlaceCandidate, candidate_id
        )
        assert current_candidate is not None
        assert current_candidate.match_status == MatchStatus.MATCHED.value
        assert current_candidate.matched_place_id == target_place_id
        assert await check_session.get(TravelPlace, source_place_id) is None
        assert await check_session.get(TravelPlace, target_place_id) is not None
        mappings = (
            await check_session.execute(
                select(VideoPlaceMapping).where(
                    VideoPlaceMapping.place_candidate_id == candidate_id
                )
            )
        ).scalars().all()
        assert len(mappings) == 1
        assert mappings[0].place_id == target_place_id
