"""Strict structured-output contracts for the AI layer."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class BriefCitation(BaseModel):
    """A claim in a brief linked back to one stored experience."""

    model_config = ConfigDict(extra="forbid")

    experience_id: str
    claim: str
    evidence_locations: list[str]


class EvidenceBrief(BaseModel):
    """Final, machine-checkable output of the evidence brief workflow."""

    model_config = ConfigDict(extra="forbid")

    answer: str
    highlights: list[str]
    citations: list[BriefCitation]
    evidence_gaps: list[str]
    next_actions: list[str]


class ProviderHealth(BaseModel):
    """Small structured response used by the live API connectivity check."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    message: str
