"""실제 PostGIS row lock/native metadata로 인계·late owner·유한 발화를 회귀한다."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest
from ktc.dagster import runtime as rt
from ktc.dagster.definitions import concierge_batch, concierge_dispatch, defs
from ktc.models import RunState, SchedulerControl, utcnow
from ktc.services import crawl_run_service as service
from ktc.services.scheduler_control import switch_backend

from dagster import DagsterInstance, DagsterRunStatus, Failure, build_sensor_context
from scheduler import worker


async def activate(session):
    session.add(SchedulerControl(id=1, backend="dagster", generation=1))
    await session.commit()


async def pending(session):
    return await service.create_run(session, job_type="harvest", source="web")


def native(owner, status, **extra):
    return SimpleNamespace(
        run_id=owner,
        status=status,
        is_finished=status
        in (
            DagsterRunStatus.SUCCESS,
            DagsterRunStatus.FAILURE,
            DagsterRunStatus.CANCELED,
        ),
        job_name="concierge_batch",
        remote_job_origin=None,
        tags={
            "kortravelcommon/project": "concierge",
            "dagster/code_location": rt.location(),
        },
        **extra,
    )


async def owned(session, state=RunState.RUNNING):
    row = await pending(session)
    row.state = state
    row.orchestrator_run_id = "native-old"
    row.started_at = row.heartbeat_at = utcnow() - timedelta(hours=1)
    await session.commit()
    return row


async def test_claim_race_and_mode_generation(session, session_factory):
    row = await pending(session)
    assert (
        await rt.claim(session_factory, row.id, "batch", 0, 0, 0, "wrong-mode") is None
    )
    await activate(session)
    assert (
        await rt.claim(session_factory, row.id, "batch", 0, 0, 0, "old-generation")
        is None
    )
    results = await asyncio.gather(
        *(
            rt.claim(session_factory, row.id, "batch", 0, 0, 1, owner)
            for owner in ("one", "two")
        )
    )
    assert sum(value is not None for value in results) == 1
    await session.refresh(row)
    assert row.orchestrator_run_id in ("one", "two") and row.state == RunState.RUNNING
    assert await service.claim_next_pending(session) is None
    with pytest.raises(ValueError, match="drain"):
        await switch_backend(session, "legacy", 1)
    await session.rollback()


async def test_previous_native_owner_cannot_complete_same_retry(
    session, session_factory
):
    row = await owned(session)
    row.orchestrator_run_id = "native-new"
    await session.commit()
    token = worker._execution_owner.set("native-old")
    try:
        assert (
            await worker._lock_owned_crawl_run_attempt(
                session, run_id=row.id, retry_count=0
            )
            is None
        )
    finally:
        worker._execution_owner.reset(token)


@pytest.mark.parametrize(
    "status,expected",
    [
        (DagsterRunStatus.STARTED, RunState.RUNNING),
        (DagsterRunStatus.CANCELING, RunState.RUNNING),
        (DagsterRunStatus.FAILURE, RunState.PENDING),
        (DagsterRunStatus.CANCELED, RunState.CANCELLED),
        (DagsterRunStatus.SUCCESS, RunState.FAILED),
    ],
)
async def test_recovery_native_states(session, session_factory, status, expected):
    row = await owned(session)
    before = rt.lease(row)
    changed = await rt.reconcile_one(
        session_factory, before, native("native-old", status)
    )
    assert changed == (expected != RunState.RUNNING)
    await session.refresh(row)
    assert row.state == expected
    if expected == RunState.PENDING:
        assert (
            row.retry_count == 1
            and row.orchestrator_attempt == 1
            and row.orchestrator_run_id is None
        )


async def test_live_execution_advisory_blocks_recovery(session, session_factory):
    row = await owned(session)
    async with worker._hold_crawl_run_execution_lock(session_factory, row.id):
        assert not await rt.reconcile_one(
            session_factory,
            rt.lease(row),
            native("native-old", DagsterRunStatus.FAILURE),
        )
    await session.refresh(row)
    assert row.state == RunState.RUNNING


async def test_metadata_missing_grace_retry_budget_and_legacy_exclusion(
    session, session_factory
):
    await activate(session)
    row = await owned(session)
    row.retry_count = 3
    await session.commit()
    assert await service.requeue_stale(session, threshold_seconds=1) == 0
    row.started_at = row.heartbeat_at = utcnow()
    await session.commit()
    assert not await rt.reconcile_one(session_factory, rt.lease(row), None)
    row.started_at = row.heartbeat_at = utcnow() - timedelta(hours=1)
    await session.commit()
    assert await rt.reconcile_one(session_factory, rt.lease(row), None)
    await session.refresh(row)
    assert row.state == RunState.FAILED and row.attention == "open"


async def test_recovery_cas_heartbeat_and_foreign_origin(session, session_factory):
    row = await owned(session)
    before = rt.lease(row)
    row.heartbeat_at = utcnow()
    await session.commit()
    assert not await rt.reconcile_one(
        session_factory, before, native("native-old", DagsterRunStatus.FAILURE)
    )
    wrong = native("native-old", DagsterRunStatus.FAILURE)
    wrong.tags["dagster/code_location"] = "foreign"
    with pytest.raises(RuntimeError, match="다른"):
        await rt.reconcile_one(session_factory, rt.lease(row), wrong)


async def test_normal_shutdown_and_user_native_cancel(session, session_factory):
    row = await owned(session, RunState.PENDING)
    await rt.finish_interrupt(
        session_factory, row, native("native-old", DagsterRunStatus.STARTED)
    )
    await session.refresh(row)
    assert (
        row.state == RunState.PENDING
        and row.orchestrator_run_id is None
        and row.orchestrator_attempt == 1
        and row.retry_count == 0
    )
    # 옛 CANCELED receipt로 새 attempt를 취소할 수 없다.
    old = rt.Lease(
        row.id,
        row.lane,
        0,
        0,
        "native-old",
        RunState.PENDING,
        row.heartbeat_at,
        row.started_at,
        row.orchestrator_claimed_at or row.created_at,
    )
    assert not await rt.reconcile_one(
        session_factory, old, native("native-old", DagsterRunStatus.CANCELED)
    )
    row2 = await owned(session, RunState.PENDING)
    await rt.finish_interrupt(
        session_factory, row2, native("native-old", DagsterRunStatus.CANCELING)
    )
    await session.refresh(row2)
    assert row2.state == RunState.CANCELLED


async def test_provider_failure_is_native_failure_without_retry(
    session, session_factory, monkeypatch
):
    await activate(session)
    row = await pending(session)
    monkeypatch.setattr(worker, "_worker_memory_mb", lambda: 0)

    async def fail(_s, _r):
        raise ValueError("provider unavailable")

    with pytest.raises(Failure) as caught:
        await rt.execute_claimed(
            session_factory,
            row_id=row.id,
            lane="batch",
            retry=0,
            attempt=0,
            generation=1,
            native_id="native-provider",
            instance=None,
            handlers={"harvest": fail},
        )
    assert caught.value.allow_retries is False
    await session.refresh(row)
    assert row.state == RunState.FAILED and row.retry_count == 0


async def test_control_rollback_and_stale_request_fence(session, session_factory):
    await activate(session)
    row = await pending(session)
    control = await switch_backend(session, "legacy", 1)
    assert control.generation == 2
    assert (
        await rt.claim(session_factory, row.id, "batch", 0, 0, 1, "late-native") is None
    )
    assert (await service.claim_next_pending(session)).id == row.id


async def test_not_started_same_key_and_preclaim_budget(
    session, session_factory, monkeypatch
):
    await activate(session)
    row = await pending(session)
    import os
    from contextlib import asynccontextmanager

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    @asynccontextmanager
    async def test_database():
        engine = create_async_engine(
            os.environ["KTC_TEST_PG_DSN"], pool_size=4, max_overflow=0
        )
        try:
            yield async_sessionmaker(engine, expire_on_commit=False)
        finally:
            await engine.dispose()

    monkeypatch.setattr(rt, "database", test_database)
    with DagsterInstance.ephemeral() as instance:
        snapshot = rt.lease(row)
        key = rt.run_key(snapshot, "root")
        tags = {
            **rt.dispatch_tags(snapshot, 1, "root"),
            "dagster/run_key": key,
            "dagster/sensor_name": rt.DISPATCH_NAME,
        }
        config = {
            "ops": {
                "batch_run": {
                    "config": {
                        "run_id": row.id,
                        "retry_count": 0,
                        "attempt": 0,
                        "control_generation": 1,
                    }
                }
            }
        }
        first = instance.create_run_for_job(
            concierge_batch,
            status=DagsterRunStatus.NOT_STARTED,
            tags=tags,
            run_config=config,
        )

        def evaluate():
            with build_sensor_context(
                instance=instance, repository_def=defs.get_repository_def()
            ) as ctx:
                return concierge_dispatch.evaluate_tick(ctx)

        result = await asyncio.to_thread(evaluate)
        assert len(result.run_requests) == 1 and result.run_requests[0].run_key == key
        instance.report_run_canceled(first)
        result = await asyncio.to_thread(evaluate)
        assert not result.run_requests
        await session.refresh(row)
        assert row.state == RunState.CANCELLED
        row = await pending(session)
        snapshot = rt.lease(row)
        tags = {
            **rt.dispatch_tags(snapshot, 1, "root"),
            "dagster/run_key": rt.run_key(snapshot, "root"),
            "dagster/sensor_name": rt.DISPATCH_NAME,
        }
        config = {
            "ops": {
                "batch_run": {
                    "config": {
                        "run_id": row.id,
                        "retry_count": 0,
                        "attempt": 0,
                        "control_generation": 1,
                    }
                }
            }
        }
        first = instance.create_run_for_job(
            concierge_batch,
            status=DagsterRunStatus.FAILURE,
            tags=tags,
            run_config=config,
        )
        for _ in range(3):
            instance.create_run_for_job(
                concierge_batch,
                status=DagsterRunStatus.FAILURE,
                tags=tags,
                run_config=config,
            )
        result = await asyncio.to_thread(evaluate)
        assert not result.run_requests
        await session.refresh(row)
        assert row.state == RunState.FAILED and row.attention == "open"


def test_defs_resolved_executor_and_paid_retry_policy():
    jobs = defs.resolve_all_job_defs()
    assert len(jobs) == 4
    for job in jobs:
        assert job.tags["dagster/max_retries"] == "0"
        assert job.tags["dagster/retry_on_asset_or_op_failure"] == "false"
        assert job.executor_def.name == "multiprocess"


async def test_native_timeout_preserves_owned_lease_and_spends_recovery_budget(
    session, session_factory
):
    row = await owned(session)
    await rt.finish_interrupt(
        session_factory,
        row,
        native("native-old", DagsterRunStatus.CANCELING),
        timed_out=True,
    )
    await session.refresh(row)
    assert row.state == RunState.RUNNING and row.orchestrator_run_id == "native-old"
    assert await rt.reconcile_one(
        session_factory, rt.lease(row), native("native-old", DagsterRunStatus.FAILURE)
    )
    await session.refresh(row)
    assert (
        row.state == RunState.PENDING
        and row.retry_count == 1
        and row.orchestrator_run_id is None
    )


def test_native_timeout_uses_actual_start_and_native_cap():
    run = native("native-old", DagsterRunStatus.CANCELING)
    run.tags["dagster/max_runtime"] = "60"
    instance = SimpleNamespace(
        get_run_record_by_id=lambda owner: SimpleNamespace(
            start_time=utcnow().timestamp() - 61
        )
    )
    assert rt.native_runtime_expired(instance, run)
    instance.get_run_record_by_id = lambda owner: SimpleNamespace(
        start_time=utcnow().timestamp() - 10
    )
    assert not rt.native_runtime_expired(instance, run)
    instance.get_run_record_by_id = lambda owner: None
    with pytest.raises(RuntimeError):
        rt.native_runtime_expired(instance, run)


def test_unknown_metadata_advances_partial_page_cursor_with_evaluation_budget(
    monkeypatch,
):
    import json

    from ktc.dagster import definitions as definitions_module

    clock = [0.0]
    visited = []

    async def control():
        return SimpleNamespace(backend="dagster", generation=1)

    async def page(lane, after):
        return [
            rt.Lease(i, lane, 0, 0, None, RunState.PENDING, None, None, None)
            for i in range(after + 1, after + 11)
        ]

    def unknown(instance, row, generation):
        visited.append((row.lane, row.id))
        clock[0] += 6
        raise RuntimeError("metadata UNKNOWN")

    monkeypatch.setattr(rt, "control_snapshot", control)
    monkeypatch.setattr(definitions_module, "pending_page", page)
    monkeypatch.setattr(definitions_module, "active", lambda context, name: False)
    monkeypatch.setattr(rt, "history", unknown)
    monkeypatch.setattr(definitions_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        definitions_module,
        "get_settings",
        lambda: SimpleNamespace(SCHEDULER_ENABLED=True),
    )
    with DagsterInstance.ephemeral() as instance:
        with build_sensor_context(
            instance=instance, repository_def=defs.get_repository_def()
        ) as context:
            first = concierge_dispatch.evaluate_tick(context)
        assert not first.run_requests and json.loads(first.cursor)["interactive"] == 5
        with build_sensor_context(
            instance=instance,
            repository_def=defs.get_repository_def(),
            cursor=first.cursor,
        ) as context:
            second = concierge_dispatch.evaluate_tick(context)
        assert not second.run_requests and json.loads(second.cursor)["batch"] == 5
        assert json.loads(second.cursor)["interactive"] == 5
        with build_sensor_context(
            instance=instance,
            repository_def=defs.get_repository_def(),
            cursor=second.cursor,
        ) as context:
            third = concierge_dispatch.evaluate_tick(context)
        assert not third.run_requests and json.loads(third.cursor)["interactive"] == 10
    assert visited == [("interactive", i) for i in range(1, 6)] + [
        ("batch", i) for i in range(1, 6)
    ] + [("interactive", i) for i in range(6, 11)]


def test_actual_resolved_executor_limits_each_job_to_one_step():
    from dagster._core.system_config.objects import ResolvedRunConfig

    for job in defs.resolve_all_job_defs():
        op_name = next(iter(job.graph.node_dict))
        config = {"control_generation": 0}
        if job.name in rt.LANE_JOBS.values():
            config.update(run_id=1, retry_count=0, attempt=0)
        resolved = ResolvedRunConfig.build(job, {"ops": {op_name: {"config": config}}})
        assert resolved.execution.execution_engine_config["max_concurrent"] == 1


@pytest.mark.parametrize("failing_lane", ["interactive", "batch"])
def test_unknown_lane_allows_other_lane_actual_request_next_tick(
    monkeypatch, failing_lane
):
    import json

    from ktc.dagster import definitions as module

    clock = [0.0]
    generation = [1]
    healthy_lane = "batch" if failing_lane == "interactive" else "interactive"

    async def control():
        return SimpleNamespace(backend="dagster", generation=generation[0])

    async def page(lane, after):
        ids = range(after + 1, after + 11) if lane == failing_lane else [100000]
        return [
            rt.Lease(i, lane, 0, 0, None, RunState.PENDING, None, None, None)
            for i in ids
        ]

    def history(instance, row, current_generation):
        if row.lane == failing_lane:
            clock[0] += 6
            raise RuntimeError("lane metadata UNKNOWN")
        return []

    monkeypatch.setattr(rt, "control_snapshot", control)
    monkeypatch.setattr(module, "pending_page", page)
    monkeypatch.setattr(module, "active", lambda context, name: False)
    monkeypatch.setattr(rt, "history", history)
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        module, "get_settings", lambda: SimpleNamespace(SCHEDULER_ENABLED=True)
    )
    # 기존 interactive/batch cursor도 읽으며 새 시작lane cursor로 점진 이관한다.
    cursor = {"interactive": 0, "batch": 0}
    if failing_lane == "batch":
        cursor["next_lane"] = "batch"
    with DagsterInstance.ephemeral() as instance:
        with build_sensor_context(
            instance=instance,
            repository_def=defs.get_repository_def(),
            cursor=json.dumps(cursor),
        ) as context:
            first = concierge_dispatch.evaluate_tick(context)
        assert not first.run_requests
        generation[0] = 2
        with build_sensor_context(
            instance=instance,
            repository_def=defs.get_repository_def(),
            cursor=first.cursor,
        ) as context:
            second = concierge_dispatch.evaluate_tick(context)
        assert len(second.run_requests) == 1
        request = second.run_requests[0]
        assert request.job_name == rt.LANE_JOBS[healthy_lane]
        assert request.tags[rt.CONTROL_TAG] == "2"
        assert (
            json.loads(second.cursor)[failing_lane]
            > json.loads(first.cursor)[failing_lane]
        )
