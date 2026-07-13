"""T-177 목록 공통 envelope·cursor 완결성 통합 테스트."""

from __future__ import annotations

import base64
import json
from time import perf_counter

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
    YoutubePlaylist,
    YoutubeVideo,
    utcnow,
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
    assert detail.json()["list_item"]["id"] == 1


async def test_unmatched_oldest_501_snapshot_and_all_filter_new_count(
    client, session
):
    session.add_all(
        [
            YoutubeChannel(channel_id="queue-channel", title="검수 채널"),
            YoutubeChannel(channel_id="other-channel", title="다른 채널"),
        ]
    )
    session.add(
        YoutubePlaylist(
            playlist_id="queue-playlist",
            channel_id="queue-channel",
            title="검수 재생목록",
        )
    )
    session.add_all(
        [
            YoutubeVideo(
                video_id="queue-video",
                title="검수 영상",
                url="https://example.invalid/queue",
                channel_id="queue-channel",
                source_search_query="검수 검색어",
            ),
            YoutubeVideo(
                video_id="other-video",
                title="다른 영상",
                url="https://example.invalid/other",
                channel_id="other-channel",
                source_search_query="다른 검색어",
            ),
        ]
    )
    await session.flush()
    session.add_all(
        [
            ExtractedPlaceCandidate(
                video_id="queue-video",
                source_channel_id="queue-channel",
                source_playlist_id="queue-playlist",
                source_kind="transcript",
                source_text=f"서울 근거 {index}",
                ai_place_name=f"서울 후보 {index}",
                match_status=MatchStatus.NEEDS_REVIEW,
                grounding_status=GroundingStatus.VERIFIED_RAW.value,
                is_domestic=True,
            )
            for index in range(501)
        ]
    )
    await session.commit()

    filters = {
        "q": "서울",
        "sort": "oldest",
        "is_domestic": "true",
        "status": "needs_review",
        "channel_id": "queue-channel",
        "playlist_id": "queue-playlist",
        "keyword": "검수 검색어",
        "reason": "extraction_only",
        "source_kind": "transcript",
        "grounding": "verified_raw",
    }
    first = await client.get(
        "/api/v1/destinations/unmatched",
        params={**filters, "limit": 300},
    )
    assert first.status_code == 200
    body = first.json()
    assert body["total"] == 501
    assert body["newest_id"] == 501
    assert body["has_more"] is True
    assert [item["id"] for item in body["items"]] == list(range(1, 301))
    assert {item["grounding_status"] for item in body["items"]} == {
        GroundingStatus.VERIFIED_RAW.value
    }

    page_out_detail = await client.get(
        "/api/v1/destinations/candidates/501/detail"
    )
    assert page_out_detail.status_code == 200
    detail_body = page_out_detail.json()
    assert detail_body["list_item"]["id"] == 501
    assert detail_body["candidate"]["source_channel_id"] == "queue-channel"
    assert detail_body["candidate"]["source_playlist_id"] == "queue-playlist"
    assert detail_body["video"]["channel_id"] == "queue-channel"
    assert detail_body["video"]["source_search_query"] == "검수 검색어"

    # cursor snapshot 뒤에는 filter별 비일치 신규 행도 함께 만든다. newer_than은
    # q/status/is_domestic/출처/사유 전체가 같은 한 행만 세어야 한다.
    session.add_all(
        [
            ExtractedPlaceCandidate(
                video_id="queue-video",
                source_channel_id="queue-channel",
                source_playlist_id="queue-playlist",
                source_kind="transcript",
                source_text="서울 제외 근거",
                ai_place_name="서울 제외 후보",
                match_status=MatchStatus.IGNORED,
                is_domestic=True,
            ),
            ExtractedPlaceCandidate(
                video_id="queue-video",
                source_channel_id="queue-channel",
                source_playlist_id="queue-playlist",
                source_kind="transcript",
                source_text="서울 해외 근거",
                ai_place_name="서울 해외 후보",
                match_status=MatchStatus.NEEDS_REVIEW,
                is_domestic=False,
            ),
            ExtractedPlaceCandidate(
                video_id="queue-video",
                source_channel_id="queue-channel",
                source_playlist_id="queue-playlist",
                source_kind="transcript",
                source_text="부산 근거",
                ai_place_name="부산 후보",
                match_status=MatchStatus.NEEDS_REVIEW,
                is_domestic=True,
            ),
            ExtractedPlaceCandidate(
                video_id="queue-video",
                source_channel_id="queue-channel",
                source_playlist_id="queue-playlist",
                source_kind="description",
                source_text="서울 설명 근거",
                ai_place_name="서울 설명 후보",
                match_status=MatchStatus.NEEDS_REVIEW,
                is_domestic=True,
            ),
            ExtractedPlaceCandidate(
                video_id="queue-video",
                source_channel_id="queue-channel",
                source_kind="transcript",
                source_text="서울 다른 재생목록 근거",
                ai_place_name="서울 다른 재생목록 후보",
                match_status=MatchStatus.NEEDS_REVIEW,
                is_domestic=True,
            ),
            ExtractedPlaceCandidate(
                video_id="other-video",
                source_channel_id="other-channel",
                source_playlist_id="queue-playlist",
                source_kind="transcript",
                source_text="서울 다른 출처 근거",
                ai_place_name="서울 다른 출처 후보",
                match_status=MatchStatus.NEEDS_REVIEW,
                is_domestic=True,
            ),
            ExtractedPlaceCandidate(
                video_id="queue-video",
                source_channel_id="queue-channel",
                source_playlist_id="queue-playlist",
                source_kind="transcript",
                source_text="서울 모호 근거",
                ai_place_name="서울 모호 후보",
                match_status=MatchStatus.NEEDS_REVIEW,
                is_domestic=True,
                provider_evidence_json={
                    "geocoding": {"decision": {"reason": "ambiguous"}}
                },
            ),
            # 일치 행을 마지막 ID로 둬 `max_id - baseline` 같은 잘못된 신규 건수
            # 계산이 8을 반환하고, 실제 filter count만 1을 반환하도록 고정한다.
            ExtractedPlaceCandidate(
                video_id="queue-video",
                source_channel_id="queue-channel",
                source_playlist_id="queue-playlist",
                source_kind="transcript",
                source_text="서울 신규 근거",
                ai_place_name="서울 신규 후보",
                match_status=MatchStatus.NEEDS_REVIEW,
                grounding_status=GroundingStatus.VERIFIED_RAW.value,
                is_domestic=True,
            ),
        ]
    )
    await session.commit()

    second = await client.get(
        "/api/v1/destinations/unmatched",
        params={
            **filters,
            "limit": 300,
            "cursor": body["next_cursor"],
            "newer_than_id": 501,
        },
    )
    assert second.status_code == 200
    second_body = second.json()
    assert [item["id"] for item in second_body["items"]] == list(range(301, 502))
    assert second_body["total"] == 501
    assert second_body["newest_id"] == 501
    assert second_body["newer_than"] == 1
    assert second_body["has_more"] is False
    assert second_body["next_cursor"] is None
    assert detail_body["list_item"] == next(
        item for item in second_body["items"] if item["id"] == 501
    )

    fresh = await client.get(
        "/api/v1/destinations/unmatched",
        params={**filters, "limit": 1, "newer_than_id": 501},
    )
    assert fresh.status_code == 200
    assert fresh.json()["total"] == 502
    assert fresh.json()["newest_id"] == 509
    assert fresh.json()["newer_than"] == 1

    newest_count = await client.get(
        "/api/v1/destinations/unmatched",
        params={
            **filters,
            "sort": "newest",
            "limit": 1,
            "newer_than_id": 501,
        },
    )
    assert newest_count.status_code == 200
    assert newest_count.json()["newest_id"] == 509
    assert newest_count.json()["newer_than"] == 1

    for changed_filter in (
        {"q": "부산"},
        {"sort": "newest"},
        {"is_domestic": "false"},
        {"status": "ignored"},
        {"grounding": "missing"},
    ):
        mismatch = await client.get(
            "/api/v1/destinations/unmatched",
            params={
                **filters,
                **changed_filter,
                "limit": 1,
                "cursor": body["next_cursor"],
            },
        )
        assert mismatch.status_code == 400


async def test_unmatched_search_normalization_wildcards_status_and_detail(
    client, session
):
    session.add(YoutubeChannel(channel_id="search-channel", title="검색 채널"))
    session.add(
        YoutubeVideo(
            video_id="search-video",
            title="검색 검수 영상",
            url="https://example.invalid/search",
            channel_id="search-channel",
        )
    )
    await session.flush()
    session.add_all(
        [
            ExtractedPlaceCandidate(
                video_id="search-video",
                source_text="특수 검색어 근거",
                ai_place_name="100%_맛집",
                match_status=MatchStatus.NEEDS_REVIEW,
                is_domestic=True,
            ),
            ExtractedPlaceCandidate(
                video_id="search-video",
                source_text="wildcard 대조 근거",
                ai_place_name="100XX맛집",
                match_status=MatchStatus.NEEDS_REVIEW,
                is_domestic=True,
            ),
            ExtractedPlaceCandidate(
                video_id="search-video",
                source_text="위치 검색 근거",
                ai_place_name="이름만 있는 후보",
                location_hint="종로 골목",
                match_status=MatchStatus.NEEDS_REVIEW,
            ),
            ExtractedPlaceCandidate(
                video_id="search-video",
                source_text="제외 근거 1",
                ai_place_name="제외 후보 1",
                match_status=MatchStatus.IGNORED,
                is_domestic=False,
            ),
            ExtractedPlaceCandidate(
                video_id="search-video",
                source_text="제외 근거 2",
                ai_place_name="제외 후보 2",
                match_status=MatchStatus.IGNORED,
                is_domestic=False,
            ),
            ExtractedPlaceCandidate(
                video_id="search-video",
                source_text="삭제 근거",
                ai_place_name="삭제 후보",
                match_status=MatchStatus.IGNORED,
                is_domestic=False,
                deleted_at=utcnow(),
                deletion_reason="테스트 soft delete",
            ),
            ExtractedPlaceCandidate(
                video_id="search-video",
                source_text="Unicode 자기검색 근거",
                ai_place_name="Straße 카페",
                match_status=MatchStatus.NEEDS_REVIEW,
            ),
            ExtractedPlaceCandidate(
                video_id="search-video",
                source_text="Unicode 대조 근거",
                ai_place_name="Strasse 카페",
                match_status=MatchStatus.NEEDS_REVIEW,
            ),
            ExtractedPlaceCandidate(
                video_id="search-video",
                source_text="percent 문자 근거",
                ai_place_name="퍼센트 100% 맛집",
                match_status=MatchStatus.NEEDS_REVIEW,
            ),
            ExtractedPlaceCandidate(
                video_id="search-video",
                source_text="percent 대조 근거",
                ai_place_name="퍼센트 100X 맛집",
                match_status=MatchStatus.NEEDS_REVIEW,
            ),
            ExtractedPlaceCandidate(
                video_id="search-video",
                source_text="underscore 문자 근거",
                ai_place_name="밑줄 A_B",
                match_status=MatchStatus.NEEDS_REVIEW,
            ),
            ExtractedPlaceCandidate(
                video_id="search-video",
                source_text="underscore 대조 근거",
                ai_place_name="밑줄 AXB",
                match_status=MatchStatus.NEEDS_REVIEW,
            ),
            ExtractedPlaceCandidate(
                video_id="search-video",
                source_text="backslash 문자 근거",
                ai_place_name=r"역슬래시 A\B",
                match_status=MatchStatus.NEEDS_REVIEW,
            ),
            ExtractedPlaceCandidate(
                video_id="search-video",
                source_text="backslash 대조 근거",
                ai_place_name="역슬래시 AB",
                match_status=MatchStatus.NEEDS_REVIEW,
            ),
        ]
    )
    await session.commit()

    literal = await client.get(
        "/api/v1/destinations/unmatched",
        params={
            "q": " 100%_맛집 ",
            "status": "needs_review",
            "is_domestic": "true",
        },
    )
    assert literal.status_code == 200
    assert literal.json()["total"] == 1
    assert literal.json()["items"][0]["ai_place_name"] == "100%_맛집"

    location = await client.get(
        "/api/v1/destinations/unmatched", params={"q": "종로"}
    )
    assert location.status_code == 200
    assert [item["ai_place_name"] for item in location.json()["items"]] == [
        "이름만 있는 후보"
    ]

    for query, expected_name in (
        ("Straße", "Straße 카페"),
        ("100% 맛집", "퍼센트 100% 맛집"),
        ("A_B", "밑줄 A_B"),
        (r"A\B", r"역슬래시 A\B"),
    ):
        escaped = await client.get(
            "/api/v1/destinations/unmatched", params={"q": query}
        )
        assert escaped.status_code == 200
        assert escaped.json()["total"] == 1
        assert [item["ai_place_name"] for item in escaped.json()["items"]] == [
            expected_name
        ]

    no_query = await client.get(
        "/api/v1/destinations/unmatched",
        params={"limit": 1, "sort": "oldest"},
    )
    whitespace_query = await client.get(
        "/api/v1/destinations/unmatched",
        params={
            "limit": 1,
            "sort": "oldest",
            "q": "   ",
            "is_domestic": "all",
            "cursor": no_query.json()["next_cursor"],
        },
    )
    assert whitespace_query.status_code == 200
    assert whitespace_query.json()["items"][0]["id"] == 2

    ignored = await client.get(
        "/api/v1/destinations/unmatched",
        params={
            "limit": 2,
            "sort": "oldest",
            "status": "ignored",
            "is_domestic": "false",
        },
    )
    ignored_body = ignored.json()
    assert ignored_body["total"] == 2
    assert [item["id"] for item in ignored_body["items"]] == [4, 5]
    assert ignored_body["has_more"] is False
    assert ignored_body["next_cursor"] is None

    ignored_detail = await client.get("/api/v1/destinations/candidates/4/detail")
    assert ignored_detail.status_code == 200
    assert ignored_detail.json()["list_item"]["match_status"] == "ignored"
    assert ignored_detail.json()["list_item"]["video_title"] == "검색 검수 영상"

    removed = await client.get(
        "/api/v1/destinations/unmatched",
        params={
            "limit": 3,
            "sort": "oldest",
            "status": "removed",
            "is_domestic": "false",
        },
    )
    removed_body = removed.json()
    assert removed.status_code == 200
    assert removed_body["total"] == 3
    assert [item["id"] for item in removed_body["items"]] == [4, 5, 6]
    assert [item["review_state"] for item in removed_body["items"]] == [
        "ignored",
        "ignored",
        "deleted",
    ]
    assert all(
        item["undo"]["candidate_id"] == item["id"]
        for item in removed_body["items"]
    )

    deleted_detail = await client.get(
        "/api/v1/destinations/candidates/6/detail"
    )
    assert deleted_detail.status_code == 200
    assert deleted_detail.json()["candidate"]["review_state"] == "deleted"
    assert deleted_detail.json()["candidate"]["undo"]["candidate_id"] == 6

    assert (
        await client.get(
            "/api/v1/destinations/unmatched", params={"q": "x" * 255}
        )
    ).status_code == 200
    assert (
        await client.get(
            "/api/v1/destinations/unmatched", params={"q": "x" * 256}
        )
    ).status_code == 422
    assert (
        await client.get(
            "/api/v1/destinations/unmatched", params={"sort": "confidence"}
        )
    ).status_code == 422
    assert (
        await client.get(
            "/api/v1/destinations/unmatched", params={"status": "matched"}
        )
    ).status_code == 422
    for accepted_domestic, expected_total in {
        "true": 2,
        "false": 0,
        "all": 11,
    }.items():
        accepted = await client.get(
            "/api/v1/destinations/unmatched",
            params={"is_domestic": accepted_domestic},
        )
        assert accepted.status_code == 200
        assert accepted.json()["total"] == expected_total
    for rejected_domestic in ("1", "yes", "on", "unknown"):
        assert (
            await client.get(
                "/api/v1/destinations/unmatched",
                params={"is_domestic": rejected_domestic},
            )
        ).status_code == 422


async def test_unmatched_search_reaches_unique_candidate_in_2000_backlog(
    client, session, record_property
):
    session.add_all(
        [
            YoutubeChannel(
                channel_id="search-backlog-channel", title="대규모 검수 채널"
            ),
            YoutubeVideo(
                video_id="search-backlog-video",
                title="대규모 검수 영상",
                url="https://example.invalid/search-backlog",
                channel_id="search-backlog-channel",
            ),
        ]
    )
    await session.flush()
    session.add_all(
        [
            ExtractedPlaceCandidate(
                video_id="search-backlog-video",
                source_text=f"대규모 근거 {index}",
                ai_place_name=(
                    "심층검색표식 후보"
                    if index == 0
                    else f"일반 검수 후보 {index}"
                ),
                match_status=MatchStatus.NEEDS_REVIEW,
            )
            for index in range(2000)
        ]
    )
    await session.commit()

    started_at = perf_counter()
    response = await client.get(
        "/api/v1/destinations/unmatched",
        params={"q": "심층검색표식", "limit": 1},
    )
    elapsed_seconds = perf_counter() - started_at
    record_property("search_response_seconds", f"{elapsed_seconds:.6f}")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == [1]
    assert body["has_more"] is False
    assert elapsed_seconds < 3.0, f"검색 응답 {elapsed_seconds:.3f}초"


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
    assert extraction["grounding_status"] == GroundingStatus.VERIFIED_RAW.value
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


async def test_unmatched_grounding_exact_filter_exposes_all_strict_states(
    client, session
):
    session.add(
        YoutubeVideo(
            video_id="grounding-filter-video",
            title="grounding 필터 영상",
            url="https://example.invalid/grounding-filter",
            channel_id="grounding-filter-channel",
        )
    )
    await session.flush()
    statuses = list(GroundingStatus)
    session.add_all(
        [
            ExtractedPlaceCandidate(
                video_id="grounding-filter-video",
                source_text=f"grounding 근거 {status.value}",
                ai_place_name=f"grounding 후보 {status.value}",
                match_status=MatchStatus.NEEDS_REVIEW,
                grounding_status=status.value,
            )
            for status in statuses
        ]
    )
    await session.commit()

    for status in statuses:
        response = await client.get(
            "/api/v1/destinations/unmatched",
            params={"grounding": status.value},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert [item["grounding_status"] for item in body["items"]] == [
            status.value
        ]
        assert [item["ai_place_name"] for item in body["items"]] == [
            f"grounding 후보 {status.value}"
        ]

    assert (
        await client.get(
            "/api/v1/destinations/unmatched",
            params={"grounding": "verified"},
        )
    ).status_code == 422


async def test_legacy_unknown_grounding_does_not_mask_queue_reason(client, session):
    # MAJOR 3: legacy_unknown(재처리 전 기존 후보)은 UNGROUNDED로 표기하지 않고 원래 사유를
    # 유지한다(행동 불가 사유로 backlog을 덮지 않도록). 실제 판정된 missing만 UNGROUNDED.
    session.add(
        YoutubeChannel(channel_id="legacy-channel", title="레거시 채널")
    )
    session.add(
        YoutubeVideo(
            video_id="legacy-video",
            title="레거시 사유 영상",
            url="https://example.invalid/legacy",
            channel_id="legacy-channel",
        )
    )
    await session.flush()
    session.add_all(
        [
            ExtractedPlaceCandidate(
                video_id="legacy-video",
                source_kind="transcript",
                source_text="레거시 지역 불일치",
                ai_place_name="레거시 지역 불일치",
                match_status=MatchStatus.NEEDS_REVIEW,
                review_note="region_mismatch",
                grounding_status=GroundingStatus.LEGACY_UNKNOWN.value,
            ),
            ExtractedPlaceCandidate(
                video_id="legacy-video",
                source_kind="transcript",
                source_text="재처리 미확인",
                ai_place_name="재처리 미확인",
                match_status=MatchStatus.NEEDS_REVIEW,
                review_note="region_mismatch",
                grounding_status=GroundingStatus.MISSING.value,
            ),
        ]
    )
    await session.commit()

    body = (await client.get("/api/v1/destinations/unmatched")).json()
    by_name = {item["ai_place_name"]: item for item in body["items"]}
    # legacy는 원래 사유(region_mismatch) 유지, 재처리 판정 missing은 ungrounded 최우선.
    assert by_name["레거시 지역 불일치"]["queue_reason"] == "region_mismatch"
    assert by_name["재처리 미확인"]["queue_reason"] == "ungrounded"


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
