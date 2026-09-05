"""Material-to-draft extraction pipeline: raw text in, one proposal out.

Shared by the interview conversation and by any connector input that
needs AI reading (PDF resumes today). This module owns the whole
no-fabrication plumbing so the rules exist in exactly one place:

- the versioned :data:`EXTRACTION_PROMPT_V1` (never invent facts),
- evidence harvesting from free text (:func:`collect_evidence_candidates`),
- tolerant JSON parsing (:func:`parse_extraction_json`),
- whitelist field mapping (:func:`draft_from_extraction`),
- the single JSON retry (:class:`AIExtraction`).

``AIExtraction`` implements the connectors-tier
``MaterialDraftExtractor`` protocol, so it can be injected into
connectors; this module never imports the connectors tier. The produced
draft is a *proposal*: ``status=draft`` and
``source.created_by="ai:<model>"`` — it never reaches the store without
field-by-field user confirmation.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from experienceos.ai.prompts import EXTRACTION_PROMPT_V1
from experienceos.ai.provider import Message
from experienceos.core.draft import ExperienceDraft
from experienceos.core.models import (
    UNDATED_START,
    EvidenceKind,
    ExperienceType,
    is_valid_year_month,
)

MAX_EVIDENCE = 10
_JSON_RETRIES = 1  # one retry after the first invalid-JSON reply

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


def build_extraction_messages(
    transcript: Sequence[tuple[str, str]],
    model: str,
    material_label: str = "Material (conversation transcript)",
) -> list[Message]:
    """System extraction prompt + the material as the user message."""
    lines = [f"{role}: {text}" for role, text in transcript]
    material = "\n".join(lines) or "(empty)"
    return [
        Message(role="system", content=EXTRACTION_PROMPT_V1),
        Message(
            role="user",
            content=(
                f"{material_label}:\n\n{material}\n\n"
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
    origin: str = "interview",
    ref: str | None = None,
) -> ExperienceDraft:
    """Whitelist-map extraction JSON into a validated draft.

    Unknown keys are dropped (never guessed); invalid enum values fall
    back to safe defaults; an absent or malformed period keeps an
    explicit undated placeholder (:data:`UNDATED_START`) the user edits
    during confirmation. ``origin``/``ref`` set the provenance
    (interview conversation by default, ``resume`` for the PDF pipeline).
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
        origin=origin,
        ref=ref,
        created_by=f"ai:{model}",
        **fields,
    )


class AIExtraction:
    """Material-to-draft extraction backed by an LLM provider.

    The JSON retry lives here and nowhere else: every caller gets a
    draft or a :class:`ValueError`, never a half-parsed reply.
    """

    def __init__(self, provider: Any, model: str) -> None:
        self._provider = provider
        self._model = model

    def extract_draft(
        self,
        materials: Sequence[tuple[str, str]],
        *,
        origin: str = "interview",
        ref: str | None = None,
        candidates: list[dict[str, str]] | None = None,
        material_label: str = "Material (conversation transcript)",
    ) -> ExperienceDraft:
        messages = build_extraction_messages(
            list(materials), self._model, material_label=material_label
        )
        data: dict[str, Any] | None = None
        last_error: Exception | None = None
        for attempt in range(1 + _JSON_RETRIES):
            raw = self._provider.complete(messages)
            try:
                data = parse_extraction_json(raw)
                break
            except ValueError as exc:
                last_error = exc
                if attempt == _JSON_RETRIES:
                    break
                messages.append(Message(role="assistant", content=raw))
                messages.append(
                    Message(
                        role="user",
                        content="That was not valid JSON. Output ONLY the JSON object.",
                    )
                )
        if data is None:
            raise ValueError(
                f"AI extraction failed twice: {last_error}"
            ) from last_error
        return draft_from_extraction(
            data, self._model, candidates=candidates, origin=origin, ref=ref
        )


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


__all__ = [
    "MAX_EVIDENCE",
    "UNDATED_START",
    "AIExtraction",
    "build_extraction_messages",
    "collect_evidence_candidates",
    "draft_from_extraction",
    "parse_extraction_json",
]
