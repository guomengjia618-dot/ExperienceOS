"""Exporter registry (#014): name-keyed lookup of output formats.

Mirrors the connector registry; a separate class so exporters and
connectors can never be mixed up in one namespace.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from experienceos.core.errors import ExportError


@runtime_checkable
class _ExporterLike(Protocol):
    name: str


class ExporterRegistry:
    """Register exporters by name; duplicates and unknowns are errors."""

    def __init__(self) -> None:
        self._exporters: dict[str, _ExporterLike] = {}

    def register(self, exporter: _ExporterLike) -> None:
        name = exporter.name
        if name in self._exporters:
            raise ExportError(f"exporter '{name}' is already registered")
        self._exporters[name] = exporter

    def unregister(self, name: str) -> bool:
        return self._exporters.pop(name, None) is not None

    def get(self, name: str) -> _ExporterLike:
        try:
            return self._exporters[name]
        except KeyError as exc:
            known = ", ".join(sorted(self._exporters)) or "(none)"
            raise ExportError(
                f"unknown exporter '{name}'. Available: {known}"
            ) from exc

    def names(self) -> list[str]:
        return sorted(self._exporters)


default_exporter_registry = ExporterRegistry()
