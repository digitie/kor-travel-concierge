"""Kakao / Naver / VWorld 지오코딩·역지오코딩 어댑터.

공식 공급자 API만 사용하며 `kraddr-geo`는 연계하지 않는다(ADR-8).

- Kakao Local API: 1차 주소 검색·좌표 변환·카테고리 식별
- Naver API: 모호한 결과 보조 검증
- VWorld API: 좌표 기반 행정/도로명 주소 보강(역지오코딩)
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
from dataclasses import dataclass

import httpx

# 모호 후보 좌표 일치 판정 반경(미터)과 최소 매칭 신뢰도
DISAMBIGUATION_RADIUS_M = 150.0
MIN_MATCH_CONFIDENCE = 0.5


@dataclass
class GeocodeCandidate:
    latitude: float
    longitude: float
    place_name: str | None = None
    road_address: str | None = None
    official_address: str | None = None
    category: str | None = None
    source: str = "kakao"


@dataclass
class GeocodeDecision:
    """지오코딩 평가 결과."""

    status: str  # matched | needs_review
    candidate: GeocodeCandidate | None
    confidence: float
    reason: str
    candidate_count: int


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
    """429 응답에 지수 백오프 + 지터를 적용해 재시도한다."""
    attempt = 0
    while True:
        if semaphore is not None:
            async with semaphore:
                resp = await send()
        else:
            resp = await send()
        if resp.status_code != 429 or attempt >= max_retries:
            return resp
        delay = base_delay * (2**attempt) + random.uniform(0, base_delay)
        await asyncio.sleep(delay)
        attempt += 1


# --- 공급자 어댑터 ---


class KakaoGeocoder:
    URL = "https://dapi.kakao.com/v2/local/search/address.json"

    def __init__(self, api_key: str, http_client: httpx.AsyncClient, **backoff):
        self._key = api_key
        self._client = http_client
        self._backoff = backoff

    async def geocode(self, address: str) -> list[GeocodeCandidate]:
        async def send() -> httpx.Response:
            return await self._client.get(
                self.URL,
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


class VWorldReverseGeocoder:
    URL = "https://api.vworld.kr/req/address"

    def __init__(self, service_key: str, http_client: httpx.AsyncClient, **backoff):
        self._key = service_key
        self._client = http_client
        self._backoff = backoff

    async def reverse(self, lat: float, lng: float) -> dict[str, str | None]:
        """좌표 → 도로명/지번 주소 보강."""

        async def fetch(addr_type: str) -> str | None:
            async def send() -> httpx.Response:
                return await self._client.get(
                    self.URL,
                    params={
                        "service": "address",
                        "request": "getAddress",
                        "point": f"{lng},{lat}",
                        "type": addr_type,
                        "key": self._key,
                    },
                )

            resp = await request_with_backoff(send, **self._backoff)
            if resp.status_code != 200:
                return None
            results = resp.json().get("response", {}).get("result", [])
            return results[0].get("text") if results else None

        return {
            "road_address": await fetch("road"),
            "parcel_address": await fetch("parcel"),
        }


# --- 결과 평가 ---


def evaluate_geocode(
    kakao: list[GeocodeCandidate], naver: list[GeocodeCandidate] | None = None
) -> GeocodeDecision:
    """Kakao 결과를 1차로, Naver를 보조 검증으로 사용해 매칭 여부를 판정한다."""
    from app.services.place_service import haversine_meters

    naver = naver or []
    count = len(kakao)

    if count == 0:
        return GeocodeDecision("needs_review", None, 0.0, "no_result", 0)

    if count == 1:
        return GeocodeDecision("matched", kakao[0], 1.0, "single_result", 1)

    # 후보 과다: Naver 최상위와 좌표가 근접하면 확정, 아니면 검수 대기
    top = kakao[0]
    if naver:
        dist = haversine_meters(
            top.latitude, top.longitude, naver[0].latitude, naver[0].longitude
        )
        if dist <= DISAMBIGUATION_RADIUS_M:
            return GeocodeDecision("matched", top, 0.7, "disambiguated_by_naver", count)

    confidence = 1.0 / count
    return GeocodeDecision("needs_review", None, confidence, "ambiguous", count)
