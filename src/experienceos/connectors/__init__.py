"""Connectors: turn fragmented sources into experience drafts.

M1 #006 ships the framework (protocol, drafts, registry, import command).
Built-in extractors arrive incrementally: GitHub (#007), local git
repositories (#008) and resumes (#009).
"""

from experienceos.connectors.base import (
    AuthoredExtractor,
    ExperienceDraft,
    Extractor,
    parse_source,
)
from experienceos.connectors.github import GitHubAPIError, GitHubExtractor
from experienceos.connectors.registry import Registry, default_registry

default_registry.register(GitHubExtractor())

__all__ = [
    "AuthoredExtractor",
    "ExperienceDraft",
    "Extractor",
    "GitHubAPIError",
    "GitHubExtractor",
    "Registry",
    "default_registry",
    "parse_source",
]
