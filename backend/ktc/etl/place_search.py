"""검수(review) 페이지용 멀티 provider 장소 검색.

Google Places(New)/Kakao(키워드)/Naver(local)에서 같은 질의로 장소 후보를 모으고,
Gemini가 후보 중 최적값을 골라 의견을 낸다. 각 provider는 독립적으로 호출하므로
한 provider가 실패해도 다른 결과에 영향을 주지 않는다(호출부에서 격리).

HTTP 호출은 `httpx.AsyncClient`를 주입받아 테스트에서 `MockTransport`로 대체한다.
Gemini 의견은 비동기 게이트웨이(`llm_client.complete_json`)를 경유한다 — thread 격리·
rate limiter 예약은 게이트웨이가 처리한다(T-161).
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from ktc.core.config import get_settings
from ktc.etl import llm_client

# Naver local 검색 title의 <b>...</b> 강조 태그 제거용.
_BOLD_TAG_RE = re.compile(r"</?b>")


class PlaceSearchProviderDisabled(RuntimeError):
    """Phase -1 provider 정책 kill switch로 비활성화된 provider 호출 (T-158)."""

GOOGLE_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
NAVER_LOCAL_URL = "https://openapi.naver.com/v1/search/local.json"

GEMINI_OPINION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "best_name": {"type": "string"},
        "latitude": {"type": "number"},
        "longitude": {"type": "number"},
        "category": {"type": "string"},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["best_name", "latitude", "longitude", "confidence", "reason"],
}


def _hit(
    provider: str,
    name: str | None,
    *,
    native_id: str | None = None,
    address: str | None = None,
    road_address: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    """provider별 응답을 공통 후보 dict로 정규화한다."""
    storage_allowed = provider != "google"
    return {
        "provider": provider,
        "native_id": str(native_id) if native_id is not None else None,
        "name": name or "",
        "address": address,
        "road_address": road_address,
        "latitude": latitude,
        "longitude": longitude,
        "category": category,
        # T-158(provider 정책) 결정 전에는 Google Places 결과를 영구 저장하거나
        # VWorld 지도 선택값으로 승격하지 않는다. 프런트 UX용 capability이며
        # 최종 강제는 place_service.resolve_candidate가 담당한다.
        "storage_allowed": storage_allowed,
        "storage_block_reason": (
            None
            if storage_allowed
            else "provider 정책 결정 전에는 Google Places 결과를 저장할 수 없습니다."
        ),
    }


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def search_google_places(
    client: httpx.AsyncClient, *, query: str, api_key: str, max_results: int = 5
) -> list[dict[str, Any]]:
    """Google Places API(New) text search 결과를 후보로 변환한다.

    `GOOGLE_PLACE_SEARCH_ENABLED=false`(Phase -1 정책 게이트)면 호출 없이
    `PlaceSearchProviderDisabled`를 던진다. `/place-search` 호출부는 이 예외를
    빈 목록 + `errors.google`의 disabled 사유로 격리한다.
    """
    if not get_settings().GOOGLE_PLACE_SEARCH_ENABLED:
        raise PlaceSearchProviderDisabled(
            "disabled: GOOGLE_PLACE_SEARCH_ENABLED=false — "
            "Phase -1 provider 정책 게이트(docs/provider-policy.md)"
        )
    resp = await client.post(
        GOOGLE_SEARCH_URL,
        headers={
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": (
                "places.id,places.displayName,places.formattedAddress,"
                "places.location,places.primaryTypeDisplayName"
            ),
            "Content-Type": "application/json",
        },
        json={
            "textQuery": query,
            "languageCode": "ko",
            "maxResultCount": max_results,
        },
    )
    if resp.is_error:
        # raise_for_status는 응답 본문을 버려 일반 '403 Forbidden'만 남긴다. Google이 돌려준
        # error.status/reason(SERVICE_DISABLED, API_KEY_HTTP_REFERRER_BLOCKED, BILLING_DISABLED 등)을
        # 그대로 노출해야 403 원인(미활성 API·키 제한·결제 미설정 등)을 진단할 수 있으므로
        # 본문 일부를 예외 메시지에 싣는다(이 메시지는 /place-search의 errors.google로 노출됨).
        detail = " ".join(resp.text.split())[:500]
        raise httpx.HTTPStatusError(
            f"Google Places {resp.status_code}: {detail}",
            request=resp.request,
            response=resp,
        )
    out: list[dict[str, Any]] = []
    for place in resp.json().get("places", []):
        if not isinstance(place, dict):
            continue
        location = place.get("location") or {}
        out.append(
            _hit(
                "google",
                (place.get("displayName") or {}).get("text"),
                native_id=place.get("id"),
                address=place.get("formattedAddress"),
                latitude=_to_float(location.get("latitude")),
                longitude=_to_float(location.get("longitude")),
                category=(place.get("primaryTypeDisplayName") or {}).get("text"),
            )
        )
    return out


async def search_kakao(
    client: httpx.AsyncClient, *, query: str, api_key: str, max_results: int = 5
) -> list[dict[str, Any]]:
    """Kakao Local 키워드 장소 검색 결과를 후보로 변환한다(x=경도, y=위도)."""
    resp = await client.get(
        KAKAO_KEYWORD_URL,
        params={"query": query, "size": max_results},
        headers={"Authorization": f"KakaoAK {api_key}"},
    )
    resp.raise_for_status()
    out: list[dict[str, Any]] = []
    for doc in resp.json().get("documents", []):
        if not isinstance(doc, dict):
            continue
        out.append(
            _hit(
                "kakao",
                doc.get("place_name"),
                native_id=doc.get("id"),
                address=doc.get("address_name"),
                road_address=doc.get("road_address_name") or None,
                latitude=_to_float(doc.get("y")),
                longitude=_to_float(doc.get("x")),
                category=doc.get("category_name") or doc.get("category_group_name"),
            )
        )
    return out


async def search_naver_local(
    client: httpx.AsyncClient,
    *,
    query: str,
    client_id: str,
    client_secret: str,
    max_results: int = 5,
) -> list[dict[str, Any]]:
    """Naver Developers 지역 검색 결과를 후보로 변환한다.

    title의 `<b>` 강조 태그를 제거하고 mapx/mapy(WGS84×10⁷)를 위경도로 변환한다.
    """
    resp = await client.get(
        NAVER_LOCAL_URL,
        params={"query": query, "display": max_results},
        headers={
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret,
        },
    )
    resp.raise_for_status()
    out: list[dict[str, Any]] = []
    for item in resp.json().get("items", []):
        if not isinstance(item, dict):
            continue
        title = _BOLD_TAG_RE.sub("", item.get("title") or "") or None
        mapx = _to_float(item.get("mapx"))
        mapy = _to_float(item.get("mapy"))
        out.append(
            _hit(
                "naver",
                title,
                # NAVER Developers Local Search는 안정적인 장소 ID를 제공하지 않는다.
                # link/map 좌표를 ID로 가장하지 않고 nullable 계약을 유지한다.
                native_id=None,
                address=item.get("address") or None,
                road_address=item.get("roadAddress") or None,
                latitude=mapy / 1e7 if mapy is not None else None,
                longitude=mapx / 1e7 if mapx is not None else None,
                category=item.get("category") or None,
            )
        )
    return out


def _build_opinion_prompt(query: str, hits: list[dict[str, Any]]) -> str:
    lines = [
        f"- [{hit.get('provider')}] {hit.get('name')} | "
        f"{hit.get('road_address') or hit.get('address') or '주소 없음'} | "
        f"{hit.get('latitude')},{hit.get('longitude')} | {hit.get('category') or '-'}"
        for hit in hits
    ]
    body = "\n".join(lines)
    return (
        f'사용자가 찾는 장소: "{query}"\n\n'
        "아래는 여러 검색 제공자(Google/Kakao/Naver)의 후보 목록이다:\n"
        f"{body}\n\n"
        "이 중 사용자가 찾는 장소에 가장 부합하는 하나를 고르거나 종합해, 표준 이름·위도·경도·"
        "카테고리와 0~1 사이 신뢰도(confidence), 한국어 근거(reason)를 JSON으로 답하라."
    )


async def gemini_place_opinion(
    runtime: llm_client.LlmRuntime,
    *,
    query: str,
    hits: list[dict[str, Any]],
    timeout_seconds: float = 10.0,
    max_attempts: int = 1,
    raise_on_error: bool = False,
) -> dict[str, Any] | None:
    """후보 목록을 받아 Gemini가 최적 장소를 고른 의견을 반환한다(게이트웨이 경유).

    검수 검색은 대화형이라 기본을 **단발 호출(max_attempts=1)·짧은 타임아웃·리미터
    무대기(quota_max_wait=0)**로 둔다. 느린 사람-유사 재시도(15초~)나 분 윈도우 대기를
    타지 않으므로 응답이 빠르고, 실패해도 검색 흐름을 막지 않는다. 윈도우 혼잡은
    `GeminiQuotaBusy`로 즉시 반환된다(호출부가 정확한 안내 메시지로 매핑).
    LLM/파싱 실패는 None으로 흡수한다.
    """
    if not hits:
        return None
    prompt = _build_opinion_prompt(query, hits)
    try:
        raw = await llm_client.complete_json(
            runtime,
            prompt,
            response_schema=GEMINI_OPINION_SCHEMA,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            # 대화형: 분 윈도우가 꽉 차 있으면 대기하지 않고 즉시 GeminiQuotaBusy.
            quota_max_wait=0,
        )
    except (
        llm_client.LlmRequestError,
        llm_client.GeminiQuotaExceeded,
        llm_client.GeminiQuotaBusy,
    ):
        if raise_on_error:
            raise
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None
