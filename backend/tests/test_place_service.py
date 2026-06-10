"""place_service 근접 탐색/중복 후보/검수 큐 테스트."""

from __future__ import annotations

from app.models import (
    ExtractedPlaceCandidate,
    MatchStatus,
    TravelPlace,
    VideoPlaceMapping,
    YoutubeVideo,
)
from app.services import place_service as svc


def test_haversine_known_distance():
    # 서울시청(37.5663,126.9779) ~ 부산시청(35.1797,129.0750) 약 325km
    d = svc.haversine_meters(37.5663, 126.9779, 35.1797, 129.0750)
    assert 320_000 < d < 330_000


async def _add_place(session, name, lat, lng, geocoded=True):
    p = TravelPlace(name=name, latitude=lat, longitude=lng, is_geocoded=geocoded)
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return p


async def test_find_within_radius_filters_and_sorts(session):
    # 해운대 기준 근처/먼 장소 배치
    await _add_place(session, "해운대", 35.1587, 129.1604)
    await _add_place(session, "광안리", 35.1532, 129.1186)  # 약 4km
    await _add_place(session, "서울", 37.5663, 126.9779)  # 약 325km

    results = await svc.find_places_within_radius(
        session, lat=35.1587, lng=129.1604, radius_meters=5000
    )
    names = [p.name for p, _ in results]
    assert "해운대" in names
    assert "광안리" in names
    assert "서울" not in names
    # 거리 오름차순: 가장 가까운 해운대가 먼저
    assert results[0][0].name == "해운대"
    assert results[0][1] < results[1][1]


async def test_excludes_non_geocoded(session):
    await _add_place(session, "미지오코딩", 35.1587, 129.1604, geocoded=False)
    results = await svc.find_places_within_radius(
        session, lat=35.1587, lng=129.1604, radius_meters=1000
    )
    assert results == []


async def test_find_duplicate_candidates(session):
    await _add_place(session, "기존장소", 35.1587, 129.1604)
    # 약 20m 떨어진 신규 좌표 -> 중복 의심
    dups = await svc.find_duplicate_candidates(
        session, lat=35.15888, lng=129.1604, radius_meters=100
    )
    assert len(dups) == 1
    assert dups[0][0].name == "기존장소"


async def test_list_unmatched_candidates(session):
    v = YoutubeVideo(video_id="v1", title="t", url="u", channel_id="c")
    session.add(v)
    await session.commit()
    session.add_all(
        [
            ExtractedPlaceCandidate(
                video_id="v1", source_text="s", ai_place_name="검수대상",
                match_status=MatchStatus.NEEDS_REVIEW,
            ),
            ExtractedPlaceCandidate(
                video_id="v1", source_text="s", ai_place_name="이미매칭",
                match_status=MatchStatus.MATCHED,
            ),
        ]
    )
    await session.commit()

    unmatched = await svc.list_unmatched_candidates(session)
    assert len(unmatched) == 1
    assert unmatched[0].ai_place_name == "검수대상"


async def test_resolve_create_place_fills_category_code_via_selector(session):
    session.add(YoutubeVideo(video_id="v1", title="t", url="u", channel_id="c"))
    await session.commit()
    candidate = ExtractedPlaceCandidate(
        video_id="v1", source_text="s", ai_place_name="월정리 해변",
        match_status=MatchStatus.NEEDS_REVIEW,
    )
    session.add(candidate)
    await session.commit()
    await session.refresh(candidate)

    captured = {}

    def fake_selector(*, name, category_label=None, description=None, address=None):
        captured["name"] = name
        captured["category_label"] = category_label
        return "01050100"

    _, place, _ = await svc.resolve_candidate(
        session,
        candidate_id=candidate.id,
        action="create_place",
        reviewed_by="web",
        place_data={
            "name": "월정리 해변",
            "latitude": 33.5563,
            "longitude": 126.7958,
            "category": "해변",
        },
        category_code_selector=fake_selector,
    )
    assert place is not None
    assert place.category_code_suggestion == "01050100"
    assert captured["name"] == "월정리 해변"
    assert captured["category_label"] == "해변"


async def test_resolve_create_place_without_selector_leaves_code_none(session):
    session.add(YoutubeVideo(video_id="v2", title="t", url="u", channel_id="c"))
    await session.commit()
    candidate = ExtractedPlaceCandidate(
        video_id="v2", source_text="s", ai_place_name="장소",
        match_status=MatchStatus.NEEDS_REVIEW,
    )
    session.add(candidate)
    await session.commit()
    await session.refresh(candidate)

    _, place, _ = await svc.resolve_candidate(
        session,
        candidate_id=candidate.id,
        action="create_place",
        reviewed_by="web",
        place_data={"name": "장소", "latitude": 33.5, "longitude": 126.7},
    )
    assert place is not None
    assert place.category_code_suggestion is None


async def test_list_place_summaries_sorts_by_mention_count(session):
    video = YoutubeVideo(
        video_id="v-source",
        title="부산 여행",
        url="https://youtu.be/source",
        channel_id="uc-source",
        channel_name="여행 채널",
    )
    first = TravelPlace(name="첫 장소", latitude=35.0, longitude=129.0, is_geocoded=True)
    second = TravelPlace(name="반복 장소", latitude=35.1, longitude=129.1, is_geocoded=True)
    session.add_all([video, first, second])
    await session.commit()
    await session.refresh(first)
    await session.refresh(second)
    session.add_all(
        [
            VideoPlaceMapping(video_id=video.video_id, place_id=second.place_id, ai_summary="1"),
            VideoPlaceMapping(video_id=video.video_id, place_id=second.place_id, ai_summary="2"),
            VideoPlaceMapping(video_id=video.video_id, place_id=first.place_id, ai_summary="3"),
        ]
    )
    await session.commit()

    summaries = await svc.list_place_summaries(session, sort="mention_count")

    assert summaries[0].place.name == "반복 장소"
    assert summaries[0].mention_count == 2
    assert summaries[0].source_channel_count == 1
    assert summaries[0].source_videos[0].channel_name == "여행 채널"
