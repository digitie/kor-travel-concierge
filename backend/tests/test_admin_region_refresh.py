"""재해결 중단·재개·cursor·HTTP/DB 연결·공급 효과를 실제 PostGIS에서 검사한다."""

import asyncio
import json
from collections import Counter
from types import SimpleNamespace

import httpx
import pytest
from ktc.etl import admin_region_refresh as refresh
from ktc.models import FeatureExport, SystemSetting, TravelPlace
from ktc.services import feature_export_service, settings_service
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .test_feature_export_api import _seed_ready_candidate
from .test_feature_export_api import (
    client as client,  # noqa: PLC0414 - pytest fixture 재사용
)

TOKEN = "dd1-" + "a" * 32
OTHER = "dd1-" + "b" * 32
SETTINGS = SimpleNamespace(
    KOR_TRAVEL_GEO_V2_BASE_URL="http://geo.test", ADMIN_REGION_REFRESH_ERROR_RATIO=0.05
)


@pytest.fixture(autouse=True)
def configured_secret(monkeypatch):
    async def secret(session, key):
        return "test-key"

    monkeypatch.setattr(refresh, "get_secret", secret)
    monkeypatch.setattr(settings_service, "get_secret", secret)


async def seed(factory, count=1, **kwargs):
    async with factory() as session:
        rows = [
            TravelPlace(
                name=f"재개 장소 {i}",
                latitude=37.5,
                longitude=127 + i * 0.001,
                is_geocoded=True,
                **kwargs,
            )
            for i in range(count)
        ]
        session.add_all(rows)
        await session.commit()
        return [(row.place_id, row.longitude) for row in rows]


async def cursor(factory):
    async with factory() as session:
        return await settings_service.get_setting(session, refresh.CURSOR_KEY)


async def begin_release(factory):
    """기존 재해결 회귀는 첫 관측과 구별되는 실제 토큰 변경으로 시작한다."""
    async with factory() as session:
        session.add(SystemSetting(key=refresh.CURSOR_KEY, value=OTHER))
        await session.commit()


class Geo:
    def __init__(self, engine, *, missing_token=False):
        self.engine = engine
        self.calls = Counter()
        self.bad = set()
        self.unresolved = set()
        self.cancel_at = None
        self.missing_token = missing_token
        self.version_calls = 0

    def handler(self, request):
        assert self.engine.pool.checkedout() == 0, (
            "HTTP 동안 DB connection을 점유했습니다"
        )
        assert (
            request.headers["X-KTG-API-Key"] == "test-key"
            and "key" not in request.url.params
        )
        if request.url.path == "/v2/dataset/version":
            self.version_calls += 1
            current = {"data_token": None if self.missing_token else TOKEN}
            return httpx.Response(
                200, json={"status": "OK", "available": True, "current": current}
            )
        lon = json.loads(request.content)["lon"]
        self.calls[lon] += 1
        if lon == self.cancel_at:
            raise asyncio.CancelledError()
        if lon in self.bad:
            return httpx.Response(503, json={"status": "ERROR"})
        if lon in self.unresolved:
            return httpx.Response(
                200, json={"status": "NOT_FOUND", "dataset": {"data_token": TOKEN}}
            )
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "dataset": {"data_token": TOKEN},
                "candidates": [{"region": {"sig_cd": "11680", "bjd_cd": "1168010100"}}],
            },
        )

    def client(self):
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


async def run(factory, geo):
    async with geo.client() as http:
        return await refresh.refresh_admin_regions(
            factory, settings=SETTINGS, http_client=http
        )


async def test_resolved_and_unresolved_are_one_attempt_per_release(
    session_factory, engine
):
    await begin_release(session_factory)
    rows = await seed(
        session_factory, 2, sigungu_code="11111", legal_dong_code="1111111111"
    )
    geo = Geo(engine)
    geo.unresolved.add(rows[1][1])
    first = await run(session_factory, geo)
    assert (first.scanned, first.resolved, first.unresolved, first.errored) == (
        2,
        1,
        1,
        0,
    )
    assert first.state == "completed" and first.token_advanced
    assert await cursor(session_factory) == TOKEN
    async with session_factory() as session:
        row = await session.get(TravelPlace, rows[1][0])
        assert row.sigungu_code == "11111" and row.admin_code_geo_data_token == TOKEN
        assert row.admin_code_source == "kor-travel-geo-v2:unresolved"
    before = geo.calls.copy()
    second = await run(session_factory, geo)
    assert second.state == "noop" and second.scanned == 0 and not second.token_advanced
    assert geo.calls == before and geo.version_calls == 2


async def test_same_global_token_still_refreshes_new_stale_place(
    session_factory, engine
):
    async with session_factory() as session:
        session.add(SystemSetting(key=refresh.CURSOR_KEY, value=TOKEN))
        await session.commit()
    rows = await seed(session_factory)
    geo = Geo(engine)
    result = await run(session_factory, geo)
    assert result.scanned == result.resolved == 1 and result.state == "completed"
    assert not result.token_advanced and geo.calls[rows[0][1]] == 1


async def test_cancelled_run_resumes_without_repeating_committed_places(
    session_factory, engine
):
    await begin_release(session_factory)
    rows = await seed(session_factory, 4)
    geo = Geo(engine)
    geo.cancel_at = rows[2][1]
    with pytest.raises(asyncio.CancelledError):
        await run(session_factory, geo)
    assert await cursor(session_factory) == OTHER
    async with session_factory() as session:
        assert [
            (await session.get(TravelPlace, row_id)).admin_code_geo_data_token
            for row_id, _ in rows
        ] == [TOKEN, TOKEN, None, None]
    geo.cancel_at = None
    result = await run(session_factory, geo)
    assert result.scanned == 2 and result.state == "completed"
    assert geo.calls[rows[0][1]] == geo.calls[rows[1][1]] == 1
    assert geo.calls[rows[2][1]] == 2 and geo.calls[rows[3][1]] == 1


@pytest.mark.parametrize("errors,raises", [(1, False), (3, True)])
async def test_remaining_errors_never_advance_cursor_and_only_failed_places_retry(
    session_factory, engine, errors, raises
):
    await begin_release(session_factory)
    rows = await seed(session_factory, 51)
    geo = Geo(engine)
    geo.bad = {lon for _, lon in rows[:errors]}
    if raises:
        with pytest.raises(refresh.RefreshError) as caught:
            await run(session_factory, geo)
        first = caught.value.stats
    else:
        first = await run(session_factory, geo)
    assert (
        first.scanned == (50 if raises else 51)
        and first.errored == errors
        and await cursor(session_factory) == OTHER
    )
    async with session_factory() as session:
        tokens = [
            (await session.get(TravelPlace, row_id)).admin_code_geo_data_token
            for row_id, _ in rows[:errors]
        ]
        assert tokens == [None] * errors
    geo.bad.clear()
    second = await run(session_factory, geo)
    assert (
        second.scanned == errors + int(raises)
        and second.state == "completed"
        and await cursor(session_factory) == TOKEN
    )
    assert all(geo.calls[lon] == 1 for _, lon in rows[errors:])


async def test_only_id_pages_and_current_token_rows_are_excluded(
    session_factory, engine
):
    await begin_release(session_factory)
    rows = await seed(session_factory, 123)
    geo = Geo(engine)
    result = await run(session_factory, geo)
    assert result.scanned == result.resolved == 123 and result.state == "completed"
    assert all(geo.calls[lon] == 1 for _, lon in rows)
    assert await cursor(session_factory) == TOKEN
    again = await run(session_factory, geo)
    assert again.scanned == 0 and all(geo.calls[lon] == 1 for _, lon in rows)


async def test_provider_without_data_token_does_not_seal_cursor_or_places(
    session_factory, engine
):
    rows = await seed(session_factory)
    geo = Geo(engine, missing_token=True)
    result = await run(session_factory, geo)
    assert result.state == "data_token_unavailable" and not geo.calls
    assert await cursor(session_factory) is None
    async with session_factory() as session:
        assert (
            await session.get(TravelPlace, rows[0][0])
        ).admin_code_geo_data_token is None


async def test_coordinate_drift_remains_stale_until_next_run(session_factory, engine):
    await begin_release(session_factory)
    rows = await seed(session_factory)
    geo = Geo(engine)
    changed = False

    async def handler(request):
        nonlocal changed
        response = geo.handler(request)
        if request.url.path == "/v2/reverse" and not changed:
            async with session_factory() as session:
                place = await session.get(TravelPlace, rows[0][0])
                place.latitude = 37.6
                await session.commit()
            changed = True
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await refresh.refresh_admin_regions(
            session_factory, settings=SETTINGS, http_client=http
        )
    assert (
        result.skipped == 1
        and result.state == "pending"
        and await cursor(session_factory) == OTHER
    )
    async with session_factory() as session:
        row = await session.get(TravelPlace, rows[0][0])
        assert row.latitude == 37.6 and row.admin_code_geo_data_token is None
    result = await run(session_factory, geo)
    assert result.resolved == 1 and result.state == "completed"


async def test_refresh_and_full_export_concurrency_have_one_change_and_fixpoint(
    client, session_factory, engine
):
    await begin_release(session_factory)
    candidate_id, place_id = await _seed_ready_candidate(session_factory)
    before = (await client.get("/api/v1/features/changes")).json()["next_cursor"]
    geo = Geo(engine)

    # 실제 job마다 rt.database()가 별도 pool을 만든다. exporter의 정당한 DB 연결을
    # refresh 자기 연결 점유로 오인하지 않도록 같은 DB·서로 다른 engine을 사용한다.
    export_engine = create_async_engine(engine.url, pool_size=1, max_overflow=0)
    export_factory = async_sessionmaker(export_engine, expire_on_commit=False)

    async def export():
        async with export_factory() as session:
            return await feature_export_service.sync_feature_exports(session)

    try:
        result, _ = await asyncio.gather(run(session_factory, geo), export())
    finally:
        await export_engine.dispose()
    assert result.resolved == 1
    response = await client.get("/api/v1/features/changes", params={"cursor": before})
    assert response.status_code == 200 and len(response.json()["items"]) == 1
    assert response.json()["items"][0]["place"]["address"]["geo_data_token"] == TOKEN
    async with session_factory() as session:
        assert await feature_export_service.sync_feature_exports(session) == 0
        exports = list((await session.scalars(select(FeatureExport))).all())
        assert len(exports) == 1 and exports[0].candidate_id == candidate_id
        assert (
            await session.get(TravelPlace, place_id)
        ).admin_code_geo_data_token == TOKEN


async def test_internal_cursor_cannot_be_edited_through_public_settings(
    client, session_factory
):
    response = await client.post("/api/v1/settings", json={refresh.CURSOR_KEY: TOKEN})
    assert response.status_code == 400 and await cursor(session_factory) is None


@pytest.mark.parametrize(
    "body",
    [
        {"status": "ERROR", "available": False},
        {"status": "OK", "available": 1, "current": {}},
        {"status": "OK", "available": True, "current": []},
        {"status": "OK", "available": True, "current": {"data_token": True}},
        {
            "status": "OK",
            "available": True,
            "current": {"data_token": "dd1-" + "a" * 40},
        },
    ],
)
async def test_malformed_version_response_is_error_not_noop(body):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    ) as http:
        with pytest.raises((ValueError, TypeError)):
            await refresh.current_token(http, "http://geo.test", "test-key")


async def test_persistent_slow_error_prefix_cannot_starve_healthy_suffix(
    session_factory, engine
):
    await begin_release(session_factory)
    rows = await seed(session_factory, 10)
    geo = Geo(engine)
    geo.bad = {lon for _, lon in rows[:4]}
    geo.cancel_at = rows[4][1]
    with pytest.raises(asyncio.CancelledError):
        await run(session_factory, geo)
    assert await cursor(session_factory) == OTHER
    async with session_factory() as session:
        progress = json.loads(
            await settings_service.get_setting(session, refresh.PROGRESS_KEY)
        )
        assert progress["after"] == rows[3][0] and progress["token"] == TOKEN
    geo.cancel_at = None
    result = await run(session_factory, geo)
    assert result.resolved == 6 and result.errored == 4
    assert result.state == "pending" and await cursor(session_factory) == OTHER
    async with session_factory() as session:
        for row_id, _ in rows[4:]:
            assert (
                await session.get(TravelPlace, row_id)
            ).admin_code_geo_data_token == TOKEN
    geo.bad.clear()
    result = await run(session_factory, geo)
    assert result.resolved == 4 and result.state == "completed"
    assert all(geo.calls[lon] == 1 for _, lon in rows[5:])


async def test_error_budget_keeps_cursor_and_next_run_reaches_remaining_places(
    session_factory, engine
):
    await begin_release(session_factory)
    rows = await seed(session_factory, 60)
    geo = Geo(engine)
    geo.bad = {lon for _, lon in rows[:50]}
    with pytest.raises(refresh.RefreshError) as caught:
        await run(session_factory, geo)
    assert caught.value.stats.scanned == 50
    assert not any(geo.calls[lon] for _, lon in rows[50:])
    with pytest.raises(refresh.RefreshError) as caught:
        await run(session_factory, geo)
    assert caught.value.stats.resolved == 10 and caught.value.stats.errored == 40
    assert all(geo.calls[lon] == 1 for _, lon in rows[50:])
    assert await cursor(session_factory) == OTHER
    geo.bad.clear()
    result = await run(session_factory, geo)
    assert result.resolved == 50 and result.state == "completed"


async def test_new_epoch_does_not_reuse_previous_epoch_progress(
    session_factory, engine
):
    rows = await seed(session_factory, 3)
    async with session_factory() as session:
        session.add(
            SystemSetting(
                key=refresh.PROGRESS_KEY,
                value=json.dumps({"token": OTHER, "after": rows[-1][0]}),
            )
        )
        await session.commit()
    geo = Geo(engine)
    result = await run(session_factory, geo)
    assert result.resolved == 3 and result.state == "completed"
    assert all(geo.calls[lon] == 1 for _, lon in rows)


async def test_progress_key_is_not_publicly_writable(client):
    response = await client.post(
        "/api/v1/settings",
        json={refresh.PROGRESS_KEY: json.dumps({"token": TOKEN, "after": 999})},
    )
    assert response.status_code == 400


async def test_continuous_new_places_do_not_delay_wrapped_retry_after_cancellation(
    session_factory, engine
):
    await begin_release(session_factory)
    rows = await seed(session_factory, 3)
    geo = Geo(engine)
    geo.bad.add(rows[0][1])
    geo.cancel_at = rows[1][1]
    with pytest.raises(asyncio.CancelledError):
        await run(session_factory, geo)
    async with session_factory() as session:
        progress = json.loads(
            await settings_service.get_setting(session, refresh.PROGRESS_KEY)
        )
        assert progress == {"token": TOKEN, "after": rows[0][0], "ceiling": rows[-1][0]}
    inserted = []

    async def add_tail():
        async with session_factory() as session:
            place = TravelPlace(
                name="연속 신규 stale",
                latitude=37.5,
                longitude=128 + len(inserted) * 0.001,
                is_geocoded=True,
            )
            session.add(place)
            await session.commit()
            inserted.append(place.place_id)

    await add_tail()
    geo.bad.clear()
    geo.cancel_at = None

    async def growing_handler(request):
        response = geo.handler(request)
        if request.url.path != "/v2/dataset/version":
            await add_tail()
        return response

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(growing_handler)
    ) as http:
        result = await asyncio.wait_for(
            refresh.refresh_admin_regions(
                session_factory, settings=SETTINGS, http_client=http
            ),
            5,
        )
    assert result.resolved == 3 and result.state == "pending"
    assert geo.calls[rows[0][1]] == 2, (
        "오류 prefix도 tail이 계속 생기는 동안 wrap해 재해결해야 한다"
    )
    assert await cursor(session_factory) == OTHER
    async with session_factory() as session:
        for row_id, _ in rows:
            assert (
                await session.get(TravelPlace, row_id)
            ).admin_code_geo_data_token == TOKEN
        for row_id in inserted:
            assert (
                await session.get(TravelPlace, row_id)
            ).admin_code_geo_data_token is None
    result = await run(session_factory, geo)
    assert result.resolved == len(inserted) and result.state == "completed"


@pytest.mark.parametrize("ceiling", [True, -1, "50", 1])
async def test_invalid_sweep_ceiling_fails_without_skipping_places(
    session_factory, engine, ceiling
):
    await seed(session_factory, 3)
    async with session_factory() as session:
        session.add(
            SystemSetting(
                key=refresh.PROGRESS_KEY,
                value=json.dumps({"token": TOKEN, "after": 2, "ceiling": ceiling}),
            )
        )
        await session.commit()
    geo = Geo(engine)
    with pytest.raises(refresh.RefreshError):
        await run(session_factory, geo)
    assert not geo.calls and await cursor(session_factory) is None


async def test_first_observation_and_next_tick_only_store_baseline(
    session_factory, engine
):
    rows = await seed(session_factory, 2, sigungu_code="11111")
    geo = Geo(engine)
    first = await run(session_factory, geo)
    assert first.state == "baseline" and first.token_advanced
    second = await run(session_factory, geo)
    assert second.state == "noop" and not second.token_advanced
    assert first.scanned == second.scanned == first.dirty == second.dirty == 0
    assert not geo.calls and geo.version_calls == 2
    async with session_factory() as session:
        assert json.loads(
            await settings_service.get_setting(session, refresh.PROGRESS_KEY)
        ) == {"token": TOKEN, "after": 0, "ceiling": None, "phase": "baseline"}
        for place_id, _ in rows:
            place = await session.get(TravelPlace, place_id)
            assert place.sigungu_code == "11111"
            assert place.admin_code_geo_data_token is None


async def test_new_release_after_baseline_refreshes_all_stale_places(
    session_factory, engine
):
    rows = await seed(session_factory, 2)
    assert await refresh.claim_baseline(session_factory, OTHER)
    geo = Geo(engine)
    result = await run(session_factory, geo)
    assert result.state == "completed" and result.resolved == len(rows)
    assert result.token_advanced and await cursor(session_factory) == TOKEN
    async with session_factory() as session:
        assert json.loads(
            await settings_service.get_setting(session, refresh.PROGRESS_KEY)
        ) == {"token": TOKEN, "after": 0, "ceiling": None}


async def test_existing_same_epoch_progress_without_cursor_resumes(
    session_factory, engine
):
    rows = await seed(session_factory, 2)
    async with session_factory() as session:
        first = await session.get(TravelPlace, rows[0][0])
        first.admin_code_geo_data_token = TOKEN
        session.add(
            SystemSetting(
                key=refresh.PROGRESS_KEY,
                value=json.dumps(
                    {"token": TOKEN, "after": rows[0][0], "ceiling": rows[-1][0]}
                ),
            )
        )
        await session.commit()
    geo = Geo(engine)
    result = await run(session_factory, geo)
    assert result.state == "completed" and result.resolved == 1
    assert geo.calls[rows[0][1]] == 0 and geo.calls[rows[1][1]] == 1


@pytest.mark.parametrize("key", [refresh.CURSOR_KEY, refresh.PROGRESS_KEY])
async def test_postgres_baseline_claim_conflict_is_atomic(session_factory, key):
    async with session_factory() as session:
        session.add(SystemSetting(key=key, value="existing-owner"))
        await session.commit()
    assert not await refresh.claim_baseline(session_factory, TOKEN)
    async with session_factory() as session:
        rows = list((await session.scalars(select(SystemSetting))).all())
        assert [(row.key, row.value) for row in rows] == [(key, "existing-owner")]
