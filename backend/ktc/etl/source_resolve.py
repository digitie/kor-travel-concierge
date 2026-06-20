"""채널/재생목록 입력 정규화.

수집 폼이 채널 ID(`UC...`)뿐 아니라 채널명·`@handle`·채널 URL을, 재생목록은
`PL...` ID뿐 아니라 재생목록/시청 URL을 받을 수 있도록 입력을 표준 ID로 변환한다.

순수 파서(`parse_channel_input`, `parse_playlist_id`)는 외부 API 호출이 없고,
`resolve_channel_id`만 YouTube Data API(`forHandle`/`forUsername`/`search`)를 사용한다.
"""

from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

ChannelInputKind = Literal["id", "handle", "username", "custom", "search"]

# UC + 22자 base64url. 채널 ID 형식.
_CHANNEL_ID_RE = re.compile(r"^UC[0-9A-Za-z_-]{22}$")
# 재생목록 ID 접두사(사용자/업로드/즐겨찾기/기타). RD/믹스 등 비안정 ID는 제외한다.
_PLAYLIST_ID_RE = re.compile(r"^(?:PL|UU|FL|OL|LL)[0-9A-Za-z_-]{10,}$")


def _looks_like_url(raw: str) -> bool:
    return raw.startswith(("http://", "https://")) or "youtube.com" in raw or "youtu.be" in raw


def _with_scheme(raw: str) -> str:
    return raw if raw.startswith(("http://", "https://")) else f"https://{raw}"


def parse_channel_input(raw: str) -> tuple[ChannelInputKind, str]:
    """채널 입력을 (종류, 값)으로 분류한다.

    - `id`: `UC...` 채널 ID (URL `/channel/UC...` 포함)
    - `handle`: `@handle` (URL `/@handle` 포함, 값은 `@` 포함)
    - `username`: legacy username (URL `/user/Name`)
    - `custom`: custom URL 이름 (`/c/Name` 또는 `youtube.com/Name`)
    - `search`: 위에 해당하지 않는 일반 채널명(검색 대상)
    """
    value = raw.strip()
    if not value:
        return "search", ""

    if _looks_like_url(value):
        parsed = urlparse(_with_scheme(value))
        segments = [seg for seg in parsed.path.split("/") if seg]
        if segments:
            first = segments[0]
            if first == "channel" and len(segments) >= 2:
                return "id", segments[1]
            if first == "user" and len(segments) >= 2:
                return "username", segments[1]
            if first == "c" and len(segments) >= 2:
                return "custom", segments[1]
            if first.startswith("@"):
                return "handle", first
            # youtube.com/CustomName (legacy custom URL)
            return "custom", first
        return "search", value

    if value.startswith("@"):
        return "handle", value
    if _CHANNEL_ID_RE.match(value):
        return "id", value
    return "search", value


def parse_playlist_id(raw: str) -> str | None:
    """재생목록 입력에서 재생목록 ID(`PL...` 등)를 추출한다.

    재생목록/시청 URL의 `list=` 쿼리, `youtu.be/..?list=..`, 또는 bare ID를 처리한다.
    """
    value = raw.strip()
    if not value:
        return None

    if _looks_like_url(value) or "list=" in value:
        parsed = urlparse(_with_scheme(value))
        listed = parse_qs(parsed.query).get("list")
        if listed and listed[0]:
            return listed[0]
        # /playlist 경로 없이 path 마지막 세그먼트가 ID인 경우는 흔치 않아 무시.
        return None

    if _PLAYLIST_ID_RE.match(value):
        return value
    return None


def _first_channel_id_from_channels(data: dict[str, Any]) -> str | None:
    items = data.get("items")
    if isinstance(items, list) and items:
        first = items[0]
        if isinstance(first, dict) and isinstance(first.get("id"), str):
            return first["id"]
    return None


def _first_channel_id_from_search(data: dict[str, Any]) -> str | None:
    items = data.get("items")
    if isinstance(items, list) and items:
        first = items[0]
        if isinstance(first, dict):
            ident = first.get("id")
            if isinstance(ident, dict) and isinstance(ident.get("channelId"), str):
                return ident["channelId"]
            snippet = first.get("snippet")
            if isinstance(snippet, dict) and isinstance(snippet.get("channelId"), str):
                return snippet["channelId"]
    return None


async def resolve_channel_id(client: Any, raw: str) -> str | None:
    """채널 입력을 표준 `UC...` 채널 ID로 해석한다.

    `client`는 `YouTubeClient`(또는 동등한 인터페이스)이며, ID/URL-ID는 API 없이
    그대로 반환한다. handle/username/custom/검색만 API를 호출한다.
    """
    kind, value = parse_channel_input(raw)
    if not value:
        return None
    if kind == "id":
        return value
    if kind == "handle":
        return _first_channel_id_from_channels(
            await client.channels_list_by_handle(value)
        )
    if kind == "username":
        return _first_channel_id_from_channels(
            await client.channels_list_by_username(value)
        )
    if kind == "custom":
        # custom URL 이름은 handle로 먼저 시도하고, 실패하면 검색으로 보완한다.
        resolved = _first_channel_id_from_channels(
            await client.channels_list_by_handle(value)
        )
        if resolved:
            return resolved
        return _first_channel_id_from_search(await client.search_channels(value))
    # kind == "search"
    return _first_channel_id_from_search(await client.search_channels(value))
