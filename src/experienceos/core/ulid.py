"""Time-sortable ULID generation (stdlib only).

Experience IDs must be lexicographically sortable by creation time so that
``list`` and storage scans can return chronological order without an index.
We implement the standard ULID format (26 chars, Crockford base 32) instead
of pulling in a dependency: 48 bits of millisecond timestamp + 80 bits of
randomness, with in-process monotonicity for IDs generated within the same
millisecond.
"""

from __future__ import annotations

import os
import threading
import time

_ENCODING = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base 32 (no I, L, O, U)
_TIME_CHARS = 10
_RANDOM_CHARS = 16
_lock = threading.Lock()
_last = (0, 0)  # (timestamp_ms, last random value) for monotonicity


def _encode_time(timestamp_ms: int) -> str:
    chars = []
    for _ in range(_TIME_CHARS):
        timestamp_ms, rem = divmod(timestamp_ms, 32)
        chars.append(_ENCODING[rem])
    return "".join(reversed(chars))


def _encode_random(value: int) -> str:
    chars = []
    for _ in range(_RANDOM_CHARS):
        value, rem = divmod(value, 32)
        chars.append(_ENCODING[rem])
    return "".join(reversed(chars))


def new_ulid() -> str:
    """Return a new ULID string (26 chars), monotonic within this process."""
    timestamp_ms = int(time.time() * 1000)
    with _lock:
        global _last
        random_value = int.from_bytes(os.urandom(10), "big")
        prev_ts, prev_rand = _last
        if timestamp_ms == prev_ts and random_value <= prev_rand:
            random_value = (prev_rand + 1) % (2**80)
        _last = (timestamp_ms, random_value)
    return _encode_time(timestamp_ms) + _encode_random(random_value)
