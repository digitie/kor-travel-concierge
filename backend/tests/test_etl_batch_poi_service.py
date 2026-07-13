"""process_video_batch dedup 완화 통합 테스트 (T-167, 로드맵 PR-14 개정판, D6).

같은 영상 안의 변형 표기("성심당"/"성심당 본점")가 정규화 이름 기준으로 하나의 후보로
합쳐지고, 서로 다른 지점("성심당 대전역점")은 별개 후보로 유지되는지 검증한다. 외부
의존(자막 fetch·교정·LLM 추출·지오코딩·RustFS)은 fake로 대체한다.
"""

from __future__ import annotations

from sqlalchemy import select

from ktc.etl import (
    batch_poi,
    batch_poi_service,
    postprocess_service,
    transcript_correction,
)
from ktc.etl.llm_client import LlmRuntime
from ktc.etl.media_store import InMemoryMediaStore
from ktc.etl.transcript import TranscriptResult, TranscriptSegment
from ktc.models import ExtractedPlaceCandidate, YoutubeVideo


async def _run_single_video_batch(
    session, monkeypatch, official_names, *, video_id="vd1"
):
    async def fake_fetch(vid):
        return TranscriptResult(
            video_id=vid,
            source="transcript_api",
            segments=[TranscriptSegment(1.0, "성심당 본점 빵이 맛있습니다.")],
        )

    async def fake_correct(runtime, *, transcript, description=None, **kwargs):
        return transcript

    async def fake_extract(runtime, items, **kwargs):
        alias = items[0][0]
        return [
            batch_poi.BatchExtractedPOI(
                video_id=alias,
                official_name=name,
                category_code="01050100",
                is_domestic=True,
            )
            for name in official_names
        ]

    async def fake_geocode(session_, candidates, *, status_reporter=None):
        return {"matched_places": 0, "needs_review_candidates": len(candidates)}

    monkeypatch.setattr(transcript_correction, "correct_transcript", fake_correct)
    monkeypatch.setattr(batch_poi, "extract_batch", fake_extract)
    monkeypatch.setattr(postprocess_service, "geocode_candidates", fake_geocode)

    video = await session.get(YoutubeVideo, video_id)
    if video is None:
        video = YoutubeVideo(
            video_id=video_id,
            title="대전 빵집",
            url=f"https://youtu.be/{video_id}",
            channel_id="UC1",
        )
        session.add(video)
        await session.commit()
        await session.refresh(video)

    return await batch_poi_service.process_video_batch(
        session,
        InMemoryMediaStore(),
        videos=[video],
        runtime=LlmRuntime(model="gemini-2.5-flash"),
        transcript_fetcher=fake_fetch,
    )


async def test_dedup_collapses_branch_variants_same_video(session, monkeypatch):
    summary = await _run_single_video_batch(
        session, monkeypatch, ["성심당", "성심당 본점", "성심당 대전역점"]
    )
    names = sorted(
        (await session.execute(select(ExtractedPlaceCandidate.ai_place_name)))
        .scalars()
        .all()
    )
    # "성심당"/"성심당 본점"은 같은 정규화 이름이라 1개로 dedup, "성심당 대전역점"은 별개.
    assert summary["created_candidates"] == 2
    assert names == ["성심당", "성심당 대전역점"]


async def test_dedup_is_idempotent_across_reruns(session, monkeypatch):
    await _run_single_video_batch(session, monkeypatch, ["성심당 본점"])
    # 재실행에서 정규화 이름이 같은 "성심당"이 들어와도 새 후보를 만들지 않는다(멱등).
    await _run_single_video_batch(session, monkeypatch, ["성심당"])
    ids = (
        (await session.execute(select(ExtractedPlaceCandidate.id))).scalars().all()
    )
    assert len(ids) == 1
