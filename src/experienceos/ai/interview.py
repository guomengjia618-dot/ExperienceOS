"""Interview-to-draft pipeline (#011): conversation in, proposal out.

The AI layer owns the mechanics — evidence harvesting from free text,
the extraction call, tolerant JSON parsing, and draft assembly. The CLI
owns every console interaction. Two invariants:

- The transcript stays in memory during the conversation; it only ever
  reaches the configured provider and, when extraction fails twice, the
  local ``<home>/drafts/`` folder as a recovery aid. Nothing is uploaded
  anywhere else.
- The produced draft is a *proposal*: ``status=draft``,
  ``source.origin=interview``, ``source.created_by="ai:<model>"``. It
  never lands in the store without field-by-field user confirmation.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from experienceos.ai.prompts import (
    EXTRACTION_PROMPT_V1,
    INTAKE_INTERVIEW_PROMPT_V1,
)
from experienceos.ai.provider import Message
from experienceos.connectors.base import ExperienceDraft
from experienceos.core.models import (
    EvidenceKind,
    ExperienceType,
    is_valid_year_month,
)

UNDATED_START = "1970-01"
MAX_EVIDENCE = 10

_URL_RE = re.compile(r"https?://[^\s)\]}<>\"']+", re.IGNORECASE)
_GITHUB_PATH_RE = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/"
    r"([A-Za-z][A-Za-z0-9_.-]*)/([A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)
_SHA_RE = re.compile(r"(?<![0-9a-zA-Z])(?=[0-9a-f]*\d)[0-9a-f]{7,40}(?![0-9a-zA-Z])")
_SLUG_RE = re.compile(
    r"(?<![\w.@:/-])([A-Za-z][A-Za-z0-9_.-]*)/([A-Za-z0-9_.-]+)(?![\w/-])"
)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_TYPE_VALUES = {t.value for t in ExperienceType}


def collect_evidence_candidates(text: str) -> list[dict[str, str]]:
    """Harvest URLs, commit SHAs and repo slugs from *text*.

    Ordered by first appearance, deduplicated by location, capped at
    :data:`MAX_EVIDENCE`. URL spans are excluded from the slug/SHA
    scans so commit paths inside links do not double-report.
    """
    found: list[dict[str, str]] = []

    def add(kind: str, location: str) -> None:
        if not location or len(found) >= MAX_EVIDENCE:
            return
        if any(item["location"] == location for item in found):
            return
        found.append({"kind": kind, "location": location, "description": ""})

    url_spans = [match.span() for match in _URL_RE.finditer(text)]
    for match in _URL_RE.finditer(text):
        add("url", _canonical_url(match.group(0)))
    for match in _GITHUB_PATH_RE.finditer(text):
        if any(start <= match.start() < end for start, end in url_spans):
            continue  # already added by the URL scan
        add("url", f"https://github.com/{match.group(1)}/{match.group(2)}")
    for match in _SHA_RE.finditer(text):
        if any(start <= match.start() < end for start, end in url_spans):
            continue
        add("commit", match.group(0))
    for match in _SLUG_RE.finditer(text):
        if any(start <= match.start() < end for start, end in url_spans):
            continue
        add("repo", match.group(0))
    return found


def _canonical_url(url: str) -> str:
    """Normalize github links so bare and http variants deduplicate."""
    cleaned = url.strip().rstrip(".,;")
    match = _GITHUB_PATH_RE.fullmatch(cleaned)
    if match:
        return f"https://github.com/{match.group(1)}/{match.group(2)}"
    return cleaned


def interview_system_prompt(language: str) -> str:
    """Rendered intake-interview system prompt (#011)."""
    return INTAKE_INTERVIEW_PROMPT_V1.format(language=language)


def build_extraction_messages(
    transcript: list[tuple[str, str]], model: str
) -> list[Message]:
    """System extraction prompt + the full transcript as the material."""
    lines = [f"{role}: {text}" for role, text in transcript]
    material = "\n".join(lines) or "(empty conversation)"
    return [
        Message(role="system", content=EXTRACTION_PROMPT_V1),
        Message(
            role="user",
            content=(
                f"Material (conversation transcript):\n\n{material}\n\n"
                f'Model name for source.created_by: "ai:{model}".\n'
                "Output ONLY the JSON object."
            ),
        ),
    ]


def parse_extraction_json(raw: str) -> dict[str, Any]:
    """Parse the model reply into a dict; tolerant of fences and prose."""
    text = raw.strip()
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"extraction output is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("extraction output is not a JSON object")
    return data


def draft_from_extraction(
    data: dict[str, Any],
    model: str,
    candidates: list[dict[str, str]] | None = None,
) -> ExperienceDraft:
    """Whitelist-map extraction JSON into a validated interview draft.

    Unknown keys are dropped (never guessed); invalid enum values fall
    back to safe defaults; an absent or malformed period keeps an
    explicit ``1970-01`` placeholder the user edits during confirmation.
    """
    fields: dict[str, Any] = {
        "title": _scalar(data.get("title")) or "Untitled experience",
        "type": data.get("type") if data.get("type") in _TYPE_VALUES else "other",
    }
    period = data.get("period") if isinstance(data.get("period"), dict) else {}
    start = _scalar(period.get("start"))
    end = _scalar(period.get("end"))
    fields["period"] = {
        "start": start if start and is_valid_year_month(start) else UNDATED_START,
        "end": end if end and is_valid_year_month(end) else None,
    }
    for scalar in ("context", "role", "description", "reflection"):
        value = _scalar(data.get(scalar))
        if value:
            fields[scalar] = value
    for list_field in ("technology", "contribution", "challenge", "solution", "result"):
        items = _string_list(data.get(list_field))
        if items:
            fields[list_field] = items

    evidence = _clean_evidence(data.get("evidence"))
    seen = {item["location"] for item in evidence}
    for candidate in candidates or []:
        if candidate["location"] not in seen:
            evidence.append(candidate)
            seen.add(candidate["location"])
    if evidence:
        fields["evidence"] = evidence[:MAX_EVIDENCE]

    return ExperienceDraft.create(
        origin="interview",
        created_by=f"ai:{model}",
        **fields,
    )


def save_transcript(
    home: Path, transcript: list[tuple[str, str]], model: str
) -> Path:
    """Persist a failed interview to ``<home>/drafts/`` for later retry."""
    drafts_dir = Path(home) / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    _ensure_gitignore(drafts_dir.parent)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = drafts_dir / f"interview-{stamp}.md"
    body = "\n".join(f"**{role}**: {text}\n" for role, text in transcript)
    path.write_text(
        f"# Interview transcript (extraction failed, kept for retry)\n\n"
        f"Model: ai:{model}\n\n{body}\n",
        encoding="utf-8",
    )
    return path


# -- helpers -----------------------------------------------------------------


def _scalar(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _clean_evidence(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    cleaned: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        location = _scalar(item.get("location"))
        if not location:
            continue
        kind = item.get("kind")
        cleaned.append(
            {
                "kind": kind if kind in {k.value for k in EvidenceKind} else "other",
                "location": location,
                "description": _scalar(item.get("description")) or "",
            }
        )
    return cleaned


def _ensure_gitignore(home: Path) -> None:
    """Suggest keeping drafts out of version control when home is a repo."""
    if not (home / ".git").exists():
        return
    gitignore = home / ".gitignore"
    try:
        existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
        if "drafts/" not in existing.splitlines():
            gitignore.write_text(
                existing.rstrip("\n") + "\ndrafts/\n", encoding="utf-8"
            )
    except OSError:  # pragma: no cover - best-effort suggestion only
        pass


__all__ = [
    "MAX_EVIDENCE",
    "UNDATED_START",
    "build_extraction_messages",
    "collect_evidence_candidates",
    "draft_from_extraction",
    "interview_system_prompt",
    "parse_extraction_json",
    "save_transcript",
]
