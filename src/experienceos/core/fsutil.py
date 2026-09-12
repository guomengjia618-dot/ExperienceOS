"""Crash-safe file primitives shared by every tier.

``atomic_write_text`` backs the "atomic write" guarantee the storage and
AI checkpoint layers advertise: the payload is fully written and fsynced
before the temp file replaces the target, so a crash mid-write can
never truncate an existing record, and a crash right after the rename
cannot lose it to a not-yet-flushed filesystem cache.
"""

from __future__ import annotations

import os
from pathlib import Path


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> Path:
    """Write *text* durably: fsync the temp file, then ``os.replace``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding=encoding) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    _fsync_directory(path.parent)
    return path


def _fsync_directory(directory: Path) -> None:
    """Persist the rename itself (POSIX); Windows has no portable equivalent."""
    if os.name != "posix":  # pragma: no cover - platform branch
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:  # pragma: no cover - directory vanished mid-write
        return
    try:
        os.fsync(fd)
    except OSError:  # pragma: no cover - some filesystems refuse dir fsync
        pass
    finally:
        os.close(fd)
