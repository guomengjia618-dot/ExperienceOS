"""HTML profile exporter (P1): one self-contained, print-ready page.

Same rules as the Markdown exporter (#015): stdlib ``string.Template``
keeps the exporter dependency-free, per-record blocks are rendered in
code, and everything is deterministic except the footer timestamp
(isolated in :func:`_now` so golden-file tests can freeze it). Record
content is escaped verbatim — the exporter renders, never embellishes.
External evidence URLs become links; local paths stay plain text. The
inline stylesheet carries a print block, so "Print → PDF" produces a
clean handout with no extra tooling.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from html import escape
from pathlib import Path
from string import Template
from urllib.parse import urlparse

from experienceos.core.errors import ExportError
from experienceos.core.models import Evidence, Experience
from experienceos.exporters.base import ExportOptions

TEMPLATES_DIR = Path(__file__).parent / "templates"

_STAR_SECTIONS = (
    ("Contribution", "contribution"),
    ("Challenge", "challenge"),
    ("Solution", "solution"),
    ("Result", "result"),
)


def _now() -> datetime:
    """Isolated so golden-file tests can freeze the footer timestamp."""
    return datetime.now()


def _is_external(location: str) -> bool:
    return urlparse(location).scheme in {"http", "https"}


class HtmlExporter:
    """Renders the full profile as one self-contained HTML document."""

    name = "html"
    suffix = ".html"

    def export(
        self,
        experiences: Sequence[Experience],
        target: Path,
        options: ExportOptions | None = None,
    ) -> Path:
        options = options or ExportOptions()
        if options.timeline:
            raise ExportError(
                "the html exporter has no timeline variant; use export markdown --timeline"
            )
        if not experiences:
            raise ExportError("nothing to export: the selection is empty")
        entries = sorted(
            experiences, key=lambda e: (e.period.start, e.id), reverse=True
        )
        template = Template(
            (TEMPLATES_DIR / "profile.html.tpl").read_text(encoding="utf-8")
        )
        document = template.substitute(
            entries=_render_profile(entries),
            generated=_now().strftime("%Y-%m-%d %H:%M"),
            count=len(entries),
        )
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(document, encoding="utf-8")
        return target


def _render_profile(entries: list[Experience]) -> str:
    return "\n".join(_render_entry(exp) for exp in entries)


def _render_entry(exp: Experience) -> str:
    meta = [escape(exp.type.value), escape(exp.period.display())]
    if exp.role:
        meta.append(escape(exp.role))
    if exp.technology:
        meta.append(escape(", ".join(exp.technology)))

    parts = ["<article class='entry'>", f"<h2>{escape(exp.title)}</h2>"]
    parts.append(f"<p class='meta'>{' · '.join(meta)}</p>")
    if exp.context:
        parts.append(f"<p class='context'>{escape(exp.context)}</p>")
    if exp.description:
        parts.append(f"<p>{escape(exp.description)}</p>")
    for label, field_name in _STAR_SECTIONS:
        items = getattr(exp, field_name)
        if items:
            rendered = "".join(f"<li>{escape(item)}</li>" for item in items)
            parts.append(f"<h3>{label}</h3><ul>{rendered}</ul>")
    if exp.evidence:
        items = "".join(f"<li>{_render_evidence(e)}</li>" for e in exp.evidence)
        parts.append(f"<h3>Evidence</h3><ul class='evidence'>{items}</ul>")
    if exp.reflection:
        parts.append(f"<blockquote>{escape(exp.reflection)}</blockquote>")
    parts.append("</article>")
    return "\n".join(parts)


def _render_evidence(evidence: Evidence) -> str:
    kind = f"<span class='kind'>{escape(evidence.kind.value)}</span>"
    suffix = f" — {escape(evidence.description)}" if evidence.description else ""
    location = escape(evidence.location)
    if _is_external(evidence.location):
        href = escape(evidence.location, quote=True)
        return f"{kind} <a href='{href}'>{location}</a>{suffix}"
    return f"{kind} <span class='local'>{location}</span>{suffix}"
