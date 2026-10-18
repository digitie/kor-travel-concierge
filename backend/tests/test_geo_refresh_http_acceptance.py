"""실제 loopback HTTP와 PostGIS로 변경 토큰·부분 실패·중단 재개 공급 계약을 검사한다."""

import asyncio
import json
import os
import socket
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from ktc.etl import admin_region_refresh as refresh
from ktc.models import FeatureExport, TravelPlace
from ktc.services import settings_service
from main import app
from sqlalchemy import select

from .test_feature_export_api import _seed_ready_candidate
from .test_feature_export_api import client as client  # noqa: PLC0414

OLD = "dd1-" + "a" * 32
NEW = "dd1-" + "b" * 32


@asynccontextmanager
async def serve(application):
    """공유 포트를 회수하지 않고 소유 socket만 종료한다."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(application, log_level="error", lifespan="off")
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():
                    await task
                    raise AssertionError("시험 HTTP 서버가 시작 전에 종료됐습니다")
                await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 10)
        sock.close()


@pytest.mark.parametrize("scenario", ["changed", "partial_503", "cancel_resume"])
async def test_changed_release_http_feed_recovers_only_unfinished_places(
    scenario, client, session_factory, engine, monkeypatch
):
    count = 21 if scenario == "partial_503" else 3
    places = []
    for i in range(count):
        candidate, place_id = await _seed_ready_candidate(
            session_factory, video_id=f"track1-{i}", place_name=f"변경 검증 {i}"
        )
        async with session_factory() as session:
            place = await session.get(TravelPlace, place_id)
            place.longitude = 127 + i * 0.001
            place.sigungu_code = "11110"
            place.legal_dong_code = "1111010100"
            place.admin_code_geo_data_token = OLD
            await session.commit()
        places.append((candidate, place_id, 127 + i * 0.001))

    async def secret(session, key):
        return "fixture-header-only"

    monkeypatch.setattr(refresh, "get_secret", secret)
    monkeypatch.setattr(settings_service, "get_secret", secret)
    geo = FastAPI()
    calls = Counter()
    state = {"token": OLD, "bad": scenario == "partial_503"}
    blocked = asyncio.Event()
    release = asyncio.Event()
    blocked_lon = places[1][2] if scenario == "cancel_resume" else None

    @geo.post("/v2/dataset/version")
    async def version(request: Request):
        assert request.headers["X-KTG-API-Key"] == "fixture-header-only"
        assert "key" not in request.query_params
        return {
            "status": "OK",
            "available": True,
            "current": {"data_token": state["token"]},
        }

    @geo.post("/v2/reverse")
    async def reverse(request: Request):
        assert engine.pool.checkedout() == 0
        assert request.headers["X-KTG-API-Key"] == "fixture-header-only"
        assert "key" not in request.query_params
        lon = (await request.json())["lon"]
        calls[lon] += 1
        if lon == blocked_lon and not release.is_set():
            blocked.set()
            await release.wait()
        if state["bad"] and lon == places[0][2]:
            return JSONResponse({"status": "ERROR"}, status_code=503)
        return {
            "status": "OK",
            "dataset": {"data_token": NEW},
            "candidates": [{"region": {"sig_cd": "11680", "bjd_cd": "1168010100"}}],
        }

    async with serve(geo) as geo_url, serve(app) as api_url:
        settings = SimpleNamespace(
            KOR_TRAVEL_GEO_V2_BASE_URL=geo_url, ADMIN_REGION_REFRESH_ERROR_RATIO=0.05
        )
        async with httpx.AsyncClient(base_url=api_url) as consumer:
            original = (await consumer.get("/api/v1/features/changes")).json()
            assert len(original["items"]) == count
            assert (
                await refresh.refresh_admin_regions(session_factory, settings=settings)
            ).state == "baseline"
            state["token"] = NEW
            if scenario == "cancel_resume":
                pending = asyncio.create_task(
                    refresh.refresh_admin_regions(session_factory, settings=settings)
                )
                try:
                    await asyncio.wait_for(blocked.wait(), 10)
                    pending.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await pending
                finally:
                    release.set()
                    if not pending.done():
                        pending.cancel()
                        await asyncio.gather(pending, return_exceptions=True)
            else:
                first = await refresh.refresh_admin_regions(
                    session_factory, settings=settings
                )
                assert first.errored == int(scenario == "partial_503")

            async with session_factory() as session:
                previous = await settings_service.get_setting(
                    session, refresh.CURSOR_KEY
                )
                tokens = [
                    (await session.get(TravelPlace, pid)).admin_code_geo_data_token
                    for _, pid, _ in places
                ]
            completed = {
                lon
                for (_, _, lon), token in zip(places, tokens, strict=True)
                if token == NEW
            }
            assert len(completed) == (
                count
                if scenario == "changed"
                else count - 1
                if scenario == "partial_503"
                else 1
            )
            assert previous == (NEW if scenario == "changed" else OLD)
            interim_response = await consumer.get(
                "/api/v1/features/changes", params={"cursor": original["next_cursor"]}
            )
            assert interim_response.status_code == 200
            interim = interim_response.json()
            assert len(interim["items"]) == len(completed)
            assert all(
                item["place"]["address"]["geo_data_token"] == NEW
                for item in interim["items"]
            )
            before_calls = calls.copy()
            state["bad"] = False
            recovered = await refresh.refresh_admin_regions(
                session_factory, settings=settings
            )
            assert recovered.scanned == count - len(completed)
            assert all(calls[lon] == before_calls[lon] for lon in completed)
            async with session_factory() as session:
                assert (
                    await settings_service.get_setting(session, refresh.CURSOR_KEY)
                    == NEW
                )
            response = await consumer.get(
                "/api/v1/features/changes", params={"cursor": original["next_cursor"]}
            )
            assert response.status_code == 200
            changed = response.json()
            assert len(changed["items"]) == count and not changed["has_more"]
            assert all(
                x["place"]["address"]["geo_data_token"] == NEW for x in changed["items"]
            )
            assert all(
                x["place"]["address"]["legal_dong_code"] == "1168010100"
                for x in changed["items"]
            )
            assert {x["candidate_id"] for x in changed["items"]} == {
                x[0] for x in places
            }
            final_calls = calls.copy()
            assert (
                await refresh.refresh_admin_regions(session_factory, settings=settings)
            ).state == "noop"
            assert calls == final_calls
            replay = await consumer.get(
                "/api/v1/features/changes", params={"cursor": changed["next_cursor"]}
            )
            assert replay.json()["items"] == []
            async with session_factory() as session:
                assert (
                    len((await session.scalars(select(FeatureExport))).all()) == count
                )
            # 별도 Map 수용 하니스 입력만 선택적으로 저장한다. 운영 데이터는 없다.
            output = os.environ.get("KTC_TRACK1_HTTP_EVIDENCE_DIR")
            if output:
                path = Path(output)
                await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)
                await asyncio.to_thread(
                    (path / f"{scenario}.json").write_text,
                    json.dumps(
                        {
                            "scenario": scenario,
                            "old": original,
                            "changed": changed,
                            "interim": interim,
                            "old_token": OLD,
                            "new_token": NEW,
                            "completed_before_recovery": len(completed),
                            "recovered": recovered.scanned,
                            "status": "PASS",
                        },
                        ensure_ascii=False,
                    ),
                )
