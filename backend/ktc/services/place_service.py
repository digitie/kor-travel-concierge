"""장소 조회 및 근접 중복 후보 탐색 서비스 (저장소 계층)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import cast, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ktc.core.spatial import sync_place_geometry
from ktc.models import (
    ExtractedPlaceCandidate,
    FeatureExportStatus,
    MatchStatus,
    MediaAsset,
    TravelPlace,
    VideoPlaceMapping,
    YoutubeVideo,
    utcnow,
)

EARTH_RADIUS_M = 6_371_000.0


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
) -> list[tuple[TravelPlace, float]]:
    """PostGIS `ST_DWithin`으로 반경 내 장소를 거리 오름차순 반환한다."""
    point = func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)
    place_geog = cast(TravelPlace.geom, Geography)
    point_geog = cast(point, Geography)
    distance_m = func.ST_Distance(place_geog, point_geog)
    stmt = (
        select(TravelPlace, distance_m.label("distance_m"))
        .where(
            TravelPlace.is_geocoded.is_(True),
            TravelPlace.geom.is_not(None),
            func.ST_DWithin(place_geog, point_geog, radius_meters),
        )
        .order_by(distance_m.asc(), TravelPlace.place_id.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [(place, float(distance or 0.0)) for place, distance in result.all()]


async def find_duplicate_candidates(
    session: AsyncSession,
    *,
    lat: float,
    lng: float,
    radius_meters: float = 100.0,
    limit: int = 5,
) -> list[tuple[TravelPlace, float]]:
    """좌표 근접성 기반 중복 의심 장소를 반환한다.

    신규 후보를 확정 장소로 승격하기 전, 같은 좌표 근방의 기존 장소를 찾아 중복
    생성을 방지하는 용도다.
    """
    return await find_places_within_radius(
        session, lat=lat, lng=lng, radius_meters=radius_meters, limit=limit
    )


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
) -> list[PlaceSummary]:
    """확정 장소 목록과 영상·유튜버 언급 근거를 함께 조회한다."""
    stmt = select(TravelPlace)
    if place_ids:
        stmt = stmt.where(TravelPlace.place_id.in_(place_ids))
    result = await session.execute(stmt)
    places = list(result.scalars().all())
    if not places:
        return []

    mentions_by_place = await _list_mentions_by_place(
        session, place_ids=[place.place_id for place in places]
    )
    summaries = [
        PlaceSummary(
            place=place,
            mention_count=len(mentions_by_place.get(place.place_id, [])),
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
        return lambda item: (item.place.category or "미분류", item.place.name)
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
    """확정 장소에 연결된 추출 후보를 조회한다."""
    stmt = (
        select(ExtractedPlaceCandidate)
        .where(ExtractedPlaceCandidate.matched_place_id == place_id)
        .order_by(ExtractedPlaceCandidate.id.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def correct_place(
    session: AsyncSession,
    *,
    place_id: int,
    updates: dict[str, Any],
    commit: bool = True,
) -> TravelPlace:
    """장소명·주소·좌표·카테고리·설명을 수동 보정한다."""
    place = await session.get(TravelPlace, place_id)
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
    applied = {key: value for key, value in updates.items() if key in allowed}
    if not applied:
        raise ValueError("보정할 필드가 필요하다")
    for key, value in applied.items():
        setattr(place, key, value)
    if ("latitude" in applied or "longitude" in applied) and "is_geocoded" not in applied:
        place.is_geocoded = True
    if ("latitude" in applied or "longitude" in applied) and place.is_geocoded:
        await sync_place_geometry(session, place.place_id, place.latitude, place.longitude)
    place.last_reviewed_at = utcnow()
    if commit:
        await session.commit()
        await session.refresh(place)
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

    source = await session.get(TravelPlace, source_place_id)
    target = await session.get(TravelPlace, target_place_id)
    if source is None:
        raise ValueError(f"source place not found: {source_place_id}")
    if target is None:
        raise ValueError(f"target place not found: {target_place_id}")

    mapping_result = await session.execute(
        select(VideoPlaceMapping).where(VideoPlaceMapping.place_id == source_place_id)
    )
    moved_mappings = list(mapping_result.scalars().all())
    for mapping in moved_mappings:
        mapping.place_id = target_place_id

    candidate_result = await session.execute(
        select(ExtractedPlaceCandidate).where(
            ExtractedPlaceCandidate.matched_place_id == source_place_id
        )
    )
    moved_candidates = list(candidate_result.scalars().all())
    for candidate in moved_candidates:
        candidate.matched_place_id = target_place_id

    asset_result = await session.execute(
        select(MediaAsset).where(MediaAsset.place_id == source_place_id)
    )
    moved_assets = list(asset_result.scalars().all())
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
    candidate = await session.get(ExtractedPlaceCandidate, candidate_id)
    if candidate is None:
        raise ValueError(f"candidate not found: {candidate_id}")
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
    return code if isinstance(code, str) and code else None


async def resolve_candidate(
    session: AsyncSession,
    *,
    candidate_id: int,
    action: str,
    reviewed_by: str,
    review_note: str | None = None,
    place_id: int | None = None,
    place_data: dict[str, Any] | None = None,
    commit: bool = True,
) -> tuple[ExtractedPlaceCandidate, TravelPlace | None, VideoPlaceMapping | None]:
    """매칭 실패 후보를 기존 장소, 신규 장소, 제외 중 하나로 해결한다.

    신규 장소(`create_place`)의 8자리 category 코드 제안은 POI 추출 단계에서 후보
    evidence에 함께 저장해 둔 값을 복사한다(별도 Gemini 호출 없음, A안).
    """
    candidate = await session.get(ExtractedPlaceCandidate, candidate_id)
    if candidate is None:
        raise ValueError(f"candidate not found: {candidate_id}")

    place: TravelPlace | None = None
    mapping: VideoPlaceMapping | None = None
    if action == "ignore":
        candidate.match_status = MatchStatus.IGNORED
        candidate.feature_export_status = FeatureExportStatus.REJECTED.value
    elif action == "match_existing":
        if place_id is None:
            raise ValueError("기존 장소 매칭에는 place_id가 필요하다")
        place = await session.get(TravelPlace, place_id)
        if place is None:
            raise ValueError(f"place not found: {place_id}")
        candidate.match_status = MatchStatus.USER_CORRECTED
        candidate.matched_place_id = place.place_id
        candidate.feature_export_status = FeatureExportStatus.READY.value
        mapping = await _ensure_candidate_mapping(session, candidate, place)
    elif action == "create_place":
        data = place_data or {}
        required = ("name", "latitude", "longitude")
        missing = [key for key in required if data.get(key) is None]
        if missing:
            raise ValueError(f"신규 장소 생성에는 {', '.join(missing)} 값이 필요하다")
        # 좌표 근접 중복: 같은 위치에 기존 장소가 있으면 신규 생성 대신 그 장소에 매핑한다
        # (여러 영상이 같은 장소를 가리킬 때 동일 좌표 장소가 무한 중복되던 문제 방지).
        dups = await find_duplicate_candidates(
            session, lat=data["latitude"], lng=data["longitude"]
        )
        if dups:
            place = dups[0][0]
        else:
            place = TravelPlace(
                name=data["name"],
                description=data.get("description"),
                gemini_enriched_description=data.get("gemini_enriched_description"),
                official_address=data.get("official_address"),
                road_address=data.get("road_address"),
                latitude=data["latitude"],
                longitude=data["longitude"],
                api_source=data.get("api_source") or "manual",
                category=data.get("category") or candidate.candidate_category,
                is_geocoded=True,
                last_reviewed_at=utcnow(),
            )
            session.add(place)
            await session.flush()
            await sync_place_geometry(
                session, place.place_id, place.latitude, place.longitude
            )
            # 8자리 카테고리 코드는 POI 추출 때 후보 evidence에 저장해 둔 값을 복사한다
            # (별도 Gemini 호출 없음, A안). 없으면 비워 둔다(best-effort, null 허용).
            code = candidate_category_code(candidate)
            if code:
                place.category_code_suggestion = code
        candidate.match_status = MatchStatus.USER_CORRECTED
        candidate.matched_place_id = place.place_id
        candidate.feature_export_status = FeatureExportStatus.READY.value
        mapping = await _ensure_candidate_mapping(session, candidate, place)
    else:
        raise ValueError(f"지원하지 않는 후보 해결 action: {action}")

    candidate.reviewed_by = reviewed_by
    candidate.reviewed_at = utcnow()
    candidate.review_note = review_note
    if commit:
        await session.commit()
        await session.refresh(candidate)
        if place is not None:
            await session.refresh(place)
        if mapping is not None:
            await session.refresh(mapping)
    return candidate, place, mapping


async def _ensure_candidate_mapping(
    session: AsyncSession,
    candidate: ExtractedPlaceCandidate,
    place: TravelPlace,
) -> VideoPlaceMapping:
    stmt = select(VideoPlaceMapping).where(
        VideoPlaceMapping.video_id == candidate.video_id,
        VideoPlaceMapping.place_candidate_id == candidate.id,
    )
    result = await session.execute(stmt)
    mapping = result.scalars().first()
    if mapping is None:
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
        mapping.place_id = place.place_id
        mapping.source_channel_id = candidate.source_channel_id
        mapping.source_playlist_id = candidate.source_playlist_id
        mapping.analysis_run_id = candidate.analysis_run_id
        mapping.source_kind = candidate.source_kind
        mapping.provider_evidence_json = candidate.provider_evidence_json
        mapping.feature_export_status = candidate.feature_export_status
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
    place = await session.get(TravelPlace, place_id)
    if place is None:
        raise ValueError(f"place not found: {place_id}")
    reverted = list(
        (
            await session.execute(
                select(ExtractedPlaceCandidate).where(
                    ExtractedPlaceCandidate.matched_place_id == place_id
                )
            )
        )
        .scalars()
        .all()
    )
    for candidate in reverted:
        candidate.matched_place_id = None
        candidate.match_status = MatchStatus.NEEDS_REVIEW
        candidate.feature_export_status = FeatureExportStatus.PENDING.value
    await session.execute(
        update(MediaAsset).where(MediaAsset.place_id == place_id).values(place_id=None)
    )
    await session.execute(
        delete(VideoPlaceMapping).where(VideoPlaceMapping.place_id == place_id)
    )
    await session.delete(place)
    await session.flush()
    return reverted


async def list_unmatched_candidates(
    session: AsyncSession, *, limit: int = 500
) -> list[ExtractedPlaceCandidate]:
    """`needs_review` 상태의 매칭 실패 후보를 조회한다."""
    stmt = (
        select(ExtractedPlaceCandidate)
        .where(ExtractedPlaceCandidate.match_status == MatchStatus.NEEDS_REVIEW)
        .order_by(ExtractedPlaceCandidate.id.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
