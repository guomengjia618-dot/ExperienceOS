"""The ExperienceDraft: a validated, not-yet-confirmed record.

Drafts are the single currency of *proposals* in ExperienceOS: every
connector and every AI pipeline produces them, and only an explicit
user confirmation turns one into a stored record. Two invariants:

1. A draft always carries ``status=draft`` — producing a proposal can
   never create a "finished" record.
2. Provenance is mandatory: ``source.origin`` / ``source.created_by``
   record where the draft came from (importer, conversation, or
   ``ai:<model>``).

The class lives in core because both the connectors tier and the ai
tier depend on it; keeping it in either sibling would force a lateral
dependency between them (see ARCHITECTURE.md, layering rules).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from experienceos.core.errors import ValidationError
from experienceos.core.models import Experience, SourceOrigin, Status


@dataclass(frozen=True)
class ExperienceDraft:
    """A validated, not-yet-confirmed experience record."""

    experience: Experience

    def __post_init__(self) -> None:
        if self.experience.status is not Status.draft:
            raise ValidationError(
                "ExperienceDraft must hold status=draft, got "
                f"{self.experience.status.value!r}"
            )

    @classmethod
    def create(
        cls,
        *,
        origin: SourceOrigin | str,
        ref: str | None = None,
        created_by: str | None = None,
        **fields: Any,
    ) -> ExperienceDraft:
        """Build a draft. ``fields`` are ``Experience.new`` kwargs
        (title, type, period, technology, evidence, ...).

        ``created_by`` overrides the provenance author ("user" by
        default; AI pipelines pass ``"ai:<model>"``)."""
        source: dict[str, Any] = {"origin": origin, "ref": ref}
        if created_by is not None:
            source["created_by"] = created_by
        try:
            experience = Experience.new(
                status=Status.draft,
                source=source,
                **fields,
            )
        except PydanticValidationError as exc:
            raise ValidationError(f"connector produced an invalid draft: {exc}") from exc
        return cls(experience)
