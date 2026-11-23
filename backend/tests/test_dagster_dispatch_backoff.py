"""claim 전 실패의 backoff·jitter·상한, 일시/결정적 오류 분류, 유지보수 유한 재시도."""

import json
from types import SimpleNamespace

import httpx
import pytest
from ktc.dagster import definitions as module
from ktc.dagster import runtime as rt
from ktc.dagster.definitions import concierge_dispatch, defs
from ktc.models import RunState, SchedulerControl
from ktc.services import crawl_run_service as service
from sqlalchemy.exc import OperationalError

from dagster import DagsterInstance, DagsterRunStatus, Failure, build_sensor_context
from scheduler import worker


def db_error(code):
    original = RuntimeError("접속 정보가 포함된 원문")
    original.sqlstate = code
    return OperationalError(None, None, original)


def test_backoff_is_bounded_jittered_and_stable():
    for failures in range(1, 12):
        delay = min(1800, 60 * 2 ** (failures - 1))
        value = rt.backoff_seconds(failures, key="row-1", base=60, cap=1800)
        assert delay / 2 <= value <= delay
        # 같은 key·횟수는 sensor tick이 바뀌어도 같은 대기 시간이다.
        assert value == rt.backoff_seconds(failures, key="row-1", base=60, cap=1800)
    spread = {
        rt.backoff_seconds(3, key=f"row-{i}", base=60, cap=1800) for i in range(20)
    }
    # 같은 시각에 실패한 행들이 한 시각으로 몰리지 않는다.
    assert len(spread) > 10


def test_transient_classification():
    request = httpx.Request("POST", "http://geo.invalid/v2/dataset/version")
    assert rt.is_transient_error(TimeoutError())
    assert rt.is_transient_error(httpx.ConnectError("down", request=request))
    for status, expected in [(503, True), (429, True), (404, False), (401, False)]:
        response = httpx.Response(status, request=request)
        error = httpx.HTTPStatusError("http", request=request, response=response)
        assert rt.is_transient_error(error) is expected
    for code in ["08006", "40001", "55P03", "57014", "53300", "53200", "53100", "58030"]:
        assert rt.is_transient_error(db_error(code)), code
    for code in ["42703", "23505", "28P01"]:
        assert not rt.is_transient_error(db_error(code)), code
    assert not rt.is_transient_error(ValueError("bad payload"))
    from sqlalchemy.exc import TimeoutError as PoolTimeoutError

    assert rt.is_transient_error(PoolTimeoutError("QueuePool limit"))


def record(status, *, end_time, run_id="native-1"):
    run = SimpleNamespace(
        run_id=run_id,
        status=status,
        is_finished=status
        in (DagsterRunStatus.SUCCESS, DagsterRunStatus.FAILURE, DagsterRunStatus.CANCELED),
        tags={},
    )
    return SimpleNamespace(dagster_run=run, end_time=end_time, update_timestamp=None)


def evaluate(cursor=None):
    with (
        DagsterInstance.ephemeral() as instance,
        build_sensor_context(
            instance=instance, repository_def=defs.get_repository_def(), cursor=cursor
        ) as context,
    ):
        return concierge_dispatch.evaluate_tick(context)


@pytest.fixture
def dispatch(monkeypatch):
    """batch lane 한 행과 그 행의 Dagster 이력을 조작할 수 있는 sensor 환경."""
    state = {"history": [], "now": 1_000_000.0, "exhausted": []}

    async def control():
        return SimpleNamespace(backend="dagster", generation=1)

    async def page(lane, after):
        if lane != "batch" or after >= 7:
            return []
        return [rt.Lease(7, "batch", 0, 0, None, RunState.PENDING, None, None, None)]

    async def exhaust(row, generation, last=None):
        state["exhausted"].append(row.id)
        state["last"] = last
        return True

    monkeypatch.setattr(rt, "control_snapshot", control)
    monkeypatch.setattr(module, "pending_page", page)
    monkeypatch.setattr(module, "active", lambda context, name: False)
    monkeypatch.setattr(module, "exhaust", exhaust)
    monkeypatch.setattr(rt, "history", lambda instance, row, generation: state["history"])
    monkeypatch.setattr(module.time, "time", lambda: state["now"])
    monkeypatch.setattr(
        module, "get_settings", lambda: SimpleNamespace(SCHEDULER_ENABLED=True)
    )
    return state


def test_first_dispatch_is_immediate(dispatch):
    result = evaluate()
    assert [r.tags[rt.PREDECESSOR_TAG] for r in result.run_requests] == ["root"]


def test_preclaim_failure_waits_for_backoff_then_redispatches(dispatch):
    lease = rt.Lease(7, "batch", 0, 0, None, RunState.PENDING, None, None, None)
    for failures in range(1, rt.MAX_DISPATCH_RUNS):
        ended = dispatch["now"]
        dispatch["history"] = [
            record(DagsterRunStatus.FAILURE, end_time=ended, run_id=f"native-{i}")
            for i in range(failures, 0, -1)
        ]
        wait = rt.dispatch_delay(lease, failures)
        assert wait >= rt.DISPATCH_BACKOFF_BASE_SECONDS / 2
        # 실패 직후와 backoff 직전에는 다시 띄우지 않는다.
        dispatch["now"] = ended + 1
        assert not evaluate().run_requests
        dispatch["now"] = ended + wait - 1
        assert not evaluate().run_requests
        # backoff가 지나면 직전 실행을 predecessor로 새 key를 만든다.
        dispatch["now"] = ended + wait + 1
        requests = evaluate().run_requests
        assert len(requests) == 1
        assert requests[0].tags[rt.PREDECESSOR_TAG] == f"native-{failures}"
        assert requests[0].run_key == rt.run_key(lease, f"native-{failures}")
    assert not dispatch["exhausted"]


def test_backoff_window_is_bounded_and_budget_exhausts(dispatch):
    lease = rt.Lease(7, "batch", 0, 0, None, RunState.PENDING, None, None, None)
    total = sum(rt.dispatch_delay(lease, n) for n in range(1, rt.MAX_DISPATCH_RUNS))
    # 짧은 launch 장애는 넘기되, 행이 몇 시간씩 pending에 묶이지는 않는다.
    assert 10 * 60 <= total <= 40 * 60
    dispatch["history"] = [
        record(DagsterRunStatus.FAILURE, end_time=dispatch["now"], run_id=f"n-{i}")
        for i in range(rt.MAX_DISPATCH_RUNS)
    ]
    assert not evaluate().run_requests
    assert dispatch["exhausted"] == [7]
    # 종결 사유에 마지막 run을 남겨 운영자가 원인을 바로 찾게 한다.
    assert dispatch["last"].run_id == "n-0"


def test_backoff_row_does_not_block_later_rows(dispatch, monkeypatch):
    async def page(lane, after):
        if lane != "batch":
            return []
        return [
            rt.Lease(i, "batch", 0, 0, None, RunState.PENDING, None, None, None)
            for i in (7, 8)
            if i > after
        ]

    def history(instance, row, generation):
        if row.id == 7:
            return [record(DagsterRunStatus.FAILURE, end_time=dispatch["now"])]
        return []

    monkeypatch.setattr(module, "pending_page", page)
    monkeypatch.setattr(rt, "history", history)
    result = evaluate()
    assert [r.tags[rt.ROW_TAG] for r in result.run_requests] == ["8"]
    # 대기 중인 행은 다음 tick에 다시 본다(keyset이 page 끝에서 처음으로 돌아간다).
    assert json.loads(result.cursor)["batch"] == 0


def test_real_run_records_feed_backoff(monkeypatch):
    """실제 Dagster run record의 종료 시각으로 backoff를 계산한다."""
    lease = rt.Lease(7, "batch", 0, 0, None, RunState.PENDING, None, None, None)
    monkeypatch.setattr(rt, "location", lambda: "ktc.dagster.definitions")
    with DagsterInstance.ephemeral() as instance:
        tags = {**rt.dispatch_tags(lease, 1, "root"), "dagster/run_key": "k"}
        config = {"run_id": 7, "retry_count": 0, "attempt": 0, "control_generation": 1}
        run = instance.create_run_for_job(
            module.concierge_batch,
            status=DagsterRunStatus.FAILURE,
            tags=tags,
            run_config={"ops": {"batch_run": {"config": config}}},
        )
        records = rt.history(instance, lease, 1)
        assert [r.dagster_run.run_id for r in records] == [run.run_id]
        finished = rt.finished_at(records[0])
        assert abs(finished - records[0].update_timestamp.timestamp()) < 1


async def test_deterministic_claim_error_fails_row_once(
    session, session_factory, monkeypatch
):
    session.add(SchedulerControl(id=1, backend="dagster", generation=1))
    await session.commit()
    row = await service.create_run(session, job_type="harvest", source="web")
    monkeypatch.setattr(worker, "_worker_memory_mb", lambda: 0)

    async def broken_claim(*args, **kwargs):
        raise db_error("42703")

    monkeypatch.setattr(rt, "claim", broken_claim)
    with pytest.raises(Failure, match="결정적") as caught:
        await rt.execute_claimed(
            session_factory,
            row_id=row.id,
            lane="batch",
            retry=0,
            attempt=0,
            generation=1,
            native_id="native-x",
            instance=None,
        )
    assert caught.value.allow_retries is False
    await session.refresh(row)
    assert row.state == RunState.FAILED and row.attention == "open"
    assert "결정적" in row.last_error


async def test_transient_claim_error_keeps_row_pending(
    session, session_factory, monkeypatch
):
    session.add(SchedulerControl(id=1, backend="dagster", generation=1))
    await session.commit()
    row = await service.create_run(session, job_type="harvest", source="web")
    monkeypatch.setattr(worker, "_worker_memory_mb", lambda: 0)

    async def busy_claim(*args, **kwargs):
        raise db_error("55P03")

    monkeypatch.setattr(rt, "claim", busy_claim)
    with pytest.raises(Failure, match="backoff"):
        await rt.execute_claimed(
            session_factory,
            row_id=row.id,
            lane="batch",
            retry=0,
            attempt=0,
            generation=1,
            native_id="native-y",
            instance=None,
        )
    await session.refresh(row)
    assert row.state == RunState.PENDING and row.orchestrator_run_id is None


async def test_unclassified_claim_error_is_not_treated_as_deterministic(
    session, session_factory, monkeypatch
):
    import socket

    session.add(SchedulerControl(id=1, backend="dagster", generation=1))
    await session.commit()
    row = await service.create_run(session, job_type="harvest", source="web")
    monkeypatch.setattr(worker, "_worker_memory_mb", lambda: 0)

    async def dns_blip(*args, **kwargs):
        raise socket.gaierror(-3, "Temporary failure in name resolution")

    monkeypatch.setattr(rt, "claim", dns_blip)
    with pytest.raises(Failure, match="backoff"):
        await rt.execute_claimed(
            session_factory,
            row_id=row.id,
            lane="batch",
            retry=0,
            attempt=0,
            generation=1,
            native_id="native-z",
            instance=None,
        )
    await session.refresh(row)
    assert row.state == RunState.PENDING


def test_finished_at_prefers_end_time_and_reads_naive_storage_time_as_utc():
    from datetime import UTC, datetime

    ended = SimpleNamespace(end_time=1_700_000_000.5, update_timestamp=None)
    assert rt.finished_at(ended) == 1_700_000_000.5
    naive = SimpleNamespace(
        end_time=None, update_timestamp=datetime(2026, 11, 16, 3, 22, 13)
    )
    aware = datetime(2026, 11, 16, 3, 22, 13, tzinfo=UTC).timestamp()
    assert rt.finished_at(naive) == aware


def run_export(monkeypatch, errors):
    calls = []

    async def maintenance(config, kind):
        calls.append(kind)
        if errors:
            raise errors.pop(0)
        return {"changed": 0}

    monkeypatch.setattr(module, "maintenance", maintenance)
    monkeypatch.setattr(module, "MAINTENANCE_BACKOFF_BASE_SECONDS", 0)
    result = module.concierge_feature_exports.execute_in_process(
        run_config={"ops": {"feature_exports": {"config": {"control_generation": 1}}}},
        raise_on_error=False,
    )
    retries = [e for e in result.all_events if e.event_type_value == "STEP_UP_FOR_RETRY"]
    return result, calls, retries


def test_maintenance_transient_error_retries_then_succeeds(monkeypatch):
    result, calls, retries = run_export(monkeypatch, [TimeoutError()])
    assert result.success and calls == ["export", "export"] and len(retries) == 1


def test_maintenance_transient_retry_is_bounded(monkeypatch):
    errors = [db_error("57014") for _ in range(5)]
    result, calls, retries = run_export(monkeypatch, errors)
    assert not result.success
    assert len(calls) == module.MAINTENANCE_RETRIES + 1
    assert len(retries) == module.MAINTENANCE_RETRIES


def test_maintenance_deterministic_error_is_not_repeated(monkeypatch):
    result, calls, retries = run_export(monkeypatch, [ValueError("bad ledger row")])
    assert not result.success and calls == ["export"] and not retries


def test_admin_refresh_transient_geo_error_retries(monkeypatch):
    from ktc.etl.admin_region_refresh import RefreshError, RefreshStats

    calls = []

    async def refresh(config):
        calls.append(1)
        if len(calls) == 1:
            raise RefreshError("geo 버전 조회 실패 (ConnectError)", RefreshStats(), transient=True)
        return {"state": "completed"}

    monkeypatch.setattr(module, "refresh_maintenance", refresh)
    monkeypatch.setattr(module, "MAINTENANCE_BACKOFF_BASE_SECONDS", 0)
    result = module.concierge_admin_region_refresh.execute_in_process(
        run_config={"ops": {"admin_region_refresh": {"config": {"control_generation": 1}}}},
        raise_on_error=False,
    )
    assert result.success and len(calls) == 2


def test_geo_transient_http_classification():
    from ktc.etl.admin_region_refresh import is_transient_http_error

    request = httpx.Request("POST", "http://geo.invalid/v2/dataset/version")
    assert is_transient_http_error(httpx.ReadTimeout("slow", request=request))
    bad = httpx.HTTPStatusError(
        "http", request=request, response=httpx.Response(403, request=request)
    )
    assert not is_transient_http_error(bad)
    assert not is_transient_http_error(ValueError("geo 버전 응답 형식 오류"))
