"""Sanitized workflow reports containing operational metadata, not user content."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from experienceos.ai.workflow import WorkflowState


class SanitizedRunReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_version: int = 1
    workflow_id: str
    status: Literal["running", "paused", "completed"]
    provider: str | None
    model: str
    created_at: datetime
    updated_at: datetime
    model_call_count: int
    tool_call_count: int
    tool_names: list[str]
    latency_ms: float | None
    retry_count: int
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    estimated_cost_usd: float | None
    request_ids: list[str]
    output_schema_valid: bool
    citation_count: int
    evidence_gap_count: int


def build_run_report(state: WorkflowState) -> SanitizedRunReport:
    """Aggregate only non-content fields safe to share after a live run."""
    calls = state.model_calls
    output = state.output
    return SanitizedRunReport(
        workflow_id=state.workflow_id,
        status=state.status,
        provider=_last_string(calls, "provider"),
        model=state.model,
        created_at=state.created_at,
        updated_at=state.updated_at,
        model_call_count=len(calls),
        tool_call_count=len(state.tool_events),
        tool_names=[event.name for event in state.tool_events],
        latency_ms=_sum_optional(calls, "latency_ms"),
        retry_count=sum(int(call.get("retry_count") or 0) for call in calls),
        input_tokens=_sum_optional_int(calls, "input_tokens"),
        output_tokens=_sum_optional_int(calls, "output_tokens"),
        total_tokens=_sum_optional_int(calls, "total_tokens"),
        estimated_cost_usd=_sum_optional(calls, "estimated_cost_usd"),
        request_ids=[
            str(call["request_id"])
            for call in calls
            if call.get("request_id") is not None
        ],
        output_schema_valid=state.status == "completed" and output is not None,
        citation_count=len(output.citations) if output is not None else 0,
        evidence_gap_count=len(output.evidence_gaps) if output is not None else 0,
    )


def save_run_report(state: WorkflowState, path: Path) -> Path:
    report = build_run_report(state)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def _last_string(calls: list[dict[str, Any]], key: str) -> str | None:
    for call in reversed(calls):
        if call.get(key) is not None:
            return str(call[key])
    return None


def _sum_optional(calls: list[dict[str, Any]], key: str) -> float | None:
    values = [float(call[key]) for call in calls if call.get(key) is not None]
    return sum(values) if values else None


def _sum_optional_int(calls: list[dict[str, Any]], key: str) -> int | None:
    values = [int(call[key]) for call in calls if call.get(key) is not None]
    return sum(values) if values else None
