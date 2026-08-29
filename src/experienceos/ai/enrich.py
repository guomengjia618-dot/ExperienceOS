"""Enrich pipeline (#012): AI proposals for one existing record.

The model returns a proposal list; this module is the *server-side
gatekeeper*: proposals targeting anything outside
{contribution, challenge, solution, result, technology} are dropped
outright — title, period, evidence and factual numbers can never be
touched through enrich, no matter what the model says. Accepted
proposals mutate the record in memory; the CLI's confirmation loop and
``ExperienceStore.save`` (which bumps ``updated_at``) do the rest.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from experienceos.ai.prompts import ENRICH_PROMPT_V1
from experienceos.ai.provider import Message
from experienceos.core.models import Experience

ALLOWED_FIELDS = ("contribution", "challenge", "solution", "result", "technology")
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


@dataclass(frozen=True)
class EnrichProposal:
    """One in-scope, normalized proposal ready for confirmation."""

    field: str
    current: str
    suggested_items: tuple[str, ...]
    reason: str

    @property
    def suggested_display(self) -> str:
        return " | ".join(self.suggested_items)


def build_enrich_messages(experience: Experience) -> list[Message]:
    """System enrich prompt + the record JSON as material."""
    material = json.dumps(experience.to_dict(), ensure_ascii=False, indent=2)
    return [
        Message(role="system", content=ENRICH_PROMPT_V1),
        Message(
            role="user",
            content=f"Record:\n\n{material}\n\nOutput ONLY the JSON array.",
        ),
    ]


def parse_proposals(raw: str) -> list[dict[str, Any]]:
    """Parse the model reply into a list of proposal dicts."""
    text = raw.strip()
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end > start:
            text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"enrich output is not valid JSON: {exc}") from exc
    if isinstance(data, dict):
        if "proposals" not in data:
            raise ValueError("enrich output is not a JSON array")
        data = data["proposals"]
    if not isinstance(data, list):
        raise ValueError("enrich output is not a JSON array")
    return [item for item in data if isinstance(item, dict)]


def normalize_proposals(
    data: list[dict[str, Any]],
) -> tuple[list[EnrichProposal], list[str]]:
    """Split raw proposals into (in-scope, rejected descriptions).

    A proposal is rejected when its field is outside the whitelist or
    its payload is malformed — the record itself is the source of truth,
    so anything questionable is dropped, never guessed.
    """
    accepted: list[EnrichProposal] = []
    rejected: list[str] = []
    for item in data:
        field = item.get("field")
        if field not in ALLOWED_FIELDS:
            rejected.append(
                f"out-of-scope field {field!r} (allowed: {', '.join(ALLOWED_FIELDS)})"
            )
            continue
        suggested = item.get("suggested")
        if isinstance(suggested, str):
            suggested_items = (suggested.strip(),) if suggested.strip() else ()
        elif isinstance(suggested, list):
            suggested_items = tuple(
                name.strip() for name in suggested if isinstance(name, str) and name.strip()
            )
        else:
            suggested_items = ()
        if not suggested_items:
            rejected.append("malformed proposal (suggested missing or empty)")
            continue
        current = item.get("current")
        has_current = isinstance(current, str) and bool(current.strip())
        if field != "technology" and not has_current:
            # STAR rewrites replace an existing item, so the model must
            # name it; technology replaces the whole list instead
            rejected.append("malformed proposal (current missing)")
            continue
        accepted.append(
            EnrichProposal(
                field=field,
                current=current.strip() if has_current else "",
                suggested_items=suggested_items,
                reason=str(item.get("reason", "")).strip(),
            )
        )
    return accepted, rejected


def apply_proposal(experience: Experience, proposal: EnrichProposal) -> None:
    """Mutate *experience* in place; pydantic validates the assignment."""
    if proposal.field == "technology":
        experience.technology = list(proposal.suggested_items)
        return
    items = list(getattr(experience, proposal.field))
    for index, item in enumerate(items):
        if item.casefold() == proposal.current.casefold():
            items[index] = proposal.suggested_items[0]
            break
    else:
        # the model paraphrased the current item; append instead of guessing
        items.append(proposal.suggested_items[0])
    setattr(experience, proposal.field, items)
