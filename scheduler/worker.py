"""APScheduler 단일 실행자.

Web REST, MCP, 정기 크롤이 공유하는 `crawl_runs` 테이블에서 `pending` 작업을
단일 claim 방식으로 가져와 async ETL 파이프라인을 실행한다(ADR-13, T-010).
Celery / Redis / RabbitMQ / PostgreSQL Advisory Lock은 초기 범위에서 제외한다.

구조:
    - `run_once`: 테스트 가능한 1회 tick. stale 재투입 -> pending claim -> 실행.
    - `execute_run`: claim된 작업을 handler에 위임하고 done/failed 상태를 기록.
    - `worker_loop`: APScheduler `interval` job으로 `run_once`를 반복 실행.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.database import async_session_factory, init_db
from app.etl.pipeline import run_harvest
from app.etl.youtube_client import YouTubeClient
from app.models import CrawlRun
from app.services import crawl_run_service

JobHandler = Callable[[AsyncSession, CrawlRun], Awaitable[dict[str, Any]]]


def load_payload(run: CrawlRun) -> dict[str, Any]:
    """`crawl_runs.payload_json`을 dict로 파싱한다."""
    if not run.payload_json:
        return {}
    try:
        payload = json.loads(run.payload_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"잘못된 payload_json: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValueError("payload_json은 JSON object여야 한다")
    return payload


def _max_videos_from_payload(payload: Mapping[str, Any]) -> int:
    settings = get_settings()
    raw = payload.get("max_videos", settings.YOUTUBE_MAX_VIDEOS_PER_RUN)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = settings.YOUTUBE_MAX_VIDEOS_PER_RUN
    return max(1, min(value, settings.YOUTUBE_MAX_VIDEOS_PER_RUN))


async def harvest_handler(session: AsyncSession, run: CrawlRun) -> dict[str, Any]:
    """기본 `harvest` 작업 handler.

    keyword/channel/playlist target을 모두 같은 수집·상세조회·ranking·ingest 경로로
    처리한다(T-019).
    """
    payload = load_payload(run)
    target_type = run.target_type or "keyword"
    query = payload.get("query") or (run.target_id if target_type == "keyword" else None)
    channel_id = payload.get("channel_id") or (
        run.target_id if target_type == "channel" else None
    )
    playlist_id = payload.get("playlist_id") or (
        run.target_id if target_type == "playlist" else None
    )

    if target_type == "keyword" and not query:
        raise ValueError("keyword harvest 작업에는 query 또는 target_id가 필요하다")
    if target_type == "channel" and not channel_id:
        raise ValueError("channel harvest 작업에는 channel_id 또는 target_id가 필요하다")
    if target_type == "playlist" and not playlist_id:
        raise ValueError("playlist harvest 작업에는 playlist_id 또는 target_id가 필요하다")
    if target_type not in ("keyword", "channel", "playlist"):
        raise ValueError(f"지원하지 않는 harvest target_type: {target_type}")

    settings = get_settings()
    async with httpx.AsyncClient(timeout=30.0) as http_client:
        client = YouTubeClient(api_key=settings.YOUTUBE_API_KEY, http_client=http_client)
        return await run_harvest(
            session,
            client,
            seed_keyword=str(query) if query else None,
            channel_id=str(channel_id) if channel_id else None,
            playlist_id=str(playlist_id) if playlist_id else None,
            max_videos=_max_videos_from_payload(payload),
        )


DEFAULT_HANDLERS: dict[str, JobHandler] = {
    "harvest": harvest_handler,
}


async def _heartbeat_loop(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: int,
    *,
    interval_seconds: float,
) -> None:
    """장시간 작업 중 heartbeat를 주기적으로 갱신한다."""
    while True:
        await asyncio.sleep(interval_seconds)
        async with session_factory() as session:
            await crawl_run_service.heartbeat(session, run_id)


async def execute_run(
    session_factory: async_sessionmaker[AsyncSession],
    run: CrawlRun,
    *,
    handlers: Mapping[str, JobHandler] | None = None,
    heartbeat_interval_seconds: float | None = None,
) -> None:
    """claim된 작업 1건을 실행하고 완료/실패 상태를 기록한다."""
    handler = (handlers or DEFAULT_HANDLERS).get(run.job_type)
    if handler is None:
        async with session_factory() as session:
            await crawl_run_service.mark_failed(
                session, run.id, error=f"지원하지 않는 job_type: {run.job_type}"
            )
        return

    settings = get_settings()
    heartbeat_interval = (
        heartbeat_interval_seconds
        if heartbeat_interval_seconds is not None
        else settings.SCHEDULER_HEARTBEAT_INTERVAL_SECONDS
    )
    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(session_factory, run.id, interval_seconds=heartbeat_interval)
    )
    try:
        async with session_factory() as session:
            await crawl_run_service.heartbeat(session, run.id, progress=0.1)
            fresh_run = await crawl_run_service.get_run(session, run.id)
            if fresh_run is None:
                raise RuntimeError(f"claim된 작업을 다시 조회할 수 없음: {run.id}")
            result = await handler(session, fresh_run)
            await crawl_run_service.heartbeat(session, run.id, progress=0.9)
            await crawl_run_service.mark_done(session, run.id, result=result)
    except Exception as exc:
        async with session_factory() as session:
            await crawl_run_service.mark_failed(session, run.id, error=str(exc))
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task


async def run_once(
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
    *,
    handlers: Mapping[str, JobHandler] | None = None,
    stale_threshold_seconds: int | None = None,
    max_retries: int | None = None,
    heartbeat_interval_seconds: float | None = None,
) -> int | None:
    """스케줄러 tick 1회.

    반환값은 claim하여 실행한 `crawl_runs.id`이며, 실행할 작업이 없으면 None이다.
    """
    settings = get_settings()
    async with session_factory() as session:
        await crawl_run_service.requeue_stale(
            session,
            threshold_seconds=(
                stale_threshold_seconds
                if stale_threshold_seconds is not None
                else settings.SCHEDULER_STALE_THRESHOLD_SECONDS
            ),
            max_retries=(
                max_retries if max_retries is not None else settings.SCHEDULER_MAX_RETRIES
            ),
        )
        run = await crawl_run_service.claim_next_pending(session)

    if run is None:
        return None

    await execute_run(
        session_factory,
        run,
        handlers=handlers,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
    )
    return run.id


async def worker_loop(
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
    *,
    handlers: Mapping[str, JobHandler] | None = None,
) -> None:
    """APScheduler interval job으로 `run_once`를 반복 실행한다."""
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore
    except ImportError as exc:
        raise RuntimeError("APScheduler가 설치되어 있지 않다") from exc

    settings = get_settings()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_once,
        "interval",
        seconds=settings.SCHEDULER_POLL_INTERVAL_SECONDS,
        kwargs={"session_factory": session_factory, "handlers": handlers},
        id="crawl-run-worker",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()

    # 시작 직후 1회 실행해 배포 직후 pending 작업을 즉시 처리한다.
    await run_once(session_factory, handlers=handlers)

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        scheduler.shutdown(wait=False)


async def amain() -> None:
    """비동기 엔트리포인트."""
    settings = get_settings()
    if not settings.SCHEDULER_ENABLED:
        print("[Scheduler] SCHEDULER_ENABLED=false 이므로 실행자를 시작하지 않는다.")
        return
    await init_db()
    print(
        "[Scheduler] APScheduler 단일 실행자 시작 "
        f"(poll={settings.SCHEDULER_POLL_INTERVAL_SECONDS}s, "
        f"stale={settings.SCHEDULER_STALE_THRESHOLD_SECONDS}s, "
        f"max_retries={settings.SCHEDULER_MAX_RETRIES})"
    )
    await worker_loop()


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
