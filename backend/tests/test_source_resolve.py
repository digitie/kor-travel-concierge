"""채널/재생목록 입력 정규화 테스트.

순수 파서는 DB/네트워크 없이 동작하고, `resolve_channel_id`는 주입한 fake client로
forHandle/forUsername/search 분기를 검증한다.
"""

from __future__ import annotations

from ktc.etl import source_resolve

_UC = "UC1234567890123456789012"  # UC + 22자


def test_parse_channel_input_id_forms():
    assert source_resolve.parse_channel_input(_UC) == ("id", _UC)
    assert source_resolve.parse_channel_input(
        f"https://www.youtube.com/channel/{_UC}"
    ) == ("id", _UC)


def test_parse_channel_input_handle_forms():
    assert source_resolve.parse_channel_input("@빵이네tv") == ("handle", "@빵이네tv")
    assert source_resolve.parse_channel_input(
        "https://youtube.com/@빵이네tv"
    ) == ("handle", "@빵이네tv")
    # 브라우저 주소창에서 복사한 percent-encoded handle URL도 디코드한다.
    assert source_resolve.parse_channel_input(
        "https://www.youtube.com/@%EB%B9%B5%EC%9D%B4%EB%84%A4tv"
    ) == ("handle", "@빵이네tv")


def test_parse_channel_input_username_and_custom():
    assert source_resolve.parse_channel_input(
        "https://www.youtube.com/user/SomeUser"
    ) == ("username", "SomeUser")
    assert source_resolve.parse_channel_input(
        "https://www.youtube.com/c/SomeCustom"
    ) == ("custom", "SomeCustom")
    assert source_resolve.parse_channel_input(
        "https://www.youtube.com/SomeCustom"
    ) == ("custom", "SomeCustom")


def test_parse_channel_input_plain_name_is_search():
    assert source_resolve.parse_channel_input("빵이네 티비") == ("search", "빵이네 티비")


def test_parse_playlist_id_url_forms():
    assert (
        source_resolve.parse_playlist_id(
            "https://www.youtube.com/playlist?list=PLabc123def456"
        )
        == "PLabc123def456"
    )
    assert (
        source_resolve.parse_playlist_id(
            "https://www.youtube.com/watch?v=xyz&list=PLabc123def456"
        )
        == "PLabc123def456"
    )
    assert (
        source_resolve.parse_playlist_id("https://youtu.be/xyz?list=UUabc123def456")
        == "UUabc123def456"
    )


def test_parse_playlist_id_bare_and_invalid():
    assert source_resolve.parse_playlist_id("PLabcdefghij123") == "PLabcdefghij123"
    assert source_resolve.parse_playlist_id("그냥 텍스트") is None
    assert source_resolve.parse_playlist_id("") is None


def test_parse_video_id_variants():
    assert source_resolve.parse_video_id("https://youtu.be/ZLONY_jLGC4") == "ZLONY_jLGC4"
    assert (
        source_resolve.parse_video_id("https://www.youtube.com/watch?v=ZLONY_jLGC4")
        == "ZLONY_jLGC4"
    )
    assert (
        source_resolve.parse_video_id("https://www.youtube.com/shorts/abcDEF12345")
        == "abcDEF12345"
    )
    assert (
        source_resolve.parse_video_id("https://www.youtube.com/embed/abcDEF12345")
        == "abcDEF12345"
    )
    # bare 문자열은 키워드와 모호해 영상으로 보지 않는다.
    assert source_resolve.parse_video_id("부산 맛집") is None
    # list= 만 있는 재생목록 URL은 영상 ID가 아니다.
    assert source_resolve.parse_video_id("https://www.youtube.com/playlist?list=PLx") is None


def test_is_video_id():
    assert source_resolve.is_video_id("ZLONY_jLGC4") is True
    assert source_resolve.is_video_id("too-short") is False
    assert source_resolve.is_video_id(_UC) is False


def test_classify_source_input_auto():
    cls = source_resolve.classify_source_input
    assert cls("https://www.youtube.com/watch?v=ZLONY_jLGC4") == ("video", "ZLONY_jLGC4")
    assert cls("https://youtu.be/ZLONY_jLGC4") == ("video", "ZLONY_jLGC4")
    assert cls("https://www.youtube.com/playlist?list=PLabc123def456") == (
        "playlist",
        "PLabc123def456",
    )
    # watch + list 둘 다면 재생목록 우선.
    assert cls("https://www.youtube.com/watch?v=ZLONY_jLGC4&list=PLabc123def456") == (
        "playlist",
        "PLabc123def456",
    )
    assert cls(f"https://www.youtube.com/channel/{_UC}")[0] == "channel"
    assert cls("https://www.youtube.com/@bbang_tv")[0] == "channel"
    assert cls(_UC) == ("channel", _UC)
    assert cls("@bbang_tv") == ("channel", "@bbang_tv")
    assert cls("PLabcdefghij123") == ("playlist", "PLabcdefghij123")
    assert cls("부산 맛집") == ("keyword", "부산 맛집")
    assert cls("") == ("keyword", "")


class _FakeClient:
    def __init__(self, *, handle=None, username=None, search=None):
        self._handle = handle
        self._username = username
        self._search = search
        self.calls: list[tuple[str, str]] = []

    async def channels_list_by_handle(self, handle: str):
        self.calls.append(("handle", handle))
        return {"items": [{"id": self._handle}]} if self._handle else {"items": []}

    async def channels_list_by_username(self, username: str):
        self.calls.append(("username", username))
        return {"items": [{"id": self._username}]} if self._username else {"items": []}

    async def search_channels(self, query: str, *, max_results: int = 1):
        self.calls.append(("search", query))
        return (
            {"items": [{"id": {"channelId": self._search}}]}
            if self._search
            else {"items": []}
        )


async def test_resolve_channel_id_passthrough_id_no_api():
    client = _FakeClient()
    assert await source_resolve.resolve_channel_id(client, _UC) == _UC
    assert client.calls == []


async def test_resolve_channel_id_handle():
    client = _FakeClient(handle="UChandleresolved00000000")
    assert (
        await source_resolve.resolve_channel_id(client, "@somehandle")
        == "UChandleresolved00000000"
    )
    assert client.calls == [("handle", "@somehandle")]


async def test_resolve_channel_id_search_for_plain_name():
    client = _FakeClient(search="UCsearchresolved00000000")
    assert (
        await source_resolve.resolve_channel_id(client, "빵이네 티비")
        == "UCsearchresolved00000000"
    )
    assert client.calls == [("search", "빵이네 티비")]


async def test_resolve_channel_id_custom_falls_back_to_search():
    client = _FakeClient(handle=None, search="UCcustomsearched00000000")
    resolved = await source_resolve.resolve_channel_id(
        client, "https://youtube.com/c/SomeCustom"
    )
    assert resolved == "UCcustomsearched00000000"
    assert client.calls == [("handle", "SomeCustom"), ("search", "SomeCustom")]


async def test_resolve_channel_id_returns_none_when_unresolved():
    client = _FakeClient()
    assert await source_resolve.resolve_channel_id(client, "@nope") is None
