"""Service layer (#018): use cases shared by the CLI and the API.

The CLI used to own all logic inline. Extracting it here lets the
FastAPI app (and future plugins/UIs) reuse the exact same behaviour
while CLI and API stay thin shells. Services never print and never
prompt; they raise ``ExperienceOSError`` subclasses and return data.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from experienceos.core.errors import StorageError, ValidationError
from experienceos.core.guardrails import ClaimIssue as GuardrailIssue
from experienceos.core.guardrails import lint_experiences
from experienceos.core.models import Experience, Status
from experienceos.stats import aggregate_stats
from experienceos.storage import ExperienceStore, SearchQuery, SearchResult, search
from experienceos.storage import fts as fts_module
from experienceos.storage.store import LoadIssue

THRESHOLD_ENV = "EXPERIENCEOS_FTS_THRESHOLD"

logger = logging.getLogger("experienceos.services")


def list_experiences(store: ExperienceStore, query: SearchQuery) -> list[Experience]:
    """Filtered, scored-ordered records for a query."""
    return run_query(store, query)


def get_experience(store: ExperienceStore, id_or_prefix: str) -> Experience:
    """One record by ID or unique prefix."""
    return store.load(store.resolve(id_or_prefix))


def search_experiences(store: ExperienceStore, query: SearchQuery) -> list[Experience]:
    """Free-text search; ranked results flattened to records."""
    return run_query(store, query)


def query_results(store: ExperienceStore, query: SearchQuery) -> list[SearchResult]:
    """Search with ranking metadata, shared by every interface (#022).

    Query semantics live in exactly one place: the in-memory engine
    (``storage.query.search``) always does the final filtering *and*
    scoring, so scores and matched fields mean the same thing on every
    path. The FTS index — when present and worth it — only narrows the
    candidate set first; it never defines semantics and never dictates
    order. Files stay the source of truth: no index, small library, or
    ``EXPERIENCEOS_FTS_THRESHOLD=0`` all mean the pure in-memory path.
    """
    experiences = store.list_all()
    if query.text and _fts_worth_it(store.root, len(experiences)):
        _refresh_stale_index(store.root, experiences)
        ids = set(fts_module.fts_search(store.root, query.text))
        if ids:
            by_id = {exp.id: exp for exp in experiences}
            candidates = [by_id[exp_id] for exp_id in ids if exp_id in by_id]
            if candidates:
                return search(candidates, query)
            # every hit was stale (index older than the files) — full scan
    return search(experiences, query)


def run_query(store: ExperienceStore, query: SearchQuery) -> list[Experience]:
    """Flattened :func:`query_results` (records only)."""
    return [result.experience for result in query_results(store, query)]


def _fts_worth_it(home: Any, record_count: int) -> bool:
    try:
        threshold = int(os.environ.get(THRESHOLD_ENV, str(fts_module.DEFAULT_THRESHOLD)))
    except ValueError:
        threshold = fts_module.DEFAULT_THRESHOLD
    if threshold <= 0 or record_count < threshold:
        return False
    return fts_module.index_exists(home)


def _refresh_stale_index(home: Any, experiences: list[Experience]) -> None:
    """Rebuild the index when it no longer matches the record files.

    The index is a rebuildable cache. Its row count drifting from the
    file count means best-effort upserts failed (a lock conflict, a
    crash) and the index now silently misses records — rebuilding from
    the source of truth beats degrading every search until someone
    notices. A rebuild failure keeps the old behaviour: FTS hits narrow
    candidates, the in-memory engine still decides correctness.
    """
    recorded = fts_module.index_doc_count(home)
    if recorded == len(experiences):
        return
    logger.info(
        "search index is stale (%s rows vs %s records); rebuilding",
        recorded,
        len(experiences),
    )
    try:
        fts_module.build_index(home, experiences)
    except sqlite3.Error as exc:  # pragma: no cover - busy timeout exhausted
        logger.warning("could not rebuild stale search index: %s", exc)


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
