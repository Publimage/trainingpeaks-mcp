"""One local-process exclusion primitive shared by existing publishers."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat
import time


class FileLockBusy(RuntimeError):
    pass


@contextmanager
def locked_descriptor(fd: int, *, timeout: float = 0):
    """Bounded exclusion on an already validated descriptor; never take over."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError as exc:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FileLockBusy("LOCAL_WORKER_ACTIVE") from exc
            time.sleep(min(0.01, remaining))
    try:
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def exclusive_file_lock(path: Path):
    """Hold an owner-only regular lock file; never unlink or expire it.

    This is local POSIX exclusion, not a distributed/network filesystem claim.
    Yield the inode identity so durable recovery can reject replaced locks.
    """
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        info = os.fstat(fd)
        if not (stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
                info.st_uid == os.geteuid() and not info.st_mode & 0o077):
            raise PermissionError("UNSAFE_LOCK_FILE")
        with locked_descriptor(fd):
            yield info.st_dev, info.st_ino
    finally:
        os.close(fd)
