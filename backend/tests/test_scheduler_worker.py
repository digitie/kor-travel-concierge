"""APScheduler 단일 실행자 worker 테스트."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta

import pytest
from sqlalchemy import select

from ktc.models import (
    CrawlRun,
    RunState,
    SourceTarget,
    TravelPlace,
    YoutubeChannel,
    YoutubeVideo,
    YoutubeVideoAnalysisRun,
    utcnow,
)
from ktc.services import crawl_run_service, settings_service
from scheduler import worker


async def _fresh_run(session_factory, run_id):
    async with session_factory() as session:
        return await crawl_run_service.get_run(session, run_id)


async def _ok_handler(session, run):
    assert run.state == RunState.RUNNING
    return {"handled_run_id": run.id, "target_id": run.target_id}


async def _boom_handler(session, run):
    raise RuntimeError("handler boom")


async def _yielding_ok_handler(session, run):
    await asyncio.sleep(0)
    return {"handled_run_id": run.id}


def test_scheduler_jobstore_url_converts_asyncpg_to_psycopg():
    url = worker.scheduler_jobstore_url(
        "postgresql+asyncpg://addr:addr@localhost:5432/kor_travel_concierge"
    )
    assert url == "postgresql+psycopg://addr:addr@localhost:5432/kor_travel_concierge"


def test_scheduler_jobstore_url_prefers_explicit_url():
    url = worker.scheduler_jobstore_url(
        "postgresql+asyncpg://addr:addr@localhost:5432/kor_travel_concierge",
        "postgresql+psycopg://addr:addr@localhost:5432/scheduler_jobs",
    )
    assert url == "postgresql+psycopg://addr:addr@localhost:5432/scheduler_jobs"


async def test_run_once_claims_executes_and_marks_done(session, session_factory):
    run = await crawl_run_service.create_run(
        session,
        job_type="harvest",
        source="web",
        target_type="keyword",
        target_id="제주도 맛집",
        payload={"query": "제주도 맛집", "max_videos": 5},
    )

    executed_id = await worker.run_once(
        session_factory,
        handlers={"harvest": _ok_handler},
        heartbeat_interval_seconds=999,
    )

    assert executed_id == run.id
    refreshed = await _fresh_run(session_factory, run.id)
    assert refreshed.state == RunState.DONE
    assert refreshed.progress == 1.0
    assert refreshed.started_at is not None
    assert refreshed.heartbeat_at is not None
    assert refreshed.finished_at is not None
    assert '"handled_run_id"' in refreshed.result_json
    logs = crawl_run_service.load_status_logs(refreshed)
    assert any(log["message"] == "작업 실행 환경을 준비 중입니다." for log in logs)
    assert logs[-1]["message"] == "작업을 완료했습니다."


async def test_run_once_returns_none_when_no_pending(session_factory):
    assert await worker.run_once(session_factory) is None


async def test_run_once_marks_failed_when_handler_raises(session, session_factory):
    run = await crawl_run_service.create_run(
        session, job_type="harvest", source="web", target_type="keyword", target_id="부산"
    )

    executed_id = await worker.run_once(
        session_factory,
        handlers={"harvest": _boom_handler},
        heartbeat_interval_seconds=999,
    )

    assert executed_id == run.id
    refreshed = await _fresh_run(session_factory, run.id)
    assert refreshed.state == RunState.FAILED
    assert "handler boom" in refreshed.last_error
    assert "작업이 실패했습니다" in refreshed.current_message


async def test_execute_run_logs_heartbeat_task_exception(
    session, session_factory, monkeypatch, caplog
):
    async def broken_heartbeat_loop(*args, **kwargs):
        raise RuntimeError("heartbeat task boom")

    monkeypatch.setattr(worker, "_heartbeat_and_cancel_watch", broken_heartbeat_loop)
    caplog.set_level(logging.ERROR, logger=worker.logger.name)
    run = await crawl_run_service.create_run(
        session, job_type="harvest", source="web", target_type="keyword", target_id="부산"
    )

    executed_id = await worker.run_once(
        session_factory,
        handlers={"harvest": _yielding_ok_handler},
        heartbeat_interval_seconds=999,
    )

    assert executed_id == run.id
    refreshed = await _fresh_run(session_factory, run.id)
    assert refreshed.state == RunState.DONE
    assert "crawl_run heartbeat task 종료 중 예외" in caplog.text
    assert "heartbeat task boom" in caplog.text


async def test_execute_run_cooperative_cancel(session, session_factory):
    """cancel_requested가 걸린 running 작업은 watcher가 협조적 취소해 cancelled로 마감한다."""

    async def slow_handler(_session, _run):
        await asyncio.sleep(30)
        return {}

    run = await crawl_run_service.create_run(
        session, job_type="harvest", source="web", target_type="keyword", target_id="부산"
    )
    # 실행 중 중지 신호를 시뮬레이션: claim되면 running 전이 후 watcher가 신호를 본다.
    await crawl_run_service.request_cancel(session, run.id)

    executed_id = await worker.run_once(
        session_factory,
        handlers={"harvest": slow_handler},
        heartbeat_interval_seconds=0.05,
    )

    assert executed_id == run.id
    refreshed = await _fresh_run(session_factory, run.id)
    assert refreshed.state == RunState.CANCELLED
    assert refreshed.cancel_requested is True


async def test_run_once_marks_failed_for_unknown_job_type(session, session_factory):
    run = await crawl_run_service.create_run(session, job_type="unknown", source="web")

    executed_id = await worker.run_once(
        session_factory,
        handlers={"harvest": _ok_handler},
        heartbeat_interval_seconds=999,
    )

    assert executed_id == run.id
    refreshed = await _fresh_run(session_factory, run.id)
    assert refreshed.state == RunState.FAILED
    assert "지원하지 않는 job_type" in refreshed.last_error


async def test_run_once_requeues_stale_before_claim(session, session_factory):
    run = await crawl_run_service.create_run(
        session, job_type="harvest", source="web", target_type="keyword", target_id="서울"
    )
    await crawl_run_service.claim_next_pending(session)
    running = await crawl_run_service.get_run(session, run.id)
    running.heartbeat_at = utcnow() - timedelta(seconds=600)
    await session.commit()

    executed_id = await worker.run_once(
        session_factory,
        handlers={"harvest": _ok_handler},
        stale_threshold_seconds=1,
        max_retries=3,
        heartbeat_interval_seconds=999,
    )

    assert executed_id == run.id
    refreshed = await _fresh_run(session_factory, run.id)
    assert refreshed.state == RunState.DONE
    assert refreshed.retry_count == 1


async def test_run_once_isolates_stale_when_retries_exhausted(session, session_factory):
    run = await crawl_run_service.create_run(session, job_type="harvest", source="web")
    await crawl_run_service.claim_next_pending(session)
    running = await crawl_run_service.get_run(session, run.id)
    running.retry_count = 3
    running.heartbeat_at = utcnow() - timedelta(seconds=600)
    await session.commit()

    executed_id = await worker.run_once(
        session_factory,
        handlers={"harvest": _ok_handler},
        stale_threshold_seconds=1,
        max_retries=3,
        heartbeat_interval_seconds=999,
    )

    assert executed_id is None
    refreshed = await _fresh_run(session_factory, run.id)
    assert refreshed.state == RunState.FAILED
    assert "max retries" in refreshed.last_error


async def test_harvest_handler_passes_channel_target(monkeypatch, session):
    captured = {}

    async def fake_run_harvest(session, client, **kwargs):
        captured.update(kwargs)
        return {"ok": True, "target_type": "channel", "video_ids": ["v1"]}

    monkeypatch.setattr(worker, "run_harvest", fake_run_harvest)
    run = await crawl_run_service.create_run(
        session,
        job_type="harvest",
        source="web",
        target_type="channel",
        target_id="UC123",
        payload={"channel_id": "UC123"},
    )
    claimed = await crawl_run_service.claim_next_pending(session)

    result = await worker.harvest_handler(session, claimed)

    # 자막·POI는 묶음 poi_batch 작업으로 분리 enqueue된다.
    assert result["ok"] is True
    assert len(result["poi_batch_runs"]) == 1
    assert captured["channel_id"] == "UC123"
    assert captured["seed_keyword"] is None
    assert captured["playlist_id"] is None


async def test_harvest_handler_passes_playlist_target(monkeypatch, session):
    captured = {}

    async def fake_run_harvest(session, client, **kwargs):
        captured.update(kwargs)
        return {"ok": True, "target_type": "playlist", "video_ids": ["v1"]}

    monkeypatch.setattr(worker, "run_harvest", fake_run_harvest)
    run = await crawl_run_service.create_run(
        session,
        job_type="harvest",
        source="web",
        target_type="playlist",
        target_id="PL123",
        payload={"playlist_id": "PL123"},
    )
    claimed = await crawl_run_service.claim_next_pending(session)

    result = await worker.harvest_handler(session, claimed)

    assert result["ok"] is True
    assert len(result["poi_batch_runs"]) == 1
    assert captured["playlist_id"] == "PL123"
    assert captured["seed_keyword"] is None
    assert captured["channel_id"] is None


async def test_harvest_handler_enqueues_poi_batch_after_ingest(monkeypatch, session):
    captured = {}

    async def fake_run_harvest(session, client, **kwargs):
        captured["harvest"] = kwargs
        return {
            "discovered": 1,
            "inserted": 1,
            "updated": 0,
            "video_ids": ["v1"],
            "target_type": "keyword",
            "target_id": "부산 맛집",
        }

    monkeypatch.setattr(worker, "run_harvest", fake_run_harvest)
    run = await crawl_run_service.create_run(
        session,
        job_type="harvest",
        source="web",
        target_type="keyword",
        target_id="부산 맛집",
        payload={
            "query": "부산 맛집",
            "max_videos": 1,
            "default_category_code": "01050100",
        },
    )
    claimed = await crawl_run_service.claim_next_pending(session)

    result = await worker.harvest_handler(session, claimed)

    assert captured["harvest"]["seed_keyword"] == "부산 맛집"
    assert result["inserted"] == 1
    assert len(result["poi_batch_runs"]) == 1
    # poi_batch 작업이 실제로 생성되었는지 확인
    poi_runs = (
        await session.execute(
            select(CrawlRun).where(CrawlRun.job_type == "poi_batch")
        )
    ).scalars().all()
    assert len(poi_runs) == 1
    assert '"default_category_code": "01050100"' in (poi_runs[0].payload_json or "")


async def test_harvest_handler_skips_transcript_when_flagged(monkeypatch, session):
    async def fake_run_harvest(session, client, **kwargs):
        return {
            "inserted": 2,
            "video_ids": ["v1", "v2"],
            "target_type": "keyword",
            "target_id": "제주 6월 여행",
        }

    monkeypatch.setattr(worker, "run_harvest", fake_run_harvest)
    run = await crawl_run_service.create_run(
        session,
        job_type="harvest",
        source="web",
        target_type="keyword",
        target_id="제주 6월 여행",
        payload={"query": "제주 6월 여행", "max_videos": 2, "skip_transcript": True},
    )
    claimed = await crawl_run_service.claim_next_pending(session)

    result = await worker.harvest_handler(session, claimed)

    assert result["transcript_skipped"] is True
    assert result["video_ids"] == ["v1", "v2"]
    assert "poi_batch_runs" not in result
    poi_runs = (
        await session.execute(
            select(CrawlRun).where(CrawlRun.job_type == "poi_batch")
        )
    ).scalars().all()
    assert poi_runs == []


async def test_transcript_handler_enqueues_poi_batch(session):
    run = await crawl_run_service.create_run(
        session,
        job_type="transcript",
        source="web",
        target_type="keyword",
        target_id="제주 6월 여행",
        payload={"video_ids": ["v1", "v2"], "source_job_id": 1},
    )
    claimed = await crawl_run_service.claim_next_pending(session)

    result = await worker.transcript_handler(session, claimed)

    assert result["video_ids"] == ["v1", "v2"]
    assert len(result["poi_batch_runs"]) == 1  # ≤10 → 한 묶음
    poi_runs = (
        await session.execute(
            select(CrawlRun).where(CrawlRun.job_type == "poi_batch")
        )
    ).scalars().all()
    assert len(poi_runs) == 1


async def test_run_once_executes_deep_research_default_handler(
    monkeypatch, session, session_factory
):
    captured = {}

    def fake_llm(prompt):
        captured["prompt"] = prompt
        return json.dumps(
            {
                "detailed_research_content": "감천문화마을은 산복도로 풍경과 골목길 관람 동선이 핵심이다.",
                "gemini_enriched_description": "부산의 대표적인 산복도로 문화마을.",
                "source_notes": ["테스트용 Gemini 응답"],
            },
            ensure_ascii=False,
        )

    captured_model = {}

    def fake_make_llm(runtime):
        captured_model["model"] = runtime.model
        return fake_llm

    monkeypatch.setattr(worker.deep_research_service, "make_llm", fake_make_llm)
    place = TravelPlace(
        name="감천문화마을",
        description="부산 사하구의 골목 여행지",
        latitude=35.0975,
        longitude=129.0106,
    )
    session.add(place)
    await session.commit()
    await session.refresh(place)
    await settings_service.set_setting(session, "gemini_engine_version", "gemini-2.0-flash")
    run = await crawl_run_service.create_run(
        session,
        job_type="deep_research",
        source="web",
        target_type="place",
        target_id=str(place.place_id),
        payload={"prompt": "역사와 포토존 중심", "max_sources": 5},
    )

    executed_id = await worker.run_once(
        session_factory,
        heartbeat_interval_seconds=999,
    )

    assert executed_id == run.id
    assert "역사와 포토존 중심" in captured["prompt"]
    assert captured_model["model"] == "gemini-2.0-flash"
    refreshed = await _fresh_run(session_factory, run.id)
    assert refreshed.state == RunState.DONE
    assert refreshed.progress == 1.0
    assert "researched" in refreshed.result_json
    async with session_factory() as verify_session:
        refreshed_place = await verify_session.get(TravelPlace, place.place_id)
        assert "산복도로 풍경" in refreshed_place.detailed_research_content
        assert refreshed_place.gemini_enriched_description == "부산의 대표적인 산복도로 문화마을."
        assert refreshed_place.last_reviewed_at is not None


async def test_source_scan_handler_enqueues_due_harvest(session, session_factory):
    now = utcnow()
    target = SourceTarget(
        target_type="keyword",
        source_value="서울 맛집",
        is_active=True,
        next_crawl_at=now - timedelta(minutes=1),
        scan_interval_minutes=30,
        default_category_code="01050100",
    )
    session.add(target)
    await session.commit()
    await session.refresh(target)
    run = await crawl_run_service.create_run(
        session,
        job_type="source_scan",
        source="scheduler",
        target_type="source_targets",
        target_id="active",
        payload={"limit": 10, "default_interval_minutes": 60, "max_videos": 3},
    )

    executed_id = await worker.run_once(
        session_factory,
        heartbeat_interval_seconds=999,
    )

    assert executed_id == run.id
    refreshed_scan = await _fresh_run(session_factory, run.id)
    assert refreshed_scan.state == RunState.DONE
    async with session_factory() as verify_session:
        harvest = (
            await verify_session.execute(
                select(CrawlRun).where(
                    CrawlRun.job_type == "harvest",
                    CrawlRun.target_type == "keyword",
                    CrawlRun.target_id == "서울 맛집",
                )
            )
        ).scalar_one()
        refreshed_target = await verify_session.get(SourceTarget, target.id)
    assert harvest.state == RunState.PENDING
    assert '"max_videos": 3' in (harvest.payload_json or "")
    assert '"default_category_code": "01050100"' in (harvest.payload_json or "")
    assert refreshed_target.next_crawl_at is not None
    assert refreshed_target.next_crawl_at > now
    assert refreshed_target.scan_failure_count == 0


async def test_scan_due_targets_stops_at_max_runs(session):
    from ktc.services import source_scan_service

    now = utcnow()
    target = SourceTarget(
        target_type="keyword",
        source_value="한정 반복",
        is_active=True,
        next_crawl_at=now - timedelta(minutes=1),
        scan_interval_minutes=30,
        max_runs=1,
    )
    session.add(target)
    await session.commit()

    result = await source_scan_service.scan_due_targets(session, now=now, max_videos=3)
    assert result["enqueued_runs"] == 1
    await session.refresh(target)
    assert target.run_count == 1
    # 상한(1) 도달 → 더 이상 반복하지 않도록 비활성화
    assert target.is_active is False


async def test_source_scan_skips_existing_active_run(session, session_factory):
    now = utcnow()
    target = SourceTarget(
        target_type="playlist",
        source_value="PL123",
        is_active=True,
        next_crawl_at=now - timedelta(minutes=1),
    )
    session.add(target)
    await session.commit()
    scan = await crawl_run_service.create_run(
        session,
        job_type="source_scan",
        source="scheduler",
        target_type="source_targets",
        target_id="active",
        payload={"duplicate_backoff_minutes": 5},
    )
    await crawl_run_service.create_run(
        session,
        job_type="harvest",
        source="scheduler",
        target_type="playlist",
        target_id="PL123",
        payload={"playlist_id": "PL123"},
    )

    executed_id = await worker.run_once(
        session_factory,
        heartbeat_interval_seconds=999,
    )

    assert executed_id == scan.id
    async with session_factory() as verify_session:
        runs = (
            await verify_session.execute(
                select(CrawlRun).where(
                    CrawlRun.job_type == "harvest",
                    CrawlRun.target_type == "playlist",
                    CrawlRun.target_id == "PL123",
                )
            )
        ).scalars().all()
        refreshed_target = await verify_session.get(SourceTarget, target.id)
    assert len(runs) == 1
    assert refreshed_target.next_crawl_at is not None
    assert refreshed_target.next_crawl_at > now


async def test_video_analysis_handler_executes_pending_analysis_runs(
    monkeypatch, session, session_factory
):
    calls = []

    async def fake_url_summary(session, video, analysis_run):
        calls.append(("url_summary", analysis_run.id))
        analysis_run.state = "done"
        analysis_run.summary_text = "서울 여행 URL 요약"
        video.gemini_url_summary_json = {"summary": "서울 여행 URL 요약", "places": []}
        await session.commit()
        return {
            "analysis_run_id": analysis_run.id,
            "run_type": analysis_run.run_type,
            "state": "done",
        }

    async def fake_reconcile(session, video, analysis_run):
        calls.append(("reconcile", analysis_run.id))
        assert video.gemini_url_summary_json == {"summary": "서울 여행 URL 요약", "places": []}
        analysis_run.state = "done"
        analysis_run.summary_text = "서울 여행 비교 결과"
        await session.commit()
        return {
            "analysis_run_id": analysis_run.id,
            "run_type": analysis_run.run_type,
            "state": "done",
        }

    monkeypatch.setattr(
        worker.video_analysis_service,
        "run_url_summary_analysis",
        fake_url_summary,
    )
    monkeypatch.setattr(
        worker.video_analysis_service,
        "run_reconcile_analysis",
        fake_reconcile,
    )
    session.add(YoutubeChannel(channel_id="UC1", title="여행채널"))
    session.add(
        YoutubeVideo(
            video_id="v1",
            title="서울 여행",
            url="https://youtu.be/v1",
            channel_id="UC1",
        )
    )
    await session.commit()
    run = await crawl_run_service.create_run(
        session,
        job_type="video_analysis",
        source="scheduler",
        target_type="video",
        target_id="v1",
        payload={
            "video_id": "v1",
            "analysis_run_types": ["url_summary", "reconcile"],
        },
    )

    executed_id = await worker.run_once(
        session_factory,
        heartbeat_interval_seconds=999,
    )

    assert executed_id == run.id
    refreshed = await _fresh_run(session_factory, run.id)
    assert refreshed.state == RunState.DONE
    assert "created_analysis_runs" in (refreshed.result_json or "")
    assert '"executed_analysis_runs": 2' in (refreshed.result_json or "")
    assert [item[0] for item in calls] == ["url_summary", "reconcile"]
    async with session_factory() as verify_session:
        analysis_runs = (
            await verify_session.execute(
                select(YoutubeVideoAnalysisRun).where(
                    YoutubeVideoAnalysisRun.video_id == "v1"
                )
            )
        ).scalars().all()
    assert {item.run_type for item in analysis_runs} == {"url_summary", "reconcile"}
    assert {item.state for item in analysis_runs} == {"done"}


async def test_enqueue_source_scan_once_deduplicates(session_factory):
    first_id = await worker.enqueue_source_scan_once(session_factory)
    second_id = await worker.enqueue_source_scan_once(session_factory)

    assert first_id is not None
    assert second_id is None
    async with session_factory() as session:
        runs = (
            await session.execute(
                select(CrawlRun).where(CrawlRun.job_type == "source_scan")
            )
        ).scalars().all()
    assert len(runs) == 1


async def test_load_payload_rejects_invalid_json(session):
    run = await crawl_run_service.create_run(session, job_type="harvest", source="web")
    run.payload_json = "["
    await session.commit()

    with pytest.raises(ValueError, match="payload_json"):
        worker.load_payload(run)
