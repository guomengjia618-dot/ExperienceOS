"""Rich rendering helpers for the CLI. Pure presentation, no business logic."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from experienceos.core.models import Experience
from experienceos.storage import SearchResult


def short_id(experience_id: str) -> str:
    """Compact, still-unambiguous prefix used in tables (resolvable by CLI)."""
    return experience_id[:12]


def render_experience(console: Console, exp: Experience) -> None:
    body = Table.grid(padding=(0, 2))
    body.add_column(style="dim", justify="right")
    body.add_column(overflow="fold")

    body.add_row("id", exp.id)
    body.add_row("type", exp.type.value)
    body.add_row("period", exp.period.display())
    body.add_row("role", exp.role or "-")
    body.add_row("status", exp.status.value)
    body.add_row("technology", ", ".join(exp.technology) or "-")
    body.add_row("tags", ", ".join(exp.tags) or "-")
    body.add_row("context", exp.context or "-")
    body.add_row("description", exp.description or "-")

    for label, items in (
        ("contribution", exp.contribution),
        ("challenge", exp.challenge),
        ("solution", exp.solution),
        ("result", exp.result),
    ):
        if items:
            body.add_row(label, "\n".join(f"- {item}" for item in items))
    if exp.reflection:
        body.add_row("reflection", exp.reflection)

    if exp.evidence:
        body.add_row(
            "evidence",
            "\n".join(f"{ev.kind.value}: {ev.location}" for ev in exp.evidence),
        )
    body.add_row(
        "source",
        f"{exp.source.origin.value} | created_by {exp.source.created_by}",
    )
    console.print(Panel(body, title=f"{exp.title}", expand=False))


def render_results(console: Console, results: list[SearchResult]) -> None:
    # deliberately lean: 5 columns fit an 80-col terminal without truncating titles
    table = Table(title=f"{len(results)} experience(s)")
    table.add_column("id", style="cyan", no_wrap=True)
    table.add_column("title", style="bold", ratio=1, overflow="fold")
    table.add_column("type")
    table.add_column("period")
    table.add_column("status")
    for result in results:
        exp = result.experience
        table.add_row(
            short_id(exp.id),
            exp.title,
            exp.type.value,
            exp.period.display(),
            exp.status.value,
        )
    console.print(table)
    if results:
        console.print(
            "[dim]Tip: use any unique id prefix with `experienceos show`, e.g. "
            f"`experienceos show {short_id(results[0].experience.id)}`[/dim]"
        )
