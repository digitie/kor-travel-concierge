"""description 단독 후보 경로 테스트 (T-168, 로드맵 PR-17, §1.3 D1).

자막 최종 실패 시 영상 설명(제목·태그 포함)으로 검수 전용 후보를 만드는 recall 경로를
검증한다. 자막이 성공하면 이 경로를 타지 않고(자막 우선), description 후보는 지오코딩돼도
자동확정되지 않는다(needs_review, queue_reason=description_only). grounding은 원문 설명
substring으로 판정하되 verified 여부와 무관하게 자동확정은 막는다. 외부 의존(자막 fetch·
교정·LLM 추출·지오코딩·RustFS)은 fake로 대체한다.
"""

from __future__ import annotations

from sqlalchemy import select

from ktc.etl import (
    batch_poi,
    batch_poi_service,
    postprocess_service,
    transcript_correction,
)
from ktc.etl.batch_poi_service import _build_description_text
from ktc.etl.geocode_service import apply_geocode_to_candidate
from ktc.etl.geocoding import GeocodeCandidate, GeocodeDecision
from ktc.etl.llm_client import LlmRuntime
from ktc.etl.media_store import InMemoryMediaStore
from ktc.etl.transcript import TranscriptResult, TranscriptSegment
from ktc.models import (
    CrawlStatus,
    EvidenceSourceKind,
    ExtractedPlaceCandidate,
    FeatureExportStatus,
    GroundingStatus,
    MatchStatus,
    TravelPlace,
    YoutubeVideo,
)
from ktc.services import feature_export_service, place_service
from ktc.services.place_service import QueueReason

# 임계 길이(기본 200자)를 넘는 실제형 여행 설명. 아래 evidence_quote들이 이 원문에
# substring으로 존재하는지로 grounding을 판정한다.
_LONG_DESCRIPTION = (
    "이번 대전 여행에서는 성심당 본점에서 튀김소보로를 먹고 대전 스카이로드를 걸었습니다. "
    "오후에는 한밭수목원을 산책하고 유성온천에서 잠시 발을 담갔어요. 저녁은 대전의 두부두루치기 "
    "맛집에서 마무리했습니다. 다음 영상에서는 대청호 드라이브 코스를 소개할 예정이니 많은 관심과 "
    "기대 부탁드립니다. 구독과 좋아요는 채널에 큰 힘이 됩니다. 감사합니다."
)


async def _make_video(
    session,
    *,
    video_id="descv1",
    description,
    title="대전 여행 브이로그",
    tags=None,
):
    video = YoutubeVideo(
        video_id=video_id,
        title=title,
        url=f"https://youtu.be/{video_id}",
        channel_id="UCdesc",
        description_raw=description,
        tags_json=tags,
    )
    session.add(video)
    await session.commit()
    await session.refresh(video)
    return video


async def _run_batch(session, monkeypatch, video, *, transcript_ok, pois, capture=None):
    async def fake_fetch(vid):
        if transcript_ok:
            return TranscriptResult(
                video_id=vid,
                source="transcript_api",
                segments=[TranscriptSegment(1.0, "성심당 본점 빵이 맛있습니다.")],
            )
        # 자막 최종 실패: coerce가 빈 실패 outcome(result=None)으로 감싼다.
        return None

    async def fake_correct(runtime, *, transcript, description=None, **kwargs):
        return transcript

    async def fake_extract(runtime, items, **kwargs):
        alias = items[0][0]
        return [batch_poi.BatchExtractedPOI(video_id=alias, **poi) for poi in pois]

    async def fake_geocode(session_, candidates, *, status_reporter=None):
        # 지오코딩 자동확정 게이트는 전용 단위 테스트에서 검증하고, 여기서는 후보 생성
        # 경로만 격리한다. 실제 apply는 호출하지 않는다.
        return {"matched_places": 0, "needs_review_candidates": len(candidates)}

    monkeypatch.setattr(transcript_correction, "correct_transcript", fake_correct)
    monkeypatch.setattr(batch_poi, "extract_batch", fake_extract)
    monkeypatch.setattr(postprocess_service, "geocode_candidates", fake_geocode)

    async def report(message, progress=None):
        if capture is not None:
            capture.append(message)

    return await batch_poi_service.process_video_batch(
        session,
        InMemoryMediaStore(),
        videos=[video],
        runtime=LlmRuntime(model="gemini-2.5-flash"),
        transcript_fetcher=fake_fetch,
        status_reporter=report,
    )


async def test_transcript_failure_long_description_creates_description_candidate(
    session, monkeypatch
):
    video = await _make_video(session, description=_LONG_DESCRIPTION)
    summary = await _run_batch(
        session,
        monkeypatch,
        video,
        transcript_ok=False,
        pois=[
            {
                "official_name": "성심당 본점",
                "category_code": "01050100",
                "is_domestic": True,
                "evidence_quote": "성심당 본점에서 튀김소보로를 먹고",
            }
        ],
    )
    assert summary["created_candidates"] == 1
    assert summary["failed_videos"] == 0

    candidate = (
        await session.execute(select(ExtractedPlaceCandidate))
    ).scalar_one()
    assert candidate.source_kind == EvidenceSourceKind.DESCRIPTION.value
    assert candidate.match_status == MatchStatus.NEEDS_REVIEW
    # evidence_quote가 원문 설명에 실존 → verified_raw(관측용, 자동확정 게이트 아님).
    assert candidate.grounding_status == GroundingStatus.VERIFIED_RAW.value
    evidence = candidate.provider_evidence_json["description"]
    assert evidence["video_id"] == video.video_id
    assert evidence["source"] == "youtube_description"
    assert "성심당 본점" in evidence["excerpt"]

    refreshed = await session.get(YoutubeVideo, video.video_id)
    # 자막 실패지만 description 후보를 냈으므로 폐기(FAILED)가 아니라 SUMMARIZED.
    assert refreshed.crawl_status != CrawlStatus.FAILED


async def test_transcript_failure_short_description_fails(session, monkeypatch):
    capture: list[str] = []
    video = await _make_video(
        session,
        video_id="descshort",
        description="아주 짧은 설명",
        title="짧은 제목",
    )
    summary = await _run_batch(
        session,
        monkeypatch,
        video,
        transcript_ok=False,
        pois=[{"official_name": "성심당", "is_domestic": True}],
        capture=capture,
    )
    assert summary["created_candidates"] == 0
    assert summary["failed_videos"] == 1
    candidates = (
        (await session.execute(select(ExtractedPlaceCandidate))).scalars().all()
    )
    assert candidates == []
    refreshed = await session.get(YoutubeVideo, video.video_id)
    assert refreshed.crawl_status == CrawlStatus.FAILED
    assert any("description_too_short" in message for message in capture)


async def test_transcript_success_uses_transcript_not_description(
    session, monkeypatch
):
    video = await _make_video(
        session, video_id="descok", description=_LONG_DESCRIPTION
    )
    summary = await _run_batch(
        session,
        monkeypatch,
        video,
        transcript_ok=True,
        pois=[
            {
                "official_name": "성심당 본점",
                "category_code": "01050100",
                "is_domestic": True,
                "evidence_quote": "성심당 본점 빵이 맛있습니다",
            }
        ],
    )
    assert summary["created_candidates"] == 1
    candidate = (
        await session.execute(select(ExtractedPlaceCandidate))
    ).scalar_one()
    # 자막 우선: 설명이 충분히 길어도 자막이 있으면 transcript 경로를 탄다.
    assert candidate.source_kind == EvidenceSourceKind.TRANSCRIPT.value
    assert "transcript" in candidate.provider_evidence_json
    assert "description" not in candidate.provider_evidence_json


async def test_description_grounding_unverified_when_quote_absent(
    session, monkeypatch
):
    video = await _make_video(
        session, video_id="descug", description=_LONG_DESCRIPTION
    )
    summary = await _run_batch(
        session,
        monkeypatch,
        video,
        transcript_ok=False,
        pois=[
            {
                "official_name": "엉뚱한 장소",
                "is_domestic": True,
                # 원문 설명에 존재하지 않는 창작 인용 → unverified.
                "evidence_quote": "이 문장은 설명 원문에 존재하지 않는 창작 인용입니다",
            }
        ],
    )
    assert summary["created_candidates"] == 1
    candidate = (
        await session.execute(select(ExtractedPlaceCandidate))
    ).scalar_one()
    assert candidate.source_kind == EvidenceSourceKind.DESCRIPTION.value
    assert candidate.grounding_status == GroundingStatus.UNVERIFIED.value
    # grounding 실패여도 폐기하지 않고 검수 큐에 남긴다(관측용 상태만 기록).
    assert candidate.match_status == MatchStatus.NEEDS_REVIEW


async def test_description_candidate_not_autoconfirmed_and_queue_reason(session):
    # 자막 후보라면 자동확정됐을 조건(poi 이름 일치·verified·국내)을 모두 갖춰도
    # description 후보는 자동확정하지 않는다(needs_review 유지, 장소 미생성).
    session.add(
        YoutubeVideo(video_id="gv1", title="t", url="u", channel_id="gc1")
    )
    await session.commit()
    candidate = ExtractedPlaceCandidate(
        video_id="gv1",
        source_text="s",
        ai_place_name="월정리 카페",
        match_status=MatchStatus.NEEDS_REVIEW,
        source_kind=EvidenceSourceKind.DESCRIPTION.value,
        grounding_status=GroundingStatus.VERIFIED_RAW.value,
        is_domestic=True,
    )
    session.add(candidate)
    await session.commit()
    await session.refresh(candidate)

    decision = GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(
            latitude=33.5563,
            longitude=126.7958,
            place_name="월정리 카페",
            road_address="제주 구좌읍 ...",
            source="kakao_keyword",
        ),
        confidence=1.0,
        reason="single_result",
        candidate_count=1,
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)
    assert place is None
    await session.refresh(candidate)
    assert candidate.match_status == MatchStatus.NEEDS_REVIEW
    assert candidate.review_note == "description_only"
    assert candidate.feature_export_status == FeatureExportStatus.PENDING.value
    assert candidate.matched_place_id is None
    # 자동확정과 달리 장소가 만들어지지 않는다.
    places = (await session.execute(select(TravelPlace))).scalars().all()
    assert places == []

    # 파생 queue_reason은 description_only(지오코딩 사유가 single_result라 파생 로직의
    # 지오코딩 사유 케이스에 걸리지 않고 source_kind로 분류된다, T-182 계약).
    page = await place_service.list_unmatched_candidates_page(session)
    reasons = {item.candidate.id: item.queue_reason for item in page.items}
    assert reasons[candidate.id] == QueueReason.DESCRIPTION_ONLY


async def test_none_domestic_description_candidate_uses_foreign_bucket(session):
    # is_domestic None(미확인) description 후보는 review_note를 domestic_unverified로 두어
    # queue_reason이 FOREIGN 버킷으로 가야 한다(국내여부 미확인 fail-closed 신호를
    # description_only가 가리지 않도록, MINOR).
    session.add(YoutubeVideo(video_id="nd1", title="t", url="u", channel_id="ndc1"))
    await session.commit()
    candidate = ExtractedPlaceCandidate(
        video_id="nd1",
        source_text="s",
        ai_place_name="어딘가 카페",
        match_status=MatchStatus.NEEDS_REVIEW,
        source_kind=EvidenceSourceKind.DESCRIPTION.value,
        grounding_status=GroundingStatus.UNVERIFIED.value,
        is_domestic=None,
    )
    session.add(candidate)
    await session.commit()
    await session.refresh(candidate)

    decision = GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(
            latitude=37.5,
            longitude=127.0,
            place_name="어딘가 카페",
            road_address="서울 ...",
            source="kakao_keyword",
        ),
        confidence=1.0,
        reason="single_result",
        candidate_count=1,
    )
    place = await apply_geocode_to_candidate(session, candidate, decision)
    assert place is None
    await session.refresh(candidate)
    assert candidate.review_note == "domestic_unverified"
    page = await place_service.list_unmatched_candidates_page(session)
    reasons = {item.candidate.id: item.queue_reason for item in page.items}
    assert reasons[candidate.id] == QueueReason.FOREIGN


async def test_description_candidate_absent_from_feature_export(session, monkeypatch):
    # description 후보는 needs_review·PENDING·matched_place_id None이라 export ledger에
    # 오르지 않는다 — snapshot(upsert)에도, changes(tombstone/reject)에도 새지 않아야 한다.
    video = await _make_video(session, video_id="exp1", description=_LONG_DESCRIPTION)
    await _run_batch(
        session,
        monkeypatch,
        video,
        transcript_ok=False,
        pois=[
            {
                "official_name": "성심당 본점",
                "category_code": "01050100",
                "is_domestic": True,
                "evidence_quote": "성심당 본점에서 튀김소보로를 먹고",
            }
        ],
    )
    candidate = (
        await session.execute(select(ExtractedPlaceCandidate))
    ).scalar_one()
    assert candidate.source_kind == EvidenceSourceKind.DESCRIPTION.value
    export_id = f"ytpc_{candidate.id}"

    snapshot = await feature_export_service.get_snapshot(session)
    changes = await feature_export_service.get_changes(session)
    assert all(item["export_id"] != export_id for item in snapshot.items)
    assert all(item["export_id"] != export_id for item in changes.items)


async def test_transcript_reprocess_supersedes_description_candidate(
    session, monkeypatch
):
    # 자막 우선순위 역전 방지(MAJOR): run1 자막 실패→description 후보, run2 자막 복구
    # 재처리→transcript 후보가 생성되고 기존 미검수 description 후보는 supersede(soft delete).
    video = await _make_video(
        session, video_id="reproc1", description=_LONG_DESCRIPTION
    )
    await _run_batch(
        session,
        monkeypatch,
        video,
        transcript_ok=False,
        pois=[
            {
                "official_name": "성심당 본점",
                "category_code": "01050100",
                "is_domestic": True,
                "evidence_quote": "성심당 본점에서 튀김소보로를 먹고",
            }
        ],
    )
    description_candidate = (
        await session.execute(select(ExtractedPlaceCandidate))
    ).scalar_one()
    assert description_candidate.source_kind == EvidenceSourceKind.DESCRIPTION.value

    summary = await _run_batch(
        session,
        monkeypatch,
        video,
        transcript_ok=True,
        pois=[
            {
                "official_name": "성심당 본점",
                "category_code": "01050100",
                "is_domestic": True,
                "evidence_quote": "성심당 본점 빵이 맛있습니다",
            }
        ],
    )
    assert summary["created_candidates"] == 1

    await session.refresh(description_candidate)
    # 기존 description 후보는 supersede(soft delete)됨(hard delete 아님, 감사 흔적 보존).
    assert description_candidate.deleted_at is not None
    assert (
        description_candidate.deletion_reason
        == "superseded_by_higher_priority_source"
    )
    live = (
        (
            await session.execute(
                select(ExtractedPlaceCandidate).where(
                    ExtractedPlaceCandidate.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(live) == 1
    assert live[0].source_kind == EvidenceSourceKind.TRANSCRIPT.value


async def test_description_suppressed_when_transcript_candidate_exists(
    session, monkeypatch
):
    # 반대 방향(자막 우선): 기존 transcript 후보가 있으면 이후 자막 실패로 description
    # 경로에 들어가도 새 description 후보를 만들지 않는다(상위 소스 존재 시 억제).
    video = await _make_video(
        session, video_id="txfirst", description=_LONG_DESCRIPTION
    )
    await _run_batch(
        session,
        monkeypatch,
        video,
        transcript_ok=True,
        pois=[
            {
                "official_name": "성심당 본점",
                "category_code": "01050100",
                "is_domestic": True,
                "evidence_quote": "성심당 본점 빵이 맛있습니다",
            }
        ],
    )
    summary = await _run_batch(
        session,
        monkeypatch,
        video,
        transcript_ok=False,
        pois=[
            {
                "official_name": "성심당 본점",
                "is_domestic": True,
                "evidence_quote": "성심당 본점에서 튀김소보로를 먹고",
            }
        ],
    )
    assert summary["created_candidates"] == 0
    live = (
        (
            await session.execute(
                select(ExtractedPlaceCandidate).where(
                    ExtractedPlaceCandidate.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(live) == 1
    assert live[0].source_kind == EvidenceSourceKind.TRANSCRIPT.value


def test_build_description_text_boundaries():
    # description_raw=None, tags=None → 제목만.
    assert (
        _build_description_text(
            YoutubeVideo(
                video_id="b1",
                title="제목만",
                url="u",
                channel_id="c",
                description_raw=None,
                tags_json=None,
            )
        )
        == "제목만"
    )
    # tags가 리스트가 아니면(문자열 등) 무시하고 크래시하지 않는다.
    text_non_list_tags = _build_description_text(
        YoutubeVideo(
            video_id="b2",
            title="t",
            url="u",
            channel_id="c",
            description_raw="설명 본문",
            tags_json="notalist",
        )
    )
    assert "설명 본문" in text_non_list_tags
    assert "notalist" not in text_non_list_tags
    # title=None·description=None·tags=None → 빈 문자열(임계 미달로 자연 실패).
    assert (
        _build_description_text(
            YoutubeVideo(
                video_id="b3",
                title=None,
                url="u",
                channel_id="c",
                description_raw=None,
                tags_json=None,
            )
        )
        == ""
    )
