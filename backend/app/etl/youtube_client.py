"""공식 YouTube Data API v3 비동기 클라이언트.

`search.list`, `playlistItems.list`, `channels.list`, `videos.list`를 감싸고
호출당 쿼터 비용을 누적한다(`docs/architecture.md` 4.2). 비공식 검색 크롤러는
사용하지 않는다(ADR-11).

`httpx.AsyncClient`를 주입받아 테스트에서 `MockTransport`로 대체할 수 있다.
"""

from __future__ import annotations

from typing import Any

import httpx

BASE_URL = "https://www.googleapis.com/youtube/v3"

# 엔드포인트별 쿼터 비용 (유닛)
QUOTA_COST = {
    "search": 100,
    "playlistItems": 1,
    "channels": 1,
    "videos": 1,
}


class YouTubeClient:
    def __init__(self, api_key: str, http_client: httpx.AsyncClient):
        self._api_key = api_key
        self._client = http_client
        self.quota_used = 0

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = {k: v for k, v in params.items() if v is not None}
        query["key"] = self._api_key
        resp = await self._client.get(f"{BASE_URL}/{path}", params=query)
        resp.raise_for_status()
        self.quota_used += QUOTA_COST.get(path, 1)
        return resp.json()

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
                "maxResults": max_results,
                "publishedAfter": published_after,
                "pageToken": page_token,
            },
        )

    async def videos_list(self, video_ids: list[str]) -> dict[str, Any]:
        """영상 상세 메타데이터/통계 조회 (쿼터 1)."""
        return await self._get(
            "videos",
            {"part": "snippet,statistics", "id": ",".join(video_ids)},
        )

    async def channels_list(self, channel_id: str) -> dict[str, Any]:
        """채널 contentDetails 조회 (쿼터 1)."""
        return await self._get(
            "channels", {"part": "contentDetails", "id": channel_id}
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
                "maxResults": max_results,
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
