"""T-187 검수 큐 provenance facet 회귀 검증.

`list_review_source_facets`(후보 provenance 기반)가 `list_place_facets`(확정 장소
기반)와 달리 **확정 장소가 없는 출처도 노출**하고, `candidate_count`가 현재 목록
filter(국내 여부 등)를 반영하되 그룹 차원(channel/playlist/keyword 선택)은 제외하는지
확인한다.
"""

from __future__ import annotations

import pytest

from ktc.models import (
    ExtractedPlaceCandidate,
    MatchStatus,
    YoutubeChannel,
    YoutubePlaylist,
    YoutubeVideo,
)
from ktc.services import place_service as svc

pytestmark = pytest.mark.asyncio


async def _seed(session):
    session.add_all(
        [
            YoutubeChannel(channel_id="UC-alpha", title="알파 채널"),
            # UC-beta는 확정 장소가 전혀 없고 검수 후보만 있는 출처다.
            YoutubeChannel(channel_id="UC-beta", title="베타 채널"),
        ]
    )
    session.add(
        YoutubePlaylist(playlist_id="PL-1", channel_id="UC-alpha", title="재생목록 1")
    )
    session.add_all(
        [
            YoutubeVideo(
                video_id="v-a",
                title="영상 A",
                url="u-a",
                channel_id="UC-alpha",
                channel_name="알파",
                source_search_query="부산 여행",
            ),
            YoutubeVideo(
                video_id="v-b",
                title="영상 B",
                url="u-b",
                channel_id="UC-beta",
                channel_name="베타",
                source_search_query="제주 맛집",
            ),
        ]
    )
    await session.flush()

    def cand(video_id, name, *, is_domestic, playlist=None, channel=None, status=None):
        return ExtractedPlaceCandidate(
            video_id=video_id,
            source_text="s",
            ai_place_name=name,
            match_status=status or MatchStatus.NEEDS_REVIEW,
            is_domestic=is_domestic,
            source_playlist_id=playlist,
            source_channel_id=channel,
        )

    session.add_all(
        [
            # 알파: needs_review 국내 2 + 해외 1, 재생목록 PL-1 1건
            cand("v-a", "알파-국내1", is_domestic=True, playlist="PL-1"),
            cand("v-a", "알파-국내2", is_domestic=True),
            cand("v-a", "알파-해외1", is_domestic=False),
            # 베타(확정 장소 없음): needs_review 국내 1
            cand("v-b", "베타-국내1", is_domestic=True),
            # 제외/처리된 후보는 needs_review facet에서 빠져야 한다.
            cand("v-b", "베타-무시", is_domestic=True, status=MatchStatus.IGNORED),
        ]
    )
    await session.commit()


async def test_review_facets_expose_sources_without_confirmed_places(session):
    await _seed(session)

    facets = await svc.list_review_source_facets(session)
    channel_counts = {c["value"]: c["candidate_count"] for c in facets["channels"]}
    # 확정 장소가 없는 베타 출처도 검수 후보 provenance로 노출된다.
    assert channel_counts == {"UC-alpha": 3, "UC-beta": 1}
    labels = {c["value"]: c["label"] for c in facets["channels"]}
    assert labels["UC-beta"] == "베타 채널"

    keyword_counts = {k["value"]: k["candidate_count"] for k in facets["keywords"]}
    assert keyword_counts == {"부산 여행": 3, "제주 맛집": 1}

    playlist_counts = {p["value"]: p["candidate_count"] for p in facets["playlists"]}
    assert playlist_counts == {"PL-1": 1}

    # 대조: 확정 장소 기반 facet은 장소가 없는 두 채널을 노출하지 않는다.
    place_facets = await svc.list_place_facets(session)
    assert place_facets["channels"] == []


async def test_review_facets_reflect_domestic_filter(session):
    await _seed(session)

    domestic = await svc.list_review_source_facets(session, is_domestic=True)
    channel_counts = {c["value"]: c["candidate_count"] for c in domestic["channels"]}
    # 국내 판정만: 알파 2, 베타 1 (해외 1건과 무시 1건 제외).
    assert channel_counts == {"UC-alpha": 2, "UC-beta": 1}

    foreign = await svc.list_review_source_facets(session, is_domestic=False)
    foreign_counts = {c["value"]: c["candidate_count"] for c in foreign["channels"]}
    assert foreign_counts == {"UC-alpha": 1}


async def test_review_facets_removed_status_scopes_to_removed(session):
    await _seed(session)

    removed = await svc.list_review_source_facets(
        session, status=svc.ReviewCandidateStatus.REMOVED
    )
    channel_counts = {c["value"]: c["candidate_count"] for c in removed["channels"]}
    # 무시(IGNORED) 후보만 removed로 집계된다.
    assert channel_counts == {"UC-beta": 1}
