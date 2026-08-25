"""ExperienceOS - an open-source personal experience operating system.

> Never forget what you have built.

ExperienceOS helps developers record, organize, understand and preserve
every project and creative experience they have taken part in. It turns
fragmented traces (code, repositories, GitHub activity, resumes, and
conversations) into structured, evidence-backed Experience Assets.
"""

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

__version__ = "0.1.0"

__all__ = [
    "SCHEMA_VERSION",
    "Evidence",
    "EvidenceKind",
    "Experience",
    "ExperienceType",
    "Period",
    "Source",
    "SourceOrigin",
    "Status",
    "__version__",
]
