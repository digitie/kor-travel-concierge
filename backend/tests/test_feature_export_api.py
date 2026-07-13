"""범용 feature 수집 API(`/api/v1/features/*`)와 export ledger 동기화 테스트.

`get_session` 의존성을 테스트 엔진으로 오버라이드해 ASGI 앱을 직접 호출한다.
(T-066, ADR-26)
"""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from ktc.core.database import get_repeatable_read_session, get_session
from main import app


@pytest_asyncio.fixture
async def client(session_factory):
    async def override_get_session():
        async with session_factory() as s:
            yield s

    async def override_repeatable_read_session():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[
        get_repeatable_read_session
    ] = override_repeatable_read_session
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
    include_playlist: bool = True,
    source_target_type: str | None = None,
    source_target_value: str | None = None,
    source_search_query: str | None = None,
    grounding_status: str | None = None,
    match_status=None,
):
    """확정(`ready`) 후보 1건과 연결 장소/영상/채널을 시드한다."""
    from ktc.models import (
        ExtractedPlaceCandidate,
        FeatureExportStatus,
        GroundingStatus,
        MatchStatus,
        TravelPlace,
        YoutubeChannel,
        YoutubePlaylist,
        YoutubeVideo,
    )

    # 기본은 자동확정된 verified_raw transcript 후보(export 대상). T-165 게이트가
    # 기존 export 회귀에 영향을 주지 않도록 grounding을 명시한다.
    grounding_status = grounding_status or GroundingStatus.VERIFIED_RAW.value
    match_status = match_status or MatchStatus.MATCHED

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
            source_target_type=source_target_type,
            source_target_value=source_target_value,
            source_search_query=source_search_query,
        )
        playlist = (
            YoutubePlaylist(
                playlist_id=f"playlist-{video_id}",
                channel_id=channel_id,
                title="제주 동쪽 코스",
                description="월정리와 성산을 묶은 여행 코스",
            )
            if include_playlist
            else None
        )
        place = TravelPlace(
            name=place_name,
            description="에메랄드빛 바다와 카페가 가까운 제주 동쪽 해변",
            gemini_enriched_description="해안 도로 드라이브와 짧은 산책에 적합",
            latitude=33.5563,
            longitude=126.7958,
            category="해변",
            category_code_suggestion="01050100",
            official_address="제주특별자치도 제주시 구좌읍 월정리",
            road_address="제주특별자치도 제주시 구좌읍 해맞이해안로",
            is_geocoded=True,
        )
        rows = [video, place]
        if playlist is not None:
            rows.append(playlist)
        s.add_all(rows)
        await s.commit()
        await s.refresh(place)
        candidate = ExtractedPlaceCandidate(
            video_id=video_id,
            source_channel_id=channel_id,
            source_playlist_id=playlist.playlist_id if playlist is not None else None,
            source_text="월정리 해변이 정말 예뻐요",
            ai_place_name=candidate_name or place_name,
            timestamp_start="00:03:12",
            timestamp_end="00:04:10",
            confidence_score=0.86,
            candidate_category="해변",
            match_status=match_status,
            grounding_status=grounding_status,
            matched_place_id=place.place_id,
            feature_export_status=FeatureExportStatus.READY.value,
            provider_evidence_json={
                "gemini_url_evidence": "영상 3분대에서 해변 산책 장면과 장소명이 일치",
                "geocoding": {
                    "provider_candidates": {
                        "vworld": {"name": "월정리", "score": 0.91},
                        "kakao": {"name": "월정리해변", "score": 0.88},
                        "naver": {"name": "월정리", "score": 0.73},
                    }
                },
            },
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
    assert item["place"]["category_code_suggestion"] == "01050100"
    assert item["place"]["address"]["official_address"].startswith("제주")
    assert item["place"]["address"]["road_address"].startswith("제주")
    assert item["youtube"]["video_id"] == "vid1"
    assert item["youtube"]["channel_title"] == "제주 여행 채널"
    assert item["youtube"]["playlist_title"] == "제주 동쪽 코스"
    assert item["youtube"]["source_title"] == "제주 동쪽 코스"
    assert item["youtube"]["video_summary"] == "월정리 방문"
    assert item["evidence"]["timestamp_start"] == "00:03:12"
    assert item["evidence"]["confidence_score"] == 0.86
    assert item["source_record"]["provider"] == "kor-travel-concierge-youtube"
    assert item["source_record"]["source_entity_id"] == str(candidate_id)
    assert item["source_record"]["raw_payload_hash"].startswith("sha256:")


async def test_snapshot_surfaces_keyword_source_title(client, session_factory):
    await _seed_ready_candidate(
        session_factory,
        video_id="keyword-source",
        include_playlist=False,
        source_target_type="keyword",
        source_target_value="제주 여행",
        source_search_query="제주 여름 해변 여행",
    )

    resp = await client.get("/api/v1/features/snapshot")

    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["youtube"]["source_type"] == "keyword"
    assert item["youtube"]["source_value"] == "제주 여행"
    assert item["youtube"]["source_search_query"] == "제주 여름 해변 여행"
    assert item["youtube"]["corrected_search_query"] == "제주 여름 해변 여행"
    assert item["youtube"]["source_title"] == "제주 여름 해변 여행"


async def test_snapshot_surfaces_category_code_suggestion(client, session_factory):
    from ktc.models import TravelPlace

    _, place_id = await _seed_ready_candidate(session_factory)
    async with session_factory() as s:
        place = await s.get(TravelPlace, place_id)
        place.category_code_suggestion = "01050100"
        await s.commit()

    resp = await client.get("/api/v1/features/snapshot")
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["place"]["category_code_suggestion"] == "01050100"


async def test_snapshot_has_pinvi_feature_linked_poi_inputs(client, session_factory):
    """T-068: PinVi feature 연계 POI row까지 이어질 입력을 보존한다."""
    await _seed_ready_candidate(session_factory)

    resp = await client.get("/api/v1/features/snapshot")
    assert resp.status_code == 200
    item = resp.json()["items"][0]

    krtour_feature_snapshot = {
        "name": item["place"]["name"],
        "coord": {
            "longitude": item["place"]["longitude"],
            "latitude": item["place"]["latitude"],
        },
        "category": item["place"]["category_code_suggestion"],
        "marker_color": "P-13",
        "marker_icon": "krtour-map category mapping",
    }
    pinvi_feature_linked_poi = {
        "feature_id": "python-krtour-map-generated-feature-id",
        "feature_snapshot": krtour_feature_snapshot,
    }
    assert pinvi_feature_linked_poi["feature_id"]
    assert pinvi_feature_linked_poi["feature_snapshot"]["name"] == "월정리 해변"
    assert pinvi_feature_linked_poi["feature_snapshot"]["coord"] == {
        "longitude": 126.7958,
        "latitude": 33.5563,
    }
    assert pinvi_feature_linked_poi["feature_snapshot"]["category"] == "01050100"

    assert item["youtube"]["video_url"] == "https://www.youtube.com/watch?v=vid1"
    assert item["youtube"]["channel_id"] == "chan-vid1"
    assert item["youtube"]["playlist_id"] == "playlist-vid1"
    assert item["evidence"]["transcript_excerpt"] == "월정리 해변이 정말 예뻐요"
    assert item["evidence"]["gemini_url_evidence"].startswith("영상 3분대")
    assert set(item["evidence"]["providers"]) == {"vworld", "kakao", "naver"}


async def test_snapshot_excludes_pending_candidate(client, session_factory):
    from ktc.models import ExtractedPlaceCandidate, MatchStatus, YoutubeVideo

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


async def test_snapshot_excludes_ungrounded_auto_matched_transcript(client, session_factory):
    # T-165 G4 defense-in-depth: 자동확정됐으나 raw grounding 미확인 transcript 후보는
    # export(snapshot)에서 제외한다.
    from ktc.models import GroundingStatus

    await _seed_ready_candidate(
        session_factory, grounding_status=GroundingStatus.UNVERIFIED.value
    )
    resp = await client.get("/api/v1/features/snapshot")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_snapshot_includes_human_confirmed_ungrounded_transcript(client, session_factory):
    # 사람이 확정한(user_corrected) 후보는 grounding 미확인이어도 사람 판단이므로 export한다.
    from ktc.models import GroundingStatus, MatchStatus

    candidate_id, _ = await _seed_ready_candidate(
        session_factory,
        grounding_status=GroundingStatus.LEGACY_UNKNOWN.value,
        match_status=MatchStatus.USER_CORRECTED,
    )
    resp = await client.get("/api/v1/features/snapshot")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["candidate_id"] == candidate_id
    assert body["items"][0]["operation"] == "upsert"


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
    from ktc.models import ExtractedPlaceCandidate, FeatureExportStatus, MatchStatus

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
    from ktc.models import TravelPlace

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


async def test_features_snapshot_rejects_out_of_range_limit(client):
    """P-01 (이슈 #82) — limit이 [1, FEATURE_EXPORT_LIMIT_MAX] 밖이면 silent clamp가
    아니라 명시적 422로 거부한다."""
    too_small = await client.get("/api/v1/features/snapshot?limit=0")
    assert too_small.status_code == 422
    too_large = await client.get("/api/v1/features/snapshot?limit=501")
    assert too_large.status_code == 422


async def test_features_changes_rejects_out_of_range_limit(client):
    """P-01 (이슈 #82) — changes endpoint도 동일하게 범위 밖 limit을 422로 거부한다."""
    too_small = await client.get("/api/v1/features/changes?limit=0")
    assert too_small.status_code == 422
    too_large = await client.get("/api/v1/features/changes?limit=501")
    assert too_large.status_code == 422


async def test_source_entity_id_stable_across_upsert_and_reject(client, session_factory):
    """이슈 #84 — 한 후보(candidate.id)의 upsert export와 reject export가 동일한
    ``source_record.source_entity_id``를 가져야 한다.

    consumer(kor-travel-map)의 inactivate 매칭이 이 id로 조인하므로, operation에 따라
    값이 달라지면 reject/tombstone가 기적재 feature를 못 찾아 silent하게 실패한다.
    reject/tombstone는 동일 직렬화 경로를 공유하므로 reject 케이스로 대표 검증한다.
    """
    from ktc.models import ExtractedPlaceCandidate, FeatureExportStatus, MatchStatus

    candidate_id, _ = await _seed_ready_candidate(session_factory)

    # upsert export의 source_entity_id를 잡는다.
    first = await client.get("/api/v1/features/changes")
    upsert_items = first.json()["items"]
    assert upsert_items[0]["operation"] == "upsert"
    upsert_entity_id = upsert_items[0]["source_record"]["source_entity_id"]
    cursor = first.json()["next_cursor"]

    # 같은 후보를 검수 제외(reject)로 전환한다.
    async with session_factory() as s:
        candidate = await s.get(ExtractedPlaceCandidate, candidate_id)
        candidate.match_status = MatchStatus.IGNORED.value
        candidate.feature_export_status = FeatureExportStatus.REJECTED.value
        await s.commit()

    changes = await client.get(f"/api/v1/features/changes?cursor={cursor}")
    reject_items = changes.json()["items"]
    assert reject_items[0]["operation"] == "reject"
    reject_entity_id = reject_items[0]["source_record"]["source_entity_id"]

    # upsert와 reject export가 동일한 source_entity_id(= str(candidate.id))를 가져야 한다.
    assert upsert_entity_id == reject_entity_id == str(candidate_id)


# --- T-160 G1: 삭제 정합성 (soft delete → tombstone → reopen → 재발행) ---


async def _ledger_state(session_factory) -> list[tuple]:
    """ledger 전체의 (export_id, operation, sequence, payload_hash, rejection_reason)."""
    from sqlalchemy import select

    from ktc.models import FeatureExport

    async with session_factory() as s:
        rows = (
            (await s.execute(select(FeatureExport).order_by(FeatureExport.export_id)))
            .scalars()
            .all()
        )
        return [
            (r.export_id, r.operation, r.sequence, r.payload_hash, r.rejection_reason)
            for r in rows
        ]


async def _assert_full_sync_is_stable(session_factory) -> None:
    """process 재시작 등가: 새 세션에서 전량 sync를 반복해도 ledger가 불변(golden)."""
    from ktc.services import feature_export_service

    golden = await _ledger_state(session_factory)
    for _ in range(2):
        async with session_factory() as s:
            await feature_export_service.sync_feature_exports(s)
        assert await _ledger_state(session_factory) == golden


def _decode_cursor(cursor: str | None) -> int | None:
    from ktc.services.feature_export_service import _decode_cursor as decode

    return decode(cursor)


async def test_g1_delete_tombstone_reopen_reissue_cycle(client, session_factory):
    """G1 시나리오: export(snapshot 노출) → 삭제 → changes tombstone(새 sequence) →
    reopen → 재확정 후 다음 sync가 upsert 재발행 → cursor 소비 일관성(유실·중복 없음)."""
    from sqlalchemy import select

    from ktc.models import ExtractedPlaceCandidate, FeatureExport

    candidate_id, place_id = await _seed_ready_candidate(
        session_factory, video_id="vid-g1"
    )
    export_id = f"ytpc_{candidate_id}"

    # 1) export: snapshot에 upsert로 노출되고 changes cursor를 소비한다.
    snap = await client.get("/api/v1/features/snapshot")
    assert [item["export_id"] for item in snap.json()["items"]] == [export_id]

    first = await client.get("/api/v1/features/changes")
    first_body = first.json()
    assert [item["operation"] for item in first_body["items"]] == ["upsert"]
    cursor = first_body["next_cursor"]
    cursor_seqs = [_decode_cursor(cursor)]
    consumed_ops = ["upsert"]

    # 2) 검수 큐 개별 삭제(soft delete) — 행·ledger 보존 + 같은 트랜잭션 tombstone.
    deleted = await client.delete(
        f"/api/v1/destinations/candidates/{candidate_id}",
        params={"reason": "G1 삭제"},
    )
    assert deleted.status_code == 200

    async with session_factory() as s:
        candidate = await s.get(ExtractedPlaceCandidate, candidate_id)
        assert candidate is not None
        assert candidate.deleted_at is not None
        assert candidate.deletion_reason == "G1 삭제"
        assert candidate.deleted_by == "web"
        row = (
            await s.execute(
                select(FeatureExport).where(
                    FeatureExport.candidate_id == candidate_id
                )
            )
        ).scalar_one()
        assert row.operation == "tombstone"
        assert row.rejection_reason == "G1 삭제"

    # 검수 큐·상세에서 유령으로 남지 않는다.
    unmatched = await client.get("/api/v1/destinations/unmatched")
    assert all(item["id"] != candidate_id for item in unmatched.json()["items"])
    detail = await client.get(
        f"/api/v1/destinations/candidates/{candidate_id}/detail"
    )
    assert detail.status_code == 404

    # 3) changes: cursor 이후 tombstone 1건(새 sequence).
    second = await client.get(f"/api/v1/features/changes?cursor={cursor}")
    second_body = second.json()
    assert [item["operation"] for item in second_body["items"]] == ["tombstone"]
    assert second_body["items"][0]["export_id"] == export_id
    cursor = second_body["next_cursor"]
    cursor_seqs.append(_decode_cursor(cursor))
    consumed_ops.append("tombstone")

    snapshot_after_delete = await client.get("/api/v1/features/snapshot")
    assert snapshot_after_delete.json()["items"] == []

    # 4) process 재시작 등가: 새 세션 전량 sync 반복에도 ledger 불변(golden).
    await _assert_full_sync_is_stable(session_factory)

    # 5) reopen: 삭제 필드 clear + needs_review + export pending.
    reopened = await client.post(
        f"/api/v1/destinations/unmatched/{candidate_id}/reopen"
    )
    assert reopened.status_code == 200
    reopened_body = reopened.json()
    assert reopened_body["reopened_from"] == "deleted"
    assert reopened_body["candidate"]["match_status"] == "needs_review"
    assert reopened_body["candidate"]["feature_export_status"] == "pending"

    # 이미 needs_review인 후보의 재reopen은 409.
    again = await client.post(
        f"/api/v1/destinations/unmatched/{candidate_id}/reopen"
    )
    assert again.status_code == 409

    # 재확정 전에는 아무 것도 재발행되지 않는다 — sync의 tombstone freeze 덕에
    # reopen 직후(`needs_review`+`pending`) 재스캔도 tombstone을 재sequence하지
    # 않는다(cursor 불변, upsert 없음).
    interim = await client.get(f"/api/v1/features/changes?cursor={cursor}")
    interim_body = interim.json()
    assert interim_body["items"] == []
    assert interim_body["next_cursor"] == cursor
    snapshot_after_reopen = await client.get("/api/v1/features/snapshot")
    assert snapshot_after_reopen.json()["items"] == []

    # 6) 재확정(기존 장소 매칭) → 다음 sync에서 같은 export_id의 upsert 재발행.
    resolved = await client.post(
        f"/api/v1/destinations/unmatched/{candidate_id}/resolve",
        json={"action": "match_existing", "place_id": place_id},
    )
    assert resolved.status_code == 200

    reissued = await client.get(f"/api/v1/features/changes?cursor={cursor}")
    reissued_body = reissued.json()
    assert [item["operation"] for item in reissued_body["items"]] == ["upsert"]
    assert reissued_body["items"][0]["export_id"] == export_id
    cursor_seqs.append(_decode_cursor(reissued_body["next_cursor"]))
    consumed_ops.append("upsert")

    snapshot_final = await client.get("/api/v1/features/snapshot")
    assert [item["export_id"] for item in snapshot_final.json()["items"]] == [
        export_id
    ]

    # 7) cursor 소비 일관성: sequence가 단조 증가(유실·중복 없음), 전이 순서 보존.
    assert cursor_seqs == sorted(cursor_seqs)
    assert len(set(cursor_seqs)) == len(cursor_seqs)
    assert consumed_ops[0] == "upsert"
    assert consumed_ops[-1] == "upsert"
    assert "tombstone" in consumed_ops

    # 최종 상태도 재시작 등가.
    await _assert_full_sync_is_stable(session_factory)


async def test_g1_exclude_video_bulk_tombstones_exported_candidates(
    client, session_factory
):
    """G1 벌크 시나리오: export된 확정 후보를 포함한 영상 제외 —
    soft delete + 고아 장소 정리 + ledger tombstone + 재시작 등가."""
    from sqlalchemy import select

    from ktc.models import (
        ExtractedPlaceCandidate,
        FeatureExport,
        TravelPlace,
        VideoPlaceMapping,
    )

    candidate_id, place_id = await _seed_ready_candidate(
        session_factory, video_id="vid-ex-bulk"
    )
    async with session_factory() as s:
        s.add(
            VideoPlaceMapping(
                video_id="vid-ex-bulk",
                place_id=place_id,
                place_candidate_id=candidate_id,
                ai_summary="언급",
            )
        )
        await s.commit()

    # export 노출 후 cursor를 잡는다.
    first = await client.get("/api/v1/features/changes")
    assert [item["operation"] for item in first.json()["items"]] == ["upsert"]
    cursor = first.json()["next_cursor"]

    # 확정 연결(매핑 보유) 후보의 개별 삭제는 여전히 409(부분 변경 없음).
    conflict = await client.delete(
        f"/api/v1/destinations/candidates/{candidate_id}"
    )
    assert conflict.status_code == 409
    async with session_factory() as s:
        candidate = await s.get(ExtractedPlaceCandidate, candidate_id)
        assert candidate.deleted_at is None
        assert candidate.matched_place_id == place_id

    # 영상 제외(force): 후보 soft delete + 매핑 삭제 + 고아 장소 삭제 + tombstone.
    excluded = await client.post(
        "/api/v1/destinations/videos/vid-ex-bulk/exclude",
        json={"reason": "관련 없는 영상"},
    )
    assert excluded.status_code == 200
    summary = excluded.json()
    assert summary["deleted_candidates"] == 1
    assert summary["deleted_mappings"] == 1
    assert summary["deleted_places"] == 1
    assert summary["tombstoned_exports"] == 1

    async with session_factory() as s:
        candidate = await s.get(ExtractedPlaceCandidate, candidate_id)
        assert candidate is not None
        assert candidate.deleted_at is not None
        assert candidate.deletion_reason == "관련 없는 영상"
        assert candidate.matched_place_id is None
        assert await s.get(TravelPlace, place_id) is None
        row = (
            await s.execute(
                select(FeatureExport).where(
                    FeatureExport.candidate_id == candidate_id
                )
            )
        ).scalar_one()
        assert row.operation == "tombstone"
        assert row.rejection_reason == "관련 없는 영상"

    # downstream은 changes로 제거를 전달받는다.
    changes = await client.get(f"/api/v1/features/changes?cursor={cursor}")
    items = changes.json()["items"]
    assert [item["operation"] for item in items] == ["tombstone"]
    assert items[0]["export_id"] == f"ytpc_{candidate_id}"

    snapshot = await client.get("/api/v1/features/snapshot")
    assert snapshot.json()["items"] == []

    # process 재시작 등가.
    await _assert_full_sync_is_stable(session_factory)


async def test_sync_safety_net_tombstones_soft_deleted_without_helper(
    client, session_factory
):
    """이중 안전망: helper를 우회해 soft delete 표시만 된 후보도 다음
    `sync_feature_exports`가 '후보 소멸' 분류로 tombstone 전환한다."""
    from sqlalchemy import select

    from ktc.models import ExtractedPlaceCandidate, FeatureExport, utcnow
    from ktc.services import feature_export_service

    candidate_id, _ = await _seed_ready_candidate(session_factory, video_id="vid-sn")

    # 먼저 export 노출(ledger upsert 생성).
    await client.get("/api/v1/features/snapshot")

    async with session_factory() as s:
        candidate = await s.get(ExtractedPlaceCandidate, candidate_id)
        candidate.deleted_at = utcnow()
        candidate.deletion_reason = "직접 표기(안전망 검증)"
        candidate.matched_place_id = None
        await s.commit()

    async with session_factory() as s:
        await feature_export_service.sync_feature_exports(s)

    async with session_factory() as s:
        row = (
            await s.execute(
                select(FeatureExport).where(
                    FeatureExport.candidate_id == candidate_id
                )
            )
        ).scalar_one()
        assert row.operation == "tombstone"

    await _assert_full_sync_is_stable(session_factory)
