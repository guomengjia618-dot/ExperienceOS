"""Rich rendering helpers for the CLI. Pure presentation, no business logic."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from experienceos.ai.schemas import EvidenceBrief
from experienceos.core.models import Experience
from experienceos.storage import SearchResult


def short_id(experience_id: str) -> str:
    """Compact, still-unambiguous prefix used in tables (resolvable by CLI)."""
    return experience_id[:12]


def unique_prefixes(experience_ids: list[str], minimum: int = 12) -> dict[str, str]:
    """Shortest per-id prefixes that stay unique within *experience_ids*."""
    prefixes: dict[str, str] = {}
    for length in range(minimum, 27):
        seen: dict[str, str] = {}
        clash = False
        for experience_id in experience_ids:
            prefix = experience_id[:length]
            if prefix in seen:
                clash = True
                break
            seen[prefix] = experience_id
        if not clash:
            prefixes = {v: k for k, v in seen.items()}
            break
    else:
        prefixes = {experience_id: experience_id for experience_id in experience_ids}
    return prefixes


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


# ruff: noqa: RUF001
def render_evidence_brief(console: Console, brief: EvidenceBrief) -> None:
    """Render the stable AI schema with Chinese labels instead of raw JSON keys."""

    console.print(Panel(brief.answer, title="分析结论", expand=False))
    if brief.highlights:
        console.print("[bold]项目亮点[/bold]")
        for item in brief.highlights:
            console.print(f"- {item}")
    if brief.citations:
        console.print("[bold]证据引用[/bold]")
        for citation in brief.citations:
            console.print(f"- {citation.claim}（{citation.experience_id}）")
            for location in citation.evidence_locations:
                console.print(f"  证据位置：{location}")
    if brief.evidence_gaps:
        console.print("[bold yellow]证据缺口[/bold yellow]")
        for item in brief.evidence_gaps:
            console.print(f"- {item}")
    if brief.next_actions:
        console.print("[bold]下一步建议[/bold]")
        for item in brief.next_actions:
            console.print(f"- {item}")
