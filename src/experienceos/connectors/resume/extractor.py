"""Resume file connector (#009): Markdown / plain text -> drafts.

One draft per parsed entry; pure rules, no LLM. The original file path
is recorded in ``source.ref`` and attached as ``file`` evidence, so
every imported claim stays traceable to the document it came from.

PDF input is intentionally rejected until the M2 AI extraction path
lands (#012): a binary PDF cannot be parsed by regex reliably, and
guessing would violate the no-fabrication rule.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from experienceos.connectors.base import ExperienceDraft, parse_source
from experienceos.connectors.resume.parser import ResumeEntry, parse_resume
from experienceos.core.errors import ConnectorError
from experienceos.core.models import EvidenceKind, ExperienceType, SourceOrigin

_SCHEME = "resume"
SUPPORTED_SUFFIXES = (".md", ".markdown", ".txt")
PDF_SUFFIX = ".pdf"
_INTERN_RE = re.compile(r"实习|intern", re.IGNORECASE)

_TYPE_BY_CATEGORY = {
    "work": ExperienceType.work,
    "internship": ExperienceType.internship,
    "projects": ExperienceType.personal,
    "open_source": ExperienceType.open_source,
    "research": ExperienceType.research,
}


class ResumeError(ConnectorError):
    """A resume file could not be turned into experience drafts."""


class ResumeExtractor:
    """Extract one experience draft per resume entry."""

    name = _SCHEME

    def can_handle(self, source: str) -> bool:
        scheme, payload = parse_source(source)
        if scheme is not None and scheme != _SCHEME:
            return False
        path = Path(payload.strip()).expanduser()
        return path.is_file() and path.suffix.lower() in (
            *SUPPORTED_SUFFIXES,
            PDF_SUFFIX,
        )

    def extract(self, source: str) -> Iterator[ExperienceDraft]:
        path = self._resolve(source)
        if path.suffix.lower() == PDF_SUFFIX:
            raise ResumeError(
                f"PDF resumes are not supported yet: AI-assisted extraction "
                f"arrives in v0.3.0 (issue 012). Export '{path.name}' to "
                "Markdown or plain text and retry."
            )
        entries = parse_resume(_read_text(path))
        if not entries:
            raise ResumeError(
                f"no experience entries found in '{path}'; the parser looks "
                "for sections named 项目经历 / 工作经历 / 实习经历 / Projects / "
                "Experience / Work Experience whose entries carry a date, "
                "a bold line or a heading"
            )
        for entry in entries:
            yield self._draft_for(entry, path)

    def _resolve(self, source: str) -> Path:
        scheme, payload = parse_source(source)
        if scheme is not None and scheme != _SCHEME:
            raise ResumeError(
                f"the resume connector does not handle scheme '{scheme}:'"
            )
        path = Path(payload.strip()).expanduser()
        if not path.is_file():
            raise ResumeError(f"resume file not found: {path}")
        return path

    def _draft_for(self, entry: ResumeEntry, path: Path) -> ExperienceDraft:
        tags = ["resume"] if entry.dated else ["resume", "undated"]
        return ExperienceDraft.create(
            origin=SourceOrigin.resume,
            ref=str(path),
            title=entry.title,
            type=self._type_for(entry),
            period={"start": entry.start, "end": entry.end},
            description="\n".join(entry.description)
            or f"Imported from resume: {path.name}",
            technology=entry.technology,
            evidence=[
                {
                    "kind": EvidenceKind.file.value,
                    "location": str(path),
                    "description": "Source resume document",
                }
            ],
            tags=tags,
        )

    @staticmethod
    def _type_for(entry: ResumeEntry) -> ExperienceType:
        # Chinese resumes commonly list internships under 工作经历; the
        # 实习/intern keyword in the title is a stronger signal than the
        # section name.
        if entry.category == "work" and _INTERN_RE.search(entry.title):
            return ExperienceType.internship
        return _TYPE_BY_CATEGORY[entry.category]


def _read_text(path: Path) -> str:
    """Decode utf-8 first, then gb18030 (common for Chinese resumes)."""
    data = path.read_bytes()
    for encoding in ("utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


__all__ = [
    "PDF_SUFFIX",
    "SUPPORTED_SUFFIXES",
    "ResumeError",
    "ResumeExtractor",
]
