"""Durability and concurrency hardening: atomic fsync writes + store lock."""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from experienceos.core.fsutil import atomic_write_text
from experienceos.storage.locking import LockTimeoutError, exclusive_lock


class TestAtomicWrite:
    def test_writes_content_and_leaves_no_temp_file(self, tmp_path: Any) -> None:
        target = tmp_path / "nested" / "record.json"
        atomic_write_text(target, '{"a": 1}\n')
        assert target.read_text(encoding="utf-8") == '{"a": 1}\n'
        assert list((tmp_path / "nested").glob("*.tmp")) == []

    def test_fsyncs_before_replace(self, tmp_path: Any, monkeypatch: Any) -> None:
        calls: list[int] = []
        real_fsync = os.fsync

        def tracked_fsync(fd: int) -> None:
            calls.append(fd)
            real_fsync(fd)

        monkeypatch.setattr(os, "fsync", tracked_fsync)
        atomic_write_text(tmp_path / "out.txt", "payload")
        assert calls, "atomic_write_text must fsync the payload before replace"


class TestExclusiveLock:
    def test_second_holder_times_out_while_first_holds(self, tmp_path: Any) -> None:
        lock = tmp_path / ".store.lock"
        with exclusive_lock(lock, timeout=5.0):
            started = threading.Event()
            outcome: list[Exception] = []

            def contender() -> None:
                started.set()
                try:
                    with exclusive_lock(lock, timeout=0.1):
                        outcome.append(AssertionError("lock should not be free"))
                except LockTimeoutError as exc:
                    outcome.append(exc)

            thread = threading.Thread(target=contender, daemon=True)
            thread.start()
            started.wait(1.0)
            thread.join(timeout=5.0)
        assert outcome and isinstance(outcome[0], LockTimeoutError)

    def test_lock_is_reacquirable_after_release(self, tmp_path: Any) -> None:
        lock = tmp_path / ".store.lock"
        with exclusive_lock(lock, timeout=5.0):
            pass
        with exclusive_lock(lock, timeout=5.0):
            pass

    def test_store_save_waits_for_external_lock(self, store: Any, make_experience: Any) -> None:
        lock = store.lock_path
        started = threading.Event()

        def hold_lock() -> None:
            with exclusive_lock(lock, timeout=5.0):
                started.set()
                time.sleep(0.3)

        thread = threading.Thread(target=hold_lock, daemon=True)
        thread.start()
        assert started.wait(1.0)
        begin = time.monotonic()
        store.save(make_experience())
        elapsed = time.monotonic() - begin
        thread.join(timeout=5.0)
        assert elapsed >= 0.25, "save must wait for the external lock holder"

    def test_lock_file_is_excluded_from_sync_gitignore(self, tmp_path: Any) -> None:
        # regression guard: the zero-byte lock file must never dirty `sync`
        from experienceos.services.homeops import _GITIGNORE_ENTRIES

        assert ".store.lock" in _GITIGNORE_ENTRIES
