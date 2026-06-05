"""place_service 근접 탐색/중복 후보/검수 큐 테스트."""

from __future__ import annotations

from app.models import ExtractedPlaceCandidate, MatchStatus, TravelPlace, YoutubeVideo
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
