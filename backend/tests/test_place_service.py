"""place_service 근접 탐색/중복 후보/검수 큐 테스트."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from ktc.models import (
    ExtractedPlaceCandidate,
    MatchStatus,
    MediaAsset,
    TravelPlace,
    VideoPlaceMapping,
    YoutubeVideo,
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
    # (b) 다른 영상 매핑이 있는 장소·다른 영상 matched 후보가 참조하는 장소는 보존된다.
    assert shared.place_id in remaining_place_ids
    assert kept_by_candidate.place_id in remaining_place_ids

    # 제외 대상 영상의 매핑·후보는 모두 사라지고, 다른 영상의 데이터는 남는다.
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
    remaining_candidates = (
        (
            await session.execute(
                select(ExtractedPlaceCandidate.video_id).order_by(
                    ExtractedPlaceCandidate.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert remaining_candidates == ["v-ex-2"]
