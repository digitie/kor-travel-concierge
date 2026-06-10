"""범용 feature 수집 API(`/api/v1/features/*`)와 export ledger 동기화 테스트.

`get_session` 의존성을 테스트 엔진으로 오버라이드해 ASGI 앱을 직접 호출한다.
(T-066, ADR-26)
"""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import get_session
from main import app


@pytest_asyncio.fixture
async def client(session_factory):
    async def override_get_session():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _seed_ready_candidate(
    session_factory,
    *,
    video_id: str = "vid1",
    place_name: str = "월정리 해변",
    candidate_name: str | None = None,
):
    """확정(`ready`) 후보 1건과 연결 장소/영상/채널을 시드한다."""
    from app.models import (
        ExtractedPlaceCandidate,
        FeatureExportStatus,
        MatchStatus,
        TravelPlace,
        YoutubeChannel,
        YoutubeVideo,
    )

    channel_id = f"chan-{video_id}"
    async with session_factory() as s:
        channel = YoutubeChannel(
            channel_id=channel_id, title="제주 여행 채널", gemini_summary="제주 전문"
        )
        s.add(channel)
        await s.flush()
        video = YoutubeVideo(
            video_id=video_id,
            title="제주 브이로그",
            url=f"https://youtu.be/{video_id}",
            canonical_url=f"https://www.youtube.com/watch?v={video_id}",
            channel_id=channel_id,
            channel_name="제주 여행 채널",
            transcript_summary="월정리 방문",
        )
        place = TravelPlace(
            name=place_name,
            latitude=33.5563,
            longitude=126.7958,
            category="해변",
            official_address="제주특별자치도 제주시 구좌읍 월정리",
            is_geocoded=True,
        )
        s.add_all([video, place])
        await s.commit()
        await s.refresh(place)
        candidate = ExtractedPlaceCandidate(
            video_id=video_id,
            source_channel_id=channel_id,
            source_text="월정리 해변이 정말 예뻐요",
            ai_place_name=candidate_name or place_name,
            timestamp_start="00:03:12",
            timestamp_end="00:04:10",
            confidence_score=0.86,
            candidate_category="해변",
            match_status=MatchStatus.MATCHED,
            matched_place_id=place.place_id,
            feature_export_status=FeatureExportStatus.READY.value,
        )
        s.add(candidate)
        await s.commit()
        await s.refresh(candidate)
        return candidate.id, place.place_id


async def test_snapshot_returns_ready_candidate_as_upsert(client, session_factory):
    candidate_id, _ = await _seed_ready_candidate(session_factory)

    resp = await client.get("/api/v1/features/snapshot")
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_more"] is False
    assert body["next_cursor"] is not None
    assert len(body["items"]) == 1

    item = body["items"][0]
    assert item["export_id"] == f"ytpc_{candidate_id}"
    assert item["operation"] == "upsert"
    assert item["candidate_id"] == candidate_id
    assert item["place"]["name"] == "월정리 해변"
    assert item["place"]["latitude"] == 33.5563
    assert item["place"]["category_label"] == "해변"
    assert item["place"]["category_code_suggestion"] is None
    assert item["place"]["address"]["official_address"].startswith("제주")
    assert item["youtube"]["video_id"] == "vid1"
    assert item["youtube"]["channel_title"] == "제주 여행 채널"
    assert item["youtube"]["video_summary"] == "월정리 방문"
    assert item["evidence"]["timestamp_start"] == "00:03:12"
    assert item["evidence"]["confidence_score"] == 0.86
    assert item["source_record"]["provider"] == "tripmate-agent-youtube"
    assert item["source_record"]["source_entity_id"] == str(candidate_id)
    assert item["source_record"]["raw_payload_hash"].startswith("sha256:")


async def test_snapshot_excludes_pending_candidate(client, session_factory):
    from app.models import ExtractedPlaceCandidate, MatchStatus, YoutubeVideo

    async with session_factory() as s:
        s.add(
            YoutubeVideo(
                video_id="vp", title="t", url="u", channel_id="c", channel_name="c"
            )
        )
        await s.commit()
        s.add(
            ExtractedPlaceCandidate(
                video_id="vp",
                source_text="아직 검수 안 됨",
                ai_place_name="미확정",
                match_status=MatchStatus.NEEDS_REVIEW,
            )
        )
        await s.commit()

    resp = await client.get("/api/v1/features/snapshot")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_changes_is_stable_without_data_change(client, session_factory):
    await _seed_ready_candidate(session_factory)

    first = await client.get("/api/v1/features/changes")
    assert first.status_code == 200
    first_body = first.json()
    assert len(first_body["items"]) == 1
    seq_cursor = first_body["next_cursor"]

    # 변화가 없으면 cursor 이후 신규 항목이 없어야 한다(반복 호출이 churn을 만들지 않는다).
    second = await client.get(f"/api/v1/features/changes?cursor={seq_cursor}")
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["items"] == []
    assert second_body["has_more"] is False


async def test_changes_emits_reject_after_export(client, session_factory):
    from app.models import ExtractedPlaceCandidate, FeatureExportStatus, MatchStatus

    candidate_id, _ = await _seed_ready_candidate(session_factory)

    # 처음 노출(upsert) 후 cursor를 잡는다.
    first = await client.get("/api/v1/features/changes")
    cursor = first.json()["next_cursor"]

    # 후보를 검수에서 제외하면 reject 변경이 cursor 이후로 노출돼야 한다.
    async with session_factory() as s:
        candidate = await s.get(ExtractedPlaceCandidate, candidate_id)
        candidate.match_status = MatchStatus.IGNORED.value
        candidate.feature_export_status = FeatureExportStatus.REJECTED.value
        candidate.review_note = "중복 장소"
        await s.commit()

    changes = await client.get(f"/api/v1/features/changes?cursor={cursor}")
    assert changes.status_code == 200
    items = changes.json()["items"]
    assert len(items) == 1
    assert items[0]["operation"] == "reject"
    assert items[0]["rejection_reason"] == "중복 장소"

    # reject된 후보는 더 이상 snapshot(활성)에 나타나지 않는다.
    snapshot = await client.get("/api/v1/features/snapshot")
    assert snapshot.json()["items"] == []


async def test_snapshot_pagination_with_limit(client, session_factory):
    await _seed_ready_candidate(session_factory, video_id="va", place_name="장소 A")
    await _seed_ready_candidate(session_factory, video_id="vb", place_name="장소 B")
    await _seed_ready_candidate(session_factory, video_id="vc", place_name="장소 C")

    first = await client.get("/api/v1/features/snapshot?limit=2")
    assert first.status_code == 200
    first_body = first.json()
    assert len(first_body["items"]) == 2
    assert first_body["has_more"] is True

    cursor = first_body["next_cursor"]
    second = await client.get(f"/api/v1/features/snapshot?limit=2&cursor={cursor}")
    assert second.status_code == 200
    second_body = second.json()
    assert len(second_body["items"]) == 1
    assert second_body["has_more"] is False

    seen = {item["export_id"] for item in first_body["items"] + second_body["items"]}
    assert len(seen) == 3


async def test_invalid_cursor_returns_400(client, session_factory):
    await _seed_ready_candidate(session_factory)
    resp = await client.get("/api/v1/features/changes?cursor=!!not-base64!!")
    assert resp.status_code == 400


async def test_changes_emits_upsert_on_payload_change(client, session_factory):
    from app.models import TravelPlace

    candidate_id, place_id = await _seed_ready_candidate(session_factory)

    first = await client.get("/api/v1/features/changes")
    cursor = first.json()["next_cursor"]

    # 장소명이 바뀌면 payload_hash가 바뀌어 새 upsert로 다시 노출돼야 한다.
    async with session_factory() as s:
        place = await s.get(TravelPlace, place_id)
        place.name = "월정리 해수욕장"
        await s.commit()

    changes = await client.get(f"/api/v1/features/changes?cursor={cursor}")
    items = changes.json()["items"]
    assert len(items) == 1
    assert items[0]["operation"] == "upsert"
    assert items[0]["place"]["name"] == "월정리 해수욕장"
    assert items[0]["export_id"] == f"ytpc_{candidate_id}"
