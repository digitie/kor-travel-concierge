"""geocode_service 적용 로직 테스트 (DB 영속화)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import InvalidRequestError

from ktc.etl import admin_region_service, geocode_service
from ktc.etl.geocode_service import (
    CandidateStateChangedError,
    _names_match,
    apply_geocode_to_candidate as apply_geocode_to_candidate_versioned,
    apply_geocode_to_current_candidate as apply_geocode_to_candidate,
)
from ktc.etl.geocoding import GeocodeCandidate, GeocodeDecision
from ktc.models import (
    AuditStatus,
    EvidenceSourceKind,
    ExtractedPlaceCandidate,
    FeatureExportStatus,
    GroundingStatus,
    MatchStatus,
    TravelPlace,
    VideoPlaceMapping,
    YoutubeVideo,
)
from ktc.models.travel_place import PlaceLifecycleOrigin
from ktc.services import place_service


def test_versioned_applier_requires_expected_candidate_version():
    with pytest.raises(TypeError, match="expected_candidate_version"):
        apply_geocode_to_candidate_versioned(None, None, None)


async def _make_candidate(
    session,
    name="월정리 카페",
    category="카페",
    *,
    # 기본은 verified_raw로 둔다: 이 파일 대부분은 grounding이 아닌 매칭 로직을 검증하며
    # T-165 게이트에 걸리지 않아야 한다(자동확정 경로 회귀).
    grounding_status=GroundingStatus.VERIFIED_RAW.value,
    source_kind=EvidenceSourceKind.TRANSCRIPT.value,
    # T-166 is_domestic fail-closed 게이트가 매칭 로직 회귀 테스트를 막지 않도록 기본은
    # 명시적 국내(True)로 둔다. None fail-closed는 전용 테스트에서만 검증한다.
    is_domestic=True,
    location_hint=None,
):
    session.add(YoutubeVideo(video_id="v1", title="t", url="u", channel_id="c"))
    await session.commit()
    c = ExtractedPlaceCandidate(
        video_id="v1", source_text="s", ai_place_name=name, candidate_category=category,
        match_status=MatchStatus.NEEDS_REVIEW,
        source_kind=source_kind,
        grounding_status=grounding_status,
        is_domestic=is_domestic,
        location_hint=location_hint,
    )
    session.add(c)
    await session.commit()
    await session.refresh(c)
    return c


async def test_apply_matched_creates_place(session):
    # 신규 장소 자동확정은 POI identity 검증을 요구한다(G4/D2). poi 결과 + 이름 일치.
    candidate = await _make_candidate(session)
    decision = GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(
            latitude=33.5563,
            longitude=126.7958,
            place_name="월정리 카페",
            road_address="제주 구좌읍 ...",
            source="kakao_keyword",
        ),
        confidence=1.0,
        reason="single_result",
        candidate_count=1,
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)
    assert place is not None
    assert place.is_geocoded is True
    assert place.name == "월정리 카페"
    assert place.road_address == "제주 구좌읍 ..."
    assert place.lifecycle_origin == PlaceLifecycleOrigin.CANDIDATE_CREATED.value
    assert place.origin_candidate_id == candidate.id

    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.match_status == MatchStatus.MATCHED
    assert refreshed.matched_place_id == place.place_id
    assert refreshed.reviewed_at is not None
    assert refreshed.feature_export_status == FeatureExportStatus.READY
    assert refreshed.provider_evidence_json["geocoding"]["decision"]["reason"] == "single_result"
    assert refreshed.provider_evidence_json["geocoding"]["selected_candidate"]["source"] == "kakao_keyword"
    assert refreshed.provider_evidence_json["geocoding"]["identity"]["name_gate"] == "poi_match"
    mapping = (await session.execute(select(VideoPlaceMapping))).scalars().one()
    assert mapping.video_id == candidate.video_id
    assert mapping.place_id == place.place_id
    assert mapping.feature_export_status == FeatureExportStatus.READY
    assert mapping.provider_evidence_json == refreshed.provider_evidence_json


async def test_apply_matched_copies_category_code_from_evidence(session):
    # A안: 확정 시 POI 추출 때 후보 evidence에 저장된 코드를 복사한다(Gemini 호출 X).
    candidate = await _make_candidate(session, name="월정리 해변", category="해변")
    candidate.provider_evidence_json = {"transcript": {"category_code": "01050100"}}
    await session.commit()
    decision = GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(
            latitude=33.5563,
            longitude=126.7958,
            place_name="월정리 해변",
            road_address="제주 구좌읍",
            source="kakao_keyword",
        ),
        confidence=1.0,
        reason="single_result",
        candidate_count=1,
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)
    assert place.category_code_suggestion == "01050100"


async def test_apply_matched_uses_unknown_when_evidence_missing(session):
    candidate = await _make_candidate(session)  # evidence에 category_code 없음
    decision = GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(
            latitude=33.5563,
            longitude=126.7958,
            place_name="월정리 카페",
            source="kakao_keyword",
        ),
        confidence=1.0,
        reason="single_result",
        candidate_count=1,
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)
    assert place.category_code_suggestion == "0"
    assert place.category == "unknown"


async def test_apply_needs_review_keeps_candidate(session):
    candidate = await _make_candidate(session)
    decision = GeocodeDecision("needs_review", None, 0.0, "no_result", 0)
    place = await apply_geocode_to_candidate(session, candidate, decision)
    assert place is None

    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.match_status == MatchStatus.NEEDS_REVIEW
    assert refreshed.review_note == "no_result"
    assert refreshed.feature_export_status == FeatureExportStatus.PENDING
    assert refreshed.provider_evidence_json["geocoding"]["decision"]["reason"] == "no_result"
    # 장소는 생성되지 않는다 (자동 확정 금지)
    places = (await session.execute(select(TravelPlace))).scalars().all()
    assert places == []


async def test_apply_matched_reuses_nearby_duplicate(session):
    # 기존 장소
    existing = TravelPlace(name="월정리 카페", latitude=33.5563, longitude=126.7958, is_geocoded=True)
    session.add(existing)
    await session.commit()
    await session.refresh(existing)

    candidate = await _make_candidate(session, name="월정리 카페")
    decision = GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(latitude=33.55635, longitude=126.79585),  # ~약 6m
        confidence=1.0,
        reason="single_result",
        candidate_count=1,
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)
    # 근접 중복이므로 기존 장소를 재사용 (새로 만들지 않음)
    assert place.place_id == existing.place_id
    assert place.lifecycle_origin == PlaceLifecycleOrigin.PERSISTENT.value
    assert place.origin_candidate_id is None
    places = (await session.execute(select(TravelPlace))).scalars().all()
    assert len(places) == 1


async def test_apply_matched_nearby_name_mismatch_needs_review(session):
    existing = TravelPlace(name="월정리 카페", latitude=33.5563, longitude=126.7958, is_geocoded=True)
    session.add(existing)
    await session.commit()

    candidate = await _make_candidate(session, name="다른 식당")
    decision = GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(latitude=33.55635, longitude=126.79585),
        confidence=1.0,
        reason="single_result",
        candidate_count=1,
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)

    assert place is None
    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.match_status == MatchStatus.NEEDS_REVIEW
    assert refreshed.review_note == "nearby_place_name_mismatch"
    assert refreshed.feature_export_status == FeatureExportStatus.PENDING


async def test_apply_matched_nearby_short_partial_name_needs_review(session):
    existing = TravelPlace(name="월정리 카페", latitude=33.5563, longitude=126.7958, is_geocoded=True)
    session.add(existing)
    await session.commit()

    candidate = await _make_candidate(session, name="카페")
    decision = GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(latitude=33.55635, longitude=126.79585),
        confidence=1.0,
        reason="single_result",
        candidate_count=1,
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)

    assert place is None
    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.match_status == MatchStatus.NEEDS_REVIEW
    assert refreshed.review_note == "nearby_place_name_mismatch"


async def test_apply_matched_ungrounded_transcript_stays_needs_review(session):
    # transcript 후보가 raw grounding 미확인이면 지오코딩 matched여도 자동확정하지 않는다.
    candidate = await _make_candidate(
        session, grounding_status=GroundingStatus.UNVERIFIED.value
    )
    decision = GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(
            latitude=33.5563, longitude=126.7958, road_address="제주 ...", source="kakao"
        ),
        confidence=1.0,
        reason="single_result",
        candidate_count=1,
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)
    assert place is None
    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.match_status == MatchStatus.NEEDS_REVIEW
    assert refreshed.review_note == "ungrounded"
    assert refreshed.feature_export_status == FeatureExportStatus.PENDING
    # 폐기하지 않고 지오코딩 근거는 기록한다(사람 검수에서 재사용).
    assert refreshed.provider_evidence_json["geocoding"]["decision"]["reason"] == "single_result"
    # 장소는 생성되지 않는다.
    places = (await session.execute(select(TravelPlace))).scalars().all()
    assert places == []


async def test_apply_matched_legacy_unknown_transcript_stays_needs_review(session):
    # 게이트 도입 전 기존 후보(legacy_unknown)도 자동확정 금지 → 사람 검수 요구.
    candidate = await _make_candidate(
        session, grounding_status=GroundingStatus.LEGACY_UNKNOWN.value
    )
    decision = GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(latitude=33.5563, longitude=126.7958),
        confidence=1.0,
        reason="single_result",
        candidate_count=1,
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)
    assert place is None
    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.match_status == MatchStatus.NEEDS_REVIEW
    assert refreshed.review_note == "ungrounded"


async def test_apply_matched_non_transcript_not_gated_by_grounding(session):
    # 비-transcript 후보(예: url_summary)는 raw segment grounding 규칙 대상이 아니라
    # grounding이 missing이어도 자동확정이 막히지 않는다(gate는 transcript 전용).
    candidate = await _make_candidate(
        session,
        source_kind=EvidenceSourceKind.URL_SUMMARY.value,
        grounding_status=GroundingStatus.MISSING.value,
    )
    decision = GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(
            latitude=33.5563,
            longitude=126.7958,
            place_name="월정리 카페",
            road_address="제주 ...",
            source="kakao_keyword",
        ),
        confidence=1.0,
        reason="single_result",
        candidate_count=1,
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)
    assert place is not None
    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.match_status == MatchStatus.MATCHED


def test_names_match_rejects_short_partial_names():
    assert _names_match("월정리 카페", "월정리카페")
    assert not _names_match("카페", "월정리카페")
    assert not _names_match("성산", "성산일출봉")


def test_names_match_allows_specific_contained_aliases():
    assert _names_match("월정리 카페", "월정리 카페 본점")
    assert _names_match("감천문화마을", "부산 감천문화마을")


def test_names_match_requires_both_names():
    # pairwise: 한쪽이 비면 검증 불가 → False (any-pair 문제 C8 제거).
    assert not _names_match("월정리 카페", None)
    assert not _names_match(None, "월정리 카페")
    assert not _names_match("", "월정리 카페")


async def test_apply_uses_vworld_for_address_enrichment(session):
    candidate = await _make_candidate(session)
    decision = GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(
            latitude=33.5563,
            longitude=126.7958,
            place_name="월정리 카페",  # poi 결과(주소는 아래 vworld reverse로 보강)
            source="kakao_keyword",
        ),
        confidence=1.0,
        reason="single_result",
        candidate_count=1,
    )

    class FakeVWorld:
        async def reverse_geocode_latlon(self, lat, lng, **kwargs):
            if kwargs["type"] == "road":
                return {"response": {"result": [{"text": "도로명주소"}]}}
            return {"response": {"result": [{"text": "지번주소"}]}}

    place = await apply_geocode_to_candidate(
        session, candidate, decision, vworld=FakeVWorld()
    )
    assert place.road_address == "도로명주소"
    assert place.official_address == "지번주소"


async def test_apply_new_place_runs_isolated_reverse_after_duplicate_disappears(
    session,
    monkeypatch,
):
    """격리 reverse provenance를 unique 제약 없는 legacy mapping 전체에 기록한다."""
    existing = TravelPlace(
        name="월정리 카페",
        latitude=33.5563,
        longitude=126.7958,
        is_geocoded=True,
    )
    session.add(existing)
    await session.commit()
    await session.refresh(existing)
    candidate = await _make_candidate(session)

    duplicate_calls = 0

    async def staged_duplicates(_session, *, lat, lng, **_kwargs):
        nonlocal duplicate_calls
        duplicate_calls += 1
        assert (lat, lng) == (33.5563, 126.7958)
        return [(existing, 0.0)] if duplicate_calls == 1 else []

    reverse_calls = 0

    async def fake_reverse(_client, lat, lng):
        nonlocal reverse_calls
        reverse_calls += 1
        assert (lat, lng) == (33.5563, 126.7958)
        return {
            "road_address": "제주특별자치도 제주시 구좌읍 월정1길",
            "parcel_address": "제주특별자치도 제주시 구좌읍 월정리",
        }

    async def insert_legacy_duplicate_mapping(factory, place_id, **_kwargs):
        async with factory() as legacy_session:
            legacy_session.add(
                VideoPlaceMapping(
                    video_id=candidate.video_id,
                    place_id=place_id,
                    place_candidate_id=candidate.id,
                    ai_summary="unique 제약 도입 전 중복 mapping",
                    provider_evidence_json={"legacy": {"duplicate": True}},
                    feature_export_status=FeatureExportStatus.READY.value,
                )
            )
            await legacy_session.commit()
        return False

    monkeypatch.setattr(
        place_service, "find_duplicate_candidates", staged_duplicates
    )
    monkeypatch.setattr(geocode_service, "reverse_with_vworld", fake_reverse)
    monkeypatch.setattr(
        admin_region_service,
        "enrich_place_admin_codes_isolated",
        insert_legacy_duplicate_mapping,
    )

    place = await apply_geocode_to_candidate(
        session,
        candidate,
        GeocodeDecision(
            status="matched",
            candidate=GeocodeCandidate(
                latitude=33.5563,
                longitude=126.7958,
                place_name="월정리 카페",
                source="kakao_keyword",
            ),
            confidence=1.0,
            reason="single_result",
            candidate_count=1,
        ),
        vworld=object(),
    )

    assert place is not None
    assert place.place_id != existing.place_id
    assert place.road_address == "제주특별자치도 제주시 구좌읍 월정1길"
    assert place.official_address == "제주특별자치도 제주시 구좌읍 월정리"
    assert duplicate_calls == 2
    assert reverse_calls == 1
    await session.refresh(candidate)
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
    reverse_vworld = {
        "road_address": "제주특별자치도 제주시 구좌읍 월정1길",
        "parcel_address": "제주특별자치도 제주시 구좌읍 월정리",
    }
    assert candidate.provider_evidence_json["geocoding"]["reverse_vworld"] == (
        reverse_vworld
    )
    assert len(mappings) == 2
    assert all(
        mapping.provider_evidence_json["geocoding"]["reverse_vworld"]
        == reverse_vworld
        for mapping in mappings
    )
    legacy_mapping = next(
        mapping
        for mapping in mappings
        if (mapping.provider_evidence_json or {}).get("legacy")
    )
    assert legacy_mapping.provider_evidence_json["legacy"] == {"duplicate": True}


# --- T-166 identity 게이트: 이름(result_kind별) ---


async def test_apply_new_place_poi_name_mismatch_blocks(session):
    # 신규 장소 생성 경로(D2)에서도 poi 결과의 provider명이 AI명과 다르면 자동확정 금지.
    candidate = await _make_candidate(session, name="스타벅스 강남점")
    decision = GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(
            latitude=37.4979,
            longitude=127.0276,
            place_name="투썸플레이스 강남점",  # 다른 상호
            source="kakao_keyword",  # → result_kind=poi
        ),
        confidence=1.0,
        reason="single_result",
        candidate_count=1,
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)
    assert place is None
    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.match_status == MatchStatus.NEEDS_REVIEW
    assert refreshed.review_note == "name_mismatch"
    identity = refreshed.provider_evidence_json["geocoding"]["identity"]
    assert identity["result_kind"] == "poi"
    assert identity["name_gate"] == "name_mismatch"
    assert (await session.execute(select(TravelPlace))).scalars().all() == []


async def test_apply_new_place_poi_name_match_creates_place(session):
    candidate = await _make_candidate(session, name="스타벅스 강남점")
    decision = GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(
            latitude=37.4979,
            longitude=127.0276,
            place_name="스타벅스 강남점",
            road_address="서울특별시 강남구 강남대로",
            source="kakao_keyword",
        ),
        confidence=1.0,
        reason="single_result",
        candidate_count=1,
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)
    assert place is not None
    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.match_status == MatchStatus.MATCHED
    assert refreshed.provider_evidence_json["geocoding"]["identity"]["name_gate"] == "poi_match"


async def test_apply_address_result_new_place_blocks_as_unverified(session):
    # 신규 장소 + 주소 결과(place_name이 주소): POI identity 검증 불가 → 자동확정 금지
    # (G4/D2). place_name이 POI명이 아니므로 name_unverified를 차단 사유로 격상한다.
    candidate = await _make_candidate(session, name="부산역 국밥집")
    decision = GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(
            latitude=35.1151,
            longitude=129.0423,
            place_name="부산광역시 동구 중앙대로 206",  # POI명이 아니라 주소
            road_address="부산광역시 동구 중앙대로 206",
            source="kakao",  # → result_kind=address
        ),
        confidence=1.0,
        reason="single_result",
        candidate_count=1,
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)
    assert place is None
    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.match_status == MatchStatus.NEEDS_REVIEW
    assert refreshed.review_note == "name_unverified"
    assert refreshed.feature_export_status == FeatureExportStatus.PENDING
    identity = refreshed.provider_evidence_json["geocoding"]["identity"]
    assert identity["result_kind"] == "address"
    assert identity["name_gate"] == "name_unverified"
    assert (await session.execute(select(TravelPlace))).scalars().all() == []


async def test_apply_address_result_reuses_nearby_without_poi_name(session):
    # 근접 중복 재사용 경로는 기존 장소명으로 검증되므로 address 결과라도 자동확정된다
    # (G4/D2 예외 — POI 이름 게이트가 아니라 기존명 대조로 identity가 검증됨).
    existing = TravelPlace(
        name="부산역 국밥집", latitude=35.1151, longitude=129.0423, is_geocoded=True
    )
    session.add(existing)
    await session.commit()
    candidate = await _make_candidate(session, name="부산역 국밥집")
    decision = GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(
            latitude=35.11512,
            longitude=129.04232,  # ~약 3m
            place_name="부산광역시 동구 중앙대로 206",
            road_address="부산광역시 동구 중앙대로 206",
            source="kakao",
        ),
        confidence=1.0,
        reason="single_result",
        candidate_count=1,
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)
    assert place is not None
    assert place.place_id == existing.place_id
    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.match_status == MatchStatus.MATCHED
    assert refreshed.provider_evidence_json["geocoding"]["identity"]["name_gate"] == "nearby_match"


# --- T-166 identity 게이트: 행정구역 ---


async def test_apply_region_mismatch_blocks(session):
    # hint는 대구인데 확정 주소가 서울 → region_mismatch로 검수 큐. poi 결과 + 이름 일치로
    # 이름 게이트를 통과시켜 행정구역 게이트가 실제 차단 사유가 되게 한다.
    candidate = await _make_candidate(
        session, name="어떤 맛집", location_hint="대구 동성로"
    )
    decision = GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(
            latitude=37.5665,
            longitude=126.9780,
            place_name="어떤 맛집",  # AI명과 일치(이름 게이트 통과)
            road_address="서울특별시 중구 세종대로",  # 시도는 서울
            source="kakao_keyword",
        ),
        confidence=1.0,
        reason="single_result",
        candidate_count=1,
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)
    assert place is None
    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.match_status == MatchStatus.NEEDS_REVIEW
    assert refreshed.review_note == "region_mismatch"
    assert refreshed.provider_evidence_json["geocoding"]["identity"]["region_gate"] == "region_mismatch"
    assert (await session.execute(select(TravelPlace))).scalars().all() == []


async def test_apply_region_match_with_alias_creates_place(session):
    # hint "대구"와 확정 주소 "대구광역시"는 별칭이므로 일치 → 자동확정(poi + 이름 일치).
    candidate = await _make_candidate(
        session, name="근대골목단팥빵", location_hint="대구 중구"
    )
    decision = GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(
            latitude=35.8688,
            longitude=128.5940,
            place_name="근대골목단팥빵",
            road_address="대구광역시 중구 남성로",
            source="kakao_keyword",
        ),
        confidence=1.0,
        reason="single_result",
        candidate_count=1,
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)
    assert place is not None
    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.match_status == MatchStatus.MATCHED
    assert refreshed.provider_evidence_json["geocoding"]["identity"]["region_gate"] == "region_match"


# --- T-166 is_domestic fail-closed ---


async def test_apply_is_domestic_none_fail_closed(session):
    # 국내 여부 미확인(None)은 지오코딩 matched여도 자동확정하지 않는다(해외 가능성).
    # poi + 이름 일치로 이름 게이트를 통과시켜 is_domestic이 실제 차단 사유가 되게 한다.
    candidate = await _make_candidate(session, name="월정리 카페", is_domestic=None)
    decision = GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(
            latitude=33.5563,
            longitude=126.7958,
            place_name="월정리 카페",
            road_address="제주특별자치도 제주시",
            source="kakao_keyword",
        ),
        confidence=1.0,
        reason="single_result",
        candidate_count=1,
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)
    assert place is None
    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.match_status == MatchStatus.NEEDS_REVIEW
    assert refreshed.review_note == "domestic_unverified"
    assert refreshed.provider_evidence_json["geocoding"]["identity"]["is_domestic_gate"] == "unverified"
    assert (await session.execute(select(TravelPlace))).scalars().all() == []


# --- T-166 ambiguous 단일 게이트 통과 자동확정 ---


async def test_apply_ambiguous_single_gate_pass_autoconfirms(session):
    # 다건 결과에서 이름 게이트를 통과하는 후보가 정확히 1개면 0.7로 자동확정한다.
    candidate = await _make_candidate(session, name="스타벅스 제주점")
    decision = GeocodeDecision(
        status="needs_review",
        candidate=None,
        confidence=0.5,
        reason="ambiguous",
        candidate_count=2,
        primary_candidates=[
            GeocodeCandidate(
                latitude=33.4996,
                longitude=126.5312,
                place_name="스타벅스 제주점",
                road_address="제주특별자치도 제주시",
                source="kakao_keyword",
            ),
            GeocodeCandidate(
                latitude=35.1796,
                longitude=129.0756,
                place_name="스타벅스 부산점",
                road_address="부산광역시",
                source="kakao_keyword",
            ),
        ],
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)
    assert place is not None
    assert place.latitude == 33.4996
    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.match_status == MatchStatus.MATCHED
    assert refreshed.confidence_score == 0.7
    identity = refreshed.provider_evidence_json["geocoding"]["identity"]
    assert identity["ambiguous_single_pass"] is True
    assert identity["name_gate"] == "poi_match"


async def test_apply_ambiguous_multiple_pass_stays_review(session):
    # 이름 게이트를 통과하는 poi 후보가 2개 이상이면 자동확정하지 않고 검수 큐로 남긴다.
    candidate = await _make_candidate(session, name="스타벅스")  # location_hint 없음
    decision = GeocodeDecision(
        status="needs_review",
        candidate=None,
        confidence=0.5,
        reason="ambiguous",
        candidate_count=2,
        primary_candidates=[
            GeocodeCandidate(
                latitude=33.4996,
                longitude=126.5312,
                place_name="스타벅스",
                road_address="제주특별자치도 제주시",
                source="kakao_keyword",
            ),
            GeocodeCandidate(
                latitude=35.1796,
                longitude=129.0756,
                place_name="스타벅스",
                road_address="부산광역시",
                source="kakao_keyword",
            ),
        ],
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)
    assert place is None
    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.match_status == MatchStatus.NEEDS_REVIEW
    assert refreshed.review_note == "ambiguous"
    assert (await session.execute(select(TravelPlace))).scalars().all() == []


async def test_apply_ambiguous_address_kind_not_autoconfirmed(session):
    # address 후보만 있는 ambiguous는 POI identity 검증 불가라 단일이어도 자동확정하지 않는다
    # (신규 장소 자동확정은 poi + 이름 게이트만 — G4/D2).
    candidate = await _make_candidate(session, name="부산역 국밥집", location_hint="부산")
    decision = GeocodeDecision(
        status="needs_review",
        candidate=None,
        confidence=0.5,
        reason="ambiguous",
        candidate_count=2,
        primary_candidates=[
            GeocodeCandidate(
                latitude=35.1151,
                longitude=129.0423,
                place_name="부산광역시 동구 중앙대로 206",
                road_address="부산광역시 동구 중앙대로 206",
                source="kakao",  # address kind → ambiguous 자동확정 제외
            ),
            GeocodeCandidate(
                latitude=37.5665,
                longitude=126.9780,
                place_name="서울특별시 중구 세종대로",
                road_address="서울특별시 중구 세종대로",
                source="kakao",
            ),
        ],
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)
    assert place is None
    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.match_status == MatchStatus.NEEDS_REVIEW
    assert refreshed.review_note == "ambiguous"
    assert (await session.execute(select(TravelPlace))).scalars().all() == []


async def test_apply_ambiguous_unrefined_echo_not_repromoted(session):
    # MAJOR 2: unrefined VWorld echo(coordinate)는 단건 vworld_unrefined_single 차단과 대칭으로
    # 다건(ambiguous)에서도 자동확정 제외. refined poi 1건과 섞여도 poi만 단일 통과해 확정된다.
    candidate = await _make_candidate(session, name="스타벅스 제주점", location_hint="제주")
    decision = GeocodeDecision(
        status="needs_review",
        candidate=None,
        confidence=0.5,
        reason="ambiguous",
        candidate_count=2,
        primary_candidates=[
            GeocodeCandidate(
                latitude=33.4996,
                longitude=126.5312,
                place_name="스타벅스 제주점",  # 질의 echo(정제 주소 아님)
                source="vworld",
                refined=False,  # → coordinate kind, 자동확정 제외
            ),
            GeocodeCandidate(
                latitude=33.4997,
                longitude=126.5313,
                place_name="스타벅스 제주점",
                road_address="제주특별자치도 제주시",
                source="kakao_keyword",  # refined poi, 이름 일치
            ),
        ],
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)
    # unrefined echo는 제외되고 refined poi 1건만 통과 → 자동확정.
    assert place is not None
    assert place.latitude == 33.4997
    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.match_status == MatchStatus.MATCHED


async def test_apply_ambiguous_all_unrefined_stays_review(session):
    # unrefined echo만 여럿이면(단건이면 vworld_unrefined_single) 다건에서도 자동확정 안 됨.
    candidate = await _make_candidate(session, name="스타벅스 제주점")
    decision = GeocodeDecision(
        status="needs_review",
        candidate=None,
        confidence=0.5,
        reason="ambiguous",
        candidate_count=2,
        primary_candidates=[
            GeocodeCandidate(
                latitude=33.4996,
                longitude=126.5312,
                place_name="스타벅스 제주점",
                source="vworld",
                refined=False,
            ),
            GeocodeCandidate(
                latitude=35.1796,
                longitude=129.0756,
                place_name="스타벅스 제주점",
                source="vworld",
                refined=False,
            ),
        ],
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)
    assert place is None
    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.match_status == MatchStatus.NEEDS_REVIEW
    assert refreshed.review_note == "ambiguous"


# --- T-167 auto-match audit 표본 ---


def test_audit_sample_fraction_is_deterministic_and_bounded():
    # 같은 id는 늘 같은 값(재현성), 값은 [0,1), id 없으면 경계 밖(1.0)이라 표본화되지 않는다.
    from ktc.etl.geocode_service import _audit_sample_fraction

    frac = _audit_sample_fraction(12345)
    assert frac == _audit_sample_fraction(12345)
    assert 0.0 <= frac < 1.0
    assert _audit_sample_fraction(None) == 1.0
    # 서로 다른 id는 (일반적으로) 다른 값 — 표본이 특정 id에 고정되지 않음.
    assert _audit_sample_fraction(1) != _audit_sample_fraction(2)


async def _matched_poi_decision(name="월정리 카페"):
    return GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(
            latitude=33.5563,
            longitude=126.7958,
            place_name=name,
            road_address="제주특별자치도 제주시",
            source="kakao_keyword",
        ),
        confidence=1.0,
        reason="single_result",
        candidate_count=1,
    )


async def test_auto_match_flags_audit_sample_when_rate_full(session, monkeypatch):
    # 표본율 1.0이면 자동확정 후보가 audit 표본으로 표시되되 MATCHED·export는 유지된다.
    monkeypatch.setattr(
        geocode_service.get_settings(), "AUTO_MATCH_AUDIT_SAMPLE_RATE", 1.0
    )
    candidate = await _make_candidate(session)
    place = await apply_geocode_to_candidate(
        session, candidate, await _matched_poi_decision()
    )
    assert place is not None
    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.match_status == MatchStatus.MATCHED
    assert refreshed.audit_status == AuditStatus.PENDING.value
    # 표본이라도 자동확정 상태·export는 그대로(사후 관측 — 노출 차단 아님).
    assert refreshed.feature_export_status == FeatureExportStatus.READY


async def test_auto_match_no_audit_sample_when_rate_zero(session, monkeypatch):
    monkeypatch.setattr(
        geocode_service.get_settings(), "AUTO_MATCH_AUDIT_SAMPLE_RATE", 0.0
    )
    candidate = await _make_candidate(session)
    place = await apply_geocode_to_candidate(
        session, candidate, await _matched_poi_decision()
    )
    assert place is not None
    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.match_status == MatchStatus.MATCHED
    assert refreshed.audit_status is None


async def test_needs_review_not_flagged_for_audit(session, monkeypatch):
    # 자동확정되지 않은(검수 큐) 후보는 표본율이 1.0이어도 audit 표본이 아니다.
    monkeypatch.setattr(
        geocode_service.get_settings(), "AUTO_MATCH_AUDIT_SAMPLE_RATE", 1.0
    )
    candidate = await _make_candidate(session)
    decision = GeocodeDecision("needs_review", None, 0.0, "no_result", 0)
    place = await apply_geocode_to_candidate(session, candidate, decision)
    assert place is None
    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.audit_status is None


# --- T-167 병합 반경 300m + 이름 게이트 결합 ---


async def test_merge_radius_reuses_place_up_to_300m(session):
    # 100m 밖·300m 안(~200m)의 같은 이름 기존 장소를 재사용한다(config 반경 300m).
    existing = TravelPlace(
        name="월정리 카페", latitude=33.5563, longitude=126.7958, is_geocoded=True
    )
    session.add(existing)
    await session.commit()
    await session.refresh(existing)

    candidate = await _make_candidate(session, name="월정리 카페")
    decision = GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(
            latitude=33.5581, longitude=126.7958  # ~약 200m 북쪽
        ),
        confidence=1.0,
        reason="single_result",
        candidate_count=1,
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)
    assert place.place_id == existing.place_id
    places = (await session.execute(select(TravelPlace))).scalars().all()
    assert len(places) == 1


async def test_merge_radius_name_mismatch_within_300m_blocks(session):
    # 300m 안이라도 이름 게이트가 불일치면 자동확정하지 않는다(반경 확대 ≠ 무검증 병합).
    existing = TravelPlace(
        name="월정리 카페", latitude=33.5563, longitude=126.7958, is_geocoded=True
    )
    session.add(existing)
    await session.commit()

    candidate = await _make_candidate(session, name="다른 식당")
    decision = GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(latitude=33.5581, longitude=126.7958),  # ~200m
        confidence=1.0,
        reason="single_result",
        candidate_count=1,
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)
    assert place is None
    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.match_status == MatchStatus.NEEDS_REVIEW
    assert refreshed.review_note == "nearby_place_name_mismatch"


async def test_apply_ambiguous_single_pass_still_blocked_by_grounding(session):
    # grounding 게이트(T-165)와 결합: ambiguous 단일 통과라도 transcript 후보가 raw grounding
    # 미확인이면 자동확정하지 않는다(grounding 실패면 identity 무관하게 차단).
    candidate = await _make_candidate(
        session, name="스타벅스 제주점", grounding_status=GroundingStatus.UNVERIFIED.value
    )
    decision = GeocodeDecision(
        status="needs_review",
        candidate=None,
        confidence=0.5,
        reason="ambiguous",
        candidate_count=2,
        primary_candidates=[
            GeocodeCandidate(
                latitude=33.4996,
                longitude=126.5312,
                place_name="스타벅스 제주점",
                source="kakao_keyword",
            ),
            GeocodeCandidate(
                latitude=35.1796,
                longitude=129.0756,
                place_name="스타벅스 부산점",
                source="kakao_keyword",
            ),
        ],
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)
    assert place is None
    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.match_status == MatchStatus.NEEDS_REVIEW
    assert refreshed.review_note == "ungrounded"


def _race_matched_decision() -> GeocodeDecision:
    """stale guard가 없으면 장소·매핑을 만드는 정상 자동확정 결과."""
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


async def test_apply_geocode_skips_stale_candidate_after_concurrent_ignore(
    session_factory,
):
    async with session_factory() as seed_session:
        candidate = await _make_candidate(seed_session)
        candidate_id = candidate.id

    # worker가 외부 provider를 기다리는 동안 들고 있던 stale ORM 객체를 재현한다.
    async with session_factory() as worker_session:
        stale_candidate = await worker_session.get(
            ExtractedPlaceCandidate, candidate_id
        )
        assert stale_candidate is not None

        async with session_factory() as reviewer_session:
            await place_service.resolve_candidate(
                reviewer_session,
                candidate_id=candidate_id,
                action="ignore",
                reviewed_by="concurrent-reviewer",
            )

        with pytest.raises(CandidateStateChangedError):
            await apply_geocode_to_candidate(
                worker_session, stale_candidate, _race_matched_decision()
            )
        assert stale_candidate.match_status == MatchStatus.IGNORED.value
        evidence = stale_candidate.provider_evidence_json or {}
        assert "geocoding" not in evidence
        assert evidence["review"]["resolutions"][-1]["action"] == "ignore"

    async with session_factory() as check_session:
        current = await check_session.get(ExtractedPlaceCandidate, candidate_id)
        assert current is not None
        assert current.match_status == MatchStatus.IGNORED.value
        assert current.feature_export_status == FeatureExportStatus.REJECTED.value
        assert current.matched_place_id is None
        assert (await check_session.execute(select(TravelPlace))).scalars().all() == []
        assert (
            await check_session.execute(select(VideoPlaceMapping))
        ).scalars().all() == []


async def test_apply_geocode_skips_stale_candidate_after_concurrent_delete(
    session_factory,
):
    async with session_factory() as seed_session:
        candidate = await _make_candidate(seed_session)
        candidate_id = candidate.id

    async with session_factory() as worker_session:
        stale_candidate = await worker_session.get(
            ExtractedPlaceCandidate, candidate_id
        )
        assert stale_candidate is not None

        async with session_factory() as delete_session:
            summary = await place_service.soft_delete_candidates(
                delete_session,
                [candidate_id],
                reason="concurrent reviewer delete",
                deleted_by="concurrent-reviewer",
                expected_status=MatchStatus.NEEDS_REVIEW,
            )
            assert summary.deleted_candidates == 1
            await delete_session.commit()

        with pytest.raises(CandidateStateChangedError):
            await apply_geocode_to_candidate(
                worker_session, stale_candidate, _race_matched_decision()
            )
        assert stale_candidate.deleted_at is not None
        assert stale_candidate.provider_evidence_json is None

    async with session_factory() as check_session:
        current = await check_session.get(ExtractedPlaceCandidate, candidate_id)
        assert current is not None
        assert current.deleted_at is not None
        assert current.match_status == MatchStatus.NEEDS_REVIEW.value
        assert current.matched_place_id is None
        assert (await check_session.execute(select(TravelPlace))).scalars().all() == []
        assert (
            await check_session.execute(select(VideoPlaceMapping))
        ).scalars().all() == []


async def test_admin_enrichment_exception_does_not_block_next_candidate(
    session,
    monkeypatch,
):
    first = await _make_candidate(session, name="월정리 카페")
    second = ExtractedPlaceCandidate(
        video_id=first.video_id,
        source_text="성산일출봉 카페",
        ai_place_name="성산일출봉 카페",
        candidate_category="카페",
        match_status=MatchStatus.NEEDS_REVIEW,
        source_kind=EvidenceSourceKind.TRANSCRIPT.value,
        grounding_status=GroundingStatus.VERIFIED_RAW.value,
        is_domestic=True,
    )
    session.add(second)
    await session.commit()
    await session.refresh(second)

    calls: list[int] = []

    async def fail_admin(_session_factory, place_id, **_kwargs):
        calls.append(place_id)
        raise RuntimeError("admin provider failed")

    monkeypatch.setattr(
        admin_region_service,
        "enrich_place_admin_codes_isolated",
        fail_admin,
    )

    first_place = await apply_geocode_to_candidate(
        session, first, _race_matched_decision()
    )
    assert first_place is not None
    assert second.ai_place_name == "성산일출봉 카페"

    second_place = await apply_geocode_to_candidate(
        session,
        second,
        GeocodeDecision(
            status="matched",
            candidate=GeocodeCandidate(
                latitude=33.4586,
                longitude=126.9423,
                place_name="성산일출봉 카페",
                road_address="제주특별자치도 서귀포시 성산읍",
                source="kakao_keyword",
            ),
            confidence=1.0,
            reason="single_result",
            candidate_count=1,
        ),
    )
    assert second_place is not None
    assert len(calls) == 2
    assert len((await session.execute(select(TravelPlace))).scalars().all()) == 2


async def test_post_enrichment_refresh_delete_race_becomes_typed_skip(
    session,
    monkeypatch,
):
    candidate = await _make_candidate(session)
    original_refresh = session.refresh

    async def fail_place_refresh(instance, *args, **kwargs):
        if isinstance(instance, TravelPlace):
            raise InvalidRequestError("place was concurrently deleted")
        return await original_refresh(instance, *args, **kwargs)

    monkeypatch.setattr(session, "refresh", fail_place_refresh)

    with pytest.raises(CandidateStateChangedError) as caught:
        await apply_geocode_to_candidate(
            session, candidate, _race_matched_decision()
        )

    assert caught.value.candidate_id == candidate.id
    assert session.in_transaction() is False
