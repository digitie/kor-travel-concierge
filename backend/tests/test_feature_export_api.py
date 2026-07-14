"""범용 feature 수집 API(`/api/v1/features/*`)와 export ledger 동기화 테스트.

`get_session` 의존성을 테스트 엔진으로 오버라이드해 ASGI 앱을 직접 호출한다.
(T-066, ADR-26)
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from ktc.core.database import get_repeatable_read_session, get_session
from main import app


def _client_operation_id() -> str:
    return str(uuid4())


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
    mark_dirty: bool = True,
):
    """확정(`ready`) 후보 1건과 연결 장소/영상/채널을 시드한다.

    `mark_dirty=False`면 dirty outbox 표시를 생략해, wired 전이를 우회한 '미배선' 후보를
    재현한다(안전망 전량 sync 검증용).
    """
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
        await s.flush()
        # 실제 파이프라인에서 후보가 export 대상(ready)이 되는 전이(geocode 자동확정·resolve)는
        # 같은 트랜잭션에서 dirty outbox에 표시된다(T-171). 직접 시드는 그 전이를 우회하므로,
        # 시드가 동일하게 dirty로 표시해 공급 GET(sync_dirty)이 ledger를 만들도록 한다.
        if mark_dirty:
            from ktc.services import feature_export_service

            await feature_export_service.mark_candidates_dirty(
                s, [candidate.id], reason="seed"
            )
        await s.commit()
        await s.refresh(candidate)
        return candidate.id, place.place_id


async def _mark_dirty(session_factory, *candidate_ids: int) -> None:
    """직접 DB를 변경한 테스트가 실제 wired mutation처럼 후보를 dirty outbox에 표시한다.

    프로덕션에서는 상태 전이가 resolve/geocode/reopen 등 wired 경로를 거쳐 같은 트랜잭션에서
    dirty로 표시된다. 아래 테스트들은 분류 로직을 직접 DB 쓰기로 검증하는 지름길을 쓰므로,
    그 트리거(dirty 표시)를 명시적으로 재현해 공급 GET(`sync_dirty`)이 반영하게 한다(T-171).
    """
    from ktc.services import feature_export_service

    async with session_factory() as s:
        await feature_export_service.mark_candidates_dirty(
            s, list(candidate_ids), reason="test"
        )
        await s.commit()


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


async def test_snapshot_item_includes_schema_version(client, session_factory):
    """T-189: 모든 item에 additive `schema_version`이 포함된다."""
    await _seed_ready_candidate(session_factory)
    resp = await client.get("/api/v1/features/snapshot")
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["schema_version"] == 1


async def test_snapshot_injects_admin_codes_with_derived_sido(client, session_factory):
    """T-189: 행정코드는 place 실데이터에서 주입하고, sido_code는 sigungu_code 앞 2자리로 유도한다."""
    from ktc.models import TravelPlace

    candidate_id, place_id = await _seed_ready_candidate(session_factory)

    # 시드 place는 행정코드가 없어 주입 결과도 None이다(하드코딩 None 제거 회귀).
    baseline = await client.get("/api/v1/features/snapshot")
    addr0 = baseline.json()["items"][0]["place"]["address"]
    assert addr0["sigungu_code"] is None
    assert addr0["legal_dong_code"] is None
    assert addr0["sido_code"] is None

    async with session_factory() as s:
        place = await s.get(TravelPlace, place_id)
        place.sigungu_code = "11680"
        place.legal_dong_code = "1168010100"
        await s.commit()
    await _mark_dirty(session_factory, candidate_id)

    resp = await client.get("/api/v1/features/snapshot")
    addr = resp.json()["items"][0]["place"]["address"]
    assert addr["sigungu_code"] == "11680"
    assert addr["legal_dong_code"] == "1168010100"
    # 유도 규칙: sigungu_code[:2].
    assert addr["sido_code"] == "11"


async def test_admin_code_injection_reissues_export(client, session_factory):
    """T-189: 행정코드 주입으로 payload_hash가 바뀌면 changes가 같은 export_id의 새 upsert로 재발행한다.

    cursor는 재발행 후에도 계속 유효하다(단조 전진).
    """
    from ktc.models import TravelPlace

    candidate_id, place_id = await _seed_ready_candidate(session_factory)

    first = await client.get("/api/v1/features/changes")
    first_items = first.json()["items"]
    assert [i["operation"] for i in first_items] == ["upsert"]
    old_hash = first_items[0]["source_record"]["raw_payload_hash"]
    cursor = first.json()["next_cursor"]

    async with session_factory() as s:
        place = await s.get(TravelPlace, place_id)
        place.sigungu_code = "26110"
        await s.commit()
    await _mark_dirty(session_factory, candidate_id)

    changes = await client.get(f"/api/v1/features/changes?cursor={cursor}")
    items = changes.json()["items"]
    assert [i["operation"] for i in items] == ["upsert"]
    assert items[0]["export_id"] == f"ytpc_{candidate_id}"
    assert items[0]["place"]["address"]["sigungu_code"] == "26110"
    assert items[0]["place"]["address"]["sido_code"] == "26"
    # 재발행: payload_hash가 바뀌고 새 sequence로 전진한다.
    assert items[0]["source_record"]["raw_payload_hash"] != old_hash
    assert _decode_cursor(changes.json()["next_cursor"]) > _decode_cursor(cursor)


async def test_invalid_cursor_returns_code_invalid_cursor(client, session_factory):
    """T-189: cursor 오류는 한국어 detail을 유지하면서 additive `code`를 노출한다."""
    await _seed_ready_candidate(session_factory)
    resp = await client.get("/api/v1/features/changes?cursor=!!not-base64!!")
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "invalid_cursor"
    assert "cursor" in detail["message"]


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


async def test_snapshot_excludes_ready_needs_review_drift(client, session_factory):
    """READY/place가 남은 legacy drift여도 미확정 후보를 신규 공급하지 않는다."""
    from sqlalchemy import select

    from ktc.models import FeatureExport, MatchStatus

    candidate_id, _ = await _seed_ready_candidate(
        session_factory,
        video_id="ready-needs-review-drift",
        match_status=MatchStatus.NEEDS_REVIEW,
    )

    resp = await client.get("/api/v1/features/snapshot")
    assert resp.status_code == 200
    assert resp.json()["items"] == []
    async with session_factory() as s:
        assert (
            await s.execute(
                select(FeatureExport).where(
                    FeatureExport.candidate_id == candidate_id
                )
            )
        ).scalar_one_or_none() is None


async def test_ready_needs_review_drift_tombstones_existing_export(
    client, session_factory
):
    """이미 공급한 후보가 미확정 상태로 drift하면 READY가 남아도 회수한다."""
    from ktc.models import ExtractedPlaceCandidate, MatchStatus
    from ktc.services import feature_export_service

    candidate_id, _ = await _seed_ready_candidate(
        session_factory,
        video_id="ready-needs-review-existing",
    )
    first = await client.get("/api/v1/features/changes")
    assert [item["operation"] for item in first.json()["items"]] == ["upsert"]

    async with session_factory() as s:
        candidate = await s.get(ExtractedPlaceCandidate, candidate_id)
        assert candidate is not None
        candidate.match_status = MatchStatus.NEEDS_REVIEW.value
        await feature_export_service.mark_candidates_dirty(
            s,
            [candidate_id],
            reason="test_ready_needs_review_drift",
        )
        await s.commit()

    changed = await client.get(
        "/api/v1/features/changes",
        params={"cursor": first.json()["next_cursor"]},
    )
    assert [item["operation"] for item in changed.json()["items"]] == [
        "tombstone"
    ]
    assert (await client.get("/api/v1/features/snapshot")).json()["items"] == []


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
        grounding_status=GroundingStatus.MISSING.value,
        match_status=MatchStatus.USER_CORRECTED,
    )
    resp = await client.get("/api/v1/features/snapshot")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["candidate_id"] == candidate_id
    assert body["items"][0]["operation"] == "upsert"


async def test_snapshot_preserves_legacy_auto_matched_transcript(client, session_factory):
    # MAJOR 2(최고위험): migration이 기존 MATCHED·export 후보를 legacy_unknown으로 backfill해도
    # export를 회수하지 않는다(기존 노출 보존 — krtour-map/PinVi 대량 inactive·POI 소실 방지).
    from ktc.models import GroundingStatus

    candidate_id, _ = await _seed_ready_candidate(
        session_factory, grounding_status=GroundingStatus.LEGACY_UNKNOWN.value
    )
    resp = await client.get("/api/v1/features/snapshot")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["candidate_id"] == candidate_id
    assert body["items"][0]["operation"] == "upsert"


async def test_changes_tombstones_legacy_after_reprocess_marks_failed(
    client, session_factory
):
    # legacy_unknown 후보는 노출을 유지하다가, 재처리로 grounding이 실제 unverified로
    # 판정되면 그때 tombstone으로 회수한다("재평가 후 회수").
    from ktc.models import ExtractedPlaceCandidate, GroundingStatus

    candidate_id, _ = await _seed_ready_candidate(
        session_factory, grounding_status=GroundingStatus.LEGACY_UNKNOWN.value
    )
    # 최초 노출(has_row 생성) — upsert.
    first = await client.get("/api/v1/features/changes")
    assert first.status_code == 200
    assert [i["operation"] for i in first.json()["items"]] == ["upsert"]
    cursor = first.json()["next_cursor"]

    # 재처리로 grounding이 unverified로 판정됨.
    async with session_factory() as s:
        cand = await s.get(ExtractedPlaceCandidate, candidate_id)
        cand.grounding_status = GroundingStatus.UNVERIFIED.value
        await s.commit()
    await _mark_dirty(session_factory, candidate_id)

    after = await client.get(f"/api/v1/features/changes?cursor={cursor}")
    assert after.status_code == 200
    items = after.json()["items"]
    assert [i["operation"] for i in items] == ["tombstone"]
    assert items[0]["candidate_id"] == candidate_id


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
    await _mark_dirty(session_factory, candidate_id)

    changes = await client.get(f"/api/v1/features/changes?cursor={cursor}")
    assert changes.status_code == 200
    items = changes.json()["items"]
    assert len(items) == 1
    assert items[0]["operation"] == "reject"
    assert items[0]["rejection_reason"] == "중복 장소"

    # reject된 후보는 더 이상 snapshot(활성)에 나타나지 않는다.
    snapshot = await client.get("/api/v1/features/snapshot")
    assert snapshot.json()["items"] == []


async def test_empty_snapshot_commits_hidden_reject_transition(
    client, session_factory
):
    """활성 row가 0건이어도 snapshot 내부 sync 결과는 rollback되지 않는다."""
    from sqlalchemy import select

    from ktc.models import (
        ExtractedPlaceCandidate,
        FeatureExport,
        FeatureExportStatus,
        MatchStatus,
    )

    candidate_id, _ = await _seed_ready_candidate(
        session_factory,
        video_id="snapshot-hidden-reject-commit",
    )
    first = await client.get("/api/v1/features/snapshot")
    assert first.status_code == 200
    assert [item["operation"] for item in first.json()["items"]] == ["upsert"]
    first_cursor = first.json()["next_cursor"]
    assert first_cursor is not None

    async with session_factory() as session:
        candidate = await session.get(ExtractedPlaceCandidate, candidate_id)
        assert candidate is not None
        candidate.match_status = MatchStatus.IGNORED.value
        candidate.feature_export_status = FeatureExportStatus.REJECTED.value
        candidate.review_note = "snapshot에서 숨겨지는 제외"
        await session.commit()
    # 직접 DB 전이는 production writer의 durable outbox 배선을 우회하므로 동일하게 표시한다.
    await _mark_dirty(session_factory, candidate_id)

    hidden = await client.get("/api/v1/features/snapshot")
    assert hidden.status_code == 200
    assert hidden.json()["items"] == []

    # 새 session에서도 reject가 남아 있어야 한다. 빈 page에서 commit하지 않으면
    # dependency session close 시 upsert로 rollback되어 이 검증이 실패한다.
    async with session_factory() as session:
        row = (
            await session.execute(
                select(FeatureExport).where(
                    FeatureExport.candidate_id == candidate_id
                )
            )
        ).scalar_one()
        assert row.operation == "reject"
        assert row.rejection_reason == "snapshot에서 숨겨지는 제외"
        committed_sequence = row.sequence

    changes = await client.get(
        "/api/v1/features/changes",
        params={"cursor": first_cursor},
    )
    assert changes.status_code == 200
    assert [item["operation"] for item in changes.json()["items"]] == ["reject"]
    assert _decode_cursor(changes.json()["next_cursor"]) == committed_sequence


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
    # 프로덕션에서는 place 보정(correct_place)이 매칭 후보를 dirty로 표시한다(T-171).
    await _mark_dirty(session_factory, candidate_id)

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
    await _mark_dirty(session_factory, candidate_id)

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


async def test_export_sync_and_reopen_share_writer_lock_without_late_upsert(
    session_factory,
    monkeypatch,
):
    """sync의 미커밋 upsert 뒤 reopen이 와도 최종 ledger는 tombstone이어야 한다."""
    from sqlalchemy import select

    from ktc.models import (
        ExtractedPlaceCandidate,
        FeatureExport,
        FeatureExportOperation,
        MatchStatus,
        TravelPlace,
        VideoPlaceMapping,
    )
    from ktc.services import feature_export_service, place_service

    candidate_id, place_id = await _seed_ready_candidate(
        session_factory,
        video_id="export-reopen-lock-race",
    )
    async with session_factory() as seed_session:
        candidate = await seed_session.get(ExtractedPlaceCandidate, candidate_id)
        place = await seed_session.get(TravelPlace, place_id)
        assert candidate is not None
        assert place is not None
        mapping = VideoPlaceMapping(
            video_id=candidate.video_id,
            place_id=place_id,
            place_candidate_id=candidate_id,
            ai_summary="동시성 검증 매핑",
        )
        seed_session.add(mapping)
        await seed_session.commit()
        undo_token = place_service.encode_candidate_undo_token(
            candidate,
            matched_place_revision=place.state_revision,
        )

    original_lock = feature_export_service.acquire_feature_export_lock
    reopen_reached_export_lock = asyncio.Event()
    reopen_acquired_export_lock = asyncio.Event()
    reopen_session = None

    async def observed_lock(session):
        if session is reopen_session:
            reopen_reached_export_lock.set()
        await original_lock(session)
        if session is reopen_session:
            reopen_acquired_export_lock.set()

    monkeypatch.setattr(
        feature_export_service,
        "acquire_feature_export_lock",
        observed_lock,
    )

    async def run_reopen():
        nonlocal reopen_session
        async with session_factory() as candidate_session:
            reopen_session = candidate_session
            result = await place_service.reopen_candidate(
                candidate_session,
                candidate_id=candidate_id,
                undo_token=undo_token,
            )
            await candidate_session.commit()
            return result

    reopen_task = None
    try:
        async with session_factory() as sync_session:
            # sync가 export writer lock 아래서 과거 READY snapshot의 upsert를 준비한다.
            await original_lock(sync_session)
            assert (
                await feature_export_service.sync_feature_exports(
                    sync_session,
                    commit=False,
                )
                == 1
            )
            reopen_task = asyncio.create_task(run_reopen())
            await asyncio.wait_for(reopen_reached_export_lock.wait(), timeout=5)
            assert reopen_acquired_export_lock.is_set() is False
            assert reopen_task.done() is False
            # 늦은 upsert를 먼저 commit해도 대기하던 reopen이 그 row를 보고 tombstone한다.
            await sync_session.commit()

        result = await asyncio.wait_for(reopen_task, timeout=5)
    finally:
        if reopen_task is not None and not reopen_task.done():
            reopen_task.cancel()
            await asyncio.gather(reopen_task, return_exceptions=True)
    assert result.tombstoned_exports == 1
    async with session_factory() as check_session:
        candidate = await check_session.get(ExtractedPlaceCandidate, candidate_id)
        assert candidate is not None
        assert candidate.match_status == MatchStatus.NEEDS_REVIEW.value
        row = (
            await check_session.execute(
                select(FeatureExport).where(
                    FeatureExport.candidate_id == candidate_id
                )
            )
        ).scalar_one()
        assert row.operation == FeatureExportOperation.TOMBSTONE.value
        mappings = (
            await check_session.execute(
                select(VideoPlaceMapping).where(
                    VideoPlaceMapping.place_candidate_id == candidate_id
                )
            )
        ).scalars().all()
        assert mappings == []


async def test_export_sync_and_merge_publish_only_complete_place_snapshots(
    session_factory,
    monkeypatch,
):
    """source snapshot을 읽은 sync가 끝난 뒤 merge가 진행되어 fallback payload를 막는다."""
    from sqlalchemy import select

    from ktc.models import ExtractedPlaceCandidate, FeatureExport, TravelPlace
    from ktc.services import feature_export_service, place_service

    candidate_id, source_place_id = await _seed_ready_candidate(
        session_factory,
        video_id="export-merge-lock-race",
        place_name="병합 전 원본 장소",
    )
    async with session_factory() as seed_session:
        target = TravelPlace(
            name="병합 후 정본 장소",
            official_address="부산광역시 정본구 정본동 1",
            latitude=35.1234,
            longitude=129.1234,
            is_geocoded=True,
        )
        seed_session.add(target)
        await seed_session.commit()
        target_place_id = target.place_id

    original_lock = feature_export_service.acquire_feature_export_lock
    original_load_related = feature_export_service._load_related
    sync_snapshot_loaded = asyncio.Event()
    release_sync = asyncio.Event()
    merge_reached_export_lock = asyncio.Event()
    merge_acquired_export_lock = asyncio.Event()
    sync_session_ref = None
    merge_session_ref = None

    async def observed_lock(session):
        if session is merge_session_ref:
            merge_reached_export_lock.set()
        await original_lock(session)
        if session is merge_session_ref:
            merge_acquired_export_lock.set()

    async def pause_after_related_snapshot(session, candidates):
        related = await original_load_related(session, candidates)
        if session is sync_session_ref:
            sync_snapshot_loaded.set()
            await release_sync.wait()
        return related

    monkeypatch.setattr(
        feature_export_service,
        "acquire_feature_export_lock",
        observed_lock,
    )
    monkeypatch.setattr(
        feature_export_service,
        "_load_related",
        pause_after_related_snapshot,
    )

    async def run_sync() -> int:
        nonlocal sync_session_ref
        async with session_factory() as sync_session:
            sync_session_ref = sync_session
            return await feature_export_service.sync_feature_exports(sync_session)

    async def run_merge() -> int:
        nonlocal merge_session_ref
        async with session_factory() as merge_session:
            merge_session_ref = merge_session
            merged = await place_service.merge_places(
                merge_session,
                source_place_id=source_place_id,
                target_place_id=target_place_id,
            )
            return merged.place_id

    sync_task = asyncio.create_task(run_sync())
    merge_task = None
    try:
        await asyncio.wait_for(sync_snapshot_loaded.wait(), timeout=5)
        merge_task = asyncio.create_task(run_merge())
        await asyncio.wait_for(merge_reached_export_lock.wait(), timeout=5)
        assert merge_acquired_export_lock.is_set() is False
        assert merge_task.done() is False
        release_sync.set()
        sync_changed, merged_place_id = await asyncio.wait_for(
            asyncio.gather(sync_task, merge_task),
            timeout=5,
        )
    finally:
        release_sync.set()
        pending = [sync_task]
        if merge_task is not None:
            pending.append(merge_task)
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    assert sync_changed == 1
    assert merged_place_id == target_place_id
    async with session_factory() as check_session:
        candidate = await check_session.get(ExtractedPlaceCandidate, candidate_id)
        row = (
            await check_session.execute(
                select(FeatureExport).where(
                    FeatureExport.candidate_id == candidate_id
                )
            )
        ).scalar_one()
        assert candidate is not None
        assert candidate.matched_place_id == target_place_id
        # merge가 기다리는 동안 commit된 ledger는 완전한 pre-merge source snapshot이다.
        assert row.payload_json["place"]["name"] == "병합 전 원본 장소"
        assert row.payload_json["place"]["latitude"] is not None
        assert row.payload_json["place"]["longitude"] is not None
        pre_merge_sequence = row.sequence

    async with session_factory() as sync_session:
        assert await feature_export_service.sync_feature_exports(sync_session) == 1
    async with session_factory() as check_session:
        row = (
            await check_session.execute(
                select(FeatureExport).where(
                    FeatureExport.candidate_id == candidate_id
                )
            )
        ).scalar_one()
        assert row.sequence > pre_merge_sequence
        assert row.payload_json["place"]["name"] == "병합 후 정본 장소"
        assert row.payload_json["place"]["address"]["official_address"] == (
            "부산광역시 정본구 정본동 1"
        )
        assert row.payload_json["place"]["latitude"] == 35.1234
        assert row.payload_json["place"]["longitude"] == 129.1234


async def test_g1_delete_tombstone_reopen_reissue_cycle(client, session_factory):
    """G1 시나리오: export(snapshot 노출) → 삭제 → changes tombstone(새 sequence) →
    reopen → 재확정 후 다음 sync가 upsert 재발행 → cursor 소비 일관성(유실·중복 없음)."""
    from sqlalchemy import select

    from ktc.models import (
        ExtractedPlaceCandidate,
        FeatureExport,
        MatchStatus,
    )

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

    # 2) 이 테스트는 삭제 이후 ledger 전이만 다룬다. 먼저 정상 MATCHED upsert를
    # 소비한 뒤, 과거 direct writer가 검수 복귀 상태만 남기고 outbox 기록 전 중단된
    # legacy drift를 재현한다. 제품 reopen을 쓰면 그 동작 자체의 tombstone이 먼저
    # 발행되어 삭제의 최초 tombstone을 검증할 수 없다.
    async with session_factory() as s:
        candidate = await s.get(ExtractedPlaceCandidate, candidate_id)
        assert candidate is not None
        candidate.match_status = MatchStatus.NEEDS_REVIEW.value
        candidate.matched_place_id = None
        candidate.feature_export_status = "pending"
        await s.commit()

    # DB trigger가 소유하는 최신 revision을 읽어 삭제 선행 조건으로 사용한다.
    delete_prerequisite = await client.get(
        f"/api/v1/destinations/candidates/{candidate_id}/detail"
    )
    assert delete_prerequisite.status_code == 200
    assert delete_prerequisite.json()["candidate"]["match_status"] == "needs_review"

    # 3) 검수 큐 개별 삭제(soft delete) — 행·ledger 보존 + 같은 트랜잭션 tombstone.
    deleted = await client.delete(
        f"/api/v1/destinations/candidates/{candidate_id}",
        params={
            "client_operation_id": _client_operation_id(),
            "reason": "G1 삭제",
            "expected_revision": delete_prerequisite.json()["candidate"][
                "state_revision"
            ],
        },
    )
    assert deleted.status_code == 200
    deleted_undo = deleted.json()["undo"]

    async with session_factory() as s:
        candidate = await s.get(ExtractedPlaceCandidate, candidate_id)
        assert candidate is not None
        assert candidate.deleted_at is not None
        assert candidate.deletion_reason == "G1 삭제"
        assert candidate.deleted_by == "unverified-web"
        row = (
            await s.execute(
                select(FeatureExport).where(
                    FeatureExport.candidate_id == candidate_id
                )
            )
        ).scalar_one()
        assert row.operation == "tombstone"
        assert row.rejection_reason == "G1 삭제"

    # 기본 검수 큐에서는 사라지지만 removed 상세/undo 이력으로는 조회된다.
    unmatched = await client.get("/api/v1/destinations/unmatched")
    assert all(item["id"] != candidate_id for item in unmatched.json()["items"])
    detail = await client.get(
        f"/api/v1/destinations/candidates/{candidate_id}/detail"
    )
    assert detail.status_code == 200
    assert detail.json()["candidate"]["review_state"] == "deleted"

    # 4) changes: cursor 이후 tombstone 1건(새 sequence).
    second = await client.get(f"/api/v1/features/changes?cursor={cursor}")
    second_body = second.json()
    assert [item["operation"] for item in second_body["items"]] == ["tombstone"]
    assert second_body["items"][0]["export_id"] == export_id
    cursor = second_body["next_cursor"]
    cursor_seqs.append(_decode_cursor(cursor))
    consumed_ops.append("tombstone")

    snapshot_after_delete = await client.get("/api/v1/features/snapshot")
    assert snapshot_after_delete.json()["items"] == []

    # 5) process 재시작 등가: 새 세션 전량 sync 반복에도 ledger 불변(golden).
    await _assert_full_sync_is_stable(session_factory)

    # 6) reopen: 삭제 필드 clear + needs_review + export pending.
    reopened = await client.post(
        f"/api/v1/destinations/unmatched/{candidate_id}/reopen",
        json={"undo_token": deleted_undo["token"]},
    )
    assert reopened.status_code == 200
    reopened_body = reopened.json()
    assert reopened_body["reopened_from"] == "deleted"
    assert reopened_body["candidate"]["match_status"] == "needs_review"
    assert reopened_body["candidate"]["feature_export_status"] == "pending"

    # 이미 needs_review인 후보의 재reopen은 409.
    again = await client.post(
        f"/api/v1/destinations/unmatched/{candidate_id}/reopen",
        json={"undo_token": deleted_undo["token"]},
    )
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "candidate_already_needs_review"

    # 재확정 전에는 아무 것도 재발행되지 않는다 — sync의 tombstone freeze 덕에
    # reopen 직후(`needs_review`+`pending`) 재스캔도 tombstone을 재sequence하지
    # 않는다(cursor 불변, upsert 없음).
    interim = await client.get(f"/api/v1/features/changes?cursor={cursor}")
    interim_body = interim.json()
    assert interim_body["items"] == []
    assert interim_body["next_cursor"] == cursor
    snapshot_after_reopen = await client.get("/api/v1/features/snapshot")
    assert snapshot_after_reopen.json()["items"] == []

    # 7) 재확정(기존 장소 매칭) → 다음 sync에서 같은 export_id의 upsert 재발행.
    resolved = await client.post(
        f"/api/v1/destinations/unmatched/{candidate_id}/resolve",
        json={
            "client_operation_id": _client_operation_id(),
            "expected_revision": reopened_body["candidate"]["state_revision"],
            "action": "match_existing",
            "place_id": place_id,
        },
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
        MatchStatus,
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

    # 기존 export와 매핑을 유지한 채 legacy 검수 복귀 상태를 재현한다. 개별 삭제는
    # needs_review gate를 통과한 뒤 매핑 fence에서 409여야 하고, 이어지는 영상 제외가
    # 기존 ledger를 tombstone한다.
    async with session_factory() as s:
        candidate = await s.get(ExtractedPlaceCandidate, candidate_id)
        assert candidate is not None
        candidate.match_status = MatchStatus.NEEDS_REVIEW.value
        candidate.feature_export_status = "pending"
        await s.commit()

    # 확정 연결(매핑 보유) 후보의 개별 삭제는 여전히 409(부분 변경 없음).
    detail = await client.get(
        f"/api/v1/destinations/candidates/{candidate_id}/detail"
    )
    assert detail.status_code == 200
    conflict = await client.delete(
        f"/api/v1/destinations/candidates/{candidate_id}",
        params={
            "expected_revision": detail.json()["candidate"]["state_revision"],
            "client_operation_id": _client_operation_id(),
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "candidate_place_changed"
    async with session_factory() as s:
        candidate = await s.get(ExtractedPlaceCandidate, candidate_id)
        assert candidate.deleted_at is None
        assert candidate.matched_place_id == place_id

    # 영상 제외(force): 후보 soft delete + 매핑 삭제 + tombstone. legacy/persistent
    # 장소는 reference가 0이어도 origin 정책상 보존한다.
    excluded = await client.post(
        "/api/v1/destinations/videos/vid-ex-bulk/exclude",
        json={"reason": "관련 없는 영상"},
    )
    assert excluded.status_code == 200
    summary = excluded.json()
    assert summary["deleted_candidates"] == 1
    assert summary["deleted_mappings"] == 1
    assert summary["deleted_places"] == 0
    assert summary["preserved_places"] == 1
    assert summary["tombstoned_exports"] == 1

    async with session_factory() as s:
        candidate = await s.get(ExtractedPlaceCandidate, candidate_id)
        assert candidate is not None
        assert candidate.deleted_at is not None
        assert candidate.deletion_reason == "관련 없는 영상"
        assert candidate.matched_place_id is None
        assert await s.get(TravelPlace, place_id) is not None
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


# --- T-171: durable dirty outbox (스로틀/consume·순수 읽기·golden·안전망) ---


async def _outbox_ids(session_factory) -> set[int]:
    from sqlalchemy import select

    from ktc.models import ExportDirtyOutbox

    async with session_factory() as s:
        rows = (await s.execute(select(ExportDirtyOutbox.candidate_id))).scalars().all()
        return {int(r) for r in rows}


async def test_get_consumes_dirty_outbox_and_is_idempotent(client, session_factory):
    """공급 GET은 outbox에 실린 후보만 sync하고, 처리한 outbox 행을 consume(삭제)한다.
    변경이 없는 반복 GET은 outbox를 다시 채우지 않는다(폴링 churn 없음)."""
    candidate_id, _ = await _seed_ready_candidate(session_factory, video_id="ob1")
    # 시드가 후보를 dirty로 표시했다.
    assert await _outbox_ids(session_factory) == {candidate_id}

    snap = await client.get("/api/v1/features/snapshot")
    assert [i["candidate_id"] for i in snap.json()["items"]] == [candidate_id]
    # GET이 outbox를 consume했다.
    assert await _outbox_ids(session_factory) == set()

    # 변경 없는 반복 GET은 outbox를 다시 채우지 않는다(O(dirty)=0).
    again = await client.get("/api/v1/features/snapshot")
    assert [i["candidate_id"] for i in again.json()["items"]] == [candidate_id]
    assert await _outbox_ids(session_factory) == set()


async def test_get_is_pure_read_when_no_dirty(client, session_factory):
    """dirty가 없는 GET은 어떤 쓰기도 하지 않는다 — sequence 불변, `last_exported_at`
    write-commit 제거(항상 None)."""
    from sqlalchemy import select

    from ktc.models import FeatureExport

    await _seed_ready_candidate(session_factory, video_id="pr1")
    # 최초 GET: dirty consume + ledger 생성.
    await client.get("/api/v1/features/snapshot")
    ledger_before = await _ledger_state(session_factory)
    assert await _outbox_ids(session_factory) == set()

    # dirty 없는 반복 GET × 2: 쓰기 없음.
    await client.get("/api/v1/features/snapshot")
    await client.get("/api/v1/features/changes")

    assert await _ledger_state(session_factory) == ledger_before
    async with session_factory() as s:
        rows = (await s.execute(select(FeatureExport))).scalars().all()
        # GET은 더 이상 last_exported_at을 쓰지 않는다(순수 읽기).
        assert all(r.last_exported_at is None for r in rows)


async def test_empty_changes_page_releases_export_lock_before_later_tombstone(
    client,
    session_factory,
    monkeypatch,
):
    """빈 GET page commit까지 writer가 기다리고, 다음 cursor에는 tombstone이 남는다."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from ktc.services import feature_export_service

    candidate_id, place_id = await _seed_ready_candidate(
        session_factory,
        video_id="empty-page-lock-order",
    )
    first = await client.get("/api/v1/features/changes")
    cursor = first.json()["next_cursor"]
    assert cursor is not None
    assert await _outbox_ids(session_factory) == set()

    page_before_commit = asyncio.Event()
    release_page_commit = asyncio.Event()
    writer_waiting_for_export = asyncio.Event()
    writer_acquired_export = asyncio.Event()
    original_commit = AsyncSession.commit
    original_acquire = feature_export_service.acquire_feature_export_lock

    async def paused_page_commit(session):
        task = asyncio.current_task()
        if (
            task is not None
            and task.get_name() == "empty-feature-page"
            and not page_before_commit.is_set()
        ):
            page_before_commit.set()
            await release_page_commit.wait()
        return await original_commit(session)

    async def observed_export_lock(session):
        task = asyncio.current_task()
        if task is not None and task.get_name() == "place-delete-writer":
            writer_waiting_for_export.set()
        result = await original_acquire(session)
        if task is not None and task.get_name() == "place-delete-writer":
            writer_acquired_export.set()
        return result

    monkeypatch.setattr(AsyncSession, "commit", paused_page_commit)
    monkeypatch.setattr(
        feature_export_service,
        "acquire_feature_export_lock",
        observed_export_lock,
    )

    empty_page_task = asyncio.create_task(
        client.get("/api/v1/features/changes", params={"cursor": cursor}),
        name="empty-feature-page",
    )
    delete_task = None
    try:
        await asyncio.wait_for(page_before_commit.wait(), timeout=5)
        delete_task = asyncio.create_task(
            client.delete(f"/api/v1/destinations/{place_id}"),
            name="place-delete-writer",
        )
        await asyncio.wait_for(writer_waiting_for_export.wait(), timeout=5)
        # writer는 GET transaction이 export lock을 놓기 전에는 완료될 수 없다.
        try:
            await asyncio.wait_for(writer_acquired_export.wait(), timeout=0.2)
        except asyncio.TimeoutError:
            pass
        else:
            raise AssertionError("빈 feature page commit 전에 writer가 export lock을 획득함")
        assert delete_task.done() is False

        release_page_commit.set()
        empty_page = await asyncio.wait_for(empty_page_task, timeout=5)
        deleted = await asyncio.wait_for(delete_task, timeout=5)
    finally:
        release_page_commit.set()
        for task in (empty_page_task, delete_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (empty_page_task, delete_task) if task is not None),
            return_exceptions=True,
        )

    assert empty_page.status_code == 200
    assert empty_page.json()["items"] == []
    assert deleted.status_code == 200
    later = await client.get(
        "/api/v1/features/changes",
        params={"cursor": cursor},
    )
    assert later.status_code == 200
    assert [item["candidate_id"] for item in later.json()["items"]] == [
        candidate_id
    ]
    assert later.json()["items"][0]["operation"] == "tombstone"


async def test_isolated_reverse_requeues_dirty_after_core_dirty_was_consumed(
    client,
    session_factory,
    monkeypatch,
):
    """core dirty를 공급자가 먼저 소비해도 늦은 reverse 주소가 즉시 다시 발행된다.

    자동확정 core commit과 post-core reverse 사이의 실제 경합을 재현한다. 주소 UPDATE만
    commit하고 dirty를 다시 넣지 않으면 두 번째 changes는 비고, 전량 sync가 뒤늦게
    변경 1건을 찾아 golden 불변식이 깨진다.
    """
    from ktc.etl import geocode_service
    from ktc.models import TravelPlace
    from ktc.services import feature_export_service

    candidate_id, place_id = await _seed_ready_candidate(
        session_factory,
        video_id="reverse-dirty-race",
    )
    # core 자동확정 시점에는 주소를 얻지 못했지만 해당 변경의 dirty는 이미 있다.
    async with session_factory() as s:
        place = await s.get(TravelPlace, place_id)
        place.road_address = None
        place.official_address = None
        await s.commit()

    first = await client.get("/api/v1/features/changes")
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["items"][0]["place"]["address"] == {
        "official_address": None,
        "road_address": None,
        "legal_dong_code": None,
        "sido_code": None,
        "sigungu_code": None,
    }
    cursor = first_body["next_cursor"]
    assert await _outbox_ids(session_factory) == set()

    async def fake_reverse(_client, lat, lng):
        assert (lat, lng) == (33.5563, 126.7958)
        return {
            "road_address": "제주특별자치도 제주시 구좌읍 새도로",
            "parcel_address": "제주특별자치도 제주시 구좌읍 새지번",
        }

    monkeypatch.setattr(geocode_service, "reverse_with_vworld", fake_reverse)
    applied = await geocode_service._enrich_missing_addresses_isolated(
        session_factory,
        place_id,
        object(),
    )
    assert applied == {
        "road_address": "제주특별자치도 제주시 구좌읍 새도로",
        "parcel_address": "제주특별자치도 제주시 구좌읍 새지번",
    }
    assert await _outbox_ids(session_factory) == {candidate_id}

    second = await client.get(f"/api/v1/features/changes?cursor={cursor}")
    assert second.status_code == 200
    items = second.json()["items"]
    assert len(items) == 1
    assert items[0]["candidate_id"] == candidate_id
    assert items[0]["place"]["address"]["road_address"].endswith("새도로")
    assert items[0]["place"]["address"]["official_address"].endswith("새지번")
    assert await _outbox_ids(session_factory) == set()

    # dirty 경로가 이미 최신 fixpoint를 만들었으므로 전량 안전망은 무변경이어야 한다.
    async with session_factory() as s:
        changed = await feature_export_service.sync_feature_exports(s)
    assert changed == 0


async def test_reconcile_requeues_conflict_and_all_video_summary_exports(
    client,
    session_factory,
):
    """reconcile은 참조 후보 tombstone과 같은 영상의 새 summary를 한 dirty fixpoint로 만든다."""
    import json

    from ktc.etl import video_analysis_service
    from ktc.models import (
        ExtractedPlaceCandidate,
        FeatureExportStatus,
        GroundingStatus,
        MatchStatus,
        TravelPlace,
        VideoAnalysisRunState,
        VideoAnalysisRunType,
        YoutubeVideo,
        YoutubeVideoAnalysisRun,
    )
    from ktc.services import feature_export_service

    conflict_id, _ = await _seed_ready_candidate(
        session_factory,
        video_id="reconcile-dirty-race",
        place_name="충돌 장소",
    )
    async with session_factory() as s:
        video = await s.get(YoutubeVideo, "reconcile-dirty-race")
        video.gemini_url_summary_json = {
            "summary": "URL 분석 원본",
            "places": [{"name": "충돌 장소"}],
        }
        other_place = TravelPlace(
            name="같은 영상의 다른 장소",
            latitude=37.51,
            longitude=127.02,
            is_geocoded=True,
        )
        s.add(other_place)
        await s.flush()
        other = ExtractedPlaceCandidate(
            video_id=video.video_id,
            source_text="같은 영상의 독립 후보",
            ai_place_name="같은 영상의 다른 장소",
            match_status=MatchStatus.MATCHED.value,
            grounding_status=GroundingStatus.VERIFIED_RAW.value,
            matched_place_id=other_place.place_id,
            feature_export_status=FeatureExportStatus.READY.value,
        )
        run = YoutubeVideoAnalysisRun(
            video_id=video.video_id,
            run_type=VideoAnalysisRunType.RECONCILE.value,
            state=VideoAnalysisRunState.PENDING.value,
        )
        s.add_all([other, run])
        await s.flush()
        await feature_export_service.mark_candidates_dirty(
            s,
            [other.id],
            reason="seed_second_video_candidate",
        )
        await s.commit()
        other_id = other.id
        run_id = run.id

    first = await client.get("/api/v1/features/changes")
    assert first.status_code == 200
    assert {item["candidate_id"] for item in first.json()["items"]} == {
        conflict_id,
        other_id,
    }
    cursor = first.json()["next_cursor"]
    assert await _outbox_ids(session_factory) == set()

    def fake_llm(_prompt: str) -> str:
        return json.dumps(
            {
                "summary": "검수 후 확정한 새로운 영상 요약",
                "places": [
                    {
                        "name": "충돌 장소",
                        "decision": "conflict",
                        "transcript_candidate_ids": [conflict_id],
                        "needs_review_reason": "URL 근거와 자막 근거가 충돌한다.",
                    }
                ],
                "conflicts": ["장소 근거 충돌"],
            },
            ensure_ascii=False,
        )

    async with session_factory() as s:
        video = await s.get(YoutubeVideo, "reconcile-dirty-race")
        run = await s.get(YoutubeVideoAnalysisRun, run_id)
        result = await video_analysis_service.run_reconcile_analysis(
            s,
            video,
            run,
            llm=fake_llm,
            model="gemini-test",
        )
    assert result["state"] == VideoAnalysisRunState.DONE.value
    assert result["stale_input"] is False
    assert result["updated_review_candidates"] == 1
    # conflict 후보뿐 아니라 새 summary를 공유하는 미참조 후보도 재발행 대상이다.
    assert await _outbox_ids(session_factory) == {conflict_id, other_id}

    second = await client.get(f"/api/v1/features/changes?cursor={cursor}")
    assert second.status_code == 200
    by_candidate = {item["candidate_id"]: item for item in second.json()["items"]}
    assert by_candidate[conflict_id]["operation"] == "tombstone"
    assert by_candidate[other_id]["operation"] == "upsert"
    assert (
        by_candidate[other_id]["youtube"]["video_summary"]
        == "검수 후 확정한 새로운 영상 요약"
    )
    assert await _outbox_ids(session_factory) == set()

    async with session_factory() as s:
        changed = await feature_export_service.sync_feature_exports(s)
    assert changed == 0


async def test_wired_place_correction_marks_dirty_and_reissues(client, session_factory):
    """place 보정 라우트(correct_place)가 매칭 후보를 dirty로 표시해, 다음 GET에서
    payload 변경이 upsert로 재발행된다(직접 DB 조작이 아닌 wired 경로)."""
    candidate_id, place_id = await _seed_ready_candidate(
        session_factory, video_id="corr1"
    )
    first = await client.get("/api/v1/features/changes")
    cursor = first.json()["next_cursor"]
    assert await _outbox_ids(session_factory) == set()

    resp = await client.post(
        f"/api/v1/destinations/{place_id}/correct",
        json={"name": "월정리 해수욕장(보정)"},
    )
    assert resp.status_code == 200

    changes = await client.get(f"/api/v1/features/changes?cursor={cursor}")
    items = changes.json()["items"]
    assert [i["operation"] for i in items] == ["upsert"]
    assert items[0]["export_id"] == f"ytpc_{candidate_id}"
    assert items[0]["place"]["name"] == "월정리 해수욕장(보정)"
    await _assert_full_sync_is_stable(session_factory)


async def test_place_delete_route_tombstones_via_dirty(client, session_factory):
    """장소 삭제 라우트가 되돌린 후보를 dirty로 표시하고, sync_dirty가 tombstone을
    발행한다(전량 sync 없이 dirty 경로로 회수)."""
    candidate_id, place_id = await _seed_ready_candidate(
        session_factory, video_id="pd1"
    )
    first = await client.get("/api/v1/features/changes")
    assert [i["operation"] for i in first.json()["items"]] == ["upsert"]
    cursor = first.json()["next_cursor"]

    deleted = await client.delete(f"/api/v1/destinations/{place_id}")
    assert deleted.status_code == 200

    changes = await client.get(f"/api/v1/features/changes?cursor={cursor}")
    items = changes.json()["items"]
    assert [i["operation"] for i in items] == ["tombstone"]
    assert items[0]["export_id"] == f"ytpc_{candidate_id}"

    snapshot = await client.get("/api/v1/features/snapshot")
    assert snapshot.json()["items"] == []
    await _assert_full_sync_is_stable(session_factory)


async def test_dirty_sync_result_matches_full_sync_golden(client, session_factory):
    """golden 동일성: 여러 wired 변경(유지·삭제·place 보정)을 dirty 경로로 반영한 뒤,
    전량 sync를 돌려도 아무 변화가 없다(dirty 결과 == 전량 sync fixpoint)."""
    from ktc.services import feature_export_service

    a_id, _ = await _seed_ready_candidate(
        session_factory, video_id="gold-a", place_name="장소 A"
    )
    b_id, b_place = await _seed_ready_candidate(
        session_factory, video_id="gold-b", place_name="장소 B"
    )
    c_id, c_place = await _seed_ready_candidate(
        session_factory, video_id="gold-c", place_name="장소 C"
    )

    # 최초 노출(dirty consume → upsert 3건).
    await client.get("/api/v1/features/changes")

    # b: 장소 삭제 → 후보 needs_review 복귀 + tombstone(확정 후보에도 동작하는 wired
    # tombstone 경로. T-183가 개별 후보 삭제에 needs_review 선행조건을 추가했으므로 확정
    # 후보의 tombstone은 장소 삭제로 만든다).
    assert (
        await client.delete(f"/api/v1/destinations/{b_place}")
    ).status_code == 200
    # c: place 보정(→ upsert 재발행).
    assert (
        await client.post(
            f"/api/v1/destinations/{c_place}/correct",
            json={"name": "장소 C(보정)"},
        )
    ).status_code == 200

    # dirty 경로로 모두 반영.
    await client.get("/api/v1/features/changes")
    await client.get("/api/v1/features/snapshot")
    assert await _outbox_ids(session_factory) == set()

    ledger_dirty = await _ledger_state(session_factory)
    # 전량 sync를 돌려도 변화 0(golden 동일) — dirty 결과가 전량 sync의 fixpoint다.
    async with session_factory() as s:
        changed = await feature_export_service.sync_feature_exports(s)
    assert changed == 0
    assert await _ledger_state(session_factory) == ledger_dirty

    # 활성 snapshot은 a·c만(b는 tombstone).
    snap = await client.get("/api/v1/features/snapshot")
    active_ids = sorted(i["candidate_id"] for i in snap.json()["items"])
    assert active_ids == sorted([a_id, c_id])


async def test_safety_net_full_sync_heals_unwired_ready_candidate(
    client, session_factory
):
    """미배선 자가 치유: dirty 표시를 우회해 export 대상이 된 후보는 GET(sync_dirty)에는
    안 보이다가, 안전망 전량 sync가 ledger로 surface한다."""
    from ktc.services import feature_export_service

    candidate_id, _ = await _seed_ready_candidate(
        session_factory, video_id="unwired1", mark_dirty=False
    )
    # dirty가 없으므로 GET에는 나타나지 않는다.
    assert await _outbox_ids(session_factory) == set()
    snap = await client.get("/api/v1/features/snapshot")
    assert snap.json()["items"] == []

    # 안전망 전량 sync가 미배선 후보를 보정한다.
    async with session_factory() as s:
        changed = await feature_export_service.sync_feature_exports(s)
    assert changed == 1

    healed = await client.get("/api/v1/features/snapshot")
    assert [i["candidate_id"] for i in healed.json()["items"]] == [candidate_id]
    await _assert_full_sync_is_stable(session_factory)


async def test_golden_merge_backfill_dirties_target_resident_candidate(
    client, session_factory
):
    """golden(co-매칭): merge가 target place 필드를 backfill하면, target에 이미 매칭돼 있던
    후보(C_target)의 export payload도 바뀐다. 그 후보를 dirty로 표시하지 않으면 전량 sync가
    변화를 감지(dirty != full)한다 — 표시하면 merge 직후 전량 sync가 fixpoint(changed==0)."""
    from ktc.models import TravelPlace
    from ktc.services import feature_export_service, place_service

    src_id, src_place = await _seed_ready_candidate(
        session_factory, video_id="mrg-src", place_name="병합 출처"
    )
    tgt_id, tgt_place = await _seed_ready_candidate(
        session_factory, video_id="mrg-tgt", place_name="병합 대상"
    )
    # target place가 description을 결여하도록 비운다(merge backfill이 실제로 채우게).
    async with session_factory() as s:
        tgt = await s.get(TravelPlace, tgt_place)
        tgt.description = None
        tgt.gemini_enriched_description = None
        await s.commit()

    # 최초 노출(dirty consume → upsert 2건). C_target ledger는 description=None로 고정.
    await client.get("/api/v1/features/changes")
    assert await _outbox_ids(session_factory) == set()

    # source→target 병합: target.description을 source에서 backfill.
    async with session_factory() as s:
        await place_service.merge_places(
            s, source_place_id=src_place, target_place_id=tgt_place
        )
    # moved 후보(src)와 target-resident 후보(tgt)가 **모두** dirty여야 한다.
    assert await _outbox_ids(session_factory) == {src_id, tgt_id}

    # dirty 반영 후 전량 sync fixpoint(golden 동일).
    await client.get("/api/v1/features/changes")
    await client.get("/api/v1/features/snapshot")
    assert await _outbox_ids(session_factory) == set()

    ledger_dirty = await _ledger_state(session_factory)
    async with session_factory() as s:
        changed = await feature_export_service.sync_feature_exports(s)
    assert changed == 0
    assert await _ledger_state(session_factory) == ledger_dirty

    # target-resident 후보의 payload가 backfill된 description을 반영한다.
    snap = await client.get("/api/v1/features/snapshot")
    by_cid = {i["candidate_id"]: i for i in snap.json()["items"]}
    assert by_cid[tgt_id]["place"]["description"] == (
        "에메랄드빛 바다와 카페가 가까운 제주 동쪽 해변"
    )


async def test_golden_resolve_reuse_dirties_co_matched_candidate(
    client, session_factory
):
    """golden(co-매칭): 한 place에 후보 2개가 매칭될 때, resolve 재사용이 place.category를
    채우면 이미 매칭돼 있던 co-매칭 후보도 stale해진다. 그 후보를 dirty로 표시하면 전량 sync가
    fixpoint(changed==0)."""
    from sqlalchemy import select

    from ktc.etl import category_catalog
    from ktc.models import (
        ExtractedPlaceCandidate,
        FeatureExportStatus,
        GroundingStatus,
        MatchStatus,
        TravelPlace,
    )
    from ktc.services import feature_export_service

    # 1) place P + co-매칭 확정 후보 C1(seed). category_code_suggestion을 UNKNOWN 센티넬로
    # 두어 재사용 category fill이 트리거되게 한다(category·category_code_suggestion 모두
    # NOT NULL이라 None 대신 UNKNOWN 코드를 쓴다).
    c1_id, p_place = await _seed_ready_candidate(
        session_factory, video_id="reuse-co", place_name="재사용 장소"
    )
    async with session_factory() as s:
        p = await s.get(TravelPlace, p_place)
        p.category_code_suggestion = category_catalog.UNKNOWN_CATEGORY_CODE
        await s.commit()

    # 2) 같은 place에 match_existing으로 확정될 needs_review 후보 C2(카테고리 코드 evidence).
    async with session_factory() as s:
        s.add(
            ExtractedPlaceCandidate(
                video_id="reuse-co",
                source_channel_id="chan-reuse-co",
                source_text="같은 장소 다른 후보",
                ai_place_name="재사용 장소",
                match_status=MatchStatus.NEEDS_REVIEW,
                grounding_status=GroundingStatus.VERIFIED_RAW.value,
                feature_export_status=FeatureExportStatus.PENDING.value,
                provider_evidence_json={"transcript": {"category_code": "01050100"}},
            )
        )
        await s.commit()
    async with session_factory() as s:
        c2_id = (
            await s.execute(
                select(ExtractedPlaceCandidate.id).where(
                    ExtractedPlaceCandidate.match_status == MatchStatus.NEEDS_REVIEW
                )
            )
        ).scalar_one()

    # 3) 최초 노출(C1 upsert, category 없음).
    await client.get("/api/v1/features/changes")
    assert await _outbox_ids(session_factory) == set()

    # 4) C2를 P에 match_existing 확정 → P.category 채워짐 → C1(co-매칭)도 dirty.
    resolved = await client.post(
        f"/api/v1/destinations/unmatched/{c2_id}/resolve",
        json={
            "client_operation_id": _client_operation_id(),
            "expected_revision": 1,
            "action": "match_existing",
            "place_id": p_place,
        },
    )
    assert resolved.status_code == 200
    assert await _outbox_ids(session_factory) == {c1_id, c2_id}

    # 5) dirty 반영 후 전량 sync fixpoint(golden 동일).
    await client.get("/api/v1/features/changes")
    await client.get("/api/v1/features/snapshot")
    assert await _outbox_ids(session_factory) == set()

    ledger_dirty = await _ledger_state(session_factory)
    async with session_factory() as s:
        changed = await feature_export_service.sync_feature_exports(s)
    assert changed == 0
    assert await _ledger_state(session_factory) == ledger_dirty

    # C1의 payload가 채워진 카테고리 코드를 반영한다.
    snap = await client.get("/api/v1/features/snapshot")
    by_cid = {i["candidate_id"]: i for i in snap.json()["items"]}
    assert by_cid[c1_id]["place"]["category_code_suggestion"] == "01050100"
