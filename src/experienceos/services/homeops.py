"""Home-directory operations (#021): git sync and zip backup.

The home directory is plain JSON + one config file, so it versions and
archives cleanly. ``git_sync`` commits everything in the home (git
itself respects ``.gitignore``); ``backup_home`` produces a restore-ready
zip — relative paths, no git internals, no scratch or backup files,
because the JSON files are the source of truth (ADR D1).
"""

from __future__ import annotations

import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

from experienceos.core.errors import StorageError

GIT_TIMEOUT_SECONDS = 60
_EXCLUDED_DIR_NAMES = {".git", "backup"}


@dataclass(frozen=True)
class SyncReport:
    """What ``git_sync`` did, for the CLI to present."""

    initialized: bool
    committed: bool
    pushed: bool
    message: str
    detail: str = ""


def _git(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(home), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise StorageError(
            "git executable not found; install Git to use `experienceos sync`"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise StorageError(f"git {args[0]} timed out in '{home}'") from exc


def git_sync(home: Path, message: str, push_remote: str | None, init: bool) -> SyncReport:
    """Commit the home directory (optionally initializing / pushing)."""
    initialized = False
    if not (home / ".git").exists():
        if not init:
            raise StorageError(
                f"{home} is not a git repository; run `experienceos sync --init` "
                "to start versioning (keep remote repositories private)"
            )
        result = _git(home, "-c", "init.defaultBranch=main", "init")
        if result.returncode != 0:
            raise StorageError(f"git init failed: {_first_line(result.stderr)}")
        initialized = True

    add = _git(home, "add", "-A")
    if add.returncode != 0:
        raise StorageError(f"git add failed: {_first_line(add.stderr)}")

    commit = _git(home, "commit", "-m", message)
    committed = commit.returncode == 0
    detail = (commit.stdout or "").strip()
    if not committed and "nothing to commit" not in (commit.stdout + commit.stderr):
        hint = ""
        if "Author identity unknown" in commit.stderr:
            hint = " (configure git: git config --global user.name / user.email)"
        raise StorageError(f"git commit failed: {_first_line(commit.stderr)}{hint}")

    pushed = False
    if push_remote:
        push = _git(home, "push", "-u", push_remote, "HEAD")
        if push.returncode != 0:
            raise StorageError(f"git push failed: {_first_line(push.stderr)}")
        pushed = True

    action = "committed" if committed else "nothing to commit"
    return SyncReport(
        initialized=initialized,
        committed=committed,
        pushed=pushed,
        message=message,
        detail=detail.splitlines()[0] if detail else action,
    )


def backup_home(home: Path, out: Path) -> tuple[Path, int]:
    """Zip the home (config included); return (archive path, file count)."""
    files = _archive_files(home)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(home).as_posix())
    return out, len(files)


def _archive_files(home: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(home.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(home)
        if any(part in _EXCLUDED_DIR_NAMES for part in relative.parts):
            continue
        if path.name.endswith(".tmp"):
            continue  # edit scratch files are never restorable state
        files.append(path)
    return files


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else "unknown error"
