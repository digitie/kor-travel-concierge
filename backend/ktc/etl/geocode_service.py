"""지오코딩 적용 오케스트레이션 (ETL 3단계).

매칭 후보(`extracted_place_candidates`)에 지오코딩 결과를 적용한다. 매칭에
성공하면 좌표 근접 중복을 확인해 기존 장소를 재사용하거나 새 `travel_places`를
만들고, VWorld 역지오코딩으로 주소를 보강한다. 실패·모호·낮은 신뢰도는
`needs_review`로 남긴다(`docs/architecture.md` 4.5, ADR-16).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import BigInteger, literal_column, select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm.exc import ObjectDeletedError
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
    VideoPlaceMapping,
    utcnow,
)
from ktc.services import place_service

_CANDIDATE_XMIN = literal_column(
    "extracted_place_candidates.xmin::text::bigint",
    type_=BigInteger,
)
_PLACE_XMIN = literal_column("travel_places.xmin::text::bigint", type_=BigInteger)


@dataclass(frozen=True)
class CandidateGeocodeSnapshot:
    """외부 provider 호출 직전 후보의 PostgreSQL row version과 적용 가능 상태."""

    version: int
    match_status: str
    deleted: bool

    @property
    def eligible(self) -> bool:
        return not self.deleted and self.match_status == MatchStatus.NEEDS_REVIEW.value


@dataclass(frozen=True)
class PlaceAddressSnapshot:
    """늦은 reverse 응답을 조건부 적용하기 위한 장소 row snapshot."""

    place_id: int
    version: int
    latitude: float
    longitude: float
    road_address: str | None
    official_address: str | None


def _place_address_snapshot(place: TravelPlace, version: int) -> PlaceAddressSnapshot:
    return PlaceAddressSnapshot(
        place_id=place.place_id,
        version=version,
        latitude=place.latitude,
        longitude=place.longitude,
        road_address=place.road_address,
        official_address=place.official_address,
    )


class CandidateStateChangedError(RuntimeError):
    """외부 지오코딩 중 후보가 사용자 작업으로 더 이상 적용 가능하지 않음."""

    def __init__(
        self,
        candidate_id: int,
        *,
        expected_version: int | None = None,
        current_version: int | None = None,
    ) -> None:
        self.candidate_id = candidate_id
        self.expected_version = expected_version
        self.current_version = current_version
        super().__init__(f"candidate {candidate_id} state changed during geocoding")


async def read_candidate_geocode_snapshot(
    session: AsyncSession, candidate_id: int
) -> CandidateGeocodeSnapshot | None:
    """후보와 PostgreSQL xmin을 함께 읽어 외부 호출 전 version snapshot을 만든다."""
    row = (
        await session.execute(
            select(ExtractedPlaceCandidate, _CANDIDATE_XMIN)
            .where(ExtractedPlaceCandidate.id == candidate_id)
            .execution_options(populate_existing=True, autoflush=False)
        )
    ).one_or_none()
    if row is None:
        return None
    candidate, version = row
    return CandidateGeocodeSnapshot(
        version=int(version),
        match_status=str(candidate.match_status),
        deleted=candidate.deleted_at is not None,
    )


async def _lock_current_candidate_for_geocode(
    session: AsyncSession, candidate_id: int
) -> tuple[ExtractedPlaceCandidate | None, int | None]:
    """외부 지오코딩 뒤 최신 후보를 잠그고 identity map의 stale 값을 교체한다."""
    row = (
        await session.execute(
            select(ExtractedPlaceCandidate, _CANDIDATE_XMIN)
            .where(ExtractedPlaceCandidate.id == candidate_id)
            .with_for_update()
            .execution_options(populate_existing=True, autoflush=False)
        )
    ).one_or_none()
    if row is None:
        return None, None
    candidate, version = row
    return candidate, int(version)


async def candidate_geocode_snapshot_is_current(
    session: AsyncSession,
    candidate_id: int,
    expected_version: int,
) -> bool:
    """provider 없음 집계 직전 후보를 잠깐 잠가 version/상태가 그대로인지 확인한다."""
    current, current_version = await _lock_current_candidate_for_geocode(
        session, candidate_id
    )
    is_current = (
        current is not None
        and current.deleted_at is None
        and current.match_status == MatchStatus.NEEDS_REVIEW.value
        and current_version == expected_version
    )
    await session.commit()
    return is_current


async def _lock_committed_candidate_mappings_for_geocode(
    session: AsyncSession,
    *,
    candidate_id: int,
    place_id: int,
    expected_candidate_version: int,
) -> tuple[ExtractedPlaceCandidate, list[VideoPlaceMapping]]:
    """post-core 외부 보강 뒤 후보·매핑 연결이 여전히 유효한지 잠가 확인한다.

    audit 표본 필드처럼 연결 의미를 바꾸지 않는 후보 갱신은 허용한다. 반대로 영상
    강제 제외·장소 삭제·수동 재해결로 후보 상태 또는 매핑이 달라졌으면 사용자 결정을
    보존하고 typed skip으로 전환한다. DB unique 제약이 없는 legacy 중복 매핑은 모두
    같은 후보·영상·장소를 가리킬 때만 함께 유효한 연결로 인정한다.
    """
    current, current_version = await _lock_current_candidate_for_geocode(
        session, candidate_id
    )
    mappings: list[VideoPlaceMapping] = []
    if (
        current is not None
        and current.deleted_at is None
        and current.match_status == MatchStatus.MATCHED.value
        and current.matched_place_id == place_id
    ):
        mappings = list(
            (
                await session.execute(
                    select(VideoPlaceMapping)
                    .where(VideoPlaceMapping.place_candidate_id == candidate_id)
                    .order_by(VideoPlaceMapping.id.asc())
                    .with_for_update()
                    .execution_options(populate_existing=True, autoflush=False)
                )
            )
            .scalars()
            .all()
        )
    mappings_are_current = (
        current is not None
        and bool(mappings)
        and all(
            mapping.place_candidate_id == current.id
            and mapping.video_id == current.video_id
            and mapping.place_id == place_id
            for mapping in mappings
        )
    )
    if (
        current is None
        or current.deleted_at is not None
        or current.match_status != MatchStatus.MATCHED.value
        or current.matched_place_id != place_id
        or not mappings_are_current
    ):
        await session.commit()
        raise CandidateStateChangedError(
            candidate_id,
            expected_version=expected_candidate_version,
            current_version=current_version,
        )
    return current, mappings


def _select_geocode_candidate(
    candidate: ExtractedPlaceCandidate,
    decision: GeocodeDecision,
) -> tuple[GeocodeCandidate | None, float, bool]:
    """확정 검토 대상, 적용 confidence, ambiguous 단일 통과 여부를 계산한다."""
    if decision.status == "matched" and decision.candidate is not None:
        return decision.candidate, decision.confidence, False
    resolved = (
        _resolve_ambiguous_single(candidate, decision)
        if decision.reason == "ambiguous"
        else None
    )
    if resolved is None:
        return None, decision.confidence, False
    return resolved, 0.7, True


async def _prepare_reverse_vworld(
    session: AsyncSession,
    candidate: ExtractedPlaceCandidate,
    decision: GeocodeDecision,
    vworld: AsyncVworldClient | None,
) -> tuple[bool, tuple[float, float] | None, dict[str, str | None] | None]:
    """row lock 전에 필요한 VWorld 역지오코딩을 준비한다.

    stale snapshot으로 자동확정 가능성이 있는 신규 장소만 선조회한다. lock 뒤 최신 후보로
    모든 gate와 근접 중복을 다시 평가하며, 선택 좌표가 달라졌으면 이 결과를 버린다.
    """
    # description fallback은 forward geocode 결과만 검수 evidence로 남기고 어떤 경우에도
    # 자동확정하지 않는다(T-168). 뒤의 확정 가능성 preflight가 불필요한 reverse HTTP를
    # 먼저 실행하지 않도록 여기서 명시적으로 제외한다.
    if (
        vworld is None
        or candidate.source_kind == EvidenceSourceKind.DESCRIPTION.value
    ):
        return False, None, None
    selected, _, _ = _select_geocode_candidate(candidate, decision)
    if selected is None or _grounding_blocks_autoconfirm(candidate):
        return False, None, None
    duplicates = await place_service.find_duplicate_candidates(
        session,
        lat=selected.latitude,
        lng=selected.longitude,
        radius_meters=get_settings().GEOCODE_MERGE_RADIUS_METERS,
    )
    nearby_place = duplicates[0][0] if duplicates else None
    result_kind = selected.result_kind or GeocodeResultKind.ADDRESS.value
    _, block_note = _evaluate_identity_gates(
        candidate, selected, result_kind, nearby_place
    )
    if nearby_place is not None or block_note is not None:
        return False, None, None
    # 근접 중복 SELECT가 연 transaction/connection을 외부 HTTP 대기 동안 점유하지 않는다.
    # apply 함수는 원래 모든 결과 경로의 commit을 소유하므로 transaction 계약은 같다.
    await session.commit()
    reverse = await reverse_with_vworld(
        vworld, selected.latitude, selected.longitude
    )
    return True, (selected.latitude, selected.longitude), reverse


async def _enrich_missing_addresses_isolated(
    session_factory: async_sessionmaker[AsyncSession],
    place_id: int,
    vworld: AsyncVworldClient,
) -> dict[str, str | None] | None:
    """DB transaction 밖에서 reverse 후 실제 적용한 주소 payload를 반환한다."""
    try:
        async with session_factory() as read_session:
            row = (
                await read_session.execute(
                    select(TravelPlace, _PLACE_XMIN).where(
                        TravelPlace.place_id == place_id
                    )
                )
            ).one_or_none()
            if row is None:
                await read_session.commit()
                return None
            place, version = row
            snapshot = _place_address_snapshot(place, int(version))
            if snapshot.road_address and snapshot.official_address:
                await read_session.commit()
                return None
            # place/xmin SELECT transaction과 connection을 reverse HTTP 전에 반환한다.
            await read_session.commit()

        reverse = await reverse_with_vworld(
            vworld, snapshot.latitude, snapshot.longitude
        )
        if not reverse.get("road_address") and not reverse.get("parcel_address"):
            return None

        async with session_factory() as write_session:
            row = (
                await write_session.execute(
                    select(TravelPlace, _PLACE_XMIN)
                    .where(TravelPlace.place_id == place_id)
                    .with_for_update()
                )
            ).one_or_none()
            if row is None:
                await write_session.commit()
                return None
            current, current_version = row
            if _place_address_snapshot(current, int(current_version)) != snapshot:
                await write_session.commit()
                return None
            applied: dict[str, str | None] = {}
            if not current.road_address and reverse.get("road_address"):
                current.road_address = reverse["road_address"]
                applied["road_address"] = reverse["road_address"]
            if not current.official_address and reverse.get("parcel_address"):
                current.official_address = reverse["parcel_address"]
                applied["parcel_address"] = reverse["parcel_address"]
            await write_session.commit()
            return applied or None
    except Exception:
        return None


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
    expected_candidate_version: int,
    vworld: AsyncVworldClient | None = None,
    reviewer: str = "system",
) -> TravelPlace | None:
    """평가 결과를 후보에 적용한다.

    외부 provider 호출 중 사람이 먼저 후보를 처리할 수 있으므로 역지오코딩까지 lock
    밖에서 준비하고, 첫 DB 변경 직전에 현재 행을 `FOR UPDATE`로 다시 읽는다. 이미
    삭제됐거나 `needs_review`가 아니면 사람 결정을 보존하고
    `CandidateStateChangedError`로 건너뛴다. 먼저 잠근 쪽이 worker면 아래
    grounding/identity gate를 통과한 결과만 확정된다.

    matched면 중복 확인 후 장소를 확정(또는 재사용)하고, 그 외에는 `needs_review`로
    남긴다. 확정한 `TravelPlace`를 반환한다(미확정 시 None). 8자리 category 코드는
    POI 추출 때 후보 evidence에 저장해 둔 값을 복사한다.
    """
    reverse_attempted, reverse_coordinates, reverse_vworld = await _prepare_reverse_vworld(
        session, candidate, decision, vworld
    )

    # 장소 연결/생성은 어떤 row lock보다 먼저 lifecycle advisory lock에 참여한다.
    # merge/delete가 아직 needs_review인 후보를 predicate에서 건너뛴 뒤 장소를 바꾸는
    # gap을 닫고, 공통 lock 순서를 advisory -> candidate -> place -> mapping으로 맞춘다.
    await place_service.acquire_place_lifecycle_lock(session)

    # 이 지점 전에는 candidate/place/mapping mutation이 없다. 외부 I/O가 끝난 뒤 짧게
    # candidate row를 잠그고 identity map의 stale 값을 최신 사용자 결정으로 교체한다.
    current, current_version = await _lock_current_candidate_for_geocode(
        session, candidate.id
    )
    if (
        current is None
        or current.deleted_at is not None
        or current.match_status != MatchStatus.NEEDS_REVIEW.value
        or current_version != expected_candidate_version
    ):
        # SELECT가 시작한 transaction과 row lock을 다음 후보까지 끌고 가지 않는다.
        # 이 함수는 기존에도 모든 결과 경로에서 commit하므로 같은 transaction 계약이다.
        await session.commit()
        raise CandidateStateChangedError(
            candidate.id,
            expected_version=expected_candidate_version,
            current_version=current_version,
        )
    candidate = current

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
        # is_domestic None(미확인)은 fail-closed 신호를 보존해 queue_reason이 FOREIGN 버킷으로
        # 가도록 domestic_unverified로 표기한다(T-166 대칭, description_only가 국내여부 미확인을
        # 가리지 않게). 명시적 국내(True)만 description_only로 둔다. is_domestic False는 상위
        # 배치가 지오코딩 대상에서 제외하므로 여기 도달하지 않는다.
        candidate.review_note = (
            "domestic_unverified"
            if candidate.is_domestic is not True
            else "description_only"
        )
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
    c, confidence, ambiguous_single_pass = _select_geocode_candidate(
        candidate, decision
    )
    if c is None:
        candidate.match_status = MatchStatus.NEEDS_REVIEW
        candidate.review_note = decision.reason
        candidate.feature_export_status = FeatureExportStatus.PENDING.value
        await session.commit()
        return None
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
    # 서로 다른 후보의 auto/auto 및 auto/manual 신규 장소 승격은 위 lifecycle lock으로
    # 최종 중복 조회→생성을 하나의 임계구간에 둔다.
    dups = await place_service.find_duplicate_candidates(
        session,
        lat=c.latitude,
        lng=c.longitude,
        radius_meters=get_settings().GEOCODE_MERGE_RADIUS_METERS,
        populate_existing=True,
        for_update=True,
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
        if (
            reverse_coordinates == (c.latitude, c.longitude)
            and reverse_vworld is not None
        ):
            road = road or reverse_vworld.get("road_address")
            official = official or reverse_vworld.get("parcel_address")
            candidate.provider_evidence_json = _merge_provider_evidence(
                candidate.provider_evidence_json,
                geocoding=_geocode_evidence(
                    decision,
                    selected_candidate=c,
                    reverse_vworld=reverse_vworld,
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
    committed_place_id = place.place_id
    needs_reverse_fallback = (
        nearby_place is None
        and vworld is not None
        and not reverse_attempted
        and (not place.road_address or not place.official_address)
    )
    # 후보 lock을 외부 admin API 동안 유지하지 않는다. 장소 확정이 정본이며 먼저 commit한다.
    await session.commit()

    # 행정구역 보강은 core 확정 뒤 완전히 별도 session의 best-effort 작업이다. 실패해도
    # 호출자 session을 rollback/expire시키거나 이미 commit된 후보·장소·매핑을 되돌리지 않는다.
    from ktc.etl import admin_region_service

    isolated_reverse_vworld: dict[str, str | None] | None = None
    if session.bind is not None:
        isolated_factory = async_sessionmaker(session.bind, expire_on_commit=False)
        if needs_reverse_fallback and vworld is not None:
            isolated_reverse_vworld = await _enrich_missing_addresses_isolated(
                isolated_factory, committed_place_id, vworld
            )
        try:
            await admin_region_service.enrich_place_admin_codes_isolated(
                isolated_factory, committed_place_id
            )
        except Exception:
            # 격리 보강의 예상 밖 실패도 core/호출자 session에는 전파하지 않는다.
            await session.commit()
    candidate, mappings = await _lock_committed_candidate_mappings_for_geocode(
        session,
        candidate_id=candidate.id,
        place_id=committed_place_id,
        expected_candidate_version=expected_candidate_version,
    )
    try:
        await session.refresh(place)
    except (InvalidRequestError, ObjectDeletedError) as exc:
        # core commit 뒤 사용자가 장소를 삭제/재개방한 경합이다. read transaction만
        # commit해 connection을 반환하고 batch가 typed skip으로 집계하도록 전환한다.
        await session.commit()
        raise CandidateStateChangedError(
            candidate.id,
            expected_version=expected_candidate_version,
        ) from exc
    if isolated_reverse_vworld is not None:
        candidate.provider_evidence_json = _merge_reverse_vworld_provenance(
            candidate.provider_evidence_json, isolated_reverse_vworld
        )
        for mapping in mappings:
            mapping.provider_evidence_json = _merge_reverse_vworld_provenance(
                mapping.provider_evidence_json, isolated_reverse_vworld
            )
    await session.commit()
    return place


async def apply_geocode_to_current_candidate(
    session: AsyncSession,
    candidate: ExtractedPlaceCandidate,
    decision: GeocodeDecision,
    *,
    vworld: AsyncVworldClient | None = None,
    reviewer: str = "system",
) -> TravelPlace | None:
    """외부 대기가 없는 direct 호출용으로 현재 xmin을 명시적으로 snapshot해 적용한다.

    production worker는 이 helper가 아니라 외부 provider 호출 전에 얻은 version을
    `apply_geocode_to_candidate`에 반드시 전달한다. 단순 None/fail-open 경로는 두지 않는다.
    """
    snapshot = await read_candidate_geocode_snapshot(session, candidate.id)
    await session.commit()
    if snapshot is None or not snapshot.eligible:
        raise CandidateStateChangedError(
            candidate.id,
            expected_version=snapshot.version if snapshot is not None else None,
        )
    return await apply_geocode_to_candidate(
        session,
        candidate,
        decision,
        expected_candidate_version=snapshot.version,
        vworld=vworld,
        reviewer=reviewer,
    )


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


def _merge_reverse_vworld_provenance(
    existing: dict | None,
    reverse_vworld: dict[str, str | None],
) -> dict:
    """최신 candidate/mapping evidence를 보존하며 격리 reverse 적용값만 합친다."""
    merged = dict(existing or {})
    geocoding = dict(merged.get("geocoding") or {})
    geocoding["reverse_vworld"] = dict(reverse_vworld)
    merged["geocoding"] = geocoding
    return merged
