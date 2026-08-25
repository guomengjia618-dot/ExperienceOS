"""Extractor registry: name-keyed, deterministic source routing."""

from __future__ import annotations

from experienceos.connectors.base import Extractor, parse_source
from experienceos.core.errors import ConnectorError


class Registry:
    """Holds extractors in registration order (dicts preserve insertion),
    making routing deterministic without priority knobs."""

    def __init__(self) -> None:
        self._extractors: dict[str, Extractor] = {}

    def register(self, extractor: Extractor) -> None:
        if extractor.name in self._extractors:
            raise ConnectorError(f"connector '{extractor.name}' is already registered")
        self._extractors[extractor.name] = extractor

    def unregister(self, name: str) -> bool:
        """Remove a connector; False when it was not registered (tests, plugins)."""
        return self._extractors.pop(name, None) is not None

    def get(self, name: str) -> Extractor:
        try:
            return self._extractors[name]
        except KeyError:
            raise ConnectorError(
                f"no connector named '{name}' "
                f"(registered: {', '.join(self.names()) or 'none'})"
            ) from None

    def names(self) -> list[str]:
        return list(self._extractors)

    def find_handler(self, source: str) -> Extractor:
        """Return the first registered extractor that claims the source.

        Raises ConnectorError when none does — with the parsed scheme and
        the registered connector list so the user can self-serve.
        """
        for extractor in self._extractors.values():
            if extractor.can_handle(source):
                return extractor
        scheme, _ = parse_source(source)
        hint = f"scheme '{scheme}'" if scheme else "no scheme (local path)"
        raise ConnectorError(
            f"no registered connector can handle '{source}' ({hint}); "
            f"registered: {', '.join(self.names()) or 'none'}"
        )


default_registry = Registry()
