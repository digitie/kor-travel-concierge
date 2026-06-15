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
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ktc.core.config import get_settings
from ktc.core.database import async_session_factory, init_db
from ktc.etl import deep_research_service, video_analysis_service
from ktc.etl.pipeline import run_harvest
from ktc.etl.postprocess_service import process_harvest_videos
from ktc.etl.youtube_client import YouTubeClient
from ktc.models import (
    CrawlRun,
    VideoAnalysisRunState,
    VideoAnalysisRunType,
    YoutubeVideo,
    YoutubeVideoAnalysisRun,
)
from ktc.services import crawl_run_service, place_service, source_scan_service

JobHandler = Callable[[AsyncSession, CrawlRun], Awaitable[dict[str, Any]]]
logger = logging.getLogger(__name__)


def scheduler_jobstore_url(database_url: str, explicit_url: str | None = None) -> str:
    """APScheduler SQLAlchemyJobStore용 sync DB URL을 반환한다."""
    if explicit_url:
        return explicit_url
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def should_use_persistent_jobstore(
    session_factory: async_sessionmaker[AsyncSession],
    handlers: Mapping[str, JobHandler] | None,
) -> bool:
    """기본 운영 실행 경로에서만 persistent APScheduler job store를 사용한다."""
    settings = get_settings()
    return (
        settings.SCHEDULER_JOBSTORE_ENABLED
        and session_factory is async_session_factory
        and handlers is None
    )


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


def _max_sources_from_payload(payload: Mapping[str, Any]) -> int:
    raw = payload.get("max_sources", 8)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 8
    return max(1, min(value, 20))


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
        client = YouTubeClient(
            api_key=settings.YOUTUBE_API_KEY,
            http_client=http_client,
            quota_budget_units=settings.YOUTUBE_SEARCH_DAILY_BUDGET_UNITS,
        )

        async def report_status(message: str, progress: float | None = None) -> None:
            await crawl_run_service.append_status_log(
                session,
                run.id,
                message,
                progress=progress,
            )

        await report_status("수집 작업 입력값을 검증했습니다.", 0.12)
        harvest_summary = await run_harvest(
            session,
            client,
            seed_keyword=str(query) if query else None,
            channel_id=str(channel_id) if channel_id else None,
            playlist_id=str(playlist_id) if playlist_id else None,
            max_videos=_max_videos_from_payload(payload),
            status_reporter=report_status,
        )
        if payload.get("skip_transcript"):
            collected = harvest_summary.get("video_ids") or []
            await report_status(
                f"영상 {len(collected)}개 수집을 완료했습니다. "
                "자막 생성은 확인 후 별도 작업으로 실행됩니다.",
                1.0,
            )
            return {**harvest_summary, "transcript_skipped": True}
        postprocess_summary = await process_harvest_videos(
            session,
            video_ids=harvest_summary.get("video_ids") or [],
            limit=_max_videos_from_payload(payload),
            status_reporter=report_status,
        )
        return {**harvest_summary, "postprocess": postprocess_summary}


async def transcript_handler(session: AsyncSession, run: CrawlRun) -> dict[str, Any]:
    """수집 완료된 영상에 자막·POI·지오코딩 후처리를 적용하는 handler.

    `harvest`에서 `skip_transcript`로 수집만 끝낸 뒤, 사용자 확인을 거쳐 생성되는
    `transcript` 작업을 처리한다(자막 생성 게이팅).
    """
    payload = load_payload(run)
    video_ids = [str(v) for v in (payload.get("video_ids") or [])]
    if not video_ids:
        raise ValueError("transcript 작업에는 video_ids가 필요하다")

    async def report_status(message: str, progress: float | None = None) -> None:
        await crawl_run_service.append_status_log(
            session, run.id, message, progress=progress
        )

    await report_status("자막·장소 추출 작업을 시작합니다.", 0.05)
    postprocess_summary = await process_harvest_videos(
        session,
        video_ids=video_ids,
        limit=len(video_ids),
        status_reporter=report_status,
    )
    return {"video_ids": video_ids, "postprocess": postprocess_summary}


async def deep_research_handler(session: AsyncSession, run: CrawlRun) -> dict[str, Any]:
    """장소 기준 `deep_research` 작업 handler."""
    payload = load_payload(run)
    if run.target_type != "place":
        raise ValueError("deep_research 작업에는 target_type=place가 필요하다")
    if not run.target_id:
        raise ValueError("deep_research 작업에는 target_id(place_id)가 필요하다")
    try:
        place_id = int(run.target_id)
    except ValueError as exc:
        raise ValueError("deep_research target_id는 place_id 정수여야 한다") from exc

    place = await place_service.get_place(session, place_id)
    if place is None:
        raise ValueError(f"place not found: {place_id}")

    async def report_status(message: str, progress: float | None = None) -> None:
        await crawl_run_service.append_status_log(
            session,
            run.id,
            message,
            progress=progress,
        )

    return await deep_research_service.research_place(
        session,
        place,
        prompt=payload.get("prompt") if isinstance(payload.get("prompt"), str) else None,
        max_sources=_max_sources_from_payload(payload),
        status_reporter=report_status,
    )


def _int_from_payload(
    payload: Mapping[str, Any],
    key: str,
    default: int,
    *,
    minimum: int = 1,
    maximum: int | None = None,
) -> int:
    raw = payload.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    if maximum is not None:
        value = min(value, maximum)
    return max(minimum, value)


async def source_scan_handler(session: AsyncSession, run: CrawlRun) -> dict[str, Any]:
    """active source target을 스캔해 후속 작업을 enqueue한다."""
    payload = load_payload(run)
    settings = get_settings()
    await crawl_run_service.append_status_log(
        session,
        run.id,
        "주기 수집 대상을 확인 중입니다.",
        progress=0.2,
    )
    summary = await source_scan_service.scan_due_targets(
        session,
        limit=_int_from_payload(
            payload,
            "limit",
            settings.SOURCE_SCAN_BATCH_SIZE,
            maximum=100,
        ),
        default_interval_minutes=_int_from_payload(
            payload,
            "default_interval_minutes",
            settings.SOURCE_SCAN_DEFAULT_INTERVAL_MINUTES,
            maximum=525_600,
        ),
        duplicate_backoff_minutes=_int_from_payload(
            payload,
            "duplicate_backoff_minutes",
            settings.SOURCE_SCAN_DUPLICATE_BACKOFF_MINUTES,
            maximum=1_440,
        ),
        max_videos=_max_videos_from_payload(payload),
        api_budget_group=(
            str(payload["api_budget_group"]) if payload.get("api_budget_group") else None
        ),
    )
    await crawl_run_service.append_status_log(
        session,
        run.id,
        f"source target {summary['scanned_targets']}건을 확인하고 "
        f"후속 작업 {summary['enqueued_runs']}건을 등록했습니다.",
        progress=0.75,
    )
    return summary


def _analysis_run_type_values(payload: Mapping[str, Any]) -> list[str]:
    raw = payload.get("analysis_run_types") or [VideoAnalysisRunType.URL_SUMMARY]
    if not isinstance(raw, list):
        raw = [raw]
    allowed = {item.value for item in VideoAnalysisRunType}
    values: list[str] = []
    for item in raw:
        value = str(item)
        if value in allowed and value not in values:
            values.append(value)
    values = values or [VideoAnalysisRunType.URL_SUMMARY.value]
    priority = {
        VideoAnalysisRunType.URL_SUMMARY.value: 10,
        VideoAnalysisRunType.RECONCILE.value: 20,
        VideoAnalysisRunType.TRANSCRIPT_EXTRACT.value: 30,
    }
    return sorted(values, key=lambda value: priority.get(value, 100))


async def _has_analysis_run(
    session: AsyncSession,
    *,
    video_id: str,
    run_type: str,
) -> bool:
    stmt = (
        select(YoutubeVideoAnalysisRun.id)
        .where(
            YoutubeVideoAnalysisRun.video_id == video_id,
            YoutubeVideoAnalysisRun.run_type == run_type,
            YoutubeVideoAnalysisRun.state.in_(
                [
                    VideoAnalysisRunState.PENDING,
                    VideoAnalysisRunState.RUNNING,
                    VideoAnalysisRunState.DONE,
                ]
            ),
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def _pending_analysis_runs(
    session: AsyncSession,
    *,
    video_id: str,
    run_type: str,
) -> list[YoutubeVideoAnalysisRun]:
    stmt = (
        select(YoutubeVideoAnalysisRun)
        .where(
            YoutubeVideoAnalysisRun.video_id == video_id,
            YoutubeVideoAnalysisRun.run_type == run_type,
            YoutubeVideoAnalysisRun.state == VideoAnalysisRunState.PENDING,
        )
        .order_by(YoutubeVideoAnalysisRun.id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def video_analysis_handler(session: AsyncSession, run: CrawlRun) -> dict[str, Any]:
    """영상 분석 실행 row를 보장하고 pending 분석을 실제 처리한다."""
    payload = load_payload(run)
    video_id = str(payload.get("video_id") or run.target_id or "")
    if run.target_type != "video" or not video_id:
        raise ValueError("video_analysis 작업에는 target_type=video와 video_id가 필요하다")
    video = await session.get(YoutubeVideo, video_id)
    if video is None:
        raise ValueError(f"video not found: {video_id}")

    created_run_ids: list[int] = []
    skipped = 0
    for run_type in _analysis_run_type_values(payload):
        if await _has_analysis_run(session, video_id=video_id, run_type=run_type):
            skipped += 1
            continue
        analysis_run = YoutubeVideoAnalysisRun(
            video_id=video_id,
            run_type=run_type,
            state=VideoAnalysisRunState.PENDING,
            prompt_version="t063-placeholder",
        )
        session.add(analysis_run)
        await session.flush()
        created_run_ids.append(analysis_run.id)
    await session.commit()

    executed_results: list[dict[str, Any]] = []
    skipped_unsupported = 0
    for run_type in _analysis_run_type_values(payload):
        pending_runs = await _pending_analysis_runs(
            session,
            video_id=video_id,
            run_type=run_type,
        )
        if run_type == VideoAnalysisRunType.URL_SUMMARY.value:
            for analysis_run in pending_runs:
                executed_results.append(
                    await video_analysis_service.run_url_summary_analysis(
                        session,
                        video,
                        analysis_run,
                    )
                )
        elif run_type == VideoAnalysisRunType.RECONCILE.value:
            for analysis_run in pending_runs:
                executed_results.append(
                    await video_analysis_service.run_reconcile_analysis(
                        session,
                        video,
                        analysis_run,
                    )
                )
        else:
            skipped_unsupported += len(pending_runs)

    failed = sum(
        1
        for item in executed_results
        if item.get("state") == VideoAnalysisRunState.FAILED.value
    )
    return {
        "video_id": video_id,
        "created_analysis_runs": len(created_run_ids),
        "skipped_existing_analysis_runs": skipped,
        "analysis_run_ids": created_run_ids,
        "executed_analysis_runs": len(executed_results),
        "failed_analysis_runs": failed,
        "skipped_unsupported_analysis_runs": skipped_unsupported,
        "analysis_results": executed_results,
    }


DEFAULT_HANDLERS: dict[str, JobHandler] = {
    "harvest": harvest_handler,
    "transcript": transcript_handler,
    "deep_research": deep_research_handler,
    "source_scan": source_scan_handler,
    "video_analysis": video_analysis_handler,
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
        try:
            async with session_factory() as session:
                await crawl_run_service.heartbeat(session, run_id)
        except Exception as exc:  # pragma: no cover - DB 상태에 따라 메시지가 달라진다.
            logger.warning("crawl_run heartbeat 갱신 실패(run_id=%s): %s", run_id, exc)


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
            await crawl_run_service.append_status_log(
                session, run.id, "작업 실행 환경을 준비 중입니다.", progress=0.1
            )
            fresh_run = await crawl_run_service.get_run(session, run.id)
            if fresh_run is None:
                raise RuntimeError(f"claim된 작업을 다시 조회할 수 없음: {run.id}")
            result = await handler(session, fresh_run)
            await crawl_run_service.append_status_log(
                session, run.id, "수집 결과를 정리 중입니다.", progress=0.9
            )
            await crawl_run_service.mark_done(session, run.id, result=result)
    except Exception as exc:
        async with session_factory() as session:
            await crawl_run_service.mark_failed(session, run.id, error=str(exc))
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("crawl_run heartbeat task 종료 중 예외(run_id=%s)", run.id)


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
    use_persistent_jobstore = should_use_persistent_jobstore(session_factory, handlers)
    scheduler_kwargs: dict[str, Any] = {"timezone": timezone.utc}
    if use_persistent_jobstore:
        try:
            from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "APScheduler persistent job store에는 SQLAlchemy jobstore 의존성이 필요하다"
            ) from exc
        scheduler_kwargs["jobstores"] = {
            "default": SQLAlchemyJobStore(
                url=scheduler_jobstore_url(
                    settings.DATABASE_URL,
                    settings.SCHEDULER_JOBSTORE_URL or None,
                ),
                tablename=settings.SCHEDULER_JOBSTORE_TABLE,
            )
        }
    scheduler = AsyncIOScheduler(**scheduler_kwargs)
    run_once_kwargs = (
        {}
        if use_persistent_jobstore
        else {"session_factory": session_factory, "handlers": handlers}
    )
    scheduler.add_job(
        run_once,
        "interval",
        seconds=settings.SCHEDULER_POLL_INTERVAL_SECONDS,
        next_run_time=datetime.now(timezone.utc),
        kwargs=run_once_kwargs,
        id="crawl-run-worker",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    if settings.SOURCE_SCAN_ENABLED:
        source_scan_kwargs = (
            {} if use_persistent_jobstore else {"session_factory": session_factory}
        )
        scheduler.add_job(
            enqueue_source_scan_once,
            "interval",
            seconds=settings.SOURCE_SCAN_INTERVAL_SECONDS,
            next_run_time=datetime.now(timezone.utc),
            kwargs=source_scan_kwargs,
            id="source-scan-enqueue",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
    scheduler.start()

    try:
        await asyncio.Event().wait()
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


async def enqueue_source_scan_once(
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
) -> int | None:
    """active source target scan 작업을 중복 없이 enqueue한다."""
    settings = get_settings()
    payload = {
        "limit": settings.SOURCE_SCAN_BATCH_SIZE,
        "default_interval_minutes": settings.SOURCE_SCAN_DEFAULT_INTERVAL_MINUTES,
        "duplicate_backoff_minutes": settings.SOURCE_SCAN_DUPLICATE_BACKOFF_MINUTES,
        "max_videos": settings.YOUTUBE_MAX_VIDEOS_PER_RUN,
    }
    async with session_factory() as session:
        run, created = await source_scan_service.ensure_source_scan_run(
            session,
            payload=payload,
        )
        return run.id if created and run is not None else None


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
