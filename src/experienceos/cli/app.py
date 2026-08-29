"""ExperienceOS command line interface.

Commands cover the full local loop: initialize a home, record or import
experiences, browse/search them, refine fields, and keep the knowledge
base healthy; plus config/AI diagnostics for the M2 assistant features.
"""

from __future__ import annotations

import functools
import json
import os
import shlex
import subprocess
import time
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import typer
from pydantic import ValidationError as PydanticValidationError
from rich.console import Console
from rich.markup import escape

from experienceos import __version__
from experienceos.ai.enrich import (
    apply_proposal,
    build_enrich_messages,
    normalize_proposals,
    parse_proposals,
)
from experienceos.ai.interview import (
    build_extraction_messages,
    collect_evidence_candidates,
    draft_from_extraction,
    interview_system_prompt,
    parse_extraction_json,
    save_transcript,
)
from experienceos.ai.mock import MockProvider
from experienceos.ai.provider import Message, build_provider
from experienceos.cli import render
from experienceos.config import load_config, resolve_home, save_config
from experienceos.connectors import (
    AuthoredExtractor,
    ExperienceDraft,
    ResumeExtractor,
    default_registry,
)
from experienceos.core.errors import (
    ExperienceOSError,
    NotFoundError,
    NotInitializedError,
    StorageError,
    ValidationError,
)
from experienceos.core.models import (
    SCHEMA_VERSION,
    Experience,
    ExperienceType,
    Period,
    Status,
    is_valid_year_month,
)
from experienceos.exporters import ExportOptions, default_exporter_registry
from experienceos.plugins import load_plugins, plugin_summary
from experienceos.services import experiences as services
from experienceos.services.homeops import backup_home, git_sync
from experienceos.stats import (
    evidence_coverage_by_year,
    technology_cooccurrence,
    technology_timeline,
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
            # escape: exception text may contain extras like 'experienceos[pdf]'
            # which rich would otherwise eat as markup tags
            err_console.print(f"[red]error:[/red] {escape(str(exc))}")
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
    # thin shell over the service layer since #018
    return services.get_experience(store, prefix)


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
    """ExperienceOS - your personal experience operating system."""
    ctx.obj = home
    load_plugins()  # entry-point connectors/exporters; failures contained


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


def _prompt_experience_basics() -> dict[str, Any]:
    """Shared prompts for `add` and `interview --no-ai`."""
    title = typer.prompt("Title")
    type_value = _prompt_type()
    start = _prompt_month("Start (YYYY-MM)")
    end = _prompt_month("End (YYYY-MM, leave empty if ongoing)", allow_empty=True)
    role = typer.prompt("Your role", default="")
    description = typer.prompt("Short description", default="")
    technology = typer.prompt("Technologies (comma separated)", default="")
    tags = typer.prompt("Tags (comma separated)", default="")
    return {
        "title": title,
        "type": type_value,
        "period": {"start": start, "end": end},
        "role": role,
        "description": description,
        "technology": [t.strip() for t in technology.split(",") if t.strip()],
        "tags": [t.strip() for t in tags.split(",") if t.strip()],
    }


@app.command()
@_friendly_errors
def add(ctx: typer.Context) -> None:
    """Record a new experience interactively.

    Only the essentials are asked here; refine the record later with
    `set`, `add-item` or `edit`.
    """
    store = _get_store(ctx)
    basics = _prompt_experience_basics()
    experience = Experience.new(**basics)
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
        help="Source to import: github:owner/repo, resume:cv.md, or a "
        "local path. PDF resumes arrive with v0.3 AI extraction "
        "(issue 012); use Markdown/plain text for now.",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Save drafts without the preview confirmation."
    ),
    author: str | None = typer.Option(
        None,
        "--author",
        help="Filter source activity by author: GitHub login or a local "
        "repo 'Name <email>' pattern (git matches against commit authors).",
    ),
) -> None:
    """Turn an external source into experience drafts (status=draft).

    Importing never overwrites existing records and never marks drafts as
    confirmed; refine them with `set`/`add-item`/`edit`, then
    `set <id> status active`.
    """
    store = _get_store(ctx)
    extractor = default_registry.find_handler(source)
    if isinstance(extractor, ResumeExtractor) and source.lower().rstrip(".").endswith(
        ".pdf"
    ):
        config = load_config(resolve_home(ctx.obj))
        extractor.set_ai(build_provider(config.ai), config.ai.model)
    if author is not None:
        if not isinstance(extractor, AuthoredExtractor):
            raise ValidationError(
                f"connector '{extractor.name}' does not support --author"
            )
        drafts = list(extractor.extract_for_author(source, author))
    else:
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


# -- interview (#011) ---------------------------------------------------------

_CONFIRM_SCALARS = (
    "title", "type", "period", "context", "role", "description", "reflection",
)
_CONFIRM_LISTS = ("technology", "contribution", "challenge", "solution", "result")


@app.command()
@_friendly_errors
def interview(
    ctx: typer.Context,
    language: str = typer.Option(
        "Chinese", "--language", help="Language the AI asks questions in."
    ),
    no_ai: bool = typer.Option(
        False, "--no-ai", help="Plain wizard, no AI involved (always available)."
    ),
) -> None:
    """Record an experience through a guided conversation (#011).

    The AI asks one question at a time (STAR), proposes a draft at the
    end, and you confirm every field before anything is saved. The
    transcript is only sent to your configured provider and is never
    stored unless extraction fails twice (then it lands in
    <home>/drafts/ for retry).
    """
    store = _get_store(ctx)
    home = resolve_home(ctx.obj)
    if no_ai:
        draft = _interview_wizard_draft()
    else:
        draft = _interview_ai_draft(home, language)
        render.render_experience(console, draft.experience)
        confirmed = _confirm_fields(draft.experience)
        if confirmed is None:
            console.print("Discarded.")
            raise typer.Exit()
        draft = ExperienceDraft(confirmed)
    saved = store.save(draft.experience)
    console.print(
        f"[green]Saved draft[/green] {draft.experience.id} -> {saved}\n"
        f"Refine it, then promote it: `experienceos set "
        f"{render.short_id(draft.experience.id)} status active`"
    )


def _interview_wizard_draft() -> ExperienceDraft:
    """`--no-ai` fallback: the pre-#006 plain wizard, kept forever."""
    basics = _prompt_experience_basics()
    return ExperienceDraft.create(
        origin="interview", created_by="user", **basics
    )


def _interview_ai_draft(home: Path, language: str) -> ExperienceDraft:
    """Conversation loop + extraction, with one JSON retry."""
    config = load_config(home)
    provider = build_provider(config.ai)
    model = config.ai.model
    console.print(
        "[dim]Conversation starts. Answer in your own words; type /done "
        "when the story feels complete.[/dim]"
    )
    messages = [
        Message(role="system", content=interview_system_prompt(language)),
        Message(
            role="user",
            content="I want to record an experience. Ask me your first question.",
        ),
    ]
    transcript: list[tuple[str, str]] = []
    candidates: list[dict[str, str]] = []
    question = provider.complete(messages)
    messages.append(Message(role="assistant", content=question))
    transcript.append(("assistant", question))
    console.print(f"[bold]AI:[/bold] {question}")
    while True:
        answer = typer.prompt("You", default="", show_default=False)
        if not answer.strip() or answer.strip() == "/done":
            break
        transcript.append(("user", answer))
        candidates.extend(collect_evidence_candidates(answer))
        messages.append(Message(role="user", content=answer))
        reply = provider.complete(messages)
        messages.append(Message(role="assistant", content=reply))
        transcript.append(("assistant", reply))
        console.print(f"[bold]AI:[/bold] {reply}")

    messages = build_extraction_messages(transcript, model)
    for attempt in (1, 2):
        raw = provider.complete(messages)
        try:
            data = parse_extraction_json(raw)
            break
        except ValueError as exc:
            if attempt == 2:
                path = save_transcript(home, transcript, model)
                err_console.print(
                    f"[red]error:[/red] {exc}; extraction failed twice, the "
                    f"transcript is kept at {path} — rerun `interview` later."
                )
                raise typer.Exit(code=1) from exc
            messages.append(Message(role="assistant", content=raw))
            messages.append(
                Message(
                    role="user",
                    content="That was not valid JSON. Output ONLY the JSON object.",
                )
            )
    return draft_from_extraction(data, model, candidates)


def _confirm_fields(experience: Experience) -> Experience | None:
    """Field-by-field accept/edit/drop; every field must be settled."""
    for field_name in (*_CONFIRM_SCALARS, *_CONFIRM_LISTS):
        current = getattr(experience, field_name)
        if not _field_has_value(current):
            continue
        _echo_field(field_name, current)
        answer = typer.prompt(
            f"{field_name} [Enter=keep / e=edit / d=drop]",
            default="",
            show_default=False,
        ).strip().lower()
        if answer == "d":
            _drop_field(experience, field_name)
        elif answer == "e":
            _edit_field(experience, field_name)
    if not typer.confirm("Save this experience?", default=True):
        return None
    return experience


def _field_has_value(value: Any) -> bool:
    if isinstance(value, list):
        return bool(value)
    if isinstance(value, Period):
        return True
    return bool(value)


def _echo_field(field_name: str, value: Any) -> None:
    if isinstance(value, Period):
        shown = value.display()
    elif isinstance(value, list):
        shown = " | ".join(
            item.location if hasattr(item, "location") else str(item)
            for item in value
        )
    else:
        shown = str(value)
    console.print(f"[bold]{field_name}:[/bold] {shown or '(empty)'}")


def _drop_field(experience: Experience, field_name: str) -> None:
    try:
        if field_name == "type":
            experience.type = ExperienceType.other
        elif isinstance(getattr(experience, field_name), list):
            setattr(experience, field_name, [])
        elif field_name == "period":
            experience.period.end = None
        else:
            setattr(experience, field_name, "")
    except PydanticValidationError as exc:  # pragma: no cover - defensive
        err_console.print(f"[red]cannot drop {field_name}:[/red] {exc}")


def _edit_field(experience: Experience, field_name: str) -> None:
    try:
        if field_name == "type":
            experience.type = _prompt_type()
        elif field_name == "period":
            start = _prompt_month("Start (YYYY-MM)")
            end = _prompt_month(
                "End (YYYY-MM, leave empty if ongoing)", allow_empty=True
            )
            experience.period = Period(start=start, end=end)
        elif field_name in _CONFIRM_LISTS:
            raw = typer.prompt(
                f"New {field_name} (comma separated replaces the list)", default=""
            )
            setattr(
                experience,
                field_name,
                [item.strip() for item in raw.split(",") if item.strip()],
            )
        else:
            setattr(
                experience,
                field_name,
                typer.prompt(f"New {field_name}", default=str(getattr(experience, field_name))),
            )
    except (PydanticValidationError, ValueError) as exc:
        err_console.print(f"[red]invalid value, keeping the old one:[/red] {exc}")


# -- enrich (#012) ------------------------------------------------------------


@app.command()
@_friendly_errors
def enrich(
    ctx: typer.Context,
    id: str = typer.Argument(..., help="ID or unique prefix"),
    all_yes: bool = typer.Option(
        False,
        "--all-yes",
        help="Apply every in-scope proposal without asking (prints a diff).",
    ),
) -> None:
    """Ask the AI for improvement proposals on one record (#012).

    Proposals may only rephrase contribution/challenge/solution/result
    or move technology names out of the description. Anything else —
    title, period, evidence, numbers — is rejected before you ever see
    it, and every accepted change still lands as your own edit.
    """
    store = _get_store(ctx)
    experience = _load_by_prefix(store, id)
    config = load_config(resolve_home(ctx.obj))
    provider = build_provider(config.ai)
    raw = provider.complete(build_enrich_messages(experience))
    accepted, rejected = normalize_proposals(parse_proposals(raw))
    for reason in rejected:
        err_console.print(f"[dim]dropped proposal: {reason}[/dim]")
    if not accepted:
        console.print("No in-scope proposals for this record.")
        return

    applied = 0
    for proposal in accepted:
        console.print(
            f"[bold]{proposal.field}[/bold]: {proposal.current}\n"
            f"  -> {proposal.suggested_display}"
        )
        if proposal.reason:
            console.print(f"  [dim]({proposal.reason})[/dim]")
        if not all_yes and not typer.confirm("Apply this proposal?", default=False):
            continue
        apply_proposal(experience, proposal)
        applied += 1
    if applied:
        store.save(experience)  # bumps updated_at
        console.print(
            f"[green]Applied[/green] {applied} proposal(s) to {experience.id}"
        )
    else:
        console.print("No proposals applied.")


# -- export (#014) ------------------------------------------------------------


@app.command("export")
@_friendly_errors
def export_cmd(
    ctx: typer.Context,
    name: str = typer.Argument(None, help="Exporter name (see --list)."),
    out: Path | None = typer.Option(
        None,
        "--out",
        "-o",
        help="Output file path (default: ./experienceos-export-<name>-<stamp><ext>).",
    ),
    status: Status | None = typer.Option(
        Status.active,
        "--status",
        "-s",
        help="Only export records with this status. Defaults to active: "
        "drafts never leak into an artifact.",
    ),
    list_names: bool = typer.Option(False, "--list", help="List available exporters."),
    type: ExperienceType | None = typer.Option(None, "--type", "-t"),
    tag: list[str] = typer.Option([], "--tag"),
    tech: list[str] = typer.Option([], "--tech"),
    since: str | None = typer.Option(None, "--since", help="YYYY-MM"),
    until: str | None = typer.Option(None, "--until", help="YYYY-MM"),
    timeline: bool = typer.Option(
        False,
        "--timeline",
        help="Markdown only: compact by-year table instead of the full profile.",
    ),
) -> None:
    """Export a filtered subset of records into a shareable artifact (#014).

    Filters reuse the search machinery (--type/--tag/--tech/--since/
    --until); the default selection is active records only, so drafts
    and archived records stay private unless you ask for them.
    """
    if list_names:
        console.print("Available exporters: " + ", ".join(default_exporter_registry.names()))
        return
    if not name:
        raise ValidationError(
            "export needs a format name; run `experienceos export --list`"
        )
    exporter = default_exporter_registry.get(name)  # fail before touching data
    store = _get_store(ctx)
    try:
        query = SearchQuery(
            types=(type,) if type else (),
            status=status,
            tags=tuple(tag),
            technology=tuple(tech),
            since=since,
            until=until,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    experiences = services.list_experiences(store, query)
    if not experiences:
        console.print("No experiences match the given filters.")
        raise typer.Exit()
    if out is not None:
        target = out
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = Path.cwd() / f"experienceos-export-{name}-{stamp}{exporter.suffix}"
    path = exporter.export(experiences, target, ExportOptions(timeline=timeline))
    dropped = getattr(exporter, "last_dropped", None)
    if dropped:
        detail = ", ".join(f"{field} x{n}" for field, n in sorted(dropped.items()))
        err_console.print(
            f"[dim]dropped unexportable fields: {escape(detail)}[/dim]",
            soft_wrap=True,
        )
    console.print(
        f"[green]Exported[/green] {len(experiences)} record(s) -> {path}",
        soft_wrap=True,
    )


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
        err_console.print(f"Your edits are kept at {scratch}; fix and rerun `edit`.")
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
    """Delete an experience (moves nothing to trash; this is final)."""
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
def stats(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False, "--json", help="Machine-readable output (used by exports and the API)."
    ),
) -> None:
    """Summarize the knowledge base: coverage, types and top technologies."""
    store = _get_store(ctx)
    summary = services.summarize(store)
    if summary["total"] == 0:
        console.print("Nothing recorded yet. Run `experienceos add` to start.")
        return
    if json_output:
        console.print_json(json.dumps(summary, ensure_ascii=False))
        return
    console.print(
        f"[bold]{summary['total']}[/bold] experiences | "
        f"evidence coverage [bold]{summary['evidence_coverage']:.0%}[/bold] | "
        f"with reflection: {summary['with_reflection'] / summary['total']:.0%}"
    )
    console.print(
        "By type: "
        + " | ".join(f"{k} {v}" for k, v in summary["by_type"].items())
    )
    console.print(
        "By status: "
        + " | ".join(f"{k} {v}" for k, v in summary["by_status"].items())
    )
    if summary["top_technologies"]:
        console.print(
            "Top technologies: " + " | ".join(summary["top_technologies"])
        )
    console.print(
        f"Unsupported claims (no evidence): {summary['unsupported_claims']}"
    )


@app.command()
@_friendly_errors
def profile(ctx: typer.Context) -> None:
    """Skill profile: technology timeline, co-occurrence and coverage (#017)."""
    store = _get_store(ctx)
    experiences = store.list_all()
    if not experiences:
        console.print("Nothing recorded yet. Run `experienceos add` to start.")
        return

    console.print("[bold]Technology timeline[/bold] (by first use)")
    for span in technology_timeline(experiences):
        arrow = f"{span.first} ~ {span.last}{'+ ongoing' if span.ongoing else ''}"
        console.print(f"  {span.name.ljust(16)} {arrow.ljust(28)} {span.records} record(s)")

    console.print("\n[bold]Frequent technology pairs[/bold]")
    pairs = technology_cooccurrence(experiences)
    if pairs:
        for first, second, count in pairs:
            console.print(f"  {first} + {second}: {count}")
    else:
        console.print("  (no records list two technologies yet)")

    console.print("\n[bold]Evidence coverage by year[/bold]")
    for year, covered, total in evidence_coverage_by_year(experiences):
        console.print(f"  {year}: {covered / total:.0%} ({covered}/{total})")

    console.print("\n[bold]By type[/bold]")
    type_counts = Counter(exp.type.value for exp in experiences)
    for name, count in type_counts.most_common():
        console.print(f"  {name}: {count}")


@app.command()
@_friendly_errors
def validate(ctx: typer.Context) -> None:
    """Check every stored record for schema problems."""
    store = _get_store(ctx)
    issues = services.validate_home(store)
    total = len(store.all_ids())
    if not issues:
        console.print(f"[green]All {total} record(s) valid.[/green]")
        return
    for issue in issues:
        err_console.print(f"[red]{issue.path.name}[/red]: {issue.error}")
    raise typer.Exit(code=1)


@app.command()
@_friendly_errors
def lint(
    ctx: typer.Context,
    all: bool = typer.Option(
        False, "--all", help="Also scan archived records (default: draft + active)."
    ),
) -> None:
    """Flag quantitative claims that lack evidence (#013).

    Exit code 1 when issues are found, so this can gate CI or pre-commit.
    """
    store = _get_store(ctx)
    issues = services.lint_home(store, include_archived=all)
    if not issues:
        console.print("[green]No unsupported claims.[/green]")
        return
    for issue in issues:
        console.print(
            f"[yellow]![/yellow] {render.short_id(issue.experience_id)} "
            f"[bold]{issue.field}[/bold]: {issue.sentence}"
        )
        console.print(f"    [dim]-> {issue.suggestion}[/dim]")
    console.print(
        f"\n{len(issues)} unsupported claim(s) across "
        f"{len({issue.experience_id for issue in issues})} record(s)."
    )
    raise typer.Exit(code=1)


# -- sync & backup (#021) -----------------------------------------------------


@app.command()
@_friendly_errors
def sync(
    ctx: typer.Context,
    push: str | None = typer.Option(
        None, "--push", help="Remote to push after committing (e.g. origin)."
    ),
    init: bool = typer.Option(
        False, "--init", help="Initialize a git repository in the home if none exists."
    ),
) -> None:
    """Version the home directory with git (#021).

    Commits every change with a message recording the record count.
    If the home is not a repository yet, --init sets one up. When
    pushing, make sure the remote is PRIVATE — this is your personal
    knowledge base.
    """
    home = resolve_home(ctx.obj)
    if not home.exists():
        raise NotInitializedError(
            f"{home} is not initialized. Run `experienceos init` first."
        )
    store = ExperienceStore(home)
    count = len(store.all_ids())
    drafts = sum(1 for e in store.list_all() if e.status is Status.draft)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    message = f"experienceos sync: {count} record(s) ({drafts} draft) at {stamp}"
    report = git_sync(home, message, push_remote=push, init=init)
    if report.initialized:
        console.print(f"[green]Initialized[/green] git repository at {home}")
    if report.committed:
        console.print(f"[green]Committed[/green] {message}")
    else:
        console.print("Already up to date — nothing to commit.")
    if report.pushed:
        console.print(f"[green]Pushed[/green] to {push} (keep the remote private!)")


@app.command()
@_friendly_errors
def backup(
    ctx: typer.Context,
    out: Path | None = typer.Option(
        None, "--out", "-o", help="Archive path (default: ./experienceos-backup-<stamp>.zip)."
    ),
) -> None:
    """Archive the whole home directory as a zip (#021).

    Includes config.toml and every experience; excludes git internals,
    scratch files and previous backups — the JSON files are the source
    of truth, so the archive alone restores everything.
    """
    home = resolve_home(ctx.obj)
    if not home.exists():
        raise NotInitializedError(
            f"{home} is not initialized. Run `experienceos init` first."
        )
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = out or Path.cwd() / f"experienceos-backup-{stamp}.zip"
    archive, count = backup_home(home, target)
    console.print(
        f"[green]Backup written[/green] {archive} ({count} file(s))",
        soft_wrap=True,
    )


# -- migrations (#020) --------------------------------------------------------


@app.command("migrate")
@_friendly_errors
def migrate(
    ctx: typer.Context,
    check: bool = typer.Option(
        False, "--check", help="Only report pending migrations; change nothing."
    ),
) -> None:
    """Bring stored records up to the current schema version (#020).

    Reads migrate transparently; the original file is always backed up
    under <home>/backup/ before a rewrite.
    """
    store = _get_store(ctx)
    pending = store.pending_migrations()
    if not pending:
        console.print(f"[green]All record(s) are at schema v{SCHEMA_VERSION}.[/green]")
        return
    for path, version in pending:
        console.print(f"pending: {path.name} (v{version} -> v{SCHEMA_VERSION})")
    if check:
        raise typer.Exit(code=1)
    for path, _version in pending:
        new_version = store.migrate_file(path)
        console.print(f"[green]migrated[/green] {path.name} -> v{new_version}")
    console.print(
        f"{len(pending)} record(s) migrated; originals kept in {store.backup_dir}"
    )


# -- plugins (#019) -----------------------------------------------------------

plugins_app = typer.Typer(help="Inspect installed connectors and exporters.")
app.add_typer(plugins_app, name="plugins")


@plugins_app.command("list")
@_friendly_errors
def plugins_list(ctx: typer.Context) -> None:
    """Show every entry-point plugin and its load state (#019)."""
    rows = plugin_summary(load_plugins())
    if not rows:
        console.print(
            "No entry-point plugins found. Built-ins: "
            + ", ".join(default_registry.names())
            + " (connectors), "
            + ", ".join(default_exporter_registry.names())
            + " (exporters)."
        )
        return
    for row in rows:
        marker = "[green]ok[/green]" if row["state"] != "failed" else "[red]failed[/red]"
        console.print(
            f"{marker} {row['name'].ljust(14)} {row['group'].ljust(10)} "
            f"v{row['version'].ljust(8)} from {row['source'].ljust(14)} "
            f"({row['state']}) {row['target']}"
        )
        if row["error"]:
            err_console.print(f"    [red]{escape(row['error'])}[/red]")


# -- config & AI diagnostics (#010) ------------------------------------------

config_app = typer.Typer(help="Inspect and change config.toml settings.")
app.add_typer(config_app, name="config")

ai_app = typer.Typer(help="AI provider diagnostics.")
app.add_typer(ai_app, name="ai")

# dotted key -> (AIConfig field, human description)
_CONFIG_KEYS: dict[str, str] = {
    "ai.provider": "provider adapter (openai-compat)",
    "ai.base_url": "OpenAI-compatible API base URL",
    "ai.model": "model name, e.g. glm-4.7 or gpt-4o-mini",
    "ai.api_key_env": "env var holding the API key — never the key itself",
    "ai.timeout": "request timeout in seconds",
}


def _ai_field(key: str) -> str:
    if key not in _CONFIG_KEYS:
        raise ValidationError(
            f"unsupported config key '{key}'. Allowed: {', '.join(_CONFIG_KEYS)}"
        )
    return key.split(".", 1)[1]


@config_app.command("list")
@_friendly_errors
def config_list(ctx: typer.Context) -> None:
    """Show every config key and its current value."""
    config = load_config(resolve_home(ctx.obj))
    values = {
        key: getattr(config.ai, key.split(".", 1)[1]) for key in _CONFIG_KEYS
    }
    width = max(len(key) for key in values)
    for key, value in values.items():
        console.print(f"{key.ljust(width)}  {value}  [dim]{_CONFIG_KEYS[key]}[/dim]")


@config_app.command("get")
@_friendly_errors
def config_get(ctx: typer.Context, key: str = typer.Argument(...)) -> None:
    """Print one config value: `config get ai.model`."""
    config = load_config(resolve_home(ctx.obj))
    console.print(getattr(config.ai, _ai_field(key)))


@config_app.command("set")
@_friendly_errors
def config_set(
    ctx: typer.Context,
    key: str = typer.Argument(...),
    value: str = typer.Argument(...),
) -> None:
    """Change one config value: `config set ai.model glm-4.7`.

    Secrets are never stored here — point `ai.api_key_env` at the
    environment variable that holds your API key.
    """
    field_name = _ai_field(key)
    home = resolve_home(ctx.obj)
    config = load_config(home)
    setattr(config.ai, field_name, _coerce_config_value(key, value))
    save_config(home, config)
    console.print(f"[green]Updated[/green] {key} = {getattr(config.ai, field_name)}")


def _coerce_config_value(key: str, value: str) -> Any:
    if key == "ai.timeout":
        try:
            return float(value)
        except ValueError as exc:
            raise ValidationError(
                f"{key} expects a number of seconds, got {value!r}"
            ) from exc
    return value


@ai_app.command("check")
@_friendly_errors
def ai_check(
    ctx: typer.Context,
    mock: bool = typer.Option(
        False, "--mock", help="Check the scripted MockProvider instead of the endpoint."
    ),
) -> None:
    """Verify the configured LLM endpoint answers a minimal request.

    Reports model name and round-trip latency. Without a key it names
    the exact environment variable to set; no key is ever read from or
    written to disk.
    """
    config = load_config(resolve_home(ctx.obj))
    provider = MockProvider("ok") if mock else build_provider(config.ai)
    started = time.perf_counter()
    reply = provider.complete(
        [Message(role="user", content="Reply with exactly: ok")]
    )
    elapsed = time.perf_counter() - started
    console.print(
        f"[green]ok[/green] provider={provider.name} model={config.ai.model} "
        f"reply={reply.strip()[:40]!r} latency={elapsed:.2f}s"
    )


def main() -> None:  # console_script entry point
    app()


if __name__ == "__main__":
    main()
