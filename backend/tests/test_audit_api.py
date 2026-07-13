"""auto-match audit 표본 API의 상태 전이·원자성 회귀 테스트."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from ktc.api import routes
from ktc.core.database import get_repeatable_read_session, get_session
from ktc.models import (
    AuditLog,
    AuditStatus,
    ExtractedPlaceCandidate,
    FeatureExportStatus,
    MatchStatus,
    TravelPlace,
    YoutubeVideo,
)
from main import app


@pytest_asyncio.fixture
async def client(session_factory):
    async def override_get_session():
        async with session_factory() as session:
            yield session

    async def override_repeatable_read_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[
        get_repeatable_read_session
    ] = override_repeatable_read_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _seed_candidate(
    session_factory,
    *,
    video_id: str,
    audit_status: str | None,
    match_status: MatchStatus = MatchStatus.MATCHED,
) -> int:
    async with session_factory() as session:
        session.add(
            YoutubeVideo(
                video_id=video_id,
                title="자동확정 감사 영상",
                url="u",
                channel_id=f"channel-{video_id}",
            )
        )
        await session.commit()
        place_id = None
        if match_status == MatchStatus.MATCHED:
            place = TravelPlace(
                name="자동확정 감사 장소",
                latitude=37.5663,
                longitude=126.9779,
                is_geocoded=True,
            )
            session.add(place)
            await session.commit()
            place_id = place.place_id
        candidate = ExtractedPlaceCandidate(
            video_id=video_id,
            source_text="자동확정 근거",
            ai_place_name="자동확정 감사 장소",
            match_status=match_status,
            matched_place_id=place_id,
            feature_export_status=(
                FeatureExportStatus.READY.value
                if match_status == MatchStatus.MATCHED
                else FeatureExportStatus.PENDING.value
            ),
            reviewed_by="system",
            audit_status=audit_status,
        )
        session.add(candidate)
        await session.commit()
        return candidate.id


async def test_audit_sample_payload_exposes_current_match_status(
    client,
    session_factory,
):
    candidate_id = await _seed_candidate(
        session_factory,
        video_id="audit-history-payload",
        audit_status=AuditStatus.ACCURATE.value,
        # 역사 표본은 이후 reopen될 수 있으므로 현재 상태가 MATCHED라는 보장은 없다.
        match_status=MatchStatus.NEEDS_REVIEW,
    )

    response = await client.get("/api/v1/destinations/audit/samples")

    assert response.status_code == 200
    item = next(
        item
        for item in response.json()["items"]
        if item["candidate_id"] == candidate_id
    )
    assert item["audit_status"] == AuditStatus.ACCURATE.value
    assert item["match_status"] == MatchStatus.NEEDS_REVIEW.value


async def test_audit_result_rejects_non_sample_and_second_decision(
    client,
    session_factory,
):
    non_sample_id = await _seed_candidate(
        session_factory,
        video_id="audit-non-sample",
        audit_status=None,
    )
    pending_id = await _seed_candidate(
        session_factory,
        video_id="audit-single-transition",
        audit_status=AuditStatus.PENDING.value,
    )

    non_sample = await client.post(
        f"/api/v1/destinations/audit/{non_sample_id}",
        json={"accurate": True},
    )
    first = await client.post(
        f"/api/v1/destinations/audit/{pending_id}",
        json={"accurate": True, "note": "첫 판정"},
    )
    second = await client.post(
        f"/api/v1/destinations/audit/{pending_id}",
        json={"accurate": False, "note": "덮어쓰기 시도"},
    )

    assert non_sample.status_code == 409
    assert first.status_code == 200
    assert first.json()["audit_status"] == AuditStatus.ACCURATE.value
    assert second.status_code == 409
    async with session_factory() as session:
        current = await session.get(ExtractedPlaceCandidate, pending_id)
        assert current is not None
        assert current.audit_status == AuditStatus.ACCURATE.value
        assert current.audit_note == "첫 판정"
        logs = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.action == "candidate.audit_result",
                    AuditLog.target_id == str(pending_id),
                )
            )
        ).scalars().all()
        assert len(logs) == 1


async def test_audit_result_rolls_back_candidate_when_audit_write_fails(
    client,
    session_factory,
    monkeypatch,
):
    candidate_id = await _seed_candidate(
        session_factory,
        video_id="audit-atomic-rollback",
        audit_status=AuditStatus.PENDING.value,
    )
    original_record = routes.audit_service.record

    async def fail_after_flush(session, **kwargs):
        await original_record(session, commit=False, **kwargs)
        # 후보 갱신과 감사 INSERT가 DB에 전달된 뒤 장애가 나도 둘 다 rollback돼야 한다.
        await session.flush()
        raise RuntimeError("audit unavailable after flush")

    monkeypatch.setattr(routes.audit_service, "record", fail_after_flush)

    with pytest.raises(RuntimeError, match="audit unavailable after flush"):
        await client.post(
            f"/api/v1/destinations/audit/{candidate_id}",
            json={"accurate": False, "note": "남으면 안 됨"},
        )

    async with session_factory() as session:
        current = await session.get(ExtractedPlaceCandidate, candidate_id)
        assert current is not None
        assert current.audit_status == AuditStatus.PENDING.value
        assert current.audit_reviewed_by is None
        assert current.audit_reviewed_at is None
        assert current.audit_note is None
        logs = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.action == "candidate.audit_result",
                    AuditLog.target_id == str(candidate_id),
                )
            )
        ).scalars().all()
        assert logs == []
