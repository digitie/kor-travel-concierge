"""Map·PinVi·Geo 공용 instance에 등록하는 단일 Definitions."""

import asyncio
import json
import signal
import time

from kortravelcommon.dagster import has_active_run, reconciliation_sensor
from kortravelcommon.deadline import call_with_deadline

from dagster import (
    Config,
    DagsterExecutionInterruptedError,
    DagsterRunStatus,
    DefaultSensorStatus,
    Definitions,
    Failure,
    RunRequest,
    SensorResult,
    SkipReason,
    job,
    multiprocess_executor,
    op,
    sensor,
)
from ktc.core.config import get_settings
from ktc.dagster import runtime as rt
from ktc.services.scheduler_control import admitted


class CrawlConfig(Config):
    run_id: int
    retry_count: int
    attempt: int
    control_generation: int


class MaintenanceConfig(Config):
    control_generation: int


def cooperative(coro):
    async def run():
        loop = asyncio.get_running_loop()
        task = asyncio.current_task()
        old = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
        for sig in old:
            loop.add_signal_handler(sig, task.cancel)
        try:
            return await coro
        finally:
            for sig, handler in old.items():
                loop.remove_signal_handler(sig)
                signal.signal(sig, handler)

    try:
        return asyncio.run(run())
    except asyncio.CancelledError:
        raise DagsterExecutionInterruptedError() from None


async def execute(context, config, lane):
    if (
        min(
            config.run_id,
            config.retry_count + 1,
            config.attempt + 1,
            config.control_generation + 1,
        )
        < 1
    ):
        raise Failure("유효하지 않은 claim 설정", allow_retries=False)
    async with rt.database() as factory:
        return await rt.execute_claimed(
            factory,
            row_id=config.run_id,
            lane=lane,
            retry=config.retry_count,
            attempt=config.attempt,
            generation=config.control_generation,
            native_id=context.run_id,
            instance=context.instance,
        )


@op
def interactive_run(context, config: CrawlConfig):
    return cooperative(execute(context, config, "interactive"))


@op
def batch_run(context, config: CrawlConfig):
    return cooperative(execute(context, config, "batch"))


executor = multiprocess_executor.configured({"max_concurrent": 1})


@job(executor_def=executor, tags=rt.job_tags("concierge_interactive"))
def concierge_interactive():
    interactive_run()


@job(executor_def=executor, tags=rt.job_tags("concierge_batch"))
def concierge_batch():
    batch_run()


async def maintenance(config, kind):
    settings = get_settings()
    enabled = (
        settings.SOURCE_SCAN_ENABLED
        if kind == "scan"
        else settings.FEATURE_EXPORT_RECONCILE_ENABLED
    )
    if not enabled:
        return {"state": "disabled"}
    async with rt.database() as factory, factory() as s:
        if not await admitted(s, "dagster", config.control_generation):
            return {"state": "skipped"}
        if kind == "scan":
            from ktc.services import source_scan_service

            row, created = await source_scan_service.ensure_source_scan_run(
                s,
                payload={
                    "limit": settings.SOURCE_SCAN_BATCH_SIZE,
                    "default_interval_minutes": settings.SOURCE_SCAN_DEFAULT_INTERVAL_MINUTES,
                    "duplicate_backoff_minutes": settings.SOURCE_SCAN_DUPLICATE_BACKOFF_MINUTES,
                    "max_videos": settings.YOUTUBE_MAX_VIDEOS_PER_RUN,
                },
            )
            return {"created": created, "crawl_run_id": row.id if row else None}
        from ktc.services import feature_export_service

        # 오류를 흡수하는 legacy wrapper 대신 실제 실패를 Dagster에 전달한다.
        return {"changed": await feature_export_service.sync_feature_exports(s)}


@op
def source_scan(context, config: MaintenanceConfig):
    return cooperative(maintenance(config, "scan"))


@op
def feature_exports(context, config: MaintenanceConfig):
    return cooperative(maintenance(config, "export"))


@job(executor_def=executor, tags=rt.job_tags("concierge_source_scan"))
def concierge_source_scan():
    source_scan()


@job(executor_def=executor, tags=rt.job_tags("concierge_feature_exports"))
def concierge_feature_exports():
    feature_exports()


JOBS = [
    concierge_interactive,
    concierge_batch,
    concierge_source_scan,
    concierge_feature_exports,
]


def active(context, name):
    return call_with_deadline(
        lambda: has_active_run(
            context.instance,
            job_name=name,
            project=rt.PROJECT,
            location_name=rt.location(),
        ),
        timeout_seconds=5,
    )


async def pending_page(lane, after):
    async with rt.database() as factory:
        return await rt.page(factory, lane=lane, after=after)


async def exhaust(row, generation):
    async with rt.database() as factory:
        return await rt.exhaust_dispatch(factory, row, generation)


@sensor(
    name=rt.DISPATCH_NAME,
    jobs=JOBS[:2],
    minimum_interval_seconds=15,
    default_status=DefaultSensorStatus.RUNNING,
)
def concierge_dispatch(context):
    control = asyncio.run(rt.control_snapshot())
    if control.backend != "dagster" or not get_settings().SCHEDULER_ENABLED:
        return SkipReason("실행 backend가 Dagster가 아니거나 중지됐습니다")
    cursor = json.loads(context.cursor or "{}")
    requests = []
    deadline = time.monotonic() + 25
    lanes = list(rt.LANE_JOBS.items())
    first = cursor.get("next_lane", lanes[0][0])
    index = next((i for i, item in enumerate(lanes) if item[0] == first), 0)
    lanes = lanes[index:] + lanes[:index]
    # 한 lane의 UNKNOWN backlog가 다음 lane의 조회 기회를 영구 독점하지 않는다.
    cursor["next_lane"] = lanes[1][0]
    for lane, name in lanes:
        if time.monotonic() >= deadline:
            break
        if active(context, name):
            continue
        rows = asyncio.run(pending_page(lane, int(cursor.get(lane, 0))))
        processed = 0
        for row in rows:
            if time.monotonic() >= deadline:
                break
            processed += 1
            cursor[lane] = row.id
            if row.cancel_requested:

                async def cancel(candidate=row):
                    async with rt.database() as factory:
                        return await rt.cancel_pending(
                            factory, candidate, control.generation
                        )

                asyncio.run(cancel())
                continue
            try:
                history = rt.history(context.instance, row, control.generation)
            except Exception as exc:  # noqa: BLE001 - UNKNOWN을 넘겨 다음 keyset 행을 처리한다
                context.log.warning(
                    "발화 metadata UNKNOWN(row=%s, %s)", row.id, type(exc).__name__
                )
                continue
            latest = history[0] if history else None
            if latest and latest.status == DagsterRunStatus.CANCELED:

                async def native_cancel(candidate=row):
                    async with rt.database() as factory:
                        return await rt.cancel_pending(
                            factory, candidate, control.generation, native_cancel=True
                        )

                asyncio.run(native_cancel())
                continue
            if latest and latest.status == DagsterRunStatus.NOT_STARTED:
                predecessor = latest.tags.get(rt.PREDECESSOR_TAG, "")
                key = rt.run_key(row, predecessor)
                if not predecessor or latest.tags.get("dagster/run_key") != key:
                    raise RuntimeError("미제출 실행의 원래 key를 확인할 수 없습니다")
                if latest.tags.get(rt.CONTROL_TAG) != str(control.generation):
                    raise RuntimeError("미제출 실행의 전환 세대가 일치하지 않습니다")
            else:
                if latest and not latest.is_finished:
                    continue
                if len(history) >= rt.MAX_DISPATCH_RUNS:
                    asyncio.run(exhaust(row, control.generation))
                    continue
                predecessor = latest.run_id if latest else "root"
                key = rt.run_key(row, predecessor)
            requests.append(
                RunRequest(
                    run_key=key,
                    job_name=name,
                    run_config={
                        "ops": {
                            "interactive_run"
                            if lane == "interactive"
                            else "batch_run": {
                                "config": {
                                    "run_id": row.id,
                                    "retry_count": row.retry,
                                    "attempt": row.attempt,
                                    "control_generation": control.generation,
                                }
                            }
                        }
                    },
                    tags=rt.dispatch_tags(row, control.generation, predecessor),
                )
            )
            break
        if processed == len(rows) and len(rows) < rt.PAGE_SIZE:
            cursor[lane] = 0
    return SensorResult(run_requests=requests, cursor=json.dumps(cursor))


async def owned_page(after):
    async with rt.database() as factory:
        return await rt.page(factory, after=after, owned=True)


async def reclaim(row, native):
    async with rt.database() as factory:
        return await rt.reconcile_one(factory, row, native)


def reconcile(context):
    after = int(context.cursor or "0")
    rows = asyncio.run(owned_page(after))
    recovered = 0
    processed = 0
    deadline = time.monotonic() + 25
    for row in rows:
        if time.monotonic() >= deadline:
            break
        processed += 1
        after = row.id
        try:
            native = rt.metadata(context.instance, row.owner)
        except Exception as exc:  # noqa: BLE001 - 조회 실패는 사망이 아니며 다음 page도 순회한다
            context.log.warning(
                "회수 metadata UNKNOWN(row=%s, %s)", row.id, type(exc).__name__
            )
            continue
        recovered += int(asyncio.run(reclaim(row, native)))
    if processed == len(rows) and len(rows) < rt.PAGE_SIZE:
        after = 0
    context.update_cursor(str(after))
    return recovered


concierge_recovery = reconciliation_sensor(
    name="concierge_recovery", reconcile=reconcile, required_resource_keys=set()
)


@sensor(
    jobs=JOBS[2:],
    minimum_interval_seconds=30,
    default_status=DefaultSensorStatus.RUNNING,
)
def concierge_maintenance(context):
    control = asyncio.run(rt.control_snapshot())
    settings = get_settings()
    if control.backend != "dagster" or not settings.SCHEDULER_ENABLED:
        return SkipReason("실행 backend가 Dagster가 아니거나 중지됐습니다")
    previous = json.loads(context.cursor or "{}")
    requests = []
    now = time.time()
    for name, op_name, enabled, interval in [
        (
            "concierge_source_scan",
            "source_scan",
            settings.SOURCE_SCAN_ENABLED,
            settings.SOURCE_SCAN_INTERVAL_SECONDS,
        ),
        (
            "concierge_feature_exports",
            "feature_exports",
            settings.FEATURE_EXPORT_RECONCILE_ENABLED,
            settings.FEATURE_EXPORT_RECONCILE_INTERVAL_SECONDS,
        ),
    ]:
        if not enabled or active(context, name):
            continue
        last = float(previous.get(name, 0))
        if last and now - last < interval:
            continue
        # cursor는 sensor tick의 durable run-request 인계와 함께 저장된다. 첫 발화는 즉시다.
        key = f"{name}:{control.generation}:{int(last)}"
        requests.append(
            RunRequest(
                run_key=key,
                job_name=name,
                run_config={
                    "ops": {
                        op_name: {"config": {"control_generation": control.generation}}
                    }
                },
                tags={**rt.job_tags(name), rt.CONTROL_TAG: str(control.generation)},
            )
        )
        previous[name] = now
    return SensorResult(run_requests=requests, cursor=json.dumps(previous))


defs = Definitions(
    jobs=JOBS, sensors=[concierge_dispatch, concierge_recovery, concierge_maintenance]
)
