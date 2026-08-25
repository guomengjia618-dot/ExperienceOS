"""Connectors: turn fragmented sources into experience drafts.

M1 #006 ships the framework (protocol, drafts, registry, ``import``
command). Built-in extractors arrive next: GitHub (#007), local git
repositories (#008) and resumes (#009).
"""

from experienceos.connectors.base import (
    ExperienceDraft,
    Extractor,
    parse_source,
)
from experienceos.connectors.registry import Registry, default_registry

__all__ = [
    "ExperienceDraft",
    "Extractor",
    "Registry",
    "default_registry",
    "parse_source",
]
