"""프레임 비전/OCR 실험 경로 테스트 (T-173, 로드맵 PR-19).

게이트 off 완전 비활성, DeepSeek 엔진 no-op 가드, 영상당 비전 1콜 상한, VISUAL
grounding=not_applicable, geocode_service 자동확정 차단(recall source_kind 예외)
회귀, dedup 비대칭(transcript가 미검수 visual을 supersede)을 검증한다. 외부 의존
(yt-dlp 스트림 해석·FFmpeg·Gemini 비전 호출·지오코딩)은 전부 주입 fake로 대체한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select

from ktc.etl import frame_extraction, grounding as grounding_module, llm_client, postprocess_service, visual_extraction
from ktc.etl.batch_poi import BatchExtractedPOI
from ktc.etl.batch_poi_service import _persist_candidates
from ktc.etl.geocode_service import (
    apply_geocode_to_current_candidate as apply_geocode_to_candidate,
)
from ktc.etl.geocoding import GeocodeCandidate, GeocodeDecision
from ktc.etl.llm_client import LlmRuntime
from ktc.etl.media_store import InMemoryMediaStore
from ktc.etl.visual_extraction import VisualFrameOcrResult, build_visual_pois, compute_frame_timestamps
from ktc.models import (
    AssetType,
    EvidenceSourceKind,
    ExtractedPlaceCandidate,
    FeatureExportStatus,
    GroundingStatus,
    MatchStatus,
    MediaAsset,
    TravelPlace,
    YoutubeVideo,
)
from ktc.services import place_service
from ktc.services.place_service import QueueReason


@dataclass
class _SettingsStub:
    """`get_settings()` 대체 — 프레임/게이트 관련 필드만 최소로 흉내낸다."""

    VISUAL_EXTRACTION_ENABLED: bool = True
    VISUAL_FRAME_COUNT_DEFAULT: int = 6
    VISUAL_FRAME_MAX: int = 8
    VISUAL_MIN_DURATION_SECONDS: int = 60


class _ReverseMustNotRun:
    """recall 경로에서 reverse VWorld 접근을 즉시 실패시킨다(description 테스트와 동일 패턴)."""

    def __getattr__(self, name: str):
        raise AssertionError(f"visual 후보에서 reverse VWorld 호출 금지: {name}")


async def _fake_geocode(session_, candidates, *, status_reporter=None):
    """실제 provider 호출 없이 전부 needs_review로 집계한다(생성 경로만 격리)."""
    return {"matched_places": 0, "needs_review_candidates": len(candidates)}


# --- 1) 프레임 샘플링(길이별 개수, 순수 함수) -------------------------------------


def test_compute_frame_timestamps_evenly_spaced_with_boundary_trim():
    timestamps = compute_frame_timestamps(600, count=6)
    assert len(timestamps) == 6
    trim = 600 * 0.05
    assert timestamps[0] == trim
    assert timestamps[-1] == 600 - trim
    diffs = [b - a for a, b in zip(timestamps, timestamps[1:])]
    assert all(abs(d - diffs[0]) < 1e-9 for d in diffs)


def test_compute_frame_timestamps_skips_missing_or_zero_duration():
    assert compute_frame_timestamps(None, count=6) == []
    assert compute_frame_timestamps(0, count=6) == []
    assert compute_frame_timestamps(600, count=0) == []


async def test_select_visual_targets_filters_short_and_already_attempted(session, monkeypatch):
    monkeypatch.setattr(
        visual_extraction, "get_settings", lambda: _SettingsStub(VISUAL_MIN_DURATION_SECONDS=60)
    )
    session.add_all(
        [
            YoutubeVideo(
                video_id="short1",
                title="t",
                url="u",
                channel_id="c1",
                duration_seconds=30,
                transcript_failure_code="no_captions",
            ),
            YoutubeVideo(
                video_id="elig1",
                title="t",
                url="u",
                channel_id="c1",
                duration_seconds=600,
                transcript_failure_code="no_captions",
            ),
            YoutubeVideo(
                video_id="framed1",
                title="t",
                url="u",
                channel_id="c1",
                duration_seconds=600,
                transcript_failure_code="no_captions",
            ),
            YoutubeVideo(
                video_id="cand1",
                title="t",
                url="u",
                channel_id="c1",
                duration_seconds=600,
                transcript_failure_code="no_captions",
            ),
            YoutubeVideo(
                video_id="ok1",
                title="t",
                url="u",
                channel_id="c1",
                duration_seconds=600,
                transcript_source="youtube_transcript_api",
                transcript_failure_code=None,
            ),
        ]
    )
    await session.commit()
    session.add(
        MediaAsset(
            asset_type=AssetType.FRAME.value,
            video_id="framed1",
            bucket="b",
            object_key="k1",
            object_uri="u1",
        )
    )
    session.add(
        ExtractedPlaceCandidate(
            video_id="cand1",
            source_text="s",
            ai_place_name="x",
            match_status=MatchStatus.NEEDS_REVIEW,
            source_kind=EvidenceSourceKind.VISUAL.value,
        )
    )
    await session.commit()

    targets = await visual_extraction.select_visual_targets(session, limit=10)
    assert {v.video_id for v in targets} == {"elig1"}


# --- 2) 후보 격리(자동확정 차단) — 회귀 핵심 --------------------------------------


async def test_visual_candidate_not_autoconfirmed_and_queue_reason(session):
    """geocode_service의 VISUAL recall 예외가 없으면 이 테스트는 실패한다(자동확정됨)."""
    session.add(YoutubeVideo(video_id="vgv1", title="t", url="u", channel_id="vgc1"))
    await session.commit()
    candidate = ExtractedPlaceCandidate(
        video_id="vgv1",
        source_text="s",
        ai_place_name="영상 카페",
        match_status=MatchStatus.NEEDS_REVIEW,
        source_kind=EvidenceSourceKind.VISUAL.value,
        grounding_status=GroundingStatus.NOT_APPLICABLE.value,
        is_domestic=True,
    )
    session.add(candidate)
    await session.commit()
    await session.refresh(candidate)

    decision = GeocodeDecision(
        status="matched",
        candidate=GeocodeCandidate(
            latitude=35.1,
            longitude=129.0,
            place_name="영상 카페",
            road_address="부산 ...",
            source="kakao_keyword",
        ),
        confidence=1.0,
        reason="single_result",
        candidate_count=1,
    )
    place = await apply_geocode_to_candidate(
        session, candidate, decision, vworld=_ReverseMustNotRun()
    )
    assert place is None
    await session.refresh(candidate)
    assert candidate.match_status == MatchStatus.NEEDS_REVIEW
    assert candidate.review_note == "visual_only"
    assert candidate.feature_export_status == FeatureExportStatus.PENDING.value
    assert candidate.matched_place_id is None
    places = (await session.execute(select(TravelPlace))).scalars().all()
    assert places == []

    page = await place_service.list_unmatched_candidates_page(session)
    reasons = {item.candidate.id: item.queue_reason for item in page.items}
    assert reasons[candidate.id] == QueueReason.VISUAL_ONLY


async def test_visual_candidate_none_domestic_uses_foreign_bucket(session):
    session.add(YoutubeVideo(video_id="vnd1", title="t", url="u", channel_id="vndc1"))
    await session.commit()
    candidate = ExtractedPlaceCandidate(
        video_id="vnd1",
        source_text="s",
        ai_place_name="어딘가 카페",
        match_status=MatchStatus.NEEDS_REVIEW,
        source_kind=EvidenceSourceKind.VISUAL.value,
        grounding_status=GroundingStatus.NOT_APPLICABLE.value,
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


# --- 3) 플래그 off 완전 무개입 ----------------------------------------------------


async def test_run_visual_extraction_noop_when_flag_disabled(session, monkeypatch):
    monkeypatch.setattr(
        visual_extraction, "get_settings", lambda: _SettingsStub(VISUAL_EXTRACTION_ENABLED=False)
    )
    calls = {"resolver": 0, "extractor": 0, "vision": 0}

    def resolver(url):
        calls["resolver"] += 1
        return "https://stream/should-not-be-called"

    def extractor(stream_url, ts):
        calls["extractor"] += 1
        return b"\xff\xd8frame"

    async def vision_caller(parts):
        calls["vision"] += 1
        return json.dumps({"frames": []})

    session.add(
        YoutubeVideo(
            video_id="flagoff1",
            title="t",
            url="u",
            channel_id="c1",
            duration_seconds=600,
            transcript_failure_code="no_captions",
        )
    )
    await session.commit()

    summary = await visual_extraction.run_visual_extraction(
        session,
        InMemoryMediaStore(),
        runtime=LlmRuntime(model="gemini-2.5-flash"),
        stream_url_resolver=resolver,
        frame_extractor=extractor,
        vision_caller=vision_caller,
    )
    assert summary == {
        "skipped": "flag_disabled",
        "processed_videos": 0,
        "created_candidates": 0,
    }
    assert calls == {"resolver": 0, "extractor": 0, "vision": 0}
    candidates = (await session.execute(select(ExtractedPlaceCandidate))).scalars().all()
    assert candidates == []
    assets = (await session.execute(select(MediaAsset))).scalars().all()
    assert assets == []


# --- 4) DeepSeek 엔진 가드 --------------------------------------------------------


async def test_run_visual_extraction_noop_for_deepseek_engine(session, monkeypatch):
    monkeypatch.setattr(visual_extraction, "get_settings", lambda: _SettingsStub())

    async def fail_generate_multimodal(*args, **kwargs):
        raise AssertionError("DeepSeek 엔진에서 generate_multimodal이 호출되면 안 된다")

    monkeypatch.setattr(llm_client, "generate_multimodal", fail_generate_multimodal)

    summary = await visual_extraction.run_visual_extraction(
        session,
        InMemoryMediaStore(),
        runtime=LlmRuntime(model="deepseek-v4-flash"),
    )
    assert summary == {
        "skipped": "engine_not_gemini",
        "processed_videos": 0,
        "created_candidates": 0,
    }


# --- 5) 1콜 상한 + evidence 보존 --------------------------------------------------


async def test_run_visual_extraction_for_video_single_vision_call_and_evidence(
    session, monkeypatch
):
    monkeypatch.setattr(
        visual_extraction,
        "get_settings",
        lambda: _SettingsStub(VISUAL_FRAME_COUNT_DEFAULT=6, VISUAL_FRAME_MAX=8),
    )
    monkeypatch.setattr(postprocess_service, "geocode_candidates", _fake_geocode)

    video = YoutubeVideo(
        video_id="visv1",
        title="t",
        url="https://youtu.be/visv1",
        channel_id="visc1",
        duration_seconds=600,
        transcript_failure_code="no_captions",
    )
    session.add(video)
    await session.commit()
    await session.refresh(video)

    resolver_calls: list[str] = []
    extractor_calls: list[float] = []
    vision_calls: list[list[dict]] = []

    def resolver(url: str) -> str:
        resolver_calls.append(url)
        return "https://stream/fake"

    def extractor(stream_url: str, timestamp: float) -> bytes:
        extractor_calls.append(timestamp)
        return f"frame-{timestamp}".encode()

    async def vision_caller(parts: list[dict]) -> str:
        vision_calls.append(parts)
        return json.dumps(
            {
                "frames": [
                    {
                        "frame_index": 0,
                        "extracted_text": "환상 카페 간판이 보인다",
                        "place_name_candidates": ["환상 카페"],
                    }
                ]
            }
        )

    outcome = await visual_extraction.run_visual_extraction_for_video(
        session,
        InMemoryMediaStore(),
        video=video,
        runtime=LlmRuntime(model="gemini-2.5-flash"),
        stream_url_resolver=resolver,
        frame_extractor=extractor,
        vision_caller=vision_caller,
    )

    assert len(resolver_calls) == 1  # 스트림 URL은 영상당 1회만 확보
    assert len(extractor_calls) == 6  # VISUAL_FRAME_COUNT_DEFAULT
    assert len(vision_calls) == 1  # 비전은 영상당 정확히 1콜
    assert len(vision_calls[0]) == 6 + 1  # 프레임 6장 inline_data + text part 1개
    assert outcome["created_candidates"] == 1
    assert outcome["frames"] == 6

    candidates = (await session.execute(select(ExtractedPlaceCandidate))).scalars().all()
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source_kind == EvidenceSourceKind.VISUAL.value
    assert candidate.grounding_status == GroundingStatus.NOT_APPLICABLE.value
    assert candidate.match_status == MatchStatus.NEEDS_REVIEW

    evidence = candidate.provider_evidence_json["visual"]
    assert evidence["source"] == "video_frame_ocr"
    assert evidence["video_id"] == "visv1"
    assert len(evidence["frames"]) == 6
    assert {f["frame_index"] for f in evidence["frames"]} == set(range(6))

    stored_assets = (
        (
            await session.execute(
                select(MediaAsset).where(MediaAsset.asset_type == AssetType.FRAME.value)
            )
        )
        .scalars()
        .all()
    )
    assert len(stored_assets) == 6
    assert {f["asset_id"] for f in evidence["frames"]} == {a.id for a in stored_assets}


async def test_run_visual_extraction_for_video_clips_frame_count_to_max(session, monkeypatch):
    monkeypatch.setattr(
        visual_extraction,
        "get_settings",
        lambda: _SettingsStub(VISUAL_FRAME_COUNT_DEFAULT=20, VISUAL_FRAME_MAX=8),
    )
    monkeypatch.setattr(postprocess_service, "geocode_candidates", _fake_geocode)

    video = YoutubeVideo(
        video_id="visv2",
        title="t",
        url="https://youtu.be/visv2",
        channel_id="visc2",
        duration_seconds=1200,
        transcript_failure_code="no_captions",
    )
    session.add(video)
    await session.commit()
    await session.refresh(video)

    extractor_calls: list[float] = []
    vision_calls: list[list[dict]] = []

    async def vision_caller(parts: list[dict]) -> str:
        vision_calls.append(parts)
        return json.dumps({"frames": []})

    outcome = await visual_extraction.run_visual_extraction_for_video(
        session,
        InMemoryMediaStore(),
        video=video,
        runtime=LlmRuntime(model="gemini-2.5-flash"),
        stream_url_resolver=lambda url: "https://stream/fake",
        frame_extractor=lambda stream_url, ts: extractor_calls.append(ts) or f"f{ts}".encode(),
        vision_caller=vision_caller,
    )

    assert len(extractor_calls) == 8  # VISUAL_FRAME_MAX로 clip(설정 기본 20 무시)
    assert len(vision_calls) == 1
    assert len(vision_calls[0]) == 8 + 1
    assert outcome["frames"] == 8
    assert outcome["created_candidates"] == 0  # 이번 응답은 place_name_candidates 없음


# --- 6) grounding_status = not_applicable (VISUAL만 평가 생략, 회귀 없음 확인) ------


async def test_persist_candidates_visual_skips_grounding_transcript_still_evaluates(
    session, monkeypatch
):
    grounding_calls: list[str | None] = []
    original_evaluate = grounding_module.evaluate_transcript_grounding

    def spy_evaluate(evidence_quote, raw_text=None, *, index=None):
        grounding_calls.append(evidence_quote)
        return original_evaluate(evidence_quote, raw_text, index=index)

    # batch_poi_service는 `from ktc.etl import grounding`으로 같은 모듈 객체를 참조하므로
    # 이 patch가 `_persist_candidates` 호출에도 그대로 보인다.
    monkeypatch.setattr(grounding_module, "evaluate_transcript_grounding", spy_evaluate)

    video1 = YoutubeVideo(video_id="gv1", title="t", url="u", channel_id="c1")
    video2 = YoutubeVideo(video_id="gv2", title="t", url="u", channel_id="c1")
    session.add_all([video1, video2])
    await session.commit()
    await session.refresh(video1)
    await session.refresh(video2)

    visual_batch = {
        "video_001": {
            "video": video1,
            "transcript_source": "visual",
            "asset_id": None,
            "corrected": None,
            "raw_text": None,
            "source_kind": EvidenceSourceKind.VISUAL.value,
            "frames": [{"asset_id": 1, "timestamp_seconds": 30.0, "frame_index": 0}],
        }
    }
    visual_poi = BatchExtractedPOI(
        video_id="video_001",
        official_name="비전 카페",
        is_domestic=True,
        evidence_quote="비전 카페 간판이 화면에 보인다",
    )
    visual_created = await _persist_candidates(
        session, batch=visual_batch, pois=[visual_poi], normalized_default_category=None
    )
    await session.commit()

    assert grounding_calls == []  # VISUAL은 평가 자체를 건너뛴다
    assert len(visual_created) == 1
    assert visual_created[0].grounding_status == GroundingStatus.NOT_APPLICABLE.value
    assert visual_created[0].provider_evidence_json["visual"]["grounding_status"] == (
        GroundingStatus.NOT_APPLICABLE.value
    )

    transcript_batch = {
        "video_002": {
            "video": video2,
            "transcript_source": "youtube_transcript_api",
            "asset_id": None,
            "corrected": "성심당 본점에서 빵을 샀다",
            "raw_text": "[00:01] 성심당 본점에서 빵을 샀다",
        }
    }
    transcript_poi = BatchExtractedPOI(
        video_id="video_002",
        official_name="성심당 본점",
        is_domestic=True,
        evidence_quote="성심당 본점에서 빵을 샀다",
    )
    transcript_created = await _persist_candidates(
        session,
        batch=transcript_batch,
        pois=[transcript_poi],
        normalized_default_category=None,
    )
    await session.commit()

    assert grounding_calls == ["성심당 본점에서 빵을 샀다"]  # transcript는 회귀 없이 평가된다
    assert len(transcript_created) == 1
    assert transcript_created[0].grounding_status == GroundingStatus.VERIFIED_RAW.value


# --- 7) build_visual_pois: dedup + evidence 보존(순수 함수) ------------------------


def test_build_visual_pois_dedups_by_normalized_name_first_frame_wins():
    frames = [
        VisualFrameOcrResult(
            frame_index=0,
            extracted_text="스타 카페 간판",
            place_name_candidates=["스타 카페"],
        ),
        VisualFrameOcrResult(
            frame_index=1,
            extracted_text="스타 카페 다시",
            place_name_candidates=["스타카페", "옆집 분식"],
        ),
    ]
    pois = build_visual_pois(
        alias="video_001",
        frame_results=frames,
        frame_timestamps={0: 12.0, 1: 40.0},
    )
    names = {p.official_name for p in pois}
    assert names == {"스타 카페", "옆집 분식"}
    star_cafe = next(p for p in pois if p.official_name == "스타 카페")
    assert star_cafe.timestamp_start == frame_extraction.format_ffmpeg_timestamp(12.0)
    assert star_cafe.speaker_note == "스타 카페 간판"


# --- 8) dedup 비대칭: transcript가 미검수 visual 후보를 supersede -----------------


async def test_transcript_candidate_supersedes_unreviewed_visual_candidate(session):
    video = YoutubeVideo(video_id="dv1", title="t", url="u", channel_id="c1")
    session.add(video)
    await session.commit()
    await session.refresh(video)

    visual_batch = {
        "video_001": {
            "video": video,
            "transcript_source": "visual",
            "asset_id": None,
            "corrected": None,
            "raw_text": None,
            "source_kind": EvidenceSourceKind.VISUAL.value,
            "frames": [{"asset_id": 1, "timestamp_seconds": 10.0, "frame_index": 0}],
        }
    }
    visual_poi = BatchExtractedPOI(
        video_id="video_001",
        official_name="같은장소",
        is_domestic=True,
        evidence_quote="같은장소 간판이 보인다",
    )
    visual_created = await _persist_candidates(
        session, batch=visual_batch, pois=[visual_poi], normalized_default_category=None
    )
    await session.commit()
    assert len(visual_created) == 1
    visual_candidate_id = visual_created[0].id

    transcript_batch = {
        "video_001": {
            "video": video,
            "transcript_source": "youtube_transcript_api",
            "asset_id": None,
            "corrected": "같은장소에 방문했다",
            "raw_text": "[00:05] 같은장소에 방문했다",
        }
    }
    transcript_poi = BatchExtractedPOI(
        video_id="video_001",
        official_name="같은장소",
        is_domestic=True,
        evidence_quote="같은장소에 방문했다",
    )
    transcript_created = await _persist_candidates(
        session,
        batch=transcript_batch,
        pois=[transcript_poi],
        normalized_default_category=None,
    )
    await session.commit()

    assert len(transcript_created) == 1
    assert transcript_created[0].source_kind == EvidenceSourceKind.TRANSCRIPT.value

    refreshed_visual = await session.get(ExtractedPlaceCandidate, visual_candidate_id)
    assert refreshed_visual.deleted_at is not None
    assert refreshed_visual.deletion_reason == "superseded_by_higher_priority_source"

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
