"""crawl_run_service 단위 테스트."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from ktc.models import (
    LANE_BATCH,
    LANE_INTERACTIVE,
    CrawlRun,
    RunAttention,
    RunState,
    utcnow,
)
from ktc.services import crawl_run_service as svc


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
    assert run.current_message == "작업이 대기열에 등록되었습니다."
    assert run.heartbeat_at is None
    assert svc.load_status_logs(run)[0]["message"] == "작업이 대기열에 등록되었습니다."

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
    assert claimed.current_message == "작업 실행자가 작업을 시작했습니다."

    # 두 번째 claim은 아직 pending인 second를 가져온다.
    claimed2 = await svc.claim_next_pending(session)
    assert claimed2 is not None
    assert claimed2.id == second.id


async def test_claim_returns_none_when_empty(session):
    assert await svc.claim_next_pending(session) is None


async def test_claim_next_pending_allows_single_parallel_claim(session_factory):
    async with session_factory() as session:
        run = await svc.create_run(session, job_type="harvest", source="web")

    async def claim_one():
        async with session_factory() as claim_session:
            return await svc.claim_next_pending(claim_session)

    first, second = await asyncio.gather(claim_one(), claim_one())

    claimed = [item for item in (first, second) if item is not None]
    assert len(claimed) == 1
    assert claimed[0].id == run.id
    async with session_factory() as verify_session:
        refreshed = await svc.get_run(verify_session, run.id)
        assert refreshed.state == RunState.RUNNING


async def test_stop_run_and_pending_claim_are_atomic(session_factory):
    async with session_factory() as session:
        run = await svc.create_run(session, job_type="harvest", source="web")

    async def stop_one():
        async with session_factory() as stop_session:
            return await svc.stop_run(stop_session, run.id)

    async def claim_one():
        async with session_factory() as claim_session:
            return await svc.claim_next_pending(claim_session)

    stopped, claimed = await asyncio.gather(stop_one(), claim_one())

    assert stopped is not None
    async with session_factory() as verify_session:
        refreshed = await svc.get_run(verify_session, run.id)
        if claimed is None:
            assert stopped.previous_state == RunState.PENDING
            assert stopped.accepted_state == RunState.CANCELLED
            assert refreshed.state == RunState.CANCELLED
            assert refreshed.cancel_requested is False
        else:
            assert claimed.id == run.id
            assert stopped.previous_state == RunState.RUNNING
            assert stopped.accepted_state == RunState.RUNNING
            assert refreshed.state == RunState.RUNNING
            assert refreshed.cancel_requested is True


async def test_stop_running_response_snapshot_survives_worker_completion(session_factory):
    async with session_factory() as session:
        run = await svc.create_run(session, job_type="harvest", source="web")
        await svc.claim_next_pending(session)
        transition = await svc.stop_run(session, run.id)

    assert transition is not None
    assert transition.previous_state == RunState.RUNNING
    assert transition.accepted_state == RunState.RUNNING

    async with session_factory() as worker_session:
        await svc.mark_cancelled(worker_session, run.id)
    async with session_factory() as verify_session:
        refreshed = await svc.get_run(verify_session, run.id)
        assert refreshed.state == RunState.CANCELLED

    # worker가 즉시 마감해도 API/audit가 쓰는 잠금 시점 snapshot은 변하지 않는다.
    assert transition.previous_state == RunState.RUNNING
    assert transition.accepted_state == RunState.RUNNING


async def test_heartbeat_and_done(session):
    run = await svc.create_run(session, job_type="harvest", source="web")
    await svc.claim_next_pending(session)

    await svc.heartbeat(session, run.id, progress=0.5)
    refreshed = await svc.get_run(session, run.id)
    assert refreshed.progress == 0.5

    await svc.append_status_log(session, run.id, "YouTube를 검색 중입니다.", progress=0.6)
    refreshed = await svc.get_run(session, run.id)
    assert refreshed.current_message == "YouTube를 검색 중입니다."
    assert svc.load_status_logs(refreshed)[-1]["progress"] == 0.6

    await svc.mark_done(session, run.id, result={"videos": 3})
    done = await svc.get_run(session, run.id)
    assert done.state == RunState.DONE
    assert done.progress == 1.0
    assert done.finished_at is not None
    assert '"videos": 3' in done.result_json
    assert svc.load_status_logs(done)[-1]["level"] == "success"


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
    assert "작업이 실패했습니다" in failed.current_message


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
    assert requeued.heartbeat_at is None
    assert "재시도 대기열" in requeued.current_message


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


# ---------------------------------------------------------------------------
# T-162: restart lineage·멱등 + attention 전이
# ---------------------------------------------------------------------------


async def _failed_run(session):
    run = await svc.create_run(
        session,
        job_type="harvest",
        source="web",
        target_type="keyword",
        target_id="부산",
        payload={"query": "부산", "max_videos": 3},
    )
    await svc.mark_failed(session, run.id, error="boom")
    return await svc.get_run(session, run.id)


async def test_mark_failed_opens_attention(session):
    failed = await _failed_run(session)
    assert failed.attention == RunAttention.OPEN


async def test_requeue_stale_isolation_opens_attention(session):
    run = await svc.create_run(session, job_type="harvest", source="web")
    await svc.claim_next_pending(session)
    run_db = await svc.get_run(session, run.id)
    run_db.retry_count = 3
    run_db.heartbeat_at = utcnow() - timedelta(seconds=600)
    await session.commit()

    await svc.requeue_stale(session, threshold_seconds=300, max_retries=3)
    failed = await svc.get_run(session, run.id)
    assert failed.state == RunState.FAILED
    assert failed.attention == RunAttention.OPEN


async def test_create_restart_run_requires_terminal(session):
    run = await svc.create_run(session, job_type="harvest", source="web")

    with pytest.raises(ValueError, match="terminal"):
        await svc.create_restart_run(session, run.id, source="web")


async def test_create_restart_run_missing_origin(session):
    run, created = await svc.create_restart_run(session, 999_999, source="web")
    assert run is None
    assert created is False


async def test_create_restart_run_idempotent_with_lineage(session):
    origin = await _failed_run(session)

    first, created_first = await svc.create_restart_run(session, origin.id, source="web")
    assert created_first is True
    assert first.state == RunState.PENDING
    assert first.restart_of_run_id == origin.id
    # 입력 snapshot(payload/job_type/target)이 복사된다.
    assert first.job_type == origin.job_type
    assert first.target_id == origin.target_id
    assert '"max_videos": 3' in (first.payload_json or "")
    # 원본 attention은 superseded로 이관된다.
    refreshed_origin = await svc.get_run(session, origin.id)
    assert refreshed_origin.attention == RunAttention.SUPERSEDED

    # 같은 원본의 중복 클릭: 새 run을 만들지 않고 active 재시작 run을 반환한다.
    second, created_second = await svc.create_restart_run(session, origin.id, source="web")
    assert created_second is False
    assert second.id == first.id
    count = await session.scalar(
        select(func.count())
        .select_from(CrawlRun)
        .where(CrawlRun.restart_of_run_id == origin.id)
    )
    assert count == 1


async def test_create_restart_run_parallel_requests_create_one_child(session_factory):
    async with session_factory() as session:
        origin = await _failed_run(session)
        origin_id = origin.id

    async def restart_once():
        async with session_factory() as restart_session:
            run, created = await svc.create_restart_run(
                restart_session, origin_id, source="web"
            )
            return run.id, created

    first, second = await asyncio.gather(restart_once(), restart_once())

    assert first[0] == second[0]
    assert sorted((first[1], second[1])) == [False, True]
    async with session_factory() as verify_session:
        count = await verify_session.scalar(
            select(func.count())
            .select_from(CrawlRun)
            .where(CrawlRun.restart_of_run_id == origin_id)
        )
    assert count == 1


async def test_restart_successful_done_resolves_origin_attention(session):
    origin = await _failed_run(session)
    restart, _ = await svc.create_restart_run(session, origin.id, source="web")

    await svc.mark_done(session, restart.id, result={"processed_videos": 3})

    refreshed_origin = await svc.get_run(session, origin.id)
    assert refreshed_origin.attention == RunAttention.RESOLVED
    # 재시작이 종료(terminal)되었으므로 새 재시작은 다시 허용된다.
    third, created = await svc.create_restart_run(session, origin.id, source="web")
    assert created is True
    assert third.id != restart.id


async def test_restart_quota_deferred_done_keeps_origin_superseded(session):
    origin = await _failed_run(session)
    restart, _ = await svc.create_restart_run(session, origin.id, source="web")

    await svc.mark_done(
        session,
        restart.id,
        result={"processed_videos": 0, "quota_deferred": True},
        final_message="Gemini API 일일 쿼터가 소진되어 작업을 보류했습니다.",
        final_level="warning",
    )

    refreshed_origin = await svc.get_run(session, origin.id)
    refreshed_restart = await svc.get_run(session, restart.id)
    assert refreshed_origin.attention == RunAttention.SUPERSEDED
    assert refreshed_restart.state == RunState.DONE
    assert '"quota_deferred": true' in (refreshed_restart.result_json or "")


async def test_restart_success_after_quota_deferred_resolves_failed_ancestor(session):
    origin = await _failed_run(session)
    deferred, _ = await svc.create_restart_run(session, origin.id, source="web")
    await svc.mark_done(
        session,
        deferred.id,
        result={"processed_videos": 0, "quota_deferred": True},
    )

    final_attempt, created = await svc.create_restart_run(
        session, deferred.id, source="web"
    )
    assert created is True
    await svc.mark_done(session, final_attempt.id, result={"processed_videos": 2})

    refreshed_origin = await svc.get_run(session, origin.id)
    refreshed_deferred = await svc.get_run(session, deferred.id)
    assert refreshed_origin.attention == RunAttention.RESOLVED
    assert refreshed_deferred.attention is None


async def test_restart_failed_leaves_origin_superseded_and_opens_leaf(session):
    origin = await _failed_run(session)
    restart, _ = await svc.create_restart_run(session, origin.id, source="web")

    await svc.mark_failed(session, restart.id, error="again")

    refreshed_origin = await svc.get_run(session, origin.id)
    refreshed_restart = await svc.get_run(session, restart.id)
    # 최신 leaf attempt가 open을 갖고, 원본은 superseded로 남는다(B6 leaf 기준).
    assert refreshed_origin.attention == RunAttention.SUPERSEDED
    assert refreshed_restart.attention == RunAttention.OPEN


async def test_restart_of_done_origin_keeps_attention_none(session):
    origin = await svc.create_run(session, job_type="harvest", source="web")
    await svc.mark_done(session, origin.id)

    restart, created = await svc.create_restart_run(session, origin.id, source="web")
    assert created is True
    await svc.mark_done(session, restart.id)

    refreshed_origin = await svc.get_run(session, origin.id)
    # 해소할 실패가 없던 원본(성공 run 재실행)은 attention이 생기지 않는다.
    assert refreshed_origin.attention is None


async def test_acknowledge_attention_transitions(session):
    failed = await _failed_run(session)

    acked = await svc.acknowledge_attention(session, failed.id)
    assert acked.attention == RunAttention.ACKNOWLEDGED
    # 멱등 재호출: 그대로 acknowledged 유지.
    again = await svc.acknowledge_attention(session, failed.id)
    assert again.attention == RunAttention.ACKNOWLEDGED

    # acknowledged 원본도 재시작 시 superseded로 이관된다.
    restart, _ = await svc.create_restart_run(session, failed.id, source="web")
    refreshed = await svc.get_run(session, failed.id)
    assert refreshed.attention == RunAttention.SUPERSEDED

    # superseded/None은 확인 대상이 아니다.
    with pytest.raises(ValueError, match="open"):
        await svc.acknowledge_attention(session, failed.id)
    done_run = await svc.create_run(session, job_type="harvest", source="web")
    await svc.mark_done(session, done_run.id)
    with pytest.raises(ValueError, match="open"):
        await svc.acknowledge_attention(session, done_run.id)

    assert await svc.acknowledge_attention(session, 999_999) is None


# ---------------------------------------------------------------------------
# T-163: 워커 레인 분리 (대화형/배치 claim 격리·lane 전파)
# ---------------------------------------------------------------------------


async def test_create_run_defaults_to_batch_lane(session):
    run = await svc.create_run(session, job_type="harvest", source="web")
    assert run.lane == LANE_BATCH


async def test_create_run_accepts_interactive_lane(session):
    run = await svc.create_run(
        session, job_type="poi_batch", source="web", lane=LANE_INTERACTIVE
    )
    assert run.lane == LANE_INTERACTIVE


async def test_claim_lane_isolation_interactive_not_blocked_by_batch(session):
    """더 오래된 batch pending이 있어도 interactive claim은 interactive를 가져온다."""
    batch = await svc.create_run(
        session, job_type="harvest", source="web", lane=LANE_BATCH
    )
    interactive = await svc.create_run(
        session, job_type="poi_batch", source="web", lane=LANE_INTERACTIVE
    )
    assert batch.id < interactive.id  # batch가 FIFO상 먼저다

    claimed = await svc.claim_next_pending(session, lane=LANE_INTERACTIVE)
    assert claimed is not None
    assert claimed.id == interactive.id
    assert claimed.lane == LANE_INTERACTIVE
    assert claimed.state == RunState.RUNNING

    # batch 레인 claim은 남은 batch를 가져온다.
    claimed_batch = await svc.claim_next_pending(session, lane=LANE_BATCH)
    assert claimed_batch is not None
    assert claimed_batch.id == batch.id


async def test_claim_batch_lane_skips_interactive(session):
    """batch 워커는 interactive pending을 집지 않는다(반대 격리)."""
    interactive = await svc.create_run(
        session, job_type="poi_batch", source="web", lane=LANE_INTERACTIVE
    )
    claimed = await svc.claim_next_pending(session, lane=LANE_BATCH)
    assert claimed is None  # interactive만 있으므로 batch 레인은 빈손

    # interactive 레인은 정상 claim.
    claimed_interactive = await svc.claim_next_pending(session, lane=LANE_INTERACTIVE)
    assert claimed_interactive is not None
    assert claimed_interactive.id == interactive.id


async def test_claim_interactive_not_starved_by_batch_backlog(session):
    """배치 백로그가 쌓여 있어도 대화형 작업은 즉시 claim된다(공정성)."""
    for _ in range(5):
        await svc.create_run(session, job_type="harvest", source="web", lane=LANE_BATCH)
    interactive = await svc.create_run(
        session, job_type="deep_research", source="web", lane=LANE_INTERACTIVE
    )
    claimed = await svc.claim_next_pending(session, lane=LANE_INTERACTIVE)
    assert claimed is not None
    assert claimed.id == interactive.id


async def test_claim_lane_none_is_fifo_across_lanes(session):
    """lane 미지정 claim은 레인 무관 FIFO를 유지한다(하위호환)."""
    batch = await svc.create_run(
        session, job_type="harvest", source="web", lane=LANE_BATCH
    )
    await svc.create_run(
        session, job_type="poi_batch", source="web", lane=LANE_INTERACTIVE
    )
    claimed = await svc.claim_next_pending(session)
    assert claimed is not None
    assert claimed.id == batch.id  # 가장 오래된 것(레인 무관)


async def test_create_restart_run_copies_interactive_lane(session):
    """대화형 원본 재시작은 interactive 레인을 복사한다(배치로 안 떨어짐, G6)."""
    origin = await svc.create_run(
        session,
        job_type="deep_research",
        source="web",
        target_type="place",
        target_id="7",
        lane=LANE_INTERACTIVE,
    )
    await svc.mark_failed(session, origin.id, error="boom")

    restart, created = await svc.create_restart_run(session, origin.id, source="web")
    assert created is True
    assert restart.lane == LANE_INTERACTIVE


async def test_create_restart_run_copies_batch_lane(session):
    origin = await svc.create_run(
        session, job_type="harvest", source="web", lane=LANE_BATCH
    )
    await svc.mark_failed(session, origin.id, error="boom")

    restart, created = await svc.create_restart_run(session, origin.id, source="web")
    assert created is True
    assert restart.lane == LANE_BATCH


async def test_requeue_stale_preserves_lane(session):
    """stale 재투입은 원 lane을 보존한다(재투입은 lane 무관 공통 로직)."""
    run = await svc.create_run(
        session, job_type="deep_research", source="web", lane=LANE_INTERACTIVE
    )
    await svc.claim_next_pending(session, lane=LANE_INTERACTIVE)
    run_db = await svc.get_run(session, run.id)
    run_db.heartbeat_at = utcnow() - timedelta(seconds=600)
    await session.commit()

    count = await svc.requeue_stale(session, threshold_seconds=300)
    assert count == 1
    requeued = await svc.get_run(session, run.id)
    assert requeued.state == RunState.PENDING
    assert requeued.lane == LANE_INTERACTIVE
    # 재투입된 작업은 같은 interactive 레인에서 다시 claim된다.
    claimed = await svc.claim_next_pending(session, lane=LANE_INTERACTIVE)
    assert claimed is not None
    assert claimed.id == run.id


async def test_requeue_stale_concurrent_no_double_requeue(session_factory):
    """2 lane 워커가 동시에 requeue_stale해도 같은 stale run을 중복 재투입하지 않는다.

    FOR UPDATE SKIP LOCKED로 한 워커만 stale run을 처리하고 다른 워커는 건너뛴다
    (retry_count가 2가 아니라 1). 하드닝 회귀(T-163).
    """
    async with session_factory() as s:
        run = await svc.create_run(s, job_type="harvest", source="web", lane=LANE_BATCH)
        await svc.claim_next_pending(s, lane=LANE_BATCH)
        run_db = await svc.get_run(s, run.id)
        run_db.heartbeat_at = utcnow() - timedelta(seconds=600)
        await s.commit()

    async def requeue_one():
        async with session_factory() as rs:
            return await svc.requeue_stale(rs, threshold_seconds=300)

    first, second = await asyncio.gather(requeue_one(), requeue_one())

    # 정확히 한 워커만 처리한다(다른 하나는 SKIP LOCKED 또는 이미 PENDING이라 0건).
    assert sorted([first, second]) == [0, 1]
    async with session_factory() as vs:
        refreshed = await svc.get_run(vs, run.id)
        assert refreshed.state == RunState.PENDING
        assert refreshed.retry_count == 1  # 중복 재투입 없음
        assert refreshed.lane == LANE_BATCH
