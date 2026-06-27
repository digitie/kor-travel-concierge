"""지오코딩 적용 오케스트레이션 (ETL 3단계).

매칭 후보(`extracted_place_candidates`)에 지오코딩 결과를 적용한다. 매칭에
성공하면 좌표 근접 중복을 확인해 기존 장소를 재사용하거나 새 `travel_places`를
만들고, VWorld 역지오코딩으로 주소를 보강한다. 실패·모호·낮은 신뢰도는
`needs_review`로 남긴다(`docs/architecture.md` 4.5, ADR-16).
"""

from __future__ import annotations

from ktc.core.spatial import sync_place_geometry
from ktc.etl.geocoding import (
    GeocodeDecision,
    KakaoGeocoder,
    NaverGeocoder,
    evaluate_geocode,
    geocode_with_vworld,
    reverse_with_vworld,
)
from sqlalchemy.ext.asyncio import AsyncSession
from vworld import AsyncVworldClient

from ktc.models import (
    ExtractedPlaceCandidate,
    FeatureExportStatus,
    MatchStatus,
    TravelPlace,
    utcnow,
)
from ktc.services import place_service
from ktc.etl import category_catalog

_MIN_CONTAINED_NAME_LENGTH = 4
_MIN_CONTAINED_NAME_RATIO = 0.6


async def geocode_query(
    query: str,
    *,
    vworld: AsyncVworldClient | None = None,
    kakao: KakaoGeocoder | None = None,
    naver: NaverGeocoder | None = None,
) -> GeocodeDecision:
    """주소/장소명 문자열을 지오코딩하고 평가 결과를 반환한다."""
    vworld_results = []
    if vworld is not None:
        vworld_results = await geocode_with_vworld(vworld, query)
        if vworld_results:
            kakao_results = []
            if kakao is not None and len(vworld_results) > 1:
                try:
                    kakao_results = await kakao.geocode(query)
                except Exception:
                    kakao_results = []
            return evaluate_geocode(
                vworld_results,
                kakao_results,
                secondary_name="kakao",
            )

    if kakao is not None:
        try:
            kakao_results = await kakao.geocode(query)
        except Exception:
            kakao_results = []
        naver_results = []
        if naver is not None and (not kakao_results or len(kakao_results) > 1):
            try:
                naver_results = await naver.geocode(query)
            except Exception:
                naver_results = []
        if kakao_results:
            return evaluate_geocode(kakao_results, naver_results, secondary_name="naver")
        if naver_results:
            return evaluate_geocode(naver_results)

    if naver is not None:
        try:
            naver_results = await naver.geocode(query)
        except Exception:
            naver_results = []
        return evaluate_geocode(naver_results)

    return evaluate_geocode([])


async def apply_geocode_to_candidate(
    session: AsyncSession,
    candidate: ExtractedPlaceCandidate,
    decision: GeocodeDecision,
    *,
    vworld: AsyncVworldClient | None = None,
    reviewer: str = "system",
) -> TravelPlace | None:
    """평가 결과를 후보에 적용한다.

    matched면 중복 확인 후 장소를 확정(또는 재사용)하고, 그 외에는 `needs_review`로
    남긴다. 확정한 `TravelPlace`를 반환한다(미확정 시 None). 8자리 category 코드는
    POI 추출 때 후보 evidence에 저장된 값을 복사한다(별도 Gemini 호출 없음, A안).
    """
    candidate.confidence_score = decision.confidence
    candidate.provider_evidence_json = _merge_provider_evidence(
        candidate.provider_evidence_json,
        geocoding=_geocode_evidence(decision),
    )

    if decision.status != "matched" or decision.candidate is None:
        candidate.match_status = MatchStatus.NEEDS_REVIEW
        candidate.review_note = decision.reason
        candidate.feature_export_status = FeatureExportStatus.PENDING.value
        await session.commit()
        return None

    c = decision.candidate

    # 좌표 근접 중복 확인 (T-005 저장소 계층 재사용)
    dups = await place_service.find_duplicate_candidates(
        session, lat=c.latitude, lng=c.longitude
    )
    if dups:
        place = dups[0][0]
        if not _names_compatible(
            candidate.ai_place_name,
            place.name,
            c.place_name,
        ):
            candidate.match_status = MatchStatus.NEEDS_REVIEW
            candidate.review_note = "nearby_place_name_mismatch"
            candidate.feature_export_status = FeatureExportStatus.PENDING.value
            await session.commit()
            return None
        code = place_service.candidate_category_code(candidate)
        if code and place.category_code_suggestion in (
            None,
            category_catalog.UNKNOWN_CATEGORY_CODE,
        ):
            place.category_code_suggestion = code
            place.category = category_catalog.label_for_or_unknown(code)
    else:
        road, official = c.road_address, c.official_address
        if vworld is not None:
            rev = await reverse_with_vworld(vworld, c.latitude, c.longitude)
            road = road or rev.get("road_address")
            official = official or rev.get("parcel_address")
            candidate.provider_evidence_json = _merge_provider_evidence(
                candidate.provider_evidence_json,
                geocoding=_geocode_evidence(decision, reverse_vworld=rev),
            )
        code = place_service.candidate_category_code(candidate)
        category_code = category_catalog.normalize_code_or_unknown(code)
        place = TravelPlace(
            name=candidate.ai_place_name,
            latitude=c.latitude,
            longitude=c.longitude,
            road_address=road,
            official_address=official,
            category=category_catalog.label_for_or_unknown(category_code),
            category_code_suggestion=category_code,
            api_source=c.source,
            is_geocoded=True,
        )
        session.add(place)
        await session.flush()

    candidate.match_status = MatchStatus.MATCHED
    candidate.matched_place_id = place.place_id
    candidate.reviewed_by = reviewer
    candidate.reviewed_at = utcnow()
    candidate.feature_export_status = FeatureExportStatus.READY.value

    await place_service.ensure_candidate_mapping(session, candidate, place)
    await sync_place_geometry(session, place.place_id, place.latitude, place.longitude)
    from ktc.etl import admin_region_service

    await admin_region_service.enrich_place_admin_codes(session, place)
    await session.commit()
    await session.refresh(place)
    return place


def _names_compatible(*values: str | None) -> bool:
    normalized = [_normalize_name(value) for value in values if value]
    for index, left in enumerate(normalized):
        for right in normalized[index + 1 :]:
            if left == right:
                return True
            if _is_specific_contained_name(left, right):
                return True
    return False


def _is_specific_contained_name(left: str, right: str) -> bool:
    if left not in right and right not in left:
        return False
    shorter, longer = sorted((left, right), key=len)
    return (
        len(shorter) >= _MIN_CONTAINED_NAME_LENGTH
        and len(shorter) / len(longer) >= _MIN_CONTAINED_NAME_RATIO
    )


def _normalize_name(value: str | None) -> str:
    return "".join((value or "").casefold().split())


def _geocode_evidence(
    decision: GeocodeDecision,
    *,
    reverse_vworld: dict[str, str | None] | None = None,
) -> dict:
    selected = None
    if decision.candidate is not None:
        selected = {
            "source": decision.candidate.source,
            "place_name": decision.candidate.place_name,
            "road_address": decision.candidate.road_address,
            "official_address": decision.candidate.official_address,
            "category": decision.candidate.category,
            "latitude": decision.candidate.latitude,
            "longitude": decision.candidate.longitude,
        }
    return {
        "decision": {
            "status": decision.status,
            "confidence": decision.confidence,
            "reason": decision.reason,
            "candidate_count": decision.candidate_count,
        },
        "selected_candidate": selected,
        "provider_candidates": decision.provider_evidence,
        "reverse_vworld": reverse_vworld,
    }


def _merge_provider_evidence(
    existing: dict | None,
    *,
    geocoding: dict,
) -> dict:
    merged = dict(existing or {})
    merged["geocoding"] = geocoding
    return merged
