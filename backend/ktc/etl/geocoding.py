"""VWorld / Kakao / Naver 지오코딩·역지오코딩 호출 유틸리티.

공식 공급자 API만 사용하며 `kraddr-geo`는 연계하지 않는다(ADR-8).

- VWorld API: `python-vworld-api`의 `AsyncVworldClient` 직접 호출
- Kakao Local API: VWorld 미매칭 시 주소 검색 후 키워드 장소 검색 보조
- Naver API: 모호한 결과 보조 검증
- 좌표는 `pyproj` `always_xy=True`로 WGS84(EPSG:4326) 경도/위도 순서 정규화
- 429 응답은 지수 백오프 + 지터로 재시도, 동시성은 Semaphore로 상한

지오코딩 실패·후보 과다·낮은 신뢰도는 자동 확정하지 않고 `needs_review`로 남긴다
(`docs/architecture.md` 4.5, ADR-16).

HTTP 호출은 `httpx.AsyncClient`를 주입받아 테스트에서 `MockTransport`로 대체한다.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx
from vworld import AsyncVworldClient, VworldError, VworldNoDataError

# 모호 후보 좌표 일치 판정 반경(미터)과 최소 매칭 신뢰도
DISAMBIGUATION_RADIUS_M = 150.0
MIN_MATCH_CONFIDENCE = 0.5


class GeocodeResultKind(str, Enum):
    """provider 지오코딩 결과의 성격(로드맵 PR-12, B3).

    `place_name` 필드의 의미가 kind마다 다르므로 이름 게이트를 kind별로 다르게 적용한다.
    Kakao 주소검색·VWorld 정제 결과의 `place_name`은 POI명이 아니라 주소일 수 있어,
    POI 이름 게이트를 그대로 걸면 오판한다.
    """

    # place_name이 실제 POI 상호명(Kakao 키워드 장소 검색). 이름 게이트 대상.
    POI = "poi"
    # place_name이 주소 문자열(Kakao 주소검색·VWorld 정제·Naver). POI 이름 게이트 skip.
    ADDRESS = "address"
    # 정제 주소 없이 좌표에 snap된 echo(VWorld unrefined). POI 이름 게이트 skip.
    COORDINATE = "coordinate"


def derive_result_kind(source: str, refined: bool) -> str:
    """provider source·refined 여부로 result_kind를 판별한다.

    - `kakao_keyword`: 키워드 장소 검색 → place_name이 POI명 → poi.
    - `vworld` + not refined: 정제 주소 없이 좌표 snap → coordinate.
    - 그 외(kakao 주소검색, vworld 정제, naver): place_name이 주소 → address.
    """
    if source == "kakao_keyword":
        return GeocodeResultKind.POI.value
    if source == "vworld" and not refined:
        return GeocodeResultKind.COORDINATE.value
    return GeocodeResultKind.ADDRESS.value


@dataclass
class GeocodeCandidate:
    latitude: float
    longitude: float
    place_name: str | None = None
    road_address: str | None = None
    official_address: str | None = None
    category: str | None = None
    source: str = "kakao"
    # VWorld get_coord가 실제 정제 주소(refined.text)를 반환했는지 여부. False면 질의를
    # 임의 좌표에 snap하고 입력을 echo만 한 것 → 자동 확정 금지(검수 큐로).
    refined: bool = True
    # 결과 성격(poi|address|coordinate). None이면 source·refined에서 파생한다(단일 규칙).
    result_kind: str | None = None

    def __post_init__(self) -> None:
        if self.result_kind is None:
            self.result_kind = derive_result_kind(self.source, self.refined)


@dataclass
class GeocodeDecision:
    """지오코딩 평가 결과."""

    status: str  # matched | needs_review
    candidate: GeocodeCandidate | None
    confidence: float
    reason: str
    candidate_count: int
    provider_evidence: dict[str, Any] = field(default_factory=dict)
    # 1차 공급자 후보 원본(ambiguous 단일 게이트 통과 자동확정에서 재평가용, 로드맵 PR-12).
    # 다건(ambiguous)일 때만 채운다 — 이름·행정구역 게이트를 후보별로 다시 적용한다.
    primary_candidates: list[GeocodeCandidate] = field(default_factory=list)


# --- 좌표 정규화 ---


def normalize_to_wgs84(
    x: float, y: float, *, source_crs: str = "EPSG:4326"
) -> tuple[float, float]:
    """좌표를 WGS84 경도/위도(always_xy) 순서로 정규화한다.

    `pyproj` 미설치 또는 이미 4326이면 입력을 그대로 반환한다.
    """
    if source_crs.upper() in ("EPSG:4326", "WGS84"):
        return x, y
    try:
        from pyproj import Transformer  # type: ignore
    except ImportError:
        return x, y
    transformer = Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)
    lng, lat = transformer.transform(x, y)
    return lng, lat


# --- 429 백오프 / 동시성 ---


async def request_with_backoff(
    send: Callable[[], Awaitable[httpx.Response]],
    *,
    max_retries: int = 3,
    base_delay: float = 0.5,
    semaphore: asyncio.Semaphore | None = None,
) -> httpx.Response:
    """429/5xx/네트워크 오류에 지수 백오프 + 지터를 적용해 재시도한다."""
    attempt = 0
    while True:
        try:
            if semaphore is not None:
                async with semaphore:
                    resp = await send()
            else:
                resp = await send()
        except httpx.HTTPError:
            if attempt >= max_retries:
                raise
            delay = base_delay * (2**attempt) + random.uniform(0, base_delay)
            await asyncio.sleep(delay)
            attempt += 1
            continue
        if resp.status_code not in {429, 500, 502, 503, 504} or attempt >= max_retries:
            return resp
        delay = base_delay * (2**attempt) + random.uniform(0, base_delay)
        await asyncio.sleep(delay)
        attempt += 1


# --- 외부 공급자 호출 ---


class KakaoGeocoder:
    ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"
    KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"

    def __init__(self, api_key: str, http_client: httpx.AsyncClient, **backoff):
        self._key = api_key
        self._client = http_client
        self._backoff = backoff

    async def geocode(self, query: str) -> list[GeocodeCandidate]:
        """주소 검색 결과가 없으면 Kakao 키워드 장소 검색을 보조로 사용한다."""

        address_results = await self.search_address(query)
        if address_results:
            return address_results
        return await self.search_keyword(query)

    async def search_address(self, address: str) -> list[GeocodeCandidate]:
        async def send() -> httpx.Response:
            return await self._client.get(
                self.ADDRESS_URL,
                params={"query": address},
                headers={"Authorization": f"KakaoAK {self._key}"},
            )

        resp = await request_with_backoff(send, **self._backoff)
        resp.raise_for_status()
        docs = resp.json().get("documents", [])
        out: list[GeocodeCandidate] = []
        for d in docs:
            lng, lat = normalize_to_wgs84(float(d["x"]), float(d["y"]))
            road = (d.get("road_address") or {}).get("address_name")
            jibun = (d.get("address") or {}).get("address_name")
            out.append(
                GeocodeCandidate(
                    latitude=lat,
                    longitude=lng,
                    place_name=d.get("address_name"),
                    road_address=road,
                    official_address=jibun,
                    source="kakao",
                )
            )
        return out

    async def search_keyword(
        self,
        query: str,
        *,
        category_group_code: str | None = None,
        x: float | None = None,
        y: float | None = None,
        radius: int | None = None,
        rect: str | None = None,
        page: int = 1,
        size: int = 10,
        sort: str = "accuracy",
    ) -> list[GeocodeCandidate]:
        """Kakao Local의 키워드 장소 검색 결과를 내부 후보로 변환한다."""

        params: dict[str, str | int | float] = {
            "query": query,
            "page": page,
            "size": size,
            "sort": sort,
        }
        if category_group_code:
            params["category_group_code"] = category_group_code
        if x is not None:
            params["x"] = x
        if y is not None:
            params["y"] = y
        if radius is not None:
            params["radius"] = radius
        if rect:
            params["rect"] = rect

        async def send() -> httpx.Response:
            return await self._client.get(
                self.KEYWORD_URL,
                params=params,
                headers={"Authorization": f"KakaoAK {self._key}"},
            )

        resp = await request_with_backoff(send, **self._backoff)
        resp.raise_for_status()
        docs = resp.json().get("documents", [])
        out: list[GeocodeCandidate] = []
        for d in docs:
            lng, lat = normalize_to_wgs84(float(d["x"]), float(d["y"]))
            out.append(
                GeocodeCandidate(
                    latitude=lat,
                    longitude=lng,
                    place_name=d.get("place_name"),
                    road_address=d.get("road_address_name") or None,
                    official_address=d.get("address_name") or None,
                    category=d.get("category_name") or d.get("category_group_name"),
                    source="kakao_keyword",
                )
            )
        return out


class NaverGeocoder:
    URL = "https://naveropenapi.apigw.ntruss.com/map-geocode/v2/geocode"

    def __init__(
        self, client_id: str, client_secret: str, http_client: httpx.AsyncClient, **backoff
    ):
        self._id = client_id
        self._secret = client_secret
        self._client = http_client
        self._backoff = backoff

    async def geocode(self, address: str) -> list[GeocodeCandidate]:
        async def send() -> httpx.Response:
            return await self._client.get(
                self.URL,
                params={"query": address},
                headers={
                    "X-NCP-APIGW-API-KEY-ID": self._id,
                    "X-NCP-APIGW-API-KEY": self._secret,
                },
            )

        resp = await request_with_backoff(send, **self._backoff)
        resp.raise_for_status()
        addrs = resp.json().get("addresses", [])
        out: list[GeocodeCandidate] = []
        for a in addrs:
            lng, lat = normalize_to_wgs84(float(a["x"]), float(a["y"]))
            out.append(
                GeocodeCandidate(
                    latitude=lat,
                    longitude=lng,
                    road_address=a.get("roadAddress"),
                    official_address=a.get("jibunAddress"),
                    source="naver",
                )
            )
        return out


async def geocode_with_vworld(
    client: AsyncVworldClient,
    address: str,
) -> list[GeocodeCandidate]:
    """`AsyncVworldClient`를 직접 호출해 VWorld 좌표 후보를 만든다."""

    out: list[GeocodeCandidate] = []
    by_coord: dict[tuple[float, float], GeocodeCandidate] = {}
    for addr_type in ("road", "parcel"):
        try:
            payload = await client.get_coord(
                address,
                addr_type,
                refine=True,
                simple=False,
                crs="EPSG:4326",
            )
        except VworldNoDataError:
            continue
        except (VworldError, httpx.HTTPError):
            continue

        candidate = _candidate_from_vworld_get_coord(payload, addr_type, address)
        if candidate is None:
            continue
        key = (round(candidate.latitude, 7), round(candidate.longitude, 7))
        existing = by_coord.get(key)
        if existing is not None:
            existing.road_address = existing.road_address or candidate.road_address
            existing.official_address = (
                existing.official_address or candidate.official_address
            )
            existing.place_name = existing.place_name or candidate.place_name
            continue
        by_coord[key] = candidate
        out.append(candidate)
    return out


async def reverse_with_vworld(
    client: AsyncVworldClient,
    lat: float,
    lng: float,
) -> dict[str, str | None]:
    """`AsyncVworldClient`를 직접 호출해 좌표의 도로명/지번 주소를 조회한다."""

    return {
        "road_address": await _reverse_vworld_text(client, lat, lng, "road"),
        "parcel_address": await _reverse_vworld_text(client, lat, lng, "parcel"),
    }


def _candidate_from_vworld_get_coord(
    payload: dict[str, Any],
    addr_type: str,
    original_address: str,
) -> GeocodeCandidate | None:
    body = payload.get("response", {})
    if not isinstance(body, dict) or body.get("status") != "OK":
        return None
    result = body.get("result") or {}
    if not isinstance(result, dict):
        return None
    point = result.get("point") or {}
    if not isinstance(point, dict) or "x" not in point or "y" not in point:
        return None
    lng, lat = normalize_to_wgs84(float(point["x"]), float(point["y"]))
    refined_text = _vworld_result_text(result)
    text = refined_text or original_address
    return GeocodeCandidate(
        latitude=lat,
        longitude=lng,
        place_name=text,
        road_address=text if addr_type == "road" else None,
        official_address=text if addr_type == "parcel" else None,
        source="vworld",
        refined=bool(refined_text),
    )


async def _reverse_vworld_text(
    client: AsyncVworldClient,
    lat: float,
    lng: float,
    addr_type: str,
) -> str | None:
    try:
        payload = await client.reverse_geocode_latlon(
            lat,
            lng,
            type=addr_type,
            zipcode=True,
            simple=False,
            crs="EPSG:4326",
        )
    except (VworldNoDataError, VworldError, httpx.HTTPError):
        return None

    results = payload.get("response", {}).get("result", [])
    if isinstance(results, dict):
        results = [results]
    if not isinstance(results, list) or not results:
        return None
    first = results[0]
    if not isinstance(first, dict):
        return None
    text = first.get("text")
    return str(text) if text else None


# --- 결과 평가 ---


def evaluate_geocode(
    primary: list[GeocodeCandidate],
    secondary: list[GeocodeCandidate] | None = None,
    *,
    secondary_name: str = "naver",
) -> GeocodeDecision:
    """1차 공급자 결과와 보조 공급자 좌표 근접도로 매칭 여부를 판정한다."""
    from ktc.services.place_service import haversine_meters

    secondary = secondary or []
    count = len(primary)
    evidence = {
        "primary": [_candidate_to_evidence(candidate) for candidate in primary],
        "secondary": [_candidate_to_evidence(candidate) for candidate in secondary],
        "secondary_name": secondary_name,
    }

    if count == 0:
        return GeocodeDecision("needs_review", None, 0.0, "no_result", 0, evidence)

    if count == 1:
        only = primary[0]
        # VWorld가 정제 주소 없이 질의를 임의 좌표에 snap한 단일 결과(우버/GS25/대한민국
        # 같은 비-POI 또는 매칭 실패)는 자동 확정하지 않고 검수 큐로 보낸다.
        if not getattr(only, "refined", True):
            return GeocodeDecision(
                "needs_review", only, 0.3, "vworld_unrefined_single", 1, evidence
            )
        return GeocodeDecision("matched", only, 1.0, "single_result", 1, evidence)

    # 후보 과다: 보조 공급자 최상위와 좌표가 근접하면 확정, 아니면 검수 대기
    top = primary[0]
    if secondary:
        dist = haversine_meters(
            top.latitude, top.longitude, secondary[0].latitude, secondary[0].longitude
        )
        if dist <= DISAMBIGUATION_RADIUS_M:
            return GeocodeDecision(
                "matched",
                top,
                0.7,
                f"disambiguated_by_{secondary_name}",
                count,
                evidence,
            )

    confidence = 1.0 / count
    return GeocodeDecision(
        "needs_review",
        None,
        confidence,
        "ambiguous",
        count,
        evidence,
        primary_candidates=list(primary),
    )


def _candidate_to_evidence(candidate: GeocodeCandidate) -> dict[str, Any]:
    return {
        "source": candidate.source,
        "result_kind": candidate.result_kind,
        "place_name": candidate.place_name,
        "road_address": candidate.road_address,
        "official_address": candidate.official_address,
        "category": candidate.category,
        "latitude": candidate.latitude,
        "longitude": candidate.longitude,
    }


def _vworld_result_text(result: dict) -> str | None:
    refined = result.get("refined")
    if isinstance(refined, dict) and refined.get("text"):
        return refined["text"]
    if result.get("text"):
        return result["text"]
    structure = result.get("structure")
    if isinstance(structure, dict):
        parts = [
            structure.get(name)
            for name in (
                "level1",
                "level2",
                "level3",
                "level4L",
                "level4LC",
                "level4A",
                "level4AC",
                "level5",
            )
            if structure.get(name)
        ]
        return " ".join(parts) if parts else None
    return None
