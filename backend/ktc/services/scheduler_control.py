"""claim과 전환을 직렬화한다. Dagster dependency 없이 API/legacy에서도 사용한다."""

from dataclasses import dataclass

from sqlalchemy import func, select, update

from ktc.models import CrawlRun, RunState, SchedulerControl

ADMISSION_LOCK = 1960030


@dataclass(frozen=True)
class Control:
    backend: str
    generation: int


async def read_control(session) -> Control:
    row = await session.get(SchedulerControl, 1, populate_existing=True)
    # create_all 테스트/bootstrap은 초기 legacy다. 운영에서는 migration이 row를 만든다.
    if row is None:
        from ktc.core.config import get_settings

        if not get_settings().is_local_env:
            raise RuntimeError(
                "scheduler_control 정본이 없습니다. migration을 확인하세요"
            )
        return Control("legacy", 0)
    return Control(row.backend, row.generation)


async def admitted(session, backend: str, generation: int | None = None) -> bool:
    await session.execute(select(func.pg_advisory_xact_lock_shared(ADMISSION_LOCK)))
    current = await read_control(session)
    return current.backend == backend and (
        generation is None or generation == current.generation
    )


async def switch_backend(session, backend: str, expected_generation: int) -> Control:
    if backend not in ("legacy", "dagster"):
        raise ValueError("지원하지 않는 실행 방식")
    await session.execute(select(func.pg_advisory_xact_lock(ADMISSION_LOCK)))
    current = await read_control(session)
    if current.generation != expected_generation:
        raise ValueError("전환 세대가 변경됐습니다. 현재 상태를 다시 확인하세요")
    if await session.scalar(
        select(CrawlRun.id).where(CrawlRun.state == RunState.RUNNING).limit(1)
    ):
        raise ValueError("실행 중 작업을 drain한 뒤 전환하세요")
    if await session.scalar(
        select(CrawlRun.id)
        .where(
            CrawlRun.state == RunState.PENDING,
            CrawlRun.orchestrator_run_id.is_not(None),
        )
        .limit(1)
    ):
        raise ValueError("Dagster 소유 pending을 먼저 회수하세요")
    row = await session.get(SchedulerControl, 1)
    if row is None:
        row = SchedulerControl(
            id=1, backend=current.backend, generation=current.generation
        )
        session.add(row)
    if current.backend != backend:
        row.backend = backend
        row.generation += 1
        # 모든 미실행 request의 attempt도 바꿔 옛 sensor run-key와 claim을 무효화한다.
        await session.execute(
            update(CrawlRun)
            .where(CrawlRun.state == RunState.PENDING)
            .values(orchestrator_attempt=CrawlRun.orchestrator_attempt + 1)
        )
    await session.commit()
    return Control(row.backend, row.generation)
