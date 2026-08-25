"""Core domain layer: models, identifiers and errors.

This layer has zero third-party I/O dependencies beyond pydantic and must
never import from storage, connectors, AI or CLI — everything else depends
on core, never the other way around.
"""

from experienceos.core.errors import (
    AIProviderError,
    AmbiguousIdError,
    ExperienceOSError,
    NotFoundError,
    NotInitializedError,
    StorageError,
    ValidationError,
)
from experienceos.core.models import (
    SCHEMA_VERSION,
    Evidence,
    EvidenceKind,
    Experience,
    ExperienceType,
    Period,
    Source,
    SourceOrigin,
    Status,
)
from experienceos.core.ulid import new_ulid

__all__ = [
    "SCHEMA_VERSION",
    "AIProviderError",
    "AmbiguousIdError",
    "Evidence",
    "EvidenceKind",
    "Experience",
    "ExperienceOSError",
    "ExperienceType",
    "NotFoundError",
    "NotInitializedError",
    "Period",
    "Source",
    "SourceOrigin",
    "Status",
    "StorageError",
    "ValidationError",
    "new_ulid",
]
