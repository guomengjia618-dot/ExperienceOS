"""Read-oriented REST API over the local knowledge base (#018).

The API is a thin shell over the service layer: it owns HTTP concerns
only. Scope is deliberately narrow — read endpoints plus draft
creation. Every state-changing confirmation gate (promote to active,
edit fields, delete) stays in the CLI, where the human is.

Requires the optional ``[api]`` extra (``pip install
'experienceos[api]'``). CORS is intentionally not configured: the
service binds to localhost and browser origins are off by default.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, Query
    from fastapi import Request as FastapiRequest
    from pydantic import BaseModel
except ImportError as exc:  # pragma: no cover - only hit without [api]
    raise ImportError(
        "fastapi is required for the API: pip install 'experienceos[api]'"
    ) from exc

from experienceos import __version__
from experienceos.config import resolve_home
from experienceos.core.errors import (
    AmbiguousIdError,
    NotFoundError,
    NotInitializedError,
    StorageError,
    ValidationError,
)
from experienceos.core.models import ExperienceType, Status
from experienceos.services import experiences as svc
from experienceos.storage import ExperienceStore, SearchQuery

DEFAULT_PORT = 8420


class DraftCreate(BaseModel):
    """Request body for draft creation; only draft-safe fields exposed."""

    title: str
    type: str
    period: dict[str, Any]
    context: str = ""
    role: str = ""
    description: str = ""
    technology: list[str] = []
    tags: list[str] = []
    status: str | None = None  # only ever "draft"; anything else is rejected


def create_app(home: Path | None = None) -> FastAPI:
    """Build the API bound to one ExperienceOS home directory."""
    resolved = Path(home) if home else resolve_home()
    if not resolved.exists():
        raise NotInitializedError(
            f"{resolved} is not initialized. Run `experienceos init` first "
            "(or set EXPERIENCEOS_HOME)."
        )
    store = ExperienceStore(resolved)
    app = FastAPI(
        title="ExperienceOS API",
        version=__version__,
        description="Read access to a local experience knowledge base.",
    )

    def _error(status_code: int, message: str, **extra: Any) -> Any:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=status_code, content={"detail": message, **extra})

    @app.exception_handler(NotFoundError)
    async def _not_found(_: FastapiRequest, exc: NotFoundError) -> Any:
        return _error(404, str(exc))

    @app.exception_handler(AmbiguousIdError)
    async def _ambiguous(_: FastapiRequest, exc: AmbiguousIdError) -> Any:
        return _error(400, str(exc), matches=exc.matches)

    @app.exception_handler(ValidationError)
    async def _invalid(_: FastapiRequest, exc: ValidationError) -> Any:
        return _error(422, str(exc))

    @app.exception_handler(StorageError)
    async def _storage(_: FastapiRequest, exc: StorageError) -> Any:
        return _error(409, str(exc))

    def _query(
        *,
        status: Status | None,
        type: ExperienceType | None,
        tag: list[str],
        tech: list[str],
        since: str | None,
        until: str | None,
        limit: int,
        text: str = "",
    ) -> SearchQuery:
        try:
            return SearchQuery(
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

    @app.get("/experiences")
    def list_experiences(
        status: Status | None = None,
        type: ExperienceType | None = None,
        tag: list[str] = Query([]),
        tech: list[str] = Query([]),
        since: str | None = None,
        until: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        query = _query(
            status=status, type=type, tag=tag, tech=tech,
            since=since, until=until, limit=limit,
        )
        return [exp.to_dict() for exp in svc.list_experiences(store, query)]

    @app.get("/search")
    def search_experiences(
        text: str,
        status: Status | None = None,
        type: ExperienceType | None = None,
        tag: list[str] = Query([]),
        tech: list[str] = Query([]),
        since: str | None = None,
        until: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        query = _query(
            text=text, status=status, type=type, tag=tag, tech=tech,
            since=since, until=until, limit=limit,
        )
        return [exp.to_dict() for exp in svc.search_experiences(store, query)]

    @app.get("/experiences/{id_or_prefix}")
    def get_experience(id_or_prefix: str) -> dict[str, Any]:
        return svc.get_experience(store, id_or_prefix).to_dict()

    @app.get("/stats")
    def stats() -> dict[str, Any]:
        return svc.summarize(store)

    @app.get("/lint")
    def lint(all: bool = False) -> dict[str, Any]:
        issues = svc.lint_home(store, include_archived=all)
        return {
            "count": len(issues),
            "issues": [
                {
                    "experience_id": issue.experience_id,
                    "field": issue.field,
                    "sentence": issue.sentence,
                    "suggestion": issue.suggestion,
                }
                for issue in issues
            ],
        }

    @app.post("/experiences/drafts", status_code=201)
    def create_draft(payload: DraftCreate) -> dict[str, Any]:
        return svc.create_draft(store, payload.model_dump(exclude_none=True)).to_dict()

    return app


def main() -> None:  # console_script entry point: experienceos-serve
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - only hit without [api]
        raise ImportError(
            "uvicorn is required to serve: pip install 'experienceos[api]'"
        ) from exc
    port = int(os.environ.get("EXPERIENCEOS_PORT", str(DEFAULT_PORT)))
    uvicorn.run(create_app(), host="127.0.0.1", port=port)
