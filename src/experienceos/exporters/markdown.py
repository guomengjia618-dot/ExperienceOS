"""Markdown profile / timeline exporter (#015).

Template decision recorded for the PR: stdlib ``string.Template`` keeps
the exporter dependency-free (no Jinja2). The templates in
``exporters/templates/`` hold the document skeleton; per-record blocks
are rendered in code because record structure is code, not config.

Rendering is deterministic except for the generation timestamp, which
goes through :func:`_now` so golden-file tests can freeze it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from string import Template

from experienceos.core.errors import ExportError
from experienceos.core.models import Experience
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


class MarkdownExporter:
    """Renders the full profile or the compact by-year timeline."""

    name = "markdown"
    suffix = ".md"

    def export(
        self,
        experiences: Sequence[Experience],
        target: Path,
        options: ExportOptions | None = None,
    ) -> Path:
        options = options or ExportOptions()
        if not experiences:
            raise ExportError("nothing to export: the selection is empty")
        entries = sorted(
            experiences, key=lambda e: (e.period.start, e.id), reverse=True
        )
        if options.timeline:
            body = _render_timeline(entries)
            template_name = "timeline.md.tpl"
        else:
            body = _render_profile(entries)
            template_name = "profile.md.tpl"
        template = Template((TEMPLATES_DIR / template_name).read_text(encoding="utf-8"))
        document = template.substitute(
            entries=body,
            table=body,
            generated=_now().strftime("%Y-%m-%d %H:%M"),
            count=len(entries),
        )
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(document, encoding="utf-8")
        return target


def _render_profile(entries: list[Experience]) -> str:
    return "\n\n".join(_render_entry(exp) for exp in entries).strip()


def _render_entry(exp: Experience) -> str:
    lines = [f"## {exp.title}", ""]
    lines.append(f"- **Type**: {exp.type.value}")
    lines.append(f"- **Period**: {exp.period.display()}")
    if exp.role:
        lines.append(f"- **Role**: {exp.role}")
    if exp.context:
        lines.append(f"- **Context**: {exp.context}")
    if exp.description:
        lines.append(f"- **Description**: {exp.description}")
    if exp.technology:
        lines.append(f"- **Technology**: {', '.join(exp.technology)}")
    for label, field_name in _STAR_SECTIONS:
        items = getattr(exp, field_name)
        if items:
            lines.append(f"- **{label}**:")
            lines.extend(f"  - {item}" for item in items)
    if exp.evidence:
        lines.append("- **Evidence**:")
        for evidence in exp.evidence:
            suffix = f" — {evidence.description}" if evidence.description else ""
            lines.append(f"  - [{evidence.kind.value}] {evidence.location}{suffix}")
    if exp.reflection:
        lines.extend(["", f"> Reflection: {exp.reflection}"])
    return "\n".join(lines)


def _render_timeline(entries: list[Experience]) -> str:
    by_year: dict[str, list[Experience]] = {}
    for exp in entries:
        by_year.setdefault(exp.period.start[:4], []).append(exp)
    blocks: list[str] = []
    for year in sorted(by_year, reverse=True):
        rows = ["| Title | Type | Period |", "| --- | --- | --- |"]
        for exp in by_year[year]:
            rows.append(
                f"| {exp.title} | {exp.type.value} | {exp.period.display()} |"
            )
        blocks.append(f"## {year}\n\n" + "\n".join(rows))
    return "\n\n".join(blocks).strip()
