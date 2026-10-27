"""Shared private host paths and SQLite inode checks for operator stores.

Not a distributed store or a defense against a compromised same-UID host.
All workers/maintenance must preserve file identities while connections exist.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3
import stat

from scripts.ironman_jobs.ironman_file_lock import locked_descriptor


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise PermissionError(code)


def require_private_path(path: Path) -> None:
    """Common host-input/store boundary; never repair an unsafe directory."""
    _require(os.name == "posix" and path.is_absolute() and ".." not in path.parts,
             "LOCAL_STATE_PATH_INVALID")
    # Container mounts may map the filesystem root owner to a namespace UID.
    # Derive that owner from the root, never from a caller-selected directory.
    root_owners = {0, Path(path.anchor).lstat().st_uid}
    for parent in path.parents:
        meta = parent.lstat()
        _require(stat.S_ISDIR(meta.st_mode) and meta.st_uid in root_owners | {os.geteuid()} and
                 (not meta.st_mode & 0o022 or
                  (meta.st_uid in root_owners and bool(meta.st_mode & stat.S_ISVTX))),
                 "LOCAL_STATE_PARENT_UNSAFE")


def _identity(meta: os.stat_result) -> tuple[int, int]:
    _require(stat.S_ISREG(meta.st_mode) and meta.st_nlink == 1 and
             meta.st_uid == os.geteuid() and meta.st_mode & 0o777 == 0o600,
             "LOCAL_STATE_FILE_UNSAFE")
    return meta.st_dev, meta.st_ino


@dataclass(frozen=True)
class LocalStateFile:
    path: Path
    identity: tuple[int, int]

    def verify(self) -> None:
        require_private_path(self.path)
        _require(_identity(self.path.lstat()) == self.identity, "LOCAL_STATE_IDENTITY_CHANGED")
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(str(self.path) + suffix)
            try:
                meta = sidecar.lstat()
            except FileNotFoundError:
                continue
            _identity(meta)


def connect_private_sqlite(path: Path) -> tuple[sqlite3.Connection, LocalStateFile]:
    """Create 0600 BEFORE SQLite; reject aliases/unsafe files without repair."""
    path = Path(path)
    require_private_path(path)
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    except OSError as exc:
        raise PermissionError("LOCAL_STATE_OPEN_DENIED") from exc
    try:
        state = LocalStateFile(path, _identity(os.fstat(fd)))
        # SQLite's journal-mode transition can fail immediately on simultaneous
        # first open, despite busy_timeout. Serialize initialization on the DB
        # inode itself, reusing the shared POSIX primitive without another file.
        with locked_descriptor(fd, timeout=8):
            state.verify()
            connection = sqlite3.connect(str(path), timeout=8)
            try:
                state.verify()
                connection.execute("PRAGMA busy_timeout=8000")
                connection.execute("PRAGMA journal_mode=WAL")
                state.verify()
            except Exception:
                connection.close()
                raise
        return connection, state
    finally:
        os.close(fd)
