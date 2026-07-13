"""T-177 목록 공통 envelope·cursor 완결성 통합 테스트."""

from __future__ import annotations

import base64
import json

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from ktc.core.database import get_repeatable_read_session, get_session
from ktc.models import (
    CrawlRun,
    ExtractedPlaceCandidate,
    GroundingStatus,
    MatchStatus,
    RunSource,
    RunState,
    TravelPlace,
    VideoPlaceMapping,
    YoutubeChannel,
    YoutubeVideo,
)
from ktc.services import crawl_run_service
from main import app


@pytest_asyncio.fixture
async def client(session_factory):
    async def override_get_session():
        async with session_factory() as test_session:
            yield test_session

    async def override_repeatable_read_session():
        async with session_factory() as test_session:
            yield test_session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[
        get_repeatable_read_session
    ] = override_repeatable_read_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


def _assert_envelope(body: dict) -> None:
    assert set(body) == {
        "items",
        "next_cursor",
        "has_more",
        "total",
        "newest_id",
        "newer_than",
    }


async def test_runs_501_keyset_snapshot_new_count_and_filter_guard(
    client, session
):
    session.add_all(
        [
            CrawlRun(
                job_type="harvest",
                source=RunSource.WEB,
                state=RunState.DONE,
                progress=1.0,
            )
            for _ in range(501)
        ]
    )
    await session.commit()

    first = await client.get("/api/v1/runs?limit=100&job_types=harvest")
    assert first.status_code == 200
    first_body = first.json()
    _assert_envelope(first_body)
    assert first_body["total"] == 501
    assert first_body["newest_id"] == 501
    assert first_body["has_more"] is True
    assert [int(item["job_id"]) for item in first_body["items"]] == list(
        range(501, 401, -1)
    )

    cursor = first_body["next_cursor"]
    seen = [int(item["job_id"]) for item in first_body["items"]]
    # 첫 page 뒤 insert되어도 기존 cursor snapshot에는 섞이지 않는다.
    session.add(
        CrawlRun(
            job_type="harvest",
            source=RunSource.WEB,
            state=RunState.DONE,
            progress=1.0,
        )
    )
    await session.commit()
    while cursor:
        response = await client.get(
            "/api/v1/runs",
            params={
                "limit": 100,
                "job_types": "harvest",
                "cursor": cursor,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 501
        seen.extend(int(item["job_id"]) for item in body["items"])
        cursor = body["next_cursor"]
        if not body["has_more"]:
            assert cursor is None
    assert seen == list(range(501, 0, -1))
    assert len(seen) == len(set(seen))

    fresh = await client.get(
        "/api/v1/runs?limit=1&job_types=harvest&newer_than_id=501"
    )
    assert fresh.json()["newest_id"] == 502
    assert fresh.json()["newer_than"] == 1

    mismatch = await client.get(
        "/api/v1/runs",
        params={"limit": 10, "state": "pending", "cursor": first_body["next_cursor"]},
    )
    assert mismatch.status_code == 400
    assert (await client.get("/api/v1/runs?cursor=not-a-cursor")).status_code == 400
    non_ascii_cursor = base64.urlsafe_b64encode(
        json.dumps(
            {"v": 1, "f": "가" * 32, "w": 501, "k": [401]},
            ensure_ascii=False,
        ).encode("utf-8")
    ).decode("ascii")
    assert (
        await client.get("/api/v1/runs", params={"cursor": non_ascii_cursor})
    ).status_code == 400
    raw_cursor = first_body["next_cursor"]
    cursor_payload = json.loads(
        base64.urlsafe_b64decode(raw_cursor + "=" * (-len(raw_cursor) % 4))
    )
    cursor_payload["w"] = 2_147_483_648
    oversized_watermark = base64.urlsafe_b64encode(
        json.dumps(cursor_payload).encode("utf-8")
    ).decode("ascii")
    assert (
        await client.get(
            "/api/v1/runs",
            params={"job_types": "harvest", "cursor": oversized_watermark},
        )
    ).status_code == 400
    assert (
        await client.get("/api/v1/runs?newer_than_id=2147483648")
    ).status_code == 422
    assert (
        await client.get("/api/v1/runs", params={"cursor": "a" * 4097})
    ).status_code == 422
    assert (
        await client.get("/api/v1/runs", params={"state": "x" * 33})
    ).status_code == 422
    assert (
        await client.get(
            "/api/v1/runs", params={"job_types": ",".join(["a"] * 11)}
        )
    ).status_code == 400
    run_detail = await client.get("/api/v1/runs/1")
    assert run_detail.status_code == 200
    assert run_detail.json()["job_id"] == "1"


async def test_runs_exact_limit_and_live_total_after_state_transition(client, session):
    session.add_all(
        [
            CrawlRun(
                job_type="harvest",
                source=RunSource.WEB,
                state=RunState.PENDING,
                progress=0.0,
            )
            for _ in range(2)
        ]
    )
    await session.commit()
    exact = await client.get("/api/v1/runs?state=pending&limit=2")
    assert exact.json()["total"] == 2
    assert exact.json()["has_more"] is False
    assert exact.json()["next_cursor"] is None

    first = await client.get("/api/v1/runs?state=pending&limit=1")
    first_body = first.json()
    assert first_body["has_more"] is True
    oldest = await session.get(CrawlRun, 1)
    assert oldest is not None
    oldest.state = RunState.RUNNING
    await session.commit()

    second = await client.get(
        "/api/v1/runs",
        params={
            "state": "pending",
            "limit": 1,
            "cursor": first_body["next_cursor"],
        },
    )
    assert second.json()["items"] == []
    assert second.json()["total"] == 1
    assert second.json()["has_more"] is False


async def test_list_service_uses_repeatable_read_snapshot(session):
    session.add(
        CrawlRun(
            job_type="harvest",
            source=RunSource.WEB,
            state=RunState.PENDING,
            progress=0.0,
        )
    )
    await session.commit()
    assert session.in_transaction() is False
    await crawl_run_service.list_runs_page(session)
    isolation = await session.scalar(text("SHOW transaction_isolation"))
    assert isolation == "repeatable read"


async def test_unmatched_301_keyset_filter_guard_and_page_outside_detail(
    client, session
):
    session.add(
        YoutubeVideo(
            video_id="queue-video",
            title="검수 영상",
            url="https://example.invalid/queue",
            channel_id="queue-channel",
            source_search_query="검수 검색어",
        )
    )
    await session.flush()
    session.add_all(
        [
            ExtractedPlaceCandidate(
                video_id="queue-video",
                source_text=f"근거 {index}",
                ai_place_name=f"후보 {index}",
                match_status=MatchStatus.NEEDS_REVIEW,
            )
            for index in range(301)
        ]
    )
    await session.commit()

    first = await client.get(
        "/api/v1/destinations/unmatched?limit=300&keyword=검수%20검색어"
    )
    assert first.status_code == 200
    body = first.json()
    _assert_envelope(body)
    assert body["total"] == 301
    assert body["newest_id"] == 301
    assert body["has_more"] is True
    assert [item["id"] for item in body["items"]] == list(range(301, 1, -1))

    second = await client.get(
        "/api/v1/destinations/unmatched",
        params={
            "limit": 300,
            "keyword": "검수 검색어",
            "cursor": body["next_cursor"],
            "newer_than_id": 300,
        },
    )
    second_body = second.json()
    assert [item["id"] for item in second_body["items"]] == [1]
    assert second_body["total"] == 301
    assert second_body["newer_than"] == 1
    assert second_body["has_more"] is False
    assert second_body["next_cursor"] is None

    mismatch = await client.get(
        "/api/v1/destinations/unmatched",
        params={"limit": 300, "keyword": "다른 검색어", "cursor": body["next_cursor"]},
    )
    assert mismatch.status_code == 400
    detail = await client.get("/api/v1/destinations/candidates/1/detail")
    assert detail.status_code == 200
    assert detail.json()["candidate"]["id"] == 1


async def test_unmatched_lightweight_payload_reason_priority_and_filters(
    client, session
):
    session.add(
        YoutubeChannel(channel_id="reason-channel", title="정규 검수 채널")
    )
    session.add(
        YoutubeVideo(
            video_id="reason-video",
            title="사유 판정 검수 영상",
            url="https://example.invalid/reason",
            channel_id="reason-channel",
            channel_name="레거시 채널명",
        )
    )
    await session.flush()

    cases = [
        (
            # raw grounding 미확인 transcript 후보(T-165) — 최우선 사유 ungrounded.
            "원문 불일치",
            "transcript",
            {"transcript": {"grounding_status": "unverified"}},
            None,
            True,
            "ungrounded",
        ),
        (
            "이름 불일치",
            "transcript",
            {"geocoding": {"decision": {"reason": "ambiguous"}}},
            "nearby_place_name_mismatch",
            True,
            "name_mismatch",
        ),
        (
            "지역 불일치",
            "transcript",
            None,
            "region_mismatch",
            True,
            "region_mismatch",
        ),
        (
            "출처 충돌",
            "reconcile",
            {"reconcile": {"decision": " Conflict "}},
            None,
            True,
            "source_conflict",
        ),
        (
            "출처 신뢰도 낮음",
            "reconcile",
            {"reconcile": {"decision": "LOW_CONFIDENCE"}},
            None,
            True,
            "source_low_confidence",
        ),
        (
            "출처 판정 불확실",
            "reconcile",
            {
                "reconcile": {
                    "decision": "matched",
                    "needs_review_reason": "출처 근거를 다시 확인해야 함",
                }
            },
            None,
            True,
            "source_uncertain",
        ),
        (
            "출처 점수 불확실",
            "reconcile",
            {"reconcile": {"decision": "matched", "confidence_score": 0.4}},
            None,
            True,
            "source_uncertain",
        ),
        (
            "손상된 출처 점수",
            "reconcile",
            {"reconcile": {"decision": "matched", "confidence_score": "bad"}},
            None,
            True,
            "extraction_only",
        ),
        (
            "객체 출처 점수",
            "reconcile",
            {
                "reconcile": {
                    "decision": "matched",
                    "confidence_score": {"invalid": True},
                }
            },
            None,
            True,
            "extraction_only",
        ),
        (
            "거대 출처 점수",
            "reconcile",
            {
                "reconcile": {
                    "decision": "matched",
                    "confidence_score": 10**1000,
                }
            },
            None,
            True,
            "extraction_only",
        ),
        (
            "모호한 해외 후보",
            "transcript",
            {"geocoding": {"decision": {"reason": "ambiguous"}}},
            None,
            False,
            "ambiguous",
        ),
        (
            "결과 없는 설명 후보",
            "description",
            {"geocoding": {"decision": {"reason": "no_result"}}},
            None,
            True,
            "no_result",
        ),
        (
            "미정제 단일 후보",
            "transcript",
            {
                "geocoding": {
                    "decision": {"reason": "vworld_unrefined_single"}
                }
            },
            None,
            True,
            "vworld_unrefined_single",
        ),
        ("해외 후보", "transcript", None, None, False, "foreign"),
        ("설명 후보", "description", None, None, True, "description_only"),
        ("시각 후보", "visual", None, None, True, "visual_only"),
        (
            "provider 누락",
            "transcript",
            {"geocoding": {}, "large_blob": "x" * 100_000},
            None,
            True,
            "provider_missing",
        ),
        (
            "정상 지오코딩 근거",
            "transcript",
            {"geocoding": {"decision": {"reason": "single_result"}}},
            None,
            True,
            "extraction_only",
        ),
        (
            "미래 지오코딩 근거",
            "transcript",
            {"geocoding": {"decision": {"reason": "future_reason"}}},
            None,
            True,
            "extraction_only",
        ),
        ("추출 후보", "transcript", None, None, True, "extraction_only"),
    ]
    session.add_all(
        [
            ExtractedPlaceCandidate(
                video_id="reason-video",
                source_kind=source_kind,
                source_text=f"긴 목록 제외 근거 {name}",
                ai_place_name=name,
                match_status=MatchStatus.NEEDS_REVIEW,
                confidence_score=0.83 if expected == "extraction_only" else None,
                provider_evidence_json=evidence,
                review_note=review_note,
                is_domestic=is_domestic,
                # ungrounded 사유를 테스트하는 케이스만 미확인으로 두고, 그 외 transcript
                # 케이스는 verified_raw로 두어 각자의 의도한 사유를 격리 검증한다(T-165).
                grounding_status=(
                    GroundingStatus.UNVERIFIED.value
                    if expected == "ungrounded"
                    else GroundingStatus.VERIFIED_RAW.value
                ),
            )
            for (
                name,
                source_kind,
                evidence,
                review_note,
                is_domestic,
                expected,
            ) in cases
        ]
    )
    invalid_scores = {
        "NaN 신뢰도": float("nan"),
        "무한 신뢰도": float("inf"),
        "음수 신뢰도": -0.1,
        "초과 신뢰도": 1.1,
    }
    session.add_all(
        [
            ExtractedPlaceCandidate(
                video_id="reason-video",
                source_text=name,
                ai_place_name=name,
                match_status=MatchStatus.NEEDS_REVIEW,
                confidence_score=score,
            )
            for name, score in invalid_scores.items()
        ]
    )
    await session.commit()

    response = await client.get("/api/v1/destinations/unmatched")
    assert response.status_code == 200
    body = response.json()
    by_name = {item["ai_place_name"]: item for item in body["items"]}
    assert {
        name: by_name[name]["queue_reason"]
        for name, *_rest in cases
    } == {name: expected for name, *_middle, expected in cases}
    extraction = by_name["추출 후보"]
    assert extraction["video_title"] == "사유 판정 검수 영상"
    assert extraction["channel_title"] == "정규 검수 채널"
    assert extraction["confidence_score"] == 0.83
    assert extraction["source_kind"] == "transcript"
    assert extraction["created_at"].endswith("+00:00")
    assert "provider_evidence_json" not in extraction
    assert "source_text" not in extraction
    assert len(response.content) < 30_000
    assert all(by_name[name]["confidence_score"] is None for name in invalid_scores)

    reason_filtered = await client.get(
        "/api/v1/destinations/unmatched",
        params={"reason": "name_mismatch"},
    )
    assert reason_filtered.status_code == 200
    assert reason_filtered.json()["total"] == 1
    assert [item["ai_place_name"] for item in reason_filtered.json()["items"]] == [
        "이름 불일치"
    ]

    combined = await client.get(
        "/api/v1/destinations/unmatched",
        params={"reason": "no_result", "source_kind": "description"},
    )
    assert combined.status_code == 200
    assert combined.json()["total"] == 1
    assert combined.json()["items"][0]["ai_place_name"] == "결과 없는 설명 후보"

    first_transcript = await client.get(
        "/api/v1/destinations/unmatched",
        params={"limit": 1, "source_kind": "transcript"},
    )
    assert first_transcript.json()["has_more"] is True
    mismatched_cursor = await client.get(
        "/api/v1/destinations/unmatched",
        params={
            "limit": 1,
            "source_kind": "visual",
            "cursor": first_transcript.json()["next_cursor"],
        },
    )
    assert mismatched_cursor.status_code == 400
    assert (
        await client.get(
            "/api/v1/destinations/unmatched", params={"reason": "not-a-reason"}
        )
    ).status_code == 422
    assert (
        await client.get(
            "/api/v1/destinations/unmatched", params={"source_kind": "unknown"}
        )
    ).status_code == 422


async def test_destinations_501_stable_tie_break_and_page_outside_detail(
    client, session
):
    session.add_all(
        [
            TravelPlace(
                name="동일 장소명",
                category="동일 카테고리",
                latitude=35.0 + index * 0.00001,
                longitude=129.0,
                is_geocoded=True,
            )
            for index in range(501)
        ]
    )
    await session.commit()

    first = await client.get(
        "/api/v1/destinations?sort=category&limit=500&newer_than_id=498"
    )
    assert first.status_code == 200
    body = first.json()
    _assert_envelope(body)
    assert body["total"] == 501
    assert body["newest_id"] == 501
    assert body["newer_than"] == 3
    assert body["has_more"] is True
    assert [item["place_id"] for item in body["items"]] == list(
        range(501, 1, -1)
    )

    second = await client.get(
        "/api/v1/destinations",
        params={
            "sort": "category",
            "limit": 500,
            "cursor": body["next_cursor"],
        },
    )
    second_body = second.json()
    assert [item["place_id"] for item in second_body["items"]] == [1]
    assert second_body["total"] == 501
    assert second_body["has_more"] is False
    assert second_body["next_cursor"] is None
    detail = await client.get("/api/v1/destinations/1/detail")
    assert detail.status_code == 200
    assert detail.json()["place"]["place_id"] == 1

    mismatch = await client.get(
        "/api/v1/destinations",
        params={"sort": "name", "limit": 500, "cursor": body["next_cursor"]},
    )
    assert mismatch.status_code == 400
    assert (
        await client.get("/api/v1/destinations", params={"q": "가" * 256})
    ).status_code == 422

    mention_page = await client.get(
        "/api/v1/destinations?sort=mention_count&limit=500"
    )
    mention_cursor = mention_page.json()["next_cursor"]
    mention_payload = json.loads(
        base64.urlsafe_b64decode(
            mention_cursor + "=" * (-len(mention_cursor) % 4)
        )
    )
    mention_payload["k"][0] = 1
    forged_count_cursor = base64.urlsafe_b64encode(
        json.dumps(mention_payload, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    assert (
        await client.get(
            "/api/v1/destinations",
            params={"sort": "mention_count", "cursor": forged_count_cursor},
        )
    ).status_code == 400


async def test_themes_301_flat_envelope_and_mapping_watermark(client, session):
    rows: list[tuple[YoutubeVideo, TravelPlace, str]] = []
    for index in range(301):
        channel_id = f"theme-channel-{index:03d}"
        video_id = f"theme-video-{index:03d}"
        channel = YoutubeChannel(channel_id=channel_id, title=f"채널 {index:03d}")
        video = YoutubeVideo(
            video_id=video_id,
            title=f"테마 영상 {index:03d}",
            url=f"https://example.invalid/{video_id}",
            channel_id=channel_id,
        )
        place = TravelPlace(
            name=f"테마 장소 {index:03d}",
            latitude=33.0 + index * 0.00001,
            longitude=126.0,
            is_geocoded=True,
        )
        session.add_all([channel, video, place])
        rows.append((video, place, channel_id))
    await session.flush()
    for video, place, channel_id in rows:
        session.add(
            VideoPlaceMapping(
                video_id=video.video_id,
                place_id=place.place_id,
                source_channel_id=channel_id,
                ai_summary="테마 근거",
            )
        )
    await session.commit()

    first = await client.get("/api/v1/themes?limit=300&newer_than_id=300")
    assert first.status_code == 200
    body = first.json()
    _assert_envelope(body)
    assert body["total"] == 301
    assert body["newest_id"] == 301
    assert body["newer_than"] == 1
    assert body["has_more"] is True
    assert all(item["kind"] == "channel" for item in body["items"])

    second = await client.get(
        "/api/v1/themes",
        params={"limit": 300, "cursor": body["next_cursor"]},
    )
    second_body = second.json()
    assert second_body["total"] == 301
    assert len(second_body["items"]) == 1
    assert second_body["items"][0]["value"] == "theme-channel-300"
    assert second_body["has_more"] is False
    assert second_body["next_cursor"] is None

    cursor_payload = json.loads(
        base64.urlsafe_b64decode(
            body["next_cursor"] + "=" * (-len(body["next_cursor"]) % 4)
        )
    )
    cursor_payload["k"][1] = 0
    zero_count_cursor = base64.urlsafe_b64encode(
        json.dumps(cursor_payload, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    assert (
        await client.get("/api/v1/themes", params={"cursor": zero_count_cursor})
    ).status_code == 400
    cursor_payload["k"][1] = -1
    cursor_payload["w"] = 0
    zero_watermark_cursor = base64.urlsafe_b64encode(
        json.dumps(cursor_payload, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    assert (
        await client.get("/api/v1/themes", params={"cursor": zero_watermark_cursor})
    ).status_code == 400

    detail = await client.get(
        "/api/v1/themes/places?kind=channel&value=theme-channel-300"
    )
    assert detail.status_code == 200
    assert detail.json()["theme"]["value"] == "theme-channel-300"
    assert detail.json()["theme"]["poi_count"] == 1

    # 기존 테마에 mapping만 추가되면 새 테마 수는 늘지 않는다.
    session.add(
        YoutubeVideo(
            video_id="theme-video-existing-extra",
            title="기존 테마 추가 영상",
            url="https://example.invalid/theme-video-existing-extra",
            channel_id="theme-channel-000",
        )
    )
    await session.flush()
    session.add(
        VideoPlaceMapping(
            video_id="theme-video-existing-extra",
            place_id=1,
            source_channel_id="theme-channel-000",
            ai_summary="기존 테마 추가 근거",
        )
    )
    await session.commit()
    updated = await client.get("/api/v1/themes?limit=500&newer_than_id=301")
    assert updated.json()["newest_id"] == 302
    assert updated.json()["newer_than"] == 0

    # 새 kind/value의 첫 mapping만 새 테마 1건으로 센다.
    new_channel = YoutubeChannel(channel_id="theme-channel-new", title="새 채널")
    new_video = YoutubeVideo(
        video_id="theme-video-new",
        title="새 테마 영상",
        url="https://example.invalid/theme-video-new",
        channel_id="theme-channel-new",
    )
    new_place = TravelPlace(
        name="새 테마 장소",
        latitude=34.0,
        longitude=127.0,
        is_geocoded=True,
    )
    session.add_all([new_channel, new_video, new_place])
    await session.flush()
    session.add(
        VideoPlaceMapping(
            video_id="theme-video-new",
            place_id=new_place.place_id,
            source_channel_id="theme-channel-new",
            ai_summary="새 테마 근거",
        )
    )
    await session.commit()
    created = await client.get("/api/v1/themes?limit=500&newer_than_id=301")
    assert created.json()["newest_id"] == 303
    assert created.json()["newer_than"] == 1


async def test_feature_list_contract_remains_unchanged(client):
    snapshot = await client.get("/api/v1/features/snapshot")
    changes = await client.get("/api/v1/features/changes")
    assert set(snapshot.json()) == {"items", "next_cursor", "has_more"}
    assert set(changes.json()) == {"items", "next_cursor", "has_more"}
