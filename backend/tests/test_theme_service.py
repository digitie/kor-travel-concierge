"""theme_service — 테마 중심 POI 공급 테스트.

유튜버/재생목록/보정 검색어 테마와 동영상 테마(≥5 게이트)를 검증한다.
"""

from __future__ import annotations

from ktc.models import (
    TravelPlace,
    VideoPlaceMapping,
    YoutubeChannel,
    YoutubeVideo,
)
from ktc.services import theme_service


async def _seed(session):
    """채널 c1의 영상 2개(v_a: POI 6개, v_b: POI 2개), 보정 검색어 부여."""
    session.add(YoutubeChannel(channel_id="c1", title="여행유튜버"))
    session.add(
        YoutubeVideo(
            video_id="v_a",
            title="부산 여행 6곳",
            url="https://youtu.be/v_a",
            channel_id="c1",
            channel_name="여행유튜버",
            source_target_type="keyword",
            source_search_query="부산 여행",
        )
    )
    session.add(
        YoutubeVideo(
            video_id="v_b",
            title="짧은 영상",
            url="https://youtu.be/v_b",
            channel_id="c1",
            channel_name="여행유튜버",
            source_target_type="channel",
        )
    )
    await session.flush()

    # v_a에 확정 POI 6개, v_b에 확정 POI 2개.
    for i in range(6):
        place = TravelPlace(
            name=f"A장소{i}", latitude=35.1 + i * 0.01, longitude=129.0, is_geocoded=True
        )
        session.add(place)
        await session.flush()
        session.add(
            VideoPlaceMapping(
                video_id="v_a",
                place_id=place.place_id,
                source_channel_id="c1",
                ai_summary=f"a{i}",
            )
        )
    for i in range(2):
        place = TravelPlace(
            name=f"B장소{i}", latitude=36.0 + i * 0.01, longitude=127.0, is_geocoded=True
        )
        session.add(place)
        await session.flush()
        session.add(
            VideoPlaceMapping(
                video_id="v_b",
                place_id=place.place_id,
                source_channel_id="c1",
                ai_summary=f"b{i}",
            )
        )
    await session.commit()


async def test_list_themes_counts_channels_and_keywords(session):
    await _seed(session)
    themes = await theme_service.list_theme_summaries_page(session)
    channel = next(
        item
        for item in themes.items
        if item["kind"] == "channel" and item["value"] == "c1"
    )
    # c1은 v_a(6) + v_b(2) = 8개 확정 POI를 공급한다.
    assert channel["poi_count"] == 8
    assert channel["title"] == "여행유튜버"
    keyword = next(
        item
        for item in themes.items
        if item["kind"] == "keyword" and item["value"] == "부산 여행"
    )
    # 보정 검색어 '부산 여행'은 v_a(6개)만 갖는다.
    assert keyword["poi_count"] == 6


async def test_channel_theme_returns_places(session):
    await _seed(session)
    result = await theme_service.get_theme_places(session, kind="channel", value="c1")
    assert result["theme"]["kind"] == "channel"
    assert result["theme"]["poi_count"] == 8
    assert len(result["places"]) == 8
    sample = result["places"][0]
    assert set(sample) >= {"place_id", "name", "latitude", "longitude", "address", "source_videos"}


async def test_keyword_theme_filters_by_corrected_query(session):
    await _seed(session)
    result = await theme_service.get_theme_places(
        session, kind="keyword", value="부산 여행"
    )
    assert result["theme"]["poi_count"] == 6
    assert len(result["places"]) == 6


async def test_video_theme_gate_released_when_5_or_more(session):
    await _seed(session)
    # v_a는 확정 POI 6개 ≥ 5 → 공개.
    result = await theme_service.get_video_theme_places(session, video_id="v_a")
    assert result["sufficient"] is True
    assert result["min_required"] == theme_service.VIDEO_THEME_MIN_POIS
    assert result["theme"]["poi_count"] == 6
    assert len(result["places"]) == 6
    assert result["theme"]["title"] == "부산 여행 6곳"


async def test_video_theme_gate_withheld_when_fewer_than_5(session):
    await _seed(session)
    # v_b는 확정 POI 2개 < 5 → 미공개(빈 목록).
    result = await theme_service.get_video_theme_places(session, video_id="v_b")
    assert result["sufficient"] is False
    assert result["theme"]["poi_count"] == 2
    assert result["places"] == []
