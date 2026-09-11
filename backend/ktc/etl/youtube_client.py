"""공식 YouTube Data API v3 비동기 클라이언트.

`search.list`, `playlistItems.list`, `channels.list`, `videos.list`를 감싸고
호출당 쿼터 비용을 누적한다(`docs/architecture.md` 4.2). 비공식 검색 크롤러는
사용하지 않는다(ADR-11).

`httpx.AsyncClient`를 주입받아 테스트에서 `MockTransport`로 대체할 수 있다.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

BASE_URL = "https://www.googleapis.com/youtube/v3"

# 엔드포인트별 쿼터 비용 (유닛)
QUOTA_COST = {
    "search": 100,
    "playlistItems": 1,
    "channels": 1,
    "playlists": 1,
    "videos": 1,
}


class YouTubeApiError(RuntimeError):
    """YouTube Data API 호출 실패."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason


class YouTubeQuotaExceededError(RuntimeError):
    """설정된 YouTube API 쿼터 예산을 초과하려는 경우."""


class YouTubeClient:
    def __init__(
        self,
        api_key: str,
        http_client: httpx.AsyncClient,
        *,
        quota_budget_units: int | None = None,
        max_retries: int = 3,
    ):
        self._api_key = api_key
        self._client = http_client
        self._quota_budget_units = quota_budget_units
        self._max_retries = max_retries
        self.quota_used = 0

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = {k: v for k, v in params.items() if v is not None}
        cost = QUOTA_COST.get(path, 1)
        self._ensure_quota(cost)

        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._client.get(
                    f"{BASE_URL}/{path}",
                    params=query,
                    headers={"X-goog-api-key": self._api_key},
                )
                if resp.status_code in {429, 500, 502, 503, 504} and attempt < self._max_retries:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                resp.raise_for_status()
                self.quota_used += cost
                try:
                    payload = resp.json()
                except ValueError as exc:
                    raise YouTubeApiError(
                        f"YouTube API {path} 응답 파싱 실패(status={resp.status_code}; "
                        f"attempts={attempt + 1}; error={_clip(str(exc))})",
                        status_code=resp.status_code,
                    ) from exc
                if not isinstance(payload, dict):
                    raise YouTubeApiError(
                        f"YouTube API {path} 응답 형식 오류(status={resp.status_code}; "
                        f"attempts={attempt + 1}; payload_type={type(payload).__name__})",
                        status_code=resp.status_code,
                    )
                return payload
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status_code = exc.response.status_code
                if status_code in {429, 500, 502, 503, 504} and attempt < self._max_retries:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                reason, api_status, detail = _youtube_error_details(exc.response)
                details = [f"status={status_code}", f"attempts={attempt + 1}"]
                if reason:
                    details.append(f"reason={_mask_api_key(reason, self._api_key)}")
                if api_status:
                    details.append(f"api_status={_mask_api_key(api_status, self._api_key)}")
                if detail:
                    details.append(f"message={_mask_api_key(detail, self._api_key)}")
                details.append(
                    f"url={_mask_api_key(str(exc.request.url), self._api_key)}"
                )
                raise YouTubeApiError(
                    f"YouTube API {path} 호출 실패({'; '.join(details)})",
                    status_code=status_code,
                    reason=reason,
                ) from exc
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < self._max_retries:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                raise YouTubeApiError(
                    f"YouTube API {path} 네트워크 오류(attempts={attempt + 1}; "
                    f"error={type(exc).__name__}: "
                    f"{_mask_api_key(_clip(str(exc)), self._api_key)})"
                ) from exc

        raise YouTubeApiError(
            f"YouTube API {path} 호출 실패: "
            f"{_mask_api_key(_clip(str(last_error)), self._api_key)}"
        )

    def _ensure_quota(self, cost: int) -> None:
        if self._quota_budget_units is None:
            return
        if self.quota_used + cost > self._quota_budget_units:
            raise YouTubeQuotaExceededError(
                f"YouTube API 쿼터 예산 초과: used={self.quota_used}, cost={cost}, budget={self._quota_budget_units}"
            )

    async def search_list(
        self,
        *,
        query: str | None = None,
        channel_id: str | None = None,
        max_results: int = 25,
        published_after: str | None = None,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """키워드/채널 기준 영상 검색 (쿼터 100)."""
        return await self._get(
            "search",
            {
                "part": "snippet",
                "type": "video",
                "order": "date",
                "q": query,
                "channelId": channel_id,
                "maxResults": _clamp_max_results(max_results),
                "publishedAfter": published_after,
                "pageToken": page_token,
            },
        )

    async def videos_list(self, video_ids: list[str]) -> dict[str, Any]:
        """영상 상세 메타데이터/통계 조회 (쿼터 1)."""
        items: list[dict[str, Any]] = []
        for chunk in _chunks([video_id for video_id in video_ids if video_id], 50):
            data = await self._get(
                "videos",
                {"part": "snippet,statistics,contentDetails", "id": ",".join(chunk)},
            )
            chunk_items = data.get("items", [])
            if isinstance(chunk_items, list):
                items.extend(item for item in chunk_items if isinstance(item, dict))
        return {"items": items}

    async def channels_list(self, channel_ids: str | list[str]) -> dict[str, Any]:
        """채널 snippet/statistics/contentDetails 조회 (쿼터 1개씩, 최대 50개/요청으로 분할).

        YouTube `channels.list`는 `id`에 최대 50개까지만 허용하고 초과분은 항상 400을
        반환한다(재시도 무의미). 호출부가 중복 제거한 채널 ID를 통째로 넘겨도 안전하도록
        `videos_list`와 동일하게 50개 단위로 나눠 호출하고 결과를 합친다.
        """
        ids = channel_ids.split(",") if isinstance(channel_ids, str) else list(channel_ids)
        ids = [cid for cid in ids if cid]
        items: list[dict[str, Any]] = []
        for chunk in _chunks(ids, 50):
            data = await self._get(
                "channels",
                {"part": "snippet,statistics,contentDetails", "id": ",".join(chunk)},
            )
            chunk_items = data.get("items", [])
            if isinstance(chunk_items, list):
                items.extend(item for item in chunk_items if isinstance(item, dict))
        return {"items": items}

    async def channels_list_by_handle(self, handle: str) -> dict[str, Any]:
        """`@handle`로 채널을 조회한다 (channels.list forHandle, 쿼터 1)."""
        return await self._get(
            "channels",
            {"part": "snippet,contentDetails", "forHandle": handle},
        )

    async def channels_list_by_username(self, username: str) -> dict[str, Any]:
        """legacy username으로 채널을 조회한다 (channels.list forUsername, 쿼터 1)."""
        return await self._get(
            "channels",
            {"part": "snippet,contentDetails", "forUsername": username},
        )

    async def search_channels(
        self, query: str, *, max_results: int = 1
    ) -> dict[str, Any]:
        """채널명으로 채널을 검색한다 (search.list type=channel, 쿼터 100)."""
        return await self._get(
            "search",
            {
                "part": "snippet",
                "type": "channel",
                "q": query,
                "maxResults": _clamp_max_results(max_results),
            },
        )

    async def playlists_list(self, playlist_ids: str | list[str]) -> dict[str, Any]:
        """재생목록 snippet/contentDetails 조회 (쿼터 1개씩, 최대 50개/요청으로 분할).

        `channels_list`와 동일한 이유(`playlists.list`도 `id` 최대 50개)로 분할한다.
        """
        ids = playlist_ids.split(",") if isinstance(playlist_ids, str) else list(playlist_ids)
        ids = [pid for pid in ids if pid]
        items: list[dict[str, Any]] = []
        for chunk in _chunks(ids, 50):
            data = await self._get(
                "playlists",
                {"part": "snippet,contentDetails", "id": ",".join(chunk)},
            )
            chunk_items = data.get("items", [])
            if isinstance(chunk_items, list):
                items.extend(item for item in chunk_items if isinstance(item, dict))
        return {"items": items}

    async def playlist_items_list(
        self, playlist_id: str, *, max_results: int = 25, page_token: str | None = None
    ) -> dict[str, Any]:
        """재생목록 항목 나열 (쿼터 1)."""
        return await self._get(
            "playlistItems",
            {
                "part": "snippet,contentDetails",
                "playlistId": playlist_id,
                "maxResults": _clamp_max_results(max_results),
                "pageToken": page_token,
            },
        )

    async def uploads_playlist_id(self, channel_id: str) -> str | None:
        """채널의 업로드 재생목록 ID를 반환한다."""
        data = await self.channels_list(channel_id)
        items = data.get("items", [])
        if not items:
            return None
        return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def _clamp_max_results(value: int) -> int:
    return max(1, min(int(value), 50))


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _mask_api_key(value: str, api_key: str) -> str:
    if api_key:
        value = value.replace(api_key, "***")
    value = re.sub(
        r"(?i)((?:x-goog-api-key|api[_-]?key|[?&]key)\s*[:=])[^\s&;,]+",
        r"\1***",
        value,
    )
    value = re.sub(
        r"(?i)(authorization\s*:\s*(?:bearer\s+)?)\S+",
        r"\1***",
        value,
    )
    return value


def _clip(value: Any, limit: int = 240) -> str:
    """외부 provider 오류를 UI/로그에 남길 짧은 한 줄로 정리한다."""
    return " ".join(str(value).split())[:limit]


def _youtube_error_details(
    response: httpx.Response,
) -> tuple[str | None, str | None, str | None]:
    """YouTube 표준 오류 응답에서 진단에 필요한 필드만 추출한다."""
    try:
        payload = response.json()
    except ValueError:
        return None, None, None
    if not isinstance(payload, dict):
        return None, None, None

    error = payload.get("error")
    if isinstance(error, str):
        return None, None, _clip(error)
    if not isinstance(error, dict):
        return None, None, None

    reason: str | None = None
    errors = error.get("errors")
    if isinstance(errors, list):
        for item in errors:
            if isinstance(item, dict):
                reason_value = item.get("reason")
                if reason_value is not None:
                    reason = _clip(reason_value)
                    break
    api_status_value = error.get("status")
    api_status = _clip(api_status_value) if api_status_value is not None else None
    detail_value = error.get("message")
    detail = _clip(detail_value) if detail_value is not None else None
    if detail is None and isinstance(errors, list):
        for item in errors:
            if isinstance(item, dict) and item.get("message") is not None:
                detail = _clip(item["message"])
                break
    return reason, api_status, detail
