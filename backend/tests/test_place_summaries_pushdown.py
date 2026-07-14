"""T-188 `/destinations` SQL pushdown 골든 검증.

재작성한 `list_place_summaries`/`list_place_summaries_page`(필터·정렬·LIMIT·keyset을
SQL로 밀어 넣음)가 재작성 전 Python 알고리즘과 **동일한 결과**를 내는지 대조한다.
참조 오라클은 유지된 Python 정본 헬퍼(`_place_matches_result_filters`,
`_list_mentions_by_place`, `_place_summary_sort_key`)를 그대로 사용해 옛 함수 본문을
재현한다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from ktc.models import (
    TravelPlace,
    VideoPlaceMapping,
    YoutubeChannel,
    YoutubePlaylist,
    YoutubeVideo,
)
from ktc.services import list_pagination
from ktc.services import place_service as svc

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------- #
# 참조 오라클: 재작성 전 list_place_summaries 본문을 그대로 재현한다.
# --------------------------------------------------------------------------- #
async def _reference_summaries(
    session,
    *,
    sort="latest",
    place_ids=None,
    limit=100,
    channel_id=None,
    playlist_id=None,
    keyword=None,
    video_id=None,
    category=None,
    query=None,
    district=None,
):
    matched = await svc._filtered_place_ids(
        session,
        channel_id=channel_id,
        playlist_id=playlist_id,
        keyword=keyword,
        video_id=video_id,
    )
    effective_ids = None
    if place_ids is not None and matched is not None:
        effective_ids = list(set(place_ids) & matched)
    elif place_ids is not None:
        effective_ids = place_ids
    elif matched is not None:
        effective_ids = list(matched)

    stmt = select(TravelPlace)
    if effective_ids is not None:
        if not effective_ids:
            return []
        stmt = stmt.where(TravelPlace.place_id.in_(effective_ids))
    places = list((await session.execute(stmt)).scalars().all())
    places = [
        p
        for p in places
        if svc._place_matches_result_filters(
            p, category=category, query=query, district=district
        )
    ]
    if not places:
        return []
    mentions = await svc._list_mentions_by_place(
        session, place_ids=[p.place_id for p in places]
    )
    summaries = [
        svc.PlaceSummary(
            place=p,
            mention_count=len({m.video_id for m in mentions.get(p.place_id, [])}),
            source_channel_count=len(
                {m.channel_id for m in mentions.get(p.place_id, []) if m.channel_id}
            ),
            source_videos=mentions.get(p.place_id, []),
        )
        for p in places
    ]
    summaries.sort(key=svc._place_summary_sort_key(sort))
    if limit is not None:
        return summaries[:limit]
    return summaries


def _fingerprint(summaries):
    """place_id 순서 + 집계 + 언급 근거(mapping_id 순서)까지 비교하는 지문."""
    return [
        (
            s.place.place_id,
            s.place.name,
            s.mention_count,
            s.source_channel_count,
            tuple(m.mapping_id for m in s.source_videos),
        )
        for s in summaries
    ]


# --------------------------------------------------------------------------- #
# 시드: COLLATE "C"(코드포인트) 정렬·필터·집계를 두루 자극한다.
# --------------------------------------------------------------------------- #
async def _seed(session):
    ch_a = "UC-alpha"
    ch_b = "UC-beta"
    session.add_all(
        [
            YoutubeChannel(channel_id=ch_a, title="알파 채널"),
            YoutubeChannel(channel_id=ch_b, title="베타 채널"),
        ]
    )
    session.add(
        YoutubePlaylist(playlist_id="PL-1", channel_id=ch_a, title="재생목록 1")
    )
    await session.flush()

    # 대문자/소문자/한글 이름을 섞어 C-collation(코드포인트)과 로케일 정렬을 구분한다.
    names = [
        "Apple",
        "apple",
        "Bravo",
        "banana",
        "Zebra",
        "zebra",
        "Zephyr",
        "가평",
        "강릉",
        "부산",
        "서울",
        "제주",
        "AB",
        "A B Cafe",
        "10월",
        "2번지",
    ]
    places: list[TravelPlace] = []
    for i, name in enumerate(names):
        # category: 다양 + 빈 문자열(미분류 정렬 분기) + unknown 기본값
        category = ["cafe", "restaurant", "unknown", "관광", ""][i % 5]
        # 절반은 sigungu_code, 나머지는 주소 라벨 fallback / 단일 토큰 / 없음
        if i % 4 == 0:
            sigungu_code = "11680"
            road_address = "서울특별시 강남구 테헤란로 152"
        elif i % 4 == 1:
            sigungu_code = None
            road_address = "부산광역시 해운대구 우동 1394"
        elif i % 4 == 2:
            sigungu_code = None
            road_address = "제주"  # 단일 토큰 → 라벨 None
        else:
            sigungu_code = None
            road_address = None
        p = TravelPlace(
            name=name,
            latitude=35.0 + i * 0.01,
            longitude=129.0 + i * 0.01,
            is_geocoded=True,
            category=category,
            sigungu_code=sigungu_code,
            sigungu_name="강남구" if sigungu_code else None,
            road_address=road_address,
            official_address=road_address,
            description=f"설명 {name} apple" if i % 3 == 0 else None,
        )
        places.append(p)
    session.add_all(places)
    await session.flush()

    # 영상: 일부는 channel_id NULL(유튜버 수 계산 제외), 검색어/재생목록 출처 다양.
    videos = [
        YoutubeVideo(
            video_id="v-a1",
            title="영상 A1",
            url="u-a1",
            channel_id=ch_a,
            channel_name="알파",
            source_search_query="부산 여행",
        ),
        YoutubeVideo(
            video_id="v-a2",
            title="영상 A2",
            url="u-a2",
            channel_id=ch_a,
            channel_name="알파",
            source_search_query="제주 맛집",
        ),
        YoutubeVideo(
            video_id="v-b1",
            title="영상 B1",
            url="u-b1",
            channel_id=ch_b,
            channel_name="베타",
            source_search_query="부산 여행",
        ),
        YoutubeVideo(
            video_id="v-null",
            title="영상 베타2",
            url="u-null",
            channel_id=ch_b,
            channel_name="베타",
            source_search_query="제주 맛집",
        ),
    ]
    session.add_all(videos)
    await session.flush()

    # 매핑: 반복 언급(같은 영상 2회 → 1회로 셈), 여러 영상/채널, 0 언급 장소 존재.
    def mp(place, video, playlist=None, channel=None):
        return VideoPlaceMapping(
            video_id=video,
            place_id=place.place_id,
            ai_summary="s",
            source_playlist_id=playlist,
            source_channel_id=channel,
        )

    mappings = []
    # places[0]: v-a1(x2) + v-b1 → 고유 영상 2, 유튜버 2
    mappings += [
        mp(places[0], "v-a1", playlist="PL-1", channel=ch_a),
        mp(places[0], "v-a1", playlist="PL-1", channel=ch_a),
        mp(places[0], "v-b1", channel=ch_b),
    ]
    # places[1]: v-a1 → 1/1
    mappings += [mp(places[1], "v-a1", playlist="PL-1", channel=ch_a)]
    # places[2]: v-null(베타) → 1 영상, 유튜버 1
    mappings += [mp(places[2], "v-null")]
    # places[3]: v-a2(알파) + v-null(베타) → 2 영상, 유튜버 2
    mappings += [mp(places[3], "v-a2", channel=ch_a), mp(places[3], "v-null")]
    # places[5]: v-b1 → 1/1
    mappings += [mp(places[5], "v-b1", channel=ch_b)]
    # places[7], places[9]: 같은 mention_count(1)로 tie-break(name) 자극
    mappings += [mp(places[7], "v-a2", channel=ch_a)]
    mappings += [mp(places[9], "v-a2", channel=ch_a)]
    # 나머지 places는 언급 0
    session.add_all(mappings)
    await session.commit()
    return {
        "channel_a": ch_a,
        "channel_b": ch_b,
        "playlist": "PL-1",
        "keyword": "부산 여행",
        "video": "v-a1",
        "district_code": "11680",
        "district_label": "부산광역시 해운대구",
        "place_ids": [p.place_id for p in places],
    }


_SORTS = ["latest", "mention_count", "name", "category"]


async def test_pushdown_matches_reference_matrix(session):
    ctx = await _seed(session)
    scenarios = [
        {},
        {"category": "cafe"},
        {"category": "관광"},
        {"category": ""},  # 빈 문자열 카테고리(있으면 필터 미적용과 동치 확인)
        {"query": "apple"},
        {"query": "APPLE"},  # 대소문자 무시
        {"query": "강남"},
        {"district": ctx["district_code"]},
        {"district": ctx["district_label"]},
        {"channel_id": ctx["channel_a"]},
        {"channel_id": ctx["channel_b"]},
        {"playlist_id": ctx["playlist"]},
        {"keyword": ctx["keyword"]},
        {"video_id": ctx["video"]},
        {"channel_id": ctx["channel_a"], "category": "cafe"},
        {"query": "apple", "district": ctx["district_code"]},
    ]
    for sort in _SORTS:
        for filt in scenarios:
            for limit in (None, 3, 100):
                got = await svc.list_place_summaries(
                    session, sort=sort, limit=limit, **filt
                )
                ref = await _reference_summaries(
                    session, sort=sort, limit=limit, **filt
                )
                assert _fingerprint(got) == _fingerprint(ref), (
                    f"sort={sort} filt={filt} limit={limit}"
                )


async def test_pushdown_place_ids_intersection(session):
    ctx = await _seed(session)
    subset = ctx["place_ids"][:6]
    for sort in _SORTS:
        got = await svc.list_place_summaries(
            session, sort=sort, place_ids=subset, limit=None
        )
        ref = await _reference_summaries(
            session, sort=sort, place_ids=subset, limit=None
        )
        assert _fingerprint(got) == _fingerprint(ref)
    # place_ids + 출처 필터 교집합
    got = await svc.list_place_summaries(
        session,
        sort="mention_count",
        place_ids=subset,
        channel_id=ctx["channel_a"],
        limit=None,
    )
    ref = await _reference_summaries(
        session,
        sort="mention_count",
        place_ids=subset,
        channel_id=ctx["channel_a"],
        limit=None,
    )
    assert _fingerprint(got) == _fingerprint(ref)
    # 빈 교집합
    empty = await svc.list_place_summaries(
        session, sort="latest", place_ids=[], limit=None
    )
    assert empty == []


async def _collect_pages(session, *, sort, page_size, **filt):
    """cursor를 끝까지 따라가며 전체 순서를 모은다."""
    items = []
    cursor = None
    first_total = None
    for _ in range(100):  # 안전 상한
        page = await svc.list_place_summaries_page(
            session, sort=sort, limit=page_size, cursor=cursor, **filt
        )
        if first_total is None:
            first_total = page.total
        items.extend(page.items)
        if not page.has_more:
            break
        assert page.next_cursor is not None
        cursor = page.next_cursor
    return items, first_total


async def test_page_walk_matches_reference(session):
    ctx = await _seed(session)
    scenarios = [
        {},
        {"category": "cafe"},
        {"query": "apple"},
        {"district": ctx["district_code"]},
        {"channel_id": ctx["channel_a"]},
    ]
    for sort in _SORTS:
        for filt in scenarios:
            walked, total = await _collect_pages(
                session, sort=sort, page_size=3, **filt
            )
            ref = await _reference_summaries(session, sort=sort, limit=None, **filt)
            assert _fingerprint(walked) == _fingerprint(ref), f"{sort} {filt}"
            assert total == len(ref)


async def test_page_cursor_snapshot_isolation(session):
    """cursor snapshot watermark: 순회 중 더 큰 id가 추가돼도 끼어들지 않는다."""
    ctx = await _seed(session)
    page1 = await svc.list_place_summaries_page(session, sort="latest", limit=5)
    assert page1.has_more
    assert page1.total == len(ctx["place_ids"])
    snapshot_before = page1.newest_id

    # 순회 도중 새 장소(더 큰 place_id) 추가
    newer = TravelPlace(
        name="새 장소", latitude=36.0, longitude=127.0, is_geocoded=True
    )
    session.add(newer)
    await session.commit()

    page2 = await svc.list_place_summaries_page(
        session,
        sort="latest",
        limit=5,
        cursor=page1.next_cursor,
        newer_than_id=snapshot_before,
    )
    walked_ids = [s.place.place_id for s in page1.items + page2.items]
    # 새 장소는 snapshot 밖이라 페이지에 등장하지 않는다.
    assert newer.place_id not in walked_ids
    # newer_than은 watermark 이후 추가분 1건을 센다.
    assert page2.newer_than == 1
    assert page2.total == len(ctx["place_ids"])  # snapshot 기준 total 불변


async def test_old_scope_cursor_rejected(session):
    """구 Python-정렬 scope cursor(destinations-python-v1)는 거부된다."""
    await _seed(session)
    old_fingerprint = list_pagination.filter_fingerprint(
        scope="destinations-python-v1",
        sort="latest",
        filters={
            "channel_id": None,
            "playlist_id": None,
            "keyword": None,
            "video_id": None,
            "category": None,
            "query": None,
            "district": None,
        },
    )
    stale = list_pagination.encode_cursor(
        fingerprint=old_fingerprint, snapshot_id=5, keys=(-3,)
    )
    with pytest.raises(ValueError):
        await svc.list_place_summaries_page(session, sort="latest", cursor=stale)


async def test_empty_source_filter_returns_empty_envelope(session):
    await _seed(session)
    page = await svc.list_place_summaries_page(
        session, sort="latest", channel_id="UC-does-not-exist"
    )
    assert page.items == []
    assert page.total == 0
    assert page.has_more is False
    assert page.next_cursor is None
    assert page.newer_than == 0
