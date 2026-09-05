"""Resume file connector (#009): Markdown / plain text -> drafts.

One draft per parsed entry; the rule-based parser never uses an LLM.
The original file path is recorded in ``source.ref`` and attached as
``file`` evidence, so every imported claim stays traceable to the
document it came from.

PDF input (#012) cannot be parsed by regex reliably: text is recovered
with ``pypdf`` (optional ``[pdf]`` extra) and then handed to an
injected :class:`MaterialDraftExtractor` (the AI extraction pipeline;
the composition root wires it in). The connector itself never imports
the ai tier — the no-fabrication rules of the extraction prompt apply,
and the output is a draft either way.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from experienceos.connectors.base import (
    ExperienceDraft,
    MaterialDraftExtractor,
    parse_source,
)
from experienceos.connectors.resume.parser import ResumeEntry, parse_resume
from experienceos.core.errors import ConnectorError
from experienceos.core.models import (
    EvidenceKind,
    ExperienceType,
    SourceOrigin,
)

_SCHEME = "resume"
SUPPORTED_SUFFIXES = (".md", ".markdown", ".txt")
PDF_SUFFIX = ".pdf"
_INTERN_RE = re.compile(r"实习|intern", re.IGNORECASE)
_MATERIAL_LABEL = "Material (resume text)"

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

    def __init__(self, material_extractor: MaterialDraftExtractor | None = None) -> None:
        self._materials = material_extractor  # AI injection point (#012)

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
            yield from self._pdf_drafts(path)
            return
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

    def set_material_extractor(self, extractor: MaterialDraftExtractor) -> None:
        """Wire the AI extraction pipeline (composition root's job)."""
        self._materials = extractor

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

    def _pdf_drafts(self, path: Path) -> Iterator[ExperienceDraft]:
        if self._materials is None:
            raise ResumeError(
                "PDF resumes need AI extraction; configure a provider first "
                "(`experienceos config set ai.model <model>` plus its API key "
                f"env var), or convert '{path.name}' to Markdown"
            )
        text = _extract_pdf_text(path)
        if not text.strip():
            raise ResumeError(
                f"no extractable text in '{path}' (scanned image PDFs need "
                "OCR, which is not supported)"
            )
        candidates = [
            {
                "kind": EvidenceKind.file.value,
                "location": str(path),
                "description": "Source resume document",
            }
        ]
        try:
            yield self._materials.extract_draft(
                [("resume text", text)],
                origin="resume",
                ref=str(path),
                candidates=candidates,
                material_label=_MATERIAL_LABEL,
            )
        except ValueError as exc:
            raise ResumeError(str(exc)) from exc

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


def _extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ResumeError(
            "pypdf is required for PDF resumes: pip install 'experienceos[pdf]'"
        ) from exc
    try:
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except ResumeError:
        raise
    except Exception as exc:
        raise ResumeError(f"could not read PDF '{path}': {exc}") from exc


def _read_text(path: Path) -> str:
    """Decode utf-8 first, then gb18030 (common for Chinese resumes)."""
    data = path.read_bytes()
    for encoding in ("utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")
