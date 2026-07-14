"""API 엔드포인트 통합 테스트.

`get_session` 의존성을 테스트 엔진으로 오버라이드해 ASGI 앱을 직접 호출한다.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from ktc.core.database import get_repeatable_read_session, get_session
from ktc.services import audit_service, settings_service
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


async def test_harvest_create_and_status(client):
    resp = await client.post("/api/v1/harvest", json={"query": "제주도 맛집", "max_videos": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "pending"
    job_id = body["job_id"]

    status = await client.get(f"/api/v1/harvest/{job_id}")
    assert status.status_code == 200
    sbody = status.json()
    assert sbody["job_id"] == job_id
    assert sbody["state"] == "pending"
    assert sbody["progress"] == 0.0
    assert sbody["current_message"] == "작업이 대기열에 등록되었습니다."
    assert sbody["status_logs"][0]["message"] == "작업이 대기열에 등록되었습니다."


async def test_harvest_status_404(client):
    resp = await client.get("/api/v1/harvest/999999")
    assert resp.status_code == 404


async def _run_by_job_id(client, job_id: str) -> dict:
    runs = await client.get("/api/v1/runs?limit=10")
    return next(r for r in runs.json()["items"] if r["job_id"] == job_id)


async def test_harvest_channel_url_resolves_to_id(client):
    cid = "UCnV8h6ZzQnLoFBFXqHGtxBg"
    resp = await client.post(
        "/api/v1/harvest",
        json={"channel_id": f"https://www.youtube.com/channel/{cid}", "max_videos": 3},
    )
    assert resp.status_code == 200
    run = await _run_by_job_id(client, resp.json()["job_id"])
    assert run["target_type"] == "channel"
    assert run["target_id"] == cid


async def test_harvest_playlist_url_resolves_to_id(client):
    pid = "PLXQvmY7fb6woRMSD8cgk10UIJRt9nmuXl"
    resp = await client.post(
        "/api/v1/harvest",
        json={"playlist_id": f"https://www.youtube.com/playlist?list={pid}", "max_videos": 3},
    )
    assert resp.status_code == 200
    run = await _run_by_job_id(client, resp.json()["job_id"])
    assert run["target_type"] == "playlist"
    assert run["target_id"] == pid


async def test_harvest_unrecognized_playlist_url_400(client):
    resp = await client.post(
        "/api/v1/harvest", json={"playlist_id": "https://example.com/no-list", "max_videos": 3}
    )
    assert resp.status_code == 400


async def test_recurring_source_target_lifecycle(client):
    cid = "UCnV8h6ZzQnLoFBFXqHGtxBg"
    resp = await client.post(
        "/api/v1/harvest",
        json={
            "channel_id": cid,
            "max_videos": 3,
            "repeat_interval_minutes": 60,
            "default_category_code": "01050100",
        },
    )
    assert resp.status_code == 200

    listing = await client.get("/api/v1/source-targets")
    assert listing.status_code == 200
    targets = listing.json()
    assert len(targets) == 1
    target = targets[0]
    assert target["target_type"] == "channel"
    assert target["source_value"] == cid
    assert target["scan_interval_minutes"] == 60
    assert target["default_category_code"] == "01050100"
    assert "해수욕장" in target["default_category_label"]
    assert target["is_active"] is True
    assert target["next_crawl_at"] is not None

    deleted = await client.delete(f"/api/v1/source-targets/{target['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "ok"
    assert (await client.get("/api/v1/source-targets")).json() == []


async def test_stop_pending_run_cancels(client):
    resp = await client.post("/api/v1/harvest", json={"query": "부산 카페", "max_videos": 3})
    job_id = resp.json()["job_id"]
    stop = await client.post(f"/api/v1/runs/{job_id}/stop")
    assert stop.status_code == 200
    assert stop.json()["state"] == "cancelled"
    status = await client.get(f"/api/v1/harvest/{job_id}")
    assert status.json()["state"] == "cancelled"


async def test_stop_running_run_sets_cancel_requested(client, session):
    from ktc.models import CrawlRun, RunState

    resp = await client.post("/api/v1/harvest", json={"query": "부산 카페", "max_videos": 3})
    job_id = int(resp.json()["job_id"])
    run = await session.get(CrawlRun, job_id)
    run.state = RunState.RUNNING
    await session.commit()

    stop = await client.post(f"/api/v1/runs/{job_id}/stop")
    assert stop.status_code == 200
    assert stop.json()["state"] == "running"
    await session.refresh(run)
    assert run.cancel_requested is True
    assert run.state == "running"


async def test_recurring_max_runs_and_patch(client):
    cid = "UCnV8h6ZzQnLoFBFXqHGtxBg"
    await client.post(
        "/api/v1/harvest",
        json={
            "channel_id": cid,
            "max_videos": 3,
            "repeat_interval_minutes": 60,
            "repeat_max_runs": 5,
        },
    )
    target = (await client.get("/api/v1/source-targets")).json()[0]
    assert target["max_runs"] == 5
    assert target["run_count"] == 0

    patched = await client.patch(
        f"/api/v1/source-targets/{target['id']}",
        json={
            "scan_interval_minutes": 720,
            "max_runs": 10,
            "default_category_code": "0",
        },
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["scan_interval_minutes"] == 720
    assert body["max_runs"] == 10
    assert body["default_category_code"] == "0"
    assert body["default_category_label"] == "unknown"

    missing = await client.patch(
        "/api/v1/source-targets/999999", json={"is_active": False}
    )
    assert missing.status_code == 404


async def test_metrics_endpoint_shape(client):
    resp = await client.get("/api/v1/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert "storage" in body and "database" in body
    db = body["database"]
    for key in (
        "youtube_videos",
        "travel_places",
        "active_recurring_targets",
        "candidates_by_status",
        "runs_by_state",
    ):
        assert key in db


async def test_run_videos_endpoint(client, session):
    from ktc.models import CrawlRun, RunSource, RunState, YoutubeChannel, YoutubeVideo

    session.add(YoutubeChannel(channel_id="UCvidtest", title="테스트 채널"))
    session.add(
        YoutubeVideo(
            video_id="vidABC",
            title="테스트 영상",
            url="https://youtu.be/vidABC",
            channel_id="UCvidtest",
            duration_seconds=42,
        )
    )
    run = CrawlRun(
        job_type="harvest",
        source=RunSource.WEB,
        target_type="keyword",
        target_id="x",
        state=RunState.DONE,
        progress=1.0,
        result_json='{"video_ids": ["vidABC"]}',
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    resp = await client.get(f"/api/v1/runs/{run.id}/videos")
    assert resp.status_code == 200
    videos = resp.json()
    assert len(videos) == 1
    assert videos[0]["video_id"] == "vidABC"
    assert videos[0]["url"] == "https://www.youtube.com/watch?v=vidABC"
    assert videos[0]["channel_title"] == "테스트 채널"


async def test_stop_terminal_run_400(client, session):
    from ktc.models import CrawlRun, RunState

    resp = await client.post("/api/v1/harvest", json={"query": "부산 카페", "max_videos": 3})
    job_id = int(resp.json()["job_id"])
    run = await session.get(CrawlRun, job_id)
    run.state = RunState.DONE
    await session.commit()
    stop = await client.post(f"/api/v1/runs/{job_id}/stop")
    assert stop.status_code == 400


async def test_stop_pending_and_running_response_contract(client, session):
    from sqlalchemy import select

    from ktc.models import AuditLog, CrawlRun, RunState
    from ktc.services import crawl_run_service

    pending_response = await client.post(
        "/api/v1/harvest", json={"query": "대기 취소", "max_videos": 1}
    )
    pending_id = int(pending_response.json()["job_id"])
    pending_stop = await client.post(f"/api/v1/runs/{pending_id}/stop")
    assert pending_stop.status_code == 200
    assert pending_stop.json() == {"job_id": str(pending_id), "state": "cancelled"}

    running_response = await client.post(
        "/api/v1/harvest", json={"query": "실행 중지", "max_videos": 1}
    )
    running_id = int(running_response.json()["job_id"])
    claimed = await crawl_run_service.claim_next_pending(session)
    assert claimed.id == running_id

    running_stop = await client.post(f"/api/v1/runs/{running_id}/stop")
    assert running_stop.status_code == 200
    assert running_stop.json() == {"job_id": str(running_id), "state": "running"}
    run = await session.get(CrawlRun, running_id)
    await session.refresh(run)
    assert run.state == RunState.RUNNING
    assert run.cancel_requested is True
    audit = (
        await session.execute(
            select(AuditLog)
            .where(
                AuditLog.action == "run.stop",
                AuditLog.target_id == str(running_id),
            )
            .order_by(AuditLog.id.desc())
            .limit(1)
        )
    ).scalars().one()
    assert json.loads(audit.payload_json)["prev_state"] == "running"

    missing = await client.post("/api/v1/runs/999999/stop")
    assert missing.status_code == 404


async def test_restart_rejects_non_terminal_run(client):
    """T-162: terminal(done/failed/cancelled) 상태만 재시작할 수 있다."""
    resp = await client.post("/api/v1/harvest", json={"query": "부산 카페", "max_videos": 3})
    job_id = resp.json()["job_id"]
    restart = await client.post(f"/api/v1/runs/{job_id}/restart")
    assert restart.status_code == 400
    assert "terminal" in restart.json()["detail"]


async def test_restart_run_lineage_attention_and_idempotency(client, session):
    """T-162: 재시작 lineage 기록 + 같은 원본 중복 클릭 멱등(409 아님)."""
    from ktc.services import crawl_run_service

    resp = await client.post("/api/v1/harvest", json={"query": "부산 카페", "max_videos": 3})
    job_id = int(resp.json()["job_id"])
    await crawl_run_service.mark_failed(session, job_id, error="boom")

    restart = await client.post(f"/api/v1/runs/{job_id}/restart")
    assert restart.status_code == 200
    body = restart.json()
    assert body["created"] is True
    assert body["state"] == "pending"
    assert body["restart_of_run_id"] == str(job_id)
    new_job_id = body["job_id"]
    assert new_job_id != str(job_id)

    # 중복 클릭: 새 run을 만들지 않고 같은 run을 돌려준다.
    again = await client.post(f"/api/v1/runs/{job_id}/restart")
    assert again.status_code == 200
    assert again.json()["job_id"] == new_job_id
    assert again.json()["created"] is False

    # 단건 응답에 lineage·attention이 additive로 노출된다.
    origin_view = (await client.get(f"/api/v1/runs/{job_id}")).json()
    assert origin_view["attention"] == "superseded"
    restart_view = (await client.get(f"/api/v1/runs/{new_job_id}")).json()
    assert restart_view["restart_of_run_id"] == str(job_id)
    assert restart_view["attention"] is None

    # #185 envelope items에서도 attention·restart_of_run_id가 살아남는다.
    listing = (await client.get("/api/v1/runs?limit=50")).json()
    by_id = {r["job_id"]: r for r in listing["items"]}
    assert by_id[str(job_id)]["attention"] == "superseded"
    assert by_id[new_job_id]["restart_of_run_id"] == str(job_id)
    assert by_id[new_job_id]["attention"] is None

    missing = await client.post("/api/v1/runs/999999/restart")
    assert missing.status_code == 404


async def test_lane_mapping_across_enqueue_points(client, session_factory):
    """T-163: enqueue 지점별 lane 매핑과 목록/상세 응답의 lane 노출."""
    from ktc.models import TravelPlace
    from ktc.services import crawl_run_service

    # harvest(수집)는 배치 레인.
    harvest = await client.post(
        "/api/v1/harvest", json={"query": "부산 야경", "max_videos": 3}
    )
    harvest_job = harvest.json()["job_id"]
    harvest_view = (await client.get(f"/api/v1/runs/{harvest_job}")).json()
    assert harvest_view["lane"] == "batch"

    # 검수 재처리(reprocess)는 대화형 레인.
    reprocess = await client.post(
        "/api/v1/destinations/reprocess",
        json={"video_ids": ["v-lane-1"], "start_stage": "transcript"},
    )
    reprocess_job = reprocess.json()["job_ids"][0]
    reprocess_view = (await client.get(f"/api/v1/runs/{reprocess_job}")).json()
    assert reprocess_view["lane"] == "interactive"

    # Deep Research(사용자 직접 트리거)는 대화형 레인.
    async with session_factory() as s:
        place = TravelPlace(name="광안리", latitude=35.153, longitude=129.118)
        s.add(place)
        await s.commit()
        await s.refresh(place)
        place_id = place.place_id

    research = await client.post(
        f"/api/v1/destinations/{place_id}/deep-research", json={}
    )
    research_job = int(research.json()["job_id"])
    research_view = (await client.get(f"/api/v1/runs/{research_job}")).json()
    assert research_view["lane"] == "interactive"

    # 재시작은 원본 lane을 복사한다(대화형 원본 → 대화형 재시작).
    async with session_factory() as s:
        await crawl_run_service.mark_failed(s, research_job, error="boom")
    restart = await client.post(f"/api/v1/runs/{research_job}/restart")
    restart_job = restart.json()["job_id"]
    restart_view = (await client.get(f"/api/v1/runs/{restart_job}")).json()
    assert restart_view["lane"] == "interactive"

    # #185 envelope 목록에서도 lane이 노출된다.
    listing = (await client.get("/api/v1/runs?limit=50")).json()
    by_id = {r["job_id"]: r["lane"] for r in listing["items"]}
    assert by_id[harvest_job] == "batch"
    assert by_id[str(reprocess_job)] == "interactive"


async def test_acknowledge_run_api(client, session):
    """T-162: open→acknowledged 전이 + 멱등 재호출 + 대상 없음 400/404."""
    from ktc.services import crawl_run_service

    resp = await client.post("/api/v1/harvest", json={"query": "부산 카페", "max_videos": 3})
    job_id = int(resp.json()["job_id"])

    # 아직 실패하지 않은 run은 확인할 attention이 없다.
    early = await client.post(f"/api/v1/runs/{job_id}/acknowledge")
    assert early.status_code == 400

    await crawl_run_service.mark_failed(session, job_id, error="boom")
    acked = await client.post(f"/api/v1/runs/{job_id}/acknowledge")
    assert acked.status_code == 200
    assert acked.json()["attention"] == "acknowledged"

    # 멱등 재호출.
    again = await client.post(f"/api/v1/runs/{job_id}/acknowledge")
    assert again.status_code == 200
    assert again.json()["attention"] == "acknowledged"

    run_view = (await client.get(f"/api/v1/runs/{job_id}")).json()
    assert run_view["attention"] == "acknowledged"

    missing = await client.post("/api/v1/runs/999999/acknowledge")
    assert missing.status_code == 404


async def test_settings_roundtrip(client):
    resp = await client.post("/api/v1/settings", json={"gemini_engine_version": "gemini-2.0-flash"})
    assert resp.status_code == 200
    assert resp.json()["settings"]["gemini_engine_version"] == "gemini-2.0-flash"
    assert "gemini-2.0-flash" in resp.json()["settings"]["gemini_engine_options"]

    get_resp = await client.get("/api/v1/settings")
    assert get_resp.json()["gemini_engine_version"] == "gemini-2.0-flash"
    assert get_resp.json()["gemini_engine_default"] == "gemini-2.5-flash"
    assert "gemini-2.0-flash" in get_resp.json()["gemini_engine_options"]


async def test_settings_rejects_unknown_keys(client):
    resp = await client.post("/api/v1/settings", json={"GEMINI_API_KEY": "plain-secret"})
    assert resp.status_code == 400
    assert "지원하지 않는 설정 키" in resp.json()["detail"]


async def test_settings_rejects_unknown_gemini_engine(client):
    resp = await client.post(
        "/api/v1/settings",
        json={"gemini_engine_version": "gemini-unknown-model"},
    )
    assert resp.status_code == 400
    assert "지원하지 않는 AI 엔진" in resp.json()["detail"]


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_destinations_reflect_db(client, session_factory):
    from ktc.models import (
        ExtractedPlaceCandidate,
        FeatureExportStatus,
        MatchStatus,
        TravelPlace,
        VideoPlaceMapping,
        YoutubeVideo,
    )

    async with session_factory() as s:
        place = TravelPlace(
            name="해운대", latitude=35.1587, longitude=129.1604, is_geocoded=True
        )
        video = YoutubeVideo(
            video_id="v1",
            title="부산 여행",
            url="https://youtu.be/v1",
            channel_id="c",
            channel_name="부산 유튜버",
        )
        s.add_all([place, video])
        await s.commit()
        await s.refresh(place)
        s.add(
            ExtractedPlaceCandidate(
                video_id="v1", source_text="s", ai_place_name="검수대상",
                match_status=MatchStatus.NEEDS_REVIEW,
            )
        )
        s.add_all(
            [
                VideoPlaceMapping(
                    video_id="v1",
                    place_id=place.place_id,
                    ai_summary="해운대 첫 언급",
                    timestamp_start="00:01:00",
                ),
                VideoPlaceMapping(
                    video_id="v1",
                    place_id=place.place_id,
                    ai_summary="해운대 반복 언급",
                    timestamp_start="00:03:00",
                ),
            ]
        )
        await s.commit()

    dest = await client.get("/api/v1/destinations?sort=mention_count")
    assert dest.status_code == 200
    haeundae = next(d for d in dest.json()["items"] if d["name"] == "해운대")
    # 같은 영상 안의 반복 mapping은 고유 영상 1건으로 센다.
    assert haeundae["mention_count"] == 1
    assert haeundae["source_channel_count"] == 1
    assert haeundae["source_videos"][0]["channel_name"] == "부산 유튜버"
    assert haeundae["source_videos"][0]["video_title"] == "부산 여행"

    unmatched = await client.get("/api/v1/destinations/unmatched")
    assert unmatched.status_code == 200
    assert any(
        u["ai_place_name"] == "검수대상" for u in unmatched.json()["items"]
    )
    unmatched_item = next(
        u for u in unmatched.json()["items"] if u["ai_place_name"] == "검수대상"
    )
    detail = await client.get(
        f"/api/v1/destinations/candidates/{unmatched_item['id']}/detail"
    )
    assert detail.json()["candidate"]["source_kind"] == "transcript"
    assert (
        detail.json()["candidate"]["grounding_status"]
        == detail.json()["list_item"]["grounding_status"]
    )
    assert (
        detail.json()["candidate"]["feature_export_status"]
        == FeatureExportStatus.PENDING
    )


async def test_candidate_detail_deduplicates_legacy_sibling_mappings(
    client,
    session_factory,
):
    """legacy 다중 mapping은 sibling을 복제하지 않고 candidate FK를 정본으로 쓴다."""
    from ktc.models import (
        ExtractedPlaceCandidate,
        MatchStatus,
        TravelPlace,
        VideoPlaceMapping,
        YoutubeVideo,
    )

    async with session_factory() as s:
        video = YoutubeVideo(
            video_id="candidate-sibling-legacy",
            title="legacy sibling",
            url="u",
            channel_id="candidate-sibling",
        )
        authoritative = TravelPlace(
            name="후보 FK 정본",
            latitude=35.1,
            longitude=129.1,
        )
        legacy_first = TravelPlace(
            name="과거 매핑 1",
            latitude=35.2,
            longitude=129.2,
        )
        legacy_latest = TravelPlace(
            name="과거 매핑 2",
            latitude=35.3,
            longitude=129.3,
        )
        s.add_all([video, authoritative, legacy_first, legacy_latest])
        await s.flush()
        requested = ExtractedPlaceCandidate(
            video_id=video.video_id,
            source_text="상세 조회 기준 후보",
            ai_place_name="상세 조회 기준 후보",
            match_status=MatchStatus.NEEDS_REVIEW,
        )
        sibling = ExtractedPlaceCandidate(
            video_id=video.video_id,
            source_text="legacy 다중 매핑 후보",
            ai_place_name="legacy 다중 매핑 후보",
            match_status=MatchStatus.NEEDS_REVIEW,
            matched_place_id=authoritative.place_id,
        )
        s.add_all([requested, sibling])
        await s.flush()
        s.add_all(
            [
                VideoPlaceMapping(
                    video_id=video.video_id,
                    place_id=legacy_first.place_id,
                    place_candidate_id=sibling.id,
                    ai_summary="과거 연결 1",
                ),
                VideoPlaceMapping(
                    video_id=video.video_id,
                    place_id=legacy_latest.place_id,
                    place_candidate_id=sibling.id,
                    ai_summary="과거 연결 2",
                ),
            ]
        )
        await s.commit()
        requested_id = requested.id
        sibling_id = sibling.id
        authoritative_id = authoritative.place_id

    response = await client.get(
        f"/api/v1/destinations/candidates/{requested_id}/detail"
    )
    assert response.status_code == 200
    siblings = response.json()["sibling_candidates"]
    assert siblings == [
        {
            "id": sibling_id,
            "ai_place_name": "legacy 다중 매핑 후보",
            "match_status": "needs_review",
            "review_state": "needs_review",
            "candidate_category": None,
            "place_id": authoritative_id,
        }
    ]


async def test_candidate_and_place_detail_and_delete(
    client,
    session_factory,
    monkeypatch,
):
    from ktc.models import (
        ExtractedPlaceCandidate,
        MatchStatus,
        TravelPlace,
        VideoPlaceMapping,
        YoutubeChannel,
        YoutubeVideo,
        YoutubeVideoAnalysisRun,
    )

    async with session_factory() as s:
        channel = YoutubeChannel(channel_id="uc-d", title="여행 유튜버")
        video = YoutubeVideo(
            video_id="vd1",
            title="부산 브이로그",
            url="https://youtu.be/vd1",
            channel_id="uc-d",
            channel_name="여행 유튜버",
            description_raw="부산 여행 설명",
        )
        place = TravelPlace(
            name="감천문화마을",
            latitude=35.0974,
            longitude=129.0106,
            is_geocoded=True,
            category="관광",
            detailed_research_content="딥리서치 결과",
        )
        s.add_all([channel, video, place])
        await s.commit()
        await s.refresh(place)
        run = YoutubeVideoAnalysisRun(
            video_id="vd1", run_type="transcript_extract", state="done", model="gemini"
        )
        s.add(run)
        await s.commit()
        await s.refresh(run)
        cand = ExtractedPlaceCandidate(
            video_id="vd1",
            source_text="감천문화마을 언급",
            ai_place_name="감천문화마을",
            match_status=MatchStatus.NEEDS_REVIEW,
            source_kind="transcript",
            location_hint="부산",
            timestamp_start="00:01:00",
            analysis_run_id=run.id,
        )
        sib = ExtractedPlaceCandidate(
            video_id="vd1",
            source_text="다른 장소",
            ai_place_name="자갈치시장",
            match_status=MatchStatus.NEEDS_REVIEW,
            source_kind="transcript",
        )
        s.add_all([cand, sib])
        s.add_all(
            [
                VideoPlaceMapping(
                    video_id="vd1",
                    place_id=place.place_id,
                    ai_summary="감천 첫 언급",
                    timestamp_start="00:01:00",
                    source_kind="transcript",
                ),
                VideoPlaceMapping(
                    video_id="vd1",
                    place_id=place.place_id,
                    ai_summary="감천 반복 언급",
                    timestamp_start="00:05:00",
                    source_kind="transcript",
                ),
            ]
        )
        await s.commit()
        await s.refresh(cand)
        cand_id = cand.id
        place_id = place.place_id

    detail = await client.get(f"/api/v1/destinations/candidates/{cand_id}/detail")
    assert detail.status_code == 200
    dj = detail.json()
    assert dj["candidate"]["ai_place_name"] == "감천문화마을"
    assert dj["video"]["title"] == "부산 브이로그"
    assert dj["video"]["channel_title"] == "여행 유튜버"
    assert dj["video"]["description"] == "부산 여행 설명"
    assert dj["source_run"]["run_type_label"] == "자막 추출"
    sibling = next(
        c for c in dj["sibling_candidates"] if c["ai_place_name"] == "자갈치시장"
    )
    assert sibling["review_state"] == "needs_review"

    place_detail = await client.get(f"/api/v1/destinations/{place_id}/detail")
    assert place_detail.status_code == 200
    pj = place_detail.json()
    assert pj["place"]["name"] == "감천문화마을"
    assert pj["place"]["detailed_research_content"] == "딥리서치 결과"
    assert pj["stats"]["mention_count"] == 2
    assert pj["stats"]["video_count"] == 1
    assert pj["stats"]["channel_count"] == 1
    source_video = pj["source_videos"][0]
    assert source_video["video_id"] == "vd1"
    assert source_video["mention_count"] == 2
    assert len(source_video["mentions"]) == 2
    assert source_video["mentions"][0]["source_text"] == "감천 첫 언급"

    delete_operation_id = _client_operation_id()
    deleted = await client.delete(
        f"/api/v1/destinations/candidates/{cand_id}"
        f"?expected_revision=1&client_operation_id={delete_operation_id}"
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert deleted.json()["client_operation_id"] == delete_operation_id
    gone = await client.get(f"/api/v1/destinations/candidates/{cand_id}/detail")
    assert gone.status_code == 200
    assert gone.json()["candidate"]["review_state"] == "deleted"
    assert gone.json()["candidate"]["undo"]["candidate_id"] == cand_id

    from ktc.api import routes

    async def preserved_transcript(*_args, asset_type, **_kwargs):
        if asset_type == "transcript_corrected":
            return "삭제 뒤에도 보존된 보정 자막"
        return None

    monkeypatch.setattr(
        routes.postprocess_service,
        "_make_media_store",
        lambda _settings: object(),
    )
    monkeypatch.setattr(
        routes.media_store,
        "load_latest_asset_text",
        preserved_transcript,
    )
    transcript = await client.get(
        f"/api/v1/destinations/candidates/{cand_id}/transcript"
    )
    assert transcript.status_code == 200
    assert transcript.json() == {
        "text": "삭제 뒤에도 보존된 보정 자막",
        "kind": "corrected",
        "video_id": "vd1",
    }


async def test_candidate_id_path_enforces_postgresql_integer_range(client):
    overflow_id = 2_147_483_648
    requests = (
        ("GET", f"/api/v1/destinations/candidates/{overflow_id}/detail", None),
        ("GET", f"/api/v1/destinations/candidates/{overflow_id}/transcript", None),
        ("DELETE", f"/api/v1/destinations/candidates/{overflow_id}", None),
        (
            "POST",
            f"/api/v1/destinations/unmatched/{overflow_id}/resolve",
            {
                "client_operation_id": _client_operation_id(),
                "expected_revision": 1,
                "action": "ignore",
            },
        ),
        ("POST", f"/api/v1/destinations/unmatched/{overflow_id}/reopen", None),
        (
            "POST",
            f"/api/v1/destinations/audit/{overflow_id}",
            {"accurate": True},
        ),
    )
    for method, path, payload in requests:
        response = await client.request(method, path, json=payload)
        assert response.status_code == 422, (method, path, response.text)

    # 경계값은 asyncpg int4 bind에 안전하게 들어가며 단순 미존재로 끝난다.
    boundary = await client.get(
        "/api/v1/destinations/candidates/2147483647/detail"
    )
    assert boundary.status_code == 404


async def test_candidate_detail_and_resolve_null_unsafe_confidence_scores(
    client,
    session_factory,
):
    from ktc.models import ExtractedPlaceCandidate, MatchStatus, YoutubeVideo

    unsafe_scores = (
        float("nan"),
        float("inf"),
        float("-inf"),
        -0.01,
        1.01,
    )
    async with session_factory() as session:
        session.add(
            YoutubeVideo(
                video_id="candidate-confidence-api",
                title="t",
                url="u",
                channel_id="c-confidence-api",
            )
        )
        await session.commit()
        candidates = [
            ExtractedPlaceCandidate(
                video_id="candidate-confidence-api",
                source_text="s",
                ai_place_name=f"비정상 신뢰도 {index}",
                match_status=MatchStatus.NEEDS_REVIEW,
                confidence_score=score,
            )
            for index, score in enumerate(unsafe_scores)
        ]
        session.add_all(candidates)
        await session.commit()
        candidate_ids = [candidate.id for candidate in candidates]

    for candidate_id in candidate_ids:
        detail = await client.get(
            f"/api/v1/destinations/candidates/{candidate_id}/detail"
        )
        assert detail.status_code == 200
        assert detail.json()["candidate"]["confidence_score"] is None

        resolved = await client.post(
            f"/api/v1/destinations/unmatched/{candidate_id}/resolve",
            json={
                "client_operation_id": _client_operation_id(),
                "expected_revision": 1,
                "action": "ignore",
            },
        )
        assert resolved.status_code == 200
        assert resolved.json()["candidate"]["confidence_score"] is None


async def test_resolve_candidate_returns_409_after_another_reviewer_resolved_it(
    client,
    session_factory,
):
    from ktc.models import ExtractedPlaceCandidate, MatchStatus, YoutubeVideo

    async with session_factory() as session:
        session.add(
            YoutubeVideo(
                video_id="candidate-resolve-conflict-api",
                title="t",
                url="u",
                channel_id="c-resolve-conflict-api",
            )
        )
        await session.commit()
        candidate = ExtractedPlaceCandidate(
            video_id="candidate-resolve-conflict-api",
            source_text="s",
            ai_place_name="중복 검수 요청",
            match_status=MatchStatus.NEEDS_REVIEW,
        )
        session.add(candidate)
        await session.commit()
        candidate_id = candidate.id

    missing_revision = await client.post(
        f"/api/v1/destinations/unmatched/{candidate_id}/resolve",
        json={"client_operation_id": _client_operation_id(), "action": "ignore"},
    )
    assert missing_revision.status_code == 422
    missing_operation = await client.post(
        f"/api/v1/destinations/unmatched/{candidate_id}/resolve",
        json={"expected_revision": 1, "action": "ignore"},
    )
    assert missing_operation.status_code == 422
    invalid_operation = await client.post(
        f"/api/v1/destinations/unmatched/{candidate_id}/resolve",
        json={
            "client_operation_id": "not-a-uuid",
            "expected_revision": 1,
            "action": "ignore",
        },
    )
    assert invalid_operation.status_code == 422
    boolean_revision = await client.post(
        f"/api/v1/destinations/unmatched/{candidate_id}/resolve",
        json={
            "client_operation_id": _client_operation_id(),
            "expected_revision": True,
            "action": "ignore",
        },
    )
    assert boolean_revision.status_code == 422

    operation_id = _client_operation_id()
    first = await client.post(
        f"/api/v1/destinations/unmatched/{candidate_id}/resolve",
        json={
            "client_operation_id": operation_id,
            "expected_revision": 1,
            "action": "ignore",
        },
    )
    assert first.status_code == 200
    assert first.json()["client_operation_id"] == operation_id
    assert first.json()["candidate"]["last_client_operation_id"] == operation_id
    assert first.json()["undo"]["candidate_id"] == candidate_id
    assert first.json()["candidate"]["state_revision"] >= 1
    assert first.json()["candidate"]["review_state"] == "ignored"

    stale = await client.post(
        f"/api/v1/destinations/unmatched/{candidate_id}/resolve",
        json={
            "client_operation_id": _client_operation_id(),
            "expected_revision": 1,
            "action": "ignore",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "candidate_revision_conflict"


async def test_candidate_resolve_rolls_back_place_and_audit_together(
    client,
    session_factory,
    monkeypatch,
):
    from sqlalchemy import select

    from ktc.api import routes
    from ktc.models import (
        AuditLog,
        ExtractedPlaceCandidate,
        MatchStatus,
        TravelPlace,
        VideoPlaceMapping,
        YoutubeVideo,
    )

    async with session_factory() as s:
        s.add(
            YoutubeVideo(
                video_id="candidate-resolve-audit-rollback",
                title="확정 감사 실패",
                url="u",
                channel_id="candidate-resolve-audit-rollback",
            )
        )
        await s.commit()
        candidate = ExtractedPlaceCandidate(
            video_id="candidate-resolve-audit-rollback",
            source_text="확정 감사 실패 근거",
            ai_place_name="확정 감사 실패 후보",
            match_status=MatchStatus.NEEDS_REVIEW,
        )
        s.add(candidate)
        await s.commit()
        candidate_id = candidate.id

    original_record = routes.audit_service.record

    async def fail_after_flush(session, **kwargs):
        assert kwargs.get("commit") is False
        await original_record(session, **kwargs)
        await session.flush()
        raise RuntimeError("resolve audit unavailable after flush")

    monkeypatch.setattr(routes.audit_service, "record", fail_after_flush)

    with pytest.raises(RuntimeError, match="resolve audit unavailable"):
        await client.post(
            f"/api/v1/destinations/unmatched/{candidate_id}/resolve",
            json={
                "client_operation_id": _client_operation_id(),
                "expected_revision": 1,
                "action": "create_place",
                "corrected_name": "rollback 장소",
                "latitude": 35.0,
                "longitude": 129.0,
            },
        )

    async with session_factory() as s:
        current = await s.get(ExtractedPlaceCandidate, candidate_id)
        assert current is not None
        assert current.match_status == MatchStatus.NEEDS_REVIEW.value
        assert current.matched_place_id is None
        assert current.provider_evidence_json is None
        assert (await s.execute(select(TravelPlace))).scalars().all() == []
        assert (await s.execute(select(VideoPlaceMapping))).scalars().all() == []
        logs = (
            await s.execute(
                select(AuditLog).where(
                    AuditLog.action == "candidate.resolve",
                    AuditLog.target_id == str(candidate_id),
                )
            )
        ).scalars().all()
        assert logs == []


async def test_resolve_finalizer_rejects_force_exclude_after_audit_commit(
    client,
    session_factory,
    monkeypatch,
):
    from ktc.models import ExtractedPlaceCandidate, MatchStatus, YoutubeVideo
    from ktc.services import place_service

    video_id = "resolve-force-exclude-api"
    async with session_factory() as session:
        session.add(
            YoutubeVideo(
                video_id=video_id,
                title="t",
                url="u",
                channel_id="c-resolve-force-exclude-api",
            )
        )
        await session.commit()
        candidate = ExtractedPlaceCandidate(
            video_id=video_id,
            source_text="s",
            ai_place_name="응답 전 제외 API 후보",
            match_status=MatchStatus.NEEDS_REVIEW,
        )
        session.add(candidate)
        await session.commit()
        candidate_id = candidate.id
    forced: list[int] = []

    async def force_exclude_after_audit(_session, *, place_id):
        async with session_factory() as force_session:
            summary = await place_service.exclude_video(
                force_session,
                video_id,
                reason="resolve REST 응답 전 강제 제외",
                excluded_by="concurrent-reviewer",
            )
        assert summary is not None
        forced.append(place_id)
        return None

    monkeypatch.setattr(
        place_service,
        "enrich_place_admin_codes_postcommit",
        force_exclude_after_audit,
    )

    response = await client.post(
        f"/api/v1/destinations/unmatched/{candidate_id}/resolve",
        json={
            "client_operation_id": _client_operation_id(),
            "expected_revision": 1,
            "action": "create_place",
            "corrected_name": "응답 전 제외 API 장소",
            "latitude": 35.1587,
            "longitude": 129.1604,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "candidate_place_changed"
    assert len(forced) == 1
    detail = await client.get(
        f"/api/v1/destinations/candidates/{candidate_id}/detail"
    )
    assert detail.status_code == 200
    assert detail.json()["candidate"]["review_state"] == "deleted"
    assert detail.json()["candidate"]["matched_place_id"] is None
    assert detail.json()["candidate"]["last_client_operation_id"] is None


async def test_candidate_delete_requires_locked_needs_review_status(
    client, session_factory
):
    from ktc.models import ExtractedPlaceCandidate, MatchStatus, YoutubeVideo

    async with session_factory() as s:
        s.add(
            YoutubeVideo(
                video_id="v-delete-status",
                title="t",
                url="u",
                channel_id="c-delete-status",
            )
        )
        await s.commit()
        ignored = ExtractedPlaceCandidate(
            video_id="v-delete-status",
            source_text="s",
            ai_place_name="이미 제외된 후보",
            match_status=MatchStatus.IGNORED,
        )
        matched = ExtractedPlaceCandidate(
            video_id="v-delete-status",
            source_text="s",
            ai_place_name="이미 확정된 후보",
            match_status=MatchStatus.MATCHED,
        )
        needs_review = ExtractedPlaceCandidate(
            video_id="v-delete-status",
            source_text="s",
            ai_place_name="삭제 가능 후보",
            match_status=MatchStatus.NEEDS_REVIEW,
        )
        s.add_all([ignored, matched, needs_review])
        await s.commit()
        ignored_id = ignored.id
        matched_id = matched.id
        needs_review_id = needs_review.id

    missing_revision = await client.delete(
        f"/api/v1/destinations/candidates/{needs_review_id}"
        f"?client_operation_id={_client_operation_id()}"
    )
    assert missing_revision.status_code == 422
    missing_operation = await client.delete(
        f"/api/v1/destinations/candidates/{needs_review_id}?expected_revision=1"
    )
    assert missing_operation.status_code == 422
    invalid_operation = await client.delete(
        f"/api/v1/destinations/candidates/{needs_review_id}"
        "?expected_revision=1&client_operation_id=not-a-uuid"
    )
    assert invalid_operation.status_code == 422

    for stale_id in (ignored_id, matched_id):
        conflict = await client.delete(
            f"/api/v1/destinations/candidates/{stale_id}"
            f"?expected_revision=1&client_operation_id={_client_operation_id()}"
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "candidate_revision_conflict"

    operation_id = _client_operation_id()
    deleted = await client.delete(
        f"/api/v1/destinations/candidates/{needs_review_id}"
        f"?expected_revision=1&client_operation_id={operation_id}"
    )
    assert deleted.status_code == 200
    assert deleted.json()["client_operation_id"] == operation_id
    assert deleted.json()["review_state"] == "deleted"
    assert deleted.json()["undo"]["candidate_id"] == needs_review_id
    detail = await client.get(
        f"/api/v1/destinations/candidates/{needs_review_id}/detail"
    )
    assert detail.status_code == 200
    assert detail.json()["candidate"]["last_client_operation_id"] == operation_id
    assert detail.json()["list_item"]["last_client_operation_id"] == operation_id
    assert (
        await client.delete(
            f"/api/v1/destinations/candidates/{needs_review_id}"
            f"?expected_revision={deleted.json()['state_revision']}"
            f"&client_operation_id={_client_operation_id()}"
        )
    ).status_code == 404
    assert (
        await client.delete(
            "/api/v1/destinations/candidates/999999?expected_revision=1"
            f"&client_operation_id={_client_operation_id()}"
        )
    ).status_code == 404

    async with session_factory() as s:
        current_ignored = await s.get(ExtractedPlaceCandidate, ignored_id)
        current_matched = await s.get(ExtractedPlaceCandidate, matched_id)
        current_deleted = await s.get(ExtractedPlaceCandidate, needs_review_id)
        assert current_ignored is not None and current_ignored.deleted_at is None
        assert current_matched is not None and current_matched.deleted_at is None
        assert current_deleted is not None and current_deleted.deleted_at is not None
        last_operation = current_deleted.provider_evidence_json["review"][
            "last_client_operation"
        ]
        assert last_operation["id"] == operation_id
        assert last_operation["action"] == "delete"
        assert isinstance(last_operation["timestamp"], str)
        delete_logs = [
            log
            for log in await audit_service.list_recent(s)
            if log.action == "candidate.delete"
            and log.target_id == str(needs_review_id)
        ]
        assert len(delete_logs) == 1
        assert json.loads(delete_logs[0].payload_json)["client_operation_id"] == (
            operation_id
        )


async def test_candidate_delete_and_reopen_roll_back_when_audit_write_fails(
    client,
    session_factory,
    monkeypatch,
):
    from sqlalchemy import select

    from ktc.api import routes
    from ktc.models import (
        AuditLog,
        ExtractedPlaceCandidate,
        MatchStatus,
        YoutubeVideo,
    )

    async with session_factory() as s:
        s.add_all(
            [
                YoutubeVideo(
                    video_id="candidate-delete-audit-rollback",
                    title="삭제 감사 실패",
                    url="u",
                    channel_id="candidate-audit-rollback",
                ),
                YoutubeVideo(
                    video_id="candidate-reopen-audit-rollback",
                    title="복귀 감사 실패",
                    url="u",
                    channel_id="candidate-audit-rollback",
                ),
            ]
        )
        await s.commit()
        deleted_candidate = ExtractedPlaceCandidate(
            video_id="candidate-delete-audit-rollback",
            source_text="삭제 감사 실패 근거",
            ai_place_name="삭제 감사 실패 후보",
            match_status=MatchStatus.NEEDS_REVIEW,
        )
        ignored_candidate = ExtractedPlaceCandidate(
            video_id="candidate-reopen-audit-rollback",
            source_text="복귀 감사 실패 근거",
            ai_place_name="복귀 감사 실패 후보",
            match_status=MatchStatus.IGNORED,
        )
        s.add_all([deleted_candidate, ignored_candidate])
        await s.commit()
        deleted_candidate_id = deleted_candidate.id
        ignored_candidate_id = ignored_candidate.id

    ignored_detail = await client.get(
        f"/api/v1/destinations/candidates/{ignored_candidate_id}/detail"
    )
    undo_token = ignored_detail.json()["candidate"]["undo"]["token"]
    original_record = routes.audit_service.record

    async def fail_after_flush(session, **kwargs):
        assert kwargs.get("commit") is False
        await original_record(session, **kwargs)
        await session.flush()
        raise RuntimeError("candidate audit unavailable after flush")

    monkeypatch.setattr(routes.audit_service, "record", fail_after_flush)

    with pytest.raises(RuntimeError, match="candidate audit unavailable"):
        await client.delete(
            f"/api/v1/destinations/candidates/{deleted_candidate_id}"
            f"?expected_revision=1&client_operation_id={_client_operation_id()}"
        )
    with pytest.raises(RuntimeError, match="candidate audit unavailable"):
        await client.post(
            f"/api/v1/destinations/unmatched/{ignored_candidate_id}/reopen",
            json={"undo_token": undo_token},
        )

    async with session_factory() as s:
        current_delete = await s.get(
            ExtractedPlaceCandidate, deleted_candidate_id
        )
        current_reopen = await s.get(
            ExtractedPlaceCandidate, ignored_candidate_id
        )
        assert current_delete is not None
        assert current_delete.deleted_at is None
        assert current_delete.match_status == MatchStatus.NEEDS_REVIEW.value
        assert current_delete.provider_evidence_json is None
        assert current_reopen is not None
        assert current_reopen.match_status == MatchStatus.IGNORED.value
        logs = (
            await s.execute(
                select(AuditLog).where(
                    AuditLog.target_id.in_(
                        [str(deleted_candidate_id), str(ignored_candidate_id)]
                    ),
                    AuditLog.action.in_(
                        ["candidate.delete", "candidate.reopen"]
                    ),
                )
            )
        ).scalars().all()
        assert logs == []


async def test_candidate_revision_trigger_fences_redelete_and_reopen_aba(
    client,
    session_factory,
):
    from ktc.models import ExtractedPlaceCandidate, MatchStatus, YoutubeVideo

    async with session_factory() as s:
        s.add_all(
            [
                YoutubeVideo(
                    video_id="candidate-trigger-delete",
                    title="revision 삭제",
                    url="u",
                    channel_id="candidate-trigger",
                ),
                YoutubeVideo(
                    video_id="candidate-trigger-aba",
                    title="revision ABA",
                    url="u",
                    channel_id="candidate-trigger",
                ),
            ]
        )
        await s.commit()
        delete_candidate = ExtractedPlaceCandidate(
            video_id="candidate-trigger-delete",
            source_text="revision 삭제 근거",
            ai_place_name="revision 삭제 후보",
            match_status=MatchStatus.NEEDS_REVIEW,
        )
        aba_candidate = ExtractedPlaceCandidate(
            video_id="candidate-trigger-aba",
            source_text="revision ABA 근거",
            ai_place_name="revision ABA 후보",
            match_status=MatchStatus.NEEDS_REVIEW,
        )
        s.add_all([delete_candidate, aba_candidate])
        await s.commit()
        delete_candidate_id = delete_candidate.id
        aba_candidate_id = aba_candidate.id

    delete_operation_id = _client_operation_id()
    deleted = await client.delete(
        f"/api/v1/destinations/candidates/{delete_candidate_id}"
        f"?expected_revision=1&client_operation_id={delete_operation_id}"
    )
    assert deleted.status_code == 200
    assert deleted.json()["state_revision"] == 2
    stale_delete = await client.delete(
        f"/api/v1/destinations/candidates/{delete_candidate_id}"
        f"?expected_revision=1&client_operation_id={_client_operation_id()}"
    )
    assert stale_delete.status_code == 409
    assert stale_delete.json()["detail"] == {
        "code": "candidate_revision_conflict",
        "message": "후보가 다른 작업으로 변경되었습니다. 최신 상태를 다시 확인해 주세요.",
        "expected_revision": 1,
        "actual_revision": 2,
    }
    assert (
        await client.delete(
            f"/api/v1/destinations/candidates/{delete_candidate_id}"
            f"?expected_revision=2&client_operation_id={_client_operation_id()}"
        )
    ).status_code == 404

    ignored = await client.post(
        f"/api/v1/destinations/unmatched/{aba_candidate_id}/resolve",
        json={
            "client_operation_id": _client_operation_id(),
            "expected_revision": 1,
            "action": "ignore",
        },
    )
    assert ignored.status_code == 200
    assert ignored.json()["candidate"]["state_revision"] == 3
    reopened = await client.post(
        f"/api/v1/destinations/unmatched/{aba_candidate_id}/reopen",
        json={"undo_token": ignored.json()["undo"]["token"]},
    )
    assert reopened.status_code == 200
    assert reopened.json()["candidate"]["state_revision"] == 4

    stale_aba = await client.post(
        f"/api/v1/destinations/unmatched/{aba_candidate_id}/resolve",
        json={
            "client_operation_id": _client_operation_id(),
            "expected_revision": 1,
            "action": "ignore",
        },
    )
    assert stale_aba.status_code == 409
    assert stale_aba.json()["detail"]["code"] == "candidate_revision_conflict"
    fresh = await client.post(
        f"/api/v1/destinations/unmatched/{aba_candidate_id}/resolve",
        json={
            "client_operation_id": _client_operation_id(),
            "expected_revision": 4,
            "action": "ignore",
        },
    )
    assert fresh.status_code == 200
    assert fresh.json()["candidate"]["state_revision"] == 6


async def test_last_client_operation_requires_exact_candidate_snapshot(
    client,
    session_factory,
):
    """과거 JSONB 표식은 남아도 reopen/내부 mutation 뒤 exact ID는 노출하지 않는다."""
    from ktc.models import ExtractedPlaceCandidate, MatchStatus, YoutubeVideo
    from ktc.services import place_service

    async with session_factory() as s:
        s.add_all(
            [
                YoutubeVideo(
                    video_id="operation-fence-ignore",
                    title="ignore operation fence",
                    url="u",
                    channel_id="operation-fence",
                ),
                YoutubeVideo(
                    video_id="operation-fence-delete",
                    title="delete operation fence",
                    url="u",
                    channel_id="operation-fence",
                ),
            ]
        )
        await s.flush()
        ignored_candidate = ExtractedPlaceCandidate(
            video_id="operation-fence-ignore",
            source_text="ignore 근거",
            ai_place_name="ignore 후보",
            match_status=MatchStatus.NEEDS_REVIEW,
        )
        deleted_candidate = ExtractedPlaceCandidate(
            video_id="operation-fence-delete",
            source_text="delete 근거",
            ai_place_name="delete 후보",
            match_status=MatchStatus.NEEDS_REVIEW,
        )
        s.add_all([ignored_candidate, deleted_candidate])
        await s.commit()
        ignored_candidate_id = ignored_candidate.id
        deleted_candidate_id = deleted_candidate.id

    ignored_operation_id = _client_operation_id()
    ignored = await client.post(
        f"/api/v1/destinations/unmatched/{ignored_candidate_id}/resolve",
        json={
            "client_operation_id": ignored_operation_id,
            "expected_revision": 1,
            "action": "ignore",
        },
    )
    assert ignored.status_code == 200
    assert (
        ignored.json()["candidate"]["last_client_operation_id"]
        == ignored_operation_id
    )
    reopened_ignore = await client.post(
        f"/api/v1/destinations/unmatched/{ignored_candidate_id}/reopen",
        json={"undo_token": ignored.json()["undo"]["token"]},
    )
    assert reopened_ignore.status_code == 200
    assert reopened_ignore.json()["candidate"]["last_client_operation_id"] is None

    # MCP/내부 호출은 client operation ID를 만들지 않는다. 과거 표식을 JSONB에서
    # 지우지 않아도 revision fence 때문에 response-loss 복구 값은 계속 null이다.
    async with session_factory() as s:
        internal_candidate, _, _ = await place_service.resolve_candidate(
            s,
            candidate_id=ignored_candidate_id,
            action="ignore",
            reviewed_by="mcp-agent",
            reviewer_type="mcp",
            expected_revision=reopened_ignore.json()["candidate"][
                "state_revision"
            ],
            client_operation_id=None,
        )
        assert internal_candidate.provider_evidence_json["review"][
            "last_client_operation"
        ]["id"] == ignored_operation_id
    ignored_detail = await client.get(
        f"/api/v1/destinations/candidates/{ignored_candidate_id}/detail"
    )
    assert ignored_detail.status_code == 200
    assert ignored_detail.json()["candidate"]["last_client_operation_id"] is None
    assert ignored_detail.json()["list_item"]["last_client_operation_id"] is None

    delete_operation_id = _client_operation_id()
    deleted = await client.delete(
        f"/api/v1/destinations/candidates/{deleted_candidate_id}",
        params={
            "expected_revision": 1,
            "client_operation_id": delete_operation_id,
        },
    )
    assert deleted.status_code == 200
    deleted_detail = await client.get(
        f"/api/v1/destinations/candidates/{deleted_candidate_id}/detail"
    )
    assert (
        deleted_detail.json()["candidate"]["last_client_operation_id"]
        == delete_operation_id
    )
    reopened_delete = await client.post(
        f"/api/v1/destinations/unmatched/{deleted_candidate_id}/reopen",
        json={"undo_token": deleted.json()["undo"]["token"]},
    )
    assert reopened_delete.status_code == 200
    assert reopened_delete.json()["candidate"]["last_client_operation_id"] is None
    async with session_factory() as s:
        current = await s.get(ExtractedPlaceCandidate, deleted_candidate_id)
        assert current is not None
        current.review_note = "reopen 뒤 내부 메모 갱신"
        await s.commit()
        assert current.provider_evidence_json["review"]["last_client_operation"][
            "id"
        ] == delete_operation_id
    reopened_detail = await client.get(
        f"/api/v1/destinations/candidates/{deleted_candidate_id}/detail"
    )
    assert reopened_detail.status_code == 200
    assert reopened_detail.json()["candidate"]["last_client_operation_id"] is None
    assert reopened_detail.json()["list_item"]["last_client_operation_id"] is None


async def test_create_place_operation_marker_is_invalidated_by_place_only_update(
    client,
    session_factory,
):
    """후보가 그대로여도 연결 장소 revision이 바뀌면 marker와 undo는 stale이다."""
    from ktc.models import ExtractedPlaceCandidate, MatchStatus, TravelPlace, YoutubeVideo

    async with session_factory() as s:
        video = YoutubeVideo(
            video_id="operation-place-revision",
            title="place revision fence",
            url="u",
            channel_id="operation-place-revision",
        )
        s.add(video)
        await s.flush()
        candidate = ExtractedPlaceCandidate(
            video_id=video.video_id,
            source_text="새 장소 생성 근거",
            ai_place_name="새 장소 후보",
            match_status=MatchStatus.NEEDS_REVIEW,
        )
        s.add(candidate)
        await s.commit()
        candidate_id = candidate.id

    operation_id = _client_operation_id()
    resolved = await client.post(
        f"/api/v1/destinations/unmatched/{candidate_id}/resolve",
        json={
            "client_operation_id": operation_id,
            "expected_revision": 1,
            "action": "create_place",
            "corrected_name": "operation revision 장소",
            "latitude": 35.123,
            "longitude": 129.123,
            "duplicate_resolution": "create_new",
        },
    )
    assert resolved.status_code == 200
    body = resolved.json()
    place_id = body["place"]["place_id"]
    assert body["candidate"]["last_client_operation_id"] == operation_id
    async with session_factory() as s:
        candidate = await s.get(ExtractedPlaceCandidate, candidate_id)
        place = await s.get(TravelPlace, place_id)
        assert candidate is not None and place is not None
        marker = candidate.provider_evidence_json["review"][
            "last_client_operation"
        ]
        assert marker["result_candidate_revision"] == candidate.state_revision
        assert marker["matched_place_id"] == place_id
        assert marker["matched_place_revision"] == place.state_revision

    corrected = await client.post(
        f"/api/v1/destinations/{place_id}/correct",
        json={"description": "브라우저 작업 이후 장소 단독 보정"},
    )
    assert corrected.status_code == 200
    detail = await client.get(
        f"/api/v1/destinations/candidates/{candidate_id}/detail"
    )
    assert detail.status_code == 200
    assert detail.json()["candidate"]["last_client_operation_id"] is None
    assert detail.json()["list_item"]["last_client_operation_id"] is None
    stale_undo = await client.post(
        f"/api/v1/destinations/unmatched/{candidate_id}/reopen",
        json={"undo_token": body["undo"]["token"]},
    )
    assert stale_undo.status_code == 409
    assert stale_undo.json()["detail"]["code"] == "candidate_place_changed"


async def test_resolve_finalizer_rejects_place_change_after_enrichment_snapshot(
    client,
    session_factory,
    monkeypatch,
):
    """행정구역 보강 반환 뒤 place update가 끼면 old operation marker를 남기지 않는다."""
    from ktc.models import ExtractedPlaceCandidate, MatchStatus, TravelPlace, YoutubeVideo
    from ktc.services import place_service

    async with session_factory() as s:
        video = YoutubeVideo(
            video_id="operation-finalizer-place-race",
            title="finalizer place race",
            url="u",
            channel_id="operation-finalizer",
        )
        place = TravelPlace(
            name="finalizer 대상 장소",
            latitude=35.4,
            longitude=129.4,
        )
        s.add_all([video, place])
        await s.flush()
        candidate = ExtractedPlaceCandidate(
            video_id=video.video_id,
            source_text="finalizer 경합 근거",
            ai_place_name="finalizer 경합 후보",
            match_status=MatchStatus.NEEDS_REVIEW,
        )
        s.add(candidate)
        await s.commit()
        candidate_id = candidate.id
        place_id = place.place_id

    snapshot_ready = asyncio.Event()
    release_finalizer = asyncio.Event()
    original_enrich = place_service.enrich_place_admin_codes_postcommit

    async def pause_after_enrichment_snapshot(*args, **kwargs):
        enriched = await original_enrich(*args, **kwargs)
        assert enriched is not None
        snapshot_ready.set()
        await release_finalizer.wait()
        return enriched

    monkeypatch.setattr(
        place_service,
        "enrich_place_admin_codes_postcommit",
        pause_after_enrichment_snapshot,
    )
    operation_id = _client_operation_id()
    resolve_task = asyncio.create_task(
        client.post(
            f"/api/v1/destinations/unmatched/{candidate_id}/resolve",
            json={
                "client_operation_id": operation_id,
                "expected_revision": 1,
                "action": "match_existing",
                "place_id": place_id,
            },
        )
    )
    try:
        await asyncio.wait_for(snapshot_ready.wait(), timeout=5)
        async with session_factory() as writer_session:
            current_place = await writer_session.get(TravelPlace, place_id)
            assert current_place is not None
            current_place.description = "enrichment snapshot 이후 동시 보정"
            await writer_session.commit()
        release_finalizer.set()
        response = await asyncio.wait_for(resolve_task, timeout=5)
    finally:
        release_finalizer.set()
        if not resolve_task.done():
            resolve_task.cancel()
        await asyncio.gather(resolve_task, return_exceptions=True)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "candidate_place_changed"
    async with session_factory() as s:
        candidate = await s.get(ExtractedPlaceCandidate, candidate_id)
        assert candidate is not None
        assert candidate.match_status == MatchStatus.USER_CORRECTED.value
        review = candidate.provider_evidence_json["review"]
        assert review["resolutions"][-1]["client_operation_id"] == operation_id
        assert "last_client_operation" not in review
    detail = await client.get(
        f"/api/v1/destinations/candidates/{candidate_id}/detail"
    )
    assert detail.status_code == 200
    assert detail.json()["candidate"]["last_client_operation_id"] is None


async def test_video_exclude_rolls_back_cleanup_and_tombstone_when_audit_fails(
    client,
    session_factory,
    monkeypatch,
):
    from sqlalchemy import select

    from ktc.api import routes
    from ktc.models import (
        AuditLog,
        ExtractedPlaceCandidate,
        FeatureExport,
        FeatureExportOperation,
        FeatureExportStatus,
        GroundingStatus,
        MatchStatus,
        TravelPlace,
        VideoPlaceMapping,
        YoutubeVideo,
    )
    from ktc.services import feature_export_service

    async with session_factory() as s:
        video = YoutubeVideo(
            video_id="video-exclude-audit-rollback",
            title="영상 제외 감사 실패",
            url="u",
            channel_id="video-exclude-audit-rollback",
        )
        place = TravelPlace(
            name="영상 제외 감사 실패 장소",
            latitude=35.0,
            longitude=129.0,
            is_geocoded=True,
        )
        s.add_all([video, place])
        await s.commit()
        candidate = ExtractedPlaceCandidate(
            video_id=video.video_id,
            source_text="영상 제외 감사 실패 근거",
            ai_place_name=place.name,
            match_status=MatchStatus.MATCHED,
            grounding_status=GroundingStatus.VERIFIED_RAW.value,
            matched_place_id=place.place_id,
            feature_export_status=FeatureExportStatus.READY.value,
        )
        s.add(candidate)
        await s.flush()
        mapping = VideoPlaceMapping(
            video_id=video.video_id,
            place_id=place.place_id,
            place_candidate_id=candidate.id,
            ai_summary="영상 제외 감사 실패 매핑",
        )
        s.add(mapping)
        await s.commit()
        candidate_id = candidate.id
        place_id = place.place_id
        mapping_id = mapping.id
        assert await feature_export_service.sync_feature_exports(s) == 1

    original_record = routes.audit_service.record

    async def fail_after_flush(session, **kwargs):
        assert kwargs.get("commit") is False
        await original_record(session, **kwargs)
        await session.flush()
        raise RuntimeError("video exclude audit unavailable after flush")

    monkeypatch.setattr(routes.audit_service, "record", fail_after_flush)
    with pytest.raises(RuntimeError, match="video exclude audit unavailable"):
        await client.post(
            "/api/v1/destinations/videos/video-exclude-audit-rollback/exclude",
            json={"reason": "rollback되어야 함"},
        )

    async with session_factory() as s:
        current_video = await s.get(YoutubeVideo, video.video_id)
        current_candidate = await s.get(ExtractedPlaceCandidate, candidate_id)
        ledger = (
            await s.execute(
                select(FeatureExport).where(
                    FeatureExport.candidate_id == candidate_id
                )
            )
        ).scalar_one()
        assert current_video is not None
        assert current_video.is_excluded is False
        assert current_candidate is not None
        assert current_candidate.deleted_at is None
        assert current_candidate.match_status == MatchStatus.MATCHED.value
        assert current_candidate.matched_place_id == place_id
        assert await s.get(TravelPlace, place_id) is not None
        assert await s.get(VideoPlaceMapping, mapping_id) is not None
        assert ledger.operation == FeatureExportOperation.UPSERT.value
        logs = (
            await s.execute(
                select(AuditLog).where(
                    AuditLog.action == "video.exclude",
                    AuditLog.target_id == video.video_id,
                )
            )
        ).scalars().all()
        assert logs == []


async def test_candidate_delete_serializes_with_concurrent_ignore_api(
    client, session_factory
):
    from ktc.models import ExtractedPlaceCandidate, MatchStatus, YoutubeVideo

    async with session_factory() as s:
        s.add(
            YoutubeVideo(
                video_id="v-delete-api-race",
                title="t",
                url="u",
                channel_id="c-delete-api-race",
            )
        )
        await s.commit()
        candidate = ExtractedPlaceCandidate(
            video_id="v-delete-api-race",
            source_text="s",
            ai_place_name="동시 삭제 제외 API",
            match_status=MatchStatus.NEEDS_REVIEW,
        )
        s.add(candidate)
        await s.commit()
        candidate_id = candidate.id

    delete_response, ignore_response = await asyncio.wait_for(
        asyncio.gather(
            client.delete(
                f"/api/v1/destinations/candidates/{candidate_id}"
                f"?expected_revision=1&client_operation_id={_client_operation_id()}"
            ),
            client.post(
                f"/api/v1/destinations/unmatched/{candidate_id}/resolve",
                json={
                    "client_operation_id": _client_operation_id(),
                    "expected_revision": 1,
                    "action": "ignore",
                },
            ),
        ),
        timeout=5,
    )

    if delete_response.status_code == 200:
        # 후보 행을 먼저 soft delete한 뒤 도착한 stale resolve도 다른 선처리와 같은
        # typed conflict 계약으로 거부된다.
        assert ignore_response.status_code == 409
        expected_deleted = True
    else:
        assert delete_response.status_code == 409
        assert ignore_response.status_code == 200
        expected_deleted = False

    async with session_factory() as s:
        current = await s.get(ExtractedPlaceCandidate, candidate_id)
        assert current is not None
        if expected_deleted:
            assert current.deleted_at is not None
            assert current.match_status == MatchStatus.NEEDS_REVIEW.value
        else:
            assert current.deleted_at is None
            assert current.match_status == MatchStatus.IGNORED.value


async def test_destination_export_formats(client, session_factory):
    from ktc.models import TravelPlace, VideoPlaceMapping, YoutubeVideo

    async with session_factory() as s:
        video = YoutubeVideo(
            video_id="v-export",
            title="제주 여행",
            url="https://youtu.be/export",
            channel_id="uc-export",
            channel_name="제주 채널",
        )
        place = TravelPlace(
            name="월정리 해변",
            latitude=33.5563,
            longitude=126.7958,
            category="해변",
            official_address="제주특별자치도 제주시 구좌읍 월정리",
            is_geocoded=True,
        )
        other = TravelPlace(name="다른 장소", latitude=37.5, longitude=127.0)
        s.add_all([video, place, other])
        await s.commit()
        await s.refresh(place)
        await s.refresh(other)
        s.add(
            VideoPlaceMapping(
                video_id=video.video_id,
                place_id=place.place_id,
                ai_summary="월정리 언급",
                timestamp_start="00:02:00",
            )
        )
        await s.commit()

    xlsx = await client.get(f"/api/v1/destinations/export?format=xlsx&ids={place.place_id}")
    assert xlsx.status_code == 200
    assert xlsx.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert re.fullmatch(
        r'attachment; filename="kor-travel-concierge-places-selected-1-sort-mention-count-\d{8}T\d{6}Z\.xlsx"',
        xlsx.headers["content-disposition"],
    )
    with ZipFile(BytesIO(xlsx.content)) as archive:
        worksheet = archive.read("xl/worksheets/sheet1.xml").decode()
    assert "월정리 해변" in worksheet
    assert "제주 채널" in worksheet
    assert "다른 장소" not in worksheet

    gpx = await client.get(f"/api/v1/destinations/export?format=gpx&ids={place.place_id}")
    assert gpx.status_code == 200
    assert "월정리 해변" in gpx.text
    assert "제주 채널" in gpx.text

    kml = await client.get(f"/api/v1/destinations/export?format=kml&ids={place.place_id}")
    assert kml.status_code == 200
    assert "126.7958000,33.5563000,0" in kml.text


async def test_destination_export_caps_limit_and_serializes_in_thread(client, monkeypatch):
    from ktc.api import routes

    captured: dict[str, int] = {}

    async def fake_list_place_summaries(
        session, *, sort, place_ids, limit, geocoded_only=False
    ):
        captured["limit"] = limit
        captured["geocoded_only"] = geocoded_only
        return []

    def fake_build_place_export(summaries, export_format):
        captured["thread_id"] = threading.get_ident()
        return b"export", "text/plain", "export.txt"

    monkeypatch.setattr(
        routes.place_service, "list_place_summaries", fake_list_place_summaries
    )
    monkeypatch.setattr(
        routes.place_export_service, "build_place_export", fake_build_place_export
    )

    main_thread_id = threading.get_ident()
    response = await client.get("/api/v1/destinations/export?format=gpx&limit=999999")

    assert response.status_code == 200
    assert response.content == b"export"
    assert captured["limit"] == routes.EXPORT_DESTINATION_LIMIT_MAX
    # export는 기본적으로 확정 좌표만 내보낸다(T-189, 미검증 좌표 유출 방지).
    assert captured["geocoded_only"] is True
    assert captured["thread_id"] != main_thread_id
    assert re.fullmatch(
        r'attachment; filename="export-all-0-sort-mention-count-\d{8}T\d{6}Z\.txt"',
        response.headers["content-disposition"],
    )


async def test_destination_export_geocoded_only_filters_unverified(
    client, session_factory
):
    """T-189: export 기본값은 확정 좌표(is_geocoded)만 내보내고, false로 opt-out한다."""
    from ktc.models import TravelPlace

    async with session_factory() as s:
        s.add_all(
            [
                TravelPlace(
                    name="확정 좌표 장소",
                    latitude=33.5,
                    longitude=126.5,
                    is_geocoded=True,
                ),
                TravelPlace(
                    name="미확정 좌표 장소",
                    latitude=37.5,
                    longitude=127.0,
                    is_geocoded=False,
                ),
            ]
        )
        await s.commit()

    # 기본값(geocoded_only=true): 미확정 좌표 장소는 제외된다.
    default_gpx = await client.get("/api/v1/destinations/export?format=gpx")
    assert default_gpx.status_code == 200
    assert "확정 좌표 장소" in default_gpx.text
    assert "미확정 좌표 장소" not in default_gpx.text

    # opt-out(geocoded_only=false): 미확정 좌표까지 포함한다.
    optout_gpx = await client.get(
        "/api/v1/destinations/export?format=gpx&geocoded_only=false"
    )
    assert optout_gpx.status_code == 200
    assert "확정 좌표 장소" in optout_gpx.text
    assert "미확정 좌표 장소" in optout_gpx.text


async def test_operations_endpoints_return_runs_audits_and_storage(client, session_factory):
    from ktc.models import AssetType, MediaAsset
    from ktc.services import audit_service, crawl_run_service

    async with session_factory() as s:
        run = await crawl_run_service.create_run(
            s, job_type="harvest", source="web", target_type="keyword", target_id="부산"
        )
        await crawl_run_service.append_status_log(
            s, run.id, "YouTube를 검색 중입니다.", progress=0.5
        )
        await crawl_run_service.mark_failed(s, run.id, error="boom")
        await audit_service.record(
            s,
            actor_type="mcp",
            action="place.correct",
            target_type="travel_place",
            target_id="1",
            payload={"ok": True},
        )
        s.add(
            MediaAsset(
                asset_type=AssetType.FRAME,
                storage_provider="rustfs",
                bucket="ktc-frames",
                object_key="frames/a.jpg",
                object_uri="rustfs://frames/a.jpg",
                size_bytes=10,
            )
        )
        await s.commit()

    runs = await client.get("/api/v1/runs")
    assert runs.status_code == 200
    assert runs.json()["items"][0]["state"] == "failed"
    assert "작업이 실패했습니다" in runs.json()["items"][0]["current_message"]
    assert runs.json()["items"][0]["status_logs"][-1]["level"] == "error"

    audits = await client.get("/api/v1/audit-logs")
    assert audits.status_code == 200
    assert audits.json()[0]["action"] == "place.correct"

    storage = await client.get("/api/v1/storage/rustfs")
    assert storage.status_code == 200
    assert storage.json()["retention_policy"] == "infinite"
    assert storage.json()["assets"][0]["count"] == 1


async def test_resolve_candidate_and_deep_research(client, session_factory):
    from ktc.models import (
        ExtractedPlaceCandidate,
        FeatureExportStatus,
        MatchStatus,
        TravelPlace,
        YoutubeVideo,
    )

    async with session_factory() as s:
        place = TravelPlace(name="해운대", latitude=35.1587, longitude=129.1604)
        video = YoutubeVideo(video_id="v2", title="t", url="u", channel_id="c")
        s.add_all([place, video])
        await s.commit()
        candidate = ExtractedPlaceCandidate(
            video_id="v2",
            source_text="해운대",
            ai_place_name="해운대",
            match_status=MatchStatus.NEEDS_REVIEW,
        )
        s.add(candidate)
        await s.commit()
        await s.refresh(place)
        await s.refresh(candidate)

    operation_id = _client_operation_id()
    resolved = await client.post(
        f"/api/v1/destinations/unmatched/{candidate.id}/resolve",
        json={
            "client_operation_id": operation_id,
            "expected_revision": 1,
            "action": "match_existing",
            "place_id": place.place_id,
        },
    )
    assert resolved.status_code == 200
    assert resolved.json()["client_operation_id"] == operation_id
    assert resolved.json()["candidate"]["last_client_operation_id"] == operation_id
    assert resolved.json()["candidate"]["match_status"] == MatchStatus.USER_CORRECTED
    assert resolved.json()["candidate"]["feature_export_status"] == FeatureExportStatus.READY
    detail = await client.get(
        f"/api/v1/destinations/candidates/{candidate.id}/detail"
    )
    assert detail.status_code == 200
    assert detail.json()["candidate"]["last_client_operation_id"] == operation_id
    assert detail.json()["list_item"]["last_client_operation_id"] == operation_id

    research = await client.post(f"/api/v1/destinations/{place.place_id}/deep-research", json={})
    assert research.status_code == 200
    assert research.json()["state"] == "pending"


async def test_resolve_candidate_rejects_google_without_mutation(
    client, session_factory
):
    from sqlalchemy import select

    from ktc.models import ExtractedPlaceCandidate, MatchStatus, TravelPlace, YoutubeVideo

    async with session_factory() as s:
        s.add(YoutubeVideo(video_id="v-google-api", title="t", url="u", channel_id="c"))
        await s.commit()
        candidate = ExtractedPlaceCandidate(
            video_id="v-google-api",
            source_text="s",
            ai_place_name="Google 저장 금지",
            match_status=MatchStatus.NEEDS_REVIEW,
            provider_evidence_json={"transcript": {"segment": "보존"}},
        )
        s.add(candidate)
        await s.commit()
        await s.refresh(candidate)
        candidate_id = candidate.id

    response = await client.post(
        f"/api/v1/destinations/unmatched/{candidate_id}/resolve",
        json={
            "client_operation_id": _client_operation_id(),
            "expected_revision": 1,
            "action": "create_place",
            "corrected_name": "Google 저장 금지",
            "latitude": 37.0,
            "longitude": 127.0,
            "api_source": "google",
            "selected_hit": {
                "provider": "google",
                "native_id": "google-place-id",
                "query": "Google 저장 금지",
                "searched_at": "2026-07-13T01:00:00Z",
                "selected_at": "2026-07-13T01:00:01Z",
                "name": "Google 저장 금지",
                "latitude": 37.0,
                "longitude": 127.0,
            },
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "provider_persistence_disabled"
    async with session_factory() as s:
        candidate = await s.get(ExtractedPlaceCandidate, candidate_id)
        assert candidate is not None
        assert candidate.match_status == MatchStatus.NEEDS_REVIEW
        assert candidate.matched_place_id is None
        assert candidate.reviewed_at is None
        assert candidate.provider_evidence_json == {
            "transcript": {"segment": "보존"}
        }
        assert (await s.execute(select(TravelPlace))).scalars().all() == []
        logs = await audit_service.list_recent(s)
        assert all(log.action != "candidate.resolve" for log in logs)


async def test_resolve_candidate_rejects_invalid_selected_hit_timestamps(client):
    selected_hit = {
        "provider": "kakao",
        "native_id": "kakao-timestamp-1",
        "query": "타임스탬프 검증",
        "searched_at": "2026-07-13T01:00:00Z",
        "selected_at": "2026-07-13T01:00:01Z",
        "name": "타임스탬프 검증 장소",
        "latitude": 37.0,
        "longitude": 127.0,
    }
    payload = {
        "client_operation_id": _client_operation_id(),
        "expected_revision": 1,
        "action": "create_place",
        "corrected_name": "타임스탬프 검증 장소",
        "latitude": 37.0,
        "longitude": 127.0,
        "selected_hit": selected_hit,
    }

    for invalid_hit, expected_message in (
        ({**selected_hit, "searched_at": "2026-07-13T01:00:00"}, "timezone"),
        ({**selected_hit, "selected_at": "2026-07-13T01:00:01"}, "timezone"),
        (
            {
                **selected_hit,
                "searched_at": "2026-07-13T01:00:02Z",
                "selected_at": "2026-07-13T01:00:01Z",
            },
            "선택 시각은 검색 시각보다",
        ),
    ):
        response = await client.post(
            "/api/v1/destinations/unmatched/999999/resolve",
            json={**payload, "selected_hit": invalid_hit},
        )

        assert response.status_code == 422
        assert expected_message in response.text


async def test_resolve_candidate_nearby_409_then_explicit_decisions_and_audit(
    client, session_factory
):
    from sqlalchemy import select

    from ktc.models import (
        ExtractedPlaceCandidate,
        MatchStatus,
        TravelPlace,
        YoutubeVideo,
    )

    async with session_factory() as s:
        existing = TravelPlace(
            name="기존 관광지",
            latitude=35.1587,
            longitude=129.1604,
            is_geocoded=True,
        )
        s.add_all(
            [
                existing,
                YoutubeVideo(
                    video_id="v-near-api-merge", title="t", url="u", channel_id="c"
                ),
                YoutubeVideo(
                    video_id="v-near-api-create", title="t", url="u", channel_id="c"
                ),
            ]
        )
        await s.commit()
        merge_candidate = ExtractedPlaceCandidate(
            video_id="v-near-api-merge",
            source_text="s",
            ai_place_name="유사 관광지",
            match_status=MatchStatus.NEEDS_REVIEW,
            provider_evidence_json={"transcript": {"segment": "보존"}},
        )
        create_candidate = ExtractedPlaceCandidate(
            video_id="v-near-api-create",
            source_text="s",
            ai_place_name="독립 관광지",
            match_status=MatchStatus.NEEDS_REVIEW,
        )
        s.add_all([merge_candidate, create_candidate])
        await s.commit()
        await s.refresh(existing)
        await s.refresh(merge_candidate)
        await s.refresh(create_candidate)
        existing_id = existing.place_id
        merge_candidate_id = merge_candidate.id
        create_candidate_id = create_candidate.id

    selected_hit = {
        "provider": "kakao",
        "native_id": "kakao-near-123",
        "query": "새 관광지",
        "searched_at": "2026-07-13T01:00:00Z",
        "selected_at": "2026-07-13T01:00:02Z",
        "name": "새관광지 원본",
        "address": "부산 해운대구 원본동 1",
        "road_address": "부산 해운대구 원본로 1",
        "latitude": 35.1588,
        "longitude": 129.1604,
        "category": "여행 > 관광지",
    }
    payload = {
        "client_operation_id": _client_operation_id(),
        "expected_revision": 1,
        "action": "create_place",
        "corrected_name": "새 관광지",
        "official_address": "부산광역시 해운대구 수정동 1",
        "road_address": "부산광역시 해운대구 수정로 1",
        "latitude": 35.1588,
        "longitude": 129.1604,
        "selected_hit": selected_hit,
    }

    conflict = await client.post(
        f"/api/v1/destinations/unmatched/{merge_candidate_id}/resolve",
        json=payload,
    )
    assert conflict.status_code == 409
    detail = conflict.json()["detail"]
    assert detail["code"] == "nearby_place_confirmation_required"
    assert detail["nearby_places"][0]["place_id"] == existing_id
    assert detail["nearby_places"][0]["distance_m"] < 100
    assert detail["nearby_places"][0]["name_compatible"] is False

    merged = await client.post(
        f"/api/v1/destinations/unmatched/{merge_candidate_id}/resolve",
        json={
            **payload,
            "duplicate_resolution": "merge_existing",
            "duplicate_place_id": existing_id,
        },
    )
    assert merged.status_code == 200
    assert merged.json()["place"]["place_id"] == existing_id

    created = await client.post(
        f"/api/v1/destinations/unmatched/{create_candidate_id}/resolve",
        json={
            **payload,
            "client_operation_id": _client_operation_id(),
            "corrected_name": "독립 관광지",
            "duplicate_resolution": "create_new",
        },
    )
    assert created.status_code == 200
    assert created.json()["place"]["place_id"] != existing_id
    assert created.json()["place"]["api_source"] == "kakao"

    async with session_factory() as s:
        places = (await s.execute(select(TravelPlace))).scalars().all()
        assert len(places) == 2
        candidate = await s.get(ExtractedPlaceCandidate, merge_candidate_id)
        assert candidate is not None
        assert candidate.matched_place_id == existing_id
        assert candidate.provider_evidence_json["transcript"] == {
            "segment": "보존"
        }
        logs = [
            log
            for log in await audit_service.list_recent(s)
            if log.action == "candidate.resolve"
            and log.target_id == str(merge_candidate_id)
        ]
        assert len(logs) == 1
        audit_payload = json.loads(logs[0].payload_json)
        assert audit_payload["client_operation_id"] == payload["client_operation_id"]
        audited_hit = audit_payload["request"]["selected_hit"]
        assert audited_hit["provider"] == "kakao"
        assert audited_hit["native_id"] == "kakao-near-123"
        assert audited_hit["query"] == "새 관광지"
        assert audited_hit["name"] == "새관광지 원본"
        last_operation = candidate.provider_evidence_json["review"][
            "last_client_operation"
        ]
        assert last_operation["id"] == payload["client_operation_id"]
        assert last_operation["action"] == "create_place"
        assert isinstance(last_operation["timestamp"], str)
        latest_resolution = candidate.provider_evidence_json["review"][
            "resolutions"
        ][-1]
        assert latest_resolution["client_operation_id"] == payload[
            "client_operation_id"
        ]
        assert audited_hit["searched_at"]
        assert audited_hit["selected_at"]
        resolution = audit_payload["resolution"]
        assert resolution["selection"]["original"]["name"] == "새관광지 원본"
        assert resolution["final"]["name"] == "기존 관광지"
        assert resolution["nearby"]["decision"] == "merge_existing"
        assert resolution["nearby"]["selected_place_id"] == existing_id


async def test_settings_post_saves_api_key_and_exposes_set_flag(client, session):
    resp = await client.post(
        "/api/v1/settings", json={"google_places_api_key": "g-secret-123"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["settings"]["api_keys"]["google_places_api_key"]["set"] is True
    # 값은 system_settings에 저장되지만 GET 응답에는 노출되지 않는다.
    assert (
        await settings_service.get_setting(session, "google_places_api_key")
        == "g-secret-123"
    )
    got = await client.get("/api/v1/settings")
    assert got.json()["api_keys"]["google_places_api_key"]["set"] is True
    assert "g-secret-123" not in got.text


async def test_settings_post_empty_key_does_not_overwrite(client, session):
    await client.post("/api/v1/settings", json={"google_places_api_key": "kept-value"})
    resp = await client.post("/api/v1/settings", json={"google_places_api_key": ""})
    assert resp.status_code == 200
    # 빈 값으로 덮어쓰지 않는다(미입력=변경 없음).
    assert (
        await settings_service.get_setting(session, "google_places_api_key")
        == "kept-value"
    )


async def test_settings_post_masks_secret_in_audit(client, session):
    resp = await client.post(
        "/api/v1/settings", json={"deepseek_api_key": "ds-secret-xyz"}
    )
    assert resp.status_code == 200
    logs = await audit_service.list_recent(session)
    settings_logs = [log for log in logs if log.action == "settings.update"]
    assert settings_logs
    assert "ds-secret-xyz" not in settings_logs[0].payload_json
    assert "***" in settings_logs[0].payload_json


async def test_run_labels_human_readable(client, session):
    from ktc.models import CrawlRun, RunSource, RunState, YoutubeChannel

    session.add(YoutubeChannel(channel_id="UClabeltest", title="빵이네tv"))
    session.add(
        CrawlRun(
            job_type="harvest",
            source=RunSource.WEB,
            target_type="channel",
            target_id="UClabeltest",
            state=RunState.DONE,
            progress=1.0,
        )
    )
    session.add(
        CrawlRun(
            job_type="harvest",
            source=RunSource.WEB,
            target_type="keyword",
            target_id="부산 여행",
            state=RunState.DONE,
            progress=1.0,
        )
    )
    session.add(
        CrawlRun(
            job_type="source_scan",
            source=RunSource.SCHEDULER,
            target_type="channel",
            target_id="UCunknownxyz",
            state=RunState.DONE,
            progress=1.0,
        )
    )
    await session.commit()

    runs = (await client.get("/api/v1/runs?limit=20")).json()["items"]
    by = {(r["target_type"], r["target_id"]): r for r in runs}
    chan = by[("channel", "UClabeltest")]
    assert chan["target_type_label"] == "유튜버"
    assert chan["target_label"] == "빵이네tv"
    assert chan["job_type_label"] == "수집"
    kw = by[("keyword", "부산 여행")]
    assert kw["target_type_label"] == "검색어"
    assert kw["target_label"] == "부산 여행"
    unknown = by[("channel", "UCunknownxyz")]
    assert unknown["target_label"] == "UCunknownxyz"  # 제목 없으면 ID 폴백
    assert unknown["job_type_label"] == "예약 스캔"


async def test_runs_job_types_filter(client, session):
    from ktc.models import CrawlRun, RunSource, RunState

    session.add(
        CrawlRun(
            job_type="harvest",
            source=RunSource.WEB,
            target_type="keyword",
            target_id="필터수집",
            state=RunState.DONE,
            progress=1.0,
        )
    )
    session.add(
        CrawlRun(
            job_type="source_scan",
            source=RunSource.SCHEDULER,
            target_type="source_targets",
            target_id="active",
            state=RunState.DONE,
            progress=1.0,
        )
    )
    await session.commit()

    only_harvest = (
        await client.get("/api/v1/runs?job_types=harvest&limit=50")
    ).json()["items"]
    types = {r["job_type"] for r in only_harvest}
    assert "harvest" in types
    assert "source_scan" not in types

    everything = (await client.get("/api/v1/runs?limit=50")).json()["items"]
    assert "source_scan" in {r["job_type"] for r in everything}


async def test_run_queue_static_route_uses_run_summary_contract(client, session):
    from ktc.models import (
        CrawlRun,
        RunAttention,
        RunSource,
        RunState,
        YoutubeChannel,
    )

    session.add(YoutubeChannel(channel_id="UCqueue", title="대기열 채널"))
    session.add(
        CrawlRun(
            job_type="harvest",
            source=RunSource.WEB,
            target_type="channel",
            target_id="UCqueue",
            state=RunState.PENDING,
            progress=0.0,
            status_log_json=json.dumps(
                [{"timestamp": "2026-07-13T00:00:00Z", "message": "파싱 금지"}]
            ),
            result_json="{invalid-json",
        )
    )
    session.add(
        CrawlRun(
            job_type="video_analysis",
            source=RunSource.WEB,
            target_type="video",
            target_id="failed-video",
            state=RunState.FAILED,
            progress=0.5,
            attention=RunAttention.OPEN,
        )
    )
    session.add(
        CrawlRun(
            job_type="source_scan",
            source=RunSource.SCHEDULER,
            target_type="source_targets",
            target_id="active",
            state=RunState.PENDING,
            progress=0.0,
        )
    )
    await session.commit()

    response = await client.get("/api/v1/runs/queue")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "items",
        "running_count",
        "pending_count",
        "open_attention_count",
        "has_more",
        "user_job_types",
    }
    assert body["running_count"] == 0
    assert body["pending_count"] == 1
    assert body["open_attention_count"] == 1
    assert body["has_more"] is False
    assert body["user_job_types"] == [
        "harvest",
        "poi_batch",
        "deep_research",
        "video_analysis",
    ]
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert set(item) == {
        "job_id",
        "job_type",
        "job_type_label",
        "lane",
        "source",
        "target_type",
        "target_type_label",
        "target_id",
        "target_label",
        "state",
        "progress",
        "current_message",
        "max_videos",
        "default_category_code",
        "default_category_label",
        "status_logs",
        "retry_count",
        "last_error",
        "restart_of_run_id",
        "attention",
        "result",
        "created_at",
        "started_at",
        "finished_at",
    }
    assert item["job_type"] == "harvest"
    assert item["state"] == "pending"
    assert item["target_label"] == "대기열 채널"
    assert item["status_logs"] == []
    assert item["result"] is None


async def test_run_queue_caps_large_backlog_and_reports_exact_counts(client, session):
    from ktc.models import CrawlRun, RunSource, RunState
    from ktc.services import crawl_run_service

    running = [
        CrawlRun(
            job_type="deep_research",
            source=RunSource.WEB,
            state=RunState.RUNNING,
            progress=0.5,
        )
        for _ in range(2)
    ]
    pending = [
        CrawlRun(
            job_type="harvest",
            source=RunSource.WEB,
            state=RunState.PENDING,
            progress=0.0,
        )
        for _ in range(crawl_run_service.RUN_QUEUE_ITEM_LIMIT + 3)
    ]
    session.add_all([*running, *pending])
    await session.commit()

    response = await client.get("/api/v1/runs/queue")

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == crawl_run_service.RUN_QUEUE_ITEM_LIMIT
    assert body["running_count"] == 2
    assert body["pending_count"] == crawl_run_service.RUN_QUEUE_ITEM_LIMIT + 3
    assert body["open_attention_count"] == 0
    assert body["has_more"] is True
    assert [item["job_id"] for item in body["items"][:2]] == [
        str(item.id) for item in running
    ]


async def test_runs_terminal_attention_filter_finds_failure_beyond_active_backlog(
    client, session
):
    from ktc.models import CrawlRun, RunAttention, RunSource, RunState

    failed = CrawlRun(
        job_type="harvest",
        source=RunSource.WEB,
        target_type="keyword",
        target_id="old-open-attention",
        state=RunState.FAILED,
        attention=RunAttention.OPEN,
        progress=0.5,
    )
    session.add(failed)
    await session.flush()
    session.add_all(
        [
            CrawlRun(
                job_type="harvest",
                source=RunSource.WEB,
                state=RunState.PENDING,
                attention=RunAttention.OPEN,
                progress=0.0,
            )
            for _ in range(81)
        ]
    )
    session.add_all(
        [
            CrawlRun(
                job_type="harvest",
                source=RunSource.WEB,
                state=RunState.DONE,
                attention=RunAttention.ACKNOWLEDGED,
                progress=1.0,
            )
            for _ in range(81)
        ]
    )
    done_open = CrawlRun(
        job_type="harvest",
        source=RunSource.WEB,
        state=RunState.DONE,
        attention=RunAttention.OPEN,
        progress=1.0,
    )
    cancelled_open = CrawlRun(
        job_type="video_analysis",
        source=RunSource.WEB,
        state=RunState.CANCELLED,
        attention=RunAttention.OPEN,
        progress=0.2,
    )
    internal_open = CrawlRun(
        job_type="source_scan",
        source=RunSource.SCHEDULER,
        state=RunState.FAILED,
        attention=RunAttention.OPEN,
        progress=0.5,
    )
    session.add_all([done_open, cancelled_open, internal_open])
    await session.commit()

    response = await client.get(
        "/api/v1/runs",
        params={
            "terminal": "true",
            "attention": "open",
            "user_jobs_only": "true",
            "limit": 2,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["has_more"] is True
    assert body["next_cursor"]
    assert [item["job_id"] for item in body["items"]] == [
        str(cancelled_open.id),
        str(done_open.id),
    ]

    next_response = await client.get(
        "/api/v1/runs",
        params={
            "terminal": "true",
            "attention": "open",
            "user_jobs_only": "true",
            "limit": 2,
            "cursor": body["next_cursor"],
        },
    )
    assert next_response.status_code == 200
    next_body = next_response.json()
    assert next_body["total"] == 3
    assert next_body["has_more"] is False
    assert [item["job_id"] for item in next_body["items"]] == [str(failed.id)]
    assert all(
        item["attention"] == "open"
        and item["state"] in {"done", "failed", "cancelled"}
        for item in [*body["items"], *next_body["items"]]
    )


async def test_runs_rejects_ambiguous_user_jobs_and_explicit_types(client):
    response = await client.get(
        "/api/v1/runs",
        params={"user_jobs_only": "true", "job_types": "harvest"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "user_jobs_only와 job_types는 함께 사용할 수 없습니다"
    )


async def test_run_now_enqueues_and_increments(client, session):
    from ktc.models import SourceTarget

    target = SourceTarget(
        target_type="keyword",
        source_value="지금 진행 테스트",
        is_active=True,
        scan_interval_minutes=60,
        max_runs=0,
        run_count=0,
    )
    session.add(target)
    await session.commit()
    await session.refresh(target)
    tid = target.id

    resp = await client.post(f"/api/v1/source-targets/{tid}/run-now")
    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] is True
    assert body["job_id"] is not None

    await session.refresh(target)
    assert target.run_count == 1

    runs = (
        await client.get("/api/v1/runs?job_types=harvest&limit=50")
    ).json()["items"]
    assert any(r["target_id"] == "지금 진행 테스트" for r in runs)

    # 같은 작업이 이미 active → 중복 생성하지 않음
    again = (await client.post(f"/api/v1/source-targets/{tid}/run-now")).json()
    assert again["created"] is False

    missing = await client.post("/api/v1/source-targets/999999/run-now")
    assert missing.status_code == 404


async def test_source_target_videos_union(client, session):
    from ktc.models import (
        CrawlRun,
        RunSource,
        RunState,
        SourceTarget,
        YoutubeChannel,
        YoutubeVideo,
    )

    session.add(YoutubeChannel(channel_id="UCunion", title="유니온 채널"))
    for vid in ("uvid1", "uvid2", "uvid3"):
        session.add(
            YoutubeVideo(
                video_id=vid,
                title=f"영상 {vid}",
                url=f"https://youtu.be/{vid}",
                channel_id="UCunion",
            )
        )
    target = SourceTarget(
        target_type="keyword",
        source_value="누적 키워드",
        is_active=True,
        scan_interval_minutes=60,
    )
    session.add(target)
    session.add(
        CrawlRun(
            job_type="harvest",
            source=RunSource.SCHEDULER,
            target_type="keyword",
            target_id="누적 키워드",
            state=RunState.DONE,
            progress=1.0,
            result_json='{"video_ids": ["uvid1", "uvid2"]}',
        )
    )
    session.add(
        CrawlRun(
            job_type="harvest",
            source=RunSource.SCHEDULER,
            target_type="keyword",
            target_id="누적 키워드",
            state=RunState.DONE,
            progress=1.0,
            result_json='{"video_ids": ["uvid3"]}',
        )
    )
    await session.commit()
    await session.refresh(target)

    videos = (
        await client.get(f"/api/v1/source-targets/{target.id}/videos")
    ).json()
    assert {v["video_id"] for v in videos} == {"uvid1", "uvid2", "uvid3"}
