"""API 엔드포인트 통합 테스트.

`get_session` 의존성을 테스트 엔진으로 오버라이드해 ASGI 앱을 직접 호출한다.
"""

from __future__ import annotations

import json
import re
import threading
from io import BytesIO
from zipfile import ZipFile

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from ktc.core.database import get_repeatable_read_session, get_session
from ktc.services import audit_service, settings_service
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
        detail.json()["candidate"]["feature_export_status"]
        == FeatureExportStatus.PENDING
    )


async def test_candidate_and_place_detail_and_delete(client, session_factory):
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
    assert any(c["ai_place_name"] == "자갈치시장" for c in dj["sibling_candidates"])

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

    deleted = await client.delete(f"/api/v1/destinations/candidates/{cand_id}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    gone = await client.get(f"/api/v1/destinations/candidates/{cand_id}/detail")
    assert gone.status_code == 404


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

    async def fake_list_place_summaries(session, *, sort, place_ids, limit):
        captured["limit"] = limit
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
    assert captured["thread_id"] != main_thread_id
    assert re.fullmatch(
        r'attachment; filename="export-all-0-sort-mention-count-\d{8}T\d{6}Z\.txt"',
        response.headers["content-disposition"],
    )


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

    resolved = await client.post(
        f"/api/v1/destinations/unmatched/{candidate.id}/resolve",
        json={"action": "match_existing", "place_id": place.place_id},
    )
    assert resolved.status_code == 200
    assert resolved.json()["candidate"]["match_status"] == MatchStatus.USER_CORRECTED
    assert resolved.json()["candidate"]["feature_export_status"] == FeatureExportStatus.READY

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
        audited_hit = audit_payload["request"]["selected_hit"]
        assert audited_hit["provider"] == "kakao"
        assert audited_hit["native_id"] == "kakao-near-123"
        assert audited_hit["query"] == "새 관광지"
        assert audited_hit["name"] == "새관광지 원본"
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
