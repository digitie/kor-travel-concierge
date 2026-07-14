"""durable stage event 기록·계측 테스트 (T-162, 로드맵 PR-34).

`crawl_run_stage_events`가 poi_batch(자막 fetch→교정→LLM 추출→지오코딩)와
harvest(검색→적재) handler에서 순서·elapsed·outcome과 함께 기록되는지 검증한다.
이 데이터는 §7 "poi_batch 단계별 소요" 지표와 T-172 게이트의 유일한 원천이다.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest

from ktc.etl import batch_poi, gemini_rate_limiter, postprocess_service, transcript_correction
from ktc.etl.media_store import InMemoryMediaStore
from ktc.etl.transcript import TranscriptAttempt, TranscriptResult, TranscriptSegment
from ktc.models import RunState, YoutubeVideo, utcnow
from ktc.services import crawl_run_service
from scheduler import worker


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        (1, False),
        ("true", False),
        ({"unexpected": True}, False),
        (None, False),
    ],
)
def test_quota_deferred_requires_explicit_boolean_true(value, expected):
    assert worker._is_quota_deferred({"quota_deferred": value}) is expected


async def test_record_stage_event_persists_and_computes_elapsed(session):
    run = await crawl_run_service.create_run(session, job_type="poi_batch", source="web")

    # started_at만 주면 elapsed_ms를 실측 시각차로 계산한다.
    started = utcnow() - timedelta(milliseconds=1500)
    await crawl_run_service.record_stage_event(
        session,
        run.id,
        stage="correction",
        outcome="success",
        provider="gemini-2.0-flash",
        item_ref="v1",
        started_at=started,
    )
    # elapsed_ms만 주면 started_at을 역산해 보존한다.
    await crawl_run_service.record_stage_event(
        session,
        run.id,
        stage="poi_extract",
        outcome="deferred",
        attempt=2,
        elapsed_ms=250,
        detail="일일 쿼터 보류",
    )

    events = await crawl_run_service.list_stage_events(session, run.id)
    assert [e.stage for e in events] == ["correction", "poi_extract"]
    first, second = events
    assert first.outcome == "success"
    assert first.provider == "gemini-2.0-flash"
    assert first.item_ref == "v1"
    assert first.elapsed_ms is not None and first.elapsed_ms >= 1400
    assert first.finished_at is not None
    assert second.outcome == "deferred"
    assert second.attempt == 2
    assert second.elapsed_ms == 250
    assert second.started_at < second.finished_at


async def test_record_stage_event_is_best_effort(session, caplog):
    """존재하지 않는 run(FK 위반)이어도 예외를 삼키고 경고만 남긴다 —
    관측 기록 실패가 본 작업을 죽이면 안 된다."""
    caplog.set_level(logging.WARNING, logger=crawl_run_service.logger.name)

    await crawl_run_service.record_stage_event(
        session, 999_999, stage="geocode", outcome="success"
    )

    assert await crawl_run_service.list_stage_events(session, 999_999) == []
    assert "stage event 기록 실패" in caplog.text


def _seed_video(session, video_id: str = "v1") -> None:
    session.add(
        YoutubeVideo(
            video_id=video_id,
            title=f"부산 영상 {video_id}",
            url=f"https://youtu.be/{video_id}",
            channel_id="UC1",
            description_raw="부산역 근처 국밥집 소개",
        )
    )


def _patch_poi_batch_pipeline(
    monkeypatch, *, extract=None, geocode_summary=None, whisper=None
):
    """poi_batch handler의 외부 의존(스토리지/자막/교정/LLM/지오코딩)을 fake로 바꾼다.

    T-172부터 caption/whisper fetcher가 분리 배선된다(`_default_caption_fetcher`/
    `_default_whisper_fetcher`). `whisper`를 안 주면 실제 auto 게이트 off와 동일한
    `disabled` 단건 stub을 쓴다 — caption 성공 시나리오에서는 애초에 호출되지 않는다.
    """
    monkeypatch.setattr(
        postprocess_service, "_make_media_store", lambda settings: InMemoryMediaStore()
    )

    async def fake_fetch(video_id: str) -> TranscriptResult:
        return TranscriptResult(
            video_id=video_id,
            source="transcript_api",
            segments=[TranscriptSegment(1.0, "부산역 국밥집에 왔습니다.")],
        )

    monkeypatch.setattr(postprocess_service, "_default_caption_fetcher", fake_fetch)

    async def _default_disabled_whisper(video_id: str) -> TranscriptAttempt:
        return TranscriptAttempt(provider="whisper", outcome="disabled", sequence=1)

    monkeypatch.setattr(
        postprocess_service,
        "_default_whisper_fetcher",
        whisper or _default_disabled_whisper,
    )

    async def fake_correct(runtime, *, transcript, description=None, **kwargs):
        return transcript

    monkeypatch.setattr(transcript_correction, "correct_transcript", fake_correct)

    if extract is None:

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
        if geocode_summary is not None:
            return geocode_summary
        return {"matched_places": 0, "needs_review_candidates": len(candidates)}

    monkeypatch.setattr(postprocess_service, "geocode_candidates", fake_geocode)


async def test_poi_batch_handler_records_stage_events_in_order(monkeypatch, session):
    _seed_video(session)
    await session.commit()

    async def extract_with_foreign(runtime, items, **kwargs):
        alias = items[0][0]
        return [
            batch_poi.BatchExtractedPOI(
                video_id=alias,
                official_name="부산역 국밥집",
                category_code="01050100",
                is_domestic=True,
            ),
            batch_poi.BatchExtractedPOI(
                video_id=alias,
                official_name="해외 국밥집",
                category_code="01050100",
                is_domestic=False,
            ),
        ]

    _patch_poi_batch_pipeline(
        monkeypatch,
        extract=extract_with_foreign,
        geocode_summary={
            "matched_places": 0,
            "needs_review_candidates": 0,
            "skipped_state_changed_candidates": 1,
        },
    )

    run = await crawl_run_service.create_run(
        session, job_type="poi_batch", source="web", payload={"video_ids": ["v1"]}
    )
    claimed = await crawl_run_service.claim_next_pending(session)

    result = await worker.poi_batch_handler(session, claimed)

    assert result["processed_videos"] == 1
    assert result["created_candidates"] == 2
    assert result["matched_places"] == 0
    assert result["needs_review_candidates"] == 1
    assert result["skipped_state_changed_candidates"] == 1
    assert result["created_candidates"] == (
        result["matched_places"]
        + result["needs_review_candidates"]
        + result["skipped_state_changed_candidates"]
    )
    events = await crawl_run_service.list_stage_events(session, run.id)
    # poi_batch_total은 handler가 process_video_batch 반환 뒤(finally)에 기록하므로 맨 끝.
    assert [e.stage for e in events] == [
        "transcript_fetch",
        "correction",
        "poi_extract",
        "geocode",
        "poi_batch_total",
    ]
    assert all(e.outcome == "success" for e in events)
    assert all(e.elapsed_ms is not None and e.elapsed_ms >= 0 for e in events)
    assert all(e.started_at is not None and e.finished_at is not None for e in events)
    fetch, correction, extract, geocode, total = events
    # stage 이벤트 provider는 canonical로 통일됐다(transcript_attempts와 조인 가능, T-164).
    assert fetch.provider == "youtube_transcript_api"
    assert fetch.item_ref == "v1"
    assert correction.item_ref == "v1"
    assert correction.provider  # LLM 모델명
    assert extract.attempt == 1
    assert "videos=1" in (extract.detail or "")
    assert "candidates=1" in (geocode.detail or "")
    assert "created_candidates=2" in (geocode.detail or "")
    assert "geocode_targets=1" in (geocode.detail or "")
    assert "foreign_needs_review=1" in (geocode.detail or "")
    assert "needs_review=1" in (geocode.detail or "")
    assert "skipped_state_changed_candidates=1" in (geocode.detail or "")
    refreshed_run = await crawl_run_service.get_run(session, run.id)
    messages = [
        item["message"] for item in crawl_run_service.load_status_logs(refreshed_run)
    ]
    assert (
        "POI 후보 처리 집계 — 전체 2개, 확정 0개, "
        "검수 필요 1개(해외 1개 포함), 사용자 처리로 건너뜀 1개입니다."
        in messages
    )
    # T-172 분모: 배치 총소요는 세부 stage 합 이상이어야 한다(사이 RustFS/commit 포함).
    assert "videos=1" in (total.detail or "")
    detail_sum = sum(e.elapsed_ms for e in (fetch, correction, extract, geocode))
    assert total.elapsed_ms >= detail_sum


async def test_poi_batch_handler_records_deferred_on_quota(monkeypatch, session):
    _seed_video(session, "v2")
    await session.commit()

    async def quota_extract(runtime, items, **kwargs):
        raise gemini_rate_limiter.GeminiQuotaExceeded("daily quota exhausted")

    _patch_poi_batch_pipeline(monkeypatch, extract=quota_extract)

    run = await crawl_run_service.create_run(
        session, job_type="poi_batch", source="web", payload={"video_ids": ["v2"]}
    )
    claimed = await crawl_run_service.claim_next_pending(session)

    result = await worker.poi_batch_handler(session, claimed)

    assert result["quota_deferred"] is True
    events = await crawl_run_service.list_stage_events(session, run.id)
    assert [e.stage for e in events] == [
        "transcript_fetch",
        "correction",
        "poi_extract",
        "poi_batch_total",
    ]
    poi_extract = next(e for e in events if e.stage == "poi_extract")
    assert poi_extract.outcome == "deferred"
    assert "쿼터" in (poi_extract.detail or "")
    # 보류 배치의 총소요도 deferred outcome으로 기록된다(T-172 분모, 비성공 표시).
    total = events[-1]
    assert total.stage == "poi_batch_total"
    assert total.outcome == "deferred"


async def test_poi_batch_handler_records_transcript_failure(monkeypatch, session):
    _seed_video(session, "v3")
    await session.commit()
    _patch_poi_batch_pipeline(monkeypatch)

    async def no_transcript(video_id: str):
        return None

    monkeypatch.setattr(postprocess_service, "_default_caption_fetcher", no_transcript)

    run = await crawl_run_service.create_run(
        session, job_type="poi_batch", source="web", payload={"video_ids": ["v3"]}
    )
    claimed = await crawl_run_service.claim_next_pending(session)

    result = await worker.poi_batch_handler(session, claimed)

    assert result["failed_videos"] == 1
    events = await crawl_run_service.list_stage_events(session, run.id)
    # 자막 실패로 배치가 비면 세부 stage는 fetch 실패 1건뿐이지만, 총소요 경계는
    # 여전히 기록된다(process_video_batch가 예외 없이 조기 return하므로 success).
    assert [e.stage for e in events] == ["transcript_fetch", "poi_batch_total"]
    assert events[0].outcome == "failure"
    assert events[0].item_ref == "v3"
    assert events[1].stage == "poi_batch_total"
    assert events[1].outcome == "success"


async def _claimed_harvest_run(session, target_id: str = "부산 맛집"):
    run = await crawl_run_service.create_run(
        session,
        job_type="harvest",
        source="web",
        target_type="keyword",
        target_id=target_id,
        payload={"query": target_id, "max_videos": 1},
    )
    claimed = await crawl_run_service.claim_next_pending(session)
    return run, claimed


async def test_harvest_handler_records_search_and_ingest_stages(monkeypatch, session):
    async def fake_run_harvest(session_, client, **kwargs):
        reporter = kwargs["stage_reporter"]
        await reporter("harvest_search", outcome="success", detail="video_candidates=1")
        await reporter("harvest_ingest", outcome="success", detail="inserted=1")
        return {
            "inserted": 1,
            "video_ids": ["v1"],
            "target_type": "keyword",
            "target_id": "부산 맛집",
        }

    monkeypatch.setattr(worker, "run_harvest", fake_run_harvest)
    run, claimed = await _claimed_harvest_run(session)

    result = await worker.harvest_handler(session, claimed)

    assert len(result["poi_batch_runs"]) == 1
    events = await crawl_run_service.list_stage_events(session, run.id)
    assert [e.stage for e in events] == ["harvest_search", "harvest_ingest"]
    assert all(e.outcome == "success" for e in events)
    assert all(e.elapsed_ms is not None and e.elapsed_ms >= 0 for e in events)


async def test_harvest_handler_attributes_ingest_failure_stage(monkeypatch, session):
    async def fake_run_harvest(session_, client, **kwargs):
        await kwargs["stage_reporter"]("harvest_search", outcome="success")
        raise RuntimeError("ingest boom")

    monkeypatch.setattr(worker, "run_harvest", fake_run_harvest)
    run, claimed = await _claimed_harvest_run(session)

    with pytest.raises(RuntimeError, match="ingest boom"):
        await worker.harvest_handler(session, claimed)

    events = await crawl_run_service.list_stage_events(session, run.id)
    assert [(e.stage, e.outcome) for e in events] == [
        ("harvest_search", "success"),
        ("harvest_ingest", "failure"),
    ]
    assert "ingest boom" in (events[-1].detail or "")


async def test_harvest_handler_attributes_search_failure_stage(monkeypatch, session):
    async def fake_run_harvest(session_, client, **kwargs):
        raise RuntimeError("search boom")

    monkeypatch.setattr(worker, "run_harvest", fake_run_harvest)
    run, claimed = await _claimed_harvest_run(session)

    with pytest.raises(RuntimeError, match="search boom"):
        await worker.harvest_handler(session, claimed)

    events = await crawl_run_service.list_stage_events(session, run.id)
    assert [(e.stage, e.outcome) for e in events] == [("harvest_search", "failure")]
    assert "search boom" in (events[0].detail or "")


async def test_stage_events_cascade_with_run_delete(session):
    """run 삭제 시 이벤트도 FK CASCADE로 함께 삭제된다."""
    run = await crawl_run_service.create_run(session, job_type="poi_batch", source="web")
    await crawl_run_service.record_stage_event(
        session, run.id, stage="geocode", outcome="success", elapsed_ms=10
    )
    assert len(await crawl_run_service.list_stage_events(session, run.id)) == 1

    db_run = await crawl_run_service.get_run(session, run.id)
    await session.delete(db_run)
    await session.commit()

    assert await crawl_run_service.list_stage_events(session, run.id) == []


async def test_run_state_transitions_do_not_touch_stage_parser(session):
    """status_log parser(UI 요약 view)는 계약 불변 — stage event가 status_log에
    끼어들지 않는다(C7: parser는 4필드 요약으로 유지)."""
    run = await crawl_run_service.create_run(session, job_type="poi_batch", source="web")
    await crawl_run_service.record_stage_event(
        session, run.id, stage="poi_extract", outcome="success", elapsed_ms=42
    )

    refreshed = await crawl_run_service.get_run(session, run.id)
    logs = crawl_run_service.load_status_logs(refreshed)
    assert all(set(log) == {"timestamp", "level", "message", "progress"} for log in logs)
    assert refreshed.state == RunState.PENDING
