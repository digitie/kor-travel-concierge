"""T-185 검수 후보 일괄 preview/execute 계약 테스트."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from ktc.core.database import get_session
from ktc.core.security import require_admin_proxy
from ktc.models import (
    AuditLog,
    ExportDirtyOutbox,
    ExtractedPlaceCandidate,
    FeatureExport,
    FeatureExportOperation,
    MatchStatus,
    ReviewBulkItemStatus,
    ReviewBulkOperation,
    ReviewBulkOperationItem,
    ReviewBulkOperationReceipt,
    ReviewBulkOperationStatus,
    YoutubeChannel,
    YoutubePlaylist,
    YoutubeVideo,
)
from ktc.models.feature_export import feature_export_sequence
from ktc.services import place_service
from main import app


def test_bulk_confirmation_digest_is_timezone_representation_independent():
    operation_id = uuid4()
    expires_at = datetime(2026, 7, 14, 3, 4, 5, 678901, tzinfo=timezone.utc)
    common = {
        "operation_id": operation_id,
        "actor": "reviewer-a",
        "action": "ignore",
        "scope_fingerprint": "a" * 64,
    }

    utc_digest = place_service._review_bulk_confirmation_digest(
        "rbulk1.test.token",
        expires_at=expires_at,
        **common,
    )
    seoul_digest = place_service._review_bulk_confirmation_digest(
        "rbulk1.test.token",
        expires_at=expires_at.astimezone(timezone(timedelta(hours=9))),
        **common,
    )
    assert seoul_digest == utc_digest


async def _seed_candidates(
    session,
    *,
    prefix: str,
    states: list[MatchStatus],
    domestic: list[bool | None] | None = None,
) -> list[int]:
    videos: list[YoutubeVideo] = []
    for index in range(len(states)):
        video_id = f"t185-{hashlib.sha256(prefix.encode()).hexdigest()[:20]}-{index}"
        videos.append(
            YoutubeVideo(
                video_id=video_id,
                title=f"{prefix} 영상 {index}",
                url="https://example.test/video",
                channel_id=f"{prefix}-channel",
            )
        )
    session.add_all(videos)
    # 관계 속성을 사용하지 않는 직접 FK 시드이므로 영상 행을 먼저 확정한다.
    await session.flush()

    candidates: list[ExtractedPlaceCandidate] = []
    for index, state in enumerate(states):
        video_id = videos[index].video_id
        candidate = ExtractedPlaceCandidate(
            video_id=video_id,
            source_text=f"{prefix} 근거 {index}",
            ai_place_name=f"{prefix} 장소 {index}",
            match_status=state,
            is_domestic=(domestic[index] if domestic is not None else True),
        )
        session.add(candidate)
        candidates.append(candidate)
    await session.commit()
    return [candidate.id for candidate in candidates]


async def test_bulk_preview_selection_is_exact_and_token_is_hash_only(session):
    ids = await _seed_candidates(
        session,
        prefix="bulk-preview-selection",
        states=[MatchStatus.NEEDS_REVIEW, MatchStatus.NEEDS_REVIEW],
    )

    result = await place_service.preview_review_bulk_operation(
        session,
        action="ignore",
        actor="reviewer-a",
        candidate_ids=list(reversed(ids)),
    )

    operation = await session.get(ReviewBulkOperation, result.operation_id)
    assert operation is not None
    assert operation.scope_json == {
        "kind": "selection",
        "candidate_ids": sorted(ids),
    }
    assert operation.total_count == 2
    assert operation.confirmation_token_hash != result.confirmation_token
    assert result.confirmation_token not in operation.confirmation_token_hash
    items = list(
        (
            await session.execute(
                select(ReviewBulkOperationItem)
                .where(
                    ReviewBulkOperationItem.operation_id == result.operation_id
                )
                .order_by(ReviewBulkOperationItem.candidate_id)
            )
        ).scalars()
    )
    assert [item.candidate_id for item in items] == sorted(ids)
    assert all(item.snapshot_revision == 1 for item in items)
    assert all(item.status == ReviewBulkItemStatus.PENDING.value for item in items)


async def test_bulk_preview_rejects_duplicates_missing_ids_and_selection_cap(session):
    ids = await _seed_candidates(
        session,
        prefix="bulk-preview-invalid",
        states=[MatchStatus.NEEDS_REVIEW],
    )
    with pytest.raises(place_service.ReviewBulkValidationError, match="중복"):
        await place_service.preview_review_bulk_operation(
            session,
            action="ignore",
            actor="reviewer-a",
            candidate_ids=[ids[0], ids[0]],
        )
    await session.rollback()
    with pytest.raises(place_service.ReviewBulkValidationError, match="존재하지"):
        await place_service.preview_review_bulk_operation(
            session,
            action="ignore",
            actor="reviewer-a",
            candidate_ids=[2_147_483_647],
        )
    await session.rollback()
    with pytest.raises(place_service.ReviewBulkValidationError, match="1~500"):
        await place_service.preview_review_bulk_operation(
            session,
            action="ignore",
            actor="reviewer-a",
            candidate_ids=list(range(1, 502)),
        )


async def test_bulk_preview_accepts_exact_selection_cap(session):
    ids = await _seed_candidates(
        session,
        prefix="bulk-cap500",
        states=[MatchStatus.NEEDS_REVIEW] * 500,
    )

    preview = await place_service.preview_review_bulk_operation(
        session,
        action="ignore",
        actor="reviewer-a",
        candidate_ids=list(reversed(ids)),
    )

    assert preview.total == 500
    item_count = int(
        await session.scalar(
            select(func.count())
            .select_from(ReviewBulkOperationItem)
            .where(ReviewBulkOperationItem.operation_id == preview.operation_id)
        )
        or 0
    )
    assert item_count == 500


async def test_bulk_empty_filter_preview_executes_zero_item_receipt(session):
    preview = await place_service.preview_review_bulk_operation(
        session,
        action="ignore",
        actor="reviewer-a",
        filter_values={"status": "needs_review"},
    )

    assert preview.total == 0
    item_count = int(
        await session.scalar(
            select(func.count())
            .select_from(ReviewBulkOperationItem)
            .where(ReviewBulkOperationItem.operation_id == preview.operation_id)
        )
        or 0
    )
    assert item_count == 0

    request_id = uuid4()
    response = await place_service.execute_review_bulk_operation(
        session,
        operation_id=preview.operation_id,
        confirmation_token=preview.confirmation_token,
        actor="reviewer-a",
        request_id=request_id,
        cursor=None,
    )

    assert response == {
        "operation_id": str(preview.operation_id),
        "request_id": str(request_id),
        "processed": 0,
        "succeeded": 0,
        "conflicts": [],
        "failed": [],
        "remaining": 0,
        "next_cursor": None,
        "complete": True,
    }
    operation = await session.get(ReviewBulkOperation, preview.operation_id)
    assert operation is not None
    assert operation.status == "completed"
    assert operation.started_at is not None
    assert operation.finished_at is not None
    assert operation.finished_at >= operation.started_at
    receipt = await session.get(
        ReviewBulkOperationReceipt,
        (preview.operation_id, request_id),
    )
    assert receipt is not None and receipt.response_json == response
    chunk_log = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.action == "candidate.bulk_chunk",
                AuditLog.target_id == str(preview.operation_id),
            )
        )
    ).scalar_one()
    assert json.loads(chunk_log.payload_json)["attempted"] == 0


async def test_bulk_filter_foreign_uses_domestic_false_and_never_truncates(
    session,
    monkeypatch,
):
    ids = await _seed_candidates(
        session,
        prefix="bulk-filter-domestic",
        states=[
            MatchStatus.NEEDS_REVIEW,
            MatchStatus.NEEDS_REVIEW,
            MatchStatus.NEEDS_REVIEW,
        ],
        domestic=[False, None, True],
    )
    result = await place_service.preview_review_bulk_operation(
        session,
        action="ignore",
        actor="reviewer-a",
        filter_values={"is_domestic": False, "status": "needs_review"},
    )
    item_ids = list(
        (
            await session.execute(
                select(ReviewBulkOperationItem.candidate_id).where(
                    ReviewBulkOperationItem.operation_id == result.operation_id
                )
            )
        ).scalars()
    )
    assert item_ids == [ids[0]]

    with pytest.raises(
        place_service.ReviewBulkValidationError,
        match="is_domestic=false",
    ):
        await place_service.preview_review_bulk_operation(
            session,
            action="ignore",
            actor="reviewer-a",
            filter_values={"reason": "foreign", "is_domestic": None},
        )
    await session.rollback()

    monkeypatch.setattr(place_service, "REVIEW_BULK_FILTER_LIMIT", 3)
    accepted_at_cap = await place_service.preview_review_bulk_operation(
        session,
        action="ignore",
        actor="reviewer-a",
        filter_values={"status": "needs_review"},
    )
    assert accepted_at_cap.total == 3
    accepted_ids = set(
        (
            await session.execute(
                select(ReviewBulkOperationItem.candidate_id).where(
                    ReviewBulkOperationItem.operation_id
                    == accepted_at_cap.operation_id
                )
            )
        ).scalars()
    )
    assert accepted_ids == set(ids)

    monkeypatch.setattr(place_service, "REVIEW_BULK_FILTER_LIMIT", 2)
    with pytest.raises(place_service.ReviewBulkLimitExceededError, match="초과"):
        await place_service.preview_review_bulk_operation(
            session,
            action="ignore",
            actor="reviewer-a",
            filter_values={"status": "needs_review"},
        )
    await session.rollback()
    operation_count = int(
        await session.scalar(select(func.count()).select_from(ReviewBulkOperation)) or 0
    )
    assert operation_count == 2


@pytest.mark.parametrize(
    ("filter_name", "canonical_value"),
    [
        ("channel_id", "bulk-filter-channel"),
        ("playlist_id", "bulk-filter-playlist"),
        ("keyword", "bulk-filter-keyword"),
    ],
)
async def test_list_and_bulk_source_filters_share_trimmed_membership(
    session,
    filter_name,
    canonical_value,
):
    prefix = f"normalize-{filter_name}"
    ids = await _seed_candidates(
        session,
        prefix=prefix,
        states=[MatchStatus.NEEDS_REVIEW, MatchStatus.NEEDS_REVIEW],
    )
    target = await session.get(ExtractedPlaceCandidate, ids[0])
    assert target is not None
    if filter_name == "channel_id":
        session.add(
            YoutubeChannel(channel_id=canonical_value, title="정규화 대상 채널")
        )
        await session.flush()
        target.source_channel_id = canonical_value
    elif filter_name == "playlist_id":
        session.add(
            YoutubePlaylist(
                playlist_id=canonical_value,
                channel_id=f"{prefix}-channel",
                title="정규화 대상 재생목록",
            )
        )
        await session.flush()
        target.source_playlist_id = canonical_value
    else:
        video = await session.get(YoutubeVideo, target.video_id)
        assert video is not None
        video.source_search_query = canonical_value
    await session.commit()

    padded_value = f"  {canonical_value}  "
    page = await place_service.list_unmatched_candidates_page(
        session,
        **{filter_name: padded_value},
    )
    assert [item.candidate.id for item in page.items] == [ids[0]]
    await session.rollback()
    preview = await place_service.preview_review_bulk_operation(
        session,
        action="ignore",
        actor="reviewer-a",
        filter_values={filter_name: padded_value},
    )
    preview_ids = list(
        (
            await session.execute(
                select(ReviewBulkOperationItem.candidate_id).where(
                    ReviewBulkOperationItem.operation_id == preview.operation_id
                )
            )
        ).scalars()
    )
    assert preview_ids == [ids[0]]
    await session.rollback()

    blank_page = await place_service.list_unmatched_candidates_page(
        session,
        **{filter_name: "   "},
    )
    assert {item.candidate.id for item in blank_page.items} == set(ids)
    await session.rollback()
    blank_preview = await place_service.preview_review_bulk_operation(
        session,
        action="ignore",
        actor="reviewer-a",
        filter_values={filter_name: "   "},
    )
    blank_preview_ids = set(
        (
            await session.execute(
                select(ReviewBulkOperationItem.candidate_id).where(
                    ReviewBulkOperationItem.operation_id
                    == blank_preview.operation_id
                )
            )
        ).scalars()
    )
    assert blank_preview_ids == set(ids)


async def test_bulk_execute_is_chunked_and_same_request_replays_exact_receipt(
    session,
    monkeypatch,
):
    ids = await _seed_candidates(
        session,
        prefix="bulk-chunks",
        states=[
            MatchStatus.NEEDS_REVIEW,
            MatchStatus.NEEDS_REVIEW,
            MatchStatus.NEEDS_REVIEW,
        ],
    )
    preview = await place_service.preview_review_bulk_operation(
        session,
        action="ignore",
        actor="reviewer-a",
        candidate_ids=ids,
    )
    monkeypatch.setattr(place_service, "REVIEW_BULK_CHUNK_SIZE", 2)
    first_request_id = uuid4()
    first = await place_service.execute_review_bulk_operation(
        session,
        operation_id=preview.operation_id,
        confirmation_token=preview.confirmation_token,
        actor="reviewer-a",
        request_id=first_request_id,
        cursor=None,
    )
    assert first["processed"] == 2
    assert first["succeeded"] == 2
    assert first["remaining"] == 1
    assert first["next_cursor"] is not None
    assert first["processed"] + first["remaining"] == preview.total

    with pytest.raises(place_service.ReviewBulkCursorConflictError):
        await place_service.execute_review_bulk_operation(
            session,
            operation_id=preview.operation_id,
            confirmation_token=preview.confirmation_token,
            actor="reviewer-a",
            request_id=first_request_id,
            cursor=first["next_cursor"],
        )
    await session.rollback()

    replay = await place_service.execute_review_bulk_operation(
        session,
        operation_id=preview.operation_id,
        confirmation_token=preview.confirmation_token,
        actor="reviewer-a",
        request_id=first_request_id,
        cursor=None,
    )
    assert replay == first
    assert not session.in_transaction()

    second_request_id = uuid4()
    second = await place_service.execute_review_bulk_operation(
        session,
        operation_id=preview.operation_id,
        confirmation_token=preview.confirmation_token,
        actor="reviewer-a",
        request_id=second_request_id,
        cursor=first["next_cursor"],
    )
    assert second["processed"] == 1
    assert second["succeeded"] == 1
    assert second["remaining"] == 0
    assert second["complete"] is True
    assert first["processed"] + second["processed"] == preview.total

    # 다음 chunk가 끝난 뒤 지연 도착한 과거 request도 단일 latest slot이 아니라
    # receipt ledger에서 같은 응답을 정확히 재생해야 한다.
    delayed_first_replay = await place_service.execute_review_bulk_operation(
        session,
        operation_id=preview.operation_id,
        confirmation_token=preview.confirmation_token,
        actor="reviewer-a",
        request_id=first_request_id,
        cursor=None,
    )
    assert delayed_first_replay == first
    with pytest.raises(place_service.ReviewBulkCursorConflictError):
        await place_service.execute_review_bulk_operation(
            session,
            operation_id=preview.operation_id,
            confirmation_token=preview.confirmation_token,
            actor="reviewer-a",
            request_id=first_request_id,
            cursor=first["next_cursor"],
        )
    await session.rollback()
    receipts = list(
        (
            await session.execute(
                select(ReviewBulkOperationReceipt).where(
                    ReviewBulkOperationReceipt.operation_id
                    == preview.operation_id
                )
            )
        ).scalars()
    )
    assert {receipt.request_id for receipt in receipts} == {
        first_request_id,
        second_request_id,
    }
    current = list(
        (
            await session.execute(
                select(ExtractedPlaceCandidate).where(
                    ExtractedPlaceCandidate.id.in_(ids)
                )
            )
        ).scalars()
    )
    assert {candidate.match_status for candidate in current} == {
        MatchStatus.IGNORED.value
    }
    chunk_logs = list(
        (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.action == "candidate.bulk_chunk",
                    AuditLog.target_id == str(preview.operation_id),
                )
            )
        ).scalars()
    )
    audit_payloads = [json.loads(log.payload_json) for log in chunk_logs]
    assert {
        candidate_id
        for payload in audit_payloads
        for candidate_id in payload["candidate_ids"]
    } == set(ids)
    assert all("token" not in json.dumps(payload) for payload in audit_payloads)
    request_by_candidate_id = {
        candidate_id: payload["request_id"]
        for payload in audit_payloads
        for candidate_id in payload["candidate_ids"]
    }
    resolve_logs = list(
        (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.action == "candidate.resolve",
                    AuditLog.target_id.in_(
                        [str(candidate_id) for candidate_id in ids]
                    ),
                )
            )
        ).scalars()
    )
    assert len(resolve_logs) == len(ids)
    for log in resolve_logs:
        payload = json.loads(log.payload_json)
        candidate_id = int(log.target_id)
        assert log.target_type == "extracted_place_candidate"
        assert payload["bulk_operation_id"] == str(preview.operation_id)
        assert payload["bulk_request_id"] == request_by_candidate_id[candidate_id]
        assert payload["client_operation_id"] == payload["bulk_request_id"]
        assert payload["request"]["action"] == "ignore"
        assert payload["resolution"]["action"] == "ignore"
        assert "confirmation_token" not in json.dumps(payload)


async def test_bulk_started_before_expiry_continues_after_confirmation_ttl(
    session,
    monkeypatch,
):
    ids = await _seed_candidates(
        session,
        prefix="bulk-ttl-running",
        states=[MatchStatus.NEEDS_REVIEW, MatchStatus.NEEDS_REVIEW],
    )
    preview = await place_service.preview_review_bulk_operation(
        session,
        action="ignore",
        actor="reviewer-a",
        candidate_ids=ids,
    )
    monkeypatch.setattr(place_service, "REVIEW_BULK_CHUNK_SIZE", 1)

    first = await place_service.execute_review_bulk_operation(
        session,
        operation_id=preview.operation_id,
        confirmation_token=preview.confirmation_token,
        actor="reviewer-a",
        request_id=uuid4(),
        cursor=None,
    )
    assert first["remaining"] == 1
    assert first["next_cursor"] is not None
    operation = await session.get(ReviewBulkOperation, preview.operation_id)
    assert operation is not None and operation.status == "running"

    after_expiry = preview.expires_at + timedelta(hours=1)
    monkeypatch.setattr(place_service, "utcnow", lambda: after_expiry)
    second = await place_service.execute_review_bulk_operation(
        session,
        operation_id=preview.operation_id,
        confirmation_token=preview.confirmation_token,
        actor="reviewer-a",
        request_id=uuid4(),
        cursor=first["next_cursor"],
    )

    assert second["succeeded"] == 1
    assert second["remaining"] == 0
    assert second["complete"] is True


async def test_bulk_execute_rejects_actor_tamper_expiry_and_stale_candidate(
    session,
    monkeypatch,
):
    ids = await _seed_candidates(
        session,
        prefix="bulk-fences",
        states=[MatchStatus.NEEDS_REVIEW],
    )
    preview = await place_service.preview_review_bulk_operation(
        session,
        action="ignore",
        actor="reviewer-a",
        candidate_ids=ids,
    )
    with pytest.raises(place_service.ReviewBulkOperationNotFoundError):
        await place_service.execute_review_bulk_operation(
            session,
            operation_id=preview.operation_id,
            confirmation_token=preview.confirmation_token,
            actor="reviewer-b",
            request_id=uuid4(),
            cursor=None,
        )
    await session.rollback()
    with pytest.raises(place_service.ReviewBulkTokenError):
        await place_service.execute_review_bulk_operation(
            session,
            operation_id=preview.operation_id,
            confirmation_token=f"{preview.confirmation_token}x",
            actor="reviewer-a",
            request_id=uuid4(),
            cursor=None,
        )
    await session.rollback()

    candidate = await session.get(ExtractedPlaceCandidate, ids[0])
    assert candidate is not None
    candidate.review_note = "preview 이후 변경"
    await session.commit()
    stale = await place_service.execute_review_bulk_operation(
        session,
        operation_id=preview.operation_id,
        confirmation_token=preview.confirmation_token,
        actor="reviewer-a",
        request_id=uuid4(),
        cursor=None,
    )
    assert stale["succeeded"] == 0
    assert stale["conflicts"][0]["code"] == "candidate_revision_conflict"
    assert stale["complete"] is True

    monkeypatch.setattr(
        place_service,
        "REVIEW_BULK_CONFIRMATION_TTL",
        timedelta(seconds=-1),
    )
    expired_ids = await _seed_candidates(
        session,
        prefix="bulk-expired",
        states=[MatchStatus.NEEDS_REVIEW],
    )
    expired = await place_service.preview_review_bulk_operation(
        session,
        action="delete",
        actor="reviewer-a",
        candidate_ids=expired_ids,
    )
    with pytest.raises(place_service.ReviewBulkTokenExpiredError):
        await place_service.execute_review_bulk_operation(
            session,
            operation_id=expired.operation_id,
            confirmation_token=expired.confirmation_token,
            actor="reviewer-a",
            request_id=uuid4(),
            cursor=None,
        )


async def test_bulk_token_is_bound_to_action_and_scope(session):
    ids = await _seed_candidates(
        session,
        prefix="bulk-token-binding",
        states=[MatchStatus.NEEDS_REVIEW, MatchStatus.NEEDS_REVIEW],
    )
    action_preview = await place_service.preview_review_bulk_operation(
        session,
        action="ignore",
        actor="reviewer-a",
        candidate_ids=[ids[0]],
    )
    action_operation = await session.get(
        ReviewBulkOperation,
        action_preview.operation_id,
    )
    assert action_operation is not None
    action_operation.action = "delete"
    await session.commit()
    with pytest.raises(place_service.ReviewBulkTokenError):
        await place_service.execute_review_bulk_operation(
            session,
            operation_id=action_preview.operation_id,
            confirmation_token=action_preview.confirmation_token,
            actor="reviewer-a",
            request_id=uuid4(),
            cursor=None,
        )
    await session.rollback()

    scope_preview = await place_service.preview_review_bulk_operation(
        session,
        action="ignore",
        actor="reviewer-a",
        candidate_ids=[ids[1]],
    )
    scope_operation = await session.get(
        ReviewBulkOperation,
        scope_preview.operation_id,
    )
    assert scope_operation is not None
    scope_operation.scope_json = {
        "kind": "selection",
        "candidate_ids": [ids[0]],
    }
    await session.commit()
    with pytest.raises(place_service.ReviewBulkTokenError):
        await place_service.execute_review_bulk_operation(
            session,
            operation_id=scope_preview.operation_id,
            confirmation_token=scope_preview.confirmation_token,
            actor="reviewer-a",
            request_id=uuid4(),
            cursor=None,
        )


async def test_bulk_delete_and_reopen_preserve_single_candidate_contract(
    session,
    monkeypatch,
):
    lock_events: list[str] = []
    original_lifecycle_lock = place_service.acquire_place_lifecycle_lock
    original_export_lock = (
        place_service.feature_export_service.acquire_feature_export_lock
    )

    async def record_lifecycle_lock(current_session):
        lock_events.append("lifecycle")
        await original_lifecycle_lock(current_session)

    async def record_export_lock(current_session):
        lock_events.append("export")
        await original_export_lock(current_session)

    monkeypatch.setattr(
        place_service,
        "acquire_place_lifecycle_lock",
        record_lifecycle_lock,
    )
    monkeypatch.setattr(
        place_service.feature_export_service,
        "acquire_feature_export_lock",
        record_export_lock,
    )
    delete_ids = await _seed_candidates(
        session,
        prefix="bulk-delete",
        states=[MatchStatus.NEEDS_REVIEW],
    )
    export_sequence = int(
        await session.scalar(select(feature_export_sequence.next_value()))
    )
    session.add(
        FeatureExport(
            export_id=f"ytpc_{delete_ids[0]}",
            sequence=export_sequence,
            candidate_id=delete_ids[0],
            operation=FeatureExportOperation.UPSERT.value,
            export_state="ready",
            payload_json={"candidate_id": delete_ids[0]},
            payload_hash="bulk-delete-seed",
        )
    )
    await session.commit()
    delete_preview = await place_service.preview_review_bulk_operation(
        session,
        action="delete",
        actor="reviewer-a",
        candidate_ids=delete_ids,
    )
    delete_request_id = uuid4()
    deleted = await place_service.execute_review_bulk_operation(
        session,
        operation_id=delete_preview.operation_id,
        confirmation_token=delete_preview.confirmation_token,
        actor="reviewer-a",
        request_id=delete_request_id,
        cursor=None,
    )
    assert deleted["succeeded"] == 1
    assert lock_events[:2] == ["lifecycle", "export"]
    candidate = await session.get(ExtractedPlaceCandidate, delete_ids[0])
    assert candidate is not None and candidate.deleted_at is not None
    delete_export = (
        await session.execute(
            select(FeatureExport).where(
                FeatureExport.candidate_id == delete_ids[0]
            )
        )
    ).scalar_one()
    assert delete_export.operation == FeatureExportOperation.TOMBSTONE.value
    assert delete_export.rejection_reason == "검수 후보 일괄 삭제"
    delete_dirty = await session.get(ExportDirtyOutbox, delete_ids[0])
    assert delete_dirty is not None and delete_dirty.reason == "soft_delete"
    delete_log = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.action == "candidate.delete",
                AuditLog.target_id == str(delete_ids[0]),
            )
        )
    ).scalar_one()
    delete_audit = json.loads(delete_log.payload_json)
    assert delete_log.target_type == "extracted_place_candidate"
    assert delete_audit["client_operation_id"] == str(delete_request_id)
    assert delete_audit["bulk_operation_id"] == str(delete_preview.operation_id)
    assert delete_audit["bulk_request_id"] == str(delete_request_id)
    assert delete_audit["soft_delete"] is True
    assert delete_audit["reason"] == "검수 후보 일괄 삭제"
    assert "confirmation_token" not in json.dumps(delete_audit)
    delete_chunk_log = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.action == "candidate.bulk_chunk",
                AuditLog.target_id == str(delete_preview.operation_id),
            )
        )
    ).scalar_one()
    delete_chunk_audit = json.loads(delete_chunk_log.payload_json)
    assert delete_chunk_audit["request_id"] == str(delete_request_id)
    assert delete_chunk_audit["candidate_ids"] == delete_ids

    reopen_ids = await _seed_candidates(
        session,
        prefix="bulk-reopen",
        states=[MatchStatus.IGNORED],
    )
    reopen_candidate = await session.get(ExtractedPlaceCandidate, reopen_ids[0])
    assert reopen_candidate is not None
    reopen_video = await session.get(YoutubeVideo, reopen_candidate.video_id)
    assert reopen_video is not None
    reopen_video.is_excluded = True
    await session.commit()
    # production의 refactored encoder를 oracle로 다시 호출하지 않고, T-184가 공개한
    # candidate-undo-v1 canonical JSON/base64url 형식을 독립적으로 고정한다.
    legacy_payload = {
        "version": "candidate-undo-v1",
        "candidate_id": reopen_candidate.id,
        "candidate_revision": reopen_candidate.state_revision,
        "prior_state": MatchStatus.IGNORED.value,
        "effective_state": MatchStatus.IGNORED.value,
        "matched_place_id": None,
        "matched_place_revision": None,
    }
    expected_reopen_token = base64.urlsafe_b64encode(
        json.dumps(
            legacy_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).decode("ascii").rstrip("=")
    reopen_preview = await place_service.preview_review_bulk_operation(
        session,
        action="reopen",
        actor="reviewer-a",
        candidate_ids=reopen_ids,
    )
    reopen_item = await session.get(
        ReviewBulkOperationItem,
        (reopen_preview.operation_id, reopen_ids[0]),
    )
    assert reopen_item is not None
    assert reopen_item.reopen_token == expected_reopen_token
    reopen_request_id = uuid4()
    reopened = await place_service.execute_review_bulk_operation(
        session,
        operation_id=reopen_preview.operation_id,
        confirmation_token=reopen_preview.confirmation_token,
        actor="reviewer-a",
        request_id=reopen_request_id,
        cursor=None,
    )
    assert reopened["succeeded"] == 1
    candidate = await session.get(ExtractedPlaceCandidate, reopen_ids[0])
    assert candidate is not None
    assert candidate.match_status == MatchStatus.NEEDS_REVIEW.value
    await session.refresh(reopen_video)
    assert reopen_video.is_excluded is True
    reopen_dirty = await session.get(ExportDirtyOutbox, reopen_ids[0])
    assert reopen_dirty is not None and reopen_dirty.reason == "reopen:ignored"
    reopen_log = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.action == "candidate.reopen",
                AuditLog.target_id == str(reopen_ids[0]),
            )
        )
    ).scalar_one()
    reopen_audit = json.loads(reopen_log.payload_json)
    assert reopen_log.target_type == "extracted_place_candidate"
    assert reopen_audit["bulk_operation_id"] == str(reopen_preview.operation_id)
    assert reopen_audit["bulk_request_id"] == str(reopen_request_id)
    assert reopen_audit["reopened_from"] == MatchStatus.IGNORED.value
    assert reopen_audit["video_is_excluded"] is True
    assert "confirmation_token" not in json.dumps(reopen_audit)
    reopen_chunk_log = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.action == "candidate.bulk_chunk",
                AuditLog.target_id == str(reopen_preview.operation_id),
            )
        )
    ).scalar_one()
    reopen_chunk_audit = json.loads(reopen_chunk_log.payload_json)
    assert reopen_chunk_audit["request_id"] == str(reopen_request_id)
    assert reopen_chunk_audit["candidate_ids"] == reopen_ids


async def test_bulk_item_exception_is_terminal_and_receipt_counts_it(
    session,
    monkeypatch,
):
    ids = await _seed_candidates(
        session,
        prefix="bulk-item-failure",
        states=[MatchStatus.NEEDS_REVIEW],
    )
    preview = await place_service.preview_review_bulk_operation(
        session,
        action="ignore",
        actor="reviewer-a",
        candidate_ids=ids,
    )

    sensitive_exception_text = "sensitive-value-should-never-be-persisted"

    async def fail_item(*_args, **_kwargs):
        raise RuntimeError(sensitive_exception_text)

    monkeypatch.setattr(place_service, "_execute_review_bulk_item", fail_item)
    result = await place_service.execute_review_bulk_operation(
        session,
        operation_id=preview.operation_id,
        confirmation_token=preview.confirmation_token,
        actor="reviewer-a",
        request_id=uuid4(),
        cursor=None,
    )
    assert result["processed"] == 1
    assert result["succeeded"] == 0
    assert len(result["failed"]) == 1
    assert result["remaining"] == 0
    assert result["complete"] is True
    item = await session.get(
        ReviewBulkOperationItem,
        (preview.operation_id, ids[0]),
    )
    assert item is not None
    assert item.status == ReviewBulkItemStatus.FAILED.value
    assert item.error_code == "candidate_bulk_failed"
    assert item.error_message == "candidate_bulk_failed:RuntimeError"
    assert sensitive_exception_text not in item.error_message
    assert sensitive_exception_text not in json.dumps(result)


async def test_bulk_candidate_audit_failure_rolls_back_item_mutation(
    session,
    monkeypatch,
):
    ids = await _seed_candidates(
        session,
        prefix="bulk-candidate-audit-rollback",
        states=[MatchStatus.NEEDS_REVIEW],
    )
    preview = await place_service.preview_review_bulk_operation(
        session,
        action="ignore",
        actor="reviewer-a",
        candidate_ids=ids,
    )
    original_record = place_service.audit_service.record

    async def fail_candidate_audit(session, **kwargs):
        log = await original_record(session, **kwargs)
        if kwargs.get("action") == "candidate.resolve":
            # 실제 INSERT까지 성공한 뒤 실패해도 item savepoint가 후보 전이와
            # 후보 감사행을 함께 되돌리는지 검증한다.
            await session.flush()
            raise RuntimeError("candidate audit unavailable")
        return log

    monkeypatch.setattr(
        place_service.audit_service,
        "record",
        fail_candidate_audit,
    )
    request_id = uuid4()
    result = await place_service.execute_review_bulk_operation(
        session,
        operation_id=preview.operation_id,
        confirmation_token=preview.confirmation_token,
        actor="reviewer-a",
        request_id=request_id,
        cursor=None,
    )

    assert result["succeeded"] == 0
    assert result["failed"] == [
        {
            "candidate_id": ids[0],
            "code": "candidate_bulk_failed",
            "message": "후보 처리 중 오류가 발생해 이 항목을 완료하지 못했습니다.",
        }
    ]
    candidate = await session.get(ExtractedPlaceCandidate, ids[0])
    item = await session.get(
        ReviewBulkOperationItem,
        (preview.operation_id, ids[0]),
    )
    assert candidate is not None
    assert candidate.match_status == MatchStatus.NEEDS_REVIEW.value
    assert item is not None
    assert item.status == ReviewBulkItemStatus.FAILED.value
    assert item.error_message == "candidate_bulk_failed:RuntimeError"
    candidate_logs = list(
        (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.action == "candidate.resolve",
                    AuditLog.target_id == str(ids[0]),
                )
            )
        ).scalars()
    )
    assert candidate_logs == []
    chunk_log = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.action == "candidate.bulk_chunk",
                AuditLog.target_id == str(preview.operation_id),
            )
        )
    ).scalar_one()
    chunk_audit = json.loads(chunk_log.payload_json)
    assert chunk_audit["request_id"] == str(request_id)
    assert chunk_audit["failed_candidate_ids"] == ids


async def test_bulk_item_savepoint_failure_continues_with_next_item(
    session,
    monkeypatch,
):
    ids = sorted(
        await _seed_candidates(
            session,
            prefix="bulk-savepoint-partial",
            states=[MatchStatus.NEEDS_REVIEW, MatchStatus.NEEDS_REVIEW],
        )
    )
    failed_candidate_id, succeeded_candidate_id = ids
    preview = await place_service.preview_review_bulk_operation(
        session,
        action="ignore",
        actor="reviewer-a",
        candidate_ids=ids,
    )
    original_record = place_service.audit_service.record

    async def fail_first_candidate_audit(session, **kwargs):
        log = await original_record(session, **kwargs)
        if (
            kwargs.get("action") == "candidate.resolve"
            and kwargs.get("target_id") == str(failed_candidate_id)
        ):
            # 첫 후보의 mutation·outbox·감사 INSERT가 모두 일어난 뒤 savepoint를
            # 실패시켜도, 다음 후보는 새 savepoint에서 정상 완료돼야 한다.
            await session.flush()
            raise RuntimeError("first candidate audit unavailable")
        return log

    monkeypatch.setattr(
        place_service.audit_service,
        "record",
        fail_first_candidate_audit,
    )
    request_id = uuid4()
    result = await place_service.execute_review_bulk_operation(
        session,
        operation_id=preview.operation_id,
        confirmation_token=preview.confirmation_token,
        actor="reviewer-a",
        request_id=request_id,
        cursor=None,
    )

    assert result == {
        "operation_id": str(preview.operation_id),
        "request_id": str(request_id),
        "processed": 2,
        "succeeded": 1,
        "conflicts": [],
        "failed": [
            {
                "candidate_id": failed_candidate_id,
                "code": "candidate_bulk_failed",
                "message": "후보 처리 중 오류가 발생해 이 항목을 완료하지 못했습니다.",
            }
        ],
        "remaining": 0,
        "next_cursor": None,
        "complete": True,
    }

    failed_candidate = await session.get(
        ExtractedPlaceCandidate,
        failed_candidate_id,
    )
    succeeded_candidate = await session.get(
        ExtractedPlaceCandidate,
        succeeded_candidate_id,
    )
    assert failed_candidate is not None
    assert failed_candidate.match_status == MatchStatus.NEEDS_REVIEW.value
    assert place_service.latest_candidate_resolution(failed_candidate) is None
    assert succeeded_candidate is not None
    assert succeeded_candidate.match_status == MatchStatus.IGNORED.value
    assert (
        place_service.latest_candidate_resolution(succeeded_candidate) or {}
    ).get("client_operation_id") == str(request_id)

    items = list(
        (
            await session.execute(
                select(ReviewBulkOperationItem)
                .where(
                    ReviewBulkOperationItem.operation_id == preview.operation_id
                )
                .order_by(ReviewBulkOperationItem.candidate_id)
            )
        ).scalars()
    )
    assert [item.candidate_id for item in items] == ids
    assert items[0].status == ReviewBulkItemStatus.FAILED.value
    assert items[0].attempt_count == 1
    assert items[0].error_code == "candidate_bulk_failed"
    assert items[0].error_message == "candidate_bulk_failed:RuntimeError"
    assert items[1].status == ReviewBulkItemStatus.SUCCEEDED.value
    assert items[1].attempt_count == 1
    assert items[1].error_code is None
    assert items[1].error_message is None

    operation = await session.get(ReviewBulkOperation, preview.operation_id)
    assert operation is not None
    assert operation.status == ReviewBulkOperationStatus.COMPLETED_WITH_ERRORS.value
    assert operation.total_count == 2
    assert operation.processed_count == 2
    assert operation.succeeded_count == 1
    assert operation.conflict_count == 0
    assert operation.failed_count == 1
    receipt = await session.get(
        ReviewBulkOperationReceipt,
        (preview.operation_id, request_id),
    )
    assert receipt is not None
    assert receipt.request_cursor is None
    assert receipt.response_json == result

    assert await session.get(ExportDirtyOutbox, failed_candidate_id) is None
    succeeded_outbox = await session.get(
        ExportDirtyOutbox,
        succeeded_candidate_id,
    )
    assert succeeded_outbox is not None
    assert succeeded_outbox.reason == "resolve:ignore"

    candidate_logs = list(
        (
            await session.execute(
                select(AuditLog)
                .where(
                    AuditLog.action == "candidate.resolve",
                    AuditLog.target_id.in_(
                        [str(failed_candidate_id), str(succeeded_candidate_id)]
                    ),
                )
                .order_by(AuditLog.id)
            )
        ).scalars()
    )
    assert [log.target_id for log in candidate_logs] == [
        str(succeeded_candidate_id)
    ]
    succeeded_audit = json.loads(candidate_logs[0].payload_json)
    assert succeeded_audit["bulk_operation_id"] == str(preview.operation_id)
    assert succeeded_audit["bulk_request_id"] == str(request_id)

    chunk_log = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.action == "candidate.bulk_chunk",
                AuditLog.target_id == str(preview.operation_id),
            )
        )
    ).scalar_one()
    chunk_audit = json.loads(chunk_log.payload_json)
    assert chunk_audit["attempted"] == 2
    assert chunk_audit["candidate_ids"] == ids
    assert chunk_audit["succeeded"] == 1
    assert chunk_audit["succeeded_candidate_ids"] == [succeeded_candidate_id]
    assert chunk_audit["conflicts"] == 0
    assert chunk_audit["failed"] == 1
    assert chunk_audit["failed_candidate_ids"] == [failed_candidate_id]


async def test_bulk_concurrent_same_request_mutates_once(session_factory):
    async with session_factory() as session:
        ids = await _seed_candidates(
            session,
            prefix="bulk-concurrent",
            states=[MatchStatus.NEEDS_REVIEW],
        )
        preview = await place_service.preview_review_bulk_operation(
            session,
            action="ignore",
            actor="reviewer-a",
            candidate_ids=ids,
        )
    request_id = uuid4()

    async def execute_once():
        async with session_factory() as session:
            return await place_service.execute_review_bulk_operation(
                session,
                operation_id=preview.operation_id,
                confirmation_token=preview.confirmation_token,
                actor="reviewer-a",
                request_id=request_id,
                cursor=None,
            )

    first, second = await asyncio.gather(execute_once(), execute_once())
    assert first == second
    async with session_factory() as session:
        candidate = await session.get(ExtractedPlaceCandidate, ids[0])
        assert candidate is not None
        assert candidate.match_status == MatchStatus.IGNORED.value
        logs = list(
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.action == "candidate.bulk_chunk",
                        AuditLog.target_id == str(preview.operation_id),
                    )
                )
            ).scalars()
        )
        assert len(logs) == 1


async def test_bulk_concurrent_different_request_rejects_consumed_cursor(
    session_factory,
):
    async with session_factory() as session:
        ids = await _seed_candidates(
            session,
            prefix="bulk-concurrent-fenced",
            states=[MatchStatus.NEEDS_REVIEW],
        )
        preview = await place_service.preview_review_bulk_operation(
            session,
            action="ignore",
            actor="reviewer-a",
            candidate_ids=ids,
        )

    async def execute_once(request_id):
        async with session_factory() as session:
            return await place_service.execute_review_bulk_operation(
                session,
                operation_id=preview.operation_id,
                confirmation_token=preview.confirmation_token,
                actor="reviewer-a",
                request_id=request_id,
                cursor=None,
            )

    results = await asyncio.gather(
        execute_once(uuid4()),
        execute_once(uuid4()),
        return_exceptions=True,
    )
    successes = [result for result in results if isinstance(result, dict)]
    conflicts = [
        result
        for result in results
        if isinstance(result, place_service.ReviewBulkCursorConflictError)
    ]
    assert len(successes) == 1
    assert successes[0]["succeeded"] == 1
    assert len(conflicts) == 1

    async with session_factory() as session:
        candidate = await session.get(ExtractedPlaceCandidate, ids[0])
        assert candidate is not None
        assert candidate.match_status == MatchStatus.IGNORED.value
        logs = list(
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.action == "candidate.bulk_chunk",
                        AuditLog.target_id == str(preview.operation_id),
                    )
                )
            ).scalars()
        )
        assert len(logs) == 1


async def test_bulk_chunk_rolls_back_candidate_item_and_audit_together(
    session_factory,
    monkeypatch,
):
    async with session_factory() as session:
        ids = await _seed_candidates(
            session,
            prefix="bulk-audit-rollback",
            states=[MatchStatus.NEEDS_REVIEW],
        )
        preview = await place_service.preview_review_bulk_operation(
            session,
            action="ignore",
            actor="reviewer-a",
            candidate_ids=ids,
        )

    original_record = place_service.audit_service.record

    async def fail_chunk_audit(session, **kwargs):
        await original_record(session, **kwargs)
        if kwargs.get("action") == "candidate.bulk_chunk":
            await session.flush()
            raise RuntimeError("bulk audit unavailable")

    monkeypatch.setattr(place_service.audit_service, "record", fail_chunk_audit)
    request_id = uuid4()
    async with session_factory() as session:
        with pytest.raises(RuntimeError, match="bulk audit unavailable"):
            await place_service.execute_review_bulk_operation(
                session,
                operation_id=preview.operation_id,
                confirmation_token=preview.confirmation_token,
                actor="reviewer-a",
                request_id=request_id,
                cursor=None,
            )
        await session.rollback()

    async with session_factory() as session:
        candidate = await session.get(ExtractedPlaceCandidate, ids[0])
        item = await session.get(
            ReviewBulkOperationItem,
            (preview.operation_id, ids[0]),
        )
        assert candidate is not None
        assert candidate.match_status == MatchStatus.NEEDS_REVIEW.value
        assert item is not None
        assert item.status == ReviewBulkItemStatus.PENDING.value
        assert item.attempt_count == 0
        receipt = await session.get(
            ReviewBulkOperationReceipt,
            (preview.operation_id, request_id),
        )
        assert receipt is None
        chunk_logs = list(
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.action == "candidate.bulk_chunk",
                        AuditLog.target_id == str(preview.operation_id),
                    )
                )
            ).scalars()
        )
        assert chunk_logs == []
        candidate_logs = list(
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.action == "candidate.resolve",
                        AuditLog.target_id == str(ids[0]),
                    )
                )
            ).scalars()
        )
        assert candidate_logs == []


@pytest_asyncio.fixture
async def bulk_api_client(session_factory):
    async def override_get_session():
        async with session_factory() as session:
            yield session

    async def override_admin_actor():
        return "route-reviewer"

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[require_admin_proxy] = override_admin_actor
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def bulk_api_untrusted_client(session_factory):
    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def test_bulk_literal_routes_are_not_captured_by_candidate_id(
    bulk_api_client,
):
    preview = await bulk_api_client.post(
        "/api/v1/destinations/unmatched/bulk/preview",
        json={
            "action": "ignore",
            "scope": {"kind": "selection", "candidate_ids": [2_147_483_647]},
        },
    )
    assert preview.status_code == 400
    assert "존재하지 않는 후보" in preview.json()["detail"]

    execute = await bulk_api_client.post(
        "/api/v1/destinations/unmatched/bulk/execute",
        json={
            "operation_id": str(uuid4()),
            "confirmation_token": "not-a-token",
            "cursor": None,
            "request_id": str(uuid4()),
        },
    )
    assert execute.status_code == 404


@pytest.mark.parametrize(
    "candidate_ids, expected_detail",
    [
        ([], "1~500"),
        ([1, 1], "중복"),
        (list(range(1, 502)), "1~500"),
    ],
)
async def test_bulk_api_selection_domain_errors_are_400(
    bulk_api_client,
    candidate_ids,
    expected_detail,
):
    response = await bulk_api_client.post(
        "/api/v1/destinations/unmatched/bulk/preview",
        json={
            "action": "ignore",
            "scope": {"kind": "selection", "candidate_ids": candidate_ids},
        },
    )
    assert response.status_code == 400
    assert expected_detail in response.json()["detail"]


async def test_bulk_api_preview_and_execute_contract(
    bulk_api_client,
    session_factory,
):
    async with session_factory() as session:
        ids = await _seed_candidates(
            session,
            prefix="bulk-api-contract",
            states=[MatchStatus.NEEDS_REVIEW],
        )
    preview = await bulk_api_client.post(
        "/api/v1/destinations/unmatched/bulk/preview",
        json={
            "action": "ignore",
            "scope": {"kind": "selection", "candidate_ids": ids},
        },
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["total"] == 1
    assert preview_body["chunk_size"] == place_service.REVIEW_BULK_CHUNK_SIZE

    request_id = str(uuid4())
    executed = await bulk_api_client.post(
        "/api/v1/destinations/unmatched/bulk/execute",
        json={
            "operation_id": preview_body["operation_id"],
            "confirmation_token": preview_body["confirmation_token"],
            "cursor": None,
            "request_id": request_id,
        },
    )
    assert executed.status_code == 200
    assert executed.json() == {
        "operation_id": preview_body["operation_id"],
        "request_id": request_id,
        "processed": 1,
        "succeeded": 1,
        "conflicts": [],
        "failed": [],
        "remaining": 0,
        "next_cursor": None,
        "complete": True,
    }


async def test_bulk_route_requires_admin_proxy(bulk_api_untrusted_client):
    response = await bulk_api_untrusted_client.post(
        "/api/v1/destinations/unmatched/bulk/preview",
        json={
            "action": "ignore",
            "scope": {"kind": "selection", "candidate_ids": [1]},
        },
    )
    assert response.status_code == 403
