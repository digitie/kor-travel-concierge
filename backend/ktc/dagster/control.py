"""명시적 drain 후 실행 backend를 전환한다. production 자동 전환은 하지 않는다."""

import asyncio
import json

from kortravelcommon.dagster import PROJECT_TAG
from kortravelcommon.deadline import call_with_deadline

from dagster import DagsterInstance, DagsterRunStatus, RunsFilter
from ktc.dagster import runtime as rt
from ktc.services.scheduler_control import read_control, switch_backend


async def change(backend, expected_generation):
    # native metadata 확인은 domain transaction 밖이다. 오류/active는 fail-closed다.
    with DagsterInstance.get() as instance:
        native = call_with_deadline(
            lambda: instance.get_runs(
                filters=RunsFilter(
                    tags={
                        PROJECT_TAG: rt.PROJECT,
                        "dagster/code_location": rt.location(),
                    },
                    statuses=[
                        DagsterRunStatus.NOT_STARTED,
                        DagsterRunStatus.QUEUED,
                        DagsterRunStatus.STARTING,
                        DagsterRunStatus.STARTED,
                        DagsterRunStatus.CANCELING,
                    ],
                ),
                limit=1,
            ),
            timeout_seconds=5,
        )
        if native:
            raise ValueError("Dagster 활성/미제출 실행을 drain한 뒤 전환하세요")
        async with rt.database() as factory:
            # terminal owned pending만 확인·인계한다. running과 UNKNOWN은 자동 인계하지 않는다.
            after = 0
            while True:
                rows = await rt.page(factory, after=after, owned=True)
                for row in rows:
                    if row.state == "pending":
                        await rt.reconcile_one(
                            factory, row, rt.metadata(instance, row.owner)
                        )
                if len(rows) < rt.PAGE_SIZE:
                    break
                after = rows[-1].id
            async with factory() as s:
                return await switch_backend(s, backend, expected_generation)


async def status():
    async with rt.database() as factory, factory() as s:
        return await read_control(s)


def main(backend=None, expected_generation=None):
    result = asyncio.run(
        status() if backend is None else change(backend, expected_generation)
    )
    print(json.dumps({"backend": result.backend, "generation": result.generation}))
    return 0
