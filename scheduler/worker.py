"""APScheduler 단일 실행자 (스캐폴드).

Web REST, MCP, 정기 크롤이 공유하는 `crawl_runs` 테이블에서 `pending` 작업을
단일 claim 방식으로 가져와 async ETL 파이프라인을 실행한다(ADR-13, T-010).
Celery / Redis / RabbitMQ / Advisory Lock은 초기 범위에서 제외한다.

구현 대상(T-010):
    - pending 작업 단일 claim (상태 pending -> running 원자적 전이)
    - heartbeat / progress / retry_count / last_error 갱신
    - stale(heartbeat 만료) 작업 재투입, 최대 재시도 초과 격리
    - blocking 작업(yt-dlp / faster-whisper / FFmpeg)은 executor로 격리
"""

from __future__ import annotations

import asyncio

from app.core.config import get_settings


async def claim_pending_run() -> dict | None:
    """`crawl_runs`에서 pending 작업 1건을 claim한다 (T-010에서 구현)."""
    # Placeholder: 원자적 UPDATE ... WHERE state='pending' 후 RETURNING.
    return None


async def execute_run(run: dict) -> None:
    """claim한 작업에 대해 async ETL 파이프라인을 실행한다 (T-010에서 구현)."""
    # Placeholder: etl.runner의 async 파이프라인 호출.
    _ = run


async def worker_loop() -> None:
    """단일 실행자 메인 루프."""
    settings = get_settings()
    interval_days = settings.CRAWL_DEFAULT_INTERVAL_DAYS
    print(
        "[Scheduler] APScheduler 단일 실행자 구동 (스캐폴드). "
        f"default_interval_days={interval_days}, "
        f"max_concurrent_videos={settings.CRAWL_MAX_CONCURRENT_VIDEOS}"
    )
    while True:
        run = await claim_pending_run()
        if run is None:
            await asyncio.sleep(5)
            continue
        await execute_run(run)


def main() -> None:
    settings = get_settings()
    if not settings.SCHEDULER_ENABLED:
        print("[Scheduler] SCHEDULER_ENABLED=false 이므로 실행자를 시작하지 않는다.")
        return
    asyncio.run(worker_loop())


if __name__ == "__main__":
    main()
