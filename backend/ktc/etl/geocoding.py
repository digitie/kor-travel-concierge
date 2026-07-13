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
import hashlib
import json
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from vworld import AsyncVworldClient, VworldError, VworldNoDataError

from ktc.models.geocode_cache import GeocodeCache

logger = logging.getLogger(__name__)

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


# =========================================================================
# provider별 지오코딩 결과 캐시 (T-170, S7)
#
# 같은 장소가 여러 영상에 반복 등장할 때 지오코딩 provider를 매번 재호출하는 문제를
# provider별 DB 캐시로 줄인다. **단, provider 약관을 엄격히 지킨다.**
# `docs/provider-policy.md`의 provider policy matrix에서 캐싱이 허용된 provider만
# 저장한다 — 결과적으로 메인 지오코딩 파이프라인에서 실제 캐시되는 provider는 **Kakao뿐**이다.
# VWorld(문면상 저장 불허)와 Naver(NCP Maps 제7조⑨·⑪ / Developers Local Search 7.3.③,
# 캐시 포함 금지)는 정책상 제외한다. 이 provider-gated allowlist가 T-170의 핵심 정확성이다.
# =========================================================================

# 정규화 로직(현재는 query 문자열 공백 정규화)이 바뀌면 이 상수를 올려 기존 key를 전량
# 버스트한다. key에 provider·endpoint·canonical param과 함께 포함된다.
NORMALIZATION_VERSION = 1


class GeocodeResponseClass(str, Enum):
    """provider 호출 결과의 4분류. 성공만 캐시하고 error는 캐시하지 않는다."""

    SUCCESS_NONEMPTY = "success_nonempty"
    SUCCESS_EMPTY = "success_empty"
    TRANSIENT_ERROR = "transient_error"
    PERMANENT_ERROR = "permanent_error"

    @property
    def is_cacheable_outcome(self) -> bool:
        """성공 응답만 캐시한다. error(transient/permanent)는 항상 재시도 가능하게 캐시 안 함."""
        return self in (
            GeocodeResponseClass.SUCCESS_NONEMPTY,
            GeocodeResponseClass.SUCCESS_EMPTY,
        )


@dataclass(frozen=True)
class ProviderCachePolicy:
    """provider별 캐시 정책(명시적·감사가능). cacheable=False면 조회·저장 모두 스킵한다."""

    provider: str
    cacheable: bool
    positive_ttl_days: float
    negative_ttl_days: float
    allowed_fields: tuple[str, ...]


# Kakao 후보에서 캐시에 저장 가능한 필드(정책 allowed_fields). 파생 result_kind 포함.
_KAKAO_CACHE_FIELDS: tuple[str, ...] = (
    "latitude",
    "longitude",
    "place_name",
    "road_address",
    "official_address",
    "category",
    "source",
    "refined",
    "result_kind",
)

_NON_CACHEABLE_POLICY = ProviderCachePolicy(
    provider="",
    cacheable=False,
    positive_ttl_days=0.0,
    negative_ttl_days=0.0,
    allowed_fields=(),
)

# provider policy matrix (docs/provider-policy.md 정본). 캐시 허용은 Kakao뿐이다.
# - kakao: UX 목적 cache 허용(제5조 반대해석) + 최신 데이터 유지 의무 → positive TTL은
#   보수적으로 30일 이하(기본 14일)로 두어 "최신 유지" 취지를 반영한다.
# - vworld: 문면상 저장 불허("별도의 저장장치나 데이터베이스에 저장할 수 없습니다") → 캐시 금지.
# - naver(NCP Maps geocoding): 제7조⑨·⑪ 저장·DB화·재사용 금지 + 사용자 결정으로 제외 확정.
# - naver_local(Developers Local Search): 7.3.③ 캐시 포함 금지.
# - google_places: 이번 범위 밖(검수 진단 `/place-search`에만 존재) → 비캐시로 명시.
PROVIDER_CACHE_POLICY: dict[str, ProviderCachePolicy] = {
    "kakao": ProviderCachePolicy(
        provider="kakao",
        cacheable=True,
        positive_ttl_days=14.0,
        negative_ttl_days=1.0,
        allowed_fields=_KAKAO_CACHE_FIELDS,
    ),
    "vworld": ProviderCachePolicy("vworld", False, 0.0, 0.0, ()),
    "naver": ProviderCachePolicy("naver", False, 0.0, 0.0, ()),
    "naver_local": ProviderCachePolicy("naver_local", False, 0.0, 0.0, ()),
    "google_places": ProviderCachePolicy("google_places", False, 0.0, 0.0, ()),
}


def cache_policy_for(provider: str) -> ProviderCachePolicy:
    """provider 정책을 조회한다. 미등록 provider는 deny-by-default(비캐시)."""
    return PROVIDER_CACHE_POLICY.get(provider, _NON_CACHEABLE_POLICY)


def is_provider_cacheable(provider: str) -> bool:
    return cache_policy_for(provider).cacheable


def normalize_query_text(text: str | None) -> str:
    """캐시 key 정규화: 앞뒤 공백 제거 + 내부 연속 공백을 1칸으로 축약.

    이 정규화 규칙이 바뀌면 `NORMALIZATION_VERSION`을 올려 기존 key를 버스트한다.
    """
    if not text:
        return ""
    return " ".join(str(text).split())


def _canonical_params(params: dict[str, Any]) -> str:
    """요청 파라미터를 결정적 문자열로 직렬화한다(query는 정규화, None은 제외)."""
    normalized: dict[str, Any] = {}
    for key in sorted(params):
        value = params[key]
        if value is None:
            continue
        normalized[key] = normalize_query_text(value) if key == "query" else value
    return json.dumps(
        normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )


def geocode_cache_key(provider: str, endpoint: str, params: dict[str, Any]) -> str:
    """`sha256(provider|endpoint|canonical_params|NORMALIZATION_VERSION)`."""
    raw = "|".join(
        (provider, endpoint, _canonical_params(params), str(NORMALIZATION_VERSION))
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def classify_geocode_success(
    candidates: list[GeocodeCandidate],
) -> GeocodeResponseClass:
    """200 응답을 건수로 분류한다(0건=success_empty, N건=success_nonempty)."""
    return (
        GeocodeResponseClass.SUCCESS_NONEMPTY
        if candidates
        else GeocodeResponseClass.SUCCESS_EMPTY
    )


def classify_geocode_exception(exc: BaseException) -> GeocodeResponseClass:
    """provider 호출 예외를 transient/permanent로 분류한다.

    429·5xx·타임아웃·네트워크 오류 = transient(재시도 가능), 그 외 4xx(인증/무효) =
    permanent. 어느 쪽도 캐시하지 않으므로(성공만 저장) 이 분류는 진단·테스트용이다.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 429 or 500 <= status < 600:
            return GeocodeResponseClass.TRANSIENT_ERROR
        return GeocodeResponseClass.PERMANENT_ERROR
    if isinstance(exc, httpx.HTTPError):
        # 타임아웃·연결·전송 오류 등은 재시도 가능한 transient로 본다.
        return GeocodeResponseClass.TRANSIENT_ERROR
    return GeocodeResponseClass.PERMANENT_ERROR


def _candidate_to_cache_dict(
    candidate: GeocodeCandidate, allowed_fields: tuple[str, ...]
) -> dict[str, Any]:
    """정책 allowed_fields로만 후보를 직렬화한다(저장 필드 화이트리스트)."""
    full: dict[str, Any] = {
        "latitude": candidate.latitude,
        "longitude": candidate.longitude,
        "place_name": candidate.place_name,
        "road_address": candidate.road_address,
        "official_address": candidate.official_address,
        "category": candidate.category,
        "source": candidate.source,
        "refined": candidate.refined,
        "result_kind": candidate.result_kind,
    }
    return {key: full[key] for key in full if key in allowed_fields}


def _candidate_from_cache_dict(data: dict[str, Any]) -> GeocodeCandidate:
    """캐시 dict를 후보로 복원한다. 저장된 result_kind를 그대로 넘겨 evidence 계약을 보존한다."""
    return GeocodeCandidate(
        latitude=data["latitude"],
        longitude=data["longitude"],
        place_name=data.get("place_name"),
        road_address=data.get("road_address"),
        official_address=data.get("official_address"),
        category=data.get("category"),
        source=data.get("source", "kakao"),
        refined=data.get("refined", True),
        result_kind=data.get("result_kind"),
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GeocodeCacheStore:
    """provider policy allowlist로 게이트된 DB 캐시 접근 계층.

    cacheable=False provider(VWorld/Naver 등)는 조회·저장이 모두 no-op이다. 만료 정리는
    lazy(조회 시 TTL 초과 행 무시, 저장 시 upsert 덮어쓰기)이며 정리 스케줄러는 없다. 각
    호출은 독립 세션을 열어 짧은 트랜잭션으로 처리하므로 provider HTTP 대기 중 메인 세션
    트랜잭션과 분리된다.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        enabled: bool = True,
        ttl_overrides: dict[str, tuple[float, float]] | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._session_factory = session_factory
        self._enabled = enabled
        self._ttl_overrides = ttl_overrides or {}
        self._clock = clock

    def is_cacheable(self, provider: str) -> bool:
        return self._enabled and is_provider_cacheable(provider)

    def _policy(self, provider: str) -> ProviderCachePolicy:
        base = cache_policy_for(provider)
        override = self._ttl_overrides.get(provider)
        if override is None:
            return base
        positive, negative = override
        return replace(base, positive_ttl_days=positive, negative_ttl_days=negative)

    def _ttl(
        self, policy: ProviderCachePolicy, response_class: GeocodeResponseClass
    ) -> timedelta:
        days = (
            policy.positive_ttl_days
            if response_class == GeocodeResponseClass.SUCCESS_NONEMPTY
            else policy.negative_ttl_days
        )
        return timedelta(days=days)

    async def lookup(
        self, provider: str, endpoint: str, params: dict[str, Any]
    ) -> list[GeocodeCandidate] | None:
        """히트+미만료면 후보 목록을, 미스/만료/비캐시면 None을 반환한다."""
        if not self.is_cacheable(provider):
            return None
        policy = self._policy(provider)
        key = geocode_cache_key(provider, endpoint, params)
        async with self._session_factory() as session:
            row = await session.get(GeocodeCache, key)
            if row is None:
                return None
            try:
                response_class = GeocodeResponseClass(row.response_class)
            except ValueError:
                return None
            created = row.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if self._clock() - created > self._ttl(policy, response_class):
                return None  # lazy 만료: 무시(다음 저장이 덮어씀)
            return [
                _candidate_from_cache_dict(item) for item in (row.results_json or [])
            ]

    async def store(
        self,
        provider: str,
        endpoint: str,
        params: dict[str, Any],
        response_class: GeocodeResponseClass,
        candidates: list[GeocodeCandidate],
    ) -> None:
        """cacheable+success일 때만 upsert한다. error는 성공으로 캐시하지 않는다."""
        if not self.is_cacheable(provider):
            return
        if not response_class.is_cacheable_outcome:
            return  # error(429/5xx/타임아웃/4xx)는 캐시 금지
        policy = self._policy(provider)
        key = geocode_cache_key(provider, endpoint, params)
        payload = [
            _candidate_to_cache_dict(candidate, policy.allowed_fields)
            for candidate in candidates
        ]
        now = self._clock()
        statement = (
            pg_insert(GeocodeCache)
            .values(
                query_hash=key,
                provider=provider,
                response_class=response_class.value,
                results_json=payload,
                created_at=now,
            )
            .on_conflict_do_update(
                index_elements=["query_hash"],
                set_={
                    "provider": provider,
                    "response_class": response_class.value,
                    "results_json": payload,
                    "created_at": now,
                },
            )
        )
        async with self._session_factory() as session:
            await session.execute(statement)
            await session.commit()


async def run_with_geocode_cache(
    cache: GeocodeCacheStore | None,
    provider: str,
    endpoint: str,
    params: dict[str, Any],
    fetch: Callable[[], Awaitable[list[GeocodeCandidate]]],
    *,
    force_refresh: bool = False,
) -> list[GeocodeCandidate]:
    """cacheable provider 호출을 캐시로 감싼다.

    - cache 없음 또는 provider 비캐시: fetch를 그대로 실행(캐시 완전 미개입 — VWorld/Naver).
    - 히트+미만료: fetch 없이 캐시 후보 반환(외부 호출 0).
    - 미스/만료: fetch 실행 → 성공만 분류·저장(fetch 예외는 그대로 전파, 저장 안 함).
    - force_refresh: 조회를 건너뛰고 재호출 후 갱신(재처리 훅).

    **캐시는 투명한 최적화(best-effort)여야 한다**: lookup/store 계층의 어떤 예외도
    (별도 세션의 pool timeout·asyncpg 일시 오류·DB hiccup 등) 지오코딩 결과를 절대 바꾸지
    않는다. lookup 실패는 miss로 취급해 provider로 폴백하고, store 실패는 이미 성공적으로
    fetch된 후보를 그대로 반환한다(둘 다 warning 로그만 남긴다). 캐시 오류가 성공 매치를
    조용히 needs_review로 강등시키는 T-170 불변식 위반을 막는다.
    """
    if cache is None or not cache.is_cacheable(provider):
        return await fetch()
    if not force_refresh:
        try:
            cached = await cache.lookup(provider, endpoint, params)
        except Exception:
            # 조회 실패는 miss로 취급하고 provider로 폴백한다(결과 불변).
            logger.warning(
                "지오코딩 캐시 조회 실패 — miss로 폴백 (provider=%s, endpoint=%s)",
                provider,
                endpoint,
                exc_info=True,
            )
            cached = None
        if cached is not None:
            return cached
    candidates = await fetch()
    try:
        await cache.store(
            provider, endpoint, params, classify_geocode_success(candidates), candidates
        )
    except Exception:
        # 저장 실패가 이미 성공한 지오코딩 결과 반환을 막지 않게 한다(best-effort).
        logger.warning(
            "지오코딩 캐시 저장 실패 — 결과는 그대로 반환 (provider=%s, endpoint=%s)",
            provider,
            endpoint,
            exc_info=True,
        )
    return candidates


# --- 외부 공급자 호출 ---


class KakaoGeocoder:
    ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"
    KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
    # provider policy allowlist 키. 주소·키워드 두 endpoint 모두 같은 provider로 묶고
    # endpoint URL을 캐시 key에 포함해 구분한다.
    PROVIDER = "kakao"

    def __init__(
        self,
        api_key: str,
        http_client: httpx.AsyncClient,
        *,
        cache: GeocodeCacheStore | None = None,
        force_refresh: bool = False,
        **backoff,
    ):
        self._key = api_key
        self._client = http_client
        self._backoff = backoff
        # cache=None이면 캐시 완전 미개입(기존 동작). VWorld/Naver는 애초에 이 클래스를 쓰지 않는다.
        self._cache = cache
        self._force_refresh = force_refresh

    async def geocode(self, query: str) -> list[GeocodeCandidate]:
        """주소 검색 결과가 없으면 Kakao 키워드 장소 검색을 보조로 사용한다."""

        address_results = await self.search_address(query)
        if address_results:
            return address_results
        return await self.search_keyword(query)

    async def search_address(self, address: str) -> list[GeocodeCandidate]:
        params: dict[str, Any] = {"query": address}

        async def fetch() -> list[GeocodeCandidate]:
            async def send() -> httpx.Response:
                return await self._client.get(
                    self.ADDRESS_URL,
                    params=params,
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

        return await run_with_geocode_cache(
            self._cache,
            self.PROVIDER,
            self.ADDRESS_URL,
            params,
            fetch,
            force_refresh=self._force_refresh,
        )

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

        async def fetch() -> list[GeocodeCandidate]:
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

        return await run_with_geocode_cache(
            self._cache,
            self.PROVIDER,
            self.KEYWORD_URL,
            dict(params),
            fetch,
            force_refresh=self._force_refresh,
        )


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
