"""범용 feature 수집 API용 export ledger 서비스.

`extracted_place_candidates`를 출처로 삼아 `feature_exports` ledger를 멱등 동기화하고,
full snapshot / incremental changes를 opaque cursor 기반으로 페이지네이션한다.
(ADR-26, `docs/youtube-feature-pipeline-plan.md` 7장)

설계 원칙:

- 후보 1건 = export 1건(`export_id = "ytpc_{candidate_id}"`). consumer는
  `python-krtour-map`이며 `feature_id` 생성은 consumer 책임이다.
- `sequence`는 payload가 의미 있게 바뀔 때만 nextval로 갱신한다. 변화가 없으면
  ledger도 그대로라 cursor가 안정적이다(반복 호출이 churn을 만들지 않는다).
- snapshot은 현재 활성(`upsert`) export만, changes는 `upsert`/`reject`/`tombstone`을
  모두 sequence 오름차순으로 노출한다.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ktc.models import (
    ExtractedPlaceCandidate,
    FeatureExport,
    FeatureExportOperation,
    FeatureExportStatus,
    MatchStatus,
    TravelPlace,
    YoutubeChannel,
    YoutubePlaylist,
    YoutubeVideo,
    feature_export_sequence,
    utcnow,
)

# `python-krtour-map` `SourceRecord` 계약과 맞추는 provider 식별자.
PROVIDER = "kor-travel-concierge-youtube"
DATASET_KEY = "youtube_place_candidates"
SOURCE_ENTITY_TYPE = "extracted_place_candidate"

EXPORTABLE_STATUSES = {
    FeatureExportStatus.READY.value,
    FeatureExportStatus.EXPORTED.value,
}

FEATURE_EXPORT_LIMIT_DEFAULT = 200
FEATURE_EXPORT_LIMIT_MAX = 500


@dataclass(frozen=True)
class FeatureExportPage:
    """페이지네이션 결과."""

    items: list[dict[str, Any]]
    next_cursor: str | None
    has_more: bool


# --- cursor (opaque) ---


def _encode_cursor(sequence: int) -> str:
    raw = str(int(sequence)).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor: str | None) -> int | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        return int(raw.decode("ascii"))
    except (ValueError, binascii.Error) as exc:
        raise ValueError(f"유효하지 않은 cursor: {cursor}") from exc


def normalize_limit(limit: int) -> int:
    return max(1, min(limit, FEATURE_EXPORT_LIMIT_MAX))


# --- payload 빌드 ---


def _video_summary(video: YoutubeVideo | None) -> str | None:
    if video is None:
        return None
    return video.reconciled_summary or video.transcript_summary or video.gemini_url_summary


def _source_title(
    *,
    video: YoutubeVideo | None,
    channel: YoutubeChannel | None,
    playlist: YoutubePlaylist | None,
) -> str | None:
    if video is not None:
        if video.source_target_type == "keyword":
            return video.source_search_query or video.source_target_value
        if video.source_target_type == "playlist":
            return (
                playlist.title
                if playlist is not None
                else video.source_target_value
            )
        if video.source_target_type == "channel":
            return channel.title if channel is not None else video.source_target_value
    if playlist is not None:
        return playlist.title
    if channel is not None:
        return channel.title
    return None


def _providers(candidate: ExtractedPlaceCandidate) -> dict[str, Any]:
    evidence = candidate.provider_evidence_json or {}
    if not isinstance(evidence, dict):
        return {}
    geocoding = evidence.get("geocoding")
    if isinstance(geocoding, dict):
        provider_candidates = geocoding.get("provider_candidates")
        if isinstance(provider_candidates, dict):
            return provider_candidates
    return {}


def _gemini_url_evidence(candidate: ExtractedPlaceCandidate) -> Any:
    evidence = candidate.provider_evidence_json or {}
    if isinstance(evidence, dict):
        return evidence.get("gemini_url_evidence")
    return None


def _build_payload(
    candidate: ExtractedPlaceCandidate,
    *,
    video: YoutubeVideo | None,
    channel: YoutubeChannel | None,
    playlist: YoutubePlaylist | None,
    place: TravelPlace | None,
) -> dict[str, Any]:
    """API 응답 item의 본문(payload)을 만든다.

    `source_record.raw_payload_hash`는 payload_hash 자체이므로 여기서는 넣지 않고,
    직렬화 시점에 ledger row의 `payload_hash`로 주입한다(순환 해시 방지).
    """
    place_block = {
        "name": place.name if place else candidate.ai_place_name,
        "description": place.description if place else None,
        "gemini_enriched_description": (
            place.gemini_enriched_description if place else None
        ),
        "category_label": place.category if place else candidate.candidate_category,
        # Gemini가 복사된 `python-krtour-map` 코드표에서 고른 8자리 제안값(T-070).
        # 아직 채워지지 않았으면 None(`feature_id`/카테고리 확정은 consumer 책임).
        "category_code_suggestion": (
            place.category_code_suggestion if place else None
        ),
        "longitude": place.longitude if place else None,
        "latitude": place.latitude if place else None,
        "address": {
            "official_address": place.official_address if place else None,
            "road_address": place.road_address if place else None,
            "legal_dong_code": None,
            "sido_code": None,
            "sigungu_code": None,
        },
    }
    youtube_block = {
        "video_id": candidate.video_id,
        "video_url": (video.canonical_url or video.url) if video else None,
        "video_title": video.title if video else None,
        "video_summary": _video_summary(video),
        "source_type": video.source_target_type if video else None,
        "source_value": video.source_target_value if video else None,
        "source_title": _source_title(video=video, channel=channel, playlist=playlist),
        "source_search_query": video.source_search_query if video else None,
        "corrected_search_query": (
            video.source_search_query
            if video is not None and video.source_target_type == "keyword"
            else None
        ),
        "channel_id": channel.channel_id if channel else candidate.source_channel_id,
        "channel_title": channel.title if channel else None,
        "channel_summary": channel.gemini_summary if channel else None,
        "playlist_id": (
            playlist.playlist_id if playlist else candidate.source_playlist_id
        ),
        "playlist_title": playlist.title if playlist else None,
    }
    evidence_block = {
        "timestamp_start": candidate.timestamp_start,
        "timestamp_end": candidate.timestamp_end,
        "transcript_excerpt": candidate.source_text,
        "gemini_url_evidence": _gemini_url_evidence(candidate),
        "confidence_score": candidate.confidence_score,
        "providers": _providers(candidate),
    }
    source_record = {
        "provider": PROVIDER,
        "dataset_key": DATASET_KEY,
        "source_entity_type": SOURCE_ENTITY_TYPE,
        "source_entity_id": str(candidate.id),
    }
    return {
        "candidate_id": candidate.id,
        "place": place_block,
        "youtube": youtube_block,
        "evidence": evidence_block,
        "source_record": source_record,
    }


def _payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _classify(
    candidate: ExtractedPlaceCandidate, *, has_row: bool
) -> tuple[str | None, str | None, str | None]:
    """후보 상태로부터 (operation, export_state, rejection_reason)을 정한다.

    `operation`이 None이면 ledger에 넣지 않는다(아직 노출한 적 없는 미확정 후보).
    """
    status = candidate.feature_export_status
    is_rejected = (
        candidate.match_status == MatchStatus.IGNORED.value
        or status == FeatureExportStatus.REJECTED.value
    )
    if is_rejected:
        # 한 번도 내보낸 적 없는 후보의 reject는 consumer에게 noise라 생략한다.
        if has_row:
            return (
                FeatureExportOperation.REJECT.value,
                FeatureExportStatus.REJECTED.value,
                candidate.review_note,
            )
        return None, None, None
    if status in EXPORTABLE_STATUSES and candidate.matched_place_id is not None:
        return FeatureExportOperation.UPSERT.value, status, None
    # pending/needs_review: 과거 export가 있으면 tombstone, 없으면 미노출.
    if has_row:
        return FeatureExportOperation.TOMBSTONE.value, status, None
    return None, None, None


async def _next_sequence(session: AsyncSession) -> int:
    value = await session.scalar(select(feature_export_sequence.next_value()))
    return int(value)


async def tombstone_candidate_exports(
    session: AsyncSession,
    candidate_ids: Sequence[int],
    *,
    reason: str | None = None,
) -> int:
    """후보 soft delete와 같은 트랜잭션에서 ledger 행을 tombstone으로 전환한다(T-160, B1).

    이미 export된(ledger 행이 있는) 후보만 대상이다. 행이 없으면(한 번도 노출된 적
    없는 후보) 의미 없는 tombstone을 만들지 않는다. 이미 tombstone인 행은 그대로
    둔다 — soft delete된 후보는 `sync_feature_exports` 스캔에서도 제외돼 '후보 소멸'
    분류(tombstone)로 잡히므로, 이 helper와 다음 sync의 결과가 같아야 한다(멱등).
    전환 행에는 새 sequence를 할당해 consumer가 `changes` cursor로 제거를 전달받는다.
    commit은 호출자 책임이다. 전환 건수를 반환한다.
    """
    ids = [int(cid) for cid in candidate_ids]
    if not ids:
        return 0
    rows = list(
        (
            await session.execute(
                select(FeatureExport).where(FeatureExport.candidate_id.in_(ids))
            )
        )
        .scalars()
        .all()
    )
    now = utcnow()
    changed = 0
    for row in rows:
        if row.operation == FeatureExportOperation.TOMBSTONE.value:
            continue
        row.operation = FeatureExportOperation.TOMBSTONE.value
        if reason:
            row.rejection_reason = reason
        row.updated_at = now
        row.sequence = await _next_sequence(session)
        changed += 1
    return changed


async def _load_related(
    session: AsyncSession, candidates: list[ExtractedPlaceCandidate]
) -> tuple[
    dict[str, YoutubeVideo],
    dict[str, YoutubeChannel],
    dict[str, YoutubePlaylist],
    dict[int, TravelPlace],
]:
    video_ids = {c.video_id for c in candidates if c.video_id}
    playlist_ids = {c.source_playlist_id for c in candidates if c.source_playlist_id}
    place_ids = {c.matched_place_id for c in candidates if c.matched_place_id}

    videos: dict[str, YoutubeVideo] = {}
    if video_ids:
        result = await session.execute(
            select(YoutubeVideo).where(YoutubeVideo.video_id.in_(video_ids))
        )
        videos = {v.video_id: v for v in result.scalars()}

    channel_ids = {c.source_channel_id for c in candidates if c.source_channel_id}
    channel_ids |= {v.channel_id for v in videos.values() if v.channel_id}
    channels: dict[str, YoutubeChannel] = {}
    if channel_ids:
        result = await session.execute(
            select(YoutubeChannel).where(YoutubeChannel.channel_id.in_(channel_ids))
        )
        channels = {c.channel_id: c for c in result.scalars()}

    playlists: dict[str, YoutubePlaylist] = {}
    if playlist_ids:
        result = await session.execute(
            select(YoutubePlaylist).where(
                YoutubePlaylist.playlist_id.in_(playlist_ids)
            )
        )
        playlists = {p.playlist_id: p for p in result.scalars()}

    places: dict[int, TravelPlace] = {}
    if place_ids:
        result = await session.execute(
            select(TravelPlace).where(TravelPlace.place_id.in_(place_ids))
        )
        places = {p.place_id: p for p in result.scalars()}

    return videos, channels, playlists, places


async def sync_feature_exports(session: AsyncSession, *, commit: bool = True) -> int:
    """후보 테이블로부터 `feature_exports` ledger를 멱등 동기화한다.

    payload가 바뀐 export에만 새 sequence를 부여한다. 변경 건수를 반환한다.

    soft delete된 후보(`deleted_at IS NOT NULL`)는 스캔에서 제외한다(T-160). 이들의
    ledger 행은 아래 '후보 소멸' 루프에서 tombstone으로 잡히므로, 삭제 트랜잭션의
    `tombstone_candidate_exports`가 어떤 이유로 누락돼도 다음 sync가 복구하는
    이중 안전망이 된다.
    """
    candidates = list(
        (
            await session.execute(
                select(ExtractedPlaceCandidate).where(
                    ExtractedPlaceCandidate.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    videos, channels, playlists, places = await _load_related(session, candidates)

    existing_rows = list(
        (await session.execute(select(FeatureExport))).scalars().all()
    )
    existing_by_candidate = {row.candidate_id: row for row in existing_rows}

    now = utcnow()
    changed = 0
    seen_candidate_ids: set[int] = set()

    for candidate in candidates:
        seen_candidate_ids.add(candidate.id)
        row = existing_by_candidate.get(candidate.id)
        operation, export_state, rejection_reason = _classify(
            candidate, has_row=row is not None
        )
        if operation is None:
            continue

        video = videos.get(candidate.video_id) if candidate.video_id else None
        channel_id = candidate.source_channel_id or (
            video.channel_id if video else None
        )
        channel = channels.get(channel_id) if channel_id else None
        playlist = (
            playlists.get(candidate.source_playlist_id)
            if candidate.source_playlist_id
            else None
        )
        place = (
            places.get(candidate.matched_place_id)
            if candidate.matched_place_id
            else None
        )
        payload = _build_payload(
            candidate, video=video, channel=channel, playlist=playlist, place=place
        )
        payload_hash = _payload_hash(payload)

        if row is None:
            session.add(
                FeatureExport(
                    export_id=f"ytpc_{candidate.id}",
                    sequence=await _next_sequence(session),
                    candidate_id=candidate.id,
                    operation=operation,
                    export_state=export_state or "",
                    payload_json=payload,
                    payload_hash=payload_hash,
                    rejection_reason=rejection_reason,
                    created_at=now,
                    updated_at=now,
                )
            )
            changed += 1
            continue

        # tombstone → tombstone 재분류는 갱신하지 않는다(freeze, T-160 리뷰).
        # tombstone은 제거 마커라 payload/state/reason 갱신이 consumer에 의미가
        # 없고, reopen 직후(`needs_review`+`pending`, has_row) 후보가 스캔에 다시
        # 들어올 때 sync가 tombstone을 재sequence하는 소음을 막는다. 삭제 시 기록한
        # 사유와 마지막 payload는 그대로 보존되며, upsert/reject로의 전이는 여전히
        # 새 sequence로 발행된다.
        if (
            operation == FeatureExportOperation.TOMBSTONE.value
            and row.operation == FeatureExportOperation.TOMBSTONE.value
        ):
            continue
        if (
            row.operation == operation
            and row.payload_hash == payload_hash
            and row.export_state == export_state
            and row.rejection_reason == rejection_reason
        ):
            continue
        row.operation = operation
        row.export_state = export_state or row.export_state
        row.payload_json = payload
        row.payload_hash = payload_hash
        row.rejection_reason = rejection_reason
        row.updated_at = now
        row.sequence = await _next_sequence(session)
        changed += 1

    # 후보가 사라진(soft delete 포함 — 스캔 제외) ledger row는 tombstone으로 전환한다.
    for row in existing_rows:
        if (
            row.candidate_id not in seen_candidate_ids
            and row.operation != FeatureExportOperation.TOMBSTONE.value
        ):
            row.operation = FeatureExportOperation.TOMBSTONE.value
            row.updated_at = now
            row.sequence = await _next_sequence(session)
            changed += 1

    if commit:
        await session.commit()
    return changed


# --- 직렬화 / 페이지네이션 ---


def _serialize_item(row: FeatureExport) -> dict[str, Any]:
    item = dict(row.payload_json)
    item["export_id"] = row.export_id
    item["operation"] = row.operation
    item["updated_at"] = row.updated_at.isoformat() if row.updated_at else None
    source_record = dict(item.get("source_record") or {})
    source_record["raw_payload_hash"] = row.payload_hash
    item["source_record"] = source_record
    if row.operation in {
        FeatureExportOperation.REJECT.value,
        FeatureExportOperation.TOMBSTONE.value,
    }:
        item["rejection_reason"] = row.rejection_reason
    return item


async def _read_page(
    session: AsyncSession,
    *,
    cursor: str | None,
    limit: int,
    only_active: bool,
) -> FeatureExportPage:
    after = _decode_cursor(cursor)
    page_limit = normalize_limit(limit)
    stmt = select(FeatureExport)
    if only_active:
        stmt = stmt.where(
            FeatureExport.operation == FeatureExportOperation.UPSERT.value
        )
    if after is not None:
        stmt = stmt.where(FeatureExport.sequence > after)
    stmt = stmt.order_by(FeatureExport.sequence.asc()).limit(page_limit + 1)
    rows = list((await session.execute(stmt)).scalars().all())

    has_more = len(rows) > page_limit
    rows = rows[:page_limit]
    items = [_serialize_item(row) for row in rows]

    if rows:
        next_cursor: str | None = _encode_cursor(rows[-1].sequence)
        now = utcnow()
        for row in rows:
            row.last_exported_at = now
        await session.commit()
    else:
        # 변경이 없으면 입력 cursor를 그대로 유지해 다음 polling이 재스캔하지 않게 한다.
        next_cursor = cursor or None

    return FeatureExportPage(items=items, next_cursor=next_cursor, has_more=has_more)


async def get_snapshot(
    session: AsyncSession,
    *,
    cursor: str | None = None,
    limit: int = FEATURE_EXPORT_LIMIT_DEFAULT,
) -> FeatureExportPage:
    """현재 활성(`upsert`) feature를 full snapshot으로 노출한다."""
    await sync_feature_exports(session)
    return await _read_page(
        session, cursor=cursor, limit=limit, only_active=True
    )


async def get_changes(
    session: AsyncSession,
    *,
    cursor: str | None = None,
    limit: int = FEATURE_EXPORT_LIMIT_DEFAULT,
) -> FeatureExportPage:
    """`upsert`/`reject`/`tombstone` 변경을 incremental로 노출한다."""
    await sync_feature_exports(session)
    return await _read_page(
        session, cursor=cursor, limit=limit, only_active=False
    )
