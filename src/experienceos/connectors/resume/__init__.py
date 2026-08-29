"""Resume connector (#009): Markdown / plain-text resumes -> drafts."""

from experienceos.connectors.resume.extractor import (
    PDF_SUFFIX,
    SUPPORTED_SUFFIXES,
    ResumeError,
    ResumeExtractor,
)
from experienceos.connectors.resume.parser import ResumeEntry, parse_resume

__all__ = [
    "PDF_SUFFIX",
    "SUPPORTED_SUFFIXES",
    "ResumeEntry",
    "ResumeError",
    "ResumeExtractor",
    "parse_resume",
]
