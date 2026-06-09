"""API 엔드포인트 통합 테스트.

`get_session` 의존성을 테스트 엔진으로 오버라이드해 ASGI 앱을 직접 호출한다.
"""

from __future__ import annotations

from io import BytesIO
import re
import threading
from zipfile import ZipFile

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


async def test_settings_roundtrip(client):
    resp = await client.post("/api/v1/settings", json={"gemini_engine_version": "gemini-1.5-pro"})
    assert resp.status_code == 200
    assert resp.json()["settings"]["gemini_engine_version"] == "gemini-1.5-pro"
    assert "gemini-1.5-pro" in resp.json()["settings"]["gemini_engine_options"]

    get_resp = await client.get("/api/v1/settings")
    assert get_resp.json()["gemini_engine_version"] == "gemini-1.5-pro"
    assert get_resp.json()["gemini_engine_default"] == "gemini-2.0-flash"
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
    assert "지원하지 않는 Gemini 엔진 버전" in resp.json()["detail"]


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_destinations_reflect_db(client, session_factory):
    from app.models import (
        ExtractedPlaceCandidate,
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
    haeundae = next(d for d in dest.json() if d["name"] == "해운대")
    assert haeundae["mention_count"] == 2
    assert haeundae["source_channel_count"] == 1
    assert haeundae["source_videos"][0]["channel_name"] == "부산 유튜버"
    assert haeundae["source_videos"][0]["video_title"] == "부산 여행"

    unmatched = await client.get("/api/v1/destinations/unmatched")
    assert unmatched.status_code == 200
    assert any(u["ai_place_name"] == "검수대상" for u in unmatched.json())


async def test_destination_export_formats(client, session_factory):
    from app.models import TravelPlace, VideoPlaceMapping, YoutubeVideo

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
        r'attachment; filename="tripmate-places-selected-1-sort-mention-count-\d{8}T\d{6}Z\.xlsx"',
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
    from app.api import routes

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
    from app.models import AssetType, MediaAsset
    from app.services import audit_service, crawl_run_service

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
                bucket="tripmate-frames",
                object_key="frames/a.jpg",
                object_uri="rustfs://frames/a.jpg",
                size_bytes=10,
            )
        )
        await s.commit()

    runs = await client.get("/api/v1/runs")
    assert runs.status_code == 200
    assert runs.json()[0]["state"] == "failed"
    assert "작업이 실패했습니다" in runs.json()[0]["current_message"]
    assert runs.json()[0]["status_logs"][-1]["level"] == "error"

    audits = await client.get("/api/v1/audit-logs")
    assert audits.status_code == 200
    assert audits.json()[0]["action"] == "place.correct"

    storage = await client.get("/api/v1/storage/rustfs")
    assert storage.status_code == 200
    assert storage.json()["retention_policy"] == "infinite"
    assert storage.json()["assets"][0]["count"] == 1


async def test_resolve_candidate_and_deep_research(client, session_factory):
    from app.models import ExtractedPlaceCandidate, MatchStatus, TravelPlace, YoutubeVideo

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

    research = await client.post(f"/api/v1/destinations/{place.place_id}/deep-research", json={})
    assert research.status_code == 200
    assert research.json()["state"] == "pending"
