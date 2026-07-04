"""place_service 근접 탐색/중복 후보/검수 큐 테스트."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from ktc.models import (
    ExtractedPlaceCandidate,
    MatchStatus,
    MediaAsset,
    TravelPlace,
    VideoPlaceMapping,
    YoutubeVideo,
)
from ktc.services import place_service as svc


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


async def test_resolve_create_place_copies_category_code_from_candidate(session):
    # A안: 카테고리 코드는 POI 추출 때 후보 evidence에 저장된 값을 복사한다(Gemini 호출 X).
    session.add(YoutubeVideo(video_id="v1", title="t", url="u", channel_id="c"))
    await session.commit()
    candidate = ExtractedPlaceCandidate(
        video_id="v1", source_text="s", ai_place_name="월정리 해변",
        match_status=MatchStatus.NEEDS_REVIEW,
        provider_evidence_json={"transcript": {"category_code": "01050100"}},
    )
    session.add(candidate)
    await session.commit()
    await session.refresh(candidate)

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
    )
    assert place is not None
    assert place.category_code_suggestion == "01050100"


async def test_resolve_create_place_without_evidence_code_uses_unknown(session):
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
    assert place.category_code_suggestion == "0"
    assert place.category == "unknown"


async def test_delete_place_reverts_candidate_unlinks_media_removes_mapping(session):
    session.add(YoutubeVideo(video_id="vdel", title="t", url="u", channel_id="c"))
    await session.commit()
    candidate = ExtractedPlaceCandidate(
        video_id="vdel",
        source_text="s",
        ai_place_name="삭제 대상",
        match_status=MatchStatus.NEEDS_REVIEW,
    )
    session.add(candidate)
    await session.commit()
    await session.refresh(candidate)

    _, place, mapping = await svc.resolve_candidate(
        session,
        candidate_id=candidate.id,
        action="create_place",
        reviewed_by="web",
        place_data={"name": "삭제 대상", "latitude": 35.0, "longitude": 129.0},
    )
    assert place is not None and mapping is not None
    place_id = place.place_id
    asset = MediaAsset(
        place_id=place_id,
        video_id="vdel",
        asset_type="frame",
        bucket="b",
        object_key="k",
        object_uri="u",
    )
    session.add(asset)
    await session.commit()
    await session.refresh(candidate)
    assert candidate.matched_place_id == place_id

    reverted = await svc.delete_place(session, place_id=place_id)
    await session.commit()

    # 장소·매핑은 사라지고, 후보는 검수 큐로, 미디어는 링크만 해제(보존)된다.
    assert await session.get(TravelPlace, place_id) is None
    remaining = (
        (
            await session.execute(
                select(VideoPlaceMapping).where(
                    VideoPlaceMapping.place_id == place_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert remaining == []
    await session.refresh(candidate)
    assert candidate.matched_place_id is None
    assert candidate.match_status == MatchStatus.NEEDS_REVIEW
    assert candidate.id in [c.id for c in reverted]
    unmatched = await svc.list_unmatched_candidates(session)
    assert candidate.id in [c.id for c in unmatched]
    await session.refresh(asset)
    assert asset.place_id is None


async def test_delete_place_missing_raises(session):
    with pytest.raises(ValueError):
        await svc.delete_place(session, place_id=999_999)


async def test_list_place_summaries_sorts_by_mention_count(session):
    # mention_count는 매핑 행 수가 아니라 고유 영상 수다(한 영상에서 여러 번 언급돼도 1회).
    # '반복 장소'는 서로 다른 영상 2개에서 언급 → mention_count=2, '첫 장소'는 1개 → 1.
    video_a = YoutubeVideo(
        video_id="v-source-a",
        title="부산 여행 A",
        url="https://youtu.be/source-a",
        channel_id="uc-source",
        channel_name="여행 채널",
    )
    video_b = YoutubeVideo(
        video_id="v-source-b",
        title="부산 여행 B",
        url="https://youtu.be/source-b",
        channel_id="uc-source",
        channel_name="여행 채널",
    )
    first = TravelPlace(name="첫 장소", latitude=35.0, longitude=129.0, is_geocoded=True)
    second = TravelPlace(name="반복 장소", latitude=35.1, longitude=129.1, is_geocoded=True)
    session.add_all([video_a, video_b, first, second])
    await session.commit()
    await session.refresh(first)
    await session.refresh(second)
    session.add_all(
        [
            # '반복 장소': 영상 A에서 2번 언급(1회로 셈) + 영상 B에서 1번 → 고유 영상 2.
            VideoPlaceMapping(video_id=video_a.video_id, place_id=second.place_id, ai_summary="1"),
            VideoPlaceMapping(video_id=video_a.video_id, place_id=second.place_id, ai_summary="2"),
            VideoPlaceMapping(video_id=video_b.video_id, place_id=second.place_id, ai_summary="3"),
            # '첫 장소': 영상 A에서만 → 고유 영상 1.
            VideoPlaceMapping(video_id=video_a.video_id, place_id=first.place_id, ai_summary="4"),
        ]
    )
    await session.commit()

    summaries = await svc.list_place_summaries(session, sort="mention_count")

    assert summaries[0].place.name == "반복 장소"
    assert summaries[0].mention_count == 2
    assert summaries[0].source_channel_count == 1
    assert summaries[0].source_videos[0].channel_name == "여행 채널"
