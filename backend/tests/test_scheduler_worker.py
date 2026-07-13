"""APScheduler 단일 실행자 worker 테스트."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta

import pytest
from sqlalchemy import select

from ktc.models import (
    AuditStatus,
    CrawlRun,
    ExtractedPlaceCandidate,
    MatchStatus,
    RunState,
    SourceTarget,
    TravelPlace,
    VideoAnalysisRunState,
    VideoAnalysisRunType,
    YoutubeChannel,
    YoutubeVideo,
    YoutubeVideoAnalysisRun,
    utcnow,
)
from ktc.services import crawl_run_service, place_service, settings_service
from scheduler import worker


async def _fresh_run(session_factory, run_id):
    async with session_factory() as session:
        return await crawl_run_service.get_run(session, run_id)


async def _running_video_analysis_parent(session, *, video_id, run_types):
    run = await crawl_run_service.create_run(
        session,
        job_type="video_analysis",
        source="scheduler",
        target_type="video",
        target_id=video_id,
        payload={"video_id": video_id, "analysis_run_types": run_types},
    )
    claimed = await crawl_run_service.claim_next_pending(session)
    assert claimed is not None and claimed.id == run.id
    return run.id


async def _invoke_video_analysis_handler(session_factory, parent_id):
    async with session_factory() as worker_session:
        parent = await worker_session.get(CrawlRun, parent_id)
        assert parent is not None
        return await worker.video_analysis_handler(worker_session, parent)


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
    await crawl_run_service.create_run(
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
    await crawl_run_service.create_run(
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
    await crawl_run_service.create_run(
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
    await crawl_run_service.create_run(
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
    await crawl_run_service.create_run(
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
    # T-163: transcript splitter가 낳는 poi_batch child는 배치 레인이고
    # payload에 부모 job_id(source_job_id) lineage가 실린다.
    child = poi_runs[0]
    assert child.lane == worker.LANE_BATCH
    assert json.loads(child.payload_json)["source_job_id"] == claimed.id


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


@pytest.mark.parametrize(
    ("run_type", "runner_name"),
    [
        (VideoAnalysisRunType.URL_SUMMARY.value, "run_url_summary_analysis"),
        (VideoAnalysisRunType.RECONCILE.value, "run_reconcile_analysis"),
    ],
)
async def test_video_analysis_handler_supersedes_duplicate_pending_after_first_done(
    monkeypatch,
    session,
    session_factory,
    run_type,
    runner_name,
):
    """같은 종류 pending 2건은 첫 완료 뒤 둘째를 외부 호출 없이 terminal 처리한다."""
    from types import SimpleNamespace

    calls: list[int] = []

    async def fake_runner(worker_session, video, analysis_run):
        calls.append(analysis_run.id)
        analysis_run.state = VideoAnalysisRunState.DONE.value
        analysis_run.summary_text = "먼저 확정된 분석 결과"
        if run_type == VideoAnalysisRunType.URL_SUMMARY.value:
            video.gemini_url_summary_json = {
                "summary": "먼저 확정된 분석 결과",
                "places": [],
            }
        await worker_session.commit()
        return {
            "analysis_run_id": analysis_run.id,
            "run_type": analysis_run.run_type,
            "state": VideoAnalysisRunState.DONE.value,
            "stale_input": False,
        }

    monkeypatch.setattr(worker.video_analysis_service, runner_name, fake_runner)
    session.add(YoutubeChannel(channel_id=f"UC-duplicate-{run_type}", title="여행채널"))
    video = YoutubeVideo(
        video_id=f"v-duplicate-{run_type}",
        title="중복 분석 영상",
        url=f"https://youtu.be/v-duplicate-{run_type}",
        channel_id=f"UC-duplicate-{run_type}",
        gemini_url_summary_json=(
            {"summary": "기존 URL 요약", "places": []}
            if run_type == VideoAnalysisRunType.RECONCILE.value
            else None
        ),
    )
    session.add(video)
    await session.flush()
    first_run = YoutubeVideoAnalysisRun(
        video_id=video.video_id,
        run_type=run_type,
        state=VideoAnalysisRunState.PENDING.value,
    )
    second_run = YoutubeVideoAnalysisRun(
        video_id=video.video_id,
        run_type=run_type,
        state=VideoAnalysisRunState.PENDING.value,
    )
    session.add_all([first_run, second_run])
    await session.commit()
    first_run_id = first_run.id
    second_run_id = second_run.id

    fake_run = SimpleNamespace(
        target_type="video",
        target_id=video.video_id,
        payload_json=json.dumps(
            {"video_id": video.video_id, "analysis_run_types": [run_type]}
        ),
    )
    async with session_factory() as worker_session:
        result = await worker.video_analysis_handler(worker_session, fake_run)

    assert calls == [first_run_id]
    assert result["created_analysis_runs"] == 0
    assert result["executed_analysis_runs"] == 1
    assert result["superseded_analysis_runs"] == 1
    async with session_factory() as verify_session:
        first = await verify_session.get(YoutubeVideoAnalysisRun, first_run_id)
        second = await verify_session.get(YoutubeVideoAnalysisRun, second_run_id)
        assert first is not None and second is not None
        assert first.state == VideoAnalysisRunState.DONE.value
        assert second.state == VideoAnalysisRunState.FAILED.value
        assert second.finished_at is not None
        assert second.last_error is not None
        assert "superseded_by_completed_peer" in second.last_error


async def test_video_analysis_handler_retries_existing_stale_pending_run(
    monkeypatch,
    session,
    session_factory,
):
    """stale_input 분석 run은 소유권을 유지한 채 새 row 없이 즉시 재실행된다."""
    calls: list[int] = []

    async def fake_url_summary(session, video, analysis_run):
        calls.append(analysis_run.id)
        if len(calls) == 1:
            analysis_run.state = "running"
            analysis_run.last_error = "stale_input: 재실행 필요"
            await session.commit()
            return {
                "analysis_run_id": analysis_run.id,
                "run_type": analysis_run.run_type,
                "state": "running",
                "stale_input": True,
            }
        analysis_run.state = "done"
        analysis_run.last_error = None
        video.gemini_url_summary = "최신 입력으로 재실행한 요약"
        await session.commit()
        return {
            "analysis_run_id": analysis_run.id,
            "run_type": analysis_run.run_type,
            "state": "done",
            "stale_input": False,
        }

    monkeypatch.setattr(
        worker.video_analysis_service,
        "run_url_summary_analysis",
        fake_url_summary,
    )
    session.add(YoutubeChannel(channel_id="UC-stale-retry", title="여행채널"))
    video = YoutubeVideo(
        video_id="v-stale-retry",
        title="최신 영상",
        url="https://youtu.be/v-stale-retry",
        channel_id="UC-stale-retry",
    )
    session.add(video)
    await session.flush()
    analysis_run = YoutubeVideoAnalysisRun(
        video_id=video.video_id,
        run_type="url_summary",
        state="pending",
        last_error="stale_input: URL 분석 중 영상 입력이 변경됨",
    )
    session.add(analysis_run)
    await session.commit()
    analysis_run_id = analysis_run.id
    run = await crawl_run_service.create_run(
        session,
        job_type="video_analysis",
        source="scheduler",
        target_type="video",
        target_id=video.video_id,
        payload={
            "video_id": video.video_id,
            "analysis_run_types": ["url_summary"],
        },
    )

    assert await worker.run_once(
        session_factory,
        heartbeat_interval_seconds=999,
    ) == run.id

    refreshed = await _fresh_run(session_factory, run.id)
    assert refreshed.state == RunState.DONE
    assert '"created_analysis_runs": 0' in (refreshed.result_json or "")
    assert '"executed_analysis_runs": 1' in (refreshed.result_json or "")
    assert calls == [analysis_run_id, analysis_run_id]
    async with session_factory() as verify_session:
        rows = (
            await verify_session.execute(
                select(YoutubeVideoAnalysisRun).where(
                    YoutubeVideoAnalysisRun.video_id == video.video_id,
                    YoutubeVideoAnalysisRun.run_type == "url_summary",
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].id == analysis_run_id
        assert rows[0].state == "done"
        assert rows[0].last_error is None


@pytest.mark.parametrize("human_action", ["review", "audit"])
async def test_reconcile_bounded_retry_preserves_human_review_fields(
    monkeypatch,
    session,
    session_factory,
    human_action,
):
    """첫 reconcile 대기 중 사람 판정은 재시도 뒤에도 AI 의견보다 우선한다."""
    from types import SimpleNamespace

    video_id = f"v-reconcile-human-{human_action}"
    session.add(
        YoutubeChannel(
            channel_id=f"UC-reconcile-human-{human_action}",
            title="사람 검수 채널",
        )
    )
    video = YoutubeVideo(
        video_id=video_id,
        title="사람 검수 경합 영상",
        url=f"https://youtu.be/{video_id}",
        channel_id=f"UC-reconcile-human-{human_action}",
        transcript_summary="사람 검수 대상 자막 요약",
        gemini_url_summary_json={
            "summary": "URL 요약",
            "places": [{"name": "사람 검수 장소"}],
        },
    )
    session.add(video)
    await session.flush()
    candidate = ExtractedPlaceCandidate(
        video_id=video_id,
        source_text="사람 검수 원문 근거",
        ai_place_name="사람 검수 장소",
        match_status=(
            MatchStatus.NEEDS_REVIEW.value
            if human_action == "review"
            else MatchStatus.MATCHED.value
        ),
        review_note="사람 판정 전 메모",
        audit_status=(AuditStatus.PENDING.value if human_action == "audit" else None),
        provider_evidence_json={"transcript": {"segment": "보존할 원문 근거"}},
    )
    analysis_run = YoutubeVideoAnalysisRun(
        video_id=video_id,
        run_type=VideoAnalysisRunType.RECONCILE.value,
        state=VideoAnalysisRunState.PENDING.value,
    )
    session.add_all([candidate, analysis_run])
    await session.commit()
    candidate_id = candidate.id
    analysis_run_id = analysis_run.id

    first_llm_started = asyncio.Event()
    release_first_llm = asyncio.Event()
    llm_calls = 0

    def reconcile_payload(summary: str) -> str:
        return json.dumps(
            {
                "summary": summary,
                "places": [
                    {
                        "name": "사람 검수 장소",
                        "decision": "conflict",
                        "transcript_candidate_ids": [candidate_id],
                        "transcript_evidence": "자막 근거",
                        "url_evidence": "URL 근거",
                        "confidence_score": 0.3,
                        "needs_review_reason": "AI 재검토 의견",
                    }
                ],
                "conflicts": ["사람 판정과 독립인 AI 충돌 의견"],
                "overall_confidence": 0.3,
            },
            ensure_ascii=False,
        )

    async def controlled_llm(_prompt: str) -> str:
        nonlocal llm_calls
        llm_calls += 1
        if llm_calls == 1:
            first_llm_started.set()
            await release_first_llm.wait()
            return reconcile_payload("사람 판정 전에 생성한 stale 결과")
        return reconcile_payload("사람 판정 뒤 최신 입력으로 생성한 결과")

    real_runner = worker.video_analysis_service.run_reconcile_analysis

    async def controlled_runner(worker_session, worker_video, worker_analysis_run):
        return await real_runner(
            worker_session,
            worker_video,
            worker_analysis_run,
            llm=controlled_llm,
            model="gemini-test",
        )

    monkeypatch.setattr(
        worker.video_analysis_service,
        "run_reconcile_analysis",
        controlled_runner,
    )
    fake_run = SimpleNamespace(
        target_type="video",
        target_id=video_id,
        payload_json=json.dumps(
            {
                "video_id": video_id,
                "analysis_run_types": [VideoAnalysisRunType.RECONCILE.value],
            }
        ),
    )

    async def invoke_handler():
        async with session_factory() as worker_session:
            return await worker.video_analysis_handler(worker_session, fake_run)

    handler_task = asyncio.create_task(invoke_handler())
    try:
        await asyncio.wait_for(first_llm_started.wait(), timeout=5)
        async with session_factory() as reviewer_session:
            if human_action == "review":
                reviewed = await place_service.review_candidate(
                    reviewer_session,
                    candidate_id=candidate_id,
                    reviewed_by="human-reviewer",
                    review_note="사람이 작성한 최종 검수 메모",
                )
                assert reviewed.match_status == MatchStatus.NEEDS_REVIEW.value
            else:
                reviewed = await place_service.record_audit_result(
                    reviewer_session,
                    candidate_id=candidate_id,
                    accurate=True,
                    reviewed_by="human-auditor",
                    note="사람이 정확 판정",
                )
                assert reviewed.audit_status == AuditStatus.ACCURATE.value
        release_first_llm.set()
        result = await asyncio.wait_for(handler_task, timeout=5)
    finally:
        release_first_llm.set()
        if not handler_task.done():
            handler_task.cancel()
        await asyncio.gather(handler_task, return_exceptions=True)

    assert llm_calls == 2
    assert result["executed_analysis_runs"] == 1
    assert result["analysis_results"][0]["attempts"] == 2
    assert result["analysis_results"][0]["state"] == VideoAnalysisRunState.DONE.value
    async with session_factory() as verify_session:
        current = await verify_session.get(ExtractedPlaceCandidate, candidate_id)
        current_run = await verify_session.get(
            YoutubeVideoAnalysisRun, analysis_run_id
        )
        assert current is not None and current_run is not None
        assert current_run.state == VideoAnalysisRunState.DONE.value
        assert current.analysis_run_id is None
        assert current.provider_evidence_json["transcript"] == {
            "segment": "보존할 원문 근거"
        }
        assert current.provider_evidence_json["reconcile"][
            "needs_review_reason"
        ] == "AI 재검토 의견"
        if human_action == "review":
            assert current.match_status == MatchStatus.NEEDS_REVIEW.value
            assert current.reviewed_by == "human-reviewer"
            assert current.reviewed_at is not None
            assert current.review_note == "사람이 작성한 최종 검수 메모"
            assert current.audit_status is None
        else:
            assert current.match_status == MatchStatus.MATCHED.value
            assert current.review_note == "사람 판정 전 메모"
            assert current.audit_status == AuditStatus.ACCURATE.value
            assert current.audit_reviewed_by == "human-auditor"
            assert current.audit_reviewed_at is not None
            assert current.audit_note == "사람이 정확 판정"


async def test_concurrent_video_analysis_handlers_create_and_claim_once(
    monkeypatch,
    session,
    session_factory,
):
    """동일 video/run_type의 동시 handler는 analysis row와 외부 실행을 하나만 만든다."""
    from types import SimpleNamespace

    calls: list[int] = []
    llm_started = asyncio.Event()
    release_llm = asyncio.Event()

    async def paused_url_summary(session, video, analysis_run):
        calls.append(analysis_run.id)
        # production `_mark_running`과 같이 claim을 먼저 commit한 뒤 외부 I/O를 기다린다.
        await session.commit()
        llm_started.set()
        await release_llm.wait()
        analysis_run.state = "done"
        video.gemini_url_summary = "동시 실행 단일 결과"
        await session.commit()
        return {
            "analysis_run_id": analysis_run.id,
            "run_type": analysis_run.run_type,
            "state": "done",
            "stale_input": False,
        }

    monkeypatch.setattr(
        worker.video_analysis_service,
        "run_url_summary_analysis",
        paused_url_summary,
    )
    session.add(YoutubeChannel(channel_id="UC-analysis-race", title="여행채널"))
    session.add(
        YoutubeVideo(
            video_id="v-analysis-race",
            title="동시 분석 영상",
            url="https://youtu.be/v-analysis-race",
            channel_id="UC-analysis-race",
        )
    )
    await session.commit()
    fake_run = SimpleNamespace(
        target_type="video",
        target_id="v-analysis-race",
        payload_json=json.dumps(
            {
                "video_id": "v-analysis-race",
                "analysis_run_types": ["url_summary"],
            }
        ),
    )
    start = asyncio.Event()

    async def invoke_handler():
        async with session_factory() as worker_session:
            await start.wait()
            return await worker.video_analysis_handler(worker_session, fake_run)

    first = asyncio.create_task(invoke_handler())
    second = asyncio.create_task(invoke_handler())
    start.set()
    try:
        await asyncio.wait_for(llm_started.wait(), timeout=5)
        release_llm.set()
        results = await asyncio.wait_for(
            asyncio.gather(first, second),
            timeout=5,
        )
    finally:
        release_llm.set()
        for task in (first, second):
            if not task.done():
                task.cancel()
        await asyncio.gather(first, second, return_exceptions=True)

    assert len(calls) == 1
    assert sum(item["created_analysis_runs"] for item in results) == 1
    assert sum(item["executed_analysis_runs"] for item in results) == 1
    async with session_factory() as verify_session:
        rows = (
            await verify_session.execute(
                select(YoutubeVideoAnalysisRun).where(
                    YoutubeVideoAnalysisRun.video_id == "v-analysis-race",
                    YoutubeVideoAnalysisRun.run_type == "url_summary",
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].id == calls[0]
        assert rows[0].state == "done"


@pytest.mark.parametrize("late_outcome", ["success", "failure"])
async def test_rotated_parent_attempt_fences_late_analysis_owner(
    monkeypatch,
    session,
    session_factory,
    late_outcome,
):
    """재투입 claim이 같은 row를 완료하면 이전 owner의 성공·실패 모두 무효화한다."""
    video_id = f"v-analysis-owner-{late_outcome}"
    session.add(
        YoutubeChannel(
            channel_id=f"UC-analysis-owner-{late_outcome}",
            title="소유권 회전 채널",
        )
    )
    session.add(
        YoutubeVideo(
            video_id=video_id,
            title="소유권 회전 영상",
            url=f"https://youtu.be/{video_id}",
            channel_id=f"UC-analysis-owner-{late_outcome}",
        )
    )
    await session.commit()
    parent = await crawl_run_service.create_run(
        session,
        job_type="video_analysis",
        source="scheduler",
        target_type="video",
        target_id=video_id,
        payload={
            "video_id": video_id,
            "analysis_run_types": [VideoAnalysisRunType.URL_SUMMARY.value],
        },
    )
    claimed = await crawl_run_service.claim_next_pending(session)
    assert claimed is not None and claimed.id == parent.id
    parent_id = parent.id

    old_llm_started = asyncio.Event()
    release_old_llm = asyncio.Event()
    runner_calls = 0
    claim_snapshots: list[tuple[str | None, int | None]] = []
    real_runner = worker.video_analysis_service.run_url_summary_analysis

    async def old_llm(_prompt: str, _video_url: str) -> str:
        old_llm_started.set()
        await release_old_llm.wait()
        if late_outcome == "failure":
            raise RuntimeError("이전 owner의 늦은 LLM 실패")
        return json.dumps(
            {"summary": "이전 owner의 늦은 요약", "places": []},
            ensure_ascii=False,
        )

    async def new_llm(_prompt: str, _video_url: str) -> str:
        return json.dumps(
            {"summary": "새 owner가 확정한 요약", "places": []},
            ensure_ascii=False,
        )

    async def routed_runner(worker_session, video, analysis_run):
        nonlocal runner_calls
        runner_calls += 1
        claim_snapshots.append(
            (analysis_run.claim_token, analysis_run.owner_retry_count)
        )
        return await real_runner(
            worker_session,
            video,
            analysis_run,
            llm=old_llm if runner_calls == 1 else new_llm,
            model="gemini-test",
        )

    monkeypatch.setattr(
        worker.video_analysis_service,
        "run_url_summary_analysis",
        routed_runner,
    )

    async def invoke_handler():
        async with session_factory() as worker_session:
            current_parent = await worker_session.get(CrawlRun, parent_id)
            assert current_parent is not None
            return await worker.video_analysis_handler(worker_session, current_parent)

    old_task = asyncio.create_task(invoke_handler())
    try:
        await asyncio.wait_for(old_llm_started.wait(), timeout=5)
        async with session_factory() as rotate_session:
            current_parent = (
                await rotate_session.execute(
                    select(CrawlRun)
                    .where(CrawlRun.id == parent_id)
                    .with_for_update()
                )
            ).scalar_one()
            current_parent.retry_count += 1
            current_parent.state = RunState.RUNNING.value
            current_parent.heartbeat_at = utcnow()
            await rotate_session.commit()

        new_result = await asyncio.wait_for(invoke_handler(), timeout=5)
        release_old_llm.set()
        old_result = await asyncio.wait_for(old_task, timeout=5)
    finally:
        release_old_llm.set()
        if not old_task.done():
            old_task.cancel()
        await asyncio.gather(old_task, return_exceptions=True)

    assert runner_calls == 2
    assert claim_snapshots[0][0]
    assert claim_snapshots[1][0]
    assert claim_snapshots[0][0] != claim_snapshots[1][0]
    assert [item[1] for item in claim_snapshots] == [0, 1]
    assert new_result["executed_analysis_runs"] == 1
    assert new_result["analysis_results"][0]["state"] == "done"
    assert old_result["analysis_results"][0]["state"] == "done"
    assert old_result["analysis_results"][0]["superseded"] is True
    assert old_result["analysis_results"][0]["ownership_lost"] is True
    async with session_factory() as verify_session:
        rows = (
            await verify_session.execute(
                select(YoutubeVideoAnalysisRun).where(
                    YoutubeVideoAnalysisRun.video_id == video_id,
                    YoutubeVideoAnalysisRun.run_type
                    == VideoAnalysisRunType.URL_SUMMARY.value,
                )
            )
        ).scalars().all()
        current_video = await verify_session.get(YoutubeVideo, video_id)
        assert len(rows) == 1
        assert current_video is not None
        assert rows[0].state == VideoAnalysisRunState.DONE.value
        assert rows[0].summary_text == "새 owner가 확정한 요약"
        assert rows[0].summary_json["summary"] == "새 owner가 확정한 요약"
        assert rows[0].owner_crawl_run_id is None
        assert rows[0].owner_retry_count is None
        assert rows[0].claim_token is None
        assert rows[0].last_error is None
        assert current_video.gemini_url_summary == "새 owner가 확정한 요약"
        assert current_video.gemini_url_summary_json["summary"] == (
            "새 owner가 확정한 요약"
        )


async def test_parent_retry_pending_fences_old_url_before_child_reclaim(
    monkeypatch,
    session,
    session_factory,
):
    """parent 세대만 바뀌어도 이전 URL owner는 running child를 적용하지 못한다."""
    video_id = "v-analysis-parent-pending"
    session.add(YoutubeChannel(channel_id="UC-parent-pending", title="세대 전환 채널"))
    session.add(
        YoutubeVideo(
            video_id=video_id,
            title="세대 전환 영상",
            url=f"https://youtu.be/{video_id}",
            channel_id="UC-parent-pending",
        )
    )
    await session.commit()
    parent_id = await _running_video_analysis_parent(
        session,
        video_id=video_id,
        run_types=[VideoAnalysisRunType.URL_SUMMARY.value],
    )

    llm_started = asyncio.Event()
    release_llm = asyncio.Event()
    real_runner = worker.video_analysis_service.run_url_summary_analysis

    async def paused_llm(_prompt: str, _video_url: str) -> str:
        llm_started.set()
        await release_llm.wait()
        return json.dumps(
            {"summary": "이전 parent 세대의 늦은 요약", "places": []},
            ensure_ascii=False,
        )

    async def controlled_runner(worker_session, video, analysis_run):
        return await real_runner(
            worker_session,
            video,
            analysis_run,
            llm=paused_llm,
            model="gemini-test",
        )

    monkeypatch.setattr(
        worker.video_analysis_service,
        "run_url_summary_analysis",
        controlled_runner,
    )
    handler_task = asyncio.create_task(
        _invoke_video_analysis_handler(session_factory, parent_id)
    )
    old_claim_token = None
    try:
        await asyncio.wait_for(llm_started.wait(), timeout=5)
        async with session_factory() as observe_session:
            running_child = (
                await observe_session.execute(
                    select(YoutubeVideoAnalysisRun).where(
                        YoutubeVideoAnalysisRun.video_id == video_id,
                        YoutubeVideoAnalysisRun.run_type
                        == VideoAnalysisRunType.URL_SUMMARY.value,
                    )
                )
            ).scalar_one()
            assert running_child.state == VideoAnalysisRunState.RUNNING.value
            assert running_child.owner_crawl_run_id == parent_id
            assert running_child.owner_retry_count == 0
            assert running_child.claim_token is not None
            old_claim_token = running_child.claim_token

        async with session_factory() as rotate_session:
            parent = (
                await rotate_session.execute(
                    select(CrawlRun).where(CrawlRun.id == parent_id).with_for_update()
                )
            ).scalar_one()
            parent.retry_count += 1
            parent.state = RunState.PENDING.value
            await rotate_session.commit()
        release_llm.set()
        result = await asyncio.wait_for(handler_task, timeout=5)
    finally:
        release_llm.set()
        if not handler_task.done():
            handler_task.cancel()
        await asyncio.gather(handler_task, return_exceptions=True)

    assert result["ownership_lost"] is True
    assert result["ownership_lost_analysis_runs"] == 1
    assert result["analysis_results"][0]["ownership_lost"] is True
    assert result["analysis_results"][0]["state"] == (
        VideoAnalysisRunState.RUNNING.value
    )
    async with session_factory() as verify_session:
        parent = await verify_session.get(CrawlRun, parent_id)
        child = (
            await verify_session.execute(
                select(YoutubeVideoAnalysisRun).where(
                    YoutubeVideoAnalysisRun.video_id == video_id,
                    YoutubeVideoAnalysisRun.run_type
                    == VideoAnalysisRunType.URL_SUMMARY.value,
                )
            )
        ).scalar_one()
        video = await verify_session.get(YoutubeVideo, video_id)
        assert parent is not None and video is not None
        assert parent.state == RunState.PENDING.value
        assert parent.retry_count == 1
        assert child.state == VideoAnalysisRunState.RUNNING.value
        assert child.owner_crawl_run_id == parent_id
        assert child.owner_retry_count == 0
        assert child.claim_token == old_claim_token
        assert child.finished_at is None
        assert child.summary_text is None
        assert child.summary_json is None
        assert child.last_error is None
        assert video.gemini_url_summary is None
        assert video.gemini_url_summary_json is None


async def test_old_url_generation_cannot_claim_pending_reconcile_after_ownership_loss(
    monkeypatch,
    session,
    session_factory,
):
    """URL ownership를 잃은 handler는 같은 old generation으로 reconcile을 claim하지 않는다."""
    video_id = "v-analysis-split-brain"
    session.add(YoutubeChannel(channel_id="UC-split-brain", title="세대 분리 채널"))
    session.add(
        YoutubeVideo(
            video_id=video_id,
            title="세대 분리 영상",
            url=f"https://youtu.be/{video_id}",
            channel_id="UC-split-brain",
            gemini_url_summary="기존 세대가 확정한 URL 요약",
            gemini_url_summary_json={
                "summary": "기존 세대가 확정한 URL 요약",
                "places": [],
            },
        )
    )
    await session.commit()
    parent_id = await _running_video_analysis_parent(
        session,
        video_id=video_id,
        run_types=[
            VideoAnalysisRunType.URL_SUMMARY.value,
            VideoAnalysisRunType.RECONCILE.value,
        ],
    )

    llm_started = asyncio.Event()
    release_llm = asyncio.Event()
    reconcile_calls = 0
    real_url_runner = worker.video_analysis_service.run_url_summary_analysis

    async def paused_url_llm(_prompt: str, _video_url: str) -> str:
        llm_started.set()
        await release_llm.wait()
        return json.dumps(
            {"summary": "old generation URL 요약", "places": []},
            ensure_ascii=False,
        )

    async def controlled_url_runner(worker_session, video, analysis_run):
        return await real_url_runner(
            worker_session,
            video,
            analysis_run,
            llm=paused_url_llm,
            model="gemini-test",
        )

    async def forbidden_reconcile_runner(_session, _video, _analysis_run):
        nonlocal reconcile_calls
        reconcile_calls += 1
        raise AssertionError("old generation이 reconcile을 실행했습니다")

    monkeypatch.setattr(
        worker.video_analysis_service,
        "run_url_summary_analysis",
        controlled_url_runner,
    )
    monkeypatch.setattr(
        worker.video_analysis_service,
        "run_reconcile_analysis",
        forbidden_reconcile_runner,
    )
    handler_task = asyncio.create_task(
        _invoke_video_analysis_handler(session_factory, parent_id)
    )
    try:
        await asyncio.wait_for(llm_started.wait(), timeout=5)
        async with session_factory() as rotate_session:
            parent = (
                await rotate_session.execute(
                    select(CrawlRun).where(CrawlRun.id == parent_id).with_for_update()
                )
            ).scalar_one()
            parent.retry_count += 1
            parent.state = RunState.PENDING.value
            await rotate_session.commit()
        release_llm.set()
        result = await asyncio.wait_for(handler_task, timeout=5)
    finally:
        release_llm.set()
        if not handler_task.done():
            handler_task.cancel()
        await asyncio.gather(handler_task, return_exceptions=True)

    assert reconcile_calls == 0
    assert result["ownership_lost"] is True
    assert result["executed_analysis_runs"] == 1
    assert result["analysis_results"][0]["run_type"] == (
        VideoAnalysisRunType.URL_SUMMARY.value
    )
    assert result["analysis_results"][0]["ownership_lost"] is True
    async with session_factory() as verify_session:
        rows = list(
            (
                await verify_session.execute(
                    select(YoutubeVideoAnalysisRun)
                    .where(YoutubeVideoAnalysisRun.video_id == video_id)
                    .order_by(YoutubeVideoAnalysisRun.id)
                )
            )
            .scalars()
            .all()
        )
        video = await verify_session.get(YoutubeVideo, video_id)
        assert video is not None
        assert len(rows) == 2
        by_type = {row.run_type: row for row in rows}
        url_run = by_type[VideoAnalysisRunType.URL_SUMMARY.value]
        reconcile_run = by_type[VideoAnalysisRunType.RECONCILE.value]
        assert url_run.state == VideoAnalysisRunState.RUNNING.value
        assert url_run.owner_crawl_run_id == parent_id
        assert url_run.owner_retry_count == 0
        assert url_run.claim_token is not None
        assert reconcile_run.state == VideoAnalysisRunState.PENDING.value
        assert reconcile_run.owner_crawl_run_id is None
        assert reconcile_run.owner_retry_count is None
        assert reconcile_run.claim_token is None
        assert video.gemini_url_summary == "기존 세대가 확정한 URL 요약"
        assert video.gemini_url_summary_json["summary"] == (
            "기존 세대가 확정한 URL 요약"
        )
        assert video.reconciled_summary_json is None


async def test_done_url_without_pending_allows_normal_reconcile_completion(
    monkeypatch,
    session,
    session_factory,
):
    """URL DONE/no-pending 정상 경로가 ORM identity를 expire하지 않고 reconcile을 잇는다."""
    video_id = "v-analysis-done-url-reconcile"
    session.add(YoutubeChannel(channel_id="UC-done-url", title="정상 이어하기 채널"))
    video = YoutubeVideo(
        video_id=video_id,
        title="URL 완료 뒤 reconcile 영상",
        url=f"https://youtu.be/{video_id}",
        channel_id="UC-done-url",
        gemini_url_summary="이미 완료된 URL 요약",
        gemini_url_summary_json={
            "summary": "이미 완료된 URL 요약",
            "places": [],
        },
    )
    url_run = YoutubeVideoAnalysisRun(
        video_id=video_id,
        run_type=VideoAnalysisRunType.URL_SUMMARY.value,
        state=VideoAnalysisRunState.DONE.value,
        summary_text="이미 완료된 URL 요약",
        summary_json={"summary": "이미 완료된 URL 요약", "places": []},
        finished_at=utcnow(),
    )
    reconcile_run = YoutubeVideoAnalysisRun(
        video_id=video_id,
        run_type=VideoAnalysisRunType.RECONCILE.value,
        state=VideoAnalysisRunState.PENDING.value,
    )
    session.add_all([video, url_run, reconcile_run])
    await session.commit()
    url_run_id = url_run.id
    reconcile_run_id = reconcile_run.id
    parent_id = await _running_video_analysis_parent(
        session,
        video_id=video_id,
        run_types=[
            VideoAnalysisRunType.URL_SUMMARY.value,
            VideoAnalysisRunType.RECONCILE.value,
        ],
    )

    url_calls = 0
    reconcile_calls = 0
    real_reconcile_runner = worker.video_analysis_service.run_reconcile_analysis

    async def forbidden_url_runner(_session, _video, _analysis_run):
        nonlocal url_calls
        url_calls += 1
        raise AssertionError("DONE URL 분석을 다시 실행했습니다")

    async def reconcile_llm(_prompt: str) -> str:
        return json.dumps(
            {
                "summary": "정상적으로 완료한 reconcile 요약",
                "places": [],
                "conflicts": [],
            },
            ensure_ascii=False,
        )

    async def controlled_reconcile_runner(worker_session, video, analysis_run):
        nonlocal reconcile_calls
        reconcile_calls += 1
        return await real_reconcile_runner(
            worker_session,
            video,
            analysis_run,
            llm=reconcile_llm,
            model="gemini-test",
        )

    monkeypatch.setattr(
        worker.video_analysis_service,
        "run_url_summary_analysis",
        forbidden_url_runner,
    )
    monkeypatch.setattr(
        worker.video_analysis_service,
        "run_reconcile_analysis",
        controlled_reconcile_runner,
    )

    result = await _invoke_video_analysis_handler(session_factory, parent_id)

    assert url_calls == 0
    assert reconcile_calls == 1
    assert result["ownership_lost"] is False
    assert result["executed_analysis_runs"] == 1
    assert result["analysis_results"][0]["run_type"] == (
        VideoAnalysisRunType.RECONCILE.value
    )
    assert result["analysis_results"][0]["state"] == (
        VideoAnalysisRunState.DONE.value
    )
    async with session_factory() as verify_session:
        current_url_run = await verify_session.get(
            YoutubeVideoAnalysisRun, url_run_id
        )
        current_reconcile_run = await verify_session.get(
            YoutubeVideoAnalysisRun, reconcile_run_id
        )
        current_video = await verify_session.get(YoutubeVideo, video_id)
        assert current_url_run is not None
        assert current_reconcile_run is not None
        assert current_video is not None
        assert current_url_run.state == VideoAnalysisRunState.DONE.value
        assert current_url_run.summary_text == "이미 완료된 URL 요약"
        assert current_reconcile_run.state == VideoAnalysisRunState.DONE.value
        assert current_reconcile_run.summary_text == "정상적으로 완료한 reconcile 요약"
        assert current_video.gemini_url_summary == "이미 완료된 URL 요약"
        assert current_video.reconciled_summary == "정상적으로 완료한 reconcile 요약"


async def test_video_analysis_handler_reclaims_expired_running_lease(
    monkeypatch,
    session,
    session_factory,
):
    """worker 중단으로 오래된 running row가 남아도 같은 row를 회수해 완료한다."""
    from types import SimpleNamespace

    calls: list[int] = []

    async def fake_url_summary(worker_session, video, analysis_run):
        calls.append(analysis_run.id)
        assert analysis_run.state == "running"
        analysis_run.state = "done"
        analysis_run.last_error = None
        video.gemini_url_summary = "lease 회수 뒤 생성한 요약"
        await worker_session.commit()
        return {
            "analysis_run_id": analysis_run.id,
            "run_type": analysis_run.run_type,
            "state": "done",
            "stale_input": False,
        }

    monkeypatch.setattr(
        worker.video_analysis_service,
        "run_url_summary_analysis",
        fake_url_summary,
    )
    session.add(YoutubeChannel(channel_id="UC-analysis-reclaim", title="여행채널"))
    video = YoutubeVideo(
        video_id="v-analysis-reclaim",
        title="lease 회수 영상",
        url="https://youtu.be/v-analysis-reclaim",
        channel_id="UC-analysis-reclaim",
    )
    session.add(video)
    await session.flush()
    analysis_run = YoutubeVideoAnalysisRun(
        video_id=video.video_id,
        run_type="url_summary",
        state="running",
        started_at=utcnow()
        - timedelta(seconds=worker.VIDEO_ANALYSIS_RUNNING_LEASE_SECONDS + 1),
        last_error="worker가 중단되기 전 상태",
    )
    session.add(analysis_run)
    await session.commit()
    analysis_run_id = analysis_run.id

    fake_run = SimpleNamespace(
        target_type="video",
        target_id=video.video_id,
        payload_json=json.dumps(
            {
                "video_id": video.video_id,
                "analysis_run_types": ["url_summary"],
            }
        ),
    )
    async with session_factory() as worker_session:
        result = await worker.video_analysis_handler(worker_session, fake_run)

    assert result["created_analysis_runs"] == 0
    assert result["executed_analysis_runs"] == 1
    assert calls == [analysis_run_id]
    async with session_factory() as verify_session:
        current = await verify_session.get(YoutubeVideoAnalysisRun, analysis_run_id)
        assert current is not None
        assert current.state == "done"
        assert current.last_error is None


async def test_video_analysis_runner_apply_exception_marks_run_failed(
    monkeypatch,
    session,
    session_factory,
):
    """service apply 예외가 나도 분석 row를 running에 영구 고착시키지 않는다."""
    from types import SimpleNamespace

    async def broken_apply(worker_session, _video, analysis_run):
        # 외부 호출 시작을 확정한 production service와 같은 commit 경계를 만든다.
        analysis_run.started_at = utcnow()
        await worker_session.commit()
        raise RuntimeError("apply transaction failed")

    monkeypatch.setattr(
        worker.video_analysis_service,
        "run_url_summary_analysis",
        broken_apply,
    )
    session.add(YoutubeChannel(channel_id="UC-analysis-apply", title="여행채널"))
    session.add(
        YoutubeVideo(
            video_id="v-analysis-apply",
            title="apply 실패 영상",
            url="https://youtu.be/v-analysis-apply",
            channel_id="UC-analysis-apply",
        )
    )
    await session.commit()
    fake_run = SimpleNamespace(
        target_type="video",
        target_id="v-analysis-apply",
        payload_json=json.dumps(
            {
                "video_id": "v-analysis-apply",
                "analysis_run_types": ["url_summary"],
            }
        ),
    )

    async with session_factory() as worker_session:
        with pytest.raises(RuntimeError, match="apply transaction failed"):
            await worker.video_analysis_handler(worker_session, fake_run)

    async with session_factory() as verify_session:
        rows = (
            await verify_session.execute(
                select(YoutubeVideoAnalysisRun).where(
                    YoutubeVideoAnalysisRun.video_id == "v-analysis-apply",
                    YoutubeVideoAnalysisRun.run_type == "url_summary",
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].state == "failed"
        assert rows[0].last_error == "runner_apply_failed: apply transaction failed"


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


# ---------------------------------------------------------------------------
# T-163: 워커 레인 job 등록 (구 job id 제거·레인당 1 job)
# ---------------------------------------------------------------------------


class _FakeScheduler:
    """add_job/remove_job 호출만 기록하는 경량 스케줄러 더블(APScheduler 미설치 환경).

    실제 AsyncIOScheduler는 이벤트 루프·apscheduler 의존이 필요하므로, 등록 로직만
    검증하려고 호출을 캡처한다. remove_job은 없는 id면 실제처럼 예외를 던진다.
    """

    def __init__(self, existing_job_ids=()):
        self.jobs: dict[str, dict] = {}
        self.removed: list[str] = []
        self._existing = set(existing_job_ids)

    def remove_job(self, job_id, jobstore=None):
        if job_id in self.jobs or job_id in self._existing:
            self.removed.append(job_id)
            self.jobs.pop(job_id, None)
            self._existing.discard(job_id)
            return
        raise LookupError(f"job not found: {job_id}")

    def add_job(self, func, trigger=None, **kwargs):
        self.jobs[kwargs["id"]] = {"func": func, "trigger": trigger, **kwargs}


def _fake_settings(*, source_scan_enabled=True, feature_export_reconcile_enabled=True):
    from types import SimpleNamespace

    return SimpleNamespace(
        SCHEDULER_POLL_INTERVAL_SECONDS=5,
        SOURCE_SCAN_ENABLED=source_scan_enabled,
        SOURCE_SCAN_INTERVAL_SECONDS=60,
        FEATURE_EXPORT_RECONCILE_ENABLED=feature_export_reconcile_enabled,
        FEATURE_EXPORT_RECONCILE_INTERVAL_SECONDS=3600,
    )


def test_register_worker_jobs_drops_legacy_and_registers_two_lanes():
    sentinel_factory = object()
    scheduler = _FakeScheduler(existing_job_ids={worker.LEGACY_WORKER_JOB_ID})

    worker.register_worker_jobs(
        scheduler,
        session_factory=sentinel_factory,
        handlers={},
        use_persistent_jobstore=False,
        settings=_fake_settings(),
    )

    # 구 단일 워커 job은 제거된다(lane 미지정 run_once 잔존 방지).
    assert worker.LEGACY_WORKER_JOB_ID in scheduler.removed
    assert worker.LEGACY_WORKER_JOB_ID not in scheduler.jobs

    assert set(scheduler.jobs) == {
        "crawl-run-worker-interactive",
        "crawl-run-worker-batch",
        "source-scan-enqueue",
        "feature-export-reconcile",
    }

    interactive = scheduler.jobs["crawl-run-worker-interactive"]
    batch = scheduler.jobs["crawl-run-worker-batch"]
    assert interactive["func"] is worker.run_once
    assert batch["func"] is worker.run_once
    assert interactive["kwargs"]["lane"] == worker.LANE_INTERACTIVE
    assert batch["kwargs"]["lane"] == worker.LANE_BATCH
    # 각 레인 1 인스턴스.
    assert interactive["max_instances"] == 1
    assert batch["max_instances"] == 1
    # 비-persistent 분기는 session_factory/handlers도 함께 넘긴다.
    assert interactive["kwargs"]["session_factory"] is sentinel_factory
    assert "handlers" in interactive["kwargs"]

    source_scan = scheduler.jobs["source-scan-enqueue"]
    assert source_scan["func"] is worker.enqueue_source_scan_once

    # feature export 안전망 job(T-171): 비-persistent 분기는 session_factory를 넘긴다.
    reconcile = scheduler.jobs["feature-export-reconcile"]
    assert reconcile["func"] is worker.reconcile_feature_exports_once
    assert reconcile["max_instances"] == 1
    assert reconcile["kwargs"]["session_factory"] is sentinel_factory


def test_register_worker_jobs_legacy_absent_is_ignored():
    scheduler = _FakeScheduler()  # 구 job 없음

    # remove_job이 LookupError를 던져도 등록은 계속된다.
    worker.register_worker_jobs(
        scheduler,
        session_factory=object(),
        handlers=None,
        use_persistent_jobstore=False,
        settings=_fake_settings(),
    )
    assert "crawl-run-worker-interactive" in scheduler.jobs
    assert "crawl-run-worker-batch" in scheduler.jobs


def test_register_worker_jobs_persistent_kwargs_are_serializable():
    scheduler = _FakeScheduler()

    worker.register_worker_jobs(
        scheduler,
        session_factory=object(),
        handlers=None,
        use_persistent_jobstore=True,
        settings=_fake_settings(),
    )

    # persistent 분기: 직렬화 불가한 session_factory/handlers 없이 lane만 넘긴다.
    interactive = scheduler.jobs["crawl-run-worker-interactive"]
    assert interactive["kwargs"] == {"lane": worker.LANE_INTERACTIVE}
    batch = scheduler.jobs["crawl-run-worker-batch"]
    assert batch["kwargs"] == {"lane": worker.LANE_BATCH}
    assert scheduler.jobs["source-scan-enqueue"]["kwargs"] == {}
    # persistent 분기: 안전망 job도 직렬화 불가 인자 없이 등록된다.
    assert scheduler.jobs["feature-export-reconcile"]["kwargs"] == {}


async def test_reconcile_feature_exports_once_heals_unwired_candidate(session_factory):
    """안전망 coroutine(T-171): dirty 마킹 없이 export 대상이 된 후보를 전량 sync로 보정한다."""
    from ktc.models import (
        ExtractedPlaceCandidate,
        FeatureExport,
        FeatureExportStatus,
        GroundingStatus,
        MatchStatus,
    )

    async with session_factory() as s:
        channel = YoutubeChannel(channel_id="rc-chan", title="채널")
        s.add(channel)
        await s.flush()
        s.add(
            YoutubeVideo(
                video_id="rc-vid",
                title="영상",
                url="https://youtu.be/rc-vid",
                channel_id="rc-chan",
                channel_name="채널",
            )
        )
        place = TravelPlace(
            name="성산일출봉",
            latitude=33.458,
            longitude=126.942,
            is_geocoded=True,
        )
        s.add(place)
        await s.commit()
        await s.refresh(place)
        # dirty 마킹 없이(미배선) export 대상 후보를 만든다.
        s.add(
            ExtractedPlaceCandidate(
                video_id="rc-vid",
                source_channel_id="rc-chan",
                source_text="성산일출봉",
                ai_place_name="성산일출봉",
                match_status=MatchStatus.MATCHED,
                grounding_status=GroundingStatus.VERIFIED_RAW.value,
                matched_place_id=place.place_id,
                feature_export_status=FeatureExportStatus.READY.value,
            )
        )
        await s.commit()

    changed = await worker.reconcile_feature_exports_once(session_factory)
    assert changed == 1

    async with session_factory() as s:
        rows = (await s.execute(select(FeatureExport))).scalars().all()
        assert len(rows) == 1
        assert rows[0].operation == "upsert"

    # 재실행은 fixpoint(추가 변경 없음).
    assert await worker.reconcile_feature_exports_once(session_factory) == 0


def test_register_worker_jobs_omits_source_scan_when_disabled():
    scheduler = _FakeScheduler()

    worker.register_worker_jobs(
        scheduler,
        session_factory=object(),
        handlers={},
        use_persistent_jobstore=False,
        settings=_fake_settings(source_scan_enabled=False),
    )
    assert "source-scan-enqueue" not in scheduler.jobs
    # source_scan을 꺼도 feature export 안전망 job은 별도 플래그라 유지된다(T-171).
    assert set(scheduler.jobs) == {
        "crawl-run-worker-interactive",
        "crawl-run-worker-batch",
        "feature-export-reconcile",
    }
