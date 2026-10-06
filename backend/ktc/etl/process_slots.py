"""Linux process 간 provider 동시성과 1GiB 메모리 예약. FD 수명은 자식까지 이어진다."""

import asyncio
import fcntl
import math
import os
import stat
from contextlib import asynccontextmanager
from pathlib import Path

MEMORY_UNIT_MB = 256
MEMORY_UNITS = 4


def open_lock(directory, name):
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise RuntimeError("provider 슬롯 디렉터리 소유권/권한이 올바르지 않습니다")
    fd = os.open(
        directory / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
    )
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        os.close(fd)
        raise RuntimeError("provider 슬롯 파일 소유권/권한이 올바르지 않습니다")
    return fd


def try_lock(fd):
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


@asynccontextmanager
async def reserve(directory, *, whisper, memory_mb, caption_limit=3, wait_seconds=120):
    units = math.ceil(memory_mb / MEMORY_UNIT_MB)
    if units < 1 or units > MEMORY_UNITS:
        raise ValueError("provider 메모리 예약은 1~1024MiB만 허용합니다")
    # 개별 guard 상한을 낮춰도 모델 bootstrap은 캡션과 겹치지 않는다.
    if whisper:
        units = MEMORY_UNITS
    provider = "whisper" if whisper else "caption"
    deadline = asyncio.get_running_loop().time() + wait_seconds
    held = []
    try:
        while not held:
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("provider 공유 슬롯 대기 시간 초과")
            gate = open_lock(directory, "admission.lock")
            candidate = []
            try:
                if try_lock(gate):
                    for i in range(1 if whisper else min(3, max(1, caption_limit))):
                        fd = open_lock(directory, f"{provider}-{i}.lock")
                        if try_lock(fd):
                            candidate.append(fd)
                            break
                        os.close(fd)
                    if candidate:
                        for i in range(MEMORY_UNITS):
                            fd = open_lock(directory, f"memory-{i}.lock")
                            if try_lock(fd):
                                candidate.append(fd)
                            else:
                                os.close(fd)
                            if len(candidate) == units + 1:
                                held, candidate = candidate, []
                                break
            finally:
                for fd in candidate:
                    os.close(fd)
                os.close(gate)
            if not held:
                await asyncio.sleep(0.05)
        yield tuple(held)
    finally:
        # LOCK_UN은 같은 OFD를 상속한 자식의 예약까지 풀어 버린다. 마지막 close가 반환한다.
        for fd in held:
            os.close(fd)
