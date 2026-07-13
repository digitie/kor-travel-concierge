"""ingest_service 멱등 upsert/워터마크 테스트."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select

from ktc.etl import ingest_service
from ktc.models import (
    ExportDirtyOutbox,
    ExtractedPlaceCandidate,
    FeatureExport,
    FeatureExportStatus,
    GroundingStatus,
    MatchStatus,
    TravelPlace,
    YoutubeChannel,
    YoutubePlaylist,
    YoutubePlaylistVideo,
    YoutubeVideo,
    utcnow,
)


async def _seed_exportable_candidate(
    session,
    *,
    video_id: str,
    source_channel_id: str | None = None,
    source_playlist_id: str | None = None,
) -> int:
    """공유 YouTube metadata dirty 배선 검증용 활성 export 후보를 만든다."""
    place = TravelPlace(
        name=f"테스트 장소 {video_id}",
        latitude=37.5,
        longitude=127.0,
        is_geocoded=True,
    )
    session.add(place)
    await session.flush()
    candidate = ExtractedPlaceCandidate(
        video_id=video_id,
        source_channel_id=source_channel_id,
        source_playlist_id=source_playlist_id,
        source_text="원문 근거",
        ai_place_name=place.name,
        grounding_status=GroundingStatus.VERIFIED_RAW.value,
        match_status=MatchStatus.MATCHED.value,
        matched_place_id=place.place_id,
        feature_export_status=FeatureExportStatus.READY.value,
    )
    session.add(candidate)
    await session.commit()
    return int(candidate.id)


async def _dirty_candidate_ids(session) -> set[int]:
    rows = (await session.execute(select(ExportDirtyOutbox.candidate_id))).scalars()
    return {int(candidate_id) for candidate_id in rows}


async def _clear_dirty_candidates(session) -> None:
    await session.execute(delete(ExportDirtyOutbox))
    await session.commit()


def test_parse_published_at():
    dt = ingest_service.parse_published_at("2026-05-01T12:00:00Z")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.year == 2026 and dt.month == 5
    assert ingest_service.parse_published_at(None) is None
    assert ingest_service.parse_published_at("garbage") is None


def test_parse_duration_seconds():
    assert ingest_service.parse_duration_seconds("PT1H2M3S") == 3723
    assert ingest_service.parse_duration_seconds("PT15M") == 900
    assert ingest_service.parse_duration_seconds("P1DT2S") == 86402
    assert ingest_service.parse_duration_seconds(None) is None
    assert ingest_service.parse_duration_seconds("garbage") is None


def test_build_youtube_source_metadata():
    now = datetime(2026, 6, 10, tzinfo=timezone.utc)
    channel = ingest_service.build_channel_metadata(
        {
            "id": "UC1",
            "snippet": {
                "title": "여행채널",
                "customUrl": "@travel",
                "publishedAt": "2020-01-01T00:00:00Z",
                "thumbnails": {
                    "default": {"url": "small.jpg"},
                    "high": {"url": "large.jpg"},
                },
            },
            "statistics": {"subscriberCount": "1234", "videoCount": "56"},
        },
        now=now,
    )
    assert channel["channel_id"] == "UC1"
    assert channel["thumbnail_url"] == "large.jpg"
    assert channel["subscriber_count"] == 1234

    playlist = ingest_service.build_playlist_metadata(
        {
            "id": "PL1",
            "snippet": {"channelId": "UC1", "title": "서울 맛집"},
            "contentDetails": {"itemCount": "7"},
        },
        now=now,
    )
    assert playlist["playlist_id"] == "PL1"
    assert playlist["channel_id"] == "UC1"
    assert playlist["item_count"] == 7

    link = ingest_service.build_playlist_video_link(
        {
            "id": "PLI1",
            "snippet": {
                "position": 3,
                "publishedAt": "2026-06-01T00:00:00Z",
                "resourceId": {"videoId": "v1"},
            },
        },
        playlist_id="PL1",
        now=now,
    )
    assert link is not None
    assert link["playlist_id"] == "PL1"
    assert link["video_id"] == "v1"
    assert link["position"] == 3


async def test_upsert_video_idempotent(session):
    candidate = {
        "video_id": "vid1",
        "title": "제주 여행",
        "channel_id": "UC1",
        "view_count": 100,
        "like_count": 10,
        "description_raw": "원문",
    }
    video, created = await ingest_service.upsert_video(session, candidate)
    assert created is True
    assert video.title == "제주 여행"

    # 같은 video_id 재적재는 갱신(insert 아님)
    candidate["view_count"] = 200
    video2, created2 = await ingest_service.upsert_video(session, candidate)
    assert created2 is False
    assert video2.view_count == 200

    # 행이 하나만 존재
    count = len((await session.execute(select(YoutubeVideo))).scalars().all())
    assert count == 1


async def test_upsert_preserves_gemini_corrected(session):
    await ingest_service.upsert_video(session, {"video_id": "v", "channel_id": "c"})
    v = await session.get(YoutubeVideo, "v")
    v.description_gemini_corrected = "보정본"
    await session.commit()

    # 재수집 시 Gemini 보정 필드는 유지된다.
    await ingest_service.upsert_video(session, {"video_id": "v", "channel_id": "c", "title": "새 제목"})
    refreshed = await session.get(YoutubeVideo, "v")
    assert refreshed.description_gemini_corrected == "보정본"
    assert refreshed.title == "새 제목"


async def test_upsert_ignores_empty_metadata_values(session):
    await ingest_service.upsert_video(
        session,
        {
            "video_id": "v-empty",
            "channel_id": "UC1",
            "title": "원래 제목",
            "description_raw": "원래 설명",
        },
    )

    await ingest_service.upsert_video(
        session,
        {
            "video_id": "v-empty",
            "channel_id": "",
            "title": "",
            "description_raw": "",
        },
    )

    refreshed = await session.get(YoutubeVideo, "v-empty")
    assert refreshed.channel_id == "UC1"
    assert refreshed.title == "원래 제목"
    assert refreshed.description_raw == "원래 설명"


async def test_channel_watermark(session):
    assert await ingest_service.get_channel_watermark(session, "UC1") is None
    await ingest_service.upsert_video(
        session,
        {
            "video_id": "a",
            "channel_id": "UC1",
            "published_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        },
    )
    await ingest_service.upsert_video(
        session,
        {
            "video_id": "b",
            "channel_id": "UC1",
            "published_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
        },
    )
    wm = await ingest_service.get_channel_watermark(session, "UC1")
    assert wm is not None
    assert wm.month == 5


async def test_ingest_candidates_summary(session):
    cands = [
        {"video_id": "x", "channel_id": "c"},
        {"video_id": "y", "channel_id": "c"},
        {"video_id": "x", "channel_id": "c"},  # 중복 -> 갱신
    ]
    summary = await ingest_service.ingest_candidates(session, cands)
    assert summary["discovered"] == 3
    assert summary["inserted"] == 2
    assert summary["updated"] == 1


async def test_ingest_candidates_upserts_youtube_source_links(session):
    now = datetime(2026, 6, 10, tzinfo=timezone.utc)
    summary = await ingest_service.ingest_candidates(
        session,
        [
            {
                "video_id": "v1",
                "channel_id": "UC1",
                "channel_name": "여행채널",
                "canonical_url": "https://www.youtube.com/watch?v=v1",
                "duration_seconds": 123,
                "thumbnail_url": "https://i.ytimg.com/vi/v1/maxresdefault.jpg",
                "default_language": "ko",
                "tags_json": ["서울", "맛집"],
            }
        ],
        channels=[
            {
                "channel_id": "UC1",
                "title": "여행채널",
                "handle": "@travel",
                "last_seen_at": now,
            }
        ],
        playlists=[
            {
                "playlist_id": "PL1",
                "channel_id": "UC1",
                "title": "서울 맛집",
                "last_crawled_at": now,
            }
        ],
        playlist_links=[
            {
                "playlist_id": "PL1",
                "video_id": "v1",
                "position": 0,
                "playlist_item_id": "PLI1",
                "first_seen_at": now,
                "last_seen_at": now,
            }
        ],
    )

    assert summary["channels_inserted"] == 1
    assert summary["playlists_inserted"] == 1
    assert summary["playlist_links_inserted"] == 1

    channel = await session.get(YoutubeChannel, "UC1")
    video = await session.get(YoutubeVideo, "v1")
    playlist = await session.get(YoutubePlaylist, "PL1")
    link = await session.get(YoutubePlaylistVideo, ("PL1", "v1"))
    assert channel is not None and channel.handle == "@travel"
    assert video is not None and video.duration_seconds == 123
    assert video.tags_json == ["서울", "맛집"]
    assert playlist is not None and playlist.channel_id == "UC1"
    assert link is not None and link.position == 0


async def test_channel_export_title_change_dirties_all_linked_candidates_only(session):
    """채널 title은 후보 직접 연결과 영상 경유 연결 모두에 복제된다."""
    now = datetime(2026, 6, 10, tzinfo=timezone.utc)
    await ingest_service.upsert_channel(
        session, {"channel_id": "UC-dirty", "title": "기존 채널", "last_seen_at": now}
    )
    await ingest_service.upsert_video(
        session,
        {"video_id": "v-channel-video", "channel_id": "UC-dirty", "title": "영상 A"},
    )
    await ingest_service.upsert_video(
        session,
        {"video_id": "v-channel-direct", "channel_id": "UC-other", "title": "영상 B"},
    )
    via_video_id = await _seed_exportable_candidate(
        session, video_id="v-channel-video"
    )
    direct_id = await _seed_exportable_candidate(
        session,
        video_id="v-channel-direct",
        source_channel_id="UC-dirty",
    )

    await ingest_service.upsert_channel(
        session,
        {"channel_id": "UC-dirty", "title": "새 채널", "last_seen_at": now},
    )
    assert await _dirty_candidate_ids(session) == {via_video_id, direct_id}

    await _clear_dirty_candidates(session)
    await ingest_service.upsert_channel(
        session,
        {
            "channel_id": "UC-dirty",
            "title": "새 채널",
            "subscriber_count": 999,
            "last_seen_at": now,
        },
    )
    assert await _dirty_candidate_ids(session) == set()


async def test_playlist_export_title_change_dirties_linked_candidates_only(session):
    """재생목록의 공급 비대상 통계만 바뀌면 outbox churn이 없어야 한다."""
    await ingest_service.upsert_video(
        session,
        {"video_id": "v-playlist", "channel_id": "UC-playlist", "title": "영상"},
    )
    await ingest_service.upsert_playlist(
        session,
        {
            "playlist_id": "PL-dirty",
            "channel_id": "UC-playlist",
            "title": "기존 재생목록",
            "item_count": 1,
        },
    )
    candidate_id = await _seed_exportable_candidate(
        session,
        video_id="v-playlist",
        source_playlist_id="PL-dirty",
    )

    await ingest_service.upsert_playlist(
        session,
        {
            "playlist_id": "PL-dirty",
            "channel_id": "UC-playlist",
            "title": "새 재생목록",
            "item_count": 1,
        },
    )
    assert await _dirty_candidate_ids(session) == {candidate_id}

    await _clear_dirty_candidates(session)
    await ingest_service.upsert_playlist(
        session,
        {
            "playlist_id": "PL-dirty",
            "channel_id": "UC-playlist",
            "title": "새 재생목록",
            "item_count": 2,
        },
    )
    assert await _dirty_candidate_ids(session) == set()


async def test_video_export_metadata_change_dirties_every_live_candidate(session):
    """영상 title/URL/source/channel linkage 변경은 같은 영상 후보 전부를 갱신한다."""
    initial = {
        "video_id": "v-dirty",
        "channel_id": "UC-video-old",
        "title": "기존 영상",
        "url": "https://youtu.be/v-dirty",
        "canonical_url": "https://www.youtube.com/watch?v=v-dirty",
        "source_target_type": "keyword",
        "source_target_value": "서울 여행",
        "source_search_query": "서울 여행",
        "view_count": 10,
    }
    await ingest_service.upsert_video(session, initial)
    first_id = await _seed_exportable_candidate(session, video_id="v-dirty")
    second_id = await _seed_exportable_candidate(session, video_id="v-dirty")
    deleted_id = await _seed_exportable_candidate(session, video_id="v-dirty")
    deleted_candidate = await session.get(ExtractedPlaceCandidate, deleted_id)
    assert deleted_candidate is not None
    deleted_candidate.deleted_at = utcnow()
    deleted_candidate.deletion_reason = "테스트 soft delete"
    await session.commit()

    changed = {
        **initial,
        "channel_id": "UC-video-new",
        "title": "새 영상",
        "url": "https://youtu.be/v-dirty?feature=shared",
        "canonical_url": "https://www.youtube.com/watch?v=v-dirty&feature=shared",
        "source_target_type": "channel",
        "source_target_value": "UC-video-new",
        "source_search_query": "서울 산책",
        "view_count": 20,
    }
    await ingest_service.upsert_video(session, changed)
    assert await _dirty_candidate_ids(session) == {first_id, second_id}

    await _clear_dirty_candidates(session)
    await ingest_service.upsert_video(session, {**changed, "view_count": 30})
    assert await _dirty_candidate_ids(session) == set()


async def test_channel_stub_title_upgrade_dirties_linked_candidates_once(session):
    """stub ID title을 실제 채널명으로 승격할 때만 공급 후보를 다시 발행한다."""
    await ingest_service.ensure_channel_stub(session, channel_id="UC-stub")
    await session.commit()
    await ingest_service.upsert_video(
        session,
        {"video_id": "v-stub", "channel_id": "UC-stub", "title": "영상"},
    )
    candidate_id = await _seed_exportable_candidate(session, video_id="v-stub")

    await ingest_service.ensure_channel_stub(
        session, channel_id="UC-stub", title="실제 채널명"
    )
    await session.commit()
    assert await _dirty_candidate_ids(session) == {candidate_id}

    await _clear_dirty_candidates(session)
    await ingest_service.ensure_channel_stub(
        session, channel_id="UC-stub", title="실제 채널명"
    )
    await session.commit()
    assert await _dirty_candidate_ids(session) == set()


async def test_stale_video_identity_reloads_latest_payload_without_dirty_churn(
    session_factory,
):
    """export lock 대기 전 캐시한 ORM 객체가 최신 DB metadata를 덮지 않아야 한다."""
    from ktc.services import feature_export_service

    initial = {
        "video_id": "v-stale-identity",
        "channel_id": "UC-stale-identity",
        "title": "기존 제목",
        "url": "https://youtu.be/v-stale-identity",
        "canonical_url": "https://www.youtube.com/watch?v=v-stale-identity",
        "source_target_type": "keyword",
        "source_target_value": "기존 검색어",
        "source_search_query": "기존 검색어",
    }
    latest = {**initial, "title": "동시 writer 최신 제목"}

    async with session_factory() as stale_session:
        await ingest_service.upsert_video(stale_session, initial)
        candidate_id = await _seed_exportable_candidate(
            stale_session, video_id="v-stale-identity"
        )
        await feature_export_service.mark_candidates_dirty(
            stale_session, [candidate_id], reason="test_initial_export"
        )
        await stale_session.commit()
        assert await feature_export_service.sync_dirty(stale_session) == 1

        cached = await stale_session.get(YoutubeVideo, "v-stale-identity")
        assert cached is not None and cached.title == "기존 제목"

        # 별도 writer가 DB와 outbox를 먼저 최신 상태로 확정한다. stale_session의
        # identity map에는 의도적으로 이전 title을 남겨 둔다.
        async with session_factory() as writer:
            await ingest_service.upsert_video(writer, latest)
        async with session_factory() as dirty_sync:
            assert await feature_export_service.sync_dirty(dirty_sync) == 1
        assert cached.title == "기존 제목"

        # 같은 최신 payload 재호출은 lock 뒤 SELECT ... populate_existing로 DB 값을
        # 다시 읽으므로 오래된 객체를 write-back하거나 outbox를 재생성하지 않는다.
        await ingest_service.upsert_video(stale_session, latest)
        assert cached.title == "동시 writer 최신 제목"

    async with session_factory() as verify:
        assert await _dirty_candidate_ids(verify) == set()
        export = await verify.get(FeatureExport, f"ytpc_{candidate_id}")
        assert export is not None
        assert export.payload_json["youtube"]["video_title"] == "동시 writer 최신 제목"
        assert await feature_export_service.sync_feature_exports(verify) == 0
