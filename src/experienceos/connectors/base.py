"""Connector framework base: sources -> validated experience drafts.

A connector (Extractor) turns one fragmented source of experience — a
GitHub repo, a local git checkout, a project folder, a resume file —
into ``ExperienceDraft`` records. Two invariants hold for everything a
connector produces:

1. Drafts land with ``status=draft`` — importing never creates "finished"
   records; confirming and refining is the user's job (AI proposals in
   M2 build on the same mechanism).
2. Provenance is mandatory: ``source.origin`` / ``source.ref`` record
   where the draft came from.

Source routing uses a ``scheme:payload`` syntax (``github:owner/repo``,
``resume:cv.md``). Strings without a scheme are local paths. Single-letter
schemes are Windows drive paths (``C:\\repo``), not schemes.

Some inputs need AI reading (PDF resumes). Connectors never import the
ai tier: an ``AIExtraction`` pipeline (or any third-party equivalent) is
*injected* through the :class:`MaterialDraftExtractor` /
:class:`AcceptsMaterialExtractor` protocols below, so the dependency
points from the composition root into both tiers — never sideways.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from typing import Protocol, runtime_checkable

from experienceos.core.draft import ExperienceDraft

_SCHEME_RE = re.compile(r"^[a-z][a-z0-9_-]+$")

Material = Sequence[tuple[str, str]]
"""Raw material: (role, text) pairs, e.g. [("user", "..."), ("resume text", "...")]."""


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


@runtime_checkable
class MaterialDraftExtractor(Protocol):
    """Turns raw material into ONE validated draft proposal.

    Implemented today by ``ai.extraction.AIExtraction``; connectors that
    need AI reading for some inputs accept one via
    :class:`AcceptsMaterialExtractor` and stay ai-tier-free.
    """

    def extract_draft(
        self,
        materials: Material,
        *,
        origin: str,
        ref: str | None = None,
        candidates: list[dict[str, str]] | None = None,
        material_label: str = "Material (conversation transcript)",
    ) -> ExperienceDraft:
        """Return one draft built only from *materials* (never guessed)."""
        ...


@runtime_checkable
class AcceptsMaterialExtractor(Protocol):
    """Optional capability: connector can be handed a material extractor."""

    def set_material_extractor(self, extractor: MaterialDraftExtractor) -> None:
        """Wire the injected extractor (composition root's job)."""
        ...


__all__ = [
    "AcceptsMaterialExtractor",
    "AuthoredExtractor",
    "ExperienceDraft",
    "Extractor",
    "Material",
    "MaterialDraftExtractor",
    "parse_source",
]
