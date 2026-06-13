"""공식 YouTube Data API v3 비동기 클라이언트.

`search.list`, `playlistItems.list`, `channels.list`, `videos.list`를 감싸고
호출당 쿼터 비용을 누적한다(`docs/architecture.md` 4.2). 비공식 검색 크롤러는
사용하지 않는다(ADR-11).

`httpx.AsyncClient`를 주입받아 테스트에서 `MockTransport`로 대체할 수 있다.
"""

from __future__ import annotations

import asyncio
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
                return resp.json()
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status_code = exc.response.status_code
                if status_code in {429, 500, 502, 503, 504} and attempt < self._max_retries:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                raise YouTubeApiError(
                    f"YouTube API {path} 호출 실패(status={status_code}, url={_mask_api_key(str(exc.request.url), self._api_key)})"
                ) from exc
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < self._max_retries:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                raise YouTubeApiError(f"YouTube API {path} 네트워크 오류: {exc}") from exc

        raise YouTubeApiError(f"YouTube API {path} 호출 실패: {last_error}")

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
        """채널 snippet/statistics/contentDetails 조회 (쿼터 1)."""
        ids = ",".join(channel_ids) if isinstance(channel_ids, list) else channel_ids
        return await self._get(
            "channels",
            {"part": "snippet,statistics,contentDetails", "id": ids},
        )

    async def playlists_list(self, playlist_ids: str | list[str]) -> dict[str, Any]:
        """재생목록 snippet/contentDetails 조회 (쿼터 1)."""
        ids = ",".join(playlist_ids) if isinstance(playlist_ids, list) else playlist_ids
        return await self._get(
            "playlists",
            {"part": "snippet,contentDetails", "id": ids},
        )

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
    return value
