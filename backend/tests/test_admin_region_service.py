"""kor-travel-geo v2 행정코드 보강 테스트."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx

from ktc.etl import admin_region_service
from ktc.models import AuditLog, TravelPlace
from ktc.services import settings_service


async def test_fetch_admin_region_reads_reverse_v2_region():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/reverse"
        assert request.url.params.get("key") == "test-key"
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "candidates": [
                    {
                        "region": {
                            "sig_cd": "11680",
                            "bjd_cd": "1168010100",
                            "sido": "서울특별시",
                            "sigungu": "강남구",
                            "legal_dong": "역삼동",
                        }
                    }
                ],
            },
            request=request,
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://geo.test",
    ) as client:
        region = await admin_region_service.fetch_admin_region(
            client,
            lat=37.501,
            lon=127.036,
            base_url="http://geo.test",
            api_key="test-key",
        )

    assert region is not None
    assert region.sigungu_code == "11680"
    assert region.sigungu_name == "서울특별시 강남구"
    assert region.legal_dong_code == "1168010100"
    assert region.legal_dong_name == "서울특별시 강남구 역삼동"


async def test_fetch_admin_region_uses_radius_fallback_for_partial_reverse():
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        assert request.url.params.get("key") == "test-key"
        if request.url.path == "/v2/reverse":
            return httpx.Response(
                200,
                json={
                    "status": "OK",
                    "candidates": [{"region": {"sig_cd": "51170"}}],
                },
                request=request,
            )
        if request.url.path == "/v2/regions/within-radius":
            return httpx.Response(
                200,
                json={
                    "status": "OK",
                    "sido": [{"code": "51", "name": "강원특별자치도"}],
                    "sigungu": [{"code": "51170", "name": "동해시"}],
                    "emd": [{"code": "51170124", "name": "삼화동"}],
                },
                request=request,
            )
        raise AssertionError(request.url.path)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://geo.test",
    ) as client:
        region = await admin_region_service.fetch_admin_region(
            client,
            lat=37.461,
            lon=129.011,
            base_url="http://geo.test",
            api_key="test-key",
        )

    assert seen_paths == ["/v2/reverse", "/v2/regions/within-radius"]
    assert region is not None
    assert region.sigungu_code == "51170"
    assert region.sigungu_name == "강원특별자치도 동해시"
    assert region.legal_dong_code == "5117012400"
    assert region.legal_dong_name == "강원특별자치도 동해시 삼화동"


async def test_isolated_admin_enrichment_skips_late_response_after_place_change(
    session_factory,
    monkeypatch,
):
    async with session_factory() as seed_session:
        place = TravelPlace(
            name="월정리 카페",
            latitude=33.5563,
            longitude=126.7958,
            is_geocoded=True,
        )
        seed_session.add(place)
        await seed_session.commit()
        await seed_session.refresh(place)
        place_id = place.place_id

    async def fake_secret(_session, _key):
        return "test-key"

    request_started = asyncio.Event()
    resume_response = asyncio.Event()

    async def fake_resolve(snapshot, **_kwargs):
        request_started.set()
        await resume_response.wait()
        return admin_region_service.AdminRegion(
            sigungu_code="50110",
            sigungu_name="제주특별자치도 제주시",
            legal_dong_code="5011025626",
            legal_dong_name="제주특별자치도 제주시 구좌읍 월정리",
        )

    monkeypatch.setattr(settings_service, "get_secret", fake_secret)
    monkeypatch.setattr(admin_region_service, "resolve_admin_region", fake_resolve)
    settings = SimpleNamespace(KOR_TRAVEL_GEO_V2_BASE_URL="http://geo.test")

    task = asyncio.create_task(
        admin_region_service.enrich_place_admin_codes_isolated(
            session_factory,
            place_id,
            settings=settings,
        )
    )
    await request_started.wait()

    # 외부 HTTP 대기 중 read transaction/connection이 닫혀 있어 사용자 보정이 완료된다.
    async with session_factory() as reviewer_session:
        current = await reviewer_session.get(TravelPlace, place_id)
        current.latitude = 33.4996
        current.longitude = 126.5312
        current.sigungu_code = "50111"
        current.sigungu_name = "사용자 보정"
        await reviewer_session.commit()

    resume_response.set()
    assert await task is False

    async with session_factory() as check_session:
        current = await check_session.get(TravelPlace, place_id)
        assert current.latitude == 33.4996
        assert current.longitude == 126.5312
        assert current.sigungu_code == "50111"
        assert current.sigungu_name == "사용자 보정"
        assert current.legal_dong_code is None


async def test_isolated_admin_enrichment_applies_after_read_transaction_closed(
    session_factory,
    monkeypatch,
):
    async with session_factory() as seed_session:
        place = TravelPlace(
            name="월정리 카페",
            latitude=33.5563,
            longitude=126.7958,
            is_geocoded=True,
        )
        seed_session.add(place)
        await seed_session.commit()
        await seed_session.refresh(place)
        place_id = place.place_id

    secret_sessions = []

    async def fake_secret(read_session, _key):
        assert read_session.in_transaction() is True
        secret_sessions.append(read_session)
        return "test-key"

    async def fake_resolve(_snapshot, **_kwargs):
        assert len(secret_sessions) == 1
        assert secret_sessions[0].in_transaction() is False
        return admin_region_service.AdminRegion(
            sigungu_code="50111",
            sigungu_name="제주특별자치도 제주시",
            legal_dong_code="5011025626",
            legal_dong_name="제주특별자치도 제주시 구좌읍 월정리",
        )

    monkeypatch.setattr(settings_service, "get_secret", fake_secret)
    monkeypatch.setattr(admin_region_service, "resolve_admin_region", fake_resolve)
    settings = SimpleNamespace(KOR_TRAVEL_GEO_V2_BASE_URL="http://geo.test")

    applied = await admin_region_service.enrich_place_admin_codes_isolated(
        session_factory,
        place_id,
        settings=settings,
    )

    assert applied is True
    async with session_factory() as check_session:
        current = await check_session.get(TravelPlace, place_id)
        assert current.sigungu_code == "50111"
        assert current.sigungu_name == "제주특별자치도 제주시"
        assert current.legal_dong_code == "5011025626"
        assert current.legal_dong_name == "제주특별자치도 제주시 구좌읍 월정리"


async def test_isolated_admin_enrichment_rejects_column_payload_guard_drift(
    session_factory,
    monkeypatch,
):
    async with session_factory() as seed_session:
        place = TravelPlace(
            name="owner drift 장소",
            latitude=37.5,
            longitude=127.0,
            is_geocoded=True,
        )
        seed_session.add(place)
        await seed_session.flush()
        audit_log = AuditLog(
            actor_type="mcp",
            action="place.correct",
            target_type="travel_place",
            target_id=str(place.place_id),
            idempotency_key="admin-owner-drift-key",
            idempotency_state="final",
            payload_json=json.dumps(
                {
                    "idempotency_key": "admin-owner-drift-key",
                    "idempotency_state": "pending",
                    "pending_owner": "stale-owner",
                }
            ),
        )
        seed_session.add(audit_log)
        await seed_session.commit()
        place_id = place.place_id
        audit_log_id = audit_log.id

    secret_calls = 0

    async def forbidden_secret(*_args, **_kwargs):
        nonlocal secret_calls
        secret_calls += 1
        return "test-key"

    monkeypatch.setattr(settings_service, "get_secret", forbidden_secret)
    applied = await admin_region_service.enrich_place_admin_codes_isolated(
        session_factory,
        place_id,
        settings=SimpleNamespace(
            KOR_TRAVEL_GEO_V2_BASE_URL="http://geo.test"
        ),
        apply_guard=admin_region_service.AdminEnrichmentGuard(
            audit_log_id=audit_log_id,
            pending_owner="stale-owner",
        ),
    )

    assert applied is False
    assert secret_calls == 0
    async with session_factory() as check_session:
        current = await check_session.get(TravelPlace, place_id)
        assert current.sigungu_code is None
        assert current.legal_dong_code is None
