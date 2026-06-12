"""T-005 공간/도메인 모델 영속성 및 관계 테스트."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import (
    AssetType,
    CrawlStatus,
    DescriptionReviewStatus,
    ExtractedPlaceCandidate,
    MatchStatus,
    MediaAsset,
    SearchKeyword,
    SourceTarget,
    TravelPlace,
    VideoPlaceMapping,
    YoutubeVideo,
)


async def test_search_keyword_persist(session):
    kw = SearchKeyword(seed_keyword="제주도", derived_keyword="제주도 겨울 맛집", season_context="winter")
    session.add(kw)
    await session.commit()
    await session.refresh(kw)
    assert kw.id is not None
    assert kw.is_active is True


async def test_search_keyword_unique_seed_derived_season(session):
    first = SearchKeyword(
        seed_keyword="제주도",
        derived_keyword="제주도 겨울 맛집",
        season_context="winter",
    )
    duplicate = SearchKeyword(
        seed_keyword="제주도",
        derived_keyword="제주도 겨울 맛집",
        season_context="winter",
    )
    session.add_all([first, duplicate])

    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_source_target_persist(session):
    t = SourceTarget(target_type="channel", source_value="UC123", display_name="여행유튜버")
    session.add(t)
    await session.commit()
    assert t.id is not None


async def test_source_target_unique_type_value(session):
    session.add_all(
        [
            SourceTarget(target_type="channel", source_value="UC123"),
            SourceTarget(target_type="channel", source_value="UC123"),
        ]
    )

    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_youtube_video_description_fields_separated(session):
    v = YoutubeVideo(
        video_id="abc123",
        title="제주 여행",
        url="https://youtu.be/abc123",
        channel_id="UC123",
        description_raw="원문 설명 (오탈자 포함)",
        description_gemini_corrected="보정된 설명",
        description_gemini_model="gemini-2.0-flash",
    )
    session.add(v)
    await session.commit()
    await session.refresh(v)
    # 원문과 보정본이 분리 저장된다 (원문을 덮어쓰지 않는다).
    assert v.description_raw == "원문 설명 (오탈자 포함)"
    assert v.description_gemini_corrected == "보정된 설명"
    assert v.crawl_status == CrawlStatus.DISCOVERED


async def test_travel_place_description_fields(session):
    p = TravelPlace(
        name="해운대 해수욕장",
        description="기본 설명",
        gemini_enriched_description="Gemini 보강 설명",
        latitude=35.1587,
        longitude=129.1604,
        is_geocoded=True,
    )
    session.add(p)
    await session.commit()
    await session.refresh(p)
    assert p.place_id is not None
    assert p.description != p.gemini_enriched_description
    assert p.description_review_status == DescriptionReviewStatus.AI_GENERATED


async def test_candidate_defaults_to_needs_review(session):
    v = YoutubeVideo(video_id="vid1", title="t", url="u", channel_id="c")
    session.add(v)
    await session.commit()

    c = ExtractedPlaceCandidate(
        video_id="vid1",
        source_text="자막 원문",
        ai_place_name="모호한 장소",
    )
    session.add(c)
    await session.commit()
    await session.refresh(c)
    # 매칭 실패 후보는 자동 확정하지 않고 needs_review로 남긴다.
    assert c.match_status == MatchStatus.NEEDS_REVIEW
    assert c.matched_place_id is None


async def test_media_asset_infinite_retention(session):
    a = MediaAsset(
        asset_type=AssetType.FRAME,
        bucket="krtour-frames",
        object_key="vid1/frame.jpg",
        object_uri="http://localhost:12101/krtour-frames/vid1/frame.jpg",
        size_bytes=1024,
        sha256="deadbeef",
    )
    session.add(a)
    await session.commit()
    await session.refresh(a)
    assert a.storage_provider == "rustfs"
    assert a.retention_policy == "infinite"


async def test_video_place_mapping_relations(session):
    v = YoutubeVideo(video_id="vid2", title="t", url="u", channel_id="c")
    p = TravelPlace(name="장소", latitude=37.5, longitude=127.0, is_geocoded=True)
    session.add_all([v, p])
    await session.commit()
    await session.refresh(p)

    m = VideoPlaceMapping(video_id="vid2", place_id=p.place_id, ai_summary="요약")
    session.add(m)
    await session.commit()
    assert m.id is not None


async def test_video_place_mapping_allows_repeated_mentions(session):
    v = YoutubeVideo(video_id="vid-repeat", title="t", url="u", channel_id="c")
    p = TravelPlace(name="장소", latitude=37.5, longitude=127.0, is_geocoded=True)
    session.add_all([v, p])
    await session.commit()
    await session.refresh(p)

    session.add_all(
        [
            VideoPlaceMapping(video_id=v.video_id, place_id=p.place_id, ai_summary="요약1"),
            VideoPlaceMapping(video_id=v.video_id, place_id=p.place_id, ai_summary="요약2"),
        ]
    )
    await session.commit()

    result = await session.execute(select(VideoPlaceMapping))
    assert len(result.scalars().all()) == 2


def _foreign_key_ondelete(model, column_name: str) -> str | None:
    [foreign_key] = list(model.__table__.c[column_name].foreign_keys)
    return foreign_key.ondelete


def test_model_foreign_keys_declare_delete_policy():
    assert _foreign_key_ondelete(ExtractedPlaceCandidate, "video_id") == "NO ACTION"
    assert _foreign_key_ondelete(ExtractedPlaceCandidate, "matched_place_id") == "NO ACTION"
    assert _foreign_key_ondelete(MediaAsset, "video_id") == "NO ACTION"
    assert _foreign_key_ondelete(MediaAsset, "place_id") == "NO ACTION"
    assert _foreign_key_ondelete(VideoPlaceMapping, "video_id") == "NO ACTION"
    assert _foreign_key_ondelete(VideoPlaceMapping, "place_id") == "NO ACTION"
    assert _foreign_key_ondelete(VideoPlaceMapping, "place_candidate_id") == "NO ACTION"
    assert _foreign_key_ondelete(VideoPlaceMapping, "frame_asset_id") == "NO ACTION"
