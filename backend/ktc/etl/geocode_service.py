"""지오코딩 적용 오케스트레이션 (ETL 3단계).

매칭 후보(`extracted_place_candidates`)에 지오코딩 결과를 적용한다. 매칭에
성공하면 좌표 근접 중복을 확인해 기존 장소를 재사용하거나 새 `travel_places`를
만들고, VWorld 역지오코딩으로 주소를 보강한다. 실패·모호·낮은 신뢰도는
`needs_review`로 남긴다(`docs/architecture.md` 4.5, ADR-16).
"""

from __future__ import annotations

import hashlib

from sqlalchemy.ext.asyncio import AsyncSession
from vworld import AsyncVworldClient

from ktc.core.config import get_settings
from ktc.core.spatial import sync_place_geometry
from ktc.etl import category_catalog, region_gate
from ktc.etl.geocoding import (
    GeocodeCandidate,
    GeocodeDecision,
    GeocodeResultKind,
    KakaoGeocoder,
    NaverGeocoder,
    evaluate_geocode,
    geocode_with_vworld,
    reverse_with_vworld,
)
from ktc.etl.place_name import names_match as _names_match
from ktc.models import (
    AuditStatus,
    EvidenceSourceKind,
    ExtractedPlaceCandidate,
    FeatureExportStatus,
    GroundingStatus,
    MatchStatus,
    TravelPlace,
    utcnow,
)
from ktc.services import place_service


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

    # description 단독 후보(T-168, 로드맵 PR-17, §1.3 D1): 자막 실패 fallback으로 생성된
    # recall 경로 후보다. 자막보다 근거가 약하므로 T-165/166 게이트 통과 여부와 무관하게
    # **자동확정하지 않는다** — 지오코딩은 수행해 좌표·주소 후보를 검수 참고용 evidence로
    # 남기되 상태는 needs_review로 고정한다. queue_reason은 파생 로직이 source_kind=
    # 'description'을 description_only로(지오코딩 사유가 있으면 그 사유로) 처리한다(T-182).
    if candidate.source_kind == EvidenceSourceKind.DESCRIPTION.value:
        candidate.provider_evidence_json = _merge_provider_evidence(
            candidate.provider_evidence_json,
            geocoding=_geocode_evidence(
                decision, selected_candidate=decision.candidate
            ),
        )
        candidate.match_status = MatchStatus.NEEDS_REVIEW
        candidate.review_note = "description_only"
        candidate.feature_export_status = FeatureExportStatus.PENDING.value
        await session.commit()
        return None

    candidate.provider_evidence_json = _merge_provider_evidence(
        candidate.provider_evidence_json,
        geocoding=_geocode_evidence(decision),
    )

    # 확정 후보와 confidence를 정한다. 단일 matched는 그대로 쓰고, 다건(ambiguous)은
    # 이름·행정구역 게이트를 모두 통과하는 후보가 정확히 1개면 0.7로 자동확정한다
    # (검수량 감소, ADR-16 보강 — 무게이트 자동확정은 여전히 금지). 그 외 상태는 검수 큐로.
    c = decision.candidate
    confidence = decision.confidence
    ambiguous_single_pass = False
    if decision.status != "matched" or c is None:
        resolved = (
            _resolve_ambiguous_single(candidate, decision)
            if decision.reason == "ambiguous"
            else None
        )
        if resolved is None:
            candidate.match_status = MatchStatus.NEEDS_REVIEW
            candidate.review_note = decision.reason
            candidate.feature_export_status = FeatureExportStatus.PENDING.value
            await session.commit()
            return None
        c = resolved
        confidence = 0.7
        ambiguous_single_pass = True
    candidate.confidence_score = confidence

    # raw grounding 게이트(T-165, 로드맵 B3·G4): transcript 후보는 근거가 raw 자막에서
    # 확인(verified_raw)되지 않으면 지오코딩이 matched여도 자동확정하지 않는다. 그럴듯한
    # hallucination이 자동 승격돼 downstream(export)까지 전파되는 것을 막는다. 후보는
    # 폐기하지 않고 needs_review로 남긴다.
    if _grounding_blocks_autoconfirm(candidate):
        candidate.provider_evidence_json = _merge_provider_evidence(
            candidate.provider_evidence_json,
            geocoding=_geocode_evidence(decision, selected_candidate=c),
        )
        candidate.match_status = MatchStatus.NEEDS_REVIEW
        candidate.review_note = "ungrounded"
        candidate.feature_export_status = FeatureExportStatus.PENDING.value
        await session.commit()
        return None

    result_kind = c.result_kind or GeocodeResultKind.ADDRESS.value

    # 좌표 근접 중복 확인 (T-005 저장소 계층 재사용). 병합 반경은 config 상수(기본 300m)로
    # 둔다(T-167, 로드맵 PR-14 절차 3). 이 근접 재사용은 아래 identity 게이트가 후보 AI명과
    # 기존 장소명을 대조하므로(이름 불일치 시 needs_review) 반경 확대가 오병합을 늘리지 않는다
    # (무검증 반경 확대 금지 원칙과 정합 — T-166 이름 게이트 통과 후에만 재사용).
    dups = await place_service.find_duplicate_candidates(
        session,
        lat=c.latitude,
        lng=c.longitude,
        radius_meters=get_settings().GEOCODE_MERGE_RADIUS_METERS,
    )
    nearby_place = dups[0][0] if dups else None

    # identity 게이트(이름·행정구역·is_domestic). 불리언 게이트 통과 여부만 쓰고 가중 합성
    # 점수는 만들지 않는다(§2.4-4, 가짜 정밀도 방지). 결과 코드는 evidence.geocoding.identity
    # 에 누적해 PR-07 queue_reason 파생(review_note 기반)과 T-167 auto-match audit에서
    # 재사용한다. grounding·이름·행정구역·is_domestic이 전부 통과해야 MATCHED가 된다.
    identity, block_note = _evaluate_identity_gates(
        candidate, c, result_kind, nearby_place
    )
    if ambiguous_single_pass:
        identity["ambiguous_single_pass"] = True
    candidate.provider_evidence_json = _merge_provider_evidence(
        candidate.provider_evidence_json,
        geocoding=_geocode_evidence(decision, selected_candidate=c, identity=identity),
    )
    if block_note is not None:
        candidate.match_status = MatchStatus.NEEDS_REVIEW
        candidate.review_note = block_note
        candidate.feature_export_status = FeatureExportStatus.PENDING.value
        await session.commit()
        return None

    if nearby_place is not None:
        place = nearby_place
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
                geocoding=_geocode_evidence(
                    decision,
                    selected_candidate=c,
                    reverse_vworld=rev,
                    identity=identity,
                ),
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
    # auto-match audit 표본 표시(T-167, G9). MATCHED·export 상태는 그대로 두고(사후 관측 —
    # 노출 차단 아님) 자동확정 정밀도(오확정률) 측정용 표본만 남긴다.
    _maybe_flag_audit_sample(candidate, reviewer)

    await place_service.ensure_candidate_mapping(session, candidate, place)
    await sync_place_geometry(session, place.place_id, place.latitude, place.longitude)
    from ktc.etl import admin_region_service

    await admin_region_service.enrich_place_admin_codes(session, place)
    await session.commit()
    await session.refresh(place)
    return place


def _grounding_blocks_autoconfirm(candidate: ExtractedPlaceCandidate) -> bool:
    """transcript 후보의 근거가 raw 자막에서 확인되지 않으면 자동확정을 막는다(T-165, G4).

    transcript source_kind만 대상이다(description/visual은 각자의 grounding 규칙 — 후속
    T-168/T-173에서 not_applicable로 둔다). LLM 자가 보고 confidence는 이 판단에 절대
    쓰지 않는다(§2.4 가짜 정밀도 방지). legacy_unknown(재처리 전 기존 후보)도 verified가
    아니므로 자동확정은 막되, 사람 검수는 허용된다(needs_review로만 남긴다).
    """
    if candidate.source_kind != EvidenceSourceKind.TRANSCRIPT.value:
        return False
    return candidate.grounding_status != GroundingStatus.VERIFIED_RAW.value


def _maybe_flag_audit_sample(
    candidate: ExtractedPlaceCandidate, reviewer: str
) -> None:
    """자동확정된 후보를 확률적으로 auto-match audit 표본으로 표시한다(T-167, G9).

    자동확정(MATCHED, reviewer="system")은 검수 큐에서 사라져 정밀도(뒤집힘 비율)를 잴
    표본이 없다(§7 지표). `AUTO_MATCH_AUDIT_SAMPLE_RATE`(기본 0.1) 비율로 표본을 남겨
    사람이 사후에 "정확/오확정"을 기록할 수 있게 한다. 표본 표시는 상태 전이가 아니라
    사후 관측이므로 MATCHED·export 상태는 건드리지 않는다. rate<=0이면 비활성, rate>=1이면
    전량. 이미 표시된 후보(재처리)는 유지한다(멱등).

    표본 선택은 `candidate.id` 해시 기반 **결정적** 판정이다(전역 random 미사용). 같은
    후보는 재현 가능하게 늘 같은 결정을 받아 테스트·재처리에서 안정적이고, id 해시가 rate에
    고르게 분포해 표본율을 근사한다.
    """
    if reviewer != "system":
        return
    if candidate.audit_status is not None:
        return
    rate = get_settings().AUTO_MATCH_AUDIT_SAMPLE_RATE
    if rate <= 0:
        return
    if rate >= 1 or _audit_sample_fraction(candidate.id) < rate:
        candidate.audit_status = AuditStatus.PENDING.value


def _audit_sample_fraction(candidate_id: int | None) -> float:
    """`candidate.id`를 [0,1) 구간의 결정적 값으로 매핑한다(sha256 기반, 균등 분포).

    id가 아직 없으면(비영속) 표본화하지 않도록 1.0(=경계 밖)을 반환한다.
    """
    if candidate_id is None:
        return 1.0
    digest = hashlib.sha256(str(candidate_id).encode("utf-8")).hexdigest()
    return (int(digest[:16], 16) % 1_000_000) / 1_000_000


def _evaluate_identity_gates(
    candidate: ExtractedPlaceCandidate,
    geocode: GeocodeCandidate,
    result_kind: str,
    nearby_place: TravelPlace | None,
) -> tuple[dict, str | None]:
    """이름·행정구역·is_domestic 게이트를 평가한다(로드맵 PR-12, D2·D4·D7).

    (identity 요약 dict, 차단 사유 코드 or None)을 반환한다. 불리언 게이트만 쓰고 가중
    합성 점수는 만들지 않는다(§2.4-4). 차단 우선순위는 이름 > 행정구역 > is_domestic이며
    (queue_reason 선언 순서와 정합), 모든 게이트 결과는 차단 여부와 무관하게 기록한다.
    """
    identity: dict = {
        "result_kind": result_kind,
        "reused_nearby_place": nearby_place is not None,
    }
    block: str | None = None

    # 1) 이름 게이트 (D2/C8) — 비교 목적별 pairwise. any-pair(C8) 문제를 제거한다.
    if nearby_place is not None:
        # 근접 중복 재사용: 후보 AI명 vs 기존 확정 장소명(둘 다 신뢰 POI명).
        if _names_match(candidate.ai_place_name, nearby_place.name):
            identity["name_gate"] = "nearby_match"
        else:
            identity["name_gate"] = "nearby_place_name_mismatch"
            block = block or "nearby_place_name_mismatch"
    elif result_kind == GeocodeResultKind.POI.value:
        # 신규 장소 생성 경로(D2): 후보 AI명 vs provider POI명. 이전엔 무검증 통과였다.
        if _names_match(candidate.ai_place_name, geocode.place_name):
            identity["name_gate"] = "poi_match"
        else:
            identity["name_gate"] = "name_mismatch"
            block = block or "name_mismatch"
    else:
        # 신규 장소 + 주소·좌표 결과(D2·G4): place_name이 POI명이 아니라 POI identity를
        # 검증할 수 없다 → 자동확정 금지(needs_review). 신규 장소 자동확정 허용 경로는
        # (a) result_kind=poi ∧ 이름 게이트 통과, (b) 근접 중복 재사용(위 분기, 기존
        # 장소명 대조) 둘뿐이다. 근접 재사용은 kind와 무관하게 기존명으로 검증되므로
        # 여기(nearby is None)에 도달하지 않는다.
        identity["name_gate"] = "name_unverified"
        block = block or "name_unverified"

    # 2) 행정구역 게이트 (D4) — hint 시도 vs 확정 주소 시도(역지오코딩 추가 호출 없음).
    if region_gate.region_conflict(
        candidate.location_hint, *_result_address_texts(geocode, result_kind)
    ):
        identity["region_gate"] = "region_mismatch"
        block = block or "region_mismatch"
    elif region_gate.sido_of(candidate.location_hint) is not None:
        identity["region_gate"] = "region_match"
    else:
        identity["region_gate"] = "region_no_signal"

    # 3) is_domestic fail-closed (D7) — 미확인(None)·해외(False)는 자동확정 금지. 명시적
    #    True만 통과한다(해외 장소가 국내 지오코딩으로 자동확정되는 FP 차단).
    if candidate.is_domestic is True:
        identity["is_domestic_gate"] = "verified"
    else:
        identity["is_domestic_gate"] = "unverified"
        block = block or "domestic_unverified"

    return identity, block


def _result_address_texts(
    geocode: GeocodeCandidate, result_kind: str
) -> list[str | None]:
    """행정구역 게이트에 넘길 확정 주소 문자열. poi 결과의 place_name은 POI명이라 제외."""
    texts: list[str | None] = [geocode.road_address, geocode.official_address]
    if result_kind != GeocodeResultKind.POI.value:
        texts.append(geocode.place_name)
    return texts


def _resolve_ambiguous_single(
    candidate: ExtractedPlaceCandidate, decision: GeocodeDecision
) -> GeocodeCandidate | None:
    """다건(ambiguous) 결과에서 POI identity가 검증되는 후보가 정확히 1개면 반환한다
    (ADR-16 보강). 신규 장소 자동확정은 POI 검증을 요구하므로 refined poi 결과 + 이름
    게이트 통과 후보만 대상이다(address·coordinate·unrefined 제외). is_domestic·grounding은
    후보 단위 공통 신호라 여기서 보지 않고 호출부의 게이트가 처리한다."""
    passed: list[GeocodeCandidate] = []
    for cand in decision.primary_candidates:
        # unrefined VWorld echo(coordinate)는 단건 vworld_unrefined_single 차단과 대칭으로
        # 제외한다(다건이면 재승격되던 구멍 차단, MAJOR 2).
        if not getattr(cand, "refined", True):
            continue
        rk = cand.result_kind or GeocodeResultKind.ADDRESS.value
        # 신규 장소 자동확정은 POI identity 검증을 요구한다(G4/D2). address·coordinate
        # 결과는 place_name이 POI명이 아니라 검증 불가이므로 ambiguous 단일 통과 대상에서
        # 제외한다(poi + 이름 게이트 통과 후보만). 근접 중복 재사용은 이후 공통 경로가
        # 기존 장소명 대조로 별도 처리한다.
        if rk != GeocodeResultKind.POI.value:
            continue
        if not _names_match(candidate.ai_place_name, cand.place_name):
            continue
        if region_gate.region_conflict(
            candidate.location_hint, *_result_address_texts(cand, rk)
        ):
            continue
        passed.append(cand)
    return passed[0] if len(passed) == 1 else None


def _geocode_evidence(
    decision: GeocodeDecision,
    *,
    selected_candidate: GeocodeCandidate | None = None,
    reverse_vworld: dict[str, str | None] | None = None,
    identity: dict | None = None,
) -> dict:
    # 실제로 확정에 쓴 후보를 우선 기록한다(ambiguous 단일 통과 시 decision.candidate는
    # None이므로 선택된 후보를 명시로 넘긴다).
    chosen = selected_candidate if selected_candidate is not None else decision.candidate
    selected = None
    if chosen is not None:
        selected = {
            "source": chosen.source,
            "result_kind": chosen.result_kind,
            "place_name": chosen.place_name,
            "road_address": chosen.road_address,
            "official_address": chosen.official_address,
            "category": chosen.category,
            "latitude": chosen.latitude,
            "longitude": chosen.longitude,
        }
    evidence: dict = {
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
    if identity is not None:
        evidence["identity"] = identity
    return evidence


def _merge_provider_evidence(
    existing: dict | None,
    *,
    geocoding: dict,
) -> dict:
    merged = dict(existing or {})
    merged["geocoding"] = geocoding
    return merged
