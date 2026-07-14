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

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ktc.models import (
    EvidenceSourceKind,
    ExportDirtyOutbox,
    ExtractedPlaceCandidate,
    FeatureExport,
    FeatureExportOperation,
    FeatureExportStatus,
    GroundingStatus,
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

# item payload 계약 버전(T-189). additive 확장이므로 소비자는 이 값을 무시해도 되고,
# 파괴적 스키마 변경이 필요할 때만 증가한다. payload 본문에 넣어 hash에 반영하므로,
# 이 값이 바뀌면 전 export가 새 sequence로 자연 재발행되고 consumer가 재수신한다.
SCHEMA_VERSION = 1


class InvalidCursorError(ValueError):
    """opaque cursor 디코드 실패. routes가 error `code`를 구분하는 데 쓴다(T-189).

    `ValueError`를 상속해 기존 `except ValueError` 경로와 호환된다.
    """

EXPORTABLE_STATUSES = {
    FeatureExportStatus.READY.value,
    FeatureExportStatus.EXPORTED.value,
}

FEATURE_EXPORT_LIMIT_DEFAULT = 200
FEATURE_EXPORT_LIMIT_MAX = 500
FEATURE_EXPORT_ADVISORY_LOCK_ID = 175


async def acquire_feature_export_lock(session: AsyncSession) -> None:
    """feature ledger 분류·전환 writer를 transaction 단위로 직렬화한다.

    장소 생명주기 mutation과 함께 잡을 때의 전역 순서는 반드시
    `place lifecycle(174) → feature export(175) → candidate/place row`다. 독립
    sync는 이 lock만 먼저 잡고 candidate snapshot을 읽는다.
    이 순서로 sync가 과거 READY snapshot을 읽어 만든 늦은 upsert가 soft delete/reopen의
    tombstone 뒤에 commit되는 write skew를 막는다.
    """
    await session.execute(
        select(func.pg_advisory_xact_lock(FEATURE_EXPORT_ADVISORY_LOCK_ID))
        .execution_options(autoflush=False)
    )


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
        raise InvalidCursorError(f"유효하지 않은 cursor: {cursor}") from exc


def normalize_limit(limit: int) -> int:
    return max(1, min(limit, FEATURE_EXPORT_LIMIT_MAX))


# --- payload 빌드 ---


def export_video_summary(video: YoutubeVideo | None) -> str | None:
    """공급 payload와 writer dirty 판정이 공유하는 영상 요약 우선순위다."""
    if video is None:
        return None
    return (
        video.reconciled_summary
        or video.transcript_summary
        or video.gemini_url_summary
    )


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
    # 행정코드는 place 실데이터에서 주입한다(T-189). `sido_code` 전용 컬럼은 없으므로
    # 행정표준 코드 앞 2자리가 시도라는 규칙으로 유도한다. 시군구 코드를 우선 쓰고, 없으면
    # 법정동 코드 앞 2자리로 fallback한다(sigungu 없이 legal_dong만 있는 경우). 둘 다 없으면 None.
    sigungu_code = place.sigungu_code if place else None
    legal_dong_code = place.legal_dong_code if place else None
    if sigungu_code:
        sido_code = sigungu_code[:2]
    elif legal_dong_code:
        sido_code = legal_dong_code[:2]
    else:
        sido_code = None
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
            "legal_dong_code": legal_dong_code,
            "sido_code": sido_code,
            "sigungu_code": sigungu_code,
        },
    }
    youtube_block = {
        "video_id": candidate.video_id,
        "video_url": (video.canonical_url or video.url) if video else None,
        "video_title": video.title if video else None,
        "video_summary": export_video_summary(video),
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
        # 계약 버전을 payload에 두어 hash에 반영한다(additive). 소비자는 무시해도 되며,
        # 이 값 변경 시 전 item이 재발행된다.
        "schema_version": SCHEMA_VERSION,
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


# 재처리로 grounding이 **실제 판정**돼 실패한 상태(=근거가 원문에 없음). export 차단·
# tombstone 회수는 이 두 상태에만 적용한다.
_GROUNDING_EXPORT_BLOCK = frozenset(
    {GroundingStatus.UNVERIFIED.value, GroundingStatus.MISSING.value}
)


def _export_grounding_blocked(candidate: ExtractedPlaceCandidate) -> bool:
    """transcript 후보가 재처리로 grounding 실패(unverified/missing)로 판정되면 export를 막는다.

    T-165 G4의 defense-in-depth. 단, **legacy_unknown은 차단하지 않는다**(코디네이터 MAJOR 2):
    migration이 기존 MATCHED·export된 후보를 legacy_unknown으로 backfill하는데, 이를 차단하면
    `_classify`가 대량 TOMBSTONE을 발행해 krtour-map/PinVi에 inactive가 쏟아지고 curated plan
    POI가 소실된다. "재처리 전까지 기존 노출 유지, 재평가로 unverified/missing이 되면 회수"
    원칙을 따른다. verified_raw·not_applicable도 허용, 사람 확정(user_corrected)도 허용한다.
    LLM 자가 보고 confidence는 이 판단에 쓰지 않는다.
    """
    if candidate.source_kind != EvidenceSourceKind.TRANSCRIPT.value:
        return False
    if candidate.match_status == MatchStatus.USER_CORRECTED.value:
        return False
    return candidate.grounding_status in _GROUNDING_EXPORT_BLOCK


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
    if (
        status in EXPORTABLE_STATUSES
        and candidate.match_status
        in {
            MatchStatus.MATCHED.value,
            MatchStatus.USER_CORRECTED.value,
        }
        and candidate.matched_place_id is not None
        and not _export_grounding_blocked(candidate)
    ):
        return FeatureExportOperation.UPSERT.value, status, None
    # pending/needs_review(또는 grounding 미확인 auto-match): 과거 export가 있으면
    # tombstone으로 회수, 없으면 미노출.
    if has_row:
        return FeatureExportOperation.TOMBSTONE.value, status, None
    return None, None, None


async def mark_candidates_dirty(
    session: AsyncSession,
    candidate_ids: Sequence[int],
    reason: str,
    *,
    marked_at: Any | None = None,
) -> None:
    """export payload에 영향을 주는 후보 변경을 durable dirty outbox에 기록한다(T-171).

    **변경을 일으키는 같은 트랜잭션/세션**에서 호출해야 한다(commit은 호출자 책임). 같은
    후보가 다시 실리면 `candidate_id` PK 충돌을 `on_conflict_do_update`로 흡수해 마지막
    사유가 이긴다(자가 dedup). sync는 멱등이라 경계 중복은 안전하다.

    이 outbox에 실린 후보만 공급 GET(`sync_dirty`)이 동기화하므로, export payload를 바꾸는
    mutation 지점에서 반드시 호출해야 즉시 반영된다. 놓친 지점은 안전망(전량
    `sync_feature_exports`)이 최대 1시간 내 보정한다.
    """
    ids = [int(cid) for cid in candidate_ids if cid is not None]
    if not ids:
        return
    now = marked_at or utcnow()
    values = [
        {"candidate_id": cid, "reason": reason, "marked_at": now}
        for cid in dict.fromkeys(ids)  # 세션 내 중복 id를 먼저 제거(같은 값 재삽입 방지)
    ]
    stmt = pg_insert(ExportDirtyOutbox).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[ExportDirtyOutbox.candidate_id],
        set_={"reason": stmt.excluded.reason, "marked_at": stmt.excluded.marked_at},
    )
    await session.execute(stmt)


async def mark_place_candidates_dirty(
    session: AsyncSession, place_id: int | None, reason: str
) -> None:
    """`place_id`에 매칭된(soft delete 안 된) **모든** 후보를 dirty outbox에 표시한다(T-171).

    한 확정 장소에는 여러 후보가 co-매칭될 수 있고, export payload의 place_block은 그 장소
    필드에서 만들어진다. 따라서 장소의 payload 관련 필드(이름·설명·주소·카테고리·좌표 등)를
    바꾸는 mutation은 현재 후보만이 아니라 **그 장소에 매칭된 후보 전부**를 dirty로 표시해야
    dirty sync 결과가 전량 sync와 같아진다(golden 불변식). 그렇지 않으면 co-매칭 후보의
    export가 안전망 reconcile 전까지 stale해진다. 변경이 실제로 있을 때만 호출하는 것은
    호출자 책임이다(불필요 churn 방지). 같은 트랜잭션에서 호출하고 commit은 호출자 몫이다.
    """
    if place_id is None:
        return
    ids = (
        await session.execute(
            select(ExtractedPlaceCandidate.id).where(
                ExtractedPlaceCandidate.matched_place_id == place_id,
                ExtractedPlaceCandidate.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    await mark_candidates_dirty(session, list(ids), reason)


async def mark_video_candidates_dirty(
    session: AsyncSession, video_id: str | None, reason: str
) -> None:
    """영상 export 필드를 공유하는 모든 활성 후보를 dirty로 표시한다.

    `video_summary` 같은 영상 단위 필드는 같은 영상에서 나온 export 후보 모두의 payload에
    복제된다. 한 분석 run이 일부 후보 상태만 바꾸더라도 영상 요약 자체가 달라졌다면 해당
    영상의 활성 후보 전부를 같은 transaction에서 다시 발행해야 golden 불변식이 유지된다.
    """
    if not video_id:
        return
    ids = (
        await session.execute(
            select(ExtractedPlaceCandidate.id).where(
                ExtractedPlaceCandidate.video_id == video_id,
                ExtractedPlaceCandidate.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    await mark_candidates_dirty(session, list(ids), reason)


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
    # 호출자가 lifecycle lock을 썼다면 그 lock이 항상 먼저다. sync와 같은 export
    # lock 아래에서 ledger 존재 여부를 읽어 늦은 upsert와 직렬화한다.
    await acquire_feature_export_lock(session)
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


async def _sync_scope(
    session: AsyncSession, *, candidate_ids: set[int] | None
) -> int:
    """후보 테이블로부터 `feature_exports` ledger를 멱등 동기화한다(commit 없음).

    `candidate_ids`가 None이면 전량(안전망 reconciliation), 아니면 그 후보와 그 후보의
    ledger 행만 동기화(dirty consume 경로). 두 경로가 **같은 per-candidate 분류·upsert·
    후보 소멸(tombstone) 로직**을 공유하므로, dirty 범위가 변경된 후보를 모두 포함하는 한
    dirty sync 결과는 전량 sync 결과와 동일하다(golden 동일성). payload가 바뀐 export에만
    새 sequence를 부여한다. 변경 건수를 반환한다.

    soft delete된 후보(`deleted_at IS NOT NULL`)는 스캔에서 제외한다(T-160). 이들의
    ledger 행은 아래 '후보 소멸' 루프에서 tombstone으로 잡히므로, 삭제 트랜잭션의
    `tombstone_candidate_exports`가 어떤 이유로 누락돼도 다음 sync가 복구하는
    이중 안전망이 된다.
    """
    cand_stmt = select(ExtractedPlaceCandidate).where(
        ExtractedPlaceCandidate.deleted_at.is_(None)
    )
    if candidate_ids is not None:
        cand_stmt = cand_stmt.where(ExtractedPlaceCandidate.id.in_(candidate_ids))
    candidates = list((await session.execute(cand_stmt)).scalars().all())
    videos, channels, playlists, places = await _load_related(session, candidates)

    row_stmt = select(FeatureExport)
    if candidate_ids is not None:
        row_stmt = row_stmt.where(FeatureExport.candidate_id.in_(candidate_ids))
    existing_rows = list((await session.execute(row_stmt)).scalars().all())
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

    return changed


async def sync_feature_exports(session: AsyncSession, *, commit: bool = True) -> int:
    """전 후보를 스캔해 ledger를 멱등 동기화하는 **안전망(reconciliation)** 전량 sync.

    비용은 O(후보 수)라 공급 GET 경로에서는 쓰지 않는다(그 경로는 `sync_dirty`). 프로세스
    시작 시 1회 + scheduler 시간당 1회 실행해, dirty outbox 배선을 놓친 mutation을 최대
    1시간 내 자가 치유한다(T-171). 변경 건수를 반환한다.
    """
    # 모든 ledger writer가 이 lock을 먼저 잡는다. tombstone 경로가 먼저면 최신 후보
    # 상태를 읽고, sync가 먼저면 뒤따르는 tombstone이 같은 임계구간에서 회수한다.
    await acquire_feature_export_lock(session)
    changed = await _sync_scope(session, candidate_ids=None)
    if commit:
        await session.commit()
    return changed


async def sync_dirty(session: AsyncSession, *, commit: bool = True) -> int:
    """durable dirty outbox에 실린 후보만 ledger에 동기화하고 처리한 outbox 행을 consume한다.

    공급 GET(`get_snapshot`/`get_changes`)의 동기화 경로다. 비용이 후보 수가 아니라 최근
    변경 수(O(dirty))에 비례해, 소비자가 폴링해도 서버 부하가 후보 수에 비례하지 않는다
    (S6/A2 해소). outbox가 비어 있으면 아무 것도 쓰지 않고 0을 반환한다(순수 읽기 GET).

    outbox가 비었으면 먼저 가벼운 존재 확인(SELECT)만 하고 어떤 쓰기 statement도 내지 않아
    GET을 순수 읽기로 둔다. 행이 있으면 DELETE ... RETURNING으로 **원자적으로 claim**한 뒤
    그 후보만 동기화한다. 같은 트랜잭션이라 실패 시 claim이 롤백돼 outbox 행이 보존되고,
    존재 확인 이후 커밋된 새 변경은 outbox에 남아 다음 GET이 처리한다(유실 없음). 변경
    건수를 반환한다.
    """
    # outbox DELETE/UPSERT와 candidate snapshot을 export lock 뒤로 일원화한다. claim을
    # 먼저 하고 lock을 기다리면, lock을 가진 writer의 outbox UPSERT와 교착할 수 있다.
    await acquire_feature_export_lock(session)
    has_dirty = await session.scalar(select(ExportDirtyOutbox.candidate_id).limit(1))
    if has_dirty is None:
        if commit:
            await session.commit()
        return 0
    claimed = (
        await session.execute(
            delete(ExportDirtyOutbox).returning(ExportDirtyOutbox.candidate_id)
        )
    ).scalars().all()
    dirty_ids = {int(cid) for cid in claimed}
    if not dirty_ids:
        if commit:
            await session.commit()
        return 0
    changed = await _sync_scope(session, candidate_ids=dirty_ids)
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

    # 순수 읽기(T-171): 예전에는 노출 진단용 `last_exported_at`를 매 GET write-commit 했으나,
    # 그 컬럼을 읽는 소비처가 없어(진단 전용) GET을 상시 쓰기로 만들 뿐이었다. 컬럼은 유지하되
    # 갱신은 제거해 GET을 순수 읽기로 둔다(동기화 쓰기는 `sync_dirty`가 dirty 있을 때만 수행).
    if rows:
        next_cursor: str | None = _encode_cursor(rows[-1].sequence)
    else:
        # 변경이 없으면 입력 cursor를 그대로 유지해 다음 polling이 재스캔하지 않게 한다.
        next_cursor = cursor or None

    # get_snapshot/get_changes가 먼저 수행한 sync(commit=False)까지 page read와 같은
    # transaction으로 확정한다. 특히 snapshot에는 노출되지 않는 reject/tombstone만
    # 새로 생긴 경우 rows가 비어도 commit하지 않으면 session close에서 ledger와
    # sequence가 rollback되어 다음 요청 cursor 계약이 깨진다.
    await session.commit()

    return FeatureExportPage(items=items, next_cursor=next_cursor, has_more=has_more)


async def get_snapshot(
    session: AsyncSession,
    *,
    cursor: str | None = None,
    limit: int = FEATURE_EXPORT_LIMIT_DEFAULT,
) -> FeatureExportPage:
    """현재 활성(`upsert`) feature를 full snapshot으로 노출한다."""
    # sync와 page read를 한 transaction에 묶어 tombstone과 경합한 요청이 오래된
    # upsert snapshot을 응답한 뒤 제거 marker보다 늦게 관측되는 순서 역전을 막는다.
    await sync_dirty(session, commit=False)
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
    await sync_dirty(session, commit=False)
    return await _read_page(
        session, cursor=cursor, limit=limit, only_active=False
    )
