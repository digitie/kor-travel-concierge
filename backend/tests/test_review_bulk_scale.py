"""T-185 검수 후보 701건 일괄 처리의 실제 PostgreSQL 규모 계약 테스트."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, insert, select, update

from ktc.core.database import get_repeatable_read_session, get_session
from ktc.core.security import require_admin_proxy
from ktc.models import (
    AuditLog,
    CrawlStatus,
    EvidenceSourceKind,
    ExtractedPlaceCandidate,
    FeatureExportStatus,
    GroundingStatus,
    MatchStatus,
    ReviewBulkItemStatus,
    ReviewBulkOperation,
    ReviewBulkOperationItem,
    ReviewBulkOperationReceipt,
    ReviewBulkOperationStatus,
    YoutubeChannel,
    YoutubeVideo,
)
from main import app


FOREIGN_CANDIDATE_COUNT = 701
CHUNK_SIZE = 100
ADMIN_ACTOR = "scale-reviewer"
SCALE_SEED_BATCH_SIZE = 1_000


def _candidate_seed_row(
    *,
    ordinal: int,
    is_domestic: bool | None,
    now: datetime,
) -> dict[str, object]:
    return {
        "state_revision": 1,
        "video_id": "bulk-scale-video",
        "source_kind": EvidenceSourceKind.TRANSCRIPT.value,
        "grounding_status": GroundingStatus.LEGACY_UNKNOWN.value,
        "source_text": f"규모 검증 근거 {ordinal}",
        "ai_place_name": f"규모 검증 장소 {ordinal}",
        "match_status": MatchStatus.NEEDS_REVIEW.value,
        "is_domestic": is_domestic,
        "feature_export_status": FeatureExportStatus.PENDING.value,
        "created_at": now,
    }


async def _seed_scale_candidates(
    session_factory,
    *,
    foreign_candidate_count: int = FOREIGN_CANDIDATE_COUNT,
    include_controls: bool = True,
) -> tuple[frozenset[int], dict[bool | None, int]]:
    """세딩 비용을 측정에서 분리하고 Core multirow INSERT를 bounded batch로 넣는다."""
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        await session.execute(
            insert(YoutubeChannel.__table__),
            [
                {
                    "channel_id": "bulk-scale-channel",
                    "title": "규모 검증 채널",
                    "created_at": now,
                }
            ],
        )
        await session.execute(
            insert(YoutubeVideo.__table__),
            [
                {
                    "video_id": "bulk-scale-video",
                    "title": "검수 일괄 처리 규모 검증 영상",
                    "url": "https://example.test/bulk-scale-video",
                    "channel_id": "bulk-scale-channel",
                    "crawl_status": CrawlStatus.DISCOVERED.value,
                    "crawled_at": now,
                    "is_excluded": False,
                }
            ],
        )

        candidate_table = ExtractedPlaceCandidate.__table__
        foreign_ids: set[int] = set()
        for offset in range(0, foreign_candidate_count, SCALE_SEED_BATCH_SIZE):
            batch_end = min(
                offset + SCALE_SEED_BATCH_SIZE,
                foreign_candidate_count,
            )
            foreign_result = await session.execute(
                insert(candidate_table)
                .values(
                    [
                        _candidate_seed_row(
                            ordinal=ordinal,
                            is_domestic=False,
                            now=now,
                        )
                        for ordinal in range(offset, batch_end)
                    ]
                )
                .returning(candidate_table.c.id)
            )
            foreign_ids.update(int(value) for value in foreign_result.scalars())

        control_ids: dict[bool | None, int] = {}
        if include_controls:
            control_result = await session.execute(
                insert(candidate_table)
                .values(
                    [
                        _candidate_seed_row(
                            ordinal=foreign_candidate_count,
                            is_domestic=None,
                            now=now,
                        ),
                        _candidate_seed_row(
                            ordinal=foreign_candidate_count + 1,
                            is_domestic=True,
                            now=now,
                        ),
                    ]
                )
                .returning(candidate_table.c.id, candidate_table.c.is_domestic)
            )
            control_ids = {
                row.is_domestic: int(row.id) for row in control_result.all()
            }
        await session.commit()

    assert len(foreign_ids) == foreign_candidate_count
    if include_controls:
        assert set(control_ids) == {None, True}
    else:
        assert control_ids == {}
    return frozenset(foreign_ids), control_ids


@pytest_asyncio.fixture
async def review_bulk_scale_client(session_factory):
    async def override_get_session():
        async with session_factory() as session:
            yield session

    async def override_repeatable_read_session():
        async with session_factory() as session:
            await session.connection(
                execution_options={"isolation_level": "REPEATABLE READ"}
            )
            yield session

    async def override_admin_actor():
        return ADMIN_ACTOR

    dependencies = {
        get_session: override_get_session,
        get_repeatable_read_session: override_repeatable_read_session,
        require_admin_proxy: override_admin_actor,
    }
    app.dependency_overrides.update(dependencies)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            # 701건 실행 성능은 테스트 본문이 별도로 60초를 강제한다. 10,000건
            # preview 경계 테스트는 성능 게이트가 아니므로 느린 n150에서도 transport
            # timeout이 계약 검증보다 먼저 실패하지 않게 여유를 둔다.
            timeout=180.0,
        ) as client:
            yield client
    finally:
        for dependency in dependencies:
            app.dependency_overrides.pop(dependency, None)


async def test_filter_literal_10000_succeeds_and_10001_is_rejected_without_truncation(
    review_bulk_scale_client,
    session_factory,
):
    """실제 상한과 상한+1 membership을 PostgreSQL operation/item 행으로 고정한다."""
    boundary_count = 10_000
    all_ids, controls = await _seed_scale_candidates(
        session_factory,
        foreign_candidate_count=boundary_count + 1,
        include_controls=False,
    )
    assert controls == {}

    # 첫 preview는 literal q로 정확히 10,000건만 고른다. 같은 DB snapshot 집합에서
    # q를 제거한 두 번째 preview는 10,001번째를 확인하고 operation 자체를 만들지
    # 않아야 하므로, 마지막 한 건만 공통 검색어에서 제외한다.
    excluded_id = max(all_ids)
    async with session_factory() as session:
        await session.execute(
            update(ExtractedPlaceCandidate)
            .where(ExtractedPlaceCandidate.id == excluded_id)
            .values(ai_place_name="상한 초과 단독 후보")
        )
        await session.commit()

    accepted_response = await review_bulk_scale_client.post(
        "/api/v1/destinations/unmatched/bulk/preview",
        json={
            "action": "ignore",
            "scope": {
                "kind": "filter",
                "filter": {
                    "q": "규모 검증 장소",
                    "is_domestic": False,
                    "status": "needs_review",
                },
            },
        },
    )
    assert accepted_response.status_code == 200, accepted_response.text
    accepted = accepted_response.json()
    assert accepted["total"] == boundary_count
    accepted_operation_id = UUID(accepted["operation_id"])

    async with session_factory() as session:
        accepted_operation = await session.get(
            ReviewBulkOperation,
            accepted_operation_id,
        )
        assert accepted_operation is not None
        assert accepted_operation.total_count == boundary_count
        accepted_item_count = int(
            await session.scalar(
                select(func.count())
                .select_from(ReviewBulkOperationItem)
                .where(
                    ReviewBulkOperationItem.operation_id == accepted_operation_id
                )
            )
            or 0
        )
        assert accepted_item_count == boundary_count
        accepted_item_ids = set(
            (
                await session.execute(
                    select(ReviewBulkOperationItem.candidate_id).where(
                        ReviewBulkOperationItem.operation_id
                        == accepted_operation_id
                    )
                )
            ).scalars()
        )
        assert accepted_item_ids == all_ids - {excluded_id}

    rejected_response = await review_bulk_scale_client.post(
        "/api/v1/destinations/unmatched/bulk/preview",
        json={
            "action": "ignore",
            "scope": {
                "kind": "filter",
                "filter": {
                    "is_domestic": False,
                    "status": "needs_review",
                },
            },
        },
    )
    assert rejected_response.status_code == 413, rejected_response.text
    assert "10000건을 초과" in rejected_response.json()["detail"]

    async with session_factory() as session:
        operation_count = int(
            await session.scalar(
                select(func.count()).select_from(ReviewBulkOperation)
            )
            or 0
        )
        item_count = int(
            await session.scalar(
                select(func.count()).select_from(ReviewBulkOperationItem)
            )
            or 0
        )
        preview_audit_count = int(
            await session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "candidate.bulk_preview")
            )
            or 0
        )
        assert operation_count == 1
        assert item_count == boundary_count
        assert preview_audit_count == 1


async def test_foreign_filter_processes_701_candidates_with_exact_receipts(
    review_bulk_scale_client,
    session_factory,
):
    foreign_ids, control_ids = await _seed_scale_candidates(session_factory)

    started_at = perf_counter()
    preview_response = await review_bulk_scale_client.post(
        "/api/v1/destinations/unmatched/bulk/preview",
        json={
            "action": "ignore",
            "scope": {
                "kind": "filter",
                "filter": {
                    "is_domestic": False,
                    "status": "needs_review",
                },
            },
        },
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["total"] == FOREIGN_CANDIDATE_COUNT
    assert preview["chunk_size"] == CHUNK_SIZE

    async def execute_chunk(request_id: UUID, cursor: str | None) -> dict[str, Any]:
        response = await review_bulk_scale_client.post(
            "/api/v1/destinations/unmatched/bulk/execute",
            json={
                "operation_id": preview["operation_id"],
                "confirmation_token": preview["confirmation_token"],
                "cursor": cursor,
                "request_id": str(request_id),
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    first_request_id = uuid4()
    first = await execute_chunk(first_request_id, None)
    assert first["processed"] == CHUNK_SIZE
    assert first["succeeded"] == CHUNK_SIZE
    assert first["conflicts"] == []
    assert first["failed"] == []
    assert first["remaining"] == FOREIGN_CANDIDATE_COUNT - CHUNK_SIZE
    assert first["complete"] is False
    assert isinstance(first["next_cursor"], str)

    # 응답 유실 재전송은 같은 request/cursor의 저장 receipt를 그대로 돌려주며,
    # 두 번째 mutation·receipt·audit을 만들지 않아야 한다.
    replay = await execute_chunk(first_request_id, None)
    assert replay == first

    expected_receipts: dict[UUID, tuple[str | None, dict[str, Any]]] = {
        first_request_id: (None, first)
    }
    processed_sizes = [first["processed"]]
    processed_total = first["processed"]
    cursor: str | None = first["next_cursor"]

    # 첫 100건 뒤 남은 601건은 100건 6회와 마지막 1건, 총 7 chunk다.
    for extra_chunk_index in range(7):
        request_id = uuid4()
        request_cursor = cursor
        body = await execute_chunk(request_id, request_cursor)
        expected_processed = CHUNK_SIZE if extra_chunk_index < 6 else 1
        processed_total += expected_processed
        processed_sizes.append(body["processed"])
        assert body["processed"] == expected_processed
        assert body["succeeded"] == expected_processed
        assert body["conflicts"] == []
        assert body["failed"] == []
        assert body["remaining"] == FOREIGN_CANDIDATE_COUNT - processed_total
        assert body["complete"] is (processed_total == FOREIGN_CANDIDATE_COUNT)
        expected_receipts[request_id] = (request_cursor, body)
        cursor = body["next_cursor"]

    elapsed_seconds = perf_counter() - started_at
    assert processed_sizes == [CHUNK_SIZE] * 7 + [1]
    assert processed_total == FOREIGN_CANDIDATE_COUNT
    assert cursor is None
    assert len(expected_receipts) == 8
    assert elapsed_seconds < 60.0, (
        "701건 filter preview·exact replay·8개 실행 chunk가 "
        f"60초를 초과했습니다: {elapsed_seconds:.3f}초"
    )

    operation_id = UUID(preview["operation_id"])
    async with session_factory() as session:
        operation = await session.get(ReviewBulkOperation, operation_id)
        assert operation is not None
        assert operation.actor == ADMIN_ACTOR
        assert operation.action == "ignore"
        assert operation.scope_kind == "filter"
        assert operation.scope_json == {
            "kind": "filter",
            "filter": {
                "channel_id": None,
                "playlist_id": None,
                "keyword": None,
                "q": None,
                "is_domestic": False,
                "status": "needs_review",
                "reason": None,
                "source_kind": None,
                "grounding": None,
            },
        }
        assert operation.status == ReviewBulkOperationStatus.COMPLETED.value
        assert operation.total_count == FOREIGN_CANDIDATE_COUNT
        assert operation.processed_count == FOREIGN_CANDIDATE_COUNT
        assert operation.succeeded_count == FOREIGN_CANDIDATE_COUNT
        assert operation.conflict_count == 0
        assert operation.failed_count == 0
        assert operation.next_cursor is None
        assert operation.started_at is not None
        assert operation.finished_at is not None
        assert operation.confirmation_token_hash != preview["confirmation_token"]
        assert preview["confirmation_token"] not in operation.confirmation_token_hash

        item_rows = (
            await session.execute(
                select(
                    ReviewBulkOperationItem.candidate_id,
                    ReviewBulkOperationItem.snapshot_revision,
                    ReviewBulkOperationItem.snapshot_review_state,
                    ReviewBulkOperationItem.status,
                    ReviewBulkOperationItem.attempt_count,
                    ReviewBulkOperationItem.error_code,
                    ReviewBulkOperationItem.error_message,
                ).where(ReviewBulkOperationItem.operation_id == operation_id)
            )
        ).all()
        assert len(item_rows) == FOREIGN_CANDIDATE_COUNT
        assert {row.candidate_id for row in item_rows} == foreign_ids
        assert all(row.snapshot_revision == 1 for row in item_rows)
        assert all(
            row.snapshot_review_state == MatchStatus.NEEDS_REVIEW.value
            for row in item_rows
        )
        assert all(
            row.status == ReviewBulkItemStatus.SUCCEEDED.value
            for row in item_rows
        )
        assert all(row.attempt_count == 1 for row in item_rows)
        assert all(row.error_code is None for row in item_rows)
        assert all(row.error_message is None for row in item_rows)

        receipts = list(
            (
                await session.execute(
                    select(ReviewBulkOperationReceipt).where(
                        ReviewBulkOperationReceipt.operation_id == operation_id
                    )
                )
            ).scalars()
        )
        assert len(receipts) == 8
        receipt_by_request = {receipt.request_id: receipt for receipt in receipts}
        assert set(receipt_by_request) == set(expected_receipts)
        for request_id, (request_cursor, expected_response) in (
            expected_receipts.items()
        ):
            receipt = receipt_by_request[request_id]
            assert receipt.request_cursor == request_cursor
            assert receipt.response_json == expected_response

        preview_logs = list(
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.action == "candidate.bulk_preview",
                        AuditLog.target_id == str(operation_id),
                    )
                )
            ).scalars()
        )
        assert len(preview_logs) == 1
        preview_audit = json.loads(preview_logs[0].payload_json or "{}")
        assert preview_audit["total"] == FOREIGN_CANDIDATE_COUNT
        assert preview_audit["actor"] == ADMIN_ACTOR
        assert "confirmation_token" not in preview_audit

        chunk_logs = list(
            (
                await session.execute(
                    select(AuditLog)
                    .where(
                        AuditLog.action == "candidate.bulk_chunk",
                        AuditLog.target_id == str(operation_id),
                    )
                    .order_by(AuditLog.id)
                )
            ).scalars()
        )
        assert len(chunk_logs) == 8
        chunk_audits = [
            json.loads(log.payload_json or "{}") for log in chunk_logs
        ]
        assert [audit["attempted"] for audit in chunk_audits] == [
            CHUNK_SIZE
        ] * 7 + [1]
        audited_candidate_ids = [
            candidate_id
            for audit in chunk_audits
            for candidate_id in audit["candidate_ids"]
        ]
        assert len(audited_candidate_ids) == FOREIGN_CANDIDATE_COUNT
        assert len(set(audited_candidate_ids)) == FOREIGN_CANDIDATE_COUNT
        assert set(audited_candidate_ids) == foreign_ids
        assert all(audit["actor"] == ADMIN_ACTOR for audit in chunk_audits)
        assert all("confirmation_token" not in audit for audit in chunk_audits)

        candidate_logs = list(
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.action == "candidate.resolve",
                        AuditLog.target_type == "extracted_place_candidate",
                    )
                )
            ).scalars()
        )
        assert len(candidate_logs) == FOREIGN_CANDIDATE_COUNT
        candidate_ids_by_request: dict[str, set[int]] = {}
        for log in candidate_logs:
            candidate_audit = json.loads(log.payload_json or "{}")
            candidate_id = int(log.target_id or "0")
            request_id = candidate_audit["bulk_request_id"]
            assert candidate_id in foreign_ids
            assert candidate_audit["bulk_operation_id"] == str(operation_id)
            assert candidate_audit["client_operation_id"] == request_id
            assert candidate_audit["request"]["action"] == "ignore"
            assert candidate_audit["resolution"]["action"] == "ignore"
            assert "confirmation_token" not in json.dumps(candidate_audit)
            candidate_ids_by_request.setdefault(request_id, set()).add(
                candidate_id
            )
        assert candidate_ids_by_request == {
            audit["request_id"]: set(audit["candidate_ids"])
            for audit in chunk_audits
        }

        candidate_rows = (
            await session.execute(
                select(
                    ExtractedPlaceCandidate.id,
                    ExtractedPlaceCandidate.is_domestic,
                    ExtractedPlaceCandidate.match_status,
                ).where(
                    ExtractedPlaceCandidate.id.in_(
                        [*foreign_ids, *control_ids.values()]
                    )
                )
            )
        ).all()
        candidate_by_id = {row.id: row for row in candidate_rows}
        assert all(
            candidate_by_id[candidate_id].is_domestic is False
            and candidate_by_id[candidate_id].match_status
            == MatchStatus.IGNORED.value
            for candidate_id in foreign_ids
        )
        assert candidate_by_id[control_ids[None]].is_domestic is None
        assert (
            candidate_by_id[control_ids[None]].match_status
            == MatchStatus.NEEDS_REVIEW.value
        )
        assert candidate_by_id[control_ids[True]].is_domestic is True
        assert (
            candidate_by_id[control_ids[True]].match_status
            == MatchStatus.NEEDS_REVIEW.value
        )

    remaining_response = await review_bulk_scale_client.get(
        "/api/v1/destinations/unmatched",
        params={"status": "needs_review", "limit": 2000},
    )
    assert remaining_response.status_code == 200, remaining_response.text
    remaining = remaining_response.json()
    assert remaining["total"] == 2
    assert {item["id"] for item in remaining["items"]} == set(
        control_ids.values()
    )
    assert {item["is_domestic"] for item in remaining["items"]} == {None, True}

    foreign_remaining_response = await review_bulk_scale_client.get(
        "/api/v1/destinations/unmatched",
        params={
            "status": "needs_review",
            "is_domestic": "false",
            "limit": 2000,
        },
    )
    assert foreign_remaining_response.status_code == 200, (
        foreign_remaining_response.text
    )
    foreign_remaining = foreign_remaining_response.json()
    assert foreign_remaining["total"] == 0
    assert foreign_remaining["items"] == []

    ignored_foreign_response = await review_bulk_scale_client.get(
        "/api/v1/destinations/unmatched",
        params={
            "status": "ignored",
            "is_domestic": "false",
            "limit": 2000,
        },
    )
    assert ignored_foreign_response.status_code == 200, ignored_foreign_response.text
    ignored_foreign = ignored_foreign_response.json()
    assert ignored_foreign["total"] == FOREIGN_CANDIDATE_COUNT
    assert len(ignored_foreign["items"]) == FOREIGN_CANDIDATE_COUNT
    assert {item["id"] for item in ignored_foreign["items"]} == foreign_ids
    assert all(item["is_domestic"] is False for item in ignored_foreign["items"])
