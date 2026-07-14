"""장소 조회 및 근접 중복 후보 탐색 서비스 (저장소 계층)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import math
import re
import secrets
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from geoalchemy2 import Geography
from sqlalchemy import (
    ARRAY,
    Numeric,
    Text,
    and_,
    case,
    cast,
    delete,
    distinct,
    func,
    insert,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import load_only

from ktc.core.config import get_settings
from ktc.core.spatial import sync_place_geometry
from ktc.etl import category_catalog
from ktc.etl.place_name import names_match
from ktc.models import (
    AuditStatus,
    ExtractedPlaceCandidate,
    EvidenceSourceKind,
    FeatureExportStatus,
    GroundingStatus,
    MatchStatus,
    MediaAsset,
    PlaceLifecycleOrigin,
    ReviewBulkAction,
    ReviewBulkItemStatus,
    ReviewBulkOperation,
    ReviewBulkOperationItem,
    ReviewBulkOperationReceipt,
    ReviewBulkOperationStatus,
    TravelPlace,
    VideoPlaceMapping,
    YoutubeChannel,
    YoutubePlaylist,
    YoutubeVideo,
    utcnow,
)
from ktc.services import audit_service, feature_export_service
from ktc.services.list_pagination import (
    ListPage,
    MAX_DB_INTEGER_ID,
    decode_cursor,
    encode_cursor,
    ensure_repeatable_read,
    filter_fingerprint,
)

EARTH_RADIUS_M = 6_371_000.0
PLACE_LIFECYCLE_ADVISORY_LOCK_ID = 174


async def acquire_place_lifecycle_lock(session: AsyncSession) -> None:
    """장소 연결·병합·삭제 임계구간을 transaction advisory lock으로 직렬화한다.

    호출자는 어떤 candidate/place/mapping/asset row lock보다 먼저 호출해야 한다.
    """
    await session.execute(
        select(func.pg_advisory_xact_lock(PLACE_LIFECYCLE_ADVISORY_LOCK_ID))
        .execution_options(autoflush=False)
    )


class ProviderPersistenceDisabled(ValueError):
    """영구 저장이 허용되지 않은 provider 결과가 resolve에 사용됨."""


class NearbyPlaceConfirmationRequired(ValueError):
    """근접 장소의 동일성을 확정할 수 없어 사용자 선택이 필요함."""

    def __init__(self, nearby_places: list[dict[str, Any]]) -> None:
        super().__init__("100m 안의 기존 장소와 합칠지 새로 만들지 선택해야 한다")
        self.nearby_places = nearby_places


class CandidateMappingConflictError(ValueError):
    """확정 연결(video_place_mappings 보유) 후보를 `force` 없이 삭제하려 했다(라우트 409)."""


class CandidateResolveConflictError(ValueError):
    """이미 해결됐거나 검수 대상이 아닌 후보를 다시 resolve하려 했다(라우트 409)."""


class CandidateRevisionConflictError(ValueError):
    """후보 row lock 뒤 확인한 revision이 클라이언트 선행 조건과 다르다."""

    def __init__(self, *, expected_revision: int, actual_revision: int) -> None:
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
        super().__init__("후보가 다른 작업으로 변경되었습니다. 최신 상태를 다시 확인해 주세요.")


class CandidatePlaceChangedError(ValueError):
    """undo token 발급 뒤 후보의 장소 연결 또는 장소 revision이 달라졌다."""


class InvalidCandidateUndoToken(ValueError):
    """strict canonical `candidate-undo-v1` token이 아니다."""


class CandidateStatusConflictError(ValueError):
    """FOR UPDATE 후의 실제 후보 상태가 삭제 선행 조건과 다르다(라우트 409)."""

    def __init__(
        self,
        *,
        expected_status: MatchStatus,
        actual_status_by_candidate_id: dict[int, str],
    ) -> None:
        self.expected_status = expected_status
        self.actual_status_by_candidate_id = actual_status_by_candidate_id
        super().__init__(
            f"{expected_status.value} 상태인 후보만 삭제할 수 있습니다."
        )


class CandidateReopenConflictError(ValueError):
    """이미 검수 대기(needs_review) 상태라 reopen이 무의미하다(라우트 409)."""


_CANDIDATE_UNDO_VERSION = "candidate-undo-v1"
_MAX_BIGINT = 9_223_372_036_854_775_807
_CANDIDATE_UNDO_KEYS = frozenset(
    {
        "version",
        "candidate_id",
        "candidate_revision",
        "prior_state",
        "effective_state",
        "matched_place_id",
        "matched_place_revision",
    }
)


@dataclass(frozen=True)
class CandidateUndoToken:
    """후보 처리 직후의 DB 상태를 고정하는 opaque undo 선행 조건."""

    candidate_id: int
    candidate_revision: int
    prior_state: str
    effective_state: str
    matched_place_id: int | None
    matched_place_revision: int | None


def candidate_review_state(candidate: ExtractedPlaceCandidate) -> str:
    """soft delete를 우선하는 사용자 관점 후보 상태를 반환한다."""
    return _candidate_review_state_from_values(
        match_status=candidate.match_status,
        deleted_at=candidate.deleted_at,
    )


def _candidate_review_state_from_values(
    *,
    match_status: MatchStatus | str,
    deleted_at: datetime | None,
) -> str:
    """ORM entity 없이도 같은 사용자 관점 상태를 계산한다."""
    if deleted_at is not None:
        return "deleted"
    return str(getattr(match_status, "value", match_status))


def _positive_int(value: Any, *, maximum: int) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 < value <= maximum
    )


def _candidate_undo_payload(
    candidate: ExtractedPlaceCandidate,
    *,
    matched_place_revision: int | None,
) -> dict[str, Any]:
    return _candidate_undo_payload_from_values(
        candidate_id=candidate.id,
        candidate_revision=candidate.state_revision,
        match_status=candidate.match_status,
        deleted_at=candidate.deleted_at,
        matched_place_id=candidate.matched_place_id,
        matched_place_revision=matched_place_revision,
    )


def _candidate_undo_payload_from_values(
    *,
    candidate_id: int,
    candidate_revision: int,
    match_status: MatchStatus | str,
    deleted_at: datetime | None,
    matched_place_id: int | None,
    matched_place_revision: int | None,
) -> dict[str, Any]:
    """단건 ORM과 bulk scalar snapshot이 공유하는 canonical undo payload다."""
    if (matched_place_id is None) != (matched_place_revision is None):
        raise ValueError("undo token의 장소 ID와 revision은 함께 있어야 합니다")
    return {
        "version": _CANDIDATE_UNDO_VERSION,
        "candidate_id": candidate_id,
        "candidate_revision": candidate_revision,
        # underlying match_status와 soft-delete 우선 effective state를 모두 넣어
        # `deleted(needs_review)`와 live `needs_review`를 구분한다.
        "prior_state": str(getattr(match_status, "value", match_status)),
        "effective_state": _candidate_review_state_from_values(
            match_status=match_status,
            deleted_at=deleted_at,
        ),
        "matched_place_id": matched_place_id,
        "matched_place_revision": matched_place_revision,
    }


def _encode_candidate_undo_payload(payload: dict[str, Any]) -> str:
    """candidate-undo-v1 payload를 canonical base64url 문자열로 직렬화한다."""
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def encode_candidate_undo_token(
    candidate: ExtractedPlaceCandidate,
    *,
    matched_place_revision: int | None = None,
) -> str:
    """padding 없는 canonical base64url JSON undo token을 생성한다."""
    payload = _candidate_undo_payload(
        candidate,
        matched_place_revision=matched_place_revision,
    )
    return _encode_candidate_undo_payload(payload)


def candidate_undo_descriptor(
    candidate: ExtractedPlaceCandidate,
    *,
    matched_place_revision: int | None = None,
) -> dict[str, Any]:
    """브라우저가 해석하지 않고 reopen에 되돌려 보낼 descriptor를 반환한다."""
    return {
        "candidate_id": candidate.id,
        "token": encode_candidate_undo_token(
            candidate,
            matched_place_revision=matched_place_revision,
        ),
    }


def decode_candidate_undo_token(token: str) -> CandidateUndoToken:
    """비정규·확장 field·타입 혼동을 거부하는 strict token decoder."""
    if not isinstance(token, str) or not 1 <= len(token) <= 4096:
        raise InvalidCandidateUndoToken("유효하지 않은 undo token입니다")
    if re.fullmatch(r"[A-Za-z0-9_-]+", token) is None:
        raise InvalidCandidateUndoToken("유효하지 않은 undo token입니다")
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.b64decode(
            padded.encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
        payload = json.loads(raw.decode("utf-8"))
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
    ) as exc:
        raise InvalidCandidateUndoToken("유효하지 않은 undo token입니다") from exc
    if not isinstance(payload, dict) or set(payload) != _CANDIDATE_UNDO_KEYS:
        raise InvalidCandidateUndoToken("유효하지 않은 undo token입니다")
    if payload.get("version") != _CANDIDATE_UNDO_VERSION:
        raise InvalidCandidateUndoToken("지원하지 않는 undo token 버전입니다")
    if not _positive_int(
        payload.get("candidate_id"), maximum=MAX_DB_INTEGER_ID
    ) or not _positive_int(
        payload.get("candidate_revision"), maximum=_MAX_BIGINT
    ):
        raise InvalidCandidateUndoToken("유효하지 않은 undo token입니다")
    prior_state = payload.get("prior_state")
    effective_state = payload.get("effective_state")
    allowed_states = {status.value for status in MatchStatus}
    if not isinstance(prior_state, str) or prior_state not in allowed_states:
        raise InvalidCandidateUndoToken("유효하지 않은 undo token입니다")
    if (
        not isinstance(effective_state, str)
        or effective_state not in allowed_states | {"deleted"}
    ):
        raise InvalidCandidateUndoToken("유효하지 않은 undo token입니다")
    if effective_state != "deleted" and effective_state != prior_state:
        raise InvalidCandidateUndoToken("유효하지 않은 undo token입니다")
    place_id = payload.get("matched_place_id")
    place_revision = payload.get("matched_place_revision")
    if (place_id is None) != (place_revision is None):
        raise InvalidCandidateUndoToken("유효하지 않은 undo token입니다")
    if place_id is not None and (
        not _positive_int(place_id, maximum=MAX_DB_INTEGER_ID)
        or not _positive_int(place_revision, maximum=_MAX_BIGINT)
    ):
        raise InvalidCandidateUndoToken("유효하지 않은 undo token입니다")
    canonical = base64.urlsafe_b64encode(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).decode("ascii").rstrip("=")
    if canonical != token:
        raise InvalidCandidateUndoToken("유효하지 않은 undo token입니다")
    return CandidateUndoToken(
        candidate_id=payload["candidate_id"],
        candidate_revision=payload["candidate_revision"],
        prior_state=prior_state,
        effective_state=effective_state,
        matched_place_id=place_id,
        matched_place_revision=place_revision,
    )


def _require_candidate_revision(
    candidate: ExtractedPlaceCandidate,
    expected_revision: int | None,
) -> None:
    """서비스 내부 호출은 생략 가능하지만 REST는 반드시 expected revision을 전달한다."""
    if expected_revision is None:
        return
    if candidate.state_revision != expected_revision:
        raise CandidateRevisionConflictError(
            expected_revision=expected_revision,
            actual_revision=candidate.state_revision,
        )


class QueueReason(str, Enum):
    """검수 대기 우선순위를 설명하는 안정 API enum.

    선언 순서가 곧 사용자 검수 우선순위다. 새 값은 기존 값의 의미를 바꾸지 않고
    추가하며, SQL filter와 목록 payload가 같은 파생 규칙을 사용한다.
    """

    UNGROUNDED = "ungrounded"
    NAME_MISMATCH = "name_mismatch"
    REGION_MISMATCH = "region_mismatch"
    SOURCE_CONFLICT = "source_conflict"
    SOURCE_LOW_CONFIDENCE = "source_low_confidence"
    SOURCE_UNCERTAIN = "source_uncertain"
    AMBIGUOUS = "ambiguous"
    NO_RESULT = "no_result"
    VWORLD_UNREFINED_SINGLE = "vworld_unrefined_single"
    FOREIGN = "foreign"
    DESCRIPTION_ONLY = "description_only"
    VISUAL_ONLY = "visual_only"
    PROVIDER_MISSING = "provider_missing"
    EXTRACTION_ONLY = "extraction_only"


class ReviewCandidateSort(str, Enum):
    """검수 큐의 안정적인 ID keyset 정렬."""

    NEWEST = "newest"
    OLDEST = "oldest"


class ReviewCandidateStatus(str, Enum):
    """검수 목록에서 사용자가 전환할 수 있는 후보 상태."""

    NEEDS_REVIEW = MatchStatus.NEEDS_REVIEW.value
    IGNORED = MatchStatus.IGNORED.value
    REMOVED = "removed"


class ReviewCandidateDomesticFilter(str, Enum):
    """검수 목록의 국내 여부 query 계약."""

    ALL = "all"
    TRUE = "true"
    FALSE = "false"


# T-185 일괄 검수 계약. selection은 실수로 거대한 요청을 만들지 못하게 500건으로
# 제한하고, filter는 preview에서 정확한 멤버십을 item 행으로 동결하되 운영 안전 상한을
# 넘으면 일부만 처리하지 않고 명시적으로 거부한다.
REVIEW_BULK_SELECTION_LIMIT = 500
REVIEW_BULK_FILTER_LIMIT = 10_000
REVIEW_BULK_CHUNK_SIZE = 100
REVIEW_BULK_ITEM_INSERT_BATCH_SIZE = 1_000
REVIEW_BULK_CONFIRMATION_TTL = timedelta(minutes=5)
_REVIEW_BULK_TOKEN_VERSION = "rbulk1"
_REVIEW_BULK_CURSOR_VERSION = "rbc1"


class ReviewBulkValidationError(ValueError):
    """일괄 검수 scope/action 조합이 유효하지 않다(라우트 400)."""


class ReviewBulkLimitExceededError(ValueError):
    """필터 결과가 안전 상한을 초과했다(라우트 413, 자동 truncation 금지)."""


class ReviewBulkOperationNotFoundError(ValueError):
    """operation이 없거나 요청 actor가 소유하지 않는다(라우트 404)."""


class ReviewBulkTokenError(ValueError):
    """confirmation token이 위조·변조됐거나 다른 operation에 속한다(라우트 403)."""


class ReviewBulkTokenExpiredError(ValueError):
    """아직 시작하지 않은 preview의 confirmation token이 만료됐다(라우트 410)."""


class ReviewBulkCursorConflictError(ValueError):
    """execute cursor/request receipt가 현재 operation 진행 위치와 충돌한다(라우트 409)."""


@dataclass(frozen=True)
class ReviewBulkPreviewResult:
    """평문 token은 이 응답에서만 노출하고 DB에는 hash만 저장한다."""

    operation_id: UUID
    confirmation_token: str
    expires_at: datetime
    total: int
    chunk_size: int


@dataclass(frozen=True)
class ReviewBulkCandidateSnapshot:
    """preview item에 필요한 candidate/place scalar만 담은 경량 snapshot."""

    candidate_id: int
    candidate_revision: int
    match_status: str
    deleted_at: datetime | None
    matched_place_id: int | None
    matched_place_revision: int | None

    @property
    def review_state(self) -> str:
        return _candidate_review_state_from_values(
            match_status=self.match_status,
            deleted_at=self.deleted_at,
        )

    def undo_token(self) -> str:
        return _encode_candidate_undo_payload(
            _candidate_undo_payload_from_values(
                candidate_id=self.candidate_id,
                candidate_revision=self.candidate_revision,
                match_status=self.match_status,
                deleted_at=self.deleted_at,
                matched_place_id=self.matched_place_id,
                matched_place_revision=self.matched_place_revision,
            )
        )


@dataclass(frozen=True)
class CandidateListItem:
    """검수 목록에 필요한 짧은 scalar만 결합한 조회 결과."""

    candidate: ExtractedPlaceCandidate
    video_title: str
    channel_title: str | None
    queue_reason: QueueReason
    video_is_excluded: bool
    matched_place_revision: int | None


@dataclass(frozen=True)
class PlaceSourceMention:
    """확정 장소가 특정 YouTube 영상에서 언급된 근거."""

    mapping_id: int
    video_id: str
    video_title: str
    video_url: str
    channel_id: str
    channel_name: str | None
    timestamp_start: str | None
    timestamp_end: str | None
    ai_summary: str
    speaker_note: str | None


@dataclass(frozen=True)
class PlaceSummary:
    """장소 목록·내보내기에서 쓰는 집계 단위."""

    place: TravelPlace
    mention_count: int
    source_channel_count: int
    source_videos: list[PlaceSourceMention]


def haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 좌표(EPSG:4326) 간 Haversine 거리(미터)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


async def find_places_within_radius(
    session: AsyncSession,
    *,
    lat: float,
    lng: float,
    radius_meters: float,
    limit: int = 20,
    populate_existing: bool = False,
    for_update: bool = False,
) -> list[tuple[TravelPlace, float]]:
    """PostGIS `ST_DWithin`으로 반경 내 장소를 거리 오름차순 반환한다.

    기본 조회는 기존 읽기 계약대로 identity map을 유지하고 row lock을 잡지 않는다.
    자동·수동 확정 임계구간처럼 최신 장소 값과 쓰기 직렬화가 모두 필요한 호출자만
    `populate_existing=True`, `for_update=True`를 명시한다.
    """
    point = func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)
    place_geog = cast(TravelPlace.geom, Geography)
    point_geog = cast(point, Geography)
    distance_m = func.ST_Distance(place_geog, point_geog)
    conditions = (
        TravelPlace.is_geocoded.is_(True),
        TravelPlace.geom.is_not(None),
        func.ST_DWithin(place_geog, point_geog, radius_meters),
    )
    if for_update:
        # 거리 순서는 요청 좌표마다 달라 merge의 place ID 순서와 교착할 수 있다. 먼저
        # 후보 ID만 고른 뒤 실제 row lock은 place_id 오름차순으로 잡고, 반환 순서만
        # 다시 거리순으로 정렬한다.
        candidate_ids = list(
            (
                await session.execute(
                    select(TravelPlace.place_id)
                    .where(*conditions)
                    .order_by(distance_m.asc(), TravelPlace.place_id.asc())
                    .limit(limit)
                    .execution_options(autoflush=False)
                )
            ).scalars()
        )
        if not candidate_ids:
            return []
        stmt = (
            select(TravelPlace, distance_m.label("distance_m"))
            .where(*conditions, TravelPlace.place_id.in_(candidate_ids))
            .order_by(TravelPlace.place_id.asc())
            .with_for_update()
        )
    else:
        stmt = (
            select(TravelPlace, distance_m.label("distance_m"))
            .where(*conditions)
            .order_by(distance_m.asc(), TravelPlace.place_id.asc())
            .limit(limit)
        )
    if populate_existing:
        stmt = stmt.execution_options(populate_existing=True, autoflush=False)
    result = await session.execute(stmt)
    rows = [(place, float(distance or 0.0)) for place, distance in result.all()]
    if for_update:
        rows.sort(key=lambda row: (row[1], row[0].place_id))
    return rows


async def find_duplicate_candidates(
    session: AsyncSession,
    *,
    lat: float,
    lng: float,
    radius_meters: float = 100.0,
    limit: int = 5,
    populate_existing: bool = False,
    for_update: bool = False,
) -> list[tuple[TravelPlace, float]]:
    """좌표 근접성 기반 중복 의심 장소를 반환한다.

    신규 후보를 확정 장소로 승격하기 전, 같은 좌표 근방의 기존 장소를 찾아 중복
    생성을 방지하는 용도다.
    """
    return await find_places_within_radius(
        session,
        lat=lat,
        lng=lng,
        radius_meters=radius_meters,
        limit=limit,
        populate_existing=populate_existing,
        for_update=for_update,
    )


# 병합 제안의 반경 조회 스캔 상한(이름 필터 전 후보 풀). 확정 장소가 수백 건 규모라
# 반경 내 이 개수까지 근접순으로 훑고 이름 게이트 통과분만 상위 N을 제안한다.
_MERGE_SUGGESTION_SCAN_LIMIT = 50


@dataclass(frozen=True)
class MergeSuggestion:
    """확정 장소의 잠재 중복 병합 후보(T-167, 로드맵 PR-14 개정판, D6).

    정규화 이름이 유사하고(같은 pairwise `names_match` 규칙) 근접(config 병합 반경 내)한
    다른 확정 장소를 노출한다. 이는 **제안**일 뿐이며 자동으로 상태를 바꾸지 않는다 —
    실제 병합은 사람이 `merge_places`로 실행한다(자동 병합은 provider ID·주소 일치의 좁은
    경우만 후속 도입, §10.4).
    """

    place: TravelPlace
    distance_m: float


async def merge_suggestions_for_place(
    session: AsyncSession,
    *,
    place_id: int,
    radius_meters: float | None = None,
    limit: int = 10,
) -> list[MergeSuggestion]:
    """확정 장소의 잠재 중복(정규화 이름 유사 + 근접) 병합 제안 목록을 산출한다.

    자동 병합을 하지 않고 제안만 반환한다(자동 상태 변경 없음). 좌표가 없는 장소는 빈
    목록을 준다. 반경 기본값은 자동확정 병합 반경(config)과 같게 둔다.
    """
    place = await session.get(TravelPlace, place_id)
    if place is None:
        raise ValueError(f"place not found: {place_id}")
    if place.latitude is None or place.longitude is None:
        return []
    radius = (
        radius_meters
        if radius_meters is not None
        else get_settings().GEOCODE_MERGE_RADIUS_METERS
    )
    # 반경 조회는 이름 필터 전이라 넉넉히 스캔한다(밀집 지역의 실제 중복이 근접순 12번째
    # 이후라 이름 필터 후 상위 N에서 누락되는 것을 완화 — 제안 전용이라 비용이 싸다).
    scan_limit = max(_MERGE_SUGGESTION_SCAN_LIMIT, limit + 1)
    nearby = await find_places_within_radius(
        session,
        lat=place.latitude,
        lng=place.longitude,
        radius_meters=radius,
        limit=scan_limit,
    )
    suggestions: list[MergeSuggestion] = []
    for other, distance in nearby:
        if other.place_id == place_id:
            continue
        # 근접만으로는 제안하지 않는다. 이름 게이트(정규화 동일 또는 구체적 부분 포함)를
        # 통과하는 잠재 중복만 노출해 오제안(관광지 밀집 지역의 무관 장소)을 줄인다.
        if not names_match(place.name, other.name):
            continue
        suggestions.append(MergeSuggestion(place=other, distance_m=distance))
        if len(suggestions) >= limit:
            break
    return suggestions


async def list_places(session: AsyncSession, *, limit: int = 100) -> list[TravelPlace]:
    """확정 장소 목록을 최신순으로 조회한다."""
    stmt = select(TravelPlace).order_by(TravelPlace.place_id.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_place_summaries(
    session: AsyncSession,
    *,
    sort: str = "latest",
    place_ids: list[int] | None = None,
    limit: int | None = 100,
    channel_id: str | None = None,
    playlist_id: str | None = None,
    keyword: str | None = None,
    video_id: str | None = None,
    category: str | None = None,
    query: str | None = None,
    district: str | None = None,
    geocoded_only: bool = False,
) -> list[PlaceSummary]:
    """확정 장소 목록과 영상·유튜버 언급 근거를 함께 조회한다.

    `channel_id`/`playlist_id`/`keyword`/`video_id`가 주어지면 해당 출처(유튜버/재생목록/
    검색어/영상)에서 수집된 장소만 반환한다(결과 보기 그룹화·필터, 영상별 필터).

    `geocoded_only=True`면 확정 좌표(`is_geocoded`)가 있는 장소만 반환한다(T-189, export의
    미검증 좌표 유출 방지). 기본값 False라 결과 보기·테마 등 기존 호출자는 영향을 받지 않는다.

    T-188: 필터·정렬·`LIMIT`를 SQL로 밀어 넣는다. 확정 장소 전량을 로드·집계한 뒤
    자르던 경로를 없애고, 무거운 언급 근거(`_list_mentions_by_place`)는 limit 적용 후
    페이지 대상 장소에 대해서만 로드한다(O(전체)→O(limit)).
    """
    where = await _place_summary_where(
        session,
        place_ids=place_ids,
        channel_id=channel_id,
        playlist_id=playlist_id,
        keyword=keyword,
        video_id=video_id,
        category=category,
        query=query,
        district=district,
    )
    if where is None:
        return []
    if geocoded_only:
        where = [*where, TravelPlace.is_geocoded.is_(True)]
    places = await _ordered_place_query(
        session,
        sort=sort,
        where_conditions=where,
        snapshot_id=None,
        keyset_keys=None,
        limit=limit,
    )
    return await _build_summaries_for_places(session, places)


def _place_search_text_expr():
    """`_place_search_text`와 동일한 SQL 표현식(빈 문자열/NULL 필드는 제외)."""
    return func.concat_ws(
        " ",
        func.nullif(TravelPlace.name, ""),
        func.nullif(TravelPlace.official_address, ""),
        func.nullif(TravelPlace.road_address, ""),
        func.nullif(TravelPlace.description, ""),
        func.nullif(TravelPlace.gemini_enriched_description, ""),
    )


def _place_district_expr():
    """`sigungu_code or _district_label_from_address(road||official)`의 SQL 표현식.

    주소 라벨은 공백 기준 앞 두 토큰의 결합이며, 토큰이 2개 미만이면 NULL이다
    (`str.split()[:2]`와 동치). ``regexp_match``는 매치가 없으면 NULL을 돌려주고 그
    NULL은 문자열 결합을 통해 전파되므로 별도 CASE가 필요 없다.
    """
    addr = func.coalesce(
        func.nullif(TravelPlace.road_address, ""),
        func.nullif(TravelPlace.official_address, ""),
    )
    tokens = func.regexp_match(addr, r"^\s*(\S+)\s+(\S+)", type_=ARRAY(Text))
    label = tokens[1].concat(" ").concat(tokens[2])
    return func.coalesce(func.nullif(TravelPlace.sigungu_code, ""), label)


def _result_filter_conditions(
    *, category: str | None, query: str | None, district: str | None
) -> list[Any]:
    """`_place_matches_result_filters`와 동일한 category/query/district 필터의 SQL 조건."""
    conditions: list[Any] = []
    if category:
        conditions.append(func.coalesce(TravelPlace.category, "") == category)
    if district:
        conditions.append(_place_district_expr() == district)
    if query:
        needle = query.strip().lower()
        if needle:
            conditions.append(
                func.strpos(func.lower(_place_search_text_expr()), needle) > 0
            )
    return conditions


async def _place_summary_where(
    session: AsyncSession,
    *,
    place_ids: list[int] | None,
    channel_id: str | None,
    playlist_id: str | None,
    keyword: str | None,
    video_id: str | None,
    category: str | None,
    query: str | None,
    district: str | None,
) -> list[Any] | None:
    """장소 요약 조회의 공통 WHERE 조건을 만든다. 결과가 반드시 비면 ``None``."""
    matched = await _filtered_place_ids(
        session,
        channel_id=channel_id,
        playlist_id=playlist_id,
        keyword=keyword,
        video_id=video_id,
    )
    effective_ids: list[int] | None = None
    if place_ids is not None and matched is not None:
        effective_ids = list(set(place_ids) & matched)
    elif place_ids is not None:
        effective_ids = place_ids
    elif matched is not None:
        effective_ids = list(matched)

    where: list[Any] = []
    if effective_ids is not None:
        if not effective_ids:
            return None
        where.append(TravelPlace.place_id.in_(sorted(set(effective_ids))))
    where.extend(
        _result_filter_conditions(
            category=category, query=query, district=district
        )
    )
    return where


def _mention_aggregate_subquery():
    """장소별 고유 영상 수·유튜버 수 집계 서브쿼리.

    ``_list_mentions_by_place``와 동일하게 실재 영상(inner join)만 센다. mention_count는
    고유 `video_id` 수, source_channel_count는 NULL이 아닌 고유 `channel_id` 수다.
    """
    return (
        select(
            VideoPlaceMapping.place_id.label("place_id"),
            func.count(distinct(VideoPlaceMapping.video_id)).label("mention_count"),
            func.count(distinct(YoutubeVideo.channel_id)).label("channel_count"),
        )
        .join(YoutubeVideo, VideoPlaceMapping.video_id == YoutubeVideo.video_id)
        .group_by(VideoPlaceMapping.place_id)
        .subquery()
    )


async def _ordered_place_query(
    session: AsyncSession,
    *,
    sort: str,
    where_conditions: list[Any],
    snapshot_id: int | None,
    keyset_keys: tuple[Any, ...] | None,
    limit: int | None,
) -> list[TravelPlace]:
    """필터·정렬·(watermark·keyset·)LIMIT를 SQL로 적용한 확정 장소 행을 반환한다.

    정렬 키 문자열 비교는 Python 코드포인트 순서(`COLLATE "C"` == UTF-8 바이트 순서)로
    맞춰 재작성 전 Python 정렬과 동일한 순서를 보장한다. cursor keyset은 재작성 전
    음수 튜플 계약(`_place_summary_cursor_key`)의 실제 값을 복원해 자연 방향 비교로 만든다.
    """
    conditions = list(where_conditions)
    if snapshot_id is not None:
        conditions.append(TravelPlace.place_id <= snapshot_id)

    name_c = TravelPlace.name.collate("C")
    stmt = select(TravelPlace)

    if sort == "mention_count":
        agg = _mention_aggregate_subquery()
        mc = func.coalesce(agg.c.mention_count, 0)
        cc = func.coalesce(agg.c.channel_count, 0)
        stmt = stmt.outerjoin(agg, agg.c.place_id == TravelPlace.place_id)
        order_by = [mc.desc(), cc.desc(), name_c.asc(), TravelPlace.place_id.desc()]
        if keyset_keys is not None:
            a_mc, a_cc, a_name, a_pid = (
                -keyset_keys[0],
                -keyset_keys[1],
                keyset_keys[2],
                -keyset_keys[3],
            )
            conditions.append(
                or_(
                    mc < a_mc,
                    and_(mc == a_mc, cc < a_cc),
                    and_(mc == a_mc, cc == a_cc, name_c > a_name),
                    and_(
                        mc == a_mc,
                        cc == a_cc,
                        name_c == a_name,
                        TravelPlace.place_id < a_pid,
                    ),
                )
            )
    elif sort == "name":
        order_by = [name_c.asc(), TravelPlace.place_id.desc()]
        if keyset_keys is not None:
            a_name, a_pid = keyset_keys[0], -keyset_keys[1]
            conditions.append(
                or_(
                    name_c > a_name,
                    and_(name_c == a_name, TravelPlace.place_id < a_pid),
                )
            )
    elif sort == "category":
        cat_c = func.coalesce(
            func.nullif(TravelPlace.category, ""), "미분류"
        ).collate("C")
        order_by = [cat_c.asc(), name_c.asc(), TravelPlace.place_id.desc()]
        if keyset_keys is not None:
            a_cat, a_name, a_pid = keyset_keys[0], keyset_keys[1], -keyset_keys[2]
            conditions.append(
                or_(
                    cat_c > a_cat,
                    and_(cat_c == a_cat, name_c > a_name),
                    and_(
                        cat_c == a_cat,
                        name_c == a_name,
                        TravelPlace.place_id < a_pid,
                    ),
                )
            )
    else:  # latest
        order_by = [TravelPlace.place_id.desc()]
        if keyset_keys is not None:
            conditions.append(TravelPlace.place_id < -keyset_keys[0])

    stmt = stmt.where(*conditions).order_by(*order_by)
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _build_summaries_for_places(
    session: AsyncSession, places: list[TravelPlace]
) -> list[PlaceSummary]:
    """정렬·LIMIT를 마친 장소들에 대해서만 언급 근거를 로드해 요약을 만든다.

    mention_count/source_channel_count는 재작성 전과 동일하게 로드된 언급에서 계산한다
    (매핑 행 수가 아니라 고유 영상/유튜버 수).
    """
    if not places:
        return []
    mentions_by_place = await _list_mentions_by_place(
        session, place_ids=[place.place_id for place in places]
    )
    return [
        PlaceSummary(
            place=place,
            mention_count=len(
                {
                    mention.video_id
                    for mention in mentions_by_place.get(place.place_id, [])
                }
            ),
            source_channel_count=len(
                {
                    mention.channel_id
                    for mention in mentions_by_place.get(place.place_id, [])
                    if mention.channel_id
                }
            ),
            source_videos=mentions_by_place.get(place.place_id, []),
        )
        for place in places
    ]


def _place_summary_cursor_key(summary: PlaceSummary, sort: str) -> tuple[Any, ...]:
    """T-177 Python 정렬 계약과 동일한, null 없는 cursor key."""
    return tuple(_place_summary_sort_key(sort)(summary))


def _valid_place_cursor_keys(
    keys: tuple[Any, ...], sort: str, *, snapshot_id: int
) -> bool:
    if sort == "latest":
        valid = len(keys) == 1 and type(keys[0]) is int
        id_key = -keys[0] if valid else 0
        return valid and 1 <= id_key <= snapshot_id
    if sort == "mention_count":
        valid = (
            len(keys) == 4
            and type(keys[0]) is int
            and -MAX_DB_INTEGER_ID <= keys[0] <= 0
            and type(keys[1]) is int
            and -MAX_DB_INTEGER_ID <= keys[1] <= 0
            and isinstance(keys[2], str)
            and len(keys[2]) <= 255
            and type(keys[3]) is int
        )
        id_key = -keys[3] if valid else 0
        return valid and 1 <= id_key <= snapshot_id
    if sort == "name":
        valid = (
            len(keys) == 2
            and isinstance(keys[0], str)
            and len(keys[0]) <= 255
            and type(keys[1]) is int
        )
        id_key = -keys[1] if valid else 0
        return valid and 1 <= id_key <= snapshot_id
    if sort == "category":
        valid = (
            len(keys) == 3
            and isinstance(keys[0], str)
            and len(keys[0]) <= 64
            and isinstance(keys[1], str)
            and len(keys[1]) <= 255
            and type(keys[2]) is int
        )
        id_key = -keys[2] if valid else 0
        return valid and 1 <= id_key <= snapshot_id
    return False


async def list_place_summaries_page(
    session: AsyncSession,
    *,
    sort: str = "latest",
    limit: int = 100,
    channel_id: str | None = None,
    playlist_id: str | None = None,
    keyword: str | None = None,
    video_id: str | None = None,
    category: str | None = None,
    query: str | None = None,
    district: str | None = None,
    cursor: str | None = None,
    newer_than_id: int | None = None,
) -> ListPage[PlaceSummary]:
    """장소 집계 목록에 공통 envelope와 안정적인 복합 cursor를 적용한다.

    T-188: watermark·total·newer_than·keyset 페이지를 모두 SQL로 계산한다. 정렬 문자열
    비교를 PostgreSQL `COLLATE "C"`(코드포인트 순서)로 옮겼으므로 cursor scope를
    ``destinations-sql-v2``로 올려 구 Python-정렬 cursor를 명시적으로 거부한다.
    """
    await ensure_repeatable_read(session)
    normalized_query = (query or "").strip().lower() or None
    filters = {
        "channel_id": channel_id or None,
        "playlist_id": playlist_id or None,
        "keyword": keyword or None,
        "video_id": video_id or None,
        "category": category or None,
        "query": normalized_query,
        "district": district or None,
    }
    fingerprint = filter_fingerprint(
        scope="destinations-sql-v2", sort=sort, filters=filters
    )
    key_count = {
        "latest": 1,
        "mention_count": 4,
        "name": 2,
        "category": 3,
    }[sort]
    decoded = (
        decode_cursor(cursor, fingerprint=fingerprint, key_count=key_count)
        if cursor
        else None
    )
    if decoded is not None and not _valid_place_cursor_keys(
        decoded.keys, sort, snapshot_id=decoded.snapshot_id
    ):
        raise ValueError("유효하지 않은 장소 목록 cursor입니다")

    where = await _place_summary_where(
        session,
        place_ids=None,
        channel_id=filters["channel_id"],
        playlist_id=filters["playlist_id"],
        keyword=filters["keyword"],
        video_id=filters["video_id"],
        category=filters["category"],
        query=filters["query"],
        district=filters["district"],
    )
    if where is None:
        # 출처 필터가 아무 장소도 매치하지 못하면 반드시 빈 결과다. cursor가 있으면 그
        # snapshot watermark를 보존해 재작성 전과 동일한 envelope를 돌려준다.
        empty_snapshot = decoded.snapshot_id if decoded is not None else 0
        return ListPage(
            items=[],
            next_cursor=None,
            has_more=False,
            total=0,
            newest_id=empty_snapshot or None,
            newer_than=0,
        )

    if decoded is not None:
        snapshot_id = decoded.snapshot_id
    else:
        snapshot_id = (
            await session.execute(
                select(func.max(TravelPlace.place_id)).where(*where)
            )
        ).scalar() or 0
    total = (
        await session.execute(
            select(func.count())
            .select_from(TravelPlace)
            .where(*where, TravelPlace.place_id <= snapshot_id)
        )
    ).scalar() or 0
    newer_than = 0
    if newer_than_id is not None:
        newer_than = (
            await session.execute(
                select(func.count())
                .select_from(TravelPlace)
                .where(*where, TravelPlace.place_id > newer_than_id)
            )
        ).scalar() or 0

    page_places = await _ordered_place_query(
        session,
        sort=sort,
        where_conditions=where,
        snapshot_id=snapshot_id,
        keyset_keys=decoded.keys if decoded is not None else None,
        limit=limit + 1,
    )
    has_more = len(page_places) > limit
    items = await _build_summaries_for_places(session, page_places[:limit])
    next_cursor = (
        encode_cursor(
            fingerprint=fingerprint,
            snapshot_id=snapshot_id,
            keys=_place_summary_cursor_key(items[-1], sort),
        )
        if has_more and items
        else None
    )
    return ListPage(
        items=items,
        next_cursor=next_cursor,
        has_more=has_more,
        total=total,
        newest_id=snapshot_id or None,
        newer_than=newer_than,
    )


async def _list_mentions_by_place(
    session: AsyncSession, *, place_ids: list[int]
) -> dict[int, list[PlaceSourceMention]]:
    if not place_ids:
        return {}
    stmt = (
        select(VideoPlaceMapping, YoutubeVideo)
        .join(YoutubeVideo, VideoPlaceMapping.video_id == YoutubeVideo.video_id)
        .where(VideoPlaceMapping.place_id.in_(place_ids))
        .order_by(VideoPlaceMapping.id.desc())
    )
    result = await session.execute(stmt)
    mentions_by_place: dict[int, list[PlaceSourceMention]] = {}
    for mapping, video in result.all():
        mentions_by_place.setdefault(mapping.place_id, []).append(
            PlaceSourceMention(
                mapping_id=mapping.id,
                video_id=video.video_id,
                video_title=video.title,
                video_url=video.url,
                channel_id=video.channel_id,
                channel_name=video.channel_name,
                timestamp_start=mapping.timestamp_start,
                timestamp_end=mapping.timestamp_end,
                ai_summary=mapping.ai_summary,
                speaker_note=mapping.speaker_note,
            )
        )
    return mentions_by_place


async def _filtered_place_ids(
    session: AsyncSession,
    *,
    channel_id: str | None,
    playlist_id: str | None,
    keyword: str | None,
    video_id: str | None = None,
) -> set[int] | None:
    """출처 필터(유튜버/재생목록/검색어/영상)에 해당하는 place_id 집합. 필터 없으면 None."""
    if not (channel_id or playlist_id or keyword or video_id):
        return None
    stmt = select(VideoPlaceMapping.place_id).join(
        YoutubeVideo, VideoPlaceMapping.video_id == YoutubeVideo.video_id
    )
    if channel_id:
        stmt = stmt.where(
            or_(
                VideoPlaceMapping.source_channel_id == channel_id,
                YoutubeVideo.channel_id == channel_id,
            )
        )
    if playlist_id:
        stmt = stmt.where(VideoPlaceMapping.source_playlist_id == playlist_id)
    if keyword:
        stmt = stmt.where(YoutubeVideo.source_search_query == keyword)
    if video_id:
        # 특정 영상이 언급한 장소만(작업 상세 → 결과 페이지 영상 필터).
        stmt = stmt.where(VideoPlaceMapping.video_id == video_id)
    result = await session.execute(stmt)
    return {int(pid) for pid in result.scalars().all()}


async def list_place_facets(session: AsyncSession) -> dict[str, list[dict[str, Any]]]:
    """확정 장소를 출처별(유튜버/재생목록/검색어)로 묶을 facet 목록을 반환한다.

    각 항목은 해당 출처에서 수집된 확정 장소 수(`place_count`)를 함께 제공해
    결과 보기의 그룹/필터 셀렉터를 구성할 수 있게 한다.
    """
    place_count = func.count(distinct(VideoPlaceMapping.place_id))

    channel_stmt = (
        select(YoutubeVideo.channel_id, YoutubeChannel.title, place_count)
        .select_from(VideoPlaceMapping)
        .join(YoutubeVideo, VideoPlaceMapping.video_id == YoutubeVideo.video_id)
        .join(
            YoutubeChannel,
            YoutubeVideo.channel_id == YoutubeChannel.channel_id,
            isouter=True,
        )
        .where(YoutubeVideo.channel_id.isnot(None))
        .group_by(YoutubeVideo.channel_id, YoutubeChannel.title)
        .order_by(place_count.desc())
    )
    playlist_stmt = (
        select(VideoPlaceMapping.source_playlist_id, YoutubePlaylist.title, place_count)
        .join(
            YoutubePlaylist,
            VideoPlaceMapping.source_playlist_id == YoutubePlaylist.playlist_id,
            isouter=True,
        )
        .where(VideoPlaceMapping.source_playlist_id.isnot(None))
        .group_by(VideoPlaceMapping.source_playlist_id, YoutubePlaylist.title)
        .order_by(place_count.desc())
    )
    keyword_stmt = (
        select(YoutubeVideo.source_search_query, place_count)
        .select_from(VideoPlaceMapping)
        .join(YoutubeVideo, VideoPlaceMapping.video_id == YoutubeVideo.video_id)
        .where(YoutubeVideo.source_search_query.isnot(None))
        .group_by(YoutubeVideo.source_search_query)
        .order_by(place_count.desc())
    )
    category_stmt = (
        select(TravelPlace.category, func.count(TravelPlace.place_id))
        .where(TravelPlace.category.isnot(None))
        .group_by(TravelPlace.category)
        .order_by(func.count(TravelPlace.place_id).desc(), TravelPlace.category)
    )

    channels = [
        {"id": cid, "title": title or cid, "place_count": int(cnt)}
        for cid, title, cnt in (await session.execute(channel_stmt)).all()
    ]
    playlists = [
        {"id": pid, "title": title or pid, "place_count": int(cnt)}
        for pid, title, cnt in (await session.execute(playlist_stmt)).all()
    ]
    keywords = [
        {"value": kw, "place_count": int(cnt)}
        for kw, cnt in (await session.execute(keyword_stmt)).all()
    ]
    categories = [
        {"value": category, "place_count": int(cnt)}
        for category, cnt in (await session.execute(category_stmt)).all()
        if category
    ]
    district_rows = (
        await session.execute(
            select(
                TravelPlace.sigungu_code,
                TravelPlace.sigungu_name,
                func.count(TravelPlace.place_id),
            )
            .where(TravelPlace.sigungu_code.isnot(None))
            .group_by(TravelPlace.sigungu_code, TravelPlace.sigungu_name)
            .order_by(func.count(TravelPlace.place_id).desc(), TravelPlace.sigungu_name)
        )
    ).all()
    districts = [
        {
            "value": code,
            "label": name or code,
            "place_count": int(cnt),
        }
        for code, name, cnt in district_rows
        if code
    ]
    fallback_place_rows = (
        await session.execute(
            select(
                TravelPlace.official_address,
                TravelPlace.road_address,
                TravelPlace.place_id,
            )
            .where(TravelPlace.sigungu_code.is_(None))
        )
    ).all()
    fallback_counts: dict[str, int] = {}
    for official_address, road_address, _place_id in fallback_place_rows:
        label = _district_label_from_address(road_address or official_address)
        if not label:
            continue
        fallback_counts[label] = fallback_counts.get(label, 0) + 1
    districts.extend(
        {"value": label, "label": label, "place_count": count}
        for label, count in sorted(
            fallback_counts.items(), key=lambda item: (-item[1], item[0])
        )
    )
    return {
        "channels": channels,
        "playlists": playlists,
        "keywords": keywords,
        "categories": categories,
        "districts": districts,
    }


async def list_review_source_facets(
    session: AsyncSession,
    *,
    is_domestic: bool | None = None,
    status: ReviewCandidateStatus = ReviewCandidateStatus.NEEDS_REVIEW,
    query: str | None = None,
    queue_reason: QueueReason | None = None,
    source_kind: EvidenceSourceKind | None = None,
    grounding_status: GroundingStatus | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """검수 큐의 **후보 provenance** 기반 출처 facet을 반환한다(T-187).

    `list_place_facets`(확정 장소 기반)와 달리, 여기서는 아직 확정 장소가 없는
    검수 후보의 출처(유튜버/재생목록/검색어)도 노출한다. 각 항목의
    `candidate_count`는 현재 목록 filter(국내 여부·상태·대기 사유·후보 출처·
    원문 근거·검색어)를 그대로 반영하되, **그룹 차원 자체(channel/playlist/
    keyword 선택)는 제외**해 사용자가 그룹을 자유롭게 전환할 수 있게 한다.
    """

    def base():
        return _unmatched_candidates_stmt(
            channel_id=None,
            playlist_id=None,
            keyword=None,
            query=query,
            is_domestic=is_domestic,
            status=status,
            queue_reason=queue_reason,
            source_kind=source_kind,
            grounding_status=grounding_status,
        )

    candidate_count = func.count(distinct(ExtractedPlaceCandidate.id))
    # 후보의 채널 출처는 후보 자체 provenance를 우선하고 없으면 영상의 채널을 쓴다.
    channel_expr = func.coalesce(
        ExtractedPlaceCandidate.source_channel_id, YoutubeVideo.channel_id
    )

    channel_stmt = (
        base()
        .with_only_columns(channel_expr.label("value"), candidate_count)
        .where(channel_expr.isnot(None))
        .group_by(channel_expr)
        .order_by(candidate_count.desc(), channel_expr)
    )
    playlist_stmt = (
        base()
        .with_only_columns(
            ExtractedPlaceCandidate.source_playlist_id.label("value"),
            candidate_count,
        )
        .where(ExtractedPlaceCandidate.source_playlist_id.isnot(None))
        .group_by(ExtractedPlaceCandidate.source_playlist_id)
        .order_by(candidate_count.desc(), ExtractedPlaceCandidate.source_playlist_id)
    )
    keyword_stmt = (
        base()
        .with_only_columns(
            YoutubeVideo.source_search_query.label("value"), candidate_count
        )
        .where(YoutubeVideo.source_search_query.isnot(None))
        .group_by(YoutubeVideo.source_search_query)
        .order_by(candidate_count.desc(), YoutubeVideo.source_search_query)
    )

    channel_rows = (await session.execute(channel_stmt)).all()
    playlist_rows = (await session.execute(playlist_stmt)).all()
    keyword_rows = (await session.execute(keyword_stmt)).all()

    channel_titles: dict[str, str | None] = {}
    channel_ids = [value for value, _ in channel_rows]
    if channel_ids:
        channel_titles = {
            cid: title
            for cid, title in (
                await session.execute(
                    select(YoutubeChannel.channel_id, YoutubeChannel.title).where(
                        YoutubeChannel.channel_id.in_(channel_ids)
                    )
                )
            ).all()
        }
    playlist_titles: dict[str, str | None] = {}
    playlist_ids = [value for value, _ in playlist_rows]
    if playlist_ids:
        playlist_titles = {
            pid: title
            for pid, title in (
                await session.execute(
                    select(YoutubePlaylist.playlist_id, YoutubePlaylist.title).where(
                        YoutubePlaylist.playlist_id.in_(playlist_ids)
                    )
                )
            ).all()
        }

    return {
        "channels": [
            {
                "value": value,
                "label": channel_titles.get(value) or value,
                "candidate_count": int(count),
            }
            for value, count in channel_rows
        ],
        "playlists": [
            {
                "value": value,
                "label": playlist_titles.get(value) or value,
                "candidate_count": int(count),
            }
            for value, count in playlist_rows
        ],
        "keywords": [
            {"value": value, "label": value, "candidate_count": int(count)}
            for value, count in keyword_rows
        ],
    }


def _place_matches_result_filters(
    place: TravelPlace,
    *,
    category: str | None,
    query: str | None,
    district: str | None,
) -> bool:
    """category/query/district 필터의 Python 판정 정본.

    T-188에서 이 판정은 `_result_filter_conditions`로 SQL에 밀어 넣었지만, 함수는
    골든 비교 테스트가 SQL 결과를 대조하는 참조 오라클로 남겨 둔다(단일 의미 출처).
    """
    if category and (place.category or "") != category:
        return False
    if district:
        place_district = place.sigungu_code or _district_label_from_address(
            place.road_address or place.official_address
        )
        if place_district != district:
            return False
    if query:
        needle = query.strip().lower()
        if needle and needle not in _place_search_text(place).lower():
            return False
    return True


def _district_label_from_address(address: str | None) -> str | None:
    if not address:
        return None
    parts = address.split()
    if len(parts) < 2:
        return None
    return " ".join(parts[:2])


def _place_summary_sort_key(sort: str):
    if sort == "mention_count":
        return lambda item: (
            -item.mention_count,
            -item.source_channel_count,
            item.place.name,
            -item.place.place_id,
        )
    if sort == "name":
        return lambda item: (item.place.name, -item.place.place_id)
    if sort == "category":
        return lambda item: (
            item.place.category or "미분류",
            item.place.name,
            -item.place.place_id,
        )
    return lambda item: (-item.place.place_id,)


async def search_places(
    session: AsyncSession,
    *,
    query: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    radius_meters: float | None = None,
    category: str | None = None,
    limit: int = 20,
) -> list[tuple[TravelPlace, float | None]]:
    """검색어·카테고리·반경 조건으로 장소를 조회한다."""
    if radius_meters is not None:
        if lat is None or lng is None:
            raise ValueError("반경 검색에는 lat/lng가 모두 필요하다")
        radius_results = await find_places_within_radius(
            session, lat=lat, lng=lng, radius_meters=radius_meters, limit=max(limit, 100)
        )
        filtered: list[tuple[TravelPlace, float | None]] = []
        needle = query.strip() if query else None
        for place, distance in radius_results:
            if category and place.category != category:
                continue
            if needle and needle not in _place_search_text(place):
                continue
            filtered.append((place, distance))
            if len(filtered) >= limit:
                break
        return filtered

    stmt = select(TravelPlace).order_by(TravelPlace.place_id.desc()).limit(limit)
    if query:
        pattern = f"%{query.strip()}%"
        stmt = stmt.where(
            or_(
                TravelPlace.name.like(pattern),
                TravelPlace.official_address.like(pattern),
                TravelPlace.road_address.like(pattern),
                TravelPlace.description.like(pattern),
            )
        )
    if category:
        stmt = stmt.where(TravelPlace.category == category)
    result = await session.execute(stmt)
    return [(place, None) for place in result.scalars().all()]


def _place_search_text(place: TravelPlace) -> str:
    return " ".join(
        value
        for value in (
            place.name,
            place.official_address,
            place.road_address,
            place.description,
            place.gemini_enriched_description,
        )
        if value
    )


async def get_place(session: AsyncSession, place_id: int) -> TravelPlace | None:
    """확정 장소 1건을 조회한다."""
    return await session.get(TravelPlace, place_id)


async def get_place_video_mappings(
    session: AsyncSession, *, place_id: int
) -> list[VideoPlaceMapping]:
    """장소와 연결된 영상 매핑을 최신순으로 조회한다."""
    stmt = (
        select(VideoPlaceMapping)
        .where(VideoPlaceMapping.place_id == place_id)
        .order_by(VideoPlaceMapping.id.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_videos_by_ids(
    session: AsyncSession, video_ids: list[str]
) -> dict[str, YoutubeVideo]:
    """video_id 목록을 영상 객체 dict로 반환한다."""
    if not video_ids:
        return {}
    stmt = select(YoutubeVideo).where(YoutubeVideo.video_id.in_(video_ids))
    result = await session.execute(stmt)
    return {video.video_id: video for video in result.scalars().all()}


async def list_candidates_for_place(
    session: AsyncSession, *, place_id: int
) -> list[ExtractedPlaceCandidate]:
    """확정 장소에 연결된 추출 후보를 조회한다.

    soft delete는 `matched_place_id`를 해제하므로(invariant) 조건은 방어적 명시다(T-160).
    """
    stmt = (
        select(ExtractedPlaceCandidate)
        .where(
            ExtractedPlaceCandidate.matched_place_id == place_id,
            ExtractedPlaceCandidate.deleted_at.is_(None),
        )
        .order_by(ExtractedPlaceCandidate.id.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def enrich_place_admin_codes_postcommit(
    session: AsyncSession,
    *,
    place_id: int,
    audit_log_id: int | None = None,
    pending_owner: str | None = None,
) -> TravelPlace | None:
    """core/audit commit 뒤 별도 session에서 admin 보강하고 최신 장소를 다시 읽는다.

    호출자 session의 read transaction도 외부 HTTP 전에 닫으며 rollback하지 않는다.
    보강 실패나 동시 장소 삭제는 이미 commit된 core/audit 결과에 영향을 주지 않는다.
    """
    await session.commit()
    if session.bind is not None:
        from ktc.etl import admin_region_service

        if (audit_log_id is None) != (pending_owner is None):
            raise ValueError("admin 보강 fencing에는 audit_log_id와 pending_owner가 모두 필요하다")
        apply_guard = (
            admin_region_service.AdminEnrichmentGuard(
                audit_log_id=audit_log_id,
                pending_owner=pending_owner,
            )
            if audit_log_id is not None and pending_owner is not None
            else None
        )
        isolated_factory = async_sessionmaker(session.bind, expire_on_commit=False)
        try:
            await admin_region_service.enrich_place_admin_codes_isolated(
                isolated_factory,
                place_id,
                apply_guard=apply_guard,
            )
        except Exception:
            await session.commit()
    latest = (
        await session.execute(
            select(TravelPlace)
            .where(TravelPlace.place_id == place_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    await session.commit()
    return latest


async def correct_place(
    session: AsyncSession,
    *,
    place_id: int,
    updates: dict[str, Any],
    commit: bool = True,
) -> TravelPlace:
    """장소명·주소·좌표·카테고리·설명을 수동 보정한다."""
    coordinate_change_requested = "latitude" in updates or "longitude" in updates
    if coordinate_change_requested:
        # 기존 장소를 다른 반경으로 옮기는 동안 신규 장소의 최종 중복 조회가 구 geom을
        # 보면 동일 좌표 장소가 이중 생성될 수 있다. 좌표 보정만 lifecycle lock에 참여한다.
        await acquire_place_lifecycle_lock(session)
    # T-171 dirty outbox와 feature sync가 candidate/place snapshot을 읽으므로 place를
    # 잠그기 전에 export lock을 선취한다. 좌표 보정은 lifecycle → export 순서다.
    await feature_export_service.acquire_feature_export_lock(session)
    # 같은 session의 identity map에 남은 구버전 장소를 수정하지 않도록 최신 행을
    # 강제로 다시 적재하고 잠근다. 좌표 보정과 자동 지오코딩은 lifecycle lock을
    # 공유하고, 장소 단독 보정은 그 뒤 place만 잠근다.
    place = (
        await session.execute(
            select(TravelPlace)
            .where(TravelPlace.place_id == place_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if place is None:
        raise ValueError(f"place not found: {place_id}")

    allowed = {
        "name",
        "description",
        "gemini_enriched_description",
        "description_review_status",
        "official_address",
        "road_address",
        "latitude",
        "longitude",
        "api_source",
        "category",
        "is_geocoded",
    }
    # 강제 카테고리 코드(드롭다운): 표시 category(label)와 category_code_suggestion을 덮어쓴다.
    forced_code = category_catalog.normalize_code(updates.pop("category_code", None))
    applied = {key: value for key, value in updates.items() if key in allowed}
    if not applied and forced_code is None:
        raise ValueError("보정할 필드가 필요하다")
    for key, value in applied.items():
        setattr(place, key, value)
    if forced_code:
        place.category_code_suggestion = forced_code
        forced_label = category_catalog.label_for(forced_code)
        if forced_label:
            place.category = forced_label
    if ("latitude" in applied or "longitude" in applied) and "is_geocoded" not in applied:
        place.is_geocoded = True
    should_enrich_admin = (
        ("latitude" in applied or "longitude" in applied) and place.is_geocoded
    )
    if should_enrich_admin:
        await sync_place_geometry(session, place.place_id, place.latitude, place.longitude)
        place.sigungu_code = None
        place.sigungu_name = None
        place.legal_dong_code = None
        place.legal_dong_name = None
    place.last_reviewed_at = utcnow()
    # 확정 장소 보정이 export payload(이름·좌표·주소·카테고리·설명)를 바꾸므로, 이 장소를
    # 매칭한 후보 전부를 dirty로 표시해 다음 공급 GET에 반영한다(T-171, 공용 헬퍼).
    await feature_export_service.mark_place_candidates_dirty(
        session, place.place_id, reason="correct_place"
    )
    if commit:
        corrected_place_id = place.place_id
        await session.commit()
        if should_enrich_admin:
            latest = await enrich_place_admin_codes_postcommit(
                session, place_id=corrected_place_id
            )
            if latest is None:
                raise ValueError(f"place not found: {corrected_place_id}")
            place = latest
        else:
            await session.refresh(place)
            await session.commit()
    return place


def _merge_place_lifecycle_origin(source: TravelPlace, target: TravelPlace) -> None:
    """병합 장소의 보존 강도를 `persistent > legacy > candidate`로 합성한다."""
    rank = {
        PlaceLifecycleOrigin.CANDIDATE_CREATED.value: 0,
        PlaceLifecycleOrigin.LEGACY_UNKNOWN.value: 1,
        PlaceLifecycleOrigin.PERSISTENT.value: 2,
    }
    source_origin = str(
        getattr(source.lifecycle_origin, "value", source.lifecycle_origin)
    )
    target_origin = str(
        getattr(target.lifecycle_origin, "value", target.lifecycle_origin)
    )
    if rank[source_origin] <= rank[target_origin]:
        # 둘 다 candidate_created인 경우도 target의 origin_candidate_id를 유지한다.
        return
    target.lifecycle_origin = source_origin
    target.origin_candidate_id = (
        source.origin_candidate_id
        if source_origin == PlaceLifecycleOrigin.CANDIDATE_CREATED.value
        else None
    )


async def merge_places(
    session: AsyncSession,
    *,
    source_place_id: int,
    target_place_id: int,
    commit: bool = True,
) -> TravelPlace:
    """중복 장소를 병합하고 source 장소를 삭제한다."""
    if source_place_id == target_place_id:
        raise ValueError("source_place_id와 target_place_id는 달라야 한다")

    # 장소 lifecycle 전역 lock 뒤 export writer lock을 선취하고 모든 관련 행을
    # mutation/autoflush 전에 candidate -> place -> mapping -> asset 순으로 잠근다.
    # sync가 source 장소 snapshot으로 payload를 만들고 있는 동안 merge가 source를
    # 삭제하면 null/fallback UPSERT가 생길 수 있으므로 174 -> 175 순서를 공유한다.
    # geocode post-core 검증과 delete/authoritative 경로도 candidate를 먼저 잠그므로,
    # merge가 mapping을 먼저 UPDATE한 뒤 candidate를 기다리는 역순 deadlock을 만들지 않는다.
    await acquire_place_lifecycle_lock(session)
    await feature_export_service.acquire_feature_export_lock(session)
    candidate_result = await session.execute(
        select(ExtractedPlaceCandidate)
        .where(
            ExtractedPlaceCandidate.matched_place_id == source_place_id,
            ExtractedPlaceCandidate.deleted_at.is_(None),
        )
        .order_by(ExtractedPlaceCandidate.id.asc())
        .with_for_update()
        .execution_options(populate_existing=True, autoflush=False)
    )
    moved_candidates = list(candidate_result.scalars().all())

    place_result = await session.execute(
        select(TravelPlace)
        .where(TravelPlace.place_id.in_([source_place_id, target_place_id]))
        .order_by(TravelPlace.place_id.asc())
        .with_for_update()
        .execution_options(populate_existing=True, autoflush=False)
    )
    places = {place.place_id: place for place in place_result.scalars().all()}
    source = places.get(source_place_id)
    target = places.get(target_place_id)
    if source is None:
        raise ValueError(f"source place not found: {source_place_id}")
    if target is None:
        raise ValueError(f"target place not found: {target_place_id}")

    mapping_result = await session.execute(
        select(VideoPlaceMapping)
        .where(VideoPlaceMapping.place_id == source_place_id)
        .order_by(VideoPlaceMapping.id.asc())
        .with_for_update()
        .execution_options(populate_existing=True, autoflush=False)
    )
    moved_mappings = list(mapping_result.scalars().all())

    asset_result = await session.execute(
        select(MediaAsset)
        .where(MediaAsset.place_id == source_place_id)
        .order_by(MediaAsset.id.asc())
        .with_for_update()
        .execution_options(populate_existing=True, autoflush=False)
    )
    moved_assets = list(asset_result.scalars().all())

    # 위 lock 집합이 완성된 뒤에만 ORM mutation을 시작한다. 이후 SELECT가 없어
    # autoflush가 lock 순서를 몰래 뒤집을 여지도 없다.
    for candidate in moved_candidates:
        candidate.matched_place_id = target_place_id
    for mapping in moved_mappings:
        mapping.place_id = target_place_id
    for asset in moved_assets:
        asset.place_id = target_place_id

    target_backfilled = False
    _merge_place_lifecycle_origin(source, target)
    for field in (
        "description",
        "gemini_enriched_description",
        "official_address",
        "road_address",
        "api_source",
        "category",
        "detailed_research_content",
    ):
        if not getattr(target, field) and getattr(source, field):
            setattr(target, field, getattr(source, field))
            target_backfilled = True
    target.last_reviewed_at = utcnow()
    await session.delete(source)
    # source→target으로 재배치된 후보의 export payload(place 이름·좌표·주소)가 바뀌므로
    # 같은 트랜잭션에서 dirty로 표시한다(T-171).
    await feature_export_service.mark_candidates_dirty(
        session,
        [candidate.id for candidate in moved_candidates],
        reason="merge_places",
    )
    # target place 필드가 backfill로 실제 바뀌면, target에 이미 매칭돼 있던 co-매칭 후보들의
    # export payload도 바뀌므로 그 후보 전부를 dirty로 표시한다(golden 불변식, T-171).
    if target_backfilled:
        await feature_export_service.mark_place_candidates_dirty(
            session, target_place_id, reason="merge_target_backfill"
        )
    if commit:
        await session.commit()
        await session.refresh(target)
    return target


async def review_candidate(
    session: AsyncSession,
    *,
    candidate_id: int,
    reviewed_by: str,
    review_note: str | None = None,
    commit: bool = True,
) -> ExtractedPlaceCandidate:
    """매칭 검수 후보에 검수 메타데이터를 남긴다."""
    candidate = (
        await session.execute(
            select(ExtractedPlaceCandidate)
            .where(ExtractedPlaceCandidate.id == candidate_id)
            .with_for_update()
            .execution_options(populate_existing=True, autoflush=False)
        )
    ).scalar_one_or_none()
    if candidate is None:
        raise ValueError(f"candidate not found: {candidate_id}")
    if candidate.deleted_at is not None:
        raise CandidateResolveConflictError(
            "삭제됐거나 다른 검수자가 이미 처리한 candidate다"
        )
    if candidate.match_status != MatchStatus.NEEDS_REVIEW.value:
        raise CandidateResolveConflictError(
            "이미 해결되었거나 검수 대상이 아닌 candidate다"
        )
    candidate.reviewed_by = reviewed_by
    candidate.reviewed_at = utcnow()
    candidate.review_note = review_note
    if commit:
        await session.commit()
        await session.refresh(candidate)
    return candidate


def candidate_category_code(candidate: ExtractedPlaceCandidate) -> str | None:
    """후보의 provider evidence에 저장된 8자리 카테고리 코드를 안전하게 읽는다.

    POI 추출 단계에서 함께 받아 검증·저장한 코드다(A안). 확정 시 별도 Gemini 호출
    없이 이 값을 장소(`category_code_suggestion`)에 복사한다.
    """
    evidence = candidate.provider_evidence_json
    if not isinstance(evidence, dict):
        return None
    transcript = evidence.get("transcript")
    if not isinstance(transcript, dict):
        return None
    code = transcript.get("category_code")
    return category_catalog.normalize_code(code) if isinstance(code, str) else None


def _place_category_from_code(code: str | None) -> tuple[str, str]:
    normalized = category_catalog.normalize_code_or_unknown(code)
    return normalized, category_catalog.label_for_or_unknown(normalized)


def _place_category_for_candidate(
    candidate: ExtractedPlaceCandidate,
    *,
    forced_code: str | None = None,
) -> tuple[str, str]:
    code = category_catalog.normalize_code(forced_code) or candidate_category_code(
        candidate
    )
    return _place_category_from_code(code)


def _normalized_identity_name(value: str | None) -> str:
    """근접 자동 병합에서만 쓰는 보수적인 이름 동일성 표현."""
    return re.sub(r"[^0-9a-z가-힣]", "", (value or "").casefold())


def _review_resolutions(candidate: ExtractedPlaceCandidate) -> list[dict[str, Any]]:
    evidence = candidate.provider_evidence_json
    if not isinstance(evidence, dict):
        return []
    review = evidence.get("review")
    if not isinstance(review, dict):
        return []
    resolutions = review.get("resolutions")
    if not isinstance(resolutions, list):
        return []
    return [item for item in resolutions if isinstance(item, dict)]


def latest_candidate_resolution(
    candidate: ExtractedPlaceCandidate,
) -> dict[str, Any] | None:
    """감사 응답과 테스트에서 후보의 최신 검수 resolution을 읽는다."""
    resolutions = _review_resolutions(candidate)
    return resolutions[-1] if resolutions else None


def last_candidate_client_operation_id(
    candidate: ExtractedPlaceCandidate,
    *,
    matched_place_revision: int | None = None,
) -> str | None:
    """현재 후보·장소 snapshot과 정확히 일치하는 브라우저 작업 ID만 읽는다.

    JSONB 표식은 감사 흔적으로 남을 수 있지만 후보가 reopen/내부 mutation을 거치거나
    연결 장소만 보정돼도 더 이상 해당 브라우저 작업의 결과가 아니다. 후보 revision과
    연결 장소 ID/revision을 모두 대조해 response-loss 복구의 거짓 양성을 막는다.
    """
    evidence = candidate.provider_evidence_json
    if not isinstance(evidence, dict):
        return None
    review = evidence.get("review")
    if not isinstance(review, dict):
        return None
    operation = review.get("last_client_operation")
    if not isinstance(operation, dict):
        return None
    operation_id = operation.get("id")
    result_candidate_revision = operation.get("result_candidate_revision")
    marker_place_id = operation.get("matched_place_id")
    marker_place_revision = operation.get("matched_place_revision")
    if (
        not isinstance(operation_id, str)
        or not operation_id
        or not _positive_int(result_candidate_revision, maximum=_MAX_BIGINT)
        or result_candidate_revision != candidate.state_revision
        or marker_place_id != candidate.matched_place_id
    ):
        return None
    if candidate.matched_place_id is None:
        if marker_place_revision is not None or matched_place_revision is not None:
            return None
    elif (
        not _positive_int(marker_place_id, maximum=MAX_DB_INTEGER_ID)
        or not _positive_int(marker_place_revision, maximum=_MAX_BIGINT)
        or marker_place_revision != matched_place_revision
    ):
        return None
    return operation_id


def _record_last_client_operation(
    candidate: ExtractedPlaceCandidate,
    *,
    client_operation_id: UUID,
    action: str,
    occurred_at,
    matched_place_revision: int | None,
) -> None:
    """다음 후보 UPDATE 결과와 연결 장소 snapshot을 묶은 복구 표식을 기록한다."""
    current = deepcopy(candidate.provider_evidence_json)
    evidence = current if isinstance(current, dict) else {}
    review = evidence.get("review")
    review = deepcopy(review) if isinstance(review, dict) else {}
    review["schema_version"] = 1
    review["last_client_operation"] = {
        "id": str(client_operation_id),
        "action": action,
        "timestamp": occurred_at.isoformat(),
        # 이 JSONB 대입을 포함한 단일 UPDATE에서 DB trigger가 정확히 1 증가시킨다.
        "result_candidate_revision": candidate.state_revision + 1,
        "matched_place_id": candidate.matched_place_id,
        "matched_place_revision": matched_place_revision,
    }
    evidence["review"] = review
    candidate.provider_evidence_json = evidence


async def _provider_identities_for_places(
    session: AsyncSession, place_ids: list[int]
) -> dict[int, set[tuple[str, str]]]:
    """기존 후보 검수 이력에서 장소별 `(provider, native_id)`를 보수적으로 읽는다.

    soft delete는 `matched_place_id`를 해제하므로(invariant) 조건은 방어적 명시다(T-160).
    """
    if not place_ids:
        return {}
    rows = (
        await session.execute(
            select(ExtractedPlaceCandidate).where(
                ExtractedPlaceCandidate.matched_place_id.in_(place_ids),
                ExtractedPlaceCandidate.deleted_at.is_(None),
            )
        )
    ).scalars()
    identities: dict[int, set[tuple[str, str]]] = {}
    for candidate in rows:
        if candidate.matched_place_id is None:
            continue
        for resolution in _review_resolutions(candidate):
            final = resolution.get("final")
            if (
                not isinstance(final, dict)
                or final.get("place_id") != candidate.matched_place_id
            ):
                continue
            selection = resolution.get("selection")
            if not isinstance(selection, dict):
                continue
            provider = selection.get("provider")
            native_id = selection.get("native_id")
            if isinstance(provider, str) and isinstance(native_id, str) and native_id:
                identities.setdefault(candidate.matched_place_id, set()).add(
                    (provider, native_id)
                )
    return identities


def _nearby_place_payload(
    place: TravelPlace,
    distance_m: float,
    *,
    final_name: str,
    provider_identity: tuple[str, str] | None,
    known_identities: set[tuple[str, str]],
) -> dict[str, Any]:
    name_compatible = bool(
        _normalized_identity_name(final_name)
        and _normalized_identity_name(final_name) == _normalized_identity_name(place.name)
    )
    provider_id_match = (
        provider_identity in known_identities if provider_identity is not None else None
    )
    return {
        "place_id": place.place_id,
        "name": place.name,
        "official_address": place.official_address,
        "road_address": place.road_address,
        "latitude": place.latitude,
        "longitude": place.longitude,
        "api_source": place.api_source,
        "distance_m": round(distance_m, 1),
        "name_compatible": name_compatible,
        "provider_id_match": provider_id_match,
    }


def _append_resolution_evidence(
    candidate: ExtractedPlaceCandidate,
    *,
    action: str,
    reviewed_by: str,
    reviewer_type: str,
    resolved_at,
    selected_hit: dict[str, Any] | None,
    place: TravelPlace | None,
    nearby_decision: str | None,
    nearby_place_ids: list[int],
    client_operation_id: UUID | None,
) -> dict[str, Any]:
    """기존 evidence namespace를 보존하며 버전된 검수 이력을 누적한다."""
    current = deepcopy(candidate.provider_evidence_json)
    evidence = current if isinstance(current, dict) else {}
    review = evidence.get("review")
    review = deepcopy(review) if isinstance(review, dict) else {}
    resolutions = review.get("resolutions")
    resolutions = deepcopy(resolutions) if isinstance(resolutions, list) else []

    if selected_hit:
        selection = {
            "kind": "provider_hit",
            "provider": selected_hit.get("provider"),
            "native_id": selected_hit.get("native_id"),
            "query": selected_hit.get("query"),
            "searched_at": selected_hit.get("searched_at"),
            "selected_at": selected_hit.get("selected_at"),
            "original": {
                "name": selected_hit.get("name"),
                "official_address": selected_hit.get("address"),
                "road_address": selected_hit.get("road_address"),
                "latitude": selected_hit.get("latitude"),
                "longitude": selected_hit.get("longitude"),
                "category": selected_hit.get("category"),
            },
        }
    else:
        selection = {
            "kind": "manual",
            "provider": None,
            "native_id": None,
            "query": None,
            "searched_at": None,
            "selected_at": None,
            "original": {
                "name": candidate.ai_place_name,
                "official_address": None,
                "road_address": None,
                "latitude": None,
                "longitude": None,
                "category": candidate.candidate_category,
            },
        }

    final = None
    if place is not None:
        final = {
            "place_id": place.place_id,
            "name": place.name,
            "official_address": place.official_address,
            "road_address": place.road_address,
            "latitude": place.latitude,
            "longitude": place.longitude,
            "category": place.category,
            "category_code": place.category_code_suggestion,
            "api_source": place.api_source,
        }
    resolution = {
        "schema_version": 1,
        "resolution_id": str(uuid4()),
        "action": action,
        "resolved_at": resolved_at.isoformat(),
        "reviewer": {"actor_type": reviewer_type, "actor_id": reviewed_by},
        "selection": selection,
        "final": final,
        "nearby": {
            "decision": nearby_decision or "none",
            "selected_place_id": (
                place.place_id
                if nearby_decision == "merge_existing" and place
                else None
            ),
            "candidate_place_ids": nearby_place_ids,
        },
    }
    if client_operation_id is not None:
        resolution["client_operation_id"] = str(client_operation_id)
    resolutions.append(resolution)
    review["schema_version"] = 1
    review["resolutions"] = resolutions
    evidence["review"] = review
    candidate.provider_evidence_json = evidence
    return resolution


async def resolve_candidate(
    session: AsyncSession,
    *,
    candidate_id: int,
    action: str,
    reviewed_by: str,
    reviewer_type: str | None = None,
    review_note: str | None = None,
    place_id: int | None = None,
    place_data: dict[str, Any] | None = None,
    resolution_evidence: dict[str, Any] | None = None,
    duplicate_resolution: str | None = None,
    duplicate_place_id: int | None = None,
    expected_revision: int | None = None,
    client_operation_id: UUID | None = None,
    commit: bool = True,
) -> tuple[ExtractedPlaceCandidate, TravelPlace | None, VideoPlaceMapping | None]:
    """매칭 실패 후보를 기존 장소, 신규 장소, 제외 중 하나로 해결한다.

    신규 장소(`create_place`)의 8자리 category 코드 제안은 POI 추출 단계에서 후보
    evidence에 함께 저장해 둔 값을 복사한다(별도 Gemini 호출 없음, A안).
    soft delete된 후보는 해결할 수 없다(먼저 reopen 필요, T-160).
    """
    # 장소를 연결하거나 만드는 action은 candidate row보다 먼저 lifecycle lock을 잡는다.
    # 모든 action은 T-171 dirty outbox/sync와 export lock을 공유해, 이후 공통 순서를
    # lifecycle advisory -> export advisory -> candidate -> place -> mapping으로 유지한다.
    if action in {"match_existing", "create_place"}:
        await acquire_place_lifecycle_lock(session)
    await feature_export_service.acquire_feature_export_lock(session)
    candidate = (
        await session.execute(
            select(ExtractedPlaceCandidate)
            .where(ExtractedPlaceCandidate.id == candidate_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if candidate is None:
        raise ValueError(f"candidate not found: {candidate_id}")
    _require_candidate_revision(candidate, expected_revision)
    if candidate.deleted_at is not None:
        raise CandidateResolveConflictError(
            "삭제됐거나 다른 검수자가 이미 처리한 candidate다"
        )
    if candidate.match_status != MatchStatus.NEEDS_REVIEW:
        raise CandidateResolveConflictError(
            "이미 해결되었거나 검수 대상이 아닌 candidate다"
        )

    data = place_data or {}
    selected_provider = (
        resolution_evidence.get("provider") if resolution_evidence else None
    )
    requested_api_source = data.get("api_source")
    if selected_provider == "google" or requested_api_source == "google":
        raise ProviderPersistenceDisabled(
            "provider 정책 결정 전에는 Google Places 결과를 저장할 수 없다"
        )
    if selected_provider and requested_api_source not in (None, selected_provider):
        raise ValueError("selected_hit.provider와 api_source가 일치해야 한다")
    if not selected_provider and requested_api_source not in (None, "manual"):
        raise ValueError("외부 api_source에는 selected_hit 근거가 필요하다")
    api_source = selected_provider or requested_api_source or "manual"

    place: TravelPlace | None = None
    mapping: VideoPlaceMapping | None = None
    nearby_decision: str | None = None
    nearby_place_ids: list[int] = []
    # 재사용(기존) place의 payload 필드가 실제로 바뀌었는지. 바뀌면 그 place의 co-매칭 후보
    # 전부를 dirty로 표시해야 golden 불변식을 지킨다(T-171).
    reused_place_field_changed = False
    if action == "ignore":
        candidate.match_status = MatchStatus.IGNORED
        candidate.feature_export_status = FeatureExportStatus.REJECTED.value
    elif action == "match_existing":
        if place_id is None:
            raise ValueError("기존 장소 매칭에는 place_id가 필요하다")
        # 후보를 먼저 잠근 뒤 최신 장소 행을 잠가 stale 사용자 보정을 덮지 않는다.
        place = (
            await session.execute(
                select(TravelPlace)
                .where(TravelPlace.place_id == place_id)
                .execution_options(populate_existing=True)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if place is None:
            raise ValueError(f"place not found: {place_id}")
        code = candidate_category_code(candidate)
        if code and place.category_code_suggestion in (
            None,
            category_catalog.UNKNOWN_CATEGORY_CODE,
        ):
            if place.category_code_suggestion != code:
                reused_place_field_changed = True
            place.category_code_suggestion = code
            place.category = category_catalog.label_for_or_unknown(code)
        candidate.match_status = MatchStatus.USER_CORRECTED
        candidate.matched_place_id = place.place_id
        candidate.feature_export_status = FeatureExportStatus.READY.value
    elif action == "create_place":
        required = ("name", "latitude", "longitude")
        missing = [key for key in required if data.get(key) is None]
        if missing:
            raise ValueError(f"신규 장소 생성에는 {', '.join(missing)} 값이 필요하다")
        dups = await find_duplicate_candidates(
            session,
            lat=data["latitude"],
            lng=data["longitude"],
            populate_existing=True,
            for_update=True,
        )
        nearby_place_ids = [item.place_id for item, _ in dups]
        identities = await _provider_identities_for_places(session, nearby_place_ids)
        provider_identity = None
        if selected_provider and resolution_evidence and resolution_evidence.get("native_id"):
            provider_identity = (
                selected_provider,
                str(resolution_evidence["native_id"]),
            )
        nearby_payloads = [
            _nearby_place_payload(
                duplicate,
                distance,
                final_name=str(data["name"]),
                provider_identity=provider_identity,
                known_identities=identities.get(duplicate.place_id, set()),
            )
            for duplicate, distance in dups
        ]
        automatic_matches = [
            payload
            for payload in nearby_payloads
            if payload["name_compatible"]
            and payload["provider_id_match"] is True
            and payload["distance_m"] <= 30.0
        ]
        if duplicate_resolution == "merge_existing":
            selected = next(
                (
                    duplicate
                    for duplicate, _ in dups
                    if duplicate.place_id == duplicate_place_id
                ),
                None,
            )
            if selected is None:
                raise ValueError("선택한 duplicate_place_id가 현재 100m 후보에 없다")
            place = selected
            nearby_decision = "merge_existing"
        elif duplicate_resolution == "create_new":
            nearby_decision = "create_new"
        elif len(automatic_matches) == 1:
            automatic_id = automatic_matches[0]["place_id"]
            place = next(item for item, _ in dups if item.place_id == automatic_id)
            nearby_decision = "merge_existing"
        elif dups:
            raise NearbyPlaceConfirmationRequired(nearby_payloads)

        forced_code = category_catalog.normalize_code(data.get("category_code"))
        selected_code, selected_label = _place_category_for_candidate(
            candidate, forced_code=forced_code
        )
        if place is not None:
            if (
                forced_code
                or place.category_code_suggestion
                in (None, category_catalog.UNKNOWN_CATEGORY_CODE)
            ):
                if (
                    place.category_code_suggestion != selected_code
                    or place.category != selected_label
                ):
                    reused_place_field_changed = True
                place.category_code_suggestion = selected_code
                place.category = selected_label
        else:
            place = TravelPlace(
                lifecycle_origin=PlaceLifecycleOrigin.CANDIDATE_CREATED.value,
                origin_candidate_id=candidate.id,
                name=data["name"],
                description=data.get("description"),
                gemini_enriched_description=data.get("gemini_enriched_description"),
                official_address=data.get("official_address"),
                road_address=data.get("road_address"),
                latitude=data["latitude"],
                longitude=data["longitude"],
                api_source=api_source,
                category=selected_label,
                category_code_suggestion=selected_code,
                is_geocoded=True,
                last_reviewed_at=utcnow(),
            )
            session.add(place)
            await session.flush()
            await sync_place_geometry(
                session, place.place_id, place.latitude, place.longitude
            )
        candidate.match_status = MatchStatus.USER_CORRECTED
        candidate.matched_place_id = place.place_id
        candidate.feature_export_status = FeatureExportStatus.READY.value
    else:
        raise ValueError(f"지원하지 않는 후보 해결 action: {action}")

    reviewed_at = utcnow()
    candidate.reviewed_by = reviewed_by
    candidate.reviewed_at = reviewed_at
    candidate.review_note = review_note
    _append_resolution_evidence(
        candidate,
        action=action,
        reviewed_by=reviewed_by,
        reviewer_type=reviewer_type or "internal",
        resolved_at=reviewed_at,
        selected_hit=resolution_evidence,
        place=place,
        nearby_decision=nearby_decision,
        nearby_place_ids=nearby_place_ids,
        client_operation_id=client_operation_id,
    )
    if place is not None:
        mapping = await _ensure_candidate_mapping(session, candidate, place)
    # export payload에 영향을 주는 상태 전이(ignore=reject, match/create=upsert)를 같은
    # 트랜잭션의 dirty outbox에 기록한다(T-171). 다음 공급 GET이 이 후보만 동기화한다.
    await feature_export_service.mark_candidates_dirty(
        session, [candidate.id], reason=f"resolve:{action}"
    )
    # 재사용 place의 카테고리 필드가 실제 바뀌면 그 place의 co-매칭 후보 전부도 stale해지므로
    # 함께 dirty로 표시한다(golden 불변식, T-171).
    if reused_place_field_changed and place is not None:
        await feature_export_service.mark_place_candidates_dirty(
            session, place.place_id, reason="resolve_reuse_backfill"
        )
    if commit:
        resolved_place_id = place.place_id if place is not None else None
        await session.commit()
        if resolved_place_id is not None:
            await enrich_place_admin_codes_postcommit(
                session, place_id=resolved_place_id
            )
        candidate, place, mapping = await authoritative_candidate_resolution(
            session, candidate_id=candidate_id
        )
    return candidate, place, mapping


async def finalize_candidate_client_operation(
    session: AsyncSession,
    *,
    candidate_id: int,
    client_operation_id: UUID,
    action: str,
    expected_candidate_revision: int,
    expected_review_state: str,
    expected_matched_place_id: int | None,
    expected_matched_place_revision: int | None,
    commit: bool = True,
) -> tuple[ExtractedPlaceCandidate, TravelPlace | None]:
    """post-core 응답 복구 표식을 후보·장소의 정확한 최종 snapshot에 붙인다.

    resolve core와 감사 로그를 먼저 확정하고 느린 행정구역 보강까지 끝낸 뒤 호출한다.
    그 사이 후보가 reopen/내부 mutation을 거쳤거나 장소가 다시 보정됐다면 안전하게
    실패해 오래된 브라우저 작업 ID를 새로운 live 상태에 붙이지 않는다.
    """
    if (expected_matched_place_id is None) != (
        expected_matched_place_revision is None
    ):
        raise ValueError("operation 표식의 장소 ID와 revision은 함께 있어야 합니다")

    # merge/delete/좌표 보정과 같은 lifecycle 경계를 먼저 통과한 뒤
    # candidate -> place 순으로 잠근다.
    await acquire_place_lifecycle_lock(session)
    candidate = (
        await session.execute(
            select(ExtractedPlaceCandidate)
            .where(ExtractedPlaceCandidate.id == candidate_id)
            .order_by(ExtractedPlaceCandidate.id.asc())
            .with_for_update()
            .execution_options(populate_existing=True, autoflush=False)
        )
    ).scalar_one_or_none()
    if candidate is None:
        raise ValueError(f"candidate not found: {candidate_id}")
    _require_candidate_revision(candidate, expected_candidate_revision)
    if candidate_review_state(candidate) != expected_review_state:
        raise CandidateResolveConflictError(
            "후보 상태가 resolve core 결과에서 변경되었습니다."
        )
    if candidate.matched_place_id != expected_matched_place_id:
        raise CandidatePlaceChangedError(
            "후보의 장소 연결이 resolve core 결과에서 변경되었습니다."
        )

    latest_resolution = latest_candidate_resolution(candidate)
    if (
        latest_resolution is None
        or latest_resolution.get("client_operation_id")
        != str(client_operation_id)
        or latest_resolution.get("action") != action
    ):
        raise CandidateResolveConflictError(
            "후보의 최신 검수 이력이 resolve core 결과에서 변경되었습니다."
        )

    place: TravelPlace | None = None
    if expected_matched_place_id is not None:
        place = (
            await session.execute(
                select(TravelPlace)
                .where(TravelPlace.place_id == expected_matched_place_id)
                .order_by(TravelPlace.place_id.asc())
                .with_for_update()
                .execution_options(populate_existing=True, autoflush=False)
            )
        ).scalar_one_or_none()
        if (
            place is None
            or place.state_revision != expected_matched_place_revision
        ):
            raise CandidatePlaceChangedError(
                "연결 장소가 행정구역 보강 결과에서 변경되었습니다."
            )

    _record_last_client_operation(
        candidate,
        client_operation_id=client_operation_id,
        action=action,
        occurred_at=utcnow(),
        matched_place_revision=expected_matched_place_revision,
    )
    await session.flush()
    await session.refresh(
        candidate,
        attribute_names=["state_revision", "provider_evidence_json"],
    )
    if (
        last_candidate_client_operation_id(
            candidate,
            matched_place_revision=expected_matched_place_revision,
        )
        != str(client_operation_id)
    ):
        raise RuntimeError("operation 표식의 결과 revision 검증에 실패했습니다")
    if commit:
        await session.commit()
    return candidate, place


async def authoritative_candidate_resolution(
    session: AsyncSession,
    *,
    candidate_id: int,
    commit: bool = True,
) -> tuple[ExtractedPlaceCandidate, TravelPlace | None, VideoPlaceMapping | None]:
    """commit 이후 후보·장소·매핑의 단일 최신 응답 snapshot을 다시 읽는다.

    resolve core나 감사 로그가 commit된 뒤 admin 보강을 기다리는 동안 영상 강제 제외,
    장소 삭제 같은 후속 쓰기가 완료될 수 있다. 호출자가 보유한 ORM 객체를 그대로
    반환하지 않고 후보를 `FOR UPDATE`로 최신화한 다음, **현재** `matched_place_id`의
    장소와 후보 매핑을 다시 읽는다. 후보 -> 장소 lock 순서를 지키며 마지막 commit으로
    응답 snapshot을 확정한다.
    """
    candidate = (
        await session.execute(
            select(ExtractedPlaceCandidate)
            .where(ExtractedPlaceCandidate.id == candidate_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if candidate is None:
        if commit:
            await session.commit()
        raise ValueError(f"candidate not found: {candidate_id}")

    place: TravelPlace | None = None
    if candidate.matched_place_id is not None:
        place = (
            await session.execute(
                select(TravelPlace)
                .where(TravelPlace.place_id == candidate.matched_place_id)
                .execution_options(populate_existing=True)
                .with_for_update()
            )
        ).scalar_one_or_none()
    mapping = (
        await session.execute(
            select(VideoPlaceMapping)
            .where(VideoPlaceMapping.place_candidate_id == candidate.id)
            .execution_options(populate_existing=True)
            .order_by(VideoPlaceMapping.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if commit:
        await session.commit()
    return candidate, place, mapping


async def _ensure_candidate_mapping(
    session: AsyncSession,
    candidate: ExtractedPlaceCandidate,
    place: TravelPlace,
) -> VideoPlaceMapping:
    # unique 제약 도입 전에는 한 candidate를 가리키는 mapping이 여러 개일 수 있다.
    # 하나만 갱신하면 candidate.matched_place_id와 나머지 mapping의 place_id가 갈라지므로
    # candidate -> place 다음 순서에서 전부 ID 순으로 잠그고 같은 연결로 정규화한다.
    stmt = (
        select(VideoPlaceMapping)
        .where(VideoPlaceMapping.place_candidate_id == candidate.id)
        .order_by(VideoPlaceMapping.id.asc())
        .with_for_update()
        .execution_options(populate_existing=True, autoflush=False)
    )
    result = await session.execute(stmt)
    mappings = list(result.scalars().all())
    if not mappings:
        mapping = VideoPlaceMapping(
            video_id=candidate.video_id,
            source_channel_id=candidate.source_channel_id,
            source_playlist_id=candidate.source_playlist_id,
            analysis_run_id=candidate.analysis_run_id,
            source_kind=candidate.source_kind,
            place_id=place.place_id,
            place_candidate_id=candidate.id,
            ai_summary=candidate.source_text,
            speaker_note=candidate.speaker_note,
            timestamp_start=candidate.timestamp_start,
            timestamp_end=candidate.timestamp_end,
            provider_evidence_json=candidate.provider_evidence_json,
            feature_export_status=candidate.feature_export_status,
        )
        session.add(mapping)
        await session.flush()
    else:
        for current in mappings:
            current.video_id = candidate.video_id
            current.place_id = place.place_id
            current.source_channel_id = candidate.source_channel_id
            current.source_playlist_id = candidate.source_playlist_id
            current.analysis_run_id = candidate.analysis_run_id
            current.source_kind = candidate.source_kind
            current.provider_evidence_json = candidate.provider_evidence_json
            current.feature_export_status = candidate.feature_export_status
        # authoritative_candidate_resolution도 최신 ID(desc)를 반환하므로 direct service와
        # REST/MCP의 mapping ID가 같은 정본을 가리키게 한다.
        mapping = mappings[-1]
    return mapping


async def ensure_candidate_mapping(
    session: AsyncSession,
    candidate: ExtractedPlaceCandidate,
    place: TravelPlace,
) -> VideoPlaceMapping:
    """후보와 확정 장소 사이의 영상 매핑을 멱등 생성한다."""
    return await _ensure_candidate_mapping(session, candidate, place)


async def delete_place(
    session: AsyncSession, *, place_id: int
) -> list[ExtractedPlaceCandidate]:
    """확정 장소를 삭제한다.

    `travel_places`를 참조하는 FK는 모두 `ondelete=NO ACTION`이라 PostgreSQL이 참조
    행이 남아 있으면 삭제를 거부한다. 따라서 참조를 명시적으로 정리한다:
    - 이 장소를 매칭한 후보는 `needs_review`로 되돌려 검수 큐로 보낸다(데이터 보존).
      `feature_export_status`도 `pending`으로 낮춰, 호출부가 `sync_feature_exports`를
      돌리면 이미 내보낸 feature가 tombstone으로 전환되도록 한다.
    - 영상-장소 매핑(`video_place_mappings`)은 삭제한다(장소가 사라짐).
    - 미디어 자산(`media_assets`)은 장소 링크만 해제한다(미디어 자체는 보존).
    되돌린 후보 목록을 반환한다(호출부의 ledger 동기화·감사 로그용).
    """
    # export sync와도 직렬화되는 lifecycle advisory -> export advisory -> candidate ->
    # place -> mapping -> asset 순서로 관련 행을 전부 잠근 뒤 mutation을 시작한다.
    # 후보가 없는 legacy mapping도
    # 존재할 수 있으므로 place를 먼저 잠그지 않고 mapping/asset을 변경하면 merge의
    # place-first 구간과 교착한다. autoflush도 잠금 집합이 완성될 때까지 억제한다.
    await acquire_place_lifecycle_lock(session)
    await feature_export_service.acquire_feature_export_lock(session)
    reverted = list(
        (
            await session.execute(
                select(ExtractedPlaceCandidate)
                .where(
                    ExtractedPlaceCandidate.matched_place_id == place_id,
                    ExtractedPlaceCandidate.deleted_at.is_(None),
                )
                # geocode post-core 검증과 같은 candidate 우선 lock 순서다.
                .order_by(ExtractedPlaceCandidate.id.asc())
                .with_for_update()
                .execution_options(populate_existing=True, autoflush=False)
            )
        )
        .scalars()
        .all()
    )

    place = (
        await session.execute(
            select(TravelPlace)
            .where(TravelPlace.place_id == place_id)
            .with_for_update()
            .execution_options(populate_existing=True, autoflush=False)
        )
    ).scalar_one_or_none()
    if place is None:
        raise ValueError(f"place not found: {place_id}")

    mappings = list(
        (
            await session.execute(
                select(VideoPlaceMapping)
                .where(VideoPlaceMapping.place_id == place_id)
                .order_by(VideoPlaceMapping.id.asc())
                .with_for_update()
                .execution_options(populate_existing=True, autoflush=False)
            )
        )
        .scalars()
        .all()
    )
    assets = list(
        (
            await session.execute(
                select(MediaAsset)
                .where(MediaAsset.place_id == place_id)
                .order_by(MediaAsset.id.asc())
                .with_for_update()
                .execution_options(populate_existing=True, autoflush=False)
            )
        )
        .scalars()
        .all()
    )

    # 모든 lock을 확보한 뒤에만 ORM mutation을 시작한다.
    for candidate in reverted:
        candidate.matched_place_id = None
        candidate.match_status = MatchStatus.NEEDS_REVIEW
        candidate.feature_export_status = FeatureExportStatus.PENDING.value
    for mapping in mappings:
        await session.delete(mapping)
    for asset in assets:
        asset.place_id = None
    # ORM relationship에 flush 순서를 맡기지 않고 FK 자식 정리를 먼저 확정한다.
    await session.flush()
    await session.delete(place)
    # 되돌린 후보(needs_review + pending, 장소 링크 해제)의 기존 export는 tombstone으로
    # 회수돼야 하므로 같은 트랜잭션에서 dirty로 표시한다(T-171). 호출부(route)가
    # `sync_dirty`를 돌리면 tombstone이 발행된다.
    await feature_export_service.mark_candidates_dirty(
        session, [candidate.id for candidate in reverted], reason="place_deleted"
    )
    await session.flush()
    return reverted


async def list_unmatched_candidates(
    session: AsyncSession,
    *,
    limit: int = 500,
    channel_id: str | None = None,
    playlist_id: str | None = None,
    keyword: str | None = None,
) -> list[ExtractedPlaceCandidate]:
    """`needs_review` 상태의 매칭 실패 후보를 조회한다.

    결과 보기와 동일하게 유튜버(channel)/재생목록(playlist)/검색어(keyword) 출처로
    필터할 수 있다. channel/keyword 필터는 후보의 출처 영상(youtube_videos)을 조인한다.
    soft delete된 후보는 제외한다(T-160 — partial index `WHERE deleted_at IS NULL`과
    같은 access path).
    """
    stmt = _unmatched_candidates_stmt(
        channel_id=channel_id,
        playlist_id=playlist_id,
        keyword=keyword,
    ).order_by(ExtractedPlaceCandidate.id.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _normalize_candidate_search(query: str | None) -> str | None:
    """검수 검색어를 cursor와 SQL이 공유하는 값으로 정규화한다."""
    if query is None:
        return None
    normalized = query.strip()
    return normalized or None


def _normalize_optional_filter_text(value: str | None) -> str | None:
    """목록과 bulk snapshot이 공유하는 공백 정규화 규칙."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("필터 문자열 형식이 올바르지 않습니다.")
    normalized = value.strip()
    return normalized or None


def _literal_ilike_pattern(value: str) -> str:
    """사용자 `%`/`_`/`\\`를 wildcard·escape가 아닌 문자 그대로 취급한다."""
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _candidate_queue_reason_expression():
    geocoding_reason = func.jsonb_extract_path_text(
        ExtractedPlaceCandidate.provider_evidence_json,
        "geocoding",
        "decision",
        "reason",
    )
    reconcile_decision = func.lower(
        func.btrim(
            func.coalesce(
                func.jsonb_extract_path_text(
                    ExtractedPlaceCandidate.provider_evidence_json,
                    "reconcile",
                    "decision",
                ),
                "",
            )
        )
    )
    reconcile_review_reason = func.jsonb_extract_path_text(
        ExtractedPlaceCandidate.provider_evidence_json,
        "reconcile",
        "needs_review_reason",
    )
    reconcile_confidence_json = ExtractedPlaceCandidate.provider_evidence_json[
        "reconcile"
    ]["confidence_score"]
    reconcile_confidence = cast(
        case(
            (
                func.jsonb_typeof(reconcile_confidence_json) == "number",
                func.jsonb_extract_path_text(
                    ExtractedPlaceCandidate.provider_evidence_json,
                    "reconcile",
                    "confidence_score",
                ),
            ),
            else_=None,
        ),
        Numeric,
    )
    review_note = func.lower(func.coalesce(ExtractedPlaceCandidate.review_note, ""))
    return case(
        (
            # 재처리로 grounding이 **실제 판정**돼 실패한(unverified/missing) transcript
            # 후보(T-165, B3). 지오코딩 사유보다 앞선다(최우선). legacy_unknown(재처리 전
            # 기존 후보)에는 적용하지 않는다 — 사람이 grounding을 만들 수 없는 행동 불가
            # 사유로 원래 사유(name_mismatch/region_mismatch/foreign/reconcile)를 덮으면
            # backlog을 가리기 때문이다(코디네이터 MAJOR 3, "재처리 전까지 건드리지 않음").
            and_(
                ExtractedPlaceCandidate.source_kind
                == EvidenceSourceKind.TRANSCRIPT.value,
                ExtractedPlaceCandidate.grounding_status.in_(
                    [
                        GroundingStatus.UNVERIFIED.value,
                        GroundingStatus.MISSING.value,
                    ]
                ),
            ),
            QueueReason.UNGROUNDED.value,
        ),
        (
            or_(
                geocoding_reason == QueueReason.NAME_MISMATCH.value,
                review_note.contains("name_mismatch"),
                # 신규 장소 + 주소/좌표 결과의 POI identity 미검증 차단(T-166, G4/D2)도
                # "장소명 확인" 검수 버킷으로 표시한다(전용 안정 enum은 늘리지 않는다).
                review_note.contains("name_unverified"),
            ),
            QueueReason.NAME_MISMATCH.value,
        ),
        (
            or_(
                geocoding_reason == QueueReason.REGION_MISMATCH.value,
                review_note.contains("region_mismatch"),
            ),
            QueueReason.REGION_MISMATCH.value,
        ),
        (
            reconcile_decision == "conflict",
            QueueReason.SOURCE_CONFLICT.value,
        ),
        (
            reconcile_decision == "low_confidence",
            QueueReason.SOURCE_LOW_CONFIDENCE.value,
        ),
        (
            or_(
                reconcile_decision.in_(["needs_review", "uncertain"]),
                func.nullif(func.btrim(reconcile_review_reason), "").is_not(None),
                reconcile_confidence < Decimal("0.65"),
            ),
            QueueReason.SOURCE_UNCERTAIN.value,
        ),
        (
            geocoding_reason == QueueReason.AMBIGUOUS.value,
            QueueReason.AMBIGUOUS.value,
        ),
        (
            geocoding_reason == QueueReason.NO_RESULT.value,
            QueueReason.NO_RESULT.value,
        ),
        (
            geocoding_reason == QueueReason.VWORLD_UNREFINED_SINGLE.value,
            QueueReason.VWORLD_UNREFINED_SINGLE.value,
        ),
        (
            # 해외 확정(is_domestic=False)과 국내 여부 미확인 fail-closed(T-166, D7)를 함께
            # "해외 후보"로 표시한다. None은 "해외 가능성"이라 별도 안정 enum을 늘리지 않고
            # 기존 FOREIGN 사유에 합류시킨다(자동확정 게이트가 review_note로 표식).
            or_(
                ExtractedPlaceCandidate.is_domestic.is_(False),
                review_note.contains("domestic_unverified"),
            ),
            QueueReason.FOREIGN.value,
        ),
        (
            ExtractedPlaceCandidate.source_kind
            == EvidenceSourceKind.DESCRIPTION.value,
            QueueReason.DESCRIPTION_ONLY.value,
        ),
        (
            ExtractedPlaceCandidate.source_kind == EvidenceSourceKind.VISUAL.value,
            QueueReason.VISUAL_ONLY.value,
        ),
        (
            and_(
                ExtractedPlaceCandidate.provider_evidence_json.op("?")("geocoding"),
                geocoding_reason.is_(None),
            ),
            QueueReason.PROVIDER_MISSING.value,
        ),
        else_=QueueReason.EXTRACTION_ONLY.value,
    )


def _unmatched_candidates_stmt(
    *,
    channel_id: str | None,
    playlist_id: str | None,
    keyword: str | None,
    query: str | None = None,
    is_domestic: bool | None = None,
    status: ReviewCandidateStatus | None = ReviewCandidateStatus.NEEDS_REVIEW,
    queue_reason: QueueReason | None = None,
    source_kind: EvidenceSourceKind | None = None,
    grounding_status: GroundingStatus | None = None,
):
    reason_expression = _candidate_queue_reason_expression()
    stmt = (
        select(
            ExtractedPlaceCandidate,
            YoutubeVideo.title.label("video_title"),
            func.coalesce(YoutubeChannel.title, YoutubeVideo.channel_name).label(
                "channel_title"
            ),
            reason_expression.label("queue_reason"),
            func.coalesce(YoutubeVideo.is_excluded, False).label(
                "video_is_excluded"
            ),
            TravelPlace.state_revision.label("matched_place_revision"),
        )
        .outerjoin(
            YoutubeVideo,
            YoutubeVideo.video_id == ExtractedPlaceCandidate.video_id,
        )
        .outerjoin(
            YoutubeChannel,
            YoutubeChannel.channel_id == YoutubeVideo.channel_id,
        )
        .outerjoin(
            TravelPlace,
            TravelPlace.place_id == ExtractedPlaceCandidate.matched_place_id,
        )
    )
    if status is not None:
        if status is ReviewCandidateStatus.REMOVED:
            stmt = stmt.where(
                or_(
                    ExtractedPlaceCandidate.deleted_at.is_not(None),
                    and_(
                        ExtractedPlaceCandidate.deleted_at.is_(None),
                        ExtractedPlaceCandidate.match_status
                        == MatchStatus.IGNORED.value,
                    ),
                )
            )
        else:
            stmt = stmt.where(
                ExtractedPlaceCandidate.deleted_at.is_(None),
                ExtractedPlaceCandidate.match_status == status.value,
            )
    if channel_id:
        stmt = stmt.where(
            or_(
                ExtractedPlaceCandidate.source_channel_id == channel_id,
                YoutubeVideo.channel_id == channel_id,
            )
        )
    if playlist_id:
        stmt = stmt.where(ExtractedPlaceCandidate.source_playlist_id == playlist_id)
    if keyword:
        stmt = stmt.where(YoutubeVideo.source_search_query == keyword)
    if query:
        pattern = _literal_ilike_pattern(query)
        stmt = stmt.where(
            or_(
                ExtractedPlaceCandidate.ai_place_name.ilike(pattern, escape="\\"),
                ExtractedPlaceCandidate.location_hint.ilike(pattern, escape="\\"),
            )
        )
    if is_domestic is not None:
        stmt = stmt.where(ExtractedPlaceCandidate.is_domestic.is_(is_domestic))
    if queue_reason is not None:
        stmt = stmt.where(reason_expression == queue_reason.value)
    if source_kind is not None:
        stmt = stmt.where(ExtractedPlaceCandidate.source_kind == source_kind.value)
    if grounding_status is not None:
        stmt = stmt.where(
            ExtractedPlaceCandidate.grounding_status == grounding_status.value
        )
    return stmt


async def list_unmatched_candidates_page(
    session: AsyncSession,
    *,
    limit: int = 500,
    channel_id: str | None = None,
    playlist_id: str | None = None,
    keyword: str | None = None,
    query: str | None = None,
    sort: ReviewCandidateSort | str = ReviewCandidateSort.NEWEST,
    is_domestic: bool | None = None,
    status: ReviewCandidateStatus | str = ReviewCandidateStatus.NEEDS_REVIEW,
    queue_reason: QueueReason | None = None,
    source_kind: EvidenceSourceKind | None = None,
    grounding_status: GroundingStatus | None = None,
    cursor: str | None = None,
    newer_than_id: int | None = None,
) -> ListPage[CandidateListItem]:
    """검수 후보를 검색·상태 filter와 안정적인 ID keyset page로 반환한다."""
    await ensure_repeatable_read(session)
    try:
        sort_value = ReviewCandidateSort(sort)
        status_value = ReviewCandidateStatus(status)
    except ValueError as exc:
        raise ValueError("유효하지 않은 검수 목록 정렬 또는 상태입니다") from exc
    if is_domestic is not None and type(is_domestic) is not bool:
        raise ValueError("is_domestic는 true 또는 false여야 합니다")
    normalized_query = _normalize_candidate_search(query)
    normalized_filters = {
        "channel_id": _normalize_optional_filter_text(channel_id),
        "playlist_id": _normalize_optional_filter_text(playlist_id),
        "keyword": _normalize_optional_filter_text(keyword),
        "q": normalized_query,
        "is_domestic": is_domestic,
        "status": status_value.value,
        "queue_reason": queue_reason.value if queue_reason else None,
        "source_kind": source_kind.value if source_kind else None,
        "grounding": grounding_status.value if grounding_status else None,
        "state_predicate": status_value.value,
    }
    fingerprint = filter_fingerprint(
        scope="unmatched-v5", sort=sort_value.value, filters=normalized_filters
    )
    decoded = (
        decode_cursor(cursor, fingerprint=fingerprint, key_count=1)
        if cursor
        else None
    )
    if decoded is not None and (
        not isinstance(decoded.keys[0], int)
        or isinstance(decoded.keys[0], bool)
        or decoded.keys[0] < 1
        or decoded.keys[0] > MAX_DB_INTEGER_ID
        or decoded.keys[0] > decoded.snapshot_id
    ):
        raise ValueError("유효하지 않은 검수 목록 cursor입니다")

    base_stmt = _unmatched_candidates_stmt(
        channel_id=normalized_filters["channel_id"],
        playlist_id=normalized_filters["playlist_id"],
        keyword=normalized_filters["keyword"],
        query=normalized_query,
        is_domestic=is_domestic,
        status=status_value,
        queue_reason=queue_reason,
        source_kind=source_kind,
        grounding_status=grounding_status,
    )
    id_stmt = base_stmt.with_only_columns(ExtractedPlaceCandidate.id).order_by(None)
    if decoded is None:
        newest_id = await session.scalar(
            select(func.max(id_stmt.subquery().c.id))
        )
        snapshot_id = int(newest_id or 0)
    else:
        snapshot_id = decoded.snapshot_id

    snapshot_ids = id_stmt.where(ExtractedPlaceCandidate.id <= snapshot_id).subquery()
    total = int(
        await session.scalar(select(func.count()).select_from(snapshot_ids)) or 0
    )
    newer_than = 0
    if newer_than_id is not None:
        newer_ids = id_stmt.where(
            ExtractedPlaceCandidate.id > newer_than_id
        ).subquery()
        newer_than = int(
            await session.scalar(select(func.count()).select_from(newer_ids)) or 0
        )

    page_stmt = base_stmt.where(ExtractedPlaceCandidate.id <= snapshot_id)
    if decoded is not None:
        cursor_id = decoded.keys[0]
        page_stmt = page_stmt.where(
            ExtractedPlaceCandidate.id < cursor_id
            if sort_value is ReviewCandidateSort.NEWEST
            else ExtractedPlaceCandidate.id > cursor_id
        )
    order_by = (
        ExtractedPlaceCandidate.id.desc()
        if sort_value is ReviewCandidateSort.NEWEST
        else ExtractedPlaceCandidate.id.asc()
    )
    rows = (
        await session.execute(
            page_stmt.order_by(order_by).limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    items = [
        CandidateListItem(
            candidate=row[0],
            video_title=row.video_title or row[0].video_id,
            channel_title=row.channel_title,
            queue_reason=QueueReason(row.queue_reason),
            video_is_excluded=bool(row.video_is_excluded),
            matched_place_revision=(
                int(row.matched_place_revision)
                if row.matched_place_revision is not None
                else None
            ),
        )
        for row in rows[:limit]
    ]
    next_cursor = (
        encode_cursor(
            fingerprint=fingerprint,
            snapshot_id=snapshot_id,
            keys=(items[-1].candidate.id,),
        )
        if has_more and items
        else None
    )
    return ListPage(
        items=items,
        next_cursor=next_cursor,
        has_more=has_more,
        total=total,
        newest_id=snapshot_id or None,
        newer_than=newer_than,
    )


async def get_candidate_list_item(
    session: AsyncSession, candidate_id: int
) -> CandidateListItem | None:
    """page 밖 딥링크용 목록 항목 1건을 삭제 여부·상태와 무관하게 직접 조회한다."""
    row = (
        await session.execute(
            _unmatched_candidates_stmt(
                channel_id=None,
                playlist_id=None,
                keyword=None,
                status=None,
            ).where(ExtractedPlaceCandidate.id == candidate_id)
        )
    ).one_or_none()
    if row is None:
        return None
    return CandidateListItem(
        candidate=row[0],
        video_title=row.video_title or row[0].video_id,
        channel_title=row.channel_title,
        queue_reason=QueueReason(row.queue_reason),
        video_is_excluded=bool(row.video_is_excluded),
        matched_place_revision=(
            int(row.matched_place_revision)
            if row.matched_place_revision is not None
            else None
        ),
    )


def _review_bulk_canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _review_bulk_scope_fingerprint(scope: dict[str, Any]) -> str:
    return hashlib.sha256(
        _review_bulk_canonical_json(scope).encode("utf-8")
    ).hexdigest()


def _review_bulk_confirmation_digest(
    token: str,
    *,
    operation_id: UUID,
    actor: str,
    action: str,
    scope_fingerprint: str,
    expires_at: datetime,
) -> str:
    """평문 token과 immutable operation 경계를 함께 hash한다."""
    if expires_at.tzinfo is None:
        raise ReviewBulkTokenError("confirmation 만료 시각에 timezone이 없습니다.")
    material = {
        "version": _REVIEW_BULK_TOKEN_VERSION,
        "operation_id": str(operation_id),
        "actor": actor,
        "action": action,
        "scope_fingerprint": scope_fingerprint,
        # PostgreSQL TIMESTAMPTZ는 같은 instant를 session timezone에 따라 다른
        # offset으로 돌려줄 수 있다. UTC microsecond 표현으로 고정해 새 session에서도
        # 동일 token digest를 계산한다.
        "expires_at": expires_at.astimezone(timezone.utc).isoformat(
            timespec="microseconds"
        ),
        "token": token,
    }
    return hashlib.sha256(
        _review_bulk_canonical_json(material).encode("utf-8")
    ).hexdigest()


def _normalize_review_bulk_text(value: Any, *, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ReviewBulkValidationError("필터 문자열 형식이 올바르지 않습니다.")
    normalized = _normalize_optional_filter_text(value)
    if normalized is not None and len(normalized) > maximum:
        raise ReviewBulkValidationError("필터 문자열이 허용 길이를 초과했습니다.")
    return normalized


def _normalize_review_bulk_filter(
    action: ReviewBulkAction,
    values: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """JSON filter를 목록 SQL과 fingerprint가 공유하는 canonical 값으로 만든다."""
    allowed = {
        "channel_id",
        "playlist_id",
        "keyword",
        "q",
        "is_domestic",
        "status",
        "reason",
        "source_kind",
        "grounding",
    }
    unknown = set(values) - allowed
    if unknown:
        raise ReviewBulkValidationError("지원하지 않는 일괄 검수 필터가 있습니다.")

    status_default = (
        ReviewCandidateStatus.REMOVED
        if action is ReviewBulkAction.REOPEN
        else ReviewCandidateStatus.NEEDS_REVIEW
    )
    try:
        status = ReviewCandidateStatus(values.get("status") or status_default)
        reason = (
            QueueReason(values["reason"])
            if values.get("reason") is not None
            else None
        )
        source_kind = (
            EvidenceSourceKind(values["source_kind"])
            if values.get("source_kind") is not None
            else None
        )
        grounding = (
            GroundingStatus(values["grounding"])
            if values.get("grounding") is not None
            else None
        )
    except ValueError as exc:
        raise ReviewBulkValidationError("유효하지 않은 일괄 검수 필터입니다.") from exc

    if action is ReviewBulkAction.REOPEN:
        if status is not ReviewCandidateStatus.REMOVED:
            raise ReviewBulkValidationError(
                "reopen 필터 작업은 removed 상태에서만 실행할 수 있습니다."
            )
    elif status is not ReviewCandidateStatus.NEEDS_REVIEW:
        raise ReviewBulkValidationError(
            "ignore/delete 필터 작업은 needs_review 상태에서만 실행할 수 있습니다."
        )

    is_domestic = values.get("is_domestic")
    if is_domestic is not None and type(is_domestic) is not bool:
        raise ReviewBulkValidationError("is_domestic는 boolean 또는 null이어야 합니다.")
    if reason is QueueReason.FOREIGN and is_domestic is not False:
        raise ReviewBulkValidationError(
            "해외 후보 일괄 작업은 reason이 아니라 is_domestic=false로 범위를 고정해야 합니다."
        )

    canonical = {
        "channel_id": _normalize_review_bulk_text(
            values.get("channel_id"), maximum=128
        ),
        "playlist_id": _normalize_review_bulk_text(
            values.get("playlist_id"), maximum=128
        ),
        "keyword": _normalize_review_bulk_text(
            values.get("keyword"), maximum=255
        ),
        "q": _normalize_review_bulk_text(values.get("q"), maximum=255),
        # false와 null을 truthiness로 합치지 않는다.
        "is_domestic": is_domestic,
        "status": status.value,
        "reason": reason.value if reason else None,
        "source_kind": source_kind.value if source_kind else None,
        "grounding": grounding.value if grounding else None,
    }
    query_args = {
        "channel_id": canonical["channel_id"],
        "playlist_id": canonical["playlist_id"],
        "keyword": canonical["keyword"],
        "query": canonical["q"],
        "is_domestic": is_domestic,
        "status": status,
        "queue_reason": reason,
        "source_kind": source_kind,
        "grounding_status": grounding,
    }
    return canonical, query_args


def _review_bulk_candidate_snapshot_stmt(base_stmt):
    """목록 filter SQL에서 preview에 필요한 scalar만 SELECT한다.

    `maintain_column_froms=True`로 channel/video 기반 filter JOIN은 유지하되 목록 표시용
    제목·queue reason·영상 상태와 candidate의 TOAST JSON/Text는 결과 row에 싣지 않는다.
    """
    return base_stmt.with_only_columns(
        ExtractedPlaceCandidate.id.label("candidate_id"),
        ExtractedPlaceCandidate.state_revision.label("candidate_revision"),
        ExtractedPlaceCandidate.match_status.label("match_status"),
        ExtractedPlaceCandidate.deleted_at.label("deleted_at"),
        ExtractedPlaceCandidate.matched_place_id.label("matched_place_id"),
        TravelPlace.state_revision.label("matched_place_revision"),
        maintain_column_froms=True,
    ).order_by(None)


async def _load_review_bulk_candidate_snapshots(
    session: AsyncSession,
    base_stmt,
    *,
    limit: int | None = None,
) -> list[ReviewBulkCandidateSnapshot]:
    stmt = _review_bulk_candidate_snapshot_stmt(base_stmt).order_by(
        ExtractedPlaceCandidate.id.asc()
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = (await session.execute(stmt)).mappings().all()
    return [
        ReviewBulkCandidateSnapshot(
            candidate_id=int(row["candidate_id"]),
            candidate_revision=int(row["candidate_revision"]),
            match_status=str(
                getattr(row["match_status"], "value", row["match_status"])
            ),
            deleted_at=row["deleted_at"],
            matched_place_id=(
                int(row["matched_place_id"])
                if row["matched_place_id"] is not None
                else None
            ),
            matched_place_revision=(
                int(row["matched_place_revision"])
                if row["matched_place_revision"] is not None
                else None
            ),
        )
        for row in rows
    ]


def _validate_review_bulk_candidate_states(
    action: ReviewBulkAction,
    snapshots: Sequence[ReviewBulkCandidateSnapshot],
) -> None:
    invalid: list[int] = []
    for snapshot in snapshots:
        state = snapshot.review_state
        if action is ReviewBulkAction.REOPEN:
            valid = state != MatchStatus.NEEDS_REVIEW.value
        else:
            valid = state == MatchStatus.NEEDS_REVIEW.value
        if not valid:
            invalid.append(snapshot.candidate_id)
    if invalid:
        sample = ", ".join(str(value) for value in invalid[:10])
        raise ReviewBulkValidationError(
            f"{action.value}할 수 없는 상태의 후보가 포함되어 있습니다: {sample}"
        )


async def preview_review_bulk_operation(
    session: AsyncSession,
    *,
    action: ReviewBulkAction | str,
    actor: str,
    candidate_ids: Sequence[int] | None = None,
    filter_values: dict[str, Any] | None = None,
    commit: bool = True,
) -> ReviewBulkPreviewResult:
    """selection 또는 filter의 정확한 멤버십/revision을 durable item으로 동결한다."""
    await ensure_repeatable_read(session)
    try:
        action_value = ReviewBulkAction(action)
    except ValueError as exc:
        raise ReviewBulkValidationError("유효하지 않은 일괄 검수 action입니다.") from exc
    actor_value = (actor or "").strip()
    if not 1 <= len(actor_value) <= 64:
        raise ReviewBulkValidationError("검수 actor 길이가 올바르지 않습니다.")
    if (candidate_ids is None) == (filter_values is None):
        raise ReviewBulkValidationError(
            "selection과 filter scope 중 정확히 하나가 필요합니다."
        )

    snapshots: list[ReviewBulkCandidateSnapshot]
    if candidate_ids is not None:
        ids = list(candidate_ids)
        if not ids or len(ids) > REVIEW_BULK_SELECTION_LIMIT:
            raise ReviewBulkValidationError(
                f"selection은 1~{REVIEW_BULK_SELECTION_LIMIT}건이어야 합니다."
            )
        if any(
            not _positive_int(value, maximum=MAX_DB_INTEGER_ID) for value in ids
        ):
            raise ReviewBulkValidationError("candidate_ids는 양의 정수여야 합니다.")
        if len(set(ids)) != len(ids):
            raise ReviewBulkValidationError("candidate_ids에 중복이 있습니다.")
        normalized_ids = sorted(ids)
        snapshots = await _load_review_bulk_candidate_snapshots(
            session,
            select(ExtractedPlaceCandidate)
            .outerjoin(
                TravelPlace,
                TravelPlace.place_id == ExtractedPlaceCandidate.matched_place_id,
            )
            .where(ExtractedPlaceCandidate.id.in_(normalized_ids)),
        )
        found = {snapshot.candidate_id for snapshot in snapshots}
        missing = [value for value in normalized_ids if value not in found]
        if missing:
            sample = ", ".join(str(value) for value in missing[:10])
            raise ReviewBulkValidationError(
                f"존재하지 않는 후보가 포함되어 있습니다: {sample}"
            )
        scope = {"kind": "selection", "candidate_ids": normalized_ids}
    else:
        canonical_filter, query_args = _normalize_review_bulk_filter(
            action_value, filter_values or {}
        )
        # 상한+1개만 읽어 초과 여부와 exact membership을 한 snapshot query로 판정한다.
        # 초과 시 일부 10,000개를 operation으로 만들지 않고 transaction을 거부한다.
        snapshots = await _load_review_bulk_candidate_snapshots(
            session,
            _unmatched_candidates_stmt(**query_args),
            limit=REVIEW_BULK_FILTER_LIMIT + 1,
        )
        if len(snapshots) > REVIEW_BULK_FILTER_LIMIT:
            raise ReviewBulkLimitExceededError(
                f"필터 결과가 상한 {REVIEW_BULK_FILTER_LIMIT}건을 초과했습니다. "
                "필터를 더 좁혀 주세요."
            )
        scope = {"kind": "filter", "filter": canonical_filter}

    _validate_review_bulk_candidate_states(action_value, snapshots)
    operation_id = uuid4()
    expires_at = utcnow() + REVIEW_BULK_CONFIRMATION_TTL
    scope_fingerprint = _review_bulk_scope_fingerprint(scope)
    token = (
        f"{_REVIEW_BULK_TOKEN_VERSION}.{operation_id}."
        f"{secrets.token_urlsafe(32)}"
    )
    token_hash = _review_bulk_confirmation_digest(
        token,
        operation_id=operation_id,
        actor=actor_value,
        action=action_value.value,
        scope_fingerprint=scope_fingerprint,
        expires_at=expires_at,
    )
    operation = ReviewBulkOperation(
        operation_id=operation_id,
        actor=actor_value,
        action=action_value.value,
        scope_kind=scope["kind"],
        scope_json=scope,
        scope_fingerprint=scope_fingerprint,
        confirmation_token_hash=token_hash,
        confirmation_expires_at=expires_at,
        total_count=len(snapshots),
    )
    session.add(operation)
    # item Core insert의 FK parent를 먼저 materialize한다. transaction commit은 여전히
    # route/service 마지막 한 번뿐이라 preview operation/items/audit은 함께 rollback된다.
    await session.flush([operation])
    item_insert = insert(ReviewBulkOperationItem.__table__)
    for offset in range(0, len(snapshots), REVIEW_BULK_ITEM_INSERT_BATCH_SIZE):
        batch = snapshots[offset : offset + REVIEW_BULK_ITEM_INSERT_BATCH_SIZE]
        await session.execute(
            item_insert,
            [
                {
                    "operation_id": operation_id,
                    "candidate_id": snapshot.candidate_id,
                    "snapshot_revision": snapshot.candidate_revision,
                    "snapshot_review_state": snapshot.review_state,
                    "snapshot_matched_place_id": snapshot.matched_place_id,
                    "snapshot_matched_place_revision": (
                        snapshot.matched_place_revision
                    ),
                    "reopen_token": (
                        snapshot.undo_token()
                        if action_value is ReviewBulkAction.REOPEN
                        else None
                    ),
                    "status": ReviewBulkItemStatus.PENDING.value,
                    "attempt_count": 0,
                }
                for snapshot in batch
            ],
        )
    await audit_service.record(
        session,
        actor_type="web",
        action="candidate.bulk_preview",
        target_type="review_bulk_operation",
        target_id=str(operation_id),
        payload={
            "operation_id": str(operation_id),
            "action": action_value.value,
            "scope_kind": scope["kind"],
            "scope_fingerprint": scope_fingerprint,
            "total": len(snapshots),
            "actor": actor_value,
        },
        commit=False,
    )
    await session.flush()
    if commit:
        await session.commit()
    return ReviewBulkPreviewResult(
        operation_id=operation_id,
        confirmation_token=token,
        expires_at=expires_at,
        total=len(snapshots),
        chunk_size=REVIEW_BULK_CHUNK_SIZE,
    )


def _verify_review_bulk_token(
    operation: ReviewBulkOperation,
    *,
    actor: str,
    token: str,
) -> None:
    if operation.actor != actor:
        # operation 존재 여부와 소유 actor를 외부에 구분해 노출하지 않는다.
        raise ReviewBulkOperationNotFoundError("일괄 검수 operation을 찾을 수 없습니다.")
    if (
        not isinstance(token, str)
        or not 1 <= len(token) <= 512
        or re.fullmatch(r"rbulk1\.[0-9a-f-]{36}\.[A-Za-z0-9_-]+", token)
        is None
    ):
        raise ReviewBulkTokenError("유효하지 않은 confirmation token입니다.")
    parts = token.split(".", 2)
    if parts[0] != _REVIEW_BULK_TOKEN_VERSION or parts[1] != str(
        operation.operation_id
    ):
        raise ReviewBulkTokenError("유효하지 않은 confirmation token입니다.")
    if (
        operation.scope_kind != operation.scope_json.get("kind")
        or not hmac.compare_digest(
            _review_bulk_scope_fingerprint(operation.scope_json),
            operation.scope_fingerprint,
        )
    ):
        raise ReviewBulkTokenError("operation scope가 변경되었습니다.")
    digest = _review_bulk_confirmation_digest(
        token,
        operation_id=operation.operation_id,
        actor=operation.actor,
        action=operation.action,
        scope_fingerprint=operation.scope_fingerprint,
        expires_at=operation.confirmation_expires_at,
    )
    if not hmac.compare_digest(digest, operation.confirmation_token_hash):
        raise ReviewBulkTokenError("유효하지 않은 confirmation token입니다.")
    if (
        operation.status == ReviewBulkOperationStatus.PREVIEWED.value
        and utcnow() >= operation.confirmation_expires_at
    ):
        raise ReviewBulkTokenExpiredError("confirmation token이 만료되었습니다.")


def _review_bulk_conflict(code: str, candidate_id: int, message: str) -> dict[str, Any]:
    return {"candidate_id": candidate_id, "code": code, "message": message}


async def _execute_review_bulk_item(
    session: AsyncSession,
    *,
    operation: ReviewBulkOperation,
    item: ReviewBulkOperationItem,
    actor: str,
    request_id: UUID,
) -> None:
    action = ReviewBulkAction(operation.action)
    bulk_audit_context = {
        "bulk_operation_id": str(operation.operation_id),
        "bulk_request_id": str(request_id),
    }
    if action is ReviewBulkAction.IGNORE:
        candidate, _, _ = await resolve_candidate(
            session,
            candidate_id=item.candidate_id,
            action="ignore",
            reviewed_by=actor,
            reviewer_type="web",
            review_note="일괄 검수에서 제외",
            expected_revision=item.snapshot_revision,
            client_operation_id=request_id,
            commit=False,
        )
        await session.flush()
        await session.refresh(
            candidate,
            attribute_names=[
                "state_revision",
                "match_status",
                "matched_place_id",
                "deleted_at",
                "provider_evidence_json",
            ],
        )
        await finalize_candidate_client_operation(
            session,
            candidate_id=item.candidate_id,
            client_operation_id=request_id,
            action="ignore",
            expected_candidate_revision=candidate.state_revision,
            expected_review_state=MatchStatus.IGNORED.value,
            expected_matched_place_id=None,
            expected_matched_place_revision=None,
            commit=False,
        )
        await audit_service.record(
            session,
            actor_type="web",
            action="candidate.resolve",
            target_type="extracted_place_candidate",
            target_id=str(item.candidate_id),
            payload={
                "client_operation_id": str(request_id),
                "request": {
                    "client_operation_id": str(request_id),
                    "expected_revision": item.snapshot_revision,
                    "action": "ignore",
                    "review_note": "일괄 검수에서 제외",
                },
                "resolution": latest_candidate_resolution(candidate),
                **bulk_audit_context,
            },
            commit=False,
        )
    elif action is ReviewBulkAction.DELETE:
        summary = await soft_delete_candidates(
            session,
            [item.candidate_id],
            reason="검수 후보 일괄 삭제",
            deleted_by=actor,
            force=False,
            expected_status=MatchStatus.NEEDS_REVIEW,
            expected_revisions={item.candidate_id: item.snapshot_revision},
            client_operation_id=request_id,
            client_operation_action="delete",
        )
        if summary.deleted_candidates != 1:
            raise CandidateStatusConflictError(
                expected_status=MatchStatus.NEEDS_REVIEW,
                actual_status_by_candidate_id={item.candidate_id: "removed"},
            )
        await audit_service.record(
            session,
            actor_type="web",
            action="candidate.delete",
            target_type="extracted_place_candidate",
            target_id=str(item.candidate_id),
            payload={
                "client_operation_id": str(request_id),
                "soft_delete": True,
                "reason": "검수 후보 일괄 삭제",
                "tombstoned_exports": summary.tombstoned_exports,
                "actor": actor,
                **bulk_audit_context,
            },
            commit=False,
        )
    else:
        if item.reopen_token is None:
            raise InvalidCandidateUndoToken("reopen snapshot token이 없습니다.")
        result = await reopen_candidate(
            session,
            candidate_id=item.candidate_id,
            undo_token=item.reopen_token,
        )
        await audit_service.record(
            session,
            actor_type="web",
            action="candidate.reopen",
            target_type="extracted_place_candidate",
            target_id=str(item.candidate_id),
            payload={
                "reopened_from": result.reopened_from,
                "tombstoned_exports": result.tombstoned_exports,
                "deleted_place_id": result.deleted_place_id,
                "video_is_excluded": result.video_is_excluded,
                "actor": actor,
                **bulk_audit_context,
            },
            commit=False,
        )


async def execute_review_bulk_operation(
    session: AsyncSession,
    *,
    operation_id: UUID,
    confirmation_token: str,
    actor: str,
    request_id: UUID,
    cursor: str | None,
    commit: bool = True,
) -> dict[str, Any]:
    """동결 item을 bounded chunk로 처리하고 receipt와 mutation을 한 commit에 남긴다."""
    actor_value = (actor or "").strip()
    operation = (
        await session.execute(
            select(ReviewBulkOperation)
            .where(ReviewBulkOperation.operation_id == operation_id)
            .with_for_update()
            .execution_options(populate_existing=True, autoflush=False)
        )
    ).scalar_one_or_none()
    if operation is None:
        raise ReviewBulkOperationNotFoundError(
            "일괄 검수 operation을 찾을 수 없습니다."
        )
    _verify_review_bulk_token(
        operation,
        actor=actor_value,
        token=confirmation_token,
    )
    receipt = (
        await session.execute(
            select(ReviewBulkOperationReceipt)
            .where(
                ReviewBulkOperationReceipt.operation_id == operation_id,
                ReviewBulkOperationReceipt.request_id == request_id,
            )
            .execution_options(populate_existing=True, autoflush=False)
        )
    ).scalar_one_or_none()
    if receipt is not None:
        if receipt.request_cursor != cursor:
            raise ReviewBulkCursorConflictError(
                "같은 request_id에 다른 cursor를 사용할 수 없습니다."
            )
        replay = deepcopy(receipt.response_json)
        # API route는 commit=False 뒤 바깥에서 commit하지만 direct service 호출자는
        # 기본 commit=True 계약에 의존한다. replay 조기 반환도 operation FOR UPDATE
        # row lock을 즉시 풀어야 다음 client가 불필요하게 session 종료까지 기다리지 않는다.
        if commit:
            await session.commit()
        return replay
    if operation.status in {
        ReviewBulkOperationStatus.COMPLETED.value,
        ReviewBulkOperationStatus.COMPLETED_WITH_ERRORS.value,
    }:
        # 완료 receipt의 exact request_id/cursor replay는 위에서 이미 반환했다. 같은
        # cursor(null 포함)를 새 request로 다시 소비하면 response-loss 복구가 아니라
        # fencing 위반이므로, 0건 성공처럼 보이게 하지 않고 항상 409로 거부한다.
        raise ReviewBulkCursorConflictError("이미 소비된 execute cursor입니다.")
    if operation.next_cursor != cursor:
        raise ReviewBulkCursorConflictError(
            "stale 또는 다른 operation의 execute cursor입니다."
        )

    items = list(
        (
            await session.execute(
                select(ReviewBulkOperationItem)
                .where(
                    ReviewBulkOperationItem.operation_id == operation_id,
                    ReviewBulkOperationItem.status
                    == ReviewBulkItemStatus.PENDING.value,
                )
                .order_by(ReviewBulkOperationItem.candidate_id.asc())
                .limit(REVIEW_BULK_CHUNK_SIZE)
                .with_for_update()
                .execution_options(populate_existing=True, autoflush=False)
            )
        )
        .scalars()
        .all()
    )

    # 세 action의 단건 helper 모두 장소 lifecycle에 진입할 수 있다. 특히 delete의
    # `soft_delete_candidates`도 lifecycle lock을 잡으므로, 여기서 공통 전역 순서인
    # lifecycle -> export를 먼저 고정하지 않으면 다른 writer와 교착할 수 있다.
    await acquire_place_lifecycle_lock(session)
    await feature_export_service.acquire_feature_export_lock(session)
    candidate_ids = [item.candidate_id for item in items]
    candidates = list(
        (
            await session.execute(
                select(ExtractedPlaceCandidate)
                .where(ExtractedPlaceCandidate.id.in_(candidate_ids))
                .order_by(ExtractedPlaceCandidate.id.asc())
                .options(
                    load_only(
                        ExtractedPlaceCandidate.id,
                        ExtractedPlaceCandidate.state_revision,
                        ExtractedPlaceCandidate.match_status,
                        ExtractedPlaceCandidate.deleted_at,
                        ExtractedPlaceCandidate.matched_place_id,
                    )
                )
                .with_for_update()
                .execution_options(populate_existing=True, autoflush=False)
            )
        )
        .scalars()
        .all()
    )
    candidate_by_id = {candidate.id: candidate for candidate in candidates}
    chunk_started_at = utcnow()
    conflicts: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    succeeded = 0
    succeeded_ids: list[int] = []
    conflict_types = (
        CandidateRevisionConflictError,
        CandidateResolveConflictError,
        CandidateStatusConflictError,
        CandidateMappingConflictError,
        CandidateReopenConflictError,
        CandidatePlaceChangedError,
        InvalidCandidateUndoToken,
    )
    for item in items:
        item.attempt_count += 1
        candidate = candidate_by_id.get(item.candidate_id)
        current_state = candidate_review_state(candidate) if candidate else None
        if (
            candidate is None
            or candidate.state_revision != item.snapshot_revision
            or current_state != item.snapshot_review_state
            or candidate.matched_place_id != item.snapshot_matched_place_id
        ):
            error = _review_bulk_conflict(
                "candidate_revision_conflict",
                item.candidate_id,
                "preview 이후 후보 상태가 변경되었습니다.",
            )
            conflicts.append(error)
            item.status = ReviewBulkItemStatus.CONFLICT.value
            item.error_code = error["code"]
            item.error_message = error["message"]
            item.processed_at = utcnow()
            continue
        try:
            async with session.begin_nested():
                await _execute_review_bulk_item(
                    session,
                    operation=operation,
                    item=item,
                    actor=actor_value,
                    request_id=request_id,
                )
                await session.flush()
        except conflict_types as exc:
            code = (
                "candidate_place_changed"
                if isinstance(
                    exc,
                    (CandidateMappingConflictError, CandidatePlaceChangedError),
                )
                else "candidate_revision_conflict"
            )
            error = _review_bulk_conflict(code, item.candidate_id, str(exc))
            conflicts.append(error)
            item.status = ReviewBulkItemStatus.CONFLICT.value
            item.error_code = code
            item.error_message = str(exc)[:2000]
            item.processed_at = utcnow()
        except Exception as exc:
            # request 자체의 response-loss는 durable receipt로 재생한다. 반면 item
            # mutation 중 예외를 같은 operation에서 자동 재시도하면 원인을 모른 채
            # 무한 진행하거나 processed+remaining 불변식을 깨뜨릴 수 있으므로 명시적인
            # terminal failure로 남겨 사용자가 새 preview로 재시도하게 한다.
            code = "candidate_bulk_failed"
            message = "후보 처리 중 오류가 발생해 이 항목을 완료하지 못했습니다."
            failed.append(_review_bulk_conflict(code, item.candidate_id, message))
            item.status = ReviewBulkItemStatus.FAILED.value
            item.error_code = code
            # 예외 원문에는 SQL parameter나 provider credential이 포함될 수 있다.
            # 영속 진단에는 고정 code와 예외 type만 남기고 str(exc)는 저장하지 않는다.
            item.error_message = f"{code}:{type(exc).__name__}"[:2000]
            item.processed_at = utcnow()
        else:
            succeeded += 1
            succeeded_ids.append(item.candidate_id)
            item.status = ReviewBulkItemStatus.SUCCEEDED.value
            item.error_code = None
            item.error_message = None
            item.processed_at = utcnow()

    await session.flush()
    status_counts = dict(
        (
            await session.execute(
                select(
                    ReviewBulkOperationItem.status,
                    func.count(),
                )
                .where(ReviewBulkOperationItem.operation_id == operation_id)
                .group_by(ReviewBulkOperationItem.status)
            )
        ).all()
    )
    operation.succeeded_count = int(
        status_counts.get(ReviewBulkItemStatus.SUCCEEDED.value, 0)
    )
    operation.conflict_count = int(
        status_counts.get(ReviewBulkItemStatus.CONFLICT.value, 0)
    )
    operation.failed_count = int(
        status_counts.get(ReviewBulkItemStatus.FAILED.value, 0)
    )
    operation.processed_count = (
        operation.succeeded_count
        + operation.conflict_count
        + operation.failed_count
    )
    remaining = operation.total_count - operation.processed_count
    complete = remaining == 0
    chunk_finished_at = utcnow()
    next_cursor = (
        None
        if complete
        else (
            f"{_REVIEW_BULK_CURSOR_VERSION}.{operation.operation_id}."
            f"{secrets.token_urlsafe(18)}"
        )
    )
    operation.next_cursor = next_cursor
    operation.started_at = operation.started_at or chunk_started_at
    if complete:
        operation.status = (
            ReviewBulkOperationStatus.COMPLETED_WITH_ERRORS.value
            if operation.conflict_count or operation.failed_count
            else ReviewBulkOperationStatus.COMPLETED.value
        )
        operation.finished_at = chunk_finished_at
    else:
        operation.status = ReviewBulkOperationStatus.RUNNING.value

    response = {
        "operation_id": str(operation.operation_id),
        "request_id": str(request_id),
        "processed": succeeded + len(conflicts) + len(failed),
        "succeeded": succeeded,
        "conflicts": conflicts,
        "failed": failed,
        "remaining": remaining,
        "next_cursor": next_cursor,
        "complete": complete,
    }
    session.add(
        ReviewBulkOperationReceipt(
            operation_id=operation.operation_id,
            request_id=request_id,
            request_cursor=cursor,
            response_json=deepcopy(response),
        )
    )
    await audit_service.record(
        session,
        actor_type="web",
        action="candidate.bulk_chunk",
        target_type="review_bulk_operation",
        target_id=str(operation.operation_id),
        payload={
            "operation_id": str(operation.operation_id),
            "request_id": str(request_id),
            "action": operation.action,
            "attempted": len(items),
            "candidate_ids": candidate_ids,
            "succeeded": succeeded,
            "succeeded_candidate_ids": succeeded_ids,
            "conflicts": len(conflicts),
            "conflict_candidate_ids": [
                issue["candidate_id"] for issue in conflicts
            ],
            "failed": len(failed),
            "failed_candidate_ids": [issue["candidate_id"] for issue in failed],
            "remaining": remaining,
            "complete": complete,
            "actor": actor_value,
        },
        commit=False,
    )
    await session.flush()
    if commit:
        await session.commit()
    return response


@dataclass(frozen=True)
class SoftDeleteSummary:
    """`soft_delete_candidates` 실행 결과(감사 로그·고아 장소 판정용)."""

    candidate_ids: list[int]
    deleted_candidates: int
    deleted_mappings: int
    affected_place_ids: frozenset[int]
    tombstoned_exports: int


_EMPTY_SOFT_DELETE = SoftDeleteSummary([], 0, 0, frozenset(), 0)


async def soft_delete_candidates(
    session: AsyncSession,
    candidate_ids: Sequence[int],
    *,
    reason: str,
    deleted_by: str | None = None,
    force: bool = False,
    expected_status: MatchStatus | str | None = None,
    expected_revisions: dict[int, int] | None = None,
    client_operation_id: UUID | None = None,
    client_operation_action: str = "delete",
) -> SoftDeleteSummary:
    """추출 후보를 soft delete 한다(T-160, 로드맵 B1).

    후보 행과 export ledger(`feature_exports`) 행은 DELETE 하지 않는다. 대신:

    - 후보의 `video_place_mappings`를 삭제하고 `matched_place_id`를 해제한다.
      고아 장소 판정에 필요한 place 참조는 해제 **전에** 수집해 반환한다.
    - `deleted_at`/`deletion_reason`/`deleted_by`를 세팅한다(사유는 CHECK로 필수).
    - 같은 트랜잭션에서, 이미 export된 ledger 행을 tombstone(새 sequence + 사유)으로
      전환한다. export된 적 없는 후보에는 아무 것도 만들지 않는다.

    정책: `force=False`(검수 큐 개별 삭제)는 기존 라우트의 409 semantics를 유지한다 —
    확정 연결(매핑 보유) 후보가 하나라도 있으면 `CandidateMappingConflictError`.
    `expected_status`를 주면 행 락 후 실제 상태를 원자적으로 검증하고, 다른
    후보가 하나라도 있으면 `CandidateStatusConflictError`로 전체를 거부한다.
    `force=True`(영상 제외)는 확정 포함 전체를 정리한다. 이미 soft delete된 후보는
    건너뛴다(멱등). flush까지만 수행하고 commit은 호출자 책임이다.
    """
    reason_text = (reason or "").strip()
    if not reason_text:
        raise ValueError("soft delete에는 사유(reason)가 필요하다")
    ids = [int(cid) for cid in candidate_ids]
    if not ids:
        return _EMPTY_SOFT_DELETE
    expected_status_value: MatchStatus | None = None
    if expected_status is not None:
        try:
            expected_status_value = MatchStatus(expected_status)
        except ValueError as exc:
            raise ValueError("유효하지 않은 후보 상태 선행 조건입니다") from exc
    # export sync도 candidate snapshot과 ledger FK insert를 수행하므로 export lock을
    # candidate row보다 먼저 잡아 `export -> candidate` 순서를 모든 writer가 공유한다.
    await feature_export_service.acquire_feature_export_lock(session)
    # 행 락으로 동시 resolve(`resolve_candidate`도 FOR UPDATE)와 직렬화한다 — 락 없이면
    # 409 판정(매핑 유무)이 구버전 스냅샷을 읽는 race가 생긴다.
    locked_candidates = list(
        (
            await session.execute(
                select(ExtractedPlaceCandidate)
                .where(ExtractedPlaceCandidate.id.in_(ids))
                .order_by(ExtractedPlaceCandidate.id.asc())
                .with_for_update()
                .execution_options(populate_existing=True, autoflush=False)
            )
        )
        .scalars()
        .all()
    )
    if expected_revisions:
        for candidate in locked_candidates:
            expected_revision = expected_revisions.get(candidate.id)
            _require_candidate_revision(candidate, expected_revision)
    candidates = [
        candidate
        for candidate in locked_candidates
        if candidate.deleted_at is None
    ]
    if not candidates:
        return _EMPTY_SOFT_DELETE
    if expected_status_value is not None:
        status_mismatches = {
            candidate.id: MatchStatus(candidate.match_status).value
            for candidate in candidates
            if candidate.match_status != expected_status_value.value
        }
        if status_mismatches:
            raise CandidateStatusConflictError(
                expected_status=expected_status_value,
                actual_status_by_candidate_id=status_mismatches,
            )
    live_ids = [candidate.id for candidate in candidates]

    mappings = list(
        (
            await session.execute(
                select(VideoPlaceMapping).where(
                    VideoPlaceMapping.place_candidate_id.in_(live_ids)
                )
                .order_by(VideoPlaceMapping.id.asc())
                .with_for_update()
                .execution_options(populate_existing=True, autoflush=False)
            )
        )
        .scalars()
        .all()
    )
    if mappings and not force:
        raise CandidateMappingConflictError(
            "확정 장소와 연결된 후보는 삭제할 수 없습니다."
        )

    # 고아 장소 판정용 참조를 해제/삭제 전에 수집한다(T-159 회귀 주의).
    affected_place_ids = {
        mapping.place_id for mapping in mappings if mapping.place_id is not None
    }
    affected_place_ids |= {
        candidate.matched_place_id
        for candidate in candidates
        if candidate.matched_place_id is not None
    }

    deleted_mappings = 0
    if mappings:
        mapping_result = await session.execute(
            delete(VideoPlaceMapping).where(
                VideoPlaceMapping.place_candidate_id.in_(live_ids)
            )
        )
        deleted_mappings = int(mapping_result.rowcount or 0)

    now = utcnow()
    for candidate in candidates:
        candidate.matched_place_id = None
        candidate.deleted_at = now
        candidate.deletion_reason = reason_text
        candidate.deleted_by = deleted_by
        if client_operation_id is not None:
            _record_last_client_operation(
                candidate,
                client_operation_id=client_operation_id,
                action=client_operation_action,
                occurred_at=now,
                matched_place_revision=None,
            )

    tombstoned = await feature_export_service.tombstone_candidate_exports(
        session, live_ids, reason=reason_text
    )
    # 삭제된 후보를 dirty로도 표시한다(T-171). 위 tombstone 전환이 이미 ledger를 갱신하므로
    # 이는 belt-and-suspenders다 — sync_dirty의 '후보 소멸' 분류는 이미 tombstone인 행을
    # 재sequence하지 않아(freeze) 결과가 동일하다. 삭제 경로가 스캔에 안 잡히는 만큼
    # outbox를 정본으로 유지한다.
    await feature_export_service.mark_candidates_dirty(
        session, live_ids, reason="soft_delete"
    )
    await session.flush()
    for candidate in candidates:
        await session.refresh(candidate, attribute_names=["state_revision"])
    return SoftDeleteSummary(
        candidate_ids=live_ids,
        deleted_candidates=len(candidates),
        deleted_mappings=deleted_mappings,
        affected_place_ids=frozenset(affected_place_ids),
        tombstoned_exports=tombstoned,
    )


@dataclass(frozen=True)
class CandidateReopenResult:
    """reopen core 결과. 감사 로그와 사용자 안내에 필요한 scalar만 반환한다."""

    candidate: ExtractedPlaceCandidate
    reopened_from: str
    tombstoned_exports: int
    deleted_place_id: int | None
    video_is_excluded: bool


async def reopen_candidate(
    session: AsyncSession,
    *,
    candidate_id: int,
    undo_token: str,
) -> CandidateReopenResult:
    """opaque token이 고정한 후보·장소 snapshot만 검수 대기로 되돌린다.

    lock 순서는 lifecycle advisory → export advisory → candidate → place →
    candidate mapping ID → asset ID다.
    후보가 만든 고아 장소만 제거하며 persistent/legacy/shared 장소와 RustFS 자산 행은
    보존한다. 영상 제외 상태도 독립 정책이라 절대 해제하지 않는다. commit과 감사 로그는
    라우트 책임이다.
    """
    token = decode_candidate_undo_token(undo_token)
    await acquire_place_lifecycle_lock(session)
    await feature_export_service.acquire_feature_export_lock(session)
    candidate = (
        await session.execute(
            select(ExtractedPlaceCandidate)
            .where(ExtractedPlaceCandidate.id == candidate_id)
            .order_by(ExtractedPlaceCandidate.id.asc())
            .with_for_update()
            .execution_options(populate_existing=True, autoflush=False)
        )
    ).scalar_one_or_none()
    if candidate is None:
        raise ValueError(f"candidate not found: {candidate_id}")
    if token.candidate_id != candidate.id:
        raise CandidateRevisionConflictError(
            expected_revision=token.candidate_revision,
            actual_revision=candidate.state_revision,
        )
    current_state = candidate_review_state(candidate)
    if current_state == MatchStatus.NEEDS_REVIEW.value:
        raise CandidateReopenConflictError(
            "이미 검수 대기(needs_review) 상태라 복귀할 것이 없습니다."
        )
    _require_candidate_revision(candidate, token.candidate_revision)
    if (
        str(getattr(candidate.match_status, "value", candidate.match_status))
        != token.prior_state
        or current_state != token.effective_state
    ):
        raise CandidateRevisionConflictError(
            expected_revision=token.candidate_revision,
            actual_revision=candidate.state_revision,
        )
    if candidate.matched_place_id != token.matched_place_id:
        raise CandidatePlaceChangedError(
            "후보의 장소 연결이 바뀌어 되돌릴 수 없습니다."
        )

    place: TravelPlace | None = None
    if token.matched_place_id is not None:
        place = (
            await session.execute(
                select(TravelPlace)
                .where(TravelPlace.place_id == token.matched_place_id)
                .order_by(TravelPlace.place_id.asc())
                .with_for_update()
                .execution_options(populate_existing=True, autoflush=False)
            )
        ).scalar_one_or_none()
        if (
            place is None
            or place.state_revision != token.matched_place_revision
        ):
            raise CandidatePlaceChangedError(
                "연결 장소가 바뀌어 되돌릴 수 없습니다."
            )

    mappings = list(
        (
            await session.execute(
                select(VideoPlaceMapping)
                .where(VideoPlaceMapping.place_candidate_id == candidate.id)
                .order_by(VideoPlaceMapping.id.asc())
                .with_for_update()
                .execution_options(populate_existing=True, autoflush=False)
            )
        )
        .scalars()
        .all()
    )
    mapping_place_ids = {mapping.place_id for mapping in mappings}
    if token.matched_place_id is None:
        if mappings:
            raise CandidatePlaceChangedError(
                "후보의 장소 매핑이 바뀌어 되돌릴 수 없습니다."
            )
    elif not mappings or mapping_place_ids != {token.matched_place_id}:
        raise CandidatePlaceChangedError(
            "후보의 장소 매핑이 바뀌어 되돌릴 수 없습니다."
        )

    assets: list[MediaAsset] = []
    if place is not None:
        assets = list(
            (
                await session.execute(
                    select(MediaAsset)
                    .where(MediaAsset.place_id == place.place_id)
                    .order_by(MediaAsset.id.asc())
                    .with_for_update()
                    .execution_options(populate_existing=True, autoflush=False)
                )
            )
            .scalars()
            .all()
        )

    # 모든 lock과 token 비교를 끝낸 뒤 mutation을 시작한다. review_note와 provider/audit
    # evidence는 과거 판단 근거라 보존한다.
    candidate.deleted_at = None
    candidate.deletion_reason = None
    candidate.deleted_by = None
    candidate.match_status = MatchStatus.NEEDS_REVIEW.value
    candidate.matched_place_id = None
    candidate.feature_export_status = FeatureExportStatus.PENDING.value
    candidate.reviewed_by = None
    candidate.reviewed_at = None
    for mapping in mappings:
        await session.delete(mapping)
    tombstoned = await feature_export_service.tombstone_candidate_exports(
        session,
        [candidate.id],
        reason="후보 검수 되돌리기",
    )
    # 복귀(needs_review+pending)를 durable outbox에도 기록한다. 기존 ledger는 위에서
    # 이미 tombstone으로 전환했으므로 다음 dirty consume은 freeze되고, 재확정 때만
    # upsert/reject로 다시 발행된다(T-171).
    await feature_export_service.mark_candidates_dirty(
        session, [candidate.id], reason=f"reopen:{current_state}"
    )
    await session.flush()

    deleted_place_id: int | None = None
    if (
        place is not None
        and place.lifecycle_origin
        == PlaceLifecycleOrigin.CANDIDATE_CREATED.value
    ):
        remaining_candidates = int(
            await session.scalar(
                select(func.count())
                .select_from(ExtractedPlaceCandidate)
                .where(
                    ExtractedPlaceCandidate.matched_place_id == place.place_id,
                    ExtractedPlaceCandidate.deleted_at.is_(None),
                )
            )
            or 0
        )
        remaining_mappings = int(
            await session.scalar(
                select(func.count())
                .select_from(VideoPlaceMapping)
                .where(VideoPlaceMapping.place_id == place.place_id)
            )
            or 0
        )
        if remaining_candidates == 0 and remaining_mappings == 0:
            for asset in assets:
                asset.place_id = None
            await session.flush()
            deleted_place_id = place.place_id
            await session.delete(place)
            await session.flush()

    await session.refresh(candidate, attribute_names=["state_revision"])
    video_is_excluded = bool(
        await session.scalar(
            select(YoutubeVideo.is_excluded).where(
                YoutubeVideo.video_id == candidate.video_id
            )
        )
        or False
    )
    return CandidateReopenResult(
        candidate=candidate,
        reopened_from=current_state,
        tombstoned_exports=tombstoned,
        deleted_place_id=deleted_place_id,
        video_is_excluded=video_is_excluded,
    )


async def exclude_video(
    session: AsyncSession,
    video_id: str,
    *,
    reason: str | None = None,
    excluded_by: str | None = "web",
    commit: bool = True,
) -> dict[str, Any] | None:
    """동영상을 제외(블록리스트)하고 관련 POI를 정리한다.

    영상을 `is_excluded=True`로 표시(이후 수집에서 스킵), 이 영상의 추출 후보를
    **soft delete**(T-160 — 행·export ledger 보존, 이미 export된 건 tombstone 전환)
    하고 언급 매핑을 삭제하며, 다른 영상이 더 이상 언급하지 않는 고아 중에서도
    `candidate_created` 장소만 삭제한다. persistent/legacy/shared 장소는 보존한다.
    반환: 정리 건수 요약. 영상을 찾지 못하면 None.
    """
    video = await session.get(YoutubeVideo, video_id)
    if video is None:
        return None
    # 이후 candidate/mapping 정리와 orphan place 삭제를 하나의 장소 lifecycle
    # 임계구간에 둔다. export lock도 row lock보다 먼저 잡아 sync와 교착하지 않는다.
    await acquire_place_lifecycle_lock(session)
    await feature_export_service.acquire_feature_export_lock(session)
    video.is_excluded = True
    # 공백 reason이 helper의 사유 필수 검증(ValueError→500)으로 흐르지 않게
    # delete 라우트와 같은 정규화 패턴을 쓴다.
    reason_text = (reason or "").strip()
    if reason_text:
        video.exclusion_reason = reason_text[:255]

    # 고아 판정 대상: 이 영상이 매핑한 place_id 집합(매핑 삭제 전에 수집).
    place_ids = {
        pid
        for pid in (
            await session.execute(
                select(VideoPlaceMapping.place_id).where(
                    VideoPlaceMapping.video_id == video_id
                )
            )
        ).scalars()
        if pid is not None
    }
    candidate_ids = list(
        (
            await session.execute(
                select(ExtractedPlaceCandidate.id).where(
                    ExtractedPlaceCandidate.video_id == video_id,
                    ExtractedPlaceCandidate.deleted_at.is_(None),
                )
            )
        ).scalars()
    )
    soft_summary = await soft_delete_candidates(
        session,
        candidate_ids,
        reason=reason_text or "동영상 제외",
        deleted_by=excluded_by,
        force=True,
    )
    place_ids |= set(soft_summary.affected_place_ids)

    # 후보와 연결되지 않은(place_candidate_id 없는) 이 영상의 잔여 매핑도 삭제한다.
    residual_result = await session.execute(
        delete(VideoPlaceMapping).where(VideoPlaceMapping.video_id == video_id)
    )
    deleted_mappings = soft_summary.deleted_mappings + int(
        residual_result.rowcount or 0
    )

    deleted_places = 0
    preserved_places = 0
    for pid in sorted(place_ids):
        remaining_maps = (
            await session.execute(
                select(func.count())
                .select_from(VideoPlaceMapping)
                .where(VideoPlaceMapping.place_id == pid)
            )
        ).scalar_one()
        remaining_cands = (
            await session.execute(
                select(func.count())
                .select_from(ExtractedPlaceCandidate)
                .where(
                    ExtractedPlaceCandidate.matched_place_id == pid,
                    ExtractedPlaceCandidate.deleted_at.is_(None),
                )
            )
        ).scalar_one()
        if remaining_maps == 0 and remaining_cands == 0:
            place = (
                await session.execute(
                    select(TravelPlace)
                    .where(TravelPlace.place_id == pid)
                    .with_for_update()
                    .execution_options(populate_existing=True, autoflush=False)
                )
            ).scalar_one_or_none()
            if place is None:
                continue
            if (
                place.lifecycle_origin
                != PlaceLifecycleOrigin.CANDIDATE_CREATED.value
            ):
                preserved_places += 1
                continue
            assets = list(
                (
                    await session.execute(
                        select(MediaAsset)
                        .where(MediaAsset.place_id == pid)
                        .order_by(MediaAsset.id.asc())
                        .with_for_update()
                        .execution_options(populate_existing=True, autoflush=False)
                    )
                )
                .scalars()
                .all()
            )
            # RustFS 객체와 DB asset 행은 보존하고 삭제될 장소 연결만 해제한다.
            for asset in assets:
                asset.place_id = None
            await session.flush()
            await session.delete(place)
            await session.flush()
            deleted_places += 1

    if commit:
        await session.commit()
    return {
        "video_id": video_id,
        "deleted_candidates": soft_summary.deleted_candidates,
        "deleted_mappings": deleted_mappings,
        "deleted_places": deleted_places,
        "preserved_places": preserved_places,
        "tombstoned_exports": soft_summary.tombstoned_exports,
        "video_is_excluded": True,
    }


# --- auto-match audit 표본 (T-167, 로드맵 PR-14 개정판, G9) ---


class AuditResultConflictError(ValueError):
    """pending audit 표본이 아닌 후보에 결과 전이를 시도했다(라우트 409)."""


class AuditNotSampledError(ValueError):
    """audit 표본이 아닌 후보에 audit 결과를 기록하려 했다(라우트 409)."""


@dataclass(frozen=True)
class AuditSampleItem:
    """auto-match audit 표본 1건(후보 + 표시용 영상 제목·확정 장소명)."""

    candidate: ExtractedPlaceCandidate
    video_title: str | None
    place_name: str | None


async def list_audit_samples(
    session: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 100,
) -> list[AuditSampleItem]:
    """auto-match audit 표본을 미검토 우선·최신순으로 조회한다(사후 검토 큐, G9).

    `status`가 주어지면 해당 audit 상태(`pending`|`accurate`|`misconfirmed`)만 반환한다.
    표본은 **자동확정 당시**의 결정을 사후 검토하는 역사 표본이다. 이후 별도 reopen으로
    현재 `match_status`가 달라질 수 있으며, 그 경우에도 원래 자동확정의 정확성을 왜곡 없이
    집계하도록 audit 이력은 유지한다. soft delete된 후보는 제외한다.
    """
    stmt = (
        select(
            ExtractedPlaceCandidate,
            YoutubeVideo.title,
            TravelPlace.name,
        )
        .join(
            YoutubeVideo,
            YoutubeVideo.video_id == ExtractedPlaceCandidate.video_id,
            isouter=True,
        )
        .join(
            TravelPlace,
            TravelPlace.place_id == ExtractedPlaceCandidate.matched_place_id,
            isouter=True,
        )
        .where(
            ExtractedPlaceCandidate.audit_status.is_not(None),
            ExtractedPlaceCandidate.deleted_at.is_(None),
        )
    )
    if status is not None:
        stmt = stmt.where(ExtractedPlaceCandidate.audit_status == status)
    stmt = stmt.order_by(
        # 미검토(pending)를 먼저 노출하고, 그 안에서 최신 표시순.
        case(
            (ExtractedPlaceCandidate.audit_status == AuditStatus.PENDING.value, 0),
            else_=1,
        ),
        ExtractedPlaceCandidate.id.desc(),
    ).limit(limit)
    rows = (await session.execute(stmt)).all()
    return [
        AuditSampleItem(candidate=candidate, video_title=title, place_name=name)
        for candidate, title, name in rows
    ]


async def record_audit_result(
    session: AsyncSession,
    *,
    candidate_id: int,
    accurate: bool,
    reviewed_by: str,
    note: str | None = None,
    commit: bool = True,
) -> ExtractedPlaceCandidate:
    """audit 표본에 사람 검토 결과(정확/오확정)를 기록한다(G9).

    이 기록은 **사후 관측**이므로 자동확정(MATCHED)·export 상태를 바꾸지 않는다. 오확정으로
    판정해도 실제 되돌리기는 별도 reopen(T-160/T-184 정책)에서 사람이 수행한다. 표본이 아닌
    후보(`audit_status IS NULL`)에 기록하려 하면 `AuditNotSampledError`. 오직 `pending`에서만
    한 번 전이할 수 있으며 이미 판정된 표본은 `AuditResultConflictError`로 거절한다.
    """
    candidate = (
        await session.execute(
            select(ExtractedPlaceCandidate)
            .where(ExtractedPlaceCandidate.id == candidate_id)
            .with_for_update()
            .execution_options(populate_existing=True, autoflush=False)
        )
    ).scalar_one_or_none()
    if candidate is None or candidate.deleted_at is not None:
        raise ValueError(f"candidate not found: {candidate_id}")
    if candidate.audit_status is None:
        raise AuditNotSampledError(
            "auto-match audit 표본이 아닌 후보에는 감사 결과를 기록할 수 없습니다."
        )
    if candidate.audit_status != AuditStatus.PENDING.value:
        raise AuditResultConflictError(
            "이미 판정된 auto-match audit 표본은 다시 판정할 수 없습니다."
        )
    candidate.audit_status = (
        AuditStatus.ACCURATE.value if accurate else AuditStatus.MISCONFIRMED.value
    )
    candidate.audit_reviewed_by = reviewed_by
    candidate.audit_reviewed_at = utcnow()
    if note is not None:
        candidate.audit_note = note.strip() or None
    if commit:
        await session.commit()
        await session.refresh(candidate)
    return candidate


async def audit_summary(session: AsyncSession) -> dict[str, Any]:
    """auto-match audit 표본의 오확정률(자동확정 뒤집힘 비율)을 집계한다(§7 G9 지표).

    `misconfirmation_rate = misconfirmed / (accurate + misconfirmed)`. 검토된 표본이 없으면
    None(표본 0을 정밀도 100%로 오도하지 않는다).
    """
    rows = (
        await session.execute(
            select(ExtractedPlaceCandidate.audit_status, func.count())
            .where(
                ExtractedPlaceCandidate.audit_status.is_not(None),
                ExtractedPlaceCandidate.deleted_at.is_(None),
            )
            .group_by(ExtractedPlaceCandidate.audit_status)
        )
    ).all()
    counts = {status: int(count) for status, count in rows}
    pending = counts.get(AuditStatus.PENDING.value, 0)
    accurate = counts.get(AuditStatus.ACCURATE.value, 0)
    misconfirmed = counts.get(AuditStatus.MISCONFIRMED.value, 0)
    reviewed = accurate + misconfirmed
    return {
        "sampled": pending + reviewed,
        "pending": pending,
        "reviewed": reviewed,
        "accurate": accurate,
        "misconfirmed": misconfirmed,
        "misconfirmation_rate": (misconfirmed / reviewed) if reviewed else None,
    }
