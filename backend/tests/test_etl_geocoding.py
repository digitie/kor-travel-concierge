"""geocoding 호출 유틸리티·백오프·정규화·평가 테스트."""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

from app.etl import geocoding
from app.etl.geocoding import (
    GeocodeCandidate,
    KakaoGeocoder,
    NaverGeocoder,
    evaluate_geocode,
    geocode_with_vworld,
    normalize_to_wgs84,
    request_with_backoff,
    reverse_with_vworld,
)

_KAKAO_SINGLE = {
    "documents": [
        {
            "address_name": "부산 해운대구 우동",
            "x": "129.1604",
            "y": "35.1587",
            "road_address": {"address_name": "부산 해운대구 해운대해변로 264"},
            "address": {"address_name": "부산 해운대구 우동 1411"},
        }
    ],
    "meta": {"total_count": 1},
}

_KAKAO_MULTI = {
    "documents": [
        {"address_name": "중앙로 A", "x": "129.10", "y": "35.10",
         "road_address": None, "address": {"address_name": "중앙로 A"}},
        {"address_name": "중앙로 B", "x": "127.00", "y": "37.50",
         "road_address": None, "address": {"address_name": "중앙로 B"}},
    ],
    "meta": {"total_count": 2},
}

_KAKAO_KEYWORD = {
    "documents": [
        {
            "place_name": "카카오프렌즈 코엑스점",
            "category_name": "가정,생활 > 문구,팬시 > 캐릭터상품",
            "category_group_name": "생활,편의",
            "address_name": "서울 강남구 삼성동 159",
            "road_address_name": "서울 강남구 영동대로 513",
            "x": "127.05902969025047",
            "y": "37.51207412593136",
        }
    ],
    "meta": {"total_count": 1},
}


def test_normalize_wgs84_identity():
    assert normalize_to_wgs84(129.16, 35.15) == (129.16, 35.15)
    assert normalize_to_wgs84(129.16, 35.15, source_crs="WGS84") == (129.16, 35.15)


async def test_kakao_geocode_parses(monkeypatch):
    def handler(request):
        assert request.headers["Authorization"].startswith("KakaoAK ")
        return httpx.Response(200, json=_KAKAO_SINGLE)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        geo = KakaoGeocoder("k", http, base_delay=0.0)
        results = await geo.geocode("부산 해운대구 우동")
    assert len(results) == 1
    assert results[0].latitude == 35.1587
    assert results[0].longitude == 129.1604
    assert results[0].road_address == "부산 해운대구 해운대해변로 264"
    assert results[0].source == "kakao"


async def test_kakao_keyword_search_used_when_address_has_no_result():
    seen_paths: list[str] = []

    def handler(request):
        seen_paths.append(request.url.path)
        assert request.headers["Authorization"].startswith("KakaoAK ")
        if request.url.path.endswith("/address.json"):
            return httpx.Response(200, json={"documents": [], "meta": {"total_count": 0}})
        assert request.url.path.endswith("/keyword.json")
        assert request.url.params["query"] == "카카오프렌즈 코엑스점"
        return httpx.Response(200, json=_KAKAO_KEYWORD)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        geo = KakaoGeocoder("k", http, base_delay=0.0)
        results = await geo.geocode("카카오프렌즈 코엑스점")

    assert seen_paths == [
        "/v2/local/search/address.json",
        "/v2/local/search/keyword.json",
    ]
    assert len(results) == 1
    assert results[0].place_name == "카카오프렌즈 코엑스점"
    assert results[0].road_address == "서울 강남구 영동대로 513"
    assert results[0].category == "가정,생활 > 문구,팬시 > 캐릭터상품"
    assert results[0].source == "kakao_keyword"


async def test_vworld_client_direct_geocode_parses():
    class FakeVWorldClient:
        calls: list[tuple[str, str]]

        def __init__(self):
            self.calls = []

        async def get_coord(self, address, type, **kwargs):
            self.calls.append((address, type))
            if type == "parcel":
                return {"response": {"status": "NOT_FOUND"}}
            return {
                "response": {
                    "status": "OK",
                    "result": {
                        "refined": {"text": "경기도 성남시 분당구 판교로 242"},
                        "point": {"x": "127.101313354", "y": "37.402352535"},
                    },
                }
            }

    client = FakeVWorldClient()
    results = await geocode_with_vworld(client, "판교로 242")

    assert client.calls == [("판교로 242", "road"), ("판교로 242", "parcel")]
    assert len(results) == 1
    assert results[0].source == "vworld"
    assert results[0].longitude == 127.101313354
    assert results[0].latitude == 37.402352535
    assert results[0].road_address == "경기도 성남시 분당구 판교로 242"


async def test_vworld_client_direct_reverse_parses():
    class FakeVWorldClient:
        async def reverse_geocode_latlon(self, lat, lon, **kwargs):
            if kwargs["type"] == "road":
                text = "경기도 성남시 분당구 판교로 242"
            else:
                text = "경기도 성남시 분당구 삼평동 681"
            return {"response": {"status": "OK", "result": [{"text": text}]}}

    result = await reverse_with_vworld(FakeVWorldClient(), 37.402352535, 127.101313354)

    assert result == {
        "road_address": "경기도 성남시 분당구 판교로 242",
        "parcel_address": "경기도 성남시 분당구 삼평동 681",
    }


async def test_backoff_retries_on_429():
    calls = {"n": 0}

    async def send():
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429)
        return httpx.Response(200, json={"ok": True})

    resp = await request_with_backoff(send, max_retries=5, base_delay=0.0)
    assert resp.status_code == 200
    assert calls["n"] == 3


async def test_backoff_gives_up_after_max():
    async def send():
        return httpx.Response(429)

    resp = await request_with_backoff(send, max_retries=2, base_delay=0.0)
    assert resp.status_code == 429


def test_evaluate_no_result():
    d = evaluate_geocode([])
    assert d.status == "needs_review"
    assert d.reason == "no_result"
    assert d.candidate is None


def test_evaluate_single_matched():
    cand = GeocodeCandidate(latitude=35.1, longitude=129.1)
    d = evaluate_geocode([cand])
    assert d.status == "matched"
    assert d.confidence == 1.0
    assert d.candidate is cand


def test_evaluate_ambiguous_needs_review():
    kakao = [
        GeocodeCandidate(latitude=35.10, longitude=129.10),
        GeocodeCandidate(latitude=37.50, longitude=127.00),
    ]
    d = evaluate_geocode(kakao, secondary=[])
    assert d.status == "needs_review"
    assert d.reason == "ambiguous"


def test_evaluate_disambiguated_by_naver():
    kakao = [
        GeocodeCandidate(latitude=35.1000, longitude=129.1000),
        GeocodeCandidate(latitude=37.50, longitude=127.00),
    ]
    # Naver 최상위가 Kakao 최상위와 매우 근접 -> 확정
    naver = [GeocodeCandidate(latitude=35.1001, longitude=129.1001, source="naver")]
    d = evaluate_geocode(kakao, naver)
    assert d.status == "matched"
    assert d.reason == "disambiguated_by_naver"
    assert d.confidence == 0.7
