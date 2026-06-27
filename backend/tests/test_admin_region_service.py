"""kor-travel-geo v2 행정코드 보강 테스트."""

from __future__ import annotations

import httpx

from ktc.etl import admin_region_service


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
