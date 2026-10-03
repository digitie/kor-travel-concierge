"""APScheduler 3의 비동기 작업을 종료 전에 기다리고 정리한다."""

import asyncio
import logging

from apscheduler.executors.asyncio import AsyncIOExecutor

logger = logging.getLogger(__name__)


class DrainingAsyncIOExecutor(AsyncIOExecutor):
    """종료를 호출하기 전에 진행 중 coroutine의 정리를 기다린다."""

    async def drain(self, grace_seconds: float) -> None:
        # APScheduler 3의 shutdown(wait=True)는 실제로도 즉시 cancel한다.
        # 이 executor가 소유한 future만 먼저 기다려 unrelated task를 건드리지 않는다.
        pending = set(self._pending_futures)
        if not pending:
            return
        _, pending = await asyncio.wait(pending, timeout=grace_seconds)
        if pending:
            logger.info("종료 대기 시간이 지나 작업 %s건을 정리합니다.", len(pending))
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
