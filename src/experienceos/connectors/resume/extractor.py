"""Resume file connector (#009): Markdown / plain text -> drafts.

One draft per parsed entry; the rule-based parser never uses an LLM.
The original file path is recorded in ``source.ref`` and attached as
``file`` evidence, so every imported claim stays traceable to the
document it came from.

PDF input (#012) cannot be parsed by regex reliably: text is recovered
with ``pypdf`` (optional ``[pdf]`` extra) and then handed to the same
AI extraction pipeline the interview uses — the no-fabrication rules in
EXTRACTION_PROMPT_V1 apply, and the output is a draft either way.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

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

    def __init__(self, provider: Any | None = None, model: str | None = None) -> None:
        self._provider = provider  # AI injection point for PDF extraction (#012)
        self._model = model

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

    def set_ai(self, provider: Any, model: str) -> None:
        """Attach the AI extraction pipeline (done by the CLI for PDFs)."""
        self._provider = provider
        self._model = model

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
        # local imports: the ai layer sits beside connectors, not below them
        from experienceos.ai.interview import (
            build_extraction_messages,
            draft_from_extraction,
            parse_extraction_json,
        )
        from experienceos.ai.provider import Message

        if self._provider is None or not self._model:
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
        messages = build_extraction_messages(
            [("resume text", text)],
            self._model,
            material_label="Material (resume text)",
        )
        candidates = [
            {
                "kind": EvidenceKind.file.value,
                "location": str(path),
                "description": "Source resume document",
            }
        ]
        data: dict[str, Any] | None = None
        last_error: Exception | None = None
        for attempt in (1, 2):
            raw = self._provider.complete(messages)
            try:
                data = parse_extraction_json(raw)
                break
            except ValueError as exc:
                last_error = exc
                if attempt == 2:
                    break
                messages.append(Message(role="assistant", content=raw))
                messages.append(
                    Message(
                        role="user",
                        content="That was not valid JSON. Output ONLY the JSON object.",
                    )
                )
        if data is None:
            raise ResumeError(
                f"AI extraction failed twice for '{path}': {last_error}"
            )
        yield draft_from_extraction(
            data, self._model, candidates=candidates, origin="resume", ref=str(path)
        )

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
