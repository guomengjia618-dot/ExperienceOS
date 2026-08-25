"""Exception hierarchy for ExperienceOS.

CLI and library callers should only need to catch ``ExperienceOSError``
to handle expected failures (bad input, missing data, storage problems)
while programming errors keep raising built-in exceptions.
"""

from __future__ import annotations


class ExperienceOSError(Exception):
    """Base class for all expected ExperienceOS failures."""


class ValidationError(ExperienceOSError):
    """A record failed domain validation (bad schema, dates, IDs, ...)."""


class NotFoundError(ExperienceOSError):
    """A requested experience does not exist."""

    def __init__(self, experience_id: str) -> None:
        super().__init__(f"Experience not found: {experience_id}")
        self.experience_id = experience_id


class AmbiguousIdError(ExperienceOSError):
    """An ID prefix matched more than one experience."""

    def __init__(self, prefix: str, matches: list[str]) -> None:
        super().__init__(
            f"ID prefix '{prefix}' is ambiguous, matches {len(matches)} experiences: "
            + ", ".join(matches[:5])
        )
        self.prefix = prefix
        self.matches = matches


class StorageError(ExperienceOSError):
    """The local storage layer could not read or write a record."""


class ConnectorError(ExperienceOSError):
    """A connector (import source) is unknown, misconfigured, or failed."""


class NotInitializedError(ExperienceOSError):
    """The ExperienceOS home directory has not been initialized."""


class AIProviderError(ExperienceOSError):
    """An LLM provider is misconfigured or failed."""
