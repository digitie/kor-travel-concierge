"""kor-travel-geo v2 기반 행정구역 보강."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import BigInteger, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ktc.core.config import Settings, get_settings
from ktc.models import AuditLog, TravelPlace, utcnow

ADMIN_CODE_SOURCE = "kor-travel-geo-v2"
_PLACE_XMIN = literal_column("travel_places.xmin::text::bigint", type_=BigInteger)


@dataclass(frozen=True)
class AdminRegion:
    """TravelPlace에 저장할 행정구역 코드 묶음."""

    sigungu_code: str | None
    sigungu_name: str | None
    legal_dong_code: str | None
    legal_dong_name: str | None


@dataclass(frozen=True)
class AdminEnrichmentSnapshot:
    """외부 admin 조회 요청과 늦은 응답의 안전한 적용을 잇는 장소 snapshot."""

    place_id: int
    version: int
    latitude: float
    longitude: float
    sigungu_code: str | None
    sigungu_name: str | None
    legal_dong_code: str | None
    legal_dong_name: str | None
    admin_code_source: str | None
    admin_code_updated_at: datetime | None


@dataclass(frozen=True)
class AdminEnrichmentGuard:
    """MCP pending owner만 외부 조회 결과를 적용하도록 묶는 fencing token."""

    audit_log_id: int
    pending_owner: str


def _admin_snapshot(place: TravelPlace, version: int) -> AdminEnrichmentSnapshot:
    return AdminEnrichmentSnapshot(
        place_id=place.place_id,
        version=version,
        latitude=place.latitude,
        longitude=place.longitude,
        sigungu_code=place.sigungu_code,
        sigungu_name=place.sigungu_name,
        legal_dong_code=place.legal_dong_code,
        legal_dong_name=place.legal_dong_name,
        admin_code_source=place.admin_code_source,
        admin_code_updated_at=place.admin_code_updated_at,
    )


async def resolve_admin_region(
    snapshot: AdminEnrichmentSnapshot,
    *,
    base_url: str,
    api_key: str,
    http_client: httpx.AsyncClient | None = None,
) -> AdminRegion | None:
    """DB session 없이 장소 snapshot의 행정구역을 외부 API에서 조회한다."""

    async def _fetch(client: httpx.AsyncClient) -> AdminRegion | None:
        return await fetch_admin_region(
            client,
            lat=snapshot.latitude,
            lon=snapshot.longitude,
            base_url=base_url,
            api_key=api_key,
        )

    if http_client is not None:
        return await _fetch(http_client)
    async with httpx.AsyncClient(timeout=10.0) as client:
        return await _fetch(client)


async def enrich_place_admin_codes_isolated(
    session_factory: async_sessionmaker[AsyncSession],
    place_id: int,
    *,
    http_client: httpx.AsyncClient | None = None,
    settings: Settings | None = None,
    apply_guard: AdminEnrichmentGuard | None = None,
) -> bool:
    """별도 짧은 DB session들 사이에서 admin HTTP를 수행하고 조건부 적용한다.

    place/secret SELECT transaction은 HTTP 전에 끝낸다. 응답 적용 시 최신 장소를
    `FOR UPDATE`로 다시 읽어 요청 xmin·좌표·기존 admin 필드가 모두 그대로일 때만 쓴다.
    모든 실패는 이 격리 session 안에서 흡수해 core 장소 확정과 호출자 session을 보존한다.
    """
    resolved_settings = settings or get_settings()
    base_url = resolved_settings.KOR_TRAVEL_GEO_V2_BASE_URL.strip()
    if not _configured(base_url):
        return False

    try:
        from ktc.services import settings_service  # 지연 import: 순환 회피

        async with session_factory() as read_session:
            row = (
                await read_session.execute(
                    select(TravelPlace, _PLACE_XMIN).where(
                        TravelPlace.place_id == place_id
                    )
                )
            ).one_or_none()
            if row is None:
                await read_session.commit()
                return False
            place, version = row
            snapshot = _admin_snapshot(place, int(version))
            if snapshot.sigungu_code and snapshot.legal_dong_code:
                await read_session.commit()
                return False
            if apply_guard is not None and not await _admin_guard_matches(
                read_session,
                apply_guard,
            ):
                await read_session.commit()
                return False
            api_key = await settings_service.get_secret(
                read_session, "kor_travel_geo_v2_api_key"
            )
            # place/secret SELECT가 연 transaction과 connection을 HTTP 전에 반환한다.
            await read_session.commit()
        if not _configured(api_key):
            return False

        region = await resolve_admin_region(
            snapshot,
            base_url=base_url,
            api_key=api_key,
            http_client=http_client,
        )
        if region is None:
            return False

        async with session_factory() as write_session:
            row = (
                await write_session.execute(
                    select(TravelPlace, _PLACE_XMIN)
                    .where(TravelPlace.place_id == place_id)
                    .with_for_update()
                )
            ).one_or_none()
            if row is None:
                await write_session.commit()
                return False
            current, current_version = row
            if _admin_snapshot(current, int(current_version)) != snapshot:
                await write_session.commit()
                return False
            # finalizer와 같은 place -> audit lock 순서를 지킨다. 외부 HTTP 뒤에도
            # pending owner가 그대로인 경우에만 늦은 응답을 실제 장소에 적용한다.
            if apply_guard is not None and not await _admin_guard_matches(
                write_session,
                apply_guard,
                for_update=True,
            ):
                await write_session.commit()
                return False
            apply_admin_region(current, region)
            await write_session.commit()
            return True
    except Exception:
        return False


async def _admin_guard_matches(
    session: AsyncSession,
    guard: AdminEnrichmentGuard,
    *,
    for_update: bool = False,
) -> bool:
    stmt = (
        select(AuditLog)
        .where(AuditLog.id == guard.audit_log_id)
        .execution_options(populate_existing=True)
    )
    if for_update:
        stmt = stmt.with_for_update()
    audit_log = (await session.execute(stmt)).scalar_one_or_none()
    if audit_log is None or not audit_log.payload_json:
        return False
    try:
        payload = json.loads(audit_log.payload_json)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    return (
        audit_log.idempotency_key is not None
        and audit_log.idempotency_state == "pending"
        and payload.get("idempotency_key") == audit_log.idempotency_key
        and payload.get("idempotency_state") == audit_log.idempotency_state
        and payload.get("pending_owner") == guard.pending_owner
    )


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
        candidates = []
    best_region: AdminRegion | None = None
    for candidate in candidates:
        region = _region_from_candidate(candidate)
        if _is_complete(region):
            return region
        if best_region is None:
            best_region = region
    radius_region = await _fetch_region_within_radius(
        client,
        lat=lat,
        lon=lon,
        base_url=base_url,
        api_key=api_key,
    )
    if best_region is not None and radius_region is not None:
        return _merge_region(best_region, radius_region)
    if best_region is not None:
        return best_region
    return radius_region


async def _fetch_region_within_radius(
    client: httpx.AsyncClient,
    *,
    lat: float,
    lon: float,
    base_url: str,
    api_key: str,
) -> AdminRegion | None:
    response = await client.post(
        f"{base_url.rstrip('/')}/v2/regions/within-radius",
        params={"key": api_key},
        json={
            "lon": lon,
            "lat": lat,
            "radius_km": 1,
            "levels": ["sido", "sigungu", "emd"],
        },
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != "OK":
        return None
    return _region_from_radius_payload(payload)


def _region_from_radius_payload(payload: Any) -> AdminRegion | None:
    if not isinstance(payload, dict):
        return None
    sido = _first_region_item(payload.get("sido"))
    sigungu = _first_region_item(payload.get("sigungu"))
    emd = _first_region_item(payload.get("emd"))
    sigungu_code = _clean_str(sigungu.get("code")) if sigungu else None
    emd_code = _normalize_legal_dong_code(_clean_str(emd.get("code")) if emd else None)
    if not sigungu_code and not emd_code:
        return None
    sido_name = _clean_str(sido.get("name")) if sido else None
    sigungu_name = _clean_str(sigungu.get("name")) if sigungu else None
    emd_name = _clean_str(emd.get("name")) if emd else None
    return AdminRegion(
        sigungu_code=sigungu_code,
        sigungu_name=_join_name(sido_name, sigungu_name),
        legal_dong_code=emd_code,
        legal_dong_name=_join_name(sido_name, sigungu_name, emd_name),
    )


def _first_region_item(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, list):
        return None
    for item in value:
        if isinstance(item, dict):
            return item
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
    legal_dong_code = _normalize_legal_dong_code(legal_dong_code)
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


def _merge_region(primary: AdminRegion, fallback: AdminRegion) -> AdminRegion:
    return AdminRegion(
        sigungu_code=primary.sigungu_code or fallback.sigungu_code,
        sigungu_name=primary.sigungu_name or fallback.sigungu_name,
        legal_dong_code=primary.legal_dong_code or fallback.legal_dong_code,
        legal_dong_name=primary.legal_dong_name or fallback.legal_dong_name,
    )


def _is_complete(region: AdminRegion | None) -> bool:
    return bool(region and region.sigungu_code and region.legal_dong_code)


def _normalize_legal_dong_code(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) == 8 and value.isdigit():
        return f"{value}00"
    return value


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
