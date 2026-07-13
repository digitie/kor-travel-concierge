"""검수 멀티 provider 장소 검색 테스트 (httpx MockTransport)."""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from ktc.core.database import get_session
from ktc.etl import llm_client, place_search
from main import app

_GOOGLE_RESPONSE = {
    "places": [
        {
            "id": "ChIJ-google-gamcheon",
            "displayName": {"text": "감천문화마을"},
            "formattedAddress": "부산 사하구 감내2로 203",
            "location": {"latitude": 35.0973904, "longitude": 129.0105924},
            "primaryTypeDisplayName": {"text": "관광 명소"},
        }
    ]
}

_KAKAO_RESPONSE = {
    "documents": [
        {
            "id": "kakao-gamcheon-123",
            "place_name": "감천문화마을",
            "address_name": "부산 사하구 감천동 산10-2",
            "road_address_name": "부산 사하구 감내2로 203",
            "x": "129.010592",
            "y": "35.097390",
            "category_name": "여행 > 관광,명소",
        }
    ]
}

_NAVER_RESPONSE = {
    "items": [
        {
            "title": "<b>감천문화마을</b>",
            "address": "부산광역시 사하구 감천동 1-14",
            "roadAddress": "부산광역시 사하구 감내2로 203",
            "mapx": "1290104393",
            "mapy": "350986415",
            "category": "여행,명소>관광지",
        }
    ]
}


def _client_for(handler) -> AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_search_google_places_normalizes():
    def handler(request):
        assert request.method == "POST"
        assert "places:searchText" in str(request.url)
        return httpx.Response(200, json=_GOOGLE_RESPONSE)

    async with _client_for(handler) as http:
        hits = await place_search.search_google_places(
            http, query="감천문화마을", api_key="k"
        )
    assert len(hits) == 1
    hit = hits[0]
    assert hit["provider"] == "google"
    assert hit["native_id"] == "ChIJ-google-gamcheon"
    assert hit["name"] == "감천문화마을"
    assert hit["latitude"] == 35.0973904
    assert hit["longitude"] == 129.0105924
    assert hit["category"] == "관광 명소"
    assert hit["storage_allowed"] is False
    assert "Google Places" in hit["storage_block_reason"]


@pytest.mark.asyncio
async def test_search_google_places_error_includes_google_body():
    def handler(request):
        return httpx.Response(
            403,
            json={
                "error": {
                    "code": 403,
                    "message": "Requests from this Android client application are blocked.",
                    "status": "PERMISSION_DENIED",
                }
            },
        )

    async with _client_for(handler) as http:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await place_search.search_google_places(
                http, query="감천문화마을", api_key="k"
            )
    message = str(exc_info.value)
    assert "Google Places 403" in message
    assert "PERMISSION_DENIED" in message
    assert "Android client" in message


@pytest.mark.asyncio
async def test_search_kakao_normalizes_xy():
    def handler(request):
        assert "dapi.kakao.com" in str(request.url)
        assert request.headers["Authorization"].startswith("KakaoAK ")
        return httpx.Response(200, json=_KAKAO_RESPONSE)

    async with _client_for(handler) as http:
        hits = await place_search.search_kakao(http, query="감천문화마을", api_key="k")
    assert hits[0]["provider"] == "kakao"
    assert hits[0]["native_id"] == "kakao-gamcheon-123"
    # x=경도, y=위도
    assert hits[0]["longitude"] == 129.010592
    assert hits[0]["latitude"] == 35.097390
    assert hits[0]["road_address"] == "부산 사하구 감내2로 203"
    assert hits[0]["storage_allowed"] is True
    assert hits[0]["storage_block_reason"] is None


@pytest.mark.asyncio
async def test_search_naver_local_converts_and_strips():
    def handler(request):
        assert "openapi.naver.com" in str(request.url)
        assert request.headers["X-Naver-Client-Id"] == "id"
        return httpx.Response(200, json=_NAVER_RESPONSE)

    async with _client_for(handler) as http:
        hits = await place_search.search_naver_local(
            http, query="감천문화마을", client_id="id", client_secret="sec"
        )
    hit = hits[0]
    assert hit["provider"] == "naver"
    assert hit["native_id"] is None
    assert hit["name"] == "감천문화마을"  # <b> 제거됨
    # mapx/mapy(WGS84×10⁷) → 위경도
    assert hit["longitude"] == 129.0104393
    assert hit["latitude"] == 35.0986415
    assert hit["storage_allowed"] is True
    assert hit["storage_block_reason"] is None


async def test_gemini_place_opinion_parses(monkeypatch):
    async def fake_complete_json(*a, **k):
        return '{"best_name":"감천문화마을","latitude":35.097,"longitude":129.01,"category":"관광지","confidence":0.9,"reason":"세 provider 일치"}'

    monkeypatch.setattr(llm_client, "complete_json", fake_complete_json)
    runtime = llm_client.LlmRuntime(model="gemini-2.5-flash", gemini_api_key="k")
    out = await place_search.gemini_place_opinion(
        runtime, query="감천문화마을", hits=[{"provider": "google", "name": "감천문화마을"}]
    )
    assert out is not None
    assert out["best_name"] == "감천문화마을"
    assert out["confidence"] == 0.9


async def test_gemini_place_opinion_failure_returns_none(monkeypatch):
    async def boom(*a, **k):
        raise llm_client.LlmRequestError("fail", status_code=500, model="gemini-2.5-flash")

    monkeypatch.setattr(llm_client, "complete_json", boom)
    runtime = llm_client.LlmRuntime(model="gemini-2.5-flash", gemini_api_key="k")
    assert (
        await place_search.gemini_place_opinion(
            runtime, query="x", hits=[{"provider": "kakao", "name": "x"}]
        )
        is None
    )
    # 빈 후보면 호출 없이 None.
    assert await place_search.gemini_place_opinion(runtime, query="x", hits=[]) is None


@pytest_asyncio.fixture
async def api_client(session_factory):
    async def override_get_session():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_place_search_endpoint_isolates_missing_keys(api_client, monkeypatch):
    # 테스트 환경은 provider 키가 없으므로 모두 빈 결과 + errors에 사유.
    resp = await api_client.get("/api/v1/place-search", params={"q": "감천문화마을"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "감천문화마을"
    searched_at = datetime.fromisoformat(body["searched_at"])
    assert searched_at.tzinfo is not None
    assert body["google"] == [] and body["kakao"] == [] and body["naver"] == []
    assert set(body["errors"]).issuperset({"google", "kakao", "naver"})
    # Gemini 의견은 GET에서 제거됨(별도 POST /place-search/opinion).
    assert "gemini" not in body


@pytest.mark.asyncio
async def test_place_search_opinion_endpoint_bounded(api_client, monkeypatch):
    # 빈 후보 → LLM 호출 없이 None.
    empty = await api_client.post(
        "/api/v1/place-search/opinion", json={"query": "감천문화마을", "hits": []}
    )
    assert empty.status_code == 200
    assert empty.json() == {"gemini": None, "error": None}

    hit = {
        "provider": "google",
        "name": "감천문화마을",
        "address": None,
        "road_address": None,
        "latitude": 35.1,
        "longitude": 129.0,
        "category": None,
    }

    async def fake_opinion(runtime, *, query, hits, **kwargs):
        return {
            "best_name": "감천문화마을",
            "latitude": 35.1,
            "longitude": 129.0,
            "confidence": 0.9,
            "reason": "ok",
        }

    monkeypatch.setattr(place_search, "gemini_place_opinion", fake_opinion)
    ok = await api_client.post(
        "/api/v1/place-search/opinion",
        json={"query": "감천문화마을", "hits": [hit]},
    )
    assert ok.status_code == 200
    ok_body = ok.json()
    assert ok_body["error"] is None
    assert ok_body["gemini"]["best_name"] == "감천문화마을"

    # LLM 실패는 500이 아니라 gemini=null로 흡수.
    async def boom(runtime, *, query, hits, **kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(place_search, "gemini_place_opinion", boom)
    failed = await api_client.post(
        "/api/v1/place-search/opinion",
        json={"query": "감천문화마을", "hits": [hit]},
    )
    assert failed.status_code == 200
    assert failed.json()["gemini"] is None
    assert failed.json()["error"]
