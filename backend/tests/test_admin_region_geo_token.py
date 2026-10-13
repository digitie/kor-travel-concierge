"""geo 토큰·격리 재해결·오류·dirty 공급 효과 회귀."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from ktc.etl import admin_region_service as service
from ktc.models import FeatureExport, TravelPlace
from ktc.services import feature_export_service, settings_service
from sqlalchemy import select

TOKEN = "dd1-" + "a" * 32
OTHER = "dd1-" + "b" * 32
SETTINGS = SimpleNamespace(KOR_TRAVEL_GEO_V2_BASE_URL="http://geo.test")


def region(token=TOKEN):
    return service.AdminRegion("11680", "강남구", "1168010100", "역삼동", token)


async def seed(session_factory, **kwargs):
    async with session_factory() as session:
        place = TravelPlace(
            name="재해결 장소",
            latitude=37.5,
            longitude=127.0,
            is_geocoded=True,
            **kwargs,
        )
        session.add(place)
        await session.commit()
        return place.place_id


async def secret(_session, _key):
    return "test-key"


@pytest.mark.parametrize("token", [None, TOKEN])
async def test_reverse_token_and_header_without_query(token):
    def handler(request):
        assert "key" not in request.url.params
        assert request.headers["X-KTG-API-Key"] == "test-key"
        payload = {
            "status": "OK",
            "candidates": [{"region": {"sig_cd": "11680", "bjd_cd": "1168010100"}}],
        }
        if token:
            payload["dataset"] = {"data_token": token}
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await service.fetch_admin_region(
            client, lat=37.5, lon=127.0, base_url="http://geo.test", api_key="test-key"
        )
    assert result.data_token == token


@pytest.mark.parametrize(
    "fallback_token,expected", [(TOKEN, TOKEN), (OTHER, None), (None, None)]
)
async def test_partial_merge_never_seals_mixed_dataset(fallback_token, expected):
    def handler(request):
        assert "key" not in request.url.params
        assert request.headers["X-KTG-API-Key"] == "test-key"
        if request.url.path == "/v2/reverse":
            return httpx.Response(
                200,
                json={
                    "status": "OK",
                    "dataset": {"data_token": TOKEN},
                    "candidates": [{"region": {"sig_cd": "11680"}}],
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "dataset": {"data_token": fallback_token},
                "sido": [],
                "sigungu": [],
                "emd": [{"code": "11680101"}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await service.fetch_admin_region(
            client, lat=37.5, lon=127.0, base_url="http://geo.test", api_key="test-key"
        )
    assert result.sigungu_code == "11680"
    assert result.legal_dong_code == "1168010100"
    assert result.data_token == expected


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"status": "ERROR"},
        {"status": "OK", "dataset": "bad"},
        {"status": "OK", "dataset": {"data_token": "invalid"}},
    ],
)
async def test_malformed_success_is_error_not_unresolved(payload):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises((ValueError, TypeError)):
            await service.fetch_admin_region_lookup(
                client,
                lat=37.5,
                lon=127,
                base_url="http://geo.test",
                api_key="test-key",
            )


async def test_refresh_unresolved_retains_codes_but_does_not_export_provenance(
    session_factory, monkeypatch
):
    from .test_feature_export_api import _seed_ready_candidate

    candidate_id, place_id = await _seed_ready_candidate(session_factory)
    async with session_factory() as session:
        place = await session.get(TravelPlace, place_id)
        service.apply_admin_region(place, region(OTHER))
        await session.commit()
        await feature_export_service.sync_dirty(session)
    monkeypatch.setattr(settings_service, "get_secret", secret)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"status": "NOT_FOUND", "dataset": {"data_token": TOKEN}}
            )
        )
    ) as client:
        result = await service.refresh_place_admin_codes_isolated(
            session_factory,
            place_id,
            data_token=TOKEN,
            settings=SETTINGS,
            http_client=client,
        )
    assert result.outcome == "unresolved" and result.dirty
    async with session_factory() as session:
        place = await session.get(TravelPlace, place_id)
        assert place.sigungu_code == "11680" and place.legal_dong_code == "1168010100"
        assert place.admin_code_geo_data_token == TOKEN
        assert place.admin_code_source == service.ADMIN_CODE_SOURCE_UNRESOLVED
        assert await feature_export_service.sync_dirty(session) == 1
        exported = (
            await session.execute(
                select(FeatureExport).where(FeatureExport.candidate_id == candidate_id)
            )
        ).scalar_one()
        assert exported.payload_json["place"]["address"]["geo_data_token"] is None
        assert await feature_export_service.sync_feature_exports(session) == 0


async def test_refresh_success_dirty_golden_and_repeat_no_change(
    session_factory, monkeypatch
):
    from .test_feature_export_api import _seed_ready_candidate

    candidate_id, place_id = await _seed_ready_candidate(session_factory)
    async with session_factory() as session:
        await feature_export_service.sync_dirty(session)
    monkeypatch.setattr(settings_service, "get_secret", secret)

    async def lookup(*args, **kwargs):
        return service.AdminLookup(region(), TOKEN)

    monkeypatch.setattr(service, "resolve_admin_region_lookup", lookup)
    first = await service.refresh_place_admin_codes_isolated(
        session_factory, place_id, data_token=TOKEN, settings=SETTINGS
    )
    assert first.outcome == "resolved" and first.dirty
    async with session_factory() as session:
        assert await feature_export_service.sync_dirty(session) == 1
        exported = (
            await session.execute(
                select(FeatureExport).where(FeatureExport.candidate_id == candidate_id)
            )
        ).scalar_one()
        assert exported.payload_json["place"]["address"]["geo_data_token"] == TOKEN
        assert await feature_export_service.sync_feature_exports(session) == 0
    again = await service.refresh_place_admin_codes_isolated(
        session_factory, place_id, data_token=TOKEN, settings=SETTINGS
    )
    assert again.outcome == "resolved" and not again.dirty
    async with session_factory() as session:
        assert await feature_export_service.sync_dirty(session) == 0


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectTimeout("test"),
        httpx.ReadTimeout("test"),
        ValueError("json"),
        httpx.HTTPStatusError(
            "test",
            request=httpx.Request("POST", "http://geo.test"),
            response=httpx.Response(503),
        ),
    ],
)
async def test_refresh_errors_do_not_record_attempt(
    session_factory, monkeypatch, error
):
    place_id = await seed(
        session_factory,
        sigungu_code="11680",
        legal_dong_code="1168010100",
        admin_code_geo_data_token=OTHER,
    )
    monkeypatch.setattr(settings_service, "get_secret", secret)

    async def lookup(*args, **kwargs):
        raise error

    monkeypatch.setattr(service, "resolve_admin_region_lookup", lookup)
    result = await service.refresh_place_admin_codes_isolated(
        session_factory, place_id, data_token=TOKEN, settings=SETTINGS
    )
    assert result.outcome == "errored" and not result.dirty
    async with session_factory() as session:
        place = await session.get(TravelPlace, place_id)
        assert (
            place.admin_code_geo_data_token == OTHER and place.sigungu_code == "11680"
        )


@pytest.mark.parametrize("changed", ["coordinate", "token"])
async def test_refresh_fence_rejects_late_response(
    session_factory, monkeypatch, changed
):
    place_id = await seed(session_factory)
    monkeypatch.setattr(settings_service, "get_secret", secret)
    started, resume = asyncio.Event(), asyncio.Event()

    async def lookup(*args, **kwargs):
        started.set()
        await resume.wait()
        return service.AdminLookup(region(), TOKEN)

    monkeypatch.setattr(service, "resolve_admin_region_lookup", lookup)
    task = asyncio.create_task(
        service.refresh_place_admin_codes_isolated(
            session_factory, place_id, data_token=TOKEN, settings=SETTINGS
        )
    )
    await asyncio.wait_for(started.wait(), 2)
    async with session_factory() as session:
        place = await session.get(TravelPlace, place_id)
        if changed == "coordinate":
            place.latitude = 38.0
        else:
            place.admin_code_geo_data_token = OTHER
        await session.commit()
    resume.set()
    result = await asyncio.wait_for(task, 2)
    assert result.outcome == "skipped" and not result.dirty
    async with session_factory() as session:
        place = await session.get(TravelPlace, place_id)
        assert place.sigungu_code is None
        assert place.admin_code_geo_data_token != TOKEN


async def test_bool_complete_skip_does_not_http_or_mutate(session_factory, monkeypatch):
    place_id = await seed(
        session_factory, sigungu_code="11680", legal_dong_code="1168010100"
    )

    calls = []

    async def forbidden(*args, **kwargs):
        calls.append(1)
        raise AssertionError("완성 코드는 기존 bool 경로에서 조회하지 않는다")

    monkeypatch.setattr(service, "resolve_admin_region", forbidden)
    assert (
        await service.enrich_place_admin_codes_isolated(
            session_factory, place_id, settings=SETTINGS
        )
        is False
    )
    assert calls == []
    async with session_factory() as session:
        assert (
            await session.get(TravelPlace, place_id)
        ).admin_code_geo_data_token is None


@pytest.mark.parametrize("isolated", [False, True])
async def test_real_factory_receives_connect_timeout_and_error_is_best_effort(
    session_factory, monkeypatch, isolated
):
    place_id = await seed(session_factory)
    monkeypatch.setattr(settings_service, "get_secret", secret)
    received = []

    def factory(**kwargs):
        received.append(kwargs["timeout"])
        raise httpx.ConnectTimeout("접속 실패")

    monkeypatch.setattr(service.httpx, "AsyncClient", factory)
    if isolated:
        result = await service.enrich_place_admin_codes_isolated(
            session_factory, place_id, settings=SETTINGS
        )
    else:
        async with session_factory() as session:
            place = await session.get(TravelPlace, place_id)
            result = await service.enrich_place_admin_codes(
                session, place, settings=SETTINGS
            )
    assert result is False
    assert received == [service.GEO_HTTP_TIMEOUT]
    assert received[0].connect == 2 and received[0].read == 10


@pytest.mark.parametrize(
    "broken",
    [
        "missing_candidates",
        "object_candidates",
        "candidate_type",
        "region_type",
        "radius_missing",
        "radius_type",
    ],
)
async def test_refresh_malformed_nested_success_does_not_seal_attempt(
    session_factory, monkeypatch, broken
):
    place_id = await seed(session_factory)
    monkeypatch.setattr(settings_service, "get_secret", secret)

    def handler(request):
        if request.url.path.endswith("within-radius"):
            payload = {
                "status": "OK",
                "dataset": {"data_token": TOKEN},
                "sido": [],
                "sigungu": [],
                "emd": [],
            }
            if broken == "radius_missing":
                del payload["emd"]
            else:
                payload["emd"] = {}
        else:
            payload = {
                "status": "OK",
                "dataset": {"data_token": TOKEN},
                "candidates": [],
            }
            if broken == "missing_candidates":
                del payload["candidates"]
            elif broken == "object_candidates":
                payload["candidates"] = {}
            elif broken == "candidate_type":
                payload["candidates"] = ["bad"]
            elif broken == "region_type":
                payload["candidates"] = [{"region": []}]
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await service.refresh_place_admin_codes_isolated(
            session_factory,
            place_id,
            data_token=TOKEN,
            settings=SETTINGS,
            http_client=client,
        )
    assert result.outcome == "errored" and not result.dirty
    async with session_factory() as session:
        assert (
            await session.get(TravelPlace, place_id)
        ).admin_code_geo_data_token is None


async def test_empty_radius_of_other_release_cannot_seal_partial_reverse():
    def handler(request):
        if request.url.path.endswith("within-radius"):
            return httpx.Response(
                200,
                json={
                    "status": "OK",
                    "dataset": {"data_token": OTHER},
                    "sido": [],
                    "sigungu": [],
                    "emd": [],
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "dataset": {"data_token": TOKEN},
                "candidates": [{"region": {"sig_cd": "11680"}}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        lookup = await service.fetch_admin_region_lookup(
            client, lat=37.5, lon=127, base_url="http://geo.test", api_key="test-key"
        )
    assert lookup.region.sigungu_code == "11680" and lookup.data_token is None


@pytest.mark.parametrize(
    "token", ["a" * 40, "dd1-" + "A" * 32, "dd1-" + "0" * 31, "dd1-" + "g" * 32]
)
def test_invalid_token_format_rejected(token):
    assert service.parse_data_token(token) is None


async def test_coordinate_correction_clears_attempt_before_new_enrichment(
    session_factory, monkeypatch
):
    from ktc.services import place_service

    place_id = await seed(
        session_factory,
        sigungu_code="11680",
        legal_dong_code="1168010100",
        admin_code_geo_data_token=OTHER,
        admin_code_source=service.ADMIN_CODE_SOURCE,
    )
    async with session_factory() as session:
        await place_service.correct_place(
            session, place_id=place_id, updates={"latitude": 37.6}, commit=False
        )
        await session.commit()
    async with session_factory() as session:
        place = await session.get(TravelPlace, place_id)
        assert place.admin_code_geo_data_token is None and place.sigungu_code is None
    monkeypatch.setattr(settings_service, "get_secret", secret)

    async def lookup(*args, **kwargs):
        return service.AdminLookup(region(), TOKEN)

    monkeypatch.setattr(service, "resolve_admin_region_lookup", lookup)
    assert (
        await service.refresh_place_admin_codes_isolated(
            session_factory, place_id, data_token=TOKEN, settings=SETTINGS
        )
    ).outcome == "resolved"
    async with session_factory() as session:
        assert (
            await session.get(TravelPlace, place_id)
        ).admin_code_geo_data_token == TOKEN


@pytest.mark.parametrize("bad", [True, 11680, {}, "True", "123", "１２３４５"])
async def test_bad_reverse_code_is_error_and_not_recorded(
    session_factory, monkeypatch, bad
):
    place_id = await seed(session_factory)
    monkeypatch.setattr(settings_service, "get_secret", secret)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "status": "OK",
                    "dataset": {"data_token": TOKEN},
                    "candidates": [{"region": {"sig_cd": bad, "bjd_cd": "1168010100"}}],
                },
            )
        )
    ) as client:
        result = await service.refresh_place_admin_codes_isolated(
            session_factory,
            place_id,
            data_token=TOKEN,
            settings=SETTINGS,
            http_client=client,
        )
    assert result.outcome == "errored" and not result.dirty
    async with session_factory() as session:
        place = await session.get(TravelPlace, place_id)
        assert place.sigungu_code is None and place.admin_code_geo_data_token is None


@pytest.mark.parametrize(
    "bad", [{}, {"code": True}, {"code": "123"}, {"code": "11680", "name": False}]
)
async def test_bad_radius_item_is_error(bad):
    def handler(request):
        if request.url.path.endswith("reverse"):
            return httpx.Response(
                200,
                json={
                    "status": "OK",
                    "dataset": {"data_token": TOKEN},
                    "candidates": [],
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "dataset": {"data_token": TOKEN},
                "sido": [],
                "sigungu": [bad],
                "emd": [],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises((TypeError, ValueError)):
            await service.fetch_admin_region_lookup(
                client,
                lat=37.5,
                lon=127,
                base_url="http://geo.test",
                api_key="test-key",
            )


async def test_refresh_and_export_sync_share_lock_and_have_one_change(
    session_factory, monkeypatch
):
    from .test_feature_export_api import _seed_ready_candidate

    candidate_id, place_id = await _seed_ready_candidate(session_factory)
    async with session_factory() as session:
        await feature_export_service.sync_dirty(session)
    monkeypatch.setattr(settings_service, "get_secret", secret)

    async def lookup(*args, **kwargs):
        return service.AdminLookup(region(), TOKEN)

    monkeypatch.setattr(service, "resolve_admin_region_lookup", lookup)

    async def sync():
        async with session_factory() as session:
            return await feature_export_service.sync_dirty(session)

    result, _ = await asyncio.wait_for(
        asyncio.gather(
            service.refresh_place_admin_codes_isolated(
                session_factory, place_id, data_token=TOKEN, settings=SETTINGS
            ),
            sync(),
        ),
        3,
    )
    assert result.outcome == "resolved"
    async with session_factory() as session:
        await feature_export_service.sync_dirty(session)
        assert await feature_export_service.sync_feature_exports(session) == 0
        rows = (
            (
                await session.execute(
                    select(FeatureExport).where(
                        FeatureExport.candidate_id == candidate_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].payload_json["place"]["address"]["geo_data_token"] == TOKEN


async def test_empty_reverse_of_other_release_cannot_seal_radius_result():
    def handler(request):
        if request.url.path.endswith("reverse"):
            return httpx.Response(
                200,
                json={
                    "status": "OK",
                    "dataset": {"data_token": OTHER},
                    "candidates": [],
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "dataset": {"data_token": TOKEN},
                "sido": [],
                "sigungu": [{"code": "11680"}],
                "emd": [{"code": "11680101"}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        lookup = await service.fetch_admin_region_lookup(
            client, lat=37.5, lon=127, base_url="http://geo.test", api_key="test-key"
        )
    assert lookup.region.sigungu_code == "11680"
    assert lookup.data_token is None and lookup.region.data_token is None
