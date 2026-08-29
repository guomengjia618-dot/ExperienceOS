"""Schema migration framework (#020).

Records carry ``schema_version`` as their migration anchor. Steps are
ordered pure functions registered against the version they upgrade
*from*; applying a step moves a record from N to N+1. The chain is
followed until the record reaches the build's ``SCHEMA_VERSION``.

Steps operate on raw dicts, deliberately bypassing the pydantic model:
the model rejects records whose version differs from the build, and a
future version must fail loudly instead of being "migrated" backwards.

Today the production chain is empty (the current schema is v1); the
framework is exercised by a v1 -> v2 drill in the tests, which is the
exact path a real schema change would take.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from experienceos.core import models
from experienceos.core.errors import StorageError, ValidationError

MigrationStep = Callable[[dict[str, Any]], dict[str, Any]]

MIGRATIONS: dict[int, MigrationStep] = {}


def register_migration(from_version: int) -> Callable[[MigrationStep], MigrationStep]:
    """Decorator registering the step that upgrades ``from_version`` -> +1."""

    def decorator(step: MigrationStep) -> MigrationStep:
        if from_version in MIGRATIONS:
            raise StorageError(f"a migration from v{from_version} already exists")
        MIGRATIONS[from_version] = step
        return step

    return decorator


def needs_migration(data: Any, latest: int | None = None) -> bool:
    """True when *data* is a record older than *latest*."""
    latest = models.SCHEMA_VERSION if latest is None else latest
    if not isinstance(data, dict):
        return False
    try:
        version = int(data.get("schema_version", 1))
    except (TypeError, ValueError):
        return False
    return 0 < version < latest


def run_migrations(
    data: dict[str, Any], latest: int | None = None
) -> tuple[dict[str, Any], list[int]]:
    """Bring *data* up to *latest*; return (data, applied target versions)."""
    latest = models.SCHEMA_VERSION if latest is None else latest
    try:
        version = int(data.get("schema_version", 1))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"unreadable schema_version: {exc}") from exc
    if version > latest:
        raise ValidationError(
            f"unsupported schema_version {version} (this build understands "
            f"{latest}); upgrade ExperienceOS to read this record"
        )
    applied: list[int] = []
    while version < latest:
        step = MIGRATIONS.get(version)
        if step is None:
            raise StorageError(
                f"no migration path from schema v{version} to v{latest}; "
                "this install is missing migration steps"
            )
        try:
            data = step(data)
            data["schema_version"] = version + 1
        except Exception as exc:
            raise StorageError(f"migration v{version} -> v{version + 1} failed: {exc}") from exc
        version = int(data["schema_version"])
        applied.append(version)
    return data, applied
