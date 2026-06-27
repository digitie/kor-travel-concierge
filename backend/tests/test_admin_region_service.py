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
