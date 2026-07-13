"""장소 조회 및 근접 중복 후보 탐색 서비스 (저장소 계층)."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import uuid4

from geoalchemy2 import Geography
from sqlalchemy import Numeric, and_, case, cast, delete, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
    TravelPlace,
    VideoPlaceMapping,
    YoutubeChannel,
    YoutubePlaylist,
    YoutubeVideo,
    utcnow,
)
from ktc.services import feature_export_service
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


class CandidateReopenUnsupportedError(ValueError):
    """`matched`/`user_corrected` 후보의 reopen은 T-160 범위 밖이다(라우트 400).

    확정 장소 정리(고아 판정·공유 장소 보호) 정책은 T-184에서 다룬다.
    """


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


class ReviewCandidateDomesticFilter(str, Enum):
    """검수 목록의 국내 여부 query 계약."""

    ALL = "all"
    TRUE = "true"
    FALSE = "false"


@dataclass(frozen=True)
class CandidateListItem:
    """검수 목록에 필요한 짧은 scalar만 결합한 조회 결과."""

    candidate: ExtractedPlaceCandidate
    video_title: str
    channel_title: str | None
    queue_reason: QueueReason


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
) -> list[PlaceSummary]:
    """확정 장소 목록과 영상·유튜버 언급 근거를 함께 조회한다.

    `channel_id`/`playlist_id`/`keyword`/`video_id`가 주어지면 해당 출처(유튜버/재생목록/
    검색어/영상)에서 수집된 장소만 반환한다(결과 보기 그룹화·필터, 영상별 필터).
    """
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

    stmt = select(TravelPlace)
    if effective_ids is not None:
        if not effective_ids:
            return []
        stmt = stmt.where(TravelPlace.place_id.in_(effective_ids))
    result = await session.execute(stmt)
    places = list(result.scalars().all())
    places = [
        place
        for place in places
        if _place_matches_result_filters(
            place,
            category=category,
            query=query,
            district=district,
        )
    ]
    if not places:
        return []

    mentions_by_place = await _list_mentions_by_place(
        session, place_ids=[place.place_id for place in places]
    )
    summaries = [
        PlaceSummary(
            place=place,
            # 한 영상에서 여러 번 언급돼도 1회로 센다(동영상 distinct). 반복 언급으로
            # 횟수가 부풀지 않도록 매핑 행 수가 아니라 고유 영상 수로 계산한다.
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
    summaries.sort(key=_place_summary_sort_key(sort))
    if limit is not None:
        return summaries[:limit]
    return summaries


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

    T-188의 SQL pushdown 전까지 기존 집계·filter semantics를 그대로 재사용한다. cursor
    scope에 버전을 넣어 T-188에서 PostgreSQL collation으로 바꿀 때 구 cursor를 명시적으로
    거부할 수 있게 한다.
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
        scope="destinations-python-v1", sort=sort, filters=filters
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

    summaries = await list_place_summaries(
        session,
        sort=sort,
        limit=None,
        channel_id=filters["channel_id"],
        playlist_id=filters["playlist_id"],
        keyword=filters["keyword"],
        video_id=filters["video_id"],
        category=filters["category"],
        query=filters["query"],
        district=filters["district"],
    )
    current_newest_id = max(
        (summary.place.place_id for summary in summaries), default=0
    )
    snapshot_id = decoded.snapshot_id if decoded is not None else current_newest_id
    snapshot_items = [
        summary for summary in summaries if summary.place.place_id <= snapshot_id
    ]
    total = len(snapshot_items)
    newer_than = (
        sum(
            1
            for summary in summaries
            if summary.place.place_id > newer_than_id
        )
        if newer_than_id is not None
        else 0
    )
    if decoded is not None:
        snapshot_items = [
            summary
            for summary in snapshot_items
            if _place_summary_cursor_key(summary, sort) > decoded.keys
        ]
    page_rows = snapshot_items[: limit + 1]
    has_more = len(page_rows) > limit
    items = page_rows[:limit]
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


def _place_matches_result_filters(
    place: TravelPlace,
    *,
    category: str | None,
    query: str | None,
    district: str | None,
) -> bool:
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
    # 매칭한 후보를 dirty로 표시해 다음 공급 GET에 반영한다(T-171).
    matched_candidate_ids = (
        await session.execute(
            select(ExtractedPlaceCandidate.id).where(
                ExtractedPlaceCandidate.matched_place_id == place.place_id,
                ExtractedPlaceCandidate.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    await feature_export_service.mark_candidates_dirty(
        session, list(matched_candidate_ids), reason="correct_place"
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

    # 장소 lifecycle 전역 lock 뒤 모든 관련 행을 mutation/autoflush 전에
    # candidate -> place -> mapping -> asset 순으로 잠근다.
    # geocode post-core 검증과 delete/authoritative 경로도 candidate를 먼저 잠그므로,
    # merge가 mapping을 먼저 UPDATE한 뒤 candidate를 기다리는 역순 deadlock을 만들지 않는다.
    await acquire_place_lifecycle_lock(session)
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
    target.last_reviewed_at = utcnow()
    await session.delete(source)
    # source→target으로 재배치된 후보의 export payload(place 이름·좌표·주소)가 바뀌므로
    # 같은 트랜잭션에서 dirty로 표시한다(T-171).
    await feature_export_service.mark_candidates_dirty(
        session,
        [candidate.id for candidate in moved_candidates],
        reason="merge_places",
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
    commit: bool = True,
) -> tuple[ExtractedPlaceCandidate, TravelPlace | None, VideoPlaceMapping | None]:
    """매칭 실패 후보를 기존 장소, 신규 장소, 제외 중 하나로 해결한다.

    신규 장소(`create_place`)의 8자리 category 코드 제안은 POI 추출 단계에서 후보
    evidence에 함께 저장해 둔 값을 복사한다(별도 Gemini 호출 없음, A안).
    soft delete된 후보는 해결할 수 없다(먼저 reopen 필요, T-160).
    """
    # 장소를 연결하거나 만드는 action은 candidate row보다 먼저 lifecycle lock을 잡는다.
    # merge/delete와 predicate-gap 없이 직렬화하고, 이후 공통 순서를
    # lifecycle advisory -> candidate -> place -> mapping으로 유지한다.
    if action in {"match_existing", "create_place"}:
        await acquire_place_lifecycle_lock(session)
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
                place.category_code_suggestion = selected_code
                place.category = selected_label
        else:
            place = TravelPlace(
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
    )
    if place is not None:
        mapping = await _ensure_candidate_mapping(session, candidate, place)
    # export payload에 영향을 주는 상태 전이(ignore=reject, match/create=upsert)를 같은
    # 트랜잭션의 dirty outbox에 기록한다(T-171). 다음 공급 GET이 이 후보만 동기화한다.
    await feature_export_service.mark_candidates_dirty(
        session, [candidate.id], reason=f"resolve:{action}"
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
    # merge_places와 같은 lifecycle advisory -> candidate -> place -> mapping -> asset
    # 순서로 관련 행을 전부 잠근 뒤 mutation을 시작한다. 후보가 없는 legacy mapping도
    # 존재할 수 있으므로 place를 먼저 잠그지 않고 mapping/asset을 변경하면 merge의
    # place-first 구간과 교착한다. autoflush도 잠금 집합이 완성될 때까지 억제한다.
    await acquire_place_lifecycle_lock(session)
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
        )
        .outerjoin(
            YoutubeVideo,
            YoutubeVideo.video_id == ExtractedPlaceCandidate.video_id,
        )
        .outerjoin(
            YoutubeChannel,
            YoutubeChannel.channel_id == YoutubeVideo.channel_id,
        )
        .where(ExtractedPlaceCandidate.deleted_at.is_(None))
    )
    if status is not None:
        stmt = stmt.where(ExtractedPlaceCandidate.match_status == status.value)
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
        "channel_id": channel_id or None,
        "playlist_id": playlist_id or None,
        "keyword": keyword or None,
        "q": normalized_query,
        "is_domestic": is_domestic,
        "status": status_value.value,
        "queue_reason": queue_reason.value if queue_reason else None,
        "source_kind": source_kind.value if source_kind else None,
        "grounding": grounding_status.value if grounding_status else None,
        "visible": "not_deleted",
    }
    fingerprint = filter_fingerprint(
        scope="unmatched-v4", sort=sort_value.value, filters=normalized_filters
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
    """page 밖 딥링크용 목록 항목 1건을 상태와 무관하게 직접 조회한다.

    `ignored`는 검수 이력으로 열람할 수 있지만 soft delete된 후보는 목록과 동일하게
    노출하지 않는다.
    """
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
    )


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
    # 행 락으로 동시 resolve(`resolve_candidate`도 FOR UPDATE)와 직렬화한다 —
    # 락 없이면 409 판정(매핑 유무)이 구버전 스냅샷을 읽는 race가 생긴다.
    candidates = list(
        (
            await session.execute(
                select(ExtractedPlaceCandidate)
                .where(
                    ExtractedPlaceCandidate.id.in_(ids),
                    ExtractedPlaceCandidate.deleted_at.is_(None),
                )
                .order_by(ExtractedPlaceCandidate.id.asc())
                .with_for_update()
                .execution_options(populate_existing=True, autoflush=False)
            )
        )
        .scalars()
        .all()
    )
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
    return SoftDeleteSummary(
        candidate_ids=live_ids,
        deleted_candidates=len(candidates),
        deleted_mappings=deleted_mappings,
        affected_place_ids=frozenset(affected_place_ids),
        tombstoned_exports=tombstoned,
    )


async def reopen_candidate(
    session: AsyncSession, *, candidate_id: int
) -> tuple[ExtractedPlaceCandidate, str]:
    """soft delete 또는 제외(`ignored`)된 후보를 검수 대기로 복귀한다(T-160, PR-09 백엔드).

    - soft deleted: 삭제 3필드를 clear 하고 `needs_review` + export `pending`으로
      되돌린다. 다음 `sync_feature_exports`는 재확정 전까지 tombstone을 유지하고,
      재확정(ready + 장소 매칭) 시 새 sequence의 upsert를 재발행한다.
    - `ignored`: `needs_review` + `pending` 복귀.
    - 이미 `needs_review`: `CandidateReopenConflictError`(409 — 복귀할 것이 없다).
    - `matched`/`user_corrected`: **의도적 이연** — `CandidateReopenUnsupportedError`(400).
      확정 해제는 reference count 기반 장소 정리(공유 장소 보호)와 함께 T-184에서
      구현한다.
    - 영상 제외(`exclude_video`)로 삭제된 후보를 reopen 해도
      `youtube_videos.is_excluded`는 별개 상태로 남는다(영상 제외 undo는 T-184
      정책 소관) — 후보만 검수 큐로 돌아오고 영상은 여전히 수집에서 스킵된다.

    반환: (후보, 복귀 출처 라벨 `deleted`|`ignored`) — 감사 로그용. flush까지만
    수행하고 commit은 호출자 책임이다.
    """
    candidate = await session.get(ExtractedPlaceCandidate, candidate_id)
    if candidate is None:
        raise ValueError(f"candidate not found: {candidate_id}")
    if candidate.deleted_at is not None:
        candidate.deleted_at = None
        candidate.deletion_reason = None
        candidate.deleted_by = None
        candidate.match_status = MatchStatus.NEEDS_REVIEW
        candidate.feature_export_status = FeatureExportStatus.PENDING.value
        # 검수자 메타는 clear(재검수 시 stale 표시 방지), review_note는 직전 판정
        # 사유 참고 가치가 있어 보존한다.
        candidate.reviewed_by = None
        candidate.reviewed_at = None
        # 복귀(needs_review+pending)로 기존 export가 tombstone 회수돼야 하므로 dirty로
        # 표시한다(T-171). 재확정 전까지 sync는 tombstone을 유지한다(freeze).
        await feature_export_service.mark_candidates_dirty(
            session, [candidate.id], reason="reopen:deleted"
        )
        await session.flush()
        return candidate, "deleted"
    if candidate.match_status == MatchStatus.IGNORED.value:
        candidate.match_status = MatchStatus.NEEDS_REVIEW
        candidate.feature_export_status = FeatureExportStatus.PENDING.value
        # 검수자 메타는 clear(재검수 시 stale 표시 방지), review_note는 보존.
        candidate.reviewed_by = None
        candidate.reviewed_at = None
        await feature_export_service.mark_candidates_dirty(
            session, [candidate.id], reason="reopen:ignored"
        )
        await session.flush()
        return candidate, "ignored"
    if candidate.match_status == MatchStatus.NEEDS_REVIEW.value:
        raise CandidateReopenConflictError(
            "이미 검수 대기(needs_review) 상태라 복귀할 것이 없습니다."
        )
    raise CandidateReopenUnsupportedError(
        "확정(matched/user_corrected)된 후보의 되돌리기는 지원하지 않습니다"
        " (장소 정리 정책은 T-184에서 다룬다)."
    )


async def exclude_video(
    session: AsyncSession,
    video_id: str,
    *,
    reason: str | None = None,
    excluded_by: str | None = "web",
) -> dict[str, Any] | None:
    """동영상을 제외(블록리스트)하고 관련 POI를 정리한다.

    영상을 `is_excluded=True`로 표시(이후 수집에서 스킵), 이 영상의 추출 후보를
    **soft delete**(T-160 — 행·export ledger 보존, 이미 export된 건 tombstone 전환)
    하고 언급 매핑을 삭제하며, 다른 영상이 더 이상 언급하지 않아 고아가 된 장소만
    삭제한다. 다른 영상이 같은 장소를 언급하면 그 장소·언급은 보존한다.
    반환: 정리 건수 요약. 영상을 찾지 못하면 None.
    """
    video = await session.get(YoutubeVideo, video_id)
    if video is None:
        return None
    # 이후 candidate/mapping 정리와 orphan place 삭제를 하나의 장소 lifecycle
    # 임계구간에 둔다. merge/delete/geocode가 중간 predicate snapshot을 관측하지 않는다.
    await acquire_place_lifecycle_lock(session)
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

    await session.commit()
    return {
        "video_id": video_id,
        "deleted_candidates": soft_summary.deleted_candidates,
        "deleted_mappings": deleted_mappings,
        "deleted_places": deleted_places,
        "tombstoned_exports": soft_summary.tombstoned_exports,
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
