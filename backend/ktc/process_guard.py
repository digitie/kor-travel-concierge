"""heavy import 없는 Linux supervisor. 부모 EOF/child 종료에도 소유 group만 회수한다."""

import ctypes
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path


def members(group):
    for entry in Path("/proc").glob("[0-9]*"):
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            if int(fields[2]) == group:
                yield int(entry.name), fields
        except (OSError, ValueError, IndexError):
            continue


def rss_mb(group):
    total = 0
    for pid, _ in members(group):
        try:
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    total += int(line.split()[1])
                    break
        except (OSError, ValueError):
            pass
    return total / 1024


def pidfd_open(pid):
    if hasattr(os, "pidfd_open"):
        return os.pidfd_open(pid)
    # manylinux CPython은 오래된 glibc로 빌드돼 os wrapper가 빠질 수 있다.
    # 실행 중인 Linux libc의 동일 API를 쓰며 syscall 번호를 재구현하지 않는다.
    libc = ctypes.CDLL(None, use_errno=True)
    fd = libc.pidfd_open(ctypes.c_int(pid), ctypes.c_uint(0))
    if fd < 0:
        raise OSError(ctypes.get_errno(), "pidfd_open")
    return fd


def send_kill(fd):
    if hasattr(signal, "pidfd_send_signal"):
        signal.pidfd_send_signal(fd, signal.SIGKILL)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if (
        libc.pidfd_send_signal(
            ctypes.c_int(fd), ctypes.c_int(signal.SIGKILL), None, ctypes.c_uint(0)
        )
        != 0
    ):
        raise OSError(ctypes.get_errno(), "pidfd_send_signal")


def kill_owned_members(group):
    # 살아 있는 session leader가 group identity를 고정한다. pidfd는 열람~신호 PID 재사용도 막는다.
    if group != os.getpid() or os.getpgrp() != group:
        raise RuntimeError("supervisor process group identity 불일치")
    deadline = time.monotonic() + 3
    while True:
        living = 0
        for pid, fields in members(group):
            if pid == group or fields[0] == "Z":
                continue
            living += 1
            try:
                fd = pidfd_open(pid)
                try:
                    fields = (
                        Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
                    )
                    if int(fields[2]) == group:
                        send_kill(fd)
                finally:
                    os.close(fd)
            except (OSError, ValueError, IndexError):
                pass
        if not living:
            return
        if time.monotonic() >= deadline:
            # 정리가 불확실하면 자기 group 전체를 끝내며 마지막 예약도 반환한다.
            os.killpg(group, signal.SIGKILL)
        time.sleep(0.01)


def arm_parent_death(expected):
    """Python signal handler를 기다리지 않고 provider 본체를 커널이 종료한다."""
    if os.getpgrp() != expected:
        raise RuntimeError("provider group identity 불일치")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "PR_SET_PDEATHSIG")
    if os.getppid() != expected:
        os.killpg(os.getpgrp(), signal.SIGKILL)


def protect_provider():
    """provider bootstrap의 이중 확인. guardian의 fork 직후에도 이미 설치된다."""
    arm_parent_death(int(os.environ.pop("KTC_PROVIDER_GUARD_PID")))


def start_watchdog(control_fd):
    """guardian 사망 EOF를 별도 stdlib 프로세스가 감지해 C 함수 안의 손자도 회수한다.

    watchdog이 같은 group에 남아 group identity를 고정하므로 PID 재사용으로 다른
    group을 죽이지 않는다. 쓰기 FD는 guardian만 가지고 provider에는 전달하지 않는다.
    """
    read, write = os.pipe2(os.O_CLOEXEC)
    pid = os.fork()
    if pid == 0:
        os.close(write)
        os.close(control_fd)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        try:
            while os.read(read, 1):
                pass
        finally:
            os.killpg(os.getpgrp(), signal.SIGKILL)
        os._exit(1)
    os.close(read)
    return pid, write


def main():
    read_fd, slots, memory, timeout, *command = sys.argv[1:]
    read_fd = int(read_fd)
    slot_fds = tuple(int(value) for value in slots.split(","))
    group = os.getpid()
    if os.getpgrp() != group:
        raise RuntimeError("supervisor는 새 session에서 실행해야 합니다")
    stopped = False

    def stop(_signal, _frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    watchdog, watchdog_write = start_watchdog(read_fd)
    child = subprocess.Popen(
        command,
        pass_fds=slot_fds,
        # guardian은 stdlib 단일 thread다. exec 전부터 parent-death fence를 설치한다.
        preexec_fn=lambda: arm_parent_death(group),  # noqa: PLW1509 - stdlib 단일 thread guardian
        env=dict(os.environ, KTC_PROVIDER_GUARD_PID=str(group)),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    started = time.monotonic()
    code = 1
    try:
        while not stopped:
            code = child.poll()
            if code is not None:
                break
            if time.monotonic() - started > float(timeout):
                code = 124
                break
            if rss_mb(group) > float(memory):
                code = 137
                break
            if select.select([read_fd], [], [], 0.2)[0] and os.read(read_fd, 1) == b"":
                code = 1
                break
    finally:
        kill_owned_members(group)
        child.wait(timeout=3)
        os.close(watchdog_write)
        os.waitpid(watchdog, 0)
        os.close(read_fd)
        for fd in slot_fds:
            os.close(fd)
    return code if isinstance(code, int) and code >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
