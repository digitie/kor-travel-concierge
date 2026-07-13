"""provider별 지오코딩 캐시(T-170, S7) 계약 테스트.

검증 계약:
- provider-gated allowlist: Kakao만 cacheable, VWorld/Naver(NCP·Local)/미등록은 비캐시.
- 캐시 miss→저장, hit→외부 호출 0(같은 결과·동일 evidence 형식).
- error(429/5xx/타임아웃/4xx)는 success로 캐시하지 않는다.
- positive/negative TTL 분리와 lazy 만료(조회 시 무시).
- canonical key 구성(provider·endpoint·param·NORMALIZATION_VERSION)과 query 정규화·버스트.
- allowed_fields 화이트리스트 저장.
- force_refresh 훅(조회 스킵·재호출·갱신).

외부 provider는 httpx.MockTransport로 모사하며 실제 호출하지 않는다. 캐시 저장소는
disposable PostgreSQL(`KTC_TEST_PG_DSN`) 위 실제 `geocode_cache` 테이블을 사용한다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select

from ktc.etl import geocoding
from ktc.etl.geocoding import (
    GeocodeCandidate,
    GeocodeCacheStore,
    GeocodeResponseClass,
    KakaoGeocoder,
    cache_policy_for,
    classify_geocode_exception,
    classify_geocode_success,
    geocode_cache_key,
    is_provider_cacheable,
)
from ktc.models import GeocodeCache

_KAKAO_ADDR = {
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

_EMPTY = {"documents": [], "meta": {"total_count": 0}}


class _Clock:
    """테스트에서 시간을 결정적으로 전진시키는 clock."""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 7, 13, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now = self.now + delta


def _counting_kakao_transport(payload_by_path: dict[str, object], counter: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        counter.append(request.url.path)
        for suffix, payload in payload_by_path.items():
            if request.url.path.endswith(suffix):
                if isinstance(payload, int):
                    return httpx.Response(payload)
                return httpx.Response(200, json=payload)
        return httpx.Response(200, json=_EMPTY)

    return httpx.MockTransport(handler)


@pytest_asyncio.fixture
async def store(session_factory) -> GeocodeCacheStore:
    return GeocodeCacheStore(session_factory)


async def _row_count(session_factory) -> int:
    async with session_factory() as session:
        return (
            await session.execute(select(func.count()).select_from(GeocodeCache))
        ).scalar_one()


# --- provider-gated allowlist (T-170 핵심 정확성) ---


def test_only_kakao_is_cacheable():
    assert is_provider_cacheable("kakao") is True
    # VWorld·Naver(NCP)·Naver Local Search는 정책상 캐시 금지.
    assert is_provider_cacheable("vworld") is False
    assert is_provider_cacheable("naver") is False
    assert is_provider_cacheable("naver_local") is False
    # google_places는 이번 범위 밖이지만 명시적으로 비캐시.
    assert is_provider_cacheable("google_places") is False
    # 미등록 provider는 deny-by-default.
    assert is_provider_cacheable("unknown") is False


def test_kakao_policy_ttls_conservative():
    policy = cache_policy_for("kakao")
    assert policy.cacheable is True
    # "최신 유지" 의무 → positive TTL은 30일 이하로 보수적.
    assert 0 < policy.positive_ttl_days <= 30
    assert policy.negative_ttl_days <= policy.positive_ttl_days


async def test_non_cacheable_provider_lookup_and_store_are_noop(store, session_factory):
    # cacheable=False provider는 조회·저장 모두 no-op이며 테이블에 아무 것도 쓰지 않는다.
    params = {"query": "판교로 242"}
    assert await store.lookup("vworld", "https://vworld/geocode", params) is None
    await store.store(
        "vworld",
        "https://vworld/geocode",
        params,
        GeocodeResponseClass.SUCCESS_NONEMPTY,
        [GeocodeCandidate(latitude=37.4, longitude=127.1, source="vworld")],
    )
    assert await store.lookup("naver", "https://naver/geocode", params) is None
    await store.store(
        "naver",
        "https://naver/geocode",
        params,
        GeocodeResponseClass.SUCCESS_NONEMPTY,
        [GeocodeCandidate(latitude=37.4, longitude=127.1, source="naver")],
    )
    assert await _row_count(session_factory) == 0


# --- miss → store → hit ---


async def test_kakao_cache_miss_then_hit_no_second_call(store, session_factory):
    calls: list[str] = []
    transport = _counting_kakao_transport({"address.json": _KAKAO_ADDR}, calls)
    async with httpx.AsyncClient(transport=transport) as http:
        geo = KakaoGeocoder("k", http, cache=store, base_delay=0.0)
        first = await geo.geocode("부산 해운대구 우동")
        second = await geo.geocode("부산 해운대구 우동")

    # 두 번째 호출은 캐시 히트라 외부 호출이 늘지 않는다(주소검색 1회만).
    assert calls == ["/v2/local/search/address.json"]
    assert len(first) == 1 and len(second) == 1
    # 결과가 동일하고 evidence 직렬화 형식도 동일하다(소비처·export 계약 불변).
    assert geocoding._candidate_to_evidence(
        first[0]
    ) == geocoding._candidate_to_evidence(second[0])
    assert second[0].source == "kakao"
    assert second[0].road_address == "부산 해운대구 해운대해변로 264"

    # DB 행이 정확히 1건, provider·response_class가 기대값.
    async with session_factory() as session:
        rows = (await session.execute(select(GeocodeCache))).scalars().all()
    assert len(rows) == 1
    assert rows[0].provider == "kakao"
    assert rows[0].response_class == "success_nonempty"


async def test_cache_hit_preserves_result_kind_for_keyword(store):
    keyword_payload = {
        "documents": [
            {
                "place_name": "카카오프렌즈 코엑스점",
                "category_name": "생활 > 문구",
                "address_name": "서울 강남구 삼성동 159",
                "road_address_name": "서울 강남구 영동대로 513",
                "x": "127.059",
                "y": "37.512",
            }
        ],
        "meta": {"total_count": 1},
    }
    calls: list[str] = []
    transport = _counting_kakao_transport(
        {"address.json": _EMPTY, "keyword.json": keyword_payload}, calls
    )
    async with httpx.AsyncClient(transport=transport) as http:
        geo = KakaoGeocoder("k", http, cache=store, base_delay=0.0)
        first = await geo.geocode("카카오프렌즈 코엑스점")
        second = await geo.geocode("카카오프렌즈 코엑스점")

    # 첫 호출: address(빈)+keyword 2회. 둘 다 캐시되어 두 번째는 외부 호출 0.
    assert calls == [
        "/v2/local/search/address.json",
        "/v2/local/search/keyword.json",
    ]
    assert first[0].result_kind == "poi"
    assert second[0].result_kind == "poi"
    assert second[0].source == "kakao_keyword"
    assert second[0].category == "생활 > 문구"


# --- error는 캐시하지 않는다 ---


def test_classify_exception_transient_vs_permanent():
    def status_error(code: int) -> httpx.HTTPStatusError:
        request = httpx.Request("GET", "https://dapi.kakao.com/x")
        response = httpx.Response(code, request=request)
        return httpx.HTTPStatusError("boom", request=request, response=response)

    assert classify_geocode_exception(status_error(429)) == (
        GeocodeResponseClass.TRANSIENT_ERROR
    )
    assert classify_geocode_exception(status_error(503)) == (
        GeocodeResponseClass.TRANSIENT_ERROR
    )
    assert classify_geocode_exception(status_error(500)) == (
        GeocodeResponseClass.TRANSIENT_ERROR
    )
    # 인증/무효 4xx는 permanent.
    assert classify_geocode_exception(status_error(401)) == (
        GeocodeResponseClass.PERMANENT_ERROR
    )
    assert classify_geocode_exception(status_error(403)) == (
        GeocodeResponseClass.PERMANENT_ERROR
    )
    assert classify_geocode_exception(status_error(400)) == (
        GeocodeResponseClass.PERMANENT_ERROR
    )
    # 타임아웃·네트워크 오류는 transient.
    assert classify_geocode_exception(httpx.ReadTimeout("t")) == (
        GeocodeResponseClass.TRANSIENT_ERROR
    )
    assert classify_geocode_exception(httpx.ConnectError("c")) == (
        GeocodeResponseClass.TRANSIENT_ERROR
    )


def test_classify_success_by_count():
    assert classify_geocode_success([]) == GeocodeResponseClass.SUCCESS_EMPTY
    assert classify_geocode_success(
        [GeocodeCandidate(latitude=1.0, longitude=2.0)]
    ) == GeocodeResponseClass.SUCCESS_NONEMPTY


@pytest.mark.parametrize("status", [429, 500, 503, 401, 400])
async def test_provider_error_is_not_cached(store, session_factory, status):
    calls: list[str] = []
    transport = _counting_kakao_transport({"address.json": status}, calls)
    async with httpx.AsyncClient(transport=transport) as http:
        geo = KakaoGeocoder("k", http, cache=store, base_delay=0.0, max_retries=0)
        with pytest.raises(httpx.HTTPStatusError):
            await geo.search_address("부산 해운대")

    # 에러는 저장하지 않으므로 테이블은 비어 있고, 다음 호출도 다시 provider로 간다.
    assert await _row_count(session_factory) == 0


async def test_store_rejects_error_classes_directly(store, session_factory):
    params = {"query": "x"}
    for cls in (
        GeocodeResponseClass.TRANSIENT_ERROR,
        GeocodeResponseClass.PERMANENT_ERROR,
    ):
        await store.store(
            "kakao",
            KakaoGeocoder.ADDRESS_URL,
            params,
            cls,
            [GeocodeCandidate(latitude=1.0, longitude=2.0, source="kakao")],
        )
    assert await _row_count(session_factory) == 0


# --- TTL 분리와 lazy 만료 ---


async def test_empty_success_uses_negative_ttl(session_factory):
    clock = _Clock()
    # positive 30일, negative 1일로 분리.
    store = GeocodeCacheStore(
        session_factory, ttl_overrides={"kakao": (30.0, 1.0)}, clock=clock
    )
    calls: list[str] = []
    # 주소·키워드 모두 빈 결과 → success_empty만 캐시.
    transport = _counting_kakao_transport(
        {"address.json": _EMPTY, "keyword.json": _EMPTY}, calls
    )
    async with httpx.AsyncClient(transport=transport) as http:
        geo = KakaoGeocoder("k", http, cache=store, base_delay=0.0)
        await geo.geocode("존재하지 않는 장소명")
        calls_after_first = len(calls)
        # negative TTL(1일) 안: 캐시 히트 → 외부 호출 없음.
        clock.advance(timedelta(hours=12))
        await geo.geocode("존재하지 않는 장소명")
        assert len(calls) == calls_after_first
        # negative TTL 초과: lazy 만료 → 다시 provider 호출.
        clock.advance(timedelta(days=2))
        await geo.geocode("존재하지 않는 장소명")
        assert len(calls) > calls_after_first

    async with session_factory() as session:
        classes = {
            row.response_class
            for row in (await session.execute(select(GeocodeCache))).scalars().all()
        }
    assert classes == {"success_empty"}


async def test_positive_ttl_expiry_refetches(session_factory):
    clock = _Clock()
    store = GeocodeCacheStore(
        session_factory, ttl_overrides={"kakao": (14.0, 1.0)}, clock=clock
    )
    calls: list[str] = []
    transport = _counting_kakao_transport({"address.json": _KAKAO_ADDR}, calls)
    async with httpx.AsyncClient(transport=transport) as http:
        geo = KakaoGeocoder("k", http, cache=store, base_delay=0.0)
        await geo.search_address("부산 해운대구 우동")
        assert len(calls) == 1
        # positive TTL 안: 히트.
        clock.advance(timedelta(days=10))
        await geo.search_address("부산 해운대구 우동")
        assert len(calls) == 1
        # positive TTL 초과: 재호출.
        clock.advance(timedelta(days=5))
        await geo.search_address("부산 해운대구 우동")
        assert len(calls) == 2


# --- canonical key / 정규화 / NORMALIZATION_VERSION ---


def test_key_includes_provider_endpoint_and_params():
    base = geocode_cache_key("kakao", "e1", {"query": "서울"})
    assert base != geocode_cache_key("naver", "e1", {"query": "서울"})
    assert base != geocode_cache_key("kakao", "e2", {"query": "서울"})
    assert base != geocode_cache_key("kakao", "e1", {"query": "부산"})
    assert base != geocode_cache_key("kakao", "e1", {"query": "서울", "page": 2})
    # 같은 입력은 결정적으로 같은 key.
    assert base == geocode_cache_key("kakao", "e1", {"query": "서울"})


def test_query_whitespace_is_normalized():
    a = geocode_cache_key("kakao", "e1", {"query": "  부산   해운대  "})
    b = geocode_cache_key("kakao", "e1", {"query": "부산 해운대"})
    assert a == b


def test_normalization_version_busts_key(monkeypatch):
    before = geocode_cache_key("kakao", "e1", {"query": "서울"})
    monkeypatch.setattr(geocoding, "NORMALIZATION_VERSION", 999)
    after = geocode_cache_key("kakao", "e1", {"query": "서울"})
    assert before != after


# --- allowed_fields 화이트리스트 ---


async def test_stored_payload_only_contains_allowed_fields(store, session_factory):
    calls: list[str] = []
    transport = _counting_kakao_transport({"address.json": _KAKAO_ADDR}, calls)
    async with httpx.AsyncClient(transport=transport) as http:
        geo = KakaoGeocoder("k", http, cache=store, base_delay=0.0)
        await geo.search_address("부산 해운대구 우동")

    allowed = set(cache_policy_for("kakao").allowed_fields)
    async with session_factory() as session:
        row = (await session.execute(select(GeocodeCache))).scalars().one()
    for item in row.results_json:
        assert set(item).issubset(allowed)
    # 좌표 등 핵심 필드는 실제로 저장돼 복원 가능해야 한다.
    assert "latitude" in row.results_json[0]
    assert "longitude" in row.results_json[0]


def test_candidate_serialization_respects_restricted_allowed_fields():
    candidate = GeocodeCandidate(
        latitude=1.0, longitude=2.0, place_name="p", category="c", source="kakao"
    )
    restricted = geocoding._candidate_to_cache_dict(
        candidate, ("latitude", "longitude")
    )
    assert set(restricted) == {"latitude", "longitude"}


# --- force_refresh 훅 ---


async def test_force_refresh_skips_lookup_and_updates(session_factory):
    store = GeocodeCacheStore(session_factory)
    calls: list[str] = []
    transport = _counting_kakao_transport({"address.json": _KAKAO_ADDR}, calls)
    async with httpx.AsyncClient(transport=transport) as http:
        cached_geo = KakaoGeocoder("k", http, cache=store, base_delay=0.0)
        await cached_geo.search_address("부산 해운대구 우동")
        assert len(calls) == 1
        # 일반 호출은 히트(외부 호출 없음).
        await cached_geo.search_address("부산 해운대구 우동")
        assert len(calls) == 1
        # force_refresh는 조회를 건너뛰고 재호출한다.
        refreshing_geo = KakaoGeocoder(
            "k", http, cache=store, force_refresh=True, base_delay=0.0
        )
        await refreshing_geo.search_address("부산 해운대구 우동")
        assert len(calls) == 2

    # 갱신 후에도 캐시 행은 여전히 1건(같은 key 덮어쓰기).
    assert await _row_count(session_factory) == 1


# --- best-effort 캐시: 캐시 계층 예외가 지오코딩 결과를 바꾸지 않는다 ---


class _RaisingCache:
    """lookup/store에서 선택적으로 예외를 던지는 최소 캐시 스텁(cacheable=True)."""

    def __init__(
        self,
        *,
        lookup_exc: Exception | None = None,
        store_exc: Exception | None = None,
    ) -> None:
        self.lookup_exc = lookup_exc
        self.store_exc = store_exc
        self.lookup_calls = 0
        self.store_calls = 0

    def is_cacheable(self, provider: str) -> bool:
        return True

    async def lookup(self, provider, endpoint, params):
        self.lookup_calls += 1
        if self.lookup_exc is not None:
            raise self.lookup_exc
        return None

    async def store(self, provider, endpoint, params, response_class, candidates):
        self.store_calls += 1
        if self.store_exc is not None:
            raise self.store_exc


async def test_store_failure_does_not_discard_fetched_candidates(caplog):
    cache = _RaisingCache(store_exc=RuntimeError("db pool timeout"))
    fetched = [GeocodeCandidate(latitude=35.1, longitude=129.1, source="kakao")]

    async def fetch() -> list[GeocodeCandidate]:
        return fetched

    with caplog.at_level(logging.WARNING, logger="ktc.etl.geocoding"):
        result = await geocoding.run_with_geocode_cache(
            cache, "kakao", "endpoint", {"query": "x"}, fetch
        )

    # store가 예외를 던져도 fetch된 후보가 그대로 반환되고 예외는 전파되지 않는다.
    assert result == fetched
    assert cache.store_calls == 1
    assert "저장 실패" in caplog.text


async def test_lookup_failure_falls_back_to_fetch(caplog):
    cache = _RaisingCache(lookup_exc=RuntimeError("asyncpg hiccup"))
    fetched = [GeocodeCandidate(latitude=35.1, longitude=129.1, source="kakao")]
    calls = {"n": 0}

    async def fetch() -> list[GeocodeCandidate]:
        calls["n"] += 1
        return fetched

    with caplog.at_level(logging.WARNING, logger="ktc.etl.geocoding"):
        result = await geocoding.run_with_geocode_cache(
            cache, "kakao", "endpoint", {"query": "x"}, fetch
        )

    # lookup 예외는 miss로 취급 → fetch 폴백. 강등 없이 후보 반환.
    assert result == fetched
    assert calls["n"] == 1
    assert cache.lookup_calls == 1
    assert "조회 실패" in caplog.text


# --- 캐시 비활성 플래그 ---


async def test_disabled_store_bypasses_cache(session_factory):
    store = GeocodeCacheStore(session_factory, enabled=False)
    calls: list[str] = []
    transport = _counting_kakao_transport({"address.json": _KAKAO_ADDR}, calls)
    async with httpx.AsyncClient(transport=transport) as http:
        geo = KakaoGeocoder("k", http, cache=store, base_delay=0.0)
        await geo.search_address("부산 해운대구 우동")
        await geo.search_address("부산 해운대구 우동")
    # 비활성이면 매번 provider로 가고 저장하지 않는다.
    assert len(calls) == 2
    assert await _row_count(session_factory) == 0
