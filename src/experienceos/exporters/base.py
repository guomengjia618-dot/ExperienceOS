"""Exporter framework base (#014): experiences -> output artifacts.

Exporters are the mirror image of connectors: a connector turns one
external source into many drafts; an exporter turns a selected subset
of records into one faithful projection. Two invariants:

1. Exports only ever contain what the user selected — the CLI defaults
   to ``status=active`` so drafts and archived records never leak into
   a shareable artifact by accident.
2. An exporter renders; it never embellishes. Whatever lands in the
   output must come from the records.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from experienceos.core.models import Experience


@dataclass(frozen=True)
class ExportOptions:
    """Generic per-invocation options; exporters ignore what they
    don't understand (e.g. ``timeline`` is markdown-only)."""

    timeline: bool = False


@runtime_checkable
class Exporter(Protocol):
    """Contract every output format must implement."""

    name: str
    suffix: str  # file extension used for default target naming

    def export(
        self,
        experiences: Sequence[Experience],
        target: Path,
        options: ExportOptions | None = None,
    ) -> Path:
        """Write the artifact to *target* and return its path."""
        ...
