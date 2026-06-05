"""crawl_run_service 단위 테스트."""

from __future__ import annotations

from datetime import timedelta

from app.models import RunState, utcnow
from app.services import crawl_run_service as svc


async def test_create_and_get_run(session):
    run = await svc.create_run(
        session,
        job_type="harvest",
        source="web",
        target_type="keyword",
        target_id="제주도 맛집",
        payload={"query": "제주도 맛집", "max_videos": 10},
    )
    assert run.id is not None
    assert run.state == RunState.PENDING
    assert run.progress == 0.0

    fetched = await svc.get_run(session, run.id)
    assert fetched is not None
    assert fetched.target_id == "제주도 맛집"


async def test_claim_next_pending_fifo(session):
    first = await svc.create_run(session, job_type="harvest", source="web")
    second = await svc.create_run(session, job_type="harvest", source="mcp")

    claimed = await svc.claim_next_pending(session)
    assert claimed is not None
    assert claimed.id == first.id
    assert claimed.state == RunState.RUNNING
    assert claimed.started_at is not None
    assert claimed.heartbeat_at is not None

    # 두 번째 claim은 아직 pending인 second를 가져온다.
    claimed2 = await svc.claim_next_pending(session)
    assert claimed2 is not None
    assert claimed2.id == second.id


async def test_claim_returns_none_when_empty(session):
    assert await svc.claim_next_pending(session) is None


async def test_heartbeat_and_done(session):
    run = await svc.create_run(session, job_type="harvest", source="web")
    await svc.claim_next_pending(session)

    await svc.heartbeat(session, run.id, progress=0.5)
    refreshed = await svc.get_run(session, run.id)
    assert refreshed.progress == 0.5

    await svc.mark_done(session, run.id, result={"videos": 3})
    done = await svc.get_run(session, run.id)
    assert done.state == RunState.DONE
    assert done.progress == 1.0
    assert done.finished_at is not None
    assert '"videos": 3' in done.result_json


async def test_heartbeat_progress_clamped(session):
    run = await svc.create_run(session, job_type="harvest", source="web")
    await svc.heartbeat(session, run.id, progress=5.0)
    refreshed = await svc.get_run(session, run.id)
    assert refreshed.progress == 1.0


async def test_mark_failed(session):
    run = await svc.create_run(session, job_type="harvest", source="web")
    await svc.mark_failed(session, run.id, error="boom")
    failed = await svc.get_run(session, run.id)
    assert failed.state == RunState.FAILED
    assert failed.last_error == "boom"


async def test_requeue_stale_requeues_when_retries_left(session):
    run = await svc.create_run(session, job_type="harvest", source="web")
    await svc.claim_next_pending(session)
    # heartbeat를 과거로 강제 이동
    run_db = await svc.get_run(session, run.id)
    run_db.heartbeat_at = utcnow() - timedelta(seconds=600)
    await session.commit()

    count = await svc.requeue_stale(session, threshold_seconds=300)
    assert count == 1
    requeued = await svc.get_run(session, run.id)
    assert requeued.state == RunState.PENDING
    assert requeued.retry_count == 1
    assert requeued.started_at is None


async def test_requeue_stale_isolates_when_retries_exhausted(session):
    run = await svc.create_run(session, job_type="harvest", source="web")
    await svc.claim_next_pending(session)
    run_db = await svc.get_run(session, run.id)
    run_db.retry_count = 3
    run_db.heartbeat_at = utcnow() - timedelta(seconds=600)
    await session.commit()

    count = await svc.requeue_stale(session, threshold_seconds=300, max_retries=3)
    assert count == 1
    failed = await svc.get_run(session, run.id)
    assert failed.state == RunState.FAILED
    assert "max retries" in (failed.last_error or "")


async def test_list_runs_filter_by_state(session):
    await svc.create_run(session, job_type="harvest", source="web")
    r2 = await svc.create_run(session, job_type="harvest", source="web")
    await svc.mark_done(session, r2.id)

    pending = await svc.list_runs(session, state=RunState.PENDING)
    done = await svc.list_runs(session, state=RunState.DONE)
    assert len(pending) == 1
    assert len(done) == 1
