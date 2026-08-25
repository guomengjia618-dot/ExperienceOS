"""Core domain model: the Experience Asset.

This module is the contract every other layer (storage, connectors, AI,
exporters) programs against. Design rules:

- Fields follow the public ExperienceOS schema exactly; additions are
  optional with defaults so records stay forward/backward compatible.
- ``extra="forbid"`` everywhere: experience files are hand-editable JSON,
  and a typo'd key must fail loudly instead of being silently dropped.
- Every record carries ``schema_version`` so future migrations have an
  anchor, and ``source`` so we always know where a record came from
  (user, importer, or ``ai:<model>``) — the foundation of the
  "no fabrication, link evidence" philosophy.
"""

from __future__ import annotations

import enum
import re
import secrets
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .ulid import new_ulid

SCHEMA_VERSION = 1

_YEAR_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_EXPERIENCE_ID_RE = re.compile(r"^exp_[0-9A-HJKMNP-TV-Z]{26}$")


def is_valid_year_month(value: str) -> bool:
    """True when *value* is a valid ``YYYY-MM`` string."""
    return bool(_YEAR_MONTH_RE.match(value))


def utcnow() -> datetime:
    """Timezone-aware UTC now (naive datetimes are forbidden on the wire)."""
    return datetime.now(timezone.utc)


class ExperienceType(str, enum.Enum):
    """The kind of experience. deliberately broader than "project"."""

    work = "work"
    internship = "internship"
    open_source = "open_source"
    competition = "competition"
    course_project = "course_project"
    graduation_project = "graduation_project"
    personal = "personal"
    research = "research"
    other = "other"


class Status(str, enum.Enum):
    """Lifecycle of a record, not of the project itself."""

    draft = "draft"
    active = "active"
    archived = "archived"


class EvidenceKind(str, enum.Enum):
    url = "url"
    repo = "repo"
    commit = "commit"
    pull_request = "pull_request"
    issue = "issue"
    file = "file"
    doc = "doc"
    image = "image"
    other = "other"


class SourceOrigin(str, enum.Enum):
    manual = "manual"
    github = "github"
    git_repo = "git_repo"
    resume = "resume"
    interview = "interview"
    import_ = "import"

    # allow "import" (a Python keyword) as the wire value
    @classmethod
    def _missing_(cls, value: object) -> SourceOrigin | None:
        if value == "import":
            return cls.import_
        return None

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


class Period(BaseModel):
    """Involvement window in ``YYYY-MM`` precision. ``end=None`` means ongoing."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    start: str
    end: str | None = None

    @field_validator("start", "end")
    @classmethod
    def _check_year_month(cls, value: str | None) -> str | None:
        if value is not None and not _YEAR_MONTH_RE.match(value):
            raise ValueError(f"period dates must be YYYY-MM, got: {value!r}")
        return value

    @model_validator(mode="after")
    def _check_order(self) -> Period:
        if self.end is not None and self.end < self.start:
            raise ValueError("period.end must not be earlier than period.start")
        return self

    @property
    def is_ongoing(self) -> bool:
        return self.end is None

    def display(self) -> str:
        return f"{self.start} ~ {self.end or 'present'}"


class Evidence(BaseModel):
    """A pointer to something that proves a claim in the experience.

    Evidence is stored as references (URLs, repo coordinates, commit SHAs,
    file paths) — never as copied content — so the record stays small and
    the source of truth remains where the artifact lives.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: f"ev_{secrets.token_hex(6)}")
    kind: EvidenceKind = EvidenceKind.other
    location: str = Field(min_length=1, description="URL, repo slug, commit SHA or file path")
    description: str = ""
    captured_at: datetime | None = None

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        if not re.match(r"^ev_[0-9a-f]{6,}$", value):
            raise ValueError(f"invalid evidence id: {value!r}")
        return value


class Source(BaseModel):
    """Provenance: how this record came to exist and who authored it."""

    model_config = ConfigDict(extra="forbid")

    origin: SourceOrigin = SourceOrigin.manual
    ref: str | None = None
    created_by: str = "user"
    created_at: datetime = Field(default_factory=utcnow)


class Experience(BaseModel):
    """A single structured experience — the core asset of ExperienceOS."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    schema_version: int = Field(default=SCHEMA_VERSION, frozen=True)
    id: str
    title: str = Field(min_length=1, max_length=200)
    type: ExperienceType
    period: Period
    context: str = ""
    role: str = ""
    description: str = ""
    technology: list[str] = []
    contribution: list[str] = []
    challenge: list[str] = []
    solution: list[str] = []
    result: list[str] = []
    reflection: str = ""
    evidence: list[Evidence] = []
    tags: list[str] = []
    status: Status = Status.active
    source: Source = Field(default_factory=Source)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        if not _EXPERIENCE_ID_RE.match(value):
            raise ValueError(
                "experience id must be 'exp_' followed by a 26-char ULID, "
                f"got: {value!r}"
            )
        return value

    @field_validator("title", "context", "role", "description", "reflection", mode="before")
    @classmethod
    def _strip_text(cls, value: Any) -> Any:
        # mode="before": trim first so length constraints see the cleaned value
        return value.strip() if isinstance(value, str) else value

    @field_validator(
        "technology", "tags", "contribution", "challenge", "solution", "result",
        mode="before",
    )
    @classmethod
    def _clean_str_list(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            return value  # let pydantic produce a proper type error
        cleaned = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        # dedupe case-insensitively, keeping first occurrence order
        seen: set[str] = set()
        unique: list[str] = []
        for item in cleaned:
            key = item.casefold()
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique

    @model_validator(mode="after")
    def _check_schema_version(self) -> Experience:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version {self.schema_version} "
                f"(this build understands {SCHEMA_VERSION})"
            )
        return self

    @classmethod
    def new(
        cls,
        *,
        title: str,
        type: ExperienceType | str,
        period: Period | dict[str, Any],
        **extra: Any,
    ) -> Experience:
        """Create a fresh record with generated id, source and timestamps."""
        now = utcnow()
        data: dict[str, Any] = {
            "id": f"exp_{new_ulid()}",
            "title": title,
            "type": type,
            "period": period,
            "source": Source(),
            "created_at": now,
            "updated_at": now,
        }
        data.update(extra)
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe dict (datetimes as ISO 8601 strings)."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Experience:
        return cls.model_validate(data)
