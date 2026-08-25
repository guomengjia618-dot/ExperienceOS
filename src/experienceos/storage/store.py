"""Local-first storage: one JSON file per experience.

The files under ``<home>/experiences/`` are the single source of truth.
They are human-readable, diff-friendly and can be backed up or versioned
with git. No database is involved at this scale; see ARCHITECTURE.md for
the threshold at which we plan to introduce an FTS index.

Design guarantees:

- Atomic writes (temp file + ``os.replace``) so a crash never truncates
  an existing record.
- Corruption-tolerant listing: one broken file must not make the whole
  knowledge base unreadable; ``validate()`` reports problems instead.
- ``updated_at`` is bumped on every save, transparently to callers.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from pydantic import ValidationError as PydanticValidationError

from experienceos.core.errors import AmbiguousIdError, NotFoundError, StorageError
from experienceos.core.models import Experience, utcnow

logger = logging.getLogger("experienceos.storage")


class LoadIssue:
    """A single file that could not be loaded, with the reason."""

    def __init__(self, path: Path, error: str) -> None:
        self.path = path
        self.error = error


class ExperienceStore:
    """File-backed repository of experiences under an ExperienceOS home."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.experiences_dir = self.root / "experiences"

    # -- paths ---------------------------------------------------------------

    def path_of(self, experience_id: str) -> Path:
        return self.experiences_dir / f"{experience_id}.json"

    # -- write ---------------------------------------------------------------

    def save(self, experience: Experience) -> Path:
        """Persist an experience atomically and refresh ``updated_at``."""
        experience.updated_at = utcnow()
        self.experiences_dir.mkdir(parents=True, exist_ok=True)
        target = self.path_of(experience.id)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(
            experience.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        os.replace(tmp, target)
        return target

    def delete(self, experience_id: str) -> bool:
        """Remove a record. Returns False if it did not exist."""
        path = self.path_of(experience_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    # -- read ----------------------------------------------------------------

    def exists(self, experience_id: str) -> bool:
        return self.path_of(experience_id).exists()

    def load(self, experience_id: str) -> Experience:
        """Load one record, raising NotFoundError / StorageError."""
        path = self.path_of(experience_id)
        if not path.exists():
            raise NotFoundError(experience_id)
        _id, experience, error = self._read_file(path)
        if experience is None:
            raise StorageError(f"cannot load {path.name}: {error}")
        return experience

    def _read_file(self, path: Path) -> tuple[str, Experience | None, str | None]:
        """Return (id, experience, error); exactly one of experience/error set."""
        raw_id = path.stem
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            experience = Experience.from_dict(data)
        except (OSError, json.JSONDecodeError, PydanticValidationError, ValueError) as exc:
            return raw_id, None, str(exc)
        return experience.id, experience, None

    def list_all(self) -> list[Experience]:
        """Load every valid record, newest first (IDs are time-sortable)."""
        experiences: list[Experience] = []
        if not self.experiences_dir.is_dir():
            return experiences
        for path in sorted(self.experiences_dir.glob("*.json")):
            _id, experience, error = self._read_file(path)
            if experience is None:
                logger.warning("skipping unreadable experience file %s: %s", path, error)
            else:
                experiences.append(experience)
        experiences.sort(key=lambda e: e.id, reverse=True)
        return experiences

    def all_ids(self) -> list[str]:
        ids: list[str] = []
        if not self.experiences_dir.is_dir():
            return ids
        ids = [path.stem for path in self.experiences_dir.glob("*.json")]
        return sorted(ids)

    def validate(self) -> list[LoadIssue]:
        """Check every file on disk and report issues without raising."""
        issues: list[LoadIssue] = []
        if not self.experiences_dir.is_dir():
            return issues
        for path in sorted(self.experiences_dir.glob("*.json")):
            _id, _experience, error = self._read_file(path)
            if error is not None:
                issues.append(LoadIssue(path, error))
        return issues

    # -- id resolution ---------------------------------------------------------

    def resolve(self, prefix: str) -> str:
        """Expand a unique ID prefix to the full ID for friendly CLI usage.

        The prefix is matched literally first; if nothing matches and the
        user omitted the ``exp_`` prefix (e.g. typed just ``01HABC``), it
        is retried with the prefix added.
        """
        matches = [i for i in self.all_ids() if i.startswith(prefix)]
        if not matches and not prefix.startswith("exp_"):
            matches = [i for i in self.all_ids() if i.startswith(f"exp_{prefix}")]
        if not matches:
            raise NotFoundError(prefix)
        if len(matches) > 1:
            raise AmbiguousIdError(prefix, matches)
        return matches[0]
