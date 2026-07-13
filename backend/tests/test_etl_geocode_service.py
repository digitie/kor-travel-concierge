"""geocode_service 적용 로직 테스트 (DB 영속화)."""

from __future__ import annotations

import json

from sqlalchemy import select

from ktc.etl.geocode_service import _names_compatible, apply_geocode_to_candidate
from ktc.etl.geocoding import GeocodeCandidate, GeocodeDecision
from ktc.models import (
    EvidenceSourceKind,
    ExtractedPlaceCandidate,
    FeatureExportStatus,
    GroundingStatus,
    MatchStatus,
    TravelPlace,
    VideoPlaceMapping,
    YoutubeVideo,
)


async def _make_candidate(
    session,
    name="월정리 카페",
    category="카페",
    *,
    # 기본은 verified_raw로 둔다: 이 파일 대부분은 grounding이 아닌 매칭 로직을 검증하며
    # T-165 게이트에 걸리지 않아야 한다(자동확정 경로 회귀).
    grounding_status=GroundingStatus.VERIFIED_RAW.value,
    source_kind=EvidenceSourceKind.TRANSCRIPT.value,
):
    session.add(YoutubeVideo(video_id="v1", title="t", url="u", channel_id="c"))
    await session.commit()
    c = ExtractedPlaceCandidate(
        video_id="v1", source_text="s", ai_place_name=name, candidate_category=category,
        match_status=MatchStatus.NEEDS_REVIEW,
        source_kind=source_kind,
        grounding_status=grounding_status,
    )
    session.add(c)
    await session.commit()
    await session.refresh(c)
    return c


async def test_apply_matched_creates_place(session):
    candidate = await _make_candidate(session)
    decision = GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(
            latitude=33.5563, longitude=126.7958, road_address="제주 구좌읍 ...", source="kakao"
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

    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.match_status == MatchStatus.MATCHED
    assert refreshed.matched_place_id == place.place_id
    assert refreshed.reviewed_at is not None
    assert refreshed.feature_export_status == FeatureExportStatus.READY
    assert refreshed.provider_evidence_json["geocoding"]["decision"]["reason"] == "single_result"
    assert refreshed.provider_evidence_json["geocoding"]["selected_candidate"]["source"] == "kakao"
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
            latitude=33.5563, longitude=126.7958, road_address="제주 구좌읍", source="kakao"
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
        candidate=GeocodeCandidate(latitude=33.5563, longitude=126.7958, source="kakao"),
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
            latitude=33.5563, longitude=126.7958, road_address="제주 ...", source="kakao"
        ),
        confidence=1.0,
        reason="single_result",
        candidate_count=1,
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)
    assert place is not None
    refreshed = await session.get(ExtractedPlaceCandidate, candidate.id)
    assert refreshed.match_status == MatchStatus.MATCHED


def test_names_compatible_rejects_short_partial_names():
    assert _names_compatible("월정리 카페", "월정리카페")
    assert not _names_compatible("카페", "월정리카페")
    assert not _names_compatible("성산", "성산일출봉")


def test_names_compatible_allows_specific_contained_aliases():
    assert _names_compatible("월정리 카페", "월정리 카페 본점")
    assert _names_compatible("감천문화마을", "부산 감천문화마을")


async def test_apply_uses_vworld_for_address_enrichment(session):
    candidate = await _make_candidate(session)
    decision = GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(latitude=33.5563, longitude=126.7958),  # 주소 없음
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
