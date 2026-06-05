"""API 엔드포인트 통합 테스트.

`get_session` 의존성을 테스트 엔진으로 오버라이드해 ASGI 앱을 직접 호출한다.
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


async def test_harvest_create_and_status(client):
    resp = await client.post("/api/harvest", json={"query": "제주도 맛집", "max_videos": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "pending"
    job_id = body["job_id"]

    status = await client.get(f"/api/harvest/{job_id}")
    assert status.status_code == 200
    sbody = status.json()
    assert sbody["job_id"] == job_id
    assert sbody["state"] == "pending"
    assert sbody["progress"] == 0.0


async def test_harvest_status_404(client):
    resp = await client.get("/api/harvest/999999")
    assert resp.status_code == 404


async def test_settings_roundtrip(client):
    resp = await client.post("/api/settings", json={"gemini_engine_version": "gemini-1.5-pro"})
    assert resp.status_code == 200
    assert resp.json()["settings"]["gemini_engine_version"] == "gemini-1.5-pro"

    get_resp = await client.get("/api/settings")
    assert get_resp.json()["gemini_engine_version"] == "gemini-1.5-pro"


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_destinations_reflect_db(client, session_factory):
    from app.models import ExtractedPlaceCandidate, MatchStatus, TravelPlace, YoutubeVideo

    async with session_factory() as s:
        s.add(TravelPlace(name="해운대", latitude=35.1587, longitude=129.1604, is_geocoded=True))
        s.add(YoutubeVideo(video_id="v1", title="t", url="u", channel_id="c"))
        await s.commit()
        s.add(
            ExtractedPlaceCandidate(
                video_id="v1", source_text="s", ai_place_name="검수대상",
                match_status=MatchStatus.NEEDS_REVIEW,
            )
        )
        await s.commit()

    dest = await client.get("/api/destinations")
    assert dest.status_code == 200
    assert any(d["name"] == "해운대" for d in dest.json())

    unmatched = await client.get("/api/destinations/unmatched")
    assert unmatched.status_code == 200
    assert any(u["ai_place_name"] == "검수대상" for u in unmatched.json())


async def test_operations_endpoints_return_runs_audits_and_storage(client, session_factory):
    from app.models import AssetType, MediaAsset
    from app.services import audit_service, crawl_run_service

    async with session_factory() as s:
        run = await crawl_run_service.create_run(
            s, job_type="harvest", source="web", target_type="keyword", target_id="부산"
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

    runs = await client.get("/api/runs")
    assert runs.status_code == 200
    assert runs.json()[0]["state"] == "failed"

    audits = await client.get("/api/audit-logs")
    assert audits.status_code == 200
    assert audits.json()[0]["action"] == "place.correct"

    storage = await client.get("/api/storage/rustfs")
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
        f"/api/destinations/unmatched/{candidate.id}/resolve",
        json={"action": "match_existing", "place_id": place.place_id},
    )
    assert resolved.status_code == 200
    assert resolved.json()["candidate"]["match_status"] == MatchStatus.USER_CORRECTED

    research = await client.post(f"/api/destinations/{place.place_id}/deep-research", json={})
    assert research.status_code == 200
    assert research.json()["state"] == "pending"
