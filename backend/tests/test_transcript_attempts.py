"""transcript_attempts durable 기록·요약 캐시 파생 테스트 (T-164, 로드맵 PR-11, G7).

`transcript.py`가 반환한 provider별 시도(TranscriptOutcome.attempts)가
`transcript_attempts` 테이블에 durable하게 기록되고, `youtube_videos`의 요약 캐시
(transcript_source·transcript_failure_code)가 attempts에서 파생 갱신되는지 검증한다.
"""

from __future__ import annotations

import logging

from ktc.etl import batch_poi, postprocess_service, transcript_correction
from ktc.etl.media_store import InMemoryMediaStore
from ktc.etl.transcript import (
    TranscriptAttempt,
    TranscriptOutcome,
    TranscriptResult,
    TranscriptSegment,
)
from ktc.models import CrawlStatus, YoutubeVideo
from ktc.services import crawl_run_service
from scheduler import worker


# --- 직접 기록 계약 ----------------------------------------------------------


async def test_record_transcript_attempts_persists_rows_in_order(session):
    session.add(
        YoutubeVideo(video_id="rv1", title="t", url="u", channel_id="UCx")
    )
    run = await crawl_run_service.create_run(
        session, job_type="poi_batch", source="web"
    )
    await session.commit()

    attempts = [
        TranscriptAttempt(
            provider="youtube_transcript_api",
            outcome="blocked",
            sequence=1,
            duration_ms=120,
            detail="IP blocked",
        ),
        TranscriptAttempt(
            provider="yt_dlp",
            outcome="success",
            sequence=2,
            language="en",
            duration_ms=300,
            tool_version="2025.1.1",
        ),
    ]
    await crawl_run_service.record_transcript_attempts(
        session, video_id="rv1", attempts=attempts, run_id=run.id
    )

    rows = await crawl_run_service.list_transcript_attempts(session, "rv1")
    assert [r.sequence for r in rows] == [1, 2]
    assert [r.provider for r in rows] == ["youtube_transcript_api", "yt_dlp"]
    assert [r.outcome for r in rows] == ["blocked", "success"]
    assert all(r.run_id == run.id for r in rows)
    assert rows[0].duration_ms == 120
    assert rows[0].detail == "IP blocked"
    assert rows[1].language == "en"
    assert rows[1].tool_version == "2025.1.1"
    # started/finished는 시도 순서대로 단조 증가한다(duration 기준 배치).
    assert rows[0].started_at <= rows[1].started_at
    assert rows[0].finished_at is not None


async def test_record_transcript_attempts_noop_on_empty(session):
    await crawl_run_service.record_transcript_attempts(
        session, video_id="rv-none", attempts=[]
    )
    assert await crawl_run_service.list_transcript_attempts(session, "rv-none") == []


async def test_record_transcript_attempts_is_best_effort(session, caplog):
    """존재하지 않는 video_id(FK 위반)여도 예외를 삼키고 경고만 남긴다."""
    caplog.set_level(logging.WARNING, logger=crawl_run_service.logger.name)
    await crawl_run_service.record_transcript_attempts(
        session,
        video_id="nonexistent-vid",
        attempts=[TranscriptAttempt(provider="yt_dlp", outcome="no_captions", sequence=1)],
    )
    assert "transcript attempts 기록 실패" in caplog.text


async def test_make_transcript_attempt_recorder_binds_run(session):
    session.add(
        YoutubeVideo(video_id="rv2", title="t", url="u", channel_id="UCx")
    )
    run = await crawl_run_service.create_run(
        session, job_type="poi_batch", source="web"
    )
    await session.commit()

    recorder = crawl_run_service.make_transcript_attempt_recorder(session, run.id)
    await recorder(
        "rv2", [TranscriptAttempt(provider="yt_dlp", outcome="success", sequence=1)]
    )
    rows = await crawl_run_service.list_transcript_attempts(session, "rv2")
    assert len(rows) == 1 and rows[0].run_id == run.id


# --- poi_batch handler을 통한 end-to-end 기록·파생 --------------------------


def _patch_pipeline(monkeypatch, fetcher):
    """poi_batch handler 외부 의존을 fake로 바꾸고 transcript fetcher를 지정한다."""
    monkeypatch.setattr(
        postprocess_service, "_make_media_store", lambda settings: InMemoryMediaStore()
    )
    monkeypatch.setattr(postprocess_service, "_default_transcript_fetcher", fetcher)

    async def fake_correct(runtime, *, transcript, description=None, **kwargs):
        return transcript

    monkeypatch.setattr(transcript_correction, "correct_transcript", fake_correct)

    async def extract(runtime, items, **kwargs):
        return [
            batch_poi.BatchExtractedPOI(
                video_id=alias,
                official_name=f"부산역 국밥집 {alias}",
                category_code="01050100",
                is_domestic=True,
            )
            for alias, _ in items
        ]

    monkeypatch.setattr(batch_poi, "extract_batch", extract)

    async def fake_geocode(session_, candidates, *, status_reporter=None):
        return {"matched_places": 0, "needs_review_candidates": len(candidates)}

    monkeypatch.setattr(postprocess_service, "geocode_candidates", fake_geocode)


async def _run_poi_batch(session, video_id: str):
    run = await crawl_run_service.create_run(
        session, job_type="poi_batch", source="web", payload={"video_ids": [video_id]}
    )
    claimed = await crawl_run_service.claim_next_pending(session)
    result = await worker.poi_batch_handler(session, claimed)
    return run, result


async def test_poi_batch_records_attempts_and_derives_source_cache(monkeypatch, session):
    session.add(
        YoutubeVideo(
            video_id="tv1",
            title="부산 영상",
            url="https://youtu.be/tv1",
            channel_id="UC1",
            description_raw="부산역 국밥집",
        )
    )
    await session.commit()

    async def fetch_outcome(video_id):
        result = TranscriptResult(
            video_id=video_id,
            source="yt-dlp",
            language="en",
            segments=[TranscriptSegment(1.0, "부산역 국밥집에 왔습니다.")],
        )
        return TranscriptOutcome(
            result=result,
            attempts=[
                TranscriptAttempt(
                    provider="youtube_transcript_api",
                    outcome="blocked",
                    sequence=1,
                    duration_ms=120,
                ),
                TranscriptAttempt(
                    provider="yt_dlp",
                    outcome="success",
                    sequence=2,
                    result=result,
                    language="en",
                    duration_ms=300,
                ),
            ],
        )

    _patch_pipeline(monkeypatch, fetch_outcome)
    run, result = await _run_poi_batch(session, "tv1")

    assert result["processed_videos"] == 1
    rows = await crawl_run_service.list_transcript_attempts(session, "tv1")
    assert [r.outcome for r in rows] == ["blocked", "success"]
    assert [r.sequence for r in rows] == [1, 2]
    assert all(r.run_id == run.id for r in rows)

    video = await session.get(YoutubeVideo, "tv1")
    # 성공 provider가 요약 캐시로 파생 갱신되고 실패 코드는 비운다.
    assert video.transcript_source == "yt_dlp"
    assert video.transcript_failure_code is None


async def test_poi_batch_records_failure_cache_on_total_failure(monkeypatch, session):
    session.add(
        YoutubeVideo(
            video_id="tv2",
            title="자막 없는 영상",
            url="https://youtu.be/tv2",
            channel_id="UC1",
            description_raw="설명",
        )
    )
    await session.commit()

    async def fetch_fail(video_id):
        return TranscriptOutcome(
            result=None,
            attempts=[
                TranscriptAttempt(
                    provider="youtube_transcript_api",
                    outcome="blocked",
                    sequence=1,
                    duration_ms=100,
                ),
                TranscriptAttempt(
                    provider="yt_dlp",
                    outcome="no_captions",
                    sequence=2,
                    duration_ms=200,
                ),
                TranscriptAttempt(
                    provider="whisper",
                    outcome="disabled",
                    sequence=3,
                    duration_ms=1,
                ),
            ],
        )

    _patch_pipeline(monkeypatch, fetch_fail)
    run, result = await _run_poi_batch(session, "tv2")

    assert result["failed_videos"] == 1
    rows = await crawl_run_service.list_transcript_attempts(session, "tv2")
    assert [r.outcome for r in rows] == ["blocked", "no_captions", "disabled"]
    assert all(r.run_id == run.id for r in rows)

    video = await session.get(YoutubeVideo, "tv2")
    assert video.crawl_status == CrawlStatus.FAILED
    assert video.transcript_source is None
    # 대표 실패 코드는 우선순위상 no_captions(영상 자체에 대한 신호)를 노출한다.
    assert video.transcript_failure_code == "no_captions"
