"""Service layer (#018): use cases shared by the CLI and the API.

The CLI used to own all logic inline. Extracting it here lets the
FastAPI app (and future plugins/UIs) reuse the exact same behaviour
while CLI and API stay thin shells. Services never print and never
prompt; they raise ``ExperienceOSError`` subclasses and return data.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError as PydanticValidationError

from experienceos.core.errors import StorageError, ValidationError
from experienceos.core.guardrails import ClaimIssue as GuardrailIssue
from experienceos.core.guardrails import lint_experiences
from experienceos.core.models import Experience, Status
from experienceos.stats import aggregate_stats
from experienceos.storage import ExperienceStore, SearchQuery, search
from experienceos.storage.store import LoadIssue


def list_experiences(store: ExperienceStore, query: SearchQuery) -> list[Experience]:
    """Filtered, scored-ordered records for a query."""
    return [result.experience for result in search(store.list_all(), query)]


def get_experience(store: ExperienceStore, id_or_prefix: str) -> Experience:
    """One record by ID or unique prefix."""
    return store.load(store.resolve(id_or_prefix))


def search_experiences(store: ExperienceStore, query: SearchQuery) -> list[Experience]:
    """Free-text search; ranked results flattened to records."""
    return [result.experience for result in search(store.list_all(), query)]


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
