"""ExperienceOS command line interface.

Twelve commands covering the M0 loop: initialize a home, record
experiences, browse/search them, refine fields, and keep the local
knowledge base healthy.
"""

from __future__ import annotations

import functools
import json
import os
import shlex
import subprocess
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer
from pydantic import ValidationError as PydanticValidationError
from rich.console import Console

from experienceos import __version__
from experienceos.cli import render
from experienceos.config import load_config, resolve_home, save_config
from experienceos.connectors import default_registry
from experienceos.core.errors import (
    ExperienceOSError,
    NotFoundError,
    NotInitializedError,
    StorageError,
    ValidationError,
)
from experienceos.core.models import (
    Experience,
    ExperienceType,
    Status,
    is_valid_year_month,
)
from experienceos.storage import ExperienceStore, SearchQuery, search

app = typer.Typer(
    name="experienceos",
    help="Never forget what you have built. Record, organize and search "
    "your personal experience assets.",
    no_args_is_help=True,
)
console = Console()
err_console = Console(stderr=True)

_LIST_FIELDS = {"technology", "tags", "contribution", "challenge", "solution", "result"}
_SET_TARGETS = {
    "title",
    "context",
    "role",
    "description",
    "reflection",
    "status",
    "type",
    "period.start",
    "period.end",
}


# -- shared plumbing ---------------------------------------------------------


def _friendly_errors(func: Callable[..., Any]) -> Callable[..., Any]:
    """Turn expected ExperienceOS failures into clean one-line CLI errors."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except ExperienceOSError as exc:
            err_console.print(f"[red]error:[/red] {exc}")
            raise typer.Exit(code=1) from exc

    return wrapper


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"experienceos {__version__}")
        raise typer.Exit()


def _get_store(ctx: typer.Context) -> ExperienceStore:
    home = resolve_home(ctx.obj)
    if not home.exists():
        raise NotInitializedError(
            f"{home} is not initialized. Run `experienceos init` first "
            "(or set EXPERIENCEOS_HOME)."
        )
    return ExperienceStore(home)


def _load_by_prefix(store: ExperienceStore, prefix: str) -> Experience:
    return store.load(store.resolve(prefix))


# -- commands ----------------------------------------------------------------


@app.callback()
def root(
    ctx: typer.Context,
    home: Path | None = typer.Option(
        None,
        "--home",
        help="ExperienceOS home directory (default: $EXPERIENCEOS_HOME or ~/.experienceos).",
    ),
    version: bool = typer.Option(
        None, "--version", callback=_version_callback, is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """ExperienceOS — your personal experience operating system."""
    ctx.obj = home


@app.command()
@_friendly_errors
def init(ctx: typer.Context) -> None:
    """Create the ExperienceOS home directory and default config."""
    home = resolve_home(ctx.obj)
    experiences_dir = home / "experiences"
    experiences_dir.mkdir(parents=True, exist_ok=True)
    if home.joinpath("config.toml").exists():
        console.print(f"[green]Already initialized at[/green] {home}")
    else:
        path = save_config(home, load_config(home))
        console.print(f"[green]Initialized ExperienceOS home at[/green] {home}")
        console.print(f"Config written to {path}")
    console.print("Next: record your first experience with `experienceos add`.")


@app.command()
@_friendly_errors
def path(ctx: typer.Context) -> None:
    """Print the active home directory."""
    # soft_wrap: the whole point is a copy-pastable path; wrapping at the
    # console width would corrupt it on narrow terminals (and CI runners).
    console.print(str(resolve_home(ctx.obj)), soft_wrap=True)


def _prompt_month(label: str, allow_empty: bool = False) -> str | None:
    while True:
        value = typer.prompt(label, default="", show_default=False).strip()
        if not value and allow_empty:
            return None
        if is_valid_year_month(value):
            return value
        typer.echo("Expected format YYYY-MM (e.g. 2024-06). Try again.")


def _prompt_type() -> ExperienceType:
    options = "/".join(t.value for t in ExperienceType)
    while True:
        value = typer.prompt(f"Type ({options})").strip().lower()
        try:
            return ExperienceType(value)
        except ValueError:
            typer.echo("Unknown type, choose one of the listed values.")


@app.command()
@_friendly_errors
def add(ctx: typer.Context) -> None:
    """Record a new experience interactively.

    Only the essentials are asked here; refine the record later with
    `set`, `add-item` or `edit`.
    """
    store = _get_store(ctx)
    title = typer.prompt("Title")
    type_value = _prompt_type()
    start = _prompt_month("Start (YYYY-MM)")
    end = _prompt_month("End (YYYY-MM, leave empty if ongoing)", allow_empty=True)
    role = typer.prompt("Your role", default="")
    description = typer.prompt("Short description", default="")
    technology = typer.prompt("Technologies (comma separated)", default="")
    tags = typer.prompt("Tags (comma separated)", default="")

    experience = Experience.new(
        title=title,
        type=type_value,
        period={"start": start, "end": end},
        role=role,
        description=description,
        technology=[t.strip() for t in technology.split(",") if t.strip()],
        tags=[t.strip() for t in tags.split(",") if t.strip()],
    )
    render.render_experience(console, experience)
    if not typer.confirm("Save this experience?", default=True):
        console.print("Discarded.")
        raise typer.Exit()
    saved = store.save(experience)
    console.print(f"[green]Saved[/green] {experience.id} -> {saved}")


@app.command("import")
@_friendly_errors
def import_cmd(
    ctx: typer.Context,
    source: str = typer.Argument(
        ...,
        help="Source to import: github:owner/repo, resume:cv.md, or a local path.",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Save drafts without the preview confirmation."
    ),
) -> None:
    """Turn an external source into experience drafts (status=draft).

    Importing never overwrites existing records and never marks drafts as
    confirmed — refine them with `set`/`add-item`/`edit`, then
    `set <id> status active`.
    """
    store = _get_store(ctx)
    extractor = default_registry.find_handler(source)
    drafts = list(extractor.extract(source))
    if not drafts:
        console.print(f"Connector '{extractor.name}' produced no drafts for {source!r}.")
        raise typer.Exit()

    for draft in drafts:
        render.render_experience(console, draft.experience)
    if not yes and not typer.confirm(f"Save {len(drafts)} draft(s)?", default=True):
        console.print("Discarded.")
        raise typer.Exit()

    saved_ids: list[str] = []
    for draft in drafts:
        if store.exists(draft.experience.id):
            raise StorageError(
                f"record id conflict: {draft.experience.id} already exists "
                "(import never overwrites records)"
            )
        store.save(draft.experience)
        saved_ids.append(draft.experience.id)

    console.print(f"[green]Saved[/green] {len(saved_ids)} draft(s) via '{extractor.name}':")
    for exp_id in saved_ids:
        console.print(f"  experienceos show {render.short_id(exp_id)}   # {exp_id}")


@app.command("list")
@_friendly_errors
def list_cmd(
    ctx: typer.Context,
    type: ExperienceType | None = typer.Option(None, "--type", "-t"),
    status: Status | None = typer.Option(None, "--status", "-s"),
    tag: list[str] = typer.Option([], "--tag"),
    tech: list[str] = typer.Option([], "--tech"),
    since: str | None = typer.Option(None, "--since", help="YYYY-MM"),
    until: str | None = typer.Option(None, "--until", help="YYYY-MM"),
    limit: int = typer.Option(50, "--limit", "-l"),
) -> None:
    """Browse experiences, newest first, with optional filters."""
    store = _get_store(ctx)
    query = SearchQuery(
        types=(type,) if type else (),
        status=status,
        tags=tuple(tag),
        technology=tuple(tech),
        since=since,
        until=until,
        limit=limit,
    )
    results = search(store.list_all(), query)
    if not results:
        console.print("No experiences found. Record one with `experienceos add`.")
        return
    render.render_results(console, results)


@app.command()
@_friendly_errors
def show(ctx: typer.Context, id: str = typer.Argument(..., help="ID or unique prefix")) -> None:
    """Display one experience in full detail."""
    store = _get_store(ctx)
    render.render_experience(console, _load_by_prefix(store, id))


@app.command("search")
@_friendly_errors
def search_cmd(
    ctx: typer.Context,
    text: str = typer.Argument(..., help="Free-text query; terms are AND-ed"),
    type: ExperienceType | None = typer.Option(None, "--type", "-t"),
    status: Status | None = typer.Option(None, "--status", "-s"),
    tag: list[str] = typer.Option([], "--tag"),
    tech: list[str] = typer.Option([], "--tech"),
    since: str | None = typer.Option(None, "--since", help="YYYY-MM"),
    until: str | None = typer.Option(None, "--until", help="YYYY-MM"),
    limit: int = typer.Option(20, "--limit", "-l"),
) -> None:
    """Full-text search across experiences (title and body weighted)."""
    store = _get_store(ctx)
    try:
        query = SearchQuery(
            text=text,
            types=(type,) if type else (),
            status=status,
            tags=tuple(tag),
            technology=tuple(tech),
            since=since,
            until=until,
            limit=limit,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    results = search(store.list_all(), query)
    if not results:
        console.print("No matches.")
        return
    render.render_results(console, results)
    for result in results[:3]:
        if result.matched_fields:
            console.print(
                f"[dim]{render.short_id(result.experience.id)} matched: "
                f"{', '.join(result.matched_fields)} (score {result.score:g})[/dim]"
            )


@app.command("set")
@_friendly_errors
def set_cmd(
    ctx: typer.Context,
    id: str = typer.Argument(...),
    key: str = typer.Argument(..., help=f"One of: {', '.join(sorted(_SET_TARGETS))}"),
    value: str = typer.Argument(..., help="New value ('' for period.end clears it)"),
) -> None:
    """Update a scalar field: `set <id> title "New title"`."""
    if key not in _SET_TARGETS:
        raise ValidationError(f"unsupported key '{key}'. Allowed: {sorted(_SET_TARGETS)}")
    store = _get_store(ctx)
    experience = _load_by_prefix(store, id)
    try:
        if key == "period.start":
            experience.period.start = value
        elif key == "period.end":
            experience.period.end = value or None
        elif key == "status":
            experience.status = Status(value)
        elif key == "type":
            experience.type = ExperienceType(value)
        else:
            setattr(experience, key, value)
    except (PydanticValidationError, ValueError) as exc:
        raise ValidationError(str(exc)) from exc
    store.save(experience)
    console.print(f"[green]Updated[/green] {key} on {experience.id}")


@app.command("add-item")
@_friendly_errors
def add_item_cmd(
    ctx: typer.Context,
    id: str = typer.Argument(...),
    field: str = typer.Argument(..., help=f"One of: {', '.join(sorted(_LIST_FIELDS))}"),
    items: list[str] = typer.Argument(..., help="One or more items to append"),
) -> None:
    """Append items to a list field: `add-item <id> contribution "Did X"`."""
    if field not in _LIST_FIELDS:
        raise ValidationError(f"unsupported field '{field}'. Allowed: {sorted(_LIST_FIELDS)}")
    store = _get_store(ctx)
    experience = _load_by_prefix(store, id)
    merged = list(getattr(experience, field)) + list(items)
    try:
        setattr(experience, field, merged)
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc
    store.save(experience)
    console.print(
        f"[green]Appended[/green] {len(items)} item(s) to {field} on {experience.id}"
    )


def _editor_tokens() -> list[str]:
    editor = (
        os.environ.get("EXPERIENCEOS_EDITOR")
        or os.environ.get("EDITOR")
        or ("notepad" if os.name == "nt" else "vi")
    )
    if os.name == "nt":
        # posix=False keeps backslashes intact; strip surrounding quotes manually
        return [token.strip('"') for token in shlex.split(editor, posix=False)]
    return shlex.split(editor)


@app.command()
@_friendly_errors
def edit(ctx: typer.Context, id: str = typer.Argument(...)) -> None:
    """Edit an experience as JSON in $EDITOR (validated before saving)."""
    store = _get_store(ctx)
    full_id = store.resolve(id)
    experience = store.load(full_id)
    # no ".json" suffix: the storage layer globs *.json and must ignore scratch files
    scratch = store.experiences_dir / f".{full_id}.edit.tmp"

    if scratch.exists() and typer.confirm("Unsaved edits found. Resume them?", default=True):
        pass
    else:
        scratch.write_text(experience.model_dump_json(indent=2) + "\n", encoding="utf-8")

    subprocess.run([*_editor_tokens(), str(scratch)], check=False)
    try:
        updated = Experience.from_dict(json.loads(scratch.read_text(encoding="utf-8")))
    except (PydanticValidationError, ValueError) as exc:
        err_console.print(f"[red]Invalid JSON, not saved.[/red] {exc}")
        err_console.print(f"Your edits are kept at {scratch} — fix and rerun `edit`.")
        raise typer.Exit(code=1) from exc
    if updated.id != full_id:
        scratch.unlink(missing_ok=True)
        raise ValidationError("editing changed the record id; refusing to save")
    store.save(updated)
    scratch.unlink(missing_ok=True)
    console.print(f"[green]Saved[/green] {updated.id}")


@app.command()
@_friendly_errors
def delete(
    ctx: typer.Context,
    id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete an experience (moves nothing to trash — this is final)."""
    store = _get_store(ctx)
    full_id = store.resolve(id)
    experience = store.load(full_id)
    if not yes:
        render.render_experience(console, experience)
        if not typer.confirm("Delete this experience?", default=False):
            console.print("Cancelled.")
            raise typer.Exit()
    if store.delete(full_id):
        console.print(f"[green]Deleted[/green] {full_id}")
    else:
        raise NotFoundError(full_id)


@app.command()
@_friendly_errors
def stats(ctx: typer.Context) -> None:
    """Summarize the knowledge base: coverage, types and top technologies."""
    store = _get_store(ctx)
    experiences = store.list_all()
    if not experiences:
        console.print("Nothing recorded yet. Run `experienceos add` to start.")
        return
    with_evidence = sum(1 for e in experiences if e.evidence)
    console.print(
        f"[bold]{len(experiences)}[/bold] experiences · "
        f"evidence coverage [bold]{with_evidence / len(experiences):.0%}[/bold] · "
        f"with reflection: "
        f"{sum(1 for e in experiences if e.reflection) / len(experiences):.0%}"
    )
    type_counts = Counter(e.type.value for e in experiences)
    console.print("By type: " + " · ".join(f"{k} {v}" for k, v in type_counts.most_common()))
    status_counts = Counter(e.status.value for e in experiences)
    console.print("By status: " + " · ".join(f"{k} {v}" for k, v in status_counts.most_common()))
    tech_counts = Counter(t.casefold() for e in experiences for t in e.technology)
    if tech_counts:
        console.print(
            "Top technologies: " + " · ".join(k for k, _ in tech_counts.most_common(10))
        )


@app.command()
@_friendly_errors
def validate(ctx: typer.Context) -> None:
    """Check every stored record for schema problems."""
    store = _get_store(ctx)
    issues = store.validate()
    total = len(store.all_ids())
    if not issues:
        console.print(f"[green]All {total} record(s) valid.[/green]")
        return
    for issue in issues:
        err_console.print(f"[red]{issue.path.name}[/red]: {issue.error}")
    raise typer.Exit(code=1)


def main() -> None:  # console_script entry point
    app()


if __name__ == "__main__":
    main()
