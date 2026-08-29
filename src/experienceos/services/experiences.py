"""Service layer (#018): use cases shared by the CLI and the API.

The CLI used to own all logic inline. Extracting it here lets the
FastAPI app (and future plugins/UIs) reuse the exact same behaviour
while CLI and API stay thin shells. Services never print and never
prompt; they raise ``ExperienceOSError`` subclasses and return data.
"""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from experienceos.core.errors import StorageError, ValidationError
from experienceos.core.guardrails import ClaimIssue as GuardrailIssue
from experienceos.core.guardrails import lint_experiences
from experienceos.core.models import Experience, Status
from experienceos.stats import aggregate_stats
from experienceos.storage import ExperienceStore, SearchQuery, search
from experienceos.storage import fts as fts_module
from experienceos.storage.store import LoadIssue

THRESHOLD_ENV = "EXPERIENCEOS_FTS_THRESHOLD"


def list_experiences(store: ExperienceStore, query: SearchQuery) -> list[Experience]:
    """Filtered, scored-ordered records for a query."""
    return run_query(store, query)


def get_experience(store: ExperienceStore, id_or_prefix: str) -> Experience:
    """One record by ID or unique prefix."""
    return store.load(store.resolve(id_or_prefix))


def search_experiences(store: ExperienceStore, query: SearchQuery) -> list[Experience]:
    """Free-text search; ranked results flattened to records."""
    return run_query(store, query)


def run_query(store: ExperienceStore, query: SearchQuery) -> list[Experience]:
    """Dispatch a query: FTS index when it pays off, memory scan otherwise (#022).

    The index only ever accelerates the *text* part; type/status/tag and
    period filters are re-applied in memory, and stale index entries
    (deleted files) drop out against the store. Files stay the source of
    truth: no index, small library, or ``EXPERIENCEOS_FTS_THRESHOLD=0``
    all mean the pure in-memory path.
    """
    experiences = store.list_all()
    if query.text and _fts_worth_it(store.root, len(experiences)):
        ids = set(fts_module.fts_search(store.root, query.text))
        if ids:
            by_id = {exp.id: exp for exp in experiences}
            candidates = [by_id[exp_id] for exp_id in ids if exp_id in by_id]
            filtered = search(candidates, replace(query, text=""))
            return [result.experience for result in filtered]
    return [result.experience for result in search(experiences, query)]


def _fts_worth_it(home: Any, record_count: int) -> bool:
    try:
        threshold = int(os.environ.get(THRESHOLD_ENV, str(fts_module.DEFAULT_THRESHOLD)))
    except ValueError:
        threshold = fts_module.DEFAULT_THRESHOLD
    if threshold <= 0 or record_count < threshold:
        return False
    return fts_module.index_exists(home)


def summarize(store: ExperienceStore) -> dict[str, Any]:
    """Machine-readable knowledge-base summary (backs `stats --json`)."""
    return aggregate_stats(store.list_all())


def create_draft(store: ExperienceStore, fields: dict[str, Any]) -> Experience:
    """Create and save one draft record; never overwrites.

    API-side creation always lands as ``status=draft`` with
    ``source.created_by=user`` — promotion to active stays a CLI-gated
    decision, keeping the "AI/API propose, human decide" gate intact.
    """
    if "status" in fields and fields["status"] != Status.draft:
        raise ValidationError("the API can only create drafts (status=draft)")
    try:
        experience = Experience.new(
            status=Status.draft,
            source={"origin": "manual", "created_by": "user"},
            **fields,
        )
    except PydanticValidationError as exc:
        raise ValidationError(f"invalid draft payload: {exc}") from exc
    if store.exists(experience.id):
        raise StorageError(
            f"record id conflict: {experience.id} already exists "
            "(creation never overwrites records)"
        )
    store.save(experience)
    return experience


def validate_home(store: ExperienceStore) -> list[LoadIssue]:
    """Schema problems across the home, reported without raising."""
    return store.validate()


def lint_home(
    store: ExperienceStore, include_archived: bool = False
) -> list[GuardrailIssue]:
    """Quantitative claims without evidence (see core/guardrails)."""
    experiences = store.list_all()
    if not include_archived:
        experiences = [e for e in experiences if e.status is not Status.archived]
    return lint_experiences(experiences)
