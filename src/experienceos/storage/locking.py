"""Cross-process advisory locking for the local store (stdlib only).

Local-first means one user, but not one process: the CLI, the REST API
and the workbench can run side by side. Read paths stay lock-free —
atomic replace means a reader sees the old or the new file, never a
torn one — while every read-modify-write (save, delete, transparent
migration) holds an exclusive lock on a single lock file, so two
writers cannot silently drop each other's updates.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from experienceos.core.errors import StorageError

try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None


class LockTimeoutError(StorageError):
    """Another process held the store lock longer than the wait budget."""


STORE_LOCK_FILENAME = ".store.lock"


@contextmanager
def exclusive_lock(
    path: Path, *, timeout: float = 10.0, poll_interval: float = 0.02
) -> Iterator[Path]:
    """Hold an exclusive advisory lock on *path* for the with-block.

    Blocking is a non-blocking acquire plus poll, so the timeout budget
    behaves identically on Windows (``msvcrt.locking``) and POSIX
    (``fcntl.flock``). The lock file is created once and never deleted:
    safe locking requires racing processes to contend on the same inode,
    which unlink-then-recreate would break.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR)
    deadline = time.monotonic() + timeout
    acquired = False
    try:
        while not acquired:
            try:
                if msvcrt is not None:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                elif fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:  # pragma: no cover - no locking backend available
                    raise LockTimeoutError("no file locking backend on this platform")
                acquired = True
            except OSError:
                if time.monotonic() >= deadline:
                    raise LockTimeoutError(
                        f"another ExperienceOS process holds the lock: {path}"
                    ) from None
                time.sleep(poll_interval)
        yield path
    finally:
        if acquired:
            try:
                if msvcrt is not None:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                elif fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
        else:
            os.close(fd)
