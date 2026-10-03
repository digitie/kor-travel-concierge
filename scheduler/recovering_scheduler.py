"""APScheduler의 DB 오류 뒤에도 다음 실행 타이머를 유지한다."""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.exc import DisconnectionError, InterfaceError, OperationalError

logger = logging.getLogger(__name__)


class RecoveringAsyncIOScheduler(AsyncIOScheduler):
    """APScheduler 3의 job store 연결 오류를 기존 재시도 주기로 복구한다."""

    def _process_jobs(self) -> float | None:
        # wakeup()은 기존 타이머를 취소한 뒤 이 반환값으로 다음 타이머를 등록한다.
        # update_job/remove_job/get_next_run_time 오류가 밖으로 나가면 등록이 생략된다.
        try:
            return super()._process_jobs()
        except (OperationalError, InterfaceError, DisconnectionError) as exc:
            # DB 예외 원문은 SQL·접속 정보를 담을 수 있어 예외 종류만 기록한다.
            logger.warning(
                "스케줄러 DB 연결 오류(%s): %s초 뒤 예약 처리를 재시도합니다.",
                type(exc).__name__,
                self.jobstore_retry_interval,
            )
            return self.jobstore_retry_interval
