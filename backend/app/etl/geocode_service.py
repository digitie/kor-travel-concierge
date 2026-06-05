"""지오코딩 적용 오케스트레이션 (ETL 3단계).

매칭 후보(`extracted_place_candidates`)에 지오코딩 결과를 적용한다. 매칭에
성공하면 좌표 근접 중복을 확인해 기존 장소를 재사용하거나 새 `travel_places`를
만들고, VWorld 역지오코딩으로 주소를 보강한다. 실패·모호·낮은 신뢰도는
`needs_review`로 남긴다(`docs/architecture.md` 4.5, ADR-16).
"""

from __future__ import annotations

from app.etl.geocoding import (
    GeocodeDecision,
    KakaoGeocoder,
    NaverGeocoder,
    VWorldReverseGeocoder,
    evaluate_geocode,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ExtractedPlaceCandidate, MatchStatus, TravelPlace, utcnow
from app.services import place_service


async def geocode_query(
    query: str, *, kakao: KakaoGeocoder, naver: NaverGeocoder | None = None
) -> GeocodeDecision:
    """주소/장소명 문자열을 지오코딩하고 평가 결과를 반환한다."""
    kakao_results = await kakao.geocode(query)
    naver_results = await naver.geocode(query) if naver else []
    return evaluate_geocode(kakao_results, naver_results)


async def apply_geocode_to_candidate(
    session: AsyncSession,
    candidate: ExtractedPlaceCandidate,
    decision: GeocodeDecision,
    *,
    vworld: VWorldReverseGeocoder | None = None,
    reviewer: str = "system",
) -> TravelPlace | None:
    """평가 결과를 후보에 적용한다.

    matched면 중복 확인 후 장소를 확정(또는 재사용)하고, 그 외에는 `needs_review`로
    남긴다. 확정한 `TravelPlace`를 반환한다(미확정 시 None).
    """
    candidate.confidence_score = decision.confidence

    if decision.status != "matched" or decision.candidate is None:
        candidate.match_status = MatchStatus.NEEDS_REVIEW
        candidate.review_note = decision.reason
        await session.commit()
        return None

    c = decision.candidate

    # 좌표 근접 중복 확인 (T-005 저장소 계층 재사용)
    dups = await place_service.find_duplicate_candidates(
        session, lat=c.latitude, lng=c.longitude
    )
    if dups:
        place = dups[0][0]
    else:
        road, official = c.road_address, c.official_address
        if vworld is not None:
            rev = await vworld.reverse(c.latitude, c.longitude)
            road = road or rev.get("road_address")
            official = official or rev.get("parcel_address")
        place = TravelPlace(
            name=candidate.ai_place_name,
            latitude=c.latitude,
            longitude=c.longitude,
            road_address=road,
            official_address=official,
            category=candidate.candidate_category,
            api_source=c.source,
            is_geocoded=True,
        )
        session.add(place)
        await session.flush()

    candidate.match_status = MatchStatus.MATCHED
    candidate.matched_place_id = place.place_id
    candidate.reviewed_by = reviewer
    candidate.reviewed_at = utcnow()
    await session.commit()
    await session.refresh(place)
    return place
