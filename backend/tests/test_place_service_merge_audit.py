"""병합 제안·auto-match audit 서비스 테스트 (T-167, 로드맵 PR-14 개정판, D6·G9)."""

from __future__ import annotations

import pytest

from ktc.models import (
    AuditStatus,
    ExtractedPlaceCandidate,
    FeatureExportStatus,
    MatchStatus,
    TravelPlace,
    YoutubeVideo,
)
from ktc.services import place_service


async def _place(session, name, lat, lng):
    place = TravelPlace(name=name, latitude=lat, longitude=lng, is_geocoded=True)
    session.add(place)
    await session.commit()
    await session.refresh(place)
    return place


async def _matched_candidate(session, *, audit_status=None, video_id="v1"):
    session.add(YoutubeVideo(video_id=video_id, title="t", url="u", channel_id="c"))
    await session.commit()
    place = await _place(session, "성심당", 36.3271, 127.4270)
    candidate = ExtractedPlaceCandidate(
        video_id=video_id,
        source_text="s",
        ai_place_name="성심당",
        match_status=MatchStatus.MATCHED,
        matched_place_id=place.place_id,
        feature_export_status=FeatureExportStatus.READY.value,
        reviewed_by="system",
        audit_status=audit_status,
    )
    session.add(candidate)
    await session.commit()
    await session.refresh(candidate)
    return candidate


# --- 병합 제안 (자동 병합 금지, 제안만) ---


async def test_merge_suggestions_returns_near_similar_names(session):
    base = await _place(session, "성심당", 36.3271, 127.4270)
    # 근접(~십수 m) + 정규화 이름 일치("성심당 본점") → 제안.
    near = await _place(session, "성심당 본점", 36.3272, 127.4271)
    # 근접하지만 무관한 이름 → 제안 아님.
    other = await _place(session, "완전 다른 곳", 36.3272, 127.4270)
    # 이름 같지만 멀리(수 km) → 제안 아님.
    far = await _place(session, "성심당", 36.5000, 127.5000)

    suggestions = await place_service.merge_suggestions_for_place(
        session, place_id=base.place_id
    )
    ids = {s.place.place_id for s in suggestions}
    assert near.place_id in ids
    assert other.place_id not in ids
    assert far.place_id not in ids
    # 제안일 뿐 자동으로 상태를 바꾸지 않는다.
    assert (await session.get(TravelPlace, near.place_id)) is not None
    assert (await session.get(TravelPlace, base.place_id)).name == "성심당"


async def test_merge_suggestions_missing_place_raises(session):
    with pytest.raises(ValueError):
        await place_service.merge_suggestions_for_place(session, place_id=999_999)


# --- auto-match audit 표본 ---


async def test_record_audit_result_keeps_matched_and_export(session):
    candidate = await _matched_candidate(
        session, audit_status=AuditStatus.PENDING.value
    )
    updated = await place_service.record_audit_result(
        session,
        candidate_id=candidate.id,
        accurate=False,
        reviewed_by="tester",
        note="틀림",
    )
    assert updated.audit_status == AuditStatus.MISCONFIRMED.value
    assert updated.audit_reviewed_by == "tester"
    assert updated.audit_reviewed_at is not None
    assert updated.audit_note == "틀림"
    # 사후 관측 — 자동확정·export 상태는 유지된다(노출 차단 아님).
    assert updated.match_status == MatchStatus.MATCHED
    assert updated.feature_export_status == FeatureExportStatus.READY


async def test_record_audit_result_rejects_non_sample(session):
    candidate = await _matched_candidate(session, audit_status=None)
    with pytest.raises(place_service.AuditNotSampledError):
        await place_service.record_audit_result(
            session, candidate_id=candidate.id, accurate=True, reviewed_by="tester"
        )


async def test_audit_summary_computes_misconfirmation_rate(session):
    await _matched_candidate(session, audit_status=AuditStatus.PENDING.value, video_id="v1")
    await _matched_candidate(session, audit_status=AuditStatus.ACCURATE.value, video_id="v2")
    await _matched_candidate(session, audit_status=AuditStatus.ACCURATE.value, video_id="v3")
    await _matched_candidate(
        session, audit_status=AuditStatus.MISCONFIRMED.value, video_id="v4"
    )
    summary = await place_service.audit_summary(session)
    assert summary["sampled"] == 4
    assert summary["pending"] == 1
    assert summary["reviewed"] == 3
    assert summary["accurate"] == 2
    assert summary["misconfirmed"] == 1
    # 오확정률 = misconfirmed / reviewed = 1/3.
    assert summary["misconfirmation_rate"] == pytest.approx(1 / 3)


async def test_audit_summary_none_rate_when_no_reviews(session):
    await _matched_candidate(session, audit_status=AuditStatus.PENDING.value)
    summary = await place_service.audit_summary(session)
    assert summary["reviewed"] == 0
    # 검토 표본이 없으면 None(표본 0을 정밀도 100%로 오도하지 않는다).
    assert summary["misconfirmation_rate"] is None


async def test_list_audit_samples_orders_pending_first_and_filters(session):
    accurate = await _matched_candidate(
        session, audit_status=AuditStatus.ACCURATE.value, video_id="v1"
    )
    pending = await _matched_candidate(
        session, audit_status=AuditStatus.PENDING.value, video_id="v2"
    )
    items = await place_service.list_audit_samples(session)
    assert [item.candidate.id for item in items][0] == pending.id  # 미검토 우선
    assert {item.candidate.id for item in items} == {accurate.id, pending.id}
    # status 필터.
    only_pending = await place_service.list_audit_samples(session, status="pending")
    assert {item.candidate.audit_status for item in only_pending} == {"pending"}
    assert only_pending[0].place_name == "성심당"
