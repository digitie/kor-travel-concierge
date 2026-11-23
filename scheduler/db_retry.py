"""스케줄러 DB 작업의 제한된 백오프와 종료 가능한 복구 대기."""

import asyncio
import errno
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.exc import (
    DBAPIError,
    DisconnectionError,
    InterfaceError,
    OperationalError,
    PendingRollbackError,
)

logger = logging.getLogger(__name__)
T = TypeVar("T")


def transient_root(exc: BaseException) -> BaseException:
    """PendingRollbackError면 그것이 가린 앞선 flush 실패를 돌려준다(기록·분류용)."""
    if isinstance(exc, PendingRollbackError) and exc.__context__ is not None:
        return exc.__context__
    return exc


def is_transient_database_error(exc: BaseException) -> bool:
    """인증·schema 오류를 제외하고 연결 장애·복구·트랜잭션 충돌만 재시도한다."""
    if transient_root(exc) is not exc:
        # 무효가 된 세션을 다시 쓴 오류다. 원인은 앞선 flush 실패(__context__)에 있다.
        return is_transient_database_error(transient_root(exc))
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if code:
            return str(code).startswith("08") or code in {
                "57P01",
                "57P02",
                "57P03",
                "40001",
                "40P01",
                # lock_timeout: 같은 행을 잠깐 쥔 다른 세션과의 경합이다(IO 정체 때 늘어남).
                "55P03",
            }
        current = getattr(current, "orig", None) or current.__cause__
    return (
        isinstance(
            exc, (OperationalError, InterfaceError, DisconnectionError, ConnectionError)
        )
        or (isinstance(exc, DBAPIError) and exc.connection_invalidated)
        or (
            isinstance(exc, OSError)
            and exc.errno in {errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ETIMEDOUT}
        )
    )


def retry_delay(attempt: int, *, base: float = 2) -> float:
    """2·4·8·16·30초 백오프. 장기 장애에서도 수치가 무한히 커지지 않는다."""
    return min(30, base * (2 ** min(max(attempt - 1, 0), 5)))


async def retry_database(
    operation: Callable[[], Awaitable[T]],
    *,
    context: str,
    max_retries: int | None = None,
    stop: asyncio.Event | None = None,
) -> T | None:
    """매 시도마다 새 연결·세션을 여는 작업에만 사용한다. None 한도는 복구 대기다."""
    failures = 0
    while stop is None or not stop.is_set():
        try:
            return await operation()
        except Exception as exc:
            # operation은 DB 처리이므로 driver의 원시 연결 timeout도 재시도한다.
            if not isinstance(exc, TimeoutError) and not is_transient_database_error(
                exc
            ):
                raise
            if max_retries is not None and failures >= max_retries:
                raise
            failures += 1
            delay = retry_delay(failures)
            # SQL·접속 문자열·비밀이 들어갈 수 있는 원문은 기록하지 않는다.
            logger.warning(
                "%s DB 일시 오류(%s): %s초 뒤 재시도(%s).",
                context,
                type(exc).__name__,
                delay,
                failures,
            )
            if stop is None:
                await asyncio.sleep(delay)
            else:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
    return None
