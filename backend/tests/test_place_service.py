"""place_service 근접 탐색/중복 후보/검수 큐 테스트."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from ktc.etl import admin_region_service
from ktc.models import (
    ExtractedPlaceCandidate,
    FeatureExport,
    FeatureExportStatus,
    MatchStatus,
    MediaAsset,
    TravelPlace,
    VideoPlaceMapping,
    YoutubeVideo,
    utcnow,
)
from ktc.services import place_service as svc


def test_haversine_known_distance():
    # 서울시청(37.5663,126.9779) ~ 부산시청(35.1797,129.0750) 약 325km
    d = svc.haversine_meters(37.5663, 126.9779, 35.1797, 129.0750)
    assert 320_000 < d < 330_000


async def _add_place(session, name, lat, lng, geocoded=True):
    p = TravelPlace(name=name, latitude=lat, longitude=lng, is_geocoded=geocoded)
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return p


async def test_correct_place_runs_admin_after_core_commit(session, monkeypatch):
    place = await _add_place(session, "보정 전", 35.1587, 129.1604)
    observed: list[int] = []

    async def fake_isolated(_factory, place_id, **_kwargs):
        assert session.in_transaction() is False
        observed.append(place_id)
        return False

    monkeypatch.setattr(
        admin_region_service,
        "enrich_place_admin_codes_isolated",
        fake_isolated,
    )

    corrected = await svc.correct_place(
        session,
        place_id=place.place_id,
        updates={"latitude": 35.159, "longitude": 129.161},
    )

    assert corrected.latitude == 35.159
    assert corrected.longitude == 129.161
    assert observed == [place.place_id]


async def test_find_within_radius_filters_and_sorts(session):
    # 해운대 기준 근처/먼 장소 배치
    await _add_place(session, "해운대", 35.1587, 129.1604)
    await _add_place(session, "광안리", 35.1532, 129.1186)  # 약 4km
    await _add_place(session, "서울", 37.5663, 126.9779)  # 약 325km

    results = await svc.find_places_within_radius(
        session, lat=35.1587, lng=129.1604, radius_meters=5000
    )
    names = [p.name for p, _ in results]
    assert "해운대" in names
    assert "광안리" in names
    assert "서울" not in names
    # 거리 오름차순: 가장 가까운 해운대가 먼저
    assert results[0][0].name == "해운대"
    assert results[0][1] < results[1][1]


async def test_excludes_non_geocoded(session):
    await _add_place(session, "미지오코딩", 35.1587, 129.1604, geocoded=False)
    results = await svc.find_places_within_radius(
        session, lat=35.1587, lng=129.1604, radius_meters=1000
    )
    assert results == []


async def test_find_duplicate_candidates(session):
    await _add_place(session, "기존장소", 35.1587, 129.1604)
    # 약 20m 떨어진 신규 좌표 -> 중복 의심
    dups = await svc.find_duplicate_candidates(
        session, lat=35.15888, lng=129.1604, radius_meters=100
    )
    assert len(dups) == 1
    assert dups[0][0].name == "기존장소"


async def test_list_unmatched_candidates(session):
    v = YoutubeVideo(video_id="v1", title="t", url="u", channel_id="c")
    session.add(v)
    await session.commit()
    session.add_all(
        [
            ExtractedPlaceCandidate(
                video_id="v1", source_text="s", ai_place_name="검수대상",
                match_status=MatchStatus.NEEDS_REVIEW,
            ),
            ExtractedPlaceCandidate(
                video_id="v1", source_text="s", ai_place_name="이미매칭",
                match_status=MatchStatus.MATCHED,
            ),
        ]
    )
    await session.commit()

    unmatched = await svc.list_unmatched_candidates(session)
    assert len(unmatched) == 1
    assert unmatched[0].ai_place_name == "검수대상"


async def test_resolve_create_place_copies_category_code_from_candidate(session):
    # A안: 카테고리 코드는 POI 추출 때 후보 evidence에 저장된 값을 복사한다(Gemini 호출 X).
    session.add(YoutubeVideo(video_id="v1", title="t", url="u", channel_id="c"))
    await session.commit()
    candidate = ExtractedPlaceCandidate(
        video_id="v1", source_text="s", ai_place_name="월정리 해변",
        match_status=MatchStatus.NEEDS_REVIEW,
        provider_evidence_json={"transcript": {"category_code": "01050100"}},
    )
    session.add(candidate)
    await session.commit()
    await session.refresh(candidate)

    _, place, _ = await svc.resolve_candidate(
        session,
        candidate_id=candidate.id,
        action="create_place",
        reviewed_by="web",
        place_data={
            "name": "월정리 해변",
            "latitude": 33.5563,
            "longitude": 126.7958,
            "category": "해변",
        },
    )
    assert place is not None
    assert place.category_code_suggestion == "01050100"


async def test_resolve_create_place_runs_admin_after_candidate_lock_commit(
    session,
    monkeypatch,
):
    session.add(
        YoutubeVideo(
            video_id="resolve-postcommit",
            title="t",
            url="u",
            channel_id="c",
        )
    )
    await session.commit()
    candidate = ExtractedPlaceCandidate(
        video_id="resolve-postcommit",
        source_text="s",
        ai_place_name="월정리 카페",
        match_status=MatchStatus.NEEDS_REVIEW,
    )
    session.add(candidate)
    await session.commit()
    await session.refresh(candidate)
    observed: list[int] = []

    async def fake_isolated(_factory, place_id, **_kwargs):
        assert session.in_transaction() is False
        observed.append(place_id)
        return False

    monkeypatch.setattr(
        admin_region_service,
        "enrich_place_admin_codes_isolated",
        fake_isolated,
    )

    _, place, _ = await svc.resolve_candidate(
        session,
        candidate_id=candidate.id,
        action="create_place",
        reviewed_by="web",
        place_data={
            "name": "월정리 카페",
            "latitude": 33.5563,
            "longitude": 126.7958,
        },
    )

    assert place is not None
    assert observed == [place.place_id]


async def test_resolve_rejects_stale_identity_map_candidate_with_typed_conflict(
    session_factory,
):
    async with session_factory() as seed_session:
        seed_session.add(
            YoutubeVideo(
                video_id="resolve-stale-conflict",
                title="t",
                url="u",
                channel_id="c",
            )
        )
        await seed_session.commit()
        candidate = ExtractedPlaceCandidate(
            video_id="resolve-stale-conflict",
            source_text="s",
            ai_place_name="동시 검수 후보",
            match_status=MatchStatus.NEEDS_REVIEW,
        )
        seed_session.add(candidate)
        await seed_session.commit()
        candidate_id = candidate.id

    async with session_factory() as stale_session:
        stale_candidate = await stale_session.get(
            ExtractedPlaceCandidate, candidate_id
        )
        assert stale_candidate is not None
        await stale_session.commit()

        async with session_factory() as current_session:
            await svc.resolve_candidate(
                current_session,
                candidate_id=candidate_id,
                action="ignore",
                reviewed_by="first-reviewer",
            )

        # expire_on_commit=False 세션에 needs_review 객체가 남아 있어도 FOR UPDATE
        # 재조회가 DB의 ignored 상태를 강제로 적재해 typed 409 계약으로 거부한다.
        with pytest.raises(svc.CandidateResolveConflictError):
            await svc.resolve_candidate(
                stale_session,
                candidate_id=candidate_id,
                action="ignore",
                reviewed_by="stale-reviewer",
            )
        await stale_session.rollback()


async def test_review_waits_for_resolve_lock_and_rejects_latest_status(
    session_factory,
):
    """동시 resolve가 선점한 후보를 review가 기다린 뒤 stale 메타데이터로 덮지 않는다."""
    async with session_factory() as seed_session:
        seed_session.add(
            YoutubeVideo(
                video_id="review-resolve-lock",
                title="동시 검수",
                url="u",
                channel_id="review-resolve-channel",
            )
        )
        await seed_session.commit()
        candidate = ExtractedPlaceCandidate(
            video_id="review-resolve-lock",
            source_text="s",
            ai_place_name="동시 검수 후보",
            match_status=MatchStatus.NEEDS_REVIEW,
        )
        seed_session.add(candidate)
        await seed_session.commit()
        candidate_id = candidate.id

    review_preloaded = asyncio.Event()
    resume_review = asyncio.Event()
    review_started = asyncio.Event()
    review_pid: list[int] = []

    async def review_concurrently():
        async with session_factory() as review_session:
            stale_candidate = await review_session.get(
                ExtractedPlaceCandidate, candidate_id
            )
            assert stale_candidate is not None
            assert stale_candidate.match_status == MatchStatus.NEEDS_REVIEW.value
            # expire_on_commit=False identity map에 needs_review 객체를 남긴다.
            await review_session.commit()
            review_preloaded.set()
            await resume_review.wait()
            review_pid.append(
                int(await review_session.scalar(text("SELECT pg_backend_pid()")))
            )
            review_started.set()
            return await svc.review_candidate(
                review_session,
                candidate_id=candidate_id,
                reviewed_by="stale-reviewer",
                review_note="이미 끝난 후보를 뒤늦게 검수",
            )

    review_task = asyncio.create_task(review_concurrently())
    try:
        await asyncio.wait_for(review_preloaded.wait(), timeout=10)
        async with session_factory() as resolve_session:
            await svc.resolve_candidate(
                resolve_session,
                candidate_id=candidate_id,
                action="ignore",
                reviewed_by="first-reviewer",
                review_note="먼저 제외",
                commit=False,
            )
            resume_review.set()
            try:
                await asyncio.wait_for(review_started.wait(), timeout=10)
                review_is_waiting = False
                async with session_factory() as monitor_session:
                    for _ in range(1000):
                        wait_event_type = await monitor_session.scalar(
                            text(
                                "SELECT wait_event_type FROM pg_stat_activity "
                                "WHERE pid = :pid"
                            ),
                            {"pid": review_pid[0]},
                        )
                        await monitor_session.commit()
                        if wait_event_type == "Lock":
                            review_is_waiting = True
                            break
                        await asyncio.sleep(0.01)
                assert review_is_waiting is True
            finally:
                # resolve의 status/reviewer를 DB에 반영하고 대기 중 review를 깨운다.
                await resolve_session.commit()

        with pytest.raises(svc.CandidateResolveConflictError):
            await asyncio.wait_for(review_task, timeout=10)
    finally:
        resume_review.set()
        if not review_task.done():
            review_task.cancel()
        await asyncio.gather(review_task, return_exceptions=True)

    async with session_factory() as check_session:
        current = await check_session.get(ExtractedPlaceCandidate, candidate_id)
        assert current is not None
        assert current.match_status == MatchStatus.IGNORED.value
        assert current.reviewed_by == "first-reviewer"
        assert current.review_note == "먼저 제외"


async def test_resolve_normalizes_all_legacy_duplicate_candidate_mappings(session):
    """unique 제약 없는 legacy mapping 전부를 candidate의 최신 연결로 맞춘다."""
    session.add_all(
        [
            YoutubeVideo(
                video_id="resolve-legacy-mapping",
                title="정본 영상",
                url="u1",
                channel_id="c-resolve-legacy-mapping",
            ),
            YoutubeVideo(
                video_id="resolve-legacy-mapping-stale",
                title="legacy 오연결 영상",
                url="u2",
                channel_id="c-resolve-legacy-mapping-stale",
            ),
        ]
    )
    old_place = TravelPlace(
        name="이전 장소", latitude=35.0, longitude=129.0, is_geocoded=True
    )
    target_place = TravelPlace(
        name="최종 장소", latitude=35.1, longitude=129.1, is_geocoded=True
    )
    session.add_all([old_place, target_place])
    await session.flush()
    candidate = ExtractedPlaceCandidate(
        video_id="resolve-legacy-mapping",
        source_text="최종 장소를 방문했습니다.",
        ai_place_name="최종 장소",
        match_status=MatchStatus.NEEDS_REVIEW,
    )
    session.add(candidate)
    await session.flush()
    session.add_all(
        [
            VideoPlaceMapping(
                video_id="resolve-legacy-mapping",
                place_id=old_place.place_id,
                place_candidate_id=candidate.id,
                ai_summary="legacy 중복 1",
            ),
            VideoPlaceMapping(
                video_id="resolve-legacy-mapping-stale",
                place_id=old_place.place_id,
                place_candidate_id=candidate.id,
                ai_summary="legacy 중복 2",
            ),
        ]
    )
    await session.commit()

    resolved, place, returned_mapping = await svc.resolve_candidate(
        session,
        candidate_id=candidate.id,
        action="match_existing",
        reviewed_by="web",
        place_id=target_place.place_id,
    )

    assert place is not None
    assert returned_mapping is not None
    assert resolved.matched_place_id == target_place.place_id
    mappings = (
        (
            await session.execute(
                select(VideoPlaceMapping)
                .where(VideoPlaceMapping.place_candidate_id == candidate.id)
                .order_by(VideoPlaceMapping.id.asc())
            )
        )
        .scalars()
        .all()
    )
    assert len(mappings) == 2
    assert returned_mapping.id == mappings[-1].id
    assert {mapping.video_id for mapping in mappings} == {candidate.video_id}
    assert {mapping.place_id for mapping in mappings} == {target_place.place_id}
    assert all(
        mapping.feature_export_status == FeatureExportStatus.READY.value
        for mapping in mappings
    )
    assert all(
        mapping.provider_evidence_json == resolved.provider_evidence_json
        for mapping in mappings
    )


async def test_resolve_create_place_without_evidence_code_uses_unknown(session):
    session.add(YoutubeVideo(video_id="v2", title="t", url="u", channel_id="c"))
    await session.commit()
    candidate = ExtractedPlaceCandidate(
        video_id="v2", source_text="s", ai_place_name="장소",
        match_status=MatchStatus.NEEDS_REVIEW,
    )
    session.add(candidate)
    await session.commit()
    await session.refresh(candidate)

    _, place, _ = await svc.resolve_candidate(
        session,
        candidate_id=candidate.id,
        action="create_place",
        reviewed_by="web",
        place_data={"name": "장소", "latitude": 33.5, "longitude": 126.7},
    )
    assert place is not None
    assert place.category_code_suggestion == "0"
    assert place.category == "unknown"


async def test_resolve_preserves_evidence_and_copies_versioned_resolution_to_mapping(
    session,
):
    session.add(YoutubeVideo(video_id="v-provenance", title="t", url="u", channel_id="c"))
    await session.commit()
    candidate = ExtractedPlaceCandidate(
        video_id="v-provenance",
        source_text="원본 자막",
        ai_place_name="AI 원본 이름",
        match_status=MatchStatus.NEEDS_REVIEW,
        provider_evidence_json={
            "transcript": {"category_code": "01050100", "segment": "원본"},
            "vision": {"frame_key": "frames/original.jpg"},
        },
    )
    session.add(candidate)
    await session.commit()
    await session.refresh(candidate)

    selected_hit = {
        "provider": "kakao",
        "native_id": "kakao-place-123",
        "query": "월정리 해변",
        "searched_at": "2026-07-13T01:00:00+00:00",
        "selected_at": "2026-07-13T01:00:03+00:00",
        "name": "월정리해수욕장",
        "address": "제주 구좌읍 월정리 1",
        "road_address": "제주 구좌읍 해맞이해안로 480-1",
        "latitude": 33.5563,
        "longitude": 126.7958,
        "category": "여행 > 해수욕장",
    }
    resolved, place, mapping = await svc.resolve_candidate(
        session,
        candidate_id=candidate.id,
        action="create_place",
        reviewed_by="reviewer@example.com",
        review_note="공식 이름으로 보정",
        place_data={
            "name": "월정리 해변",
            "official_address": "제주특별자치도 제주시 구좌읍 월정리 1",
            "road_address": "제주특별자치도 제주시 구좌읍 해맞이해안로 480-1",
            "latitude": 33.55631,
            "longitude": 126.79581,
            "api_source": "kakao",
        },
        resolution_evidence=selected_hit,
    )

    assert place is not None and mapping is not None
    assert resolved.provider_evidence_json["transcript"] == {
        "category_code": "01050100",
        "segment": "원본",
    }
    assert resolved.provider_evidence_json["vision"] == {
        "frame_key": "frames/original.jpg"
    }
    resolution = svc.latest_candidate_resolution(resolved)
    assert resolution is not None
    assert resolution["schema_version"] == 1
    assert resolution["reviewer"] == {
        "actor_type": "internal",
        "actor_id": "reviewer@example.com",
    }
    assert resolution["selection"]["provider"] == "kakao"
    assert resolution["selection"]["native_id"] == "kakao-place-123"
    assert resolution["selection"]["original"] == {
        "name": "월정리해수욕장",
        "official_address": "제주 구좌읍 월정리 1",
        "road_address": "제주 구좌읍 해맞이해안로 480-1",
        "latitude": 33.5563,
        "longitude": 126.7958,
        "category": "여행 > 해수욕장",
    }
    assert resolution["final"]["name"] == "월정리 해변"
    assert resolution["final"]["official_address"].startswith("제주특별자치도")
    assert resolution["final"]["latitude"] == 33.55631
    assert resolution["final"]["api_source"] == "kakao"
    assert resolution["selection"]["original"]["name"] != resolution["final"]["name"]
    assert mapping.provider_evidence_json == resolved.provider_evidence_json


async def test_resolve_google_selection_is_rejected_without_mutation(session):
    session.add(YoutubeVideo(video_id="v-google-block", title="t", url="u", channel_id="c"))
    await session.commit()
    original_evidence = {"transcript": {"segment": "보존"}}
    candidate = ExtractedPlaceCandidate(
        video_id="v-google-block",
        source_text="s",
        ai_place_name="저장 금지",
        match_status=MatchStatus.NEEDS_REVIEW,
        provider_evidence_json=original_evidence,
    )
    session.add(candidate)
    await session.commit()
    await session.refresh(candidate)

    with pytest.raises(svc.ProviderPersistenceDisabled):
        await svc.resolve_candidate(
            session,
            candidate_id=candidate.id,
            action="create_place",
            reviewed_by="web",
            place_data={
                "name": "저장 금지",
                "latitude": 37.0,
                "longitude": 127.0,
                "api_source": "google",
            },
            resolution_evidence={
                "provider": "google",
                "native_id": "google-place-id",
                "query": "저장 금지",
            },
        )

    await session.refresh(candidate)
    assert candidate.match_status == MatchStatus.NEEDS_REVIEW
    assert candidate.matched_place_id is None
    assert candidate.reviewed_at is None
    assert candidate.provider_evidence_json == original_evidence
    assert (await session.execute(select(TravelPlace))).scalars().all() == []


async def test_nearby_place_requires_confirmation_then_supports_both_decisions(session):
    existing = await _add_place(session, "기존 관광지", 35.1587, 129.1604)
    session.add_all(
        [
            YoutubeVideo(video_id="v-near-merge", title="t", url="u", channel_id="c"),
            YoutubeVideo(video_id="v-near-create", title="t", url="u", channel_id="c"),
        ]
    )
    await session.commit()
    merge_candidate = ExtractedPlaceCandidate(
        video_id="v-near-merge",
        source_text="s",
        ai_place_name="유사 관광지",
        match_status=MatchStatus.NEEDS_REVIEW,
    )
    create_candidate = ExtractedPlaceCandidate(
        video_id="v-near-create",
        source_text="s",
        ai_place_name="독립 관광지",
        match_status=MatchStatus.NEEDS_REVIEW,
    )
    session.add_all([merge_candidate, create_candidate])
    await session.commit()
    await session.refresh(merge_candidate)
    await session.refresh(create_candidate)
    place_data = {
        "name": "새 관광지",
        "latitude": 35.1588,
        "longitude": 129.1604,
    }

    with pytest.raises(svc.NearbyPlaceConfirmationRequired) as exc_info:
        await svc.resolve_candidate(
            session,
            candidate_id=merge_candidate.id,
            action="create_place",
            reviewed_by="web",
            place_data=place_data,
        )
    assert exc_info.value.nearby_places[0]["place_id"] == existing.place_id
    assert exc_info.value.nearby_places[0]["distance_m"] < 100
    assert exc_info.value.nearby_places[0]["name_compatible"] is False
    await session.refresh(merge_candidate)
    assert merge_candidate.match_status == MatchStatus.NEEDS_REVIEW

    _, merged_place, _ = await svc.resolve_candidate(
        session,
        candidate_id=merge_candidate.id,
        action="create_place",
        reviewed_by="web",
        place_data=place_data,
        duplicate_resolution="merge_existing",
        duplicate_place_id=existing.place_id,
    )
    assert merged_place is not None
    assert merged_place.place_id == existing.place_id

    _, created_place, _ = await svc.resolve_candidate(
        session,
        candidate_id=create_candidate.id,
        action="create_place",
        reviewed_by="web",
        place_data={**place_data, "name": "독립 관광지"},
        duplicate_resolution="create_new",
    )
    assert created_place is not None
    assert created_place.place_id != existing.place_id
    places = (await session.execute(select(TravelPlace))).scalars().all()
    assert {place.place_id for place in places} == {
        existing.place_id,
        created_place.place_id,
    }


async def test_nearby_place_auto_merges_only_with_exact_identity_gate(session):
    existing = await _add_place(session, "감천문화마을", 35.09739, 129.01059)
    session.add_all(
        [
            YoutubeVideo(video_id="v-identity-old", title="t", url="u", channel_id="c"),
            YoutubeVideo(video_id="v-identity-new", title="t", url="u", channel_id="c"),
        ]
    )
    await session.commit()
    previous = ExtractedPlaceCandidate(
        video_id="v-identity-old",
        source_text="s",
        ai_place_name="감천문화마을",
        match_status=MatchStatus.USER_CORRECTED,
        matched_place_id=existing.place_id,
        provider_evidence_json={
            "review": {
                "schema_version": 1,
                "resolutions": [
                    {
                        "selection": {
                            "provider": "kakao",
                            "native_id": "kakao-gamcheon-123",
                        },
                        "final": {"place_id": existing.place_id},
                    }
                ],
            }
        },
    )
    incoming = ExtractedPlaceCandidate(
        video_id="v-identity-new",
        source_text="s",
        ai_place_name="감천문화마을",
        match_status=MatchStatus.NEEDS_REVIEW,
    )
    session.add_all([previous, incoming])
    await session.commit()
    await session.refresh(incoming)

    resolved, place, _ = await svc.resolve_candidate(
        session,
        candidate_id=incoming.id,
        action="create_place",
        reviewed_by="web",
        place_data={
            "name": "감천문화마을",
            "latitude": 35.0974,
            "longitude": 129.01059,
            "api_source": "kakao",
        },
        resolution_evidence={
            "provider": "kakao",
            "native_id": "kakao-gamcheon-123",
            "query": "감천문화마을",
        },
    )

    assert place is not None
    assert place.place_id == existing.place_id
    resolution = svc.latest_candidate_resolution(resolved)
    assert resolution is not None
    assert resolution["nearby"]["decision"] == "merge_existing"
    assert resolution["nearby"]["candidate_place_ids"] == [existing.place_id]


async def test_concurrent_create_place_requests_cannot_both_create_nearby_places(
    session_factory,
):
    async with session_factory() as session:
        session.add_all(
            [
                YoutubeVideo(video_id="v-concurrent-1", title="t", url="u", channel_id="c"),
                YoutubeVideo(video_id="v-concurrent-2", title="t", url="u", channel_id="c"),
            ]
        )
        await session.commit()
        candidates = [
            ExtractedPlaceCandidate(
                video_id=f"v-concurrent-{index}",
                source_text="s",
                ai_place_name=f"동시 장소 {index}",
                match_status=MatchStatus.NEEDS_REVIEW,
            )
            for index in (1, 2)
        ]
        session.add_all(candidates)
        await session.commit()
        candidate_ids = [candidate.id for candidate in candidates]

    async def resolve(candidate_id: int, name: str):
        async with session_factory() as session:
            return await svc.resolve_candidate(
                session,
                candidate_id=candidate_id,
                action="create_place",
                reviewed_by="web",
                place_data={
                    "name": name,
                    "latitude": 35.1588,
                    "longitude": 129.1604,
                },
            )

    results = await asyncio.gather(
        resolve(candidate_ids[0], "동시 장소 1"),
        resolve(candidate_ids[1], "동시 장소 2"),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(
        isinstance(result, svc.NearbyPlaceConfirmationRequired) for result in results
    ) == 1
    async with session_factory() as session:
        places = (await session.execute(select(TravelPlace))).scalars().all()
        assert len(places) == 1


async def test_delete_place_reverts_candidate_unlinks_media_removes_mapping(session):
    session.add(YoutubeVideo(video_id="vdel", title="t", url="u", channel_id="c"))
    await session.commit()
    candidate = ExtractedPlaceCandidate(
        video_id="vdel",
        source_text="s",
        ai_place_name="삭제 대상",
        match_status=MatchStatus.NEEDS_REVIEW,
    )
    session.add(candidate)
    await session.commit()
    await session.refresh(candidate)

    _, place, mapping = await svc.resolve_candidate(
        session,
        candidate_id=candidate.id,
        action="create_place",
        reviewed_by="web",
        place_data={"name": "삭제 대상", "latitude": 35.0, "longitude": 129.0},
    )
    assert place is not None and mapping is not None
    place_id = place.place_id
    asset = MediaAsset(
        place_id=place_id,
        video_id="vdel",
        asset_type="frame",
        bucket="b",
        object_key="k",
        object_uri="u",
    )
    session.add(asset)
    await session.commit()
    await session.refresh(candidate)
    assert candidate.matched_place_id == place_id

    reverted = await svc.delete_place(session, place_id=place_id)
    await session.commit()

    # 장소·매핑은 사라지고, 후보는 검수 큐로, 미디어는 링크만 해제(보존)된다.
    assert await session.get(TravelPlace, place_id) is None
    remaining = (
        (
            await session.execute(
                select(VideoPlaceMapping).where(
                    VideoPlaceMapping.place_id == place_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert remaining == []
    await session.refresh(candidate)
    assert candidate.matched_place_id is None
    assert candidate.match_status == MatchStatus.NEEDS_REVIEW
    assert candidate.id in [c.id for c in reverted]
    unmatched = await svc.list_unmatched_candidates(session)
    assert candidate.id in [c.id for c in unmatched]
    await session.refresh(asset)
    assert asset.place_id is None


async def test_delete_place_missing_raises(session):
    with pytest.raises(ValueError):
        await svc.delete_place(session, place_id=999_999)


async def test_delete_place_and_merge_serialize_candidate_less_legacy_refs(
    session_factory,
    monkeypatch,
):
    """후보 없는 legacy 장소도 lifecycle 경계에서 mapping/asset 교착을 막는다."""
    async with session_factory() as seed_session:
        video = YoutubeVideo(
            video_id="v-delete-merge-legacy",
            title="후보 없는 legacy 장소",
            url="u",
            channel_id="c-delete-merge-legacy",
        )
        source = TravelPlace(
            name="legacy 원본",
            latitude=35.0,
            longitude=129.0,
            is_geocoded=True,
        )
        target = TravelPlace(
            name="legacy 통합본",
            latitude=35.1,
            longitude=129.1,
            is_geocoded=True,
        )
        seed_session.add_all([video, source, target])
        await seed_session.flush()
        mapping = VideoPlaceMapping(
            video_id=video.video_id,
            place_id=source.place_id,
            place_candidate_id=None,
            ai_summary="candidate FK가 없는 legacy mapping",
        )
        asset = MediaAsset(
            video_id=video.video_id,
            place_id=source.place_id,
            asset_type="frame",
            bucket="b",
            object_key="legacy-lock-order",
            object_uri="u",
        )
        seed_session.add_all([mapping, asset])
        await seed_session.commit()
        source_place_id = source.place_id
        target_place_id = target.place_id
        mapping_id = mapping.id
        asset_id = asset.id

    merge_has_place_locks = asyncio.Event()
    resume_merge_mapping_lock = asyncio.Event()
    delete_pid_ready = asyncio.Event()
    delete_pid: int | None = None

    async def merge_concurrently() -> int:
        async with session_factory() as merge_session:
            original_execute = merge_session.execute
            paused = False

            async def pause_before_mapping_lock(statement, *args, **kwargs):
                nonlocal paused
                descriptions = getattr(statement, "column_descriptions", ())
                selects_mapping = any(
                    description.get("entity") is VideoPlaceMapping
                    for description in descriptions
                )
                if selects_mapping and not paused:
                    paused = True
                    merge_has_place_locks.set()
                    await resume_merge_mapping_lock.wait()
                return await original_execute(statement, *args, **kwargs)

            monkeypatch.setattr(merge_session, "execute", pause_before_mapping_lock)
            merged = await svc.merge_places(
                merge_session,
                source_place_id=source_place_id,
                target_place_id=target_place_id,
            )
            return merged.place_id

    async def delete_concurrently() -> str:
        nonlocal delete_pid
        async with session_factory() as delete_session:
            delete_pid = int(
                (
                    await delete_session.execute(text("SELECT pg_backend_pid()"))
                ).scalar_one()
            )
            await delete_session.commit()
            delete_pid_ready.set()
            try:
                await svc.delete_place(delete_session, place_id=source_place_id)
                await delete_session.commit()
            except ValueError:
                await delete_session.rollback()
                return "not_found"
            return "deleted"

    merge_task = asyncio.create_task(merge_concurrently())
    delete_task: asyncio.Task[str] | None = None
    try:
        await asyncio.wait_for(merge_has_place_locks.wait(), timeout=10)
        delete_task = asyncio.create_task(delete_concurrently())
        await asyncio.wait_for(delete_pid_ready.wait(), timeout=10)
        assert delete_pid is not None

        # 새 순서에서는 delete가 mapping/asset을 건드리기 전에 merge의 lifecycle
        # 임계구간에서 대기한다. 구 순서는 asset+mapping을 먼저 잡고 place를 기다려,
        # merge 재개 시 place <-> mapping/asset 교착을 만들었다.
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

        resume_merge_mapping_lock.set()
        merged_place_id, delete_outcome = await asyncio.wait_for(
            asyncio.gather(merge_task, delete_task),
            timeout=10,
        )
    finally:
        resume_merge_mapping_lock.set()
        pending = [merge_task]
        if delete_task is not None:
            pending.append(delete_task)
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    assert merged_place_id == target_place_id
    assert delete_outcome == "not_found"
    async with session_factory() as check_session:
        assert await check_session.get(TravelPlace, source_place_id) is None
        current_mapping = await check_session.get(VideoPlaceMapping, mapping_id)
        current_asset = await check_session.get(MediaAsset, asset_id)
        assert current_mapping is not None
        assert current_mapping.place_id == target_place_id
        assert current_asset is not None
        assert current_asset.place_id == target_place_id


async def test_list_place_summaries_sorts_by_mention_count(session):
    # mention_count는 매핑 행 수가 아니라 고유 영상 수다(한 영상에서 여러 번 언급돼도 1회).
    # '반복 장소'는 서로 다른 영상 2개에서 언급 → mention_count=2, '첫 장소'는 1개 → 1.
    video_a = YoutubeVideo(
        video_id="v-source-a",
        title="부산 여행 A",
        url="https://youtu.be/source-a",
        channel_id="uc-source",
        channel_name="여행 채널",
    )
    video_b = YoutubeVideo(
        video_id="v-source-b",
        title="부산 여행 B",
        url="https://youtu.be/source-b",
        channel_id="uc-source",
        channel_name="여행 채널",
    )
    first = TravelPlace(name="첫 장소", latitude=35.0, longitude=129.0, is_geocoded=True)
    second = TravelPlace(name="반복 장소", latitude=35.1, longitude=129.1, is_geocoded=True)
    session.add_all([video_a, video_b, first, second])
    await session.commit()
    await session.refresh(first)
    await session.refresh(second)
    session.add_all(
        [
            # '반복 장소': 영상 A에서 2번 언급(1회로 셈) + 영상 B에서 1번 → 고유 영상 2.
            VideoPlaceMapping(video_id=video_a.video_id, place_id=second.place_id, ai_summary="1"),
            VideoPlaceMapping(video_id=video_a.video_id, place_id=second.place_id, ai_summary="2"),
            VideoPlaceMapping(video_id=video_b.video_id, place_id=second.place_id, ai_summary="3"),
            # '첫 장소': 영상 A에서만 → 고유 영상 1.
            VideoPlaceMapping(video_id=video_a.video_id, place_id=first.place_id, ai_summary="4"),
        ]
    )
    await session.commit()

    summaries = await svc.list_place_summaries(session, sort="mention_count")

    assert summaries[0].place.name == "반복 장소"
    assert summaries[0].mention_count == 2
    assert summaries[0].source_channel_count == 1
    assert summaries[0].source_videos[0].channel_name == "여행 채널"


async def test_exclude_video_deletes_orphan_place_and_preserves_shared(session):
    # T-159 회귀: 매핑 보유 영상 제외 시 고아 판정 루프가 존재하지 않는
    # ExtractedPlaceCandidate.place_id를 참조해 AttributeError로 죽던 경로.
    # 수정 후에는 정상 완료하고 (a) 고아 장소만 삭제, (b) 공유 장소는 보존해야 한다.
    video_main = YoutubeVideo(
        video_id="v-ex-1", title="제외 대상", url="u1", channel_id="c"
    )
    video_other = YoutubeVideo(
        video_id="v-ex-2", title="보존 영상", url="u2", channel_id="c"
    )
    orphan = TravelPlace(name="고아 장소", latitude=35.0, longitude=129.0, is_geocoded=True)
    shared = TravelPlace(name="공유 장소", latitude=35.1, longitude=129.1, is_geocoded=True)
    kept_by_candidate = TravelPlace(
        name="후보 참조 장소", latitude=35.2, longitude=129.2, is_geocoded=True
    )
    session.add_all([video_main, video_other, orphan, shared, kept_by_candidate])
    await session.commit()
    for place in (orphan, shared, kept_by_candidate):
        await session.refresh(place)

    session.add_all(
        [
            # 고아 장소를 삭제해도 RustFS asset 행은 보존하고 place 연결만 해제한다.
            MediaAsset(
                video_id="v-ex-1",
                place_id=orphan.place_id,
                asset_type="frame",
                bucket="b",
                object_key="exclude-orphan-preserved",
                object_uri="u",
            ),
            # 제외 대상 영상의 언급 매핑: 세 장소 모두.
            VideoPlaceMapping(video_id="v-ex-1", place_id=orphan.place_id, ai_summary="s"),
            VideoPlaceMapping(video_id="v-ex-1", place_id=shared.place_id, ai_summary="s"),
            VideoPlaceMapping(
                video_id="v-ex-1", place_id=kept_by_candidate.place_id, ai_summary="s"
            ),
            # 다른 영상이 '공유 장소'를 매핑으로 언급 → 보존 근거 (b).
            VideoPlaceMapping(video_id="v-ex-2", place_id=shared.place_id, ai_summary="s"),
            # 제외 대상 영상의 matched 후보(영상 제외와 함께 삭제됨).
            ExtractedPlaceCandidate(
                video_id="v-ex-1", source_text="s", ai_place_name="고아 장소",
                match_status=MatchStatus.MATCHED, matched_place_id=orphan.place_id,
            ),
            # 다른 영상의 matched 후보가 '후보 참조 장소'를 참조 → 수정된 컬럼 경로로 보존.
            ExtractedPlaceCandidate(
                video_id="v-ex-2", source_text="s", ai_place_name="후보 참조 장소",
                match_status=MatchStatus.MATCHED,
                matched_place_id=kept_by_candidate.place_id,
            ),
        ]
    )
    await session.commit()
    orphan_asset_id = (
        await session.execute(
            select(MediaAsset.id).where(
                MediaAsset.object_key == "exclude-orphan-preserved"
            )
        )
    ).scalar_one()

    # 수정 전에는 place_ids가 비어 있지 않아 고아 판정 루프 진입 즉시 AttributeError.
    summary = await svc.exclude_video(session, "v-ex-1", reason="스팸 영상")

    assert summary is not None
    assert summary["deleted_candidates"] == 1
    assert summary["deleted_mappings"] == 3
    assert summary["deleted_places"] == 1

    video = await session.get(YoutubeVideo, "v-ex-1")
    assert video is not None
    assert video.is_excluded is True
    assert video.exclusion_reason == "스팸 영상"

    remaining_place_ids = set(
        (await session.execute(select(TravelPlace.place_id))).scalars()
    )
    # (a) 다른 영상 언급이 없는 고아 장소만 삭제된다.
    assert orphan.place_id not in remaining_place_ids
    orphan_asset = await session.get(MediaAsset, orphan_asset_id)
    assert orphan_asset is not None
    assert orphan_asset.place_id is None
    # (b) 다른 영상 매핑이 있는 장소·다른 영상 matched 후보가 참조하는 장소는 보존된다.
    assert shared.place_id in remaining_place_ids
    assert kept_by_candidate.place_id in remaining_place_ids

    # 제외 대상 영상의 매핑은 사라지고, 다른 영상의 데이터는 남는다.
    remaining_mappings = (
        (
            await session.execute(
                select(VideoPlaceMapping.video_id).order_by(VideoPlaceMapping.id)
            )
        )
        .scalars()
        .all()
    )
    assert remaining_mappings == ["v-ex-2"]
    # T-160: 후보는 hard delete 대신 soft delete — 행은 보존되고 활성 조회에서만 제외.
    active_candidates = (
        (
            await session.execute(
                select(ExtractedPlaceCandidate.video_id)
                .where(ExtractedPlaceCandidate.deleted_at.is_(None))
                .order_by(ExtractedPlaceCandidate.id)
            )
        )
        .scalars()
        .all()
    )
    assert active_candidates == ["v-ex-2"]
    deleted_candidate = (
        (
            await session.execute(
                select(ExtractedPlaceCandidate).where(
                    ExtractedPlaceCandidate.video_id == "v-ex-1"
                )
            )
        )
        .scalars()
        .one()
    )
    assert deleted_candidate.deleted_at is not None
    assert deleted_candidate.deletion_reason == "스팸 영상"
    assert deleted_candidate.matched_place_id is None


async def _seed_candidate(
    session,
    *,
    video_id: str = "v-sd-1",
    name: str = "후보",
    status: MatchStatus = MatchStatus.NEEDS_REVIEW,
    matched_place_id: int | None = None,
) -> ExtractedPlaceCandidate:
    if await session.get(YoutubeVideo, video_id) is None:
        session.add(YoutubeVideo(video_id=video_id, title="t", url="u", channel_id="c"))
        await session.commit()
    candidate = ExtractedPlaceCandidate(
        video_id=video_id,
        source_text="s",
        ai_place_name=name,
        match_status=status,
        matched_place_id=matched_place_id,
    )
    session.add(candidate)
    await session.commit()
    await session.refresh(candidate)
    return candidate


async def test_soft_delete_requires_reason_and_is_idempotent(session):
    candidate = await _seed_candidate(session)

    with pytest.raises(ValueError):
        await svc.soft_delete_candidates(session, [candidate.id], reason="  ")

    summary = await svc.soft_delete_candidates(
        session, [candidate.id], reason="테스트 삭제", deleted_by="web"
    )
    assert summary.deleted_candidates == 1
    assert summary.candidate_ids == [candidate.id]
    await session.commit()
    await session.refresh(candidate)
    assert candidate.deleted_at is not None
    assert candidate.deletion_reason == "테스트 삭제"
    assert candidate.deleted_by == "web"

    # 이미 soft delete된 후보는 건너뛴다(멱등).
    again = await svc.soft_delete_candidates(
        session, [candidate.id], reason="재시도"
    )
    assert again.deleted_candidates == 0
    await session.refresh(candidate)
    assert candidate.deletion_reason == "테스트 삭제"


async def test_soft_delete_expected_status_rejects_stale_bulk_atomically(session):
    needs_review = await _seed_candidate(
        session, video_id="v-sd-status-needs", name="검수 대기"
    )
    ignored = await _seed_candidate(
        session,
        video_id="v-sd-status-ignored",
        name="이미 제외",
        status=MatchStatus.IGNORED,
    )
    matched = await _seed_candidate(
        session,
        video_id="v-sd-status-matched",
        name="이미 확정",
        status=MatchStatus.MATCHED,
    )

    with pytest.raises(svc.CandidateStatusConflictError) as raised:
        await svc.soft_delete_candidates(
            session,
            [needs_review.id, ignored.id, matched.id],
            reason="stale bulk 삭제",
            expected_status=MatchStatus.NEEDS_REVIEW,
        )

    assert raised.value.expected_status is MatchStatus.NEEDS_REVIEW
    assert raised.value.actual_status_by_candidate_id == {
        ignored.id: MatchStatus.IGNORED.value,
        matched.id: MatchStatus.MATCHED.value,
    }
    # 하나라도 stale면 함께 잠긴 정상 후보도 삭제하지 않는다.
    for candidate in (needs_review, ignored, matched):
        await session.refresh(candidate)
        assert candidate.deleted_at is None


async def test_soft_delete_expected_status_serializes_with_concurrent_ignore(
    session_factory,
):
    async with session_factory() as seed_session:
        candidate = await _seed_candidate(
            seed_session,
            video_id="v-sd-status-race",
            name="동시 삭제 제외",
        )
        candidate_id = candidate.id

    async def delete_from_stale_queue() -> str:
        async with session_factory() as delete_session:
            try:
                await svc.soft_delete_candidates(
                    delete_session,
                    [candidate_id],
                    reason="stale row 삭제",
                    expected_status=MatchStatus.NEEDS_REVIEW,
                )
                await delete_session.commit()
            except svc.CandidateStatusConflictError:
                await delete_session.rollback()
                return "delete_conflict"
            return "deleted"

    async def ignore_from_other_reviewer() -> str:
        async with session_factory() as resolve_session:
            try:
                await svc.resolve_candidate(
                    resolve_session,
                    candidate_id=candidate_id,
                    action="ignore",
                    reviewed_by="other-reviewer",
                    commit=False,
                )
                await resolve_session.commit()
            except ValueError:
                await resolve_session.rollback()
                return "ignore_rejected"
            return "ignored"

    outcomes = set(
        await asyncio.wait_for(
            asyncio.gather(
                delete_from_stale_queue(),
                ignore_from_other_reviewer(),
            ),
            timeout=5,
        )
    )
    assert outcomes in (
        {"deleted", "ignore_rejected"},
        {"delete_conflict", "ignored"},
    )

    async with session_factory() as check_session:
        current = await check_session.get(ExtractedPlaceCandidate, candidate_id)
        assert current is not None
        if outcomes == {"deleted", "ignore_rejected"}:
            assert current.deleted_at is not None
            assert current.match_status == MatchStatus.NEEDS_REVIEW.value
        else:
            assert current.deleted_at is None
            assert current.match_status == MatchStatus.IGNORED.value


async def test_soft_delete_conflict_without_force_and_cleanup_with_force(session):
    place = await _add_place(session, "확정 장소", 35.0, 129.0)
    candidate = await _seed_candidate(
        session,
        status=MatchStatus.USER_CORRECTED,
        matched_place_id=place.place_id,
    )
    session.add(
        VideoPlaceMapping(
            video_id=candidate.video_id,
            place_id=place.place_id,
            place_candidate_id=candidate.id,
            ai_summary="s",
        )
    )
    await session.commit()

    # force=False(검수 큐 개별 삭제): 확정 연결(매핑 보유) 후보는 409 semantics.
    with pytest.raises(svc.CandidateMappingConflictError):
        await svc.soft_delete_candidates(session, [candidate.id], reason="개별 삭제")
    await session.refresh(candidate)
    assert candidate.deleted_at is None
    assert candidate.matched_place_id == place.place_id

    # force=True(영상 제외): 매핑 삭제 + matched_place_id 해제 + 삭제 필드 세팅.
    summary = await svc.soft_delete_candidates(
        session, [candidate.id], reason="영상 제외", deleted_by="web", force=True
    )
    await session.commit()
    assert summary.deleted_candidates == 1
    assert summary.deleted_mappings == 1
    assert summary.affected_place_ids == frozenset({place.place_id})
    await session.refresh(candidate)
    assert candidate.deleted_at is not None
    assert candidate.matched_place_id is None
    remaining = (
        await session.execute(
            select(VideoPlaceMapping).where(
                VideoPlaceMapping.place_candidate_id == candidate.id
            )
        )
    ).scalars().all()
    assert remaining == []


async def test_reopen_candidate_transitions(session):
    # soft deleted → needs_review 복귀 + 삭제 필드 clear + export pending.
    deleted = await _seed_candidate(session, name="삭제 후보")
    deleted.reviewed_by = "reviewer-a"
    deleted.reviewed_at = utcnow()
    deleted.review_note = "직전 판정 사유"
    await session.commit()
    await svc.soft_delete_candidates(session, [deleted.id], reason="실수 삭제")
    await session.commit()
    reopened, source = await svc.reopen_candidate(session, candidate_id=deleted.id)
    await session.commit()
    assert source == "deleted"
    assert reopened.deleted_at is None
    assert reopened.deletion_reason is None
    assert reopened.deleted_by is None
    assert reopened.match_status == MatchStatus.NEEDS_REVIEW.value
    assert reopened.feature_export_status == FeatureExportStatus.PENDING.value
    # 검수자 메타는 clear(재검수 시 stale 표시 방지), review_note는 보존.
    assert reopened.reviewed_by is None
    assert reopened.reviewed_at is None
    assert reopened.review_note == "직전 판정 사유"

    # ignored → needs_review 복귀.
    ignored = await _seed_candidate(
        session, video_id="v-sd-2", name="제외 후보", status=MatchStatus.IGNORED
    )
    reopened2, source2 = await svc.reopen_candidate(session, candidate_id=ignored.id)
    await session.commit()
    assert source2 == "ignored"
    assert reopened2.match_status == MatchStatus.NEEDS_REVIEW.value

    # 이미 needs_review → 409용 conflict.
    with pytest.raises(svc.CandidateReopenConflictError):
        await svc.reopen_candidate(session, candidate_id=reopened2.id)

    # matched/user_corrected → 범위 밖(400) — 장소 정리 정책은 T-184.
    corrected = await _seed_candidate(
        session, video_id="v-sd-3", name="확정 후보", status=MatchStatus.USER_CORRECTED
    )
    with pytest.raises(svc.CandidateReopenUnsupportedError):
        await svc.reopen_candidate(session, candidate_id=corrected.id)

    # 존재하지 않는 후보 → 404용 ValueError.
    with pytest.raises(ValueError):
        await svc.reopen_candidate(session, candidate_id=999_999)


async def test_list_unmatched_excludes_soft_deleted(session):
    keep = await _seed_candidate(session, name="유지 후보")
    drop = await _seed_candidate(session, name="삭제 후보")
    await svc.soft_delete_candidates(session, [drop.id], reason="정리")
    await session.commit()

    unmatched = await svc.list_unmatched_candidates(session)
    ids = {candidate.id for candidate in unmatched}
    assert keep.id in ids
    assert drop.id not in ids

    # resolve/review 접근도 soft delete 후보를 거부한다.
    with pytest.raises(ValueError):
        await svc.resolve_candidate(
            session, candidate_id=drop.id, action="ignore", reviewed_by="web"
        )
    with pytest.raises(ValueError):
        await svc.review_candidate(
            session, candidate_id=drop.id, reviewed_by="web"
        )


async def test_check_constraint_requires_deletion_reason(session):
    # B1 절차 5 회귀: helper를 우회해 사유 없이 deleted_at만 세팅하면
    # DB CHECK(ck_epc_deleted_requires_reason)가 flush에서 막는다.
    candidate = await _seed_candidate(session, name="사유 없는 삭제")
    candidate.deleted_at = utcnow()  # deletion_reason 없이
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_review_queue_partial_indexes_exclude_deleted(session):
    # B1 절차 5 회귀(모델·migration 드리프트 가드): 검수 큐 인덱스 3종은
    # `WHERE (deleted_at IS NULL)` partial index여야 한다.
    rows = (
        await session.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = 'extracted_place_candidates' "
                "AND indexname LIKE 'ix_epc_review_queue%'"
            )
        )
    ).all()
    defs = {name: definition for name, definition in rows}
    assert set(defs) == {
        "ix_epc_review_queue_status_id",
        "ix_epc_review_queue_channel_status_id",
        "ix_epc_review_queue_playlist_status_id",
    }
    for definition in defs.values():
        assert "WHERE (deleted_at IS NULL)" in definition


async def test_soft_delete_never_exported_candidate_creates_no_tombstone(session):
    # export된 적 없는 후보 삭제: 의미 없는 tombstone을 만들지 않는다(B1 절차 3).
    candidate = await _seed_candidate(session, name="미노출 후보")
    summary = await svc.soft_delete_candidates(
        session, [candidate.id], reason="노출 전 삭제"
    )
    await session.commit()
    assert summary.tombstoned_exports == 0
    ledger_rows = (
        (
            await session.execute(
                select(FeatureExport).where(
                    FeatureExport.candidate_id == candidate.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert ledger_rows == []


async def test_exclude_video_blank_reason_uses_default(session):
    # 공백 reason이 helper 사유 검증(ValueError→500)으로 흐르지 않고 기본 사유를 쓴다.
    candidate = await _seed_candidate(session, video_id="v-blank", name="공백 사유")
    summary = await svc.exclude_video(session, "v-blank", reason="   ")
    assert summary is not None
    assert summary["deleted_candidates"] == 1
    await session.refresh(candidate)
    assert candidate.deleted_at is not None
    assert candidate.deletion_reason == "동영상 제외"
    video = await session.get(YoutubeVideo, "v-blank")
    assert video is not None
    assert video.is_excluded is True
    assert video.exclusion_reason is None  # 공백은 저장하지 않는다
