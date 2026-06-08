"""APScheduler 단일 실행자 worker 테스트."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta

import pytest

from app.models import RunState, TravelPlace, utcnow
from app.services import crawl_run_service
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

    monkeypatch.setattr(worker, "_heartbeat_loop", broken_heartbeat_loop)
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
        return {"ok": True, "target_type": "channel"}

    async def fake_process_harvest_videos(session, **kwargs):
        return {"processed_videos": 0}

    monkeypatch.setattr(worker, "run_harvest", fake_run_harvest)
    monkeypatch.setattr(worker, "process_harvest_videos", fake_process_harvest_videos)
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

    assert result == {
        "ok": True,
        "target_type": "channel",
        "postprocess": {"processed_videos": 0},
    }
    assert captured["channel_id"] == "UC123"
    assert captured["seed_keyword"] is None
    assert captured["playlist_id"] is None


async def test_harvest_handler_passes_playlist_target(monkeypatch, session):
    captured = {}

    async def fake_run_harvest(session, client, **kwargs):
        captured.update(kwargs)
        return {"ok": True, "target_type": "playlist"}

    async def fake_process_harvest_videos(session, **kwargs):
        return {"processed_videos": 0}

    monkeypatch.setattr(worker, "run_harvest", fake_run_harvest)
    monkeypatch.setattr(worker, "process_harvest_videos", fake_process_harvest_videos)
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

    assert result == {
        "ok": True,
        "target_type": "playlist",
        "postprocess": {"processed_videos": 0},
    }
    assert captured["playlist_id"] == "PL123"
    assert captured["seed_keyword"] is None
    assert captured["channel_id"] is None


async def test_harvest_handler_runs_postprocess_after_video_ingest(monkeypatch, session):
    captured = {}

    async def fake_run_harvest(session, client, **kwargs):
        captured["harvest"] = kwargs
        return {
            "discovered": 1,
            "inserted": 1,
            "updated": 0,
            "target_type": "keyword",
            "target_id": "부산 맛집",
        }

    async def fake_process_harvest_videos(session, **kwargs):
        captured["postprocess"] = kwargs
        return {
            "processed_videos": 1,
            "summarized_videos": 1,
            "failed_videos": 0,
            "created_candidates": 1,
            "matched_places": 1,
            "needs_review_candidates": 0,
        }

    monkeypatch.setattr(worker, "run_harvest", fake_run_harvest)
    monkeypatch.setattr(worker, "process_harvest_videos", fake_process_harvest_videos)
    run = await crawl_run_service.create_run(
        session,
        job_type="harvest",
        source="web",
        target_type="keyword",
        target_id="부산 맛집",
        payload={"query": "부산 맛집", "max_videos": 1},
    )
    claimed = await crawl_run_service.claim_next_pending(session)

    result = await worker.harvest_handler(session, claimed)

    assert captured["harvest"]["seed_keyword"] == "부산 맛집"
    assert captured["postprocess"]["limit"] == 1
    assert result["inserted"] == 1
    assert result["postprocess"]["created_candidates"] == 1
    assert result["postprocess"]["matched_places"] == 1


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

    monkeypatch.setattr(worker.deep_research_service, "make_gemini_llm", lambda: fake_llm)
    place = TravelPlace(
        name="감천문화마을",
        description="부산 사하구의 골목 여행지",
        latitude=35.0975,
        longitude=129.0106,
    )
    session.add(place)
    await session.commit()
    await session.refresh(place)
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
    refreshed = await _fresh_run(session_factory, run.id)
    assert refreshed.state == RunState.DONE
    assert refreshed.progress == 1.0
    assert "researched" in refreshed.result_json
    async with session_factory() as verify_session:
        refreshed_place = await verify_session.get(TravelPlace, place.place_id)
        assert "산복도로 풍경" in refreshed_place.detailed_research_content
        assert refreshed_place.gemini_enriched_description == "부산의 대표적인 산복도로 문화마을."
        assert refreshed_place.last_reviewed_at is not None


async def test_load_payload_rejects_invalid_json(session):
    run = await crawl_run_service.create_run(session, job_type="harvest", source="web")
    run.payload_json = "["
    await session.commit()

    with pytest.raises(ValueError, match="payload_json"):
        worker.load_payload(run)
