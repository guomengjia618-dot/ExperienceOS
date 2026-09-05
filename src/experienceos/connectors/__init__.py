"""Connectors: turn fragmented sources into experience drafts.

M1 #006 ships the framework (protocol, drafts, registry, import command).
Built-in extractors: GitHub (#007), local git repositories (#008),
resumes (#009) and plain project directories (#028).
"""

from experienceos.connectors.base import (
    AcceptsMaterialExtractor,
    AuthoredExtractor,
    ExperienceDraft,
    Extractor,
    Material,
    MaterialDraftExtractor,
    parse_source,
)
from experienceos.connectors.github import GitHubAPIError, GitHubExtractor
from experienceos.connectors.gitrepo import GitRepoError, GitRepoExtractor
from experienceos.connectors.projectfiles import (
    ProjectFilesError,
    ProjectFilesExtractor,
)
from experienceos.connectors.registry import Registry, default_registry
from experienceos.connectors.resume import ResumeError, ResumeExtractor

default_registry.register(GitHubExtractor())
default_registry.register(GitRepoExtractor())
default_registry.register(ResumeExtractor())
default_registry.register(ProjectFilesExtractor())

__all__ = [
    "AcceptsMaterialExtractor",
    "AuthoredExtractor",
    "ExperienceDraft",
    "Extractor",
    "GitHubAPIError",
    "GitHubExtractor",
    "GitRepoError",
    "GitRepoExtractor",
    "Material",
    "MaterialDraftExtractor",
    "ProjectFilesError",
    "ProjectFilesExtractor",
    "Registry",
    "ResumeError",
    "ResumeExtractor",
    "default_registry",
    "parse_source",
]
