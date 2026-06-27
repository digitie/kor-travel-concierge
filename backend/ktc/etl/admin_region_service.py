"""kor-travel-geo v2 기반 행정구역 보강."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ktc.core.config import Settings, get_settings
from ktc.models import TravelPlace, utcnow

ADMIN_CODE_SOURCE = "kor-travel-geo-v2"


@dataclass(frozen=True)
class AdminRegion:
    """TravelPlace에 저장할 행정구역 코드 묶음."""

    sigungu_code: str | None
    sigungu_name: str | None
    legal_dong_code: str | None
    legal_dong_name: str | None


async def enrich_place_admin_codes(
    session: AsyncSession,
    place: TravelPlace,
    *,
    http_client: httpx.AsyncClient | None = None,
    settings: Settings | None = None,
) -> bool:
    """좌표 기준 행정구역 코드를 채운다.

    외부 API 실패가 장소 확정 흐름을 막지 않도록 best-effort로 동작한다. 이미
    `sigungu_code`와 `legal_dong_code`가 모두 있으면 다시 호출하지 않는다.
    """
    if place.sigungu_code and place.legal_dong_code:
        return False
    resolved_settings = settings or get_settings()
    base_url = resolved_settings.KOR_TRAVEL_GEO_V2_BASE_URL.strip()
    if not _configured(base_url):
        return False
    from ktc.services import settings_service  # 지연 import: place_service 순환 회피

    api_key = await settings_service.get_secret(session, "kor_travel_geo_v2_api_key")
    if not _configured(api_key):
        return False

    async def _fetch(client: httpx.AsyncClient) -> AdminRegion | None:
        return await fetch_admin_region(
            client,
            lat=place.latitude,
            lon=place.longitude,
            base_url=base_url,
            api_key=api_key,
        )

    try:
        if http_client is not None:
            region = await _fetch(http_client)
        else:
            async with httpx.AsyncClient(timeout=10.0) as client:
                region = await _fetch(client)
    except Exception:
        return False
    if region is None:
        return False
    apply_admin_region(place, region)
    return True


async def fetch_admin_region(
    client: httpx.AsyncClient,
    *,
    lat: float,
    lon: float,
    base_url: str,
    api_key: str,
) -> AdminRegion | None:
    """kor-travel-geo v2 reverse 응답에서 행정구역 정보를 추출한다."""
    response = await client.post(
        f"{base_url.rstrip('/')}/v2/reverse",
        params={"key": api_key},
        json={
            "lon": lon,
            "lat": lat,
            "include_region": True,
            "include_zipcode": False,
            "radius_m": 200,
        },
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != "OK":
        return None
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return None
    for candidate in candidates:
        region = _region_from_candidate(candidate)
        if region is not None:
            return region
    return None


def apply_admin_region(place: TravelPlace, region: AdminRegion) -> None:
    """행정구역 정보를 TravelPlace에 반영한다."""
    place.sigungu_code = region.sigungu_code
    place.sigungu_name = region.sigungu_name
    place.legal_dong_code = region.legal_dong_code
    place.legal_dong_name = region.legal_dong_name
    place.admin_code_source = ADMIN_CODE_SOURCE
    place.admin_code_updated_at = utcnow()


def _region_from_candidate(candidate: Any) -> AdminRegion | None:
    if not isinstance(candidate, dict):
        return None
    region = candidate.get("region")
    address = candidate.get("address")
    if not isinstance(region, dict):
        region = {}
    if not isinstance(address, dict):
        address = {}
    sigungu_code = _clean_str(region.get("sig_cd"))
    legal_dong_code = _clean_str(region.get("bjd_cd")) or _clean_str(
        address.get("legal_dong_code")
    )
    if not sigungu_code and not legal_dong_code:
        return None
    sido = _clean_str(region.get("sido"))
    sigungu = _clean_str(region.get("sigungu"))
    legal_dong = _clean_str(region.get("legal_dong")) or _clean_str(
        region.get("eup_myeon_dong")
    )
    return AdminRegion(
        sigungu_code=sigungu_code,
        sigungu_name=_join_name(sido, sigungu),
        legal_dong_code=legal_dong_code,
        legal_dong_name=_join_name(sido, sigungu, legal_dong),
    )


def _join_name(*parts: str | None) -> str | None:
    text = " ".join(part for part in parts if part)
    return text or None


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _configured(value: str | None) -> bool:
    if not value:
        return False
    lowered = value.strip().casefold()
    return not lowered.startswith("your_") and "placeholder" not in lowered
