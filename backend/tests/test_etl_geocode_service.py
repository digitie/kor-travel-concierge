"""geocode_service 적용 로직 테스트 (DB 영속화)."""

from __future__ import annotations

from sqlalchemy import select

from app.etl.geocode_service import _names_compatible, apply_geocode_to_candidate
from app.etl.geocoding import GeocodeCandidate, GeocodeDecision
from app.models import (
    ExtractedPlaceCandidate,
    FeatureExportStatus,
    MatchStatus,
    TravelPlace,
    VideoPlaceMapping,
    YoutubeVideo,
)


async def _make_candidate(session, name="월정리 카페", category="카페"):
    session.add(YoutubeVideo(video_id="v1", title="t", url="u", channel_id="c"))
    await session.commit()
    c = ExtractedPlaceCandidate(
        video_id="v1", source_text="s", ai_place_name=name, candidate_category=category,
        match_status=MatchStatus.NEEDS_REVIEW,
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
