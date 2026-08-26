"""Connector framework base: sources -> validated experience drafts.

A connector (Extractor) turns one fragmented source of experience — a
GitHub repo, a local git checkout, a resume file — into ``ExperienceDraft``
records. Two invariants hold for everything a connector produces:

1. Drafts land with ``status=draft`` — importing never creates "finished"
   records; confirming and refining is the user's job (AI proposals in M2
   build on the same mechanism).
2. Provenance is mandatory: ``source.origin`` / ``source.ref`` record where
   the draft came from.

Source routing uses a ``scheme:payload`` syntax (``github:owner/repo``,
``resume:cv.md``). Strings without a scheme are local paths. Single-letter
schemes are Windows drive paths (``C:\\repo``), not schemes.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from pydantic import ValidationError as PydanticValidationError

from experienceos.core.errors import ValidationError
from experienceos.core.models import Experience, SourceOrigin, Status

_SCHEME_RE = re.compile(r"^[a-z][a-z0-9_-]+$")


def parse_source(source: str) -> tuple[str | None, str]:
    """Split ``scheme:payload``; return ``(None, source)`` when unmarked.

    A scheme must start with a letter, contain only ``[a-z0-9_-]`` and be
    at least two characters long — which keeps ``C:\\repo`` and relative
    paths like ``./note:x`` out of scheme routing.
    """
    head, sep, tail = source.partition(":")
    if sep:
        scheme = head.lower()
        if len(scheme) >= 2 and _SCHEME_RE.match(scheme):
            return scheme, tail
    return None, source


@runtime_checkable
class Extractor(Protocol):
    """Adapter contract every import source must implement.

    Implementations must be deterministic for a given source; network or
    filesystem failures must surface as ``ExperienceOSError`` subclasses,
    never raw tracebacks.
    """

    name: str

    def can_handle(self, source: str) -> bool:
        """Return True when this extractor claims the source string."""
        ...

    def extract(self, source: str) -> Iterator[ExperienceDraft]:
        """Yield validated drafts for the source (may yield nothing)."""
        ...


@runtime_checkable
class AuthoredExtractor(Protocol):
    """Optional capability for sources that can filter activity by author."""

    def extract_for_author(
        self, source: str, author: str
    ) -> Iterator[ExperienceDraft]:
        """Yield drafts containing only activity attributed to *author*."""
        ...


@dataclass(frozen=True)
class ExperienceDraft:
    """A validated, not-yet-confirmed experience record from a connector."""

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
        **fields: Any,
    ) -> ExperienceDraft:
        """Build a draft. ``fields`` are ``Experience.new`` kwargs
        (title, type, period, technology, evidence, ...)."""
        try:
            experience = Experience.new(
                status=Status.draft,
                source={"origin": origin, "ref": ref},
                **fields,
            )
        except PydanticValidationError as exc:
            raise ValidationError(f"connector produced an invalid draft: {exc}") from exc
        return cls(experience)
