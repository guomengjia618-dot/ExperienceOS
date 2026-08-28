"""Reproducible, human-labelled evaluation for the evidence brief workflow."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from experienceos.ai.provider import LLMProvider, MockProvider, ModelResponse, ToolCall
from experienceos.ai.tools import ExperienceToolRegistry
from experienceos.ai.workflow import (
    EvidenceBriefWorkflow,
    WorkflowCheckpointStore,
    WorkflowState,
)
from experienceos.core.errors import AIProviderError
from experienceos.core.models import Experience
from experienceos.storage import ExperienceStore


class RecordedToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    arguments: dict[str, Any]


class RecordedTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: dict[str, Any] | None = None
    tool_calls: list[RecordedToolCall] = Field(default_factory=list)
    error: str | None = None


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    question: str
    experiences: list[dict[str, Any]]
    expected_tool_sequence: list[str]
    expected_terms: list[str]
    expected_status: Literal["completed", "paused"] = "completed"
    expected_error_contains: str | None = None
    resume_after_error: bool = False
    label_source: Literal[
        "ai-assisted-synthetic",
        "human-labelled-sanitized-real",
    ]
    expected_behavior_notes: str
    recorded_turns: list[RecordedTurn]


class EvalCaseReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    passed: bool
    expected_status: Literal["completed", "paused"]
    observed_status: Literal["running", "paused", "completed"]
    structured_output: bool
    tool_sequence_correct: bool
    citations_grounded: bool
    expected_terms_present: bool
    recovery_passed: bool | None
    called_tools: list[str]
    latency_ms: float | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    retry_count: int
    estimated_cost_usd: float | None
    error: str | None


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_version: int = 2
    generated_at: datetime
    dataset: str
    live: bool
    interpretation: str
    passed: int
    total: int
    expectation_pass_rate: float
    tool_sequence_pass_rate: float
    schema_pass_rate: float
    grounded_citation_pass_rate: float
    task_completion_rate: float
    recovery_pass_rate: float | None
    latency_ms: float | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    retry_count: int
    estimated_cost_usd: float | None
    cases: list[EvalCaseReport]


def load_eval_cases(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            case = EvalCase.model_validate_json(line)
            if case.id in seen_ids:
                raise ValueError(f"duplicate eval case id: {case.id}")
            seen_ids.add(case.id)
            cases.append(case)
        except Exception as exc:
            raise ValueError(f"invalid eval case at {path}:{line_number}: {exc}") from exc
    if not cases:
        raise ValueError(f"evaluation dataset is empty: {path}")
    return cases


def save_evaluation_report(report: EvaluationReport, path: Path) -> Path:
    shareable = report.model_copy(deep=True)
    shareable.dataset = Path(shareable.dataset).name
    for case in shareable.cases:
        case.error = _redacted_error(case.error)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(shareable.model_dump_json(indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def _redacted_error(error: str | None) -> str | None:
    if error is None:
        return None
    normalized = error.casefold()
    categories = (
        ("unknown evidence locations", "grounding_error"),
        ("invalid arguments", "tool_argument_error"),
        ("schema validation", "schema_validation_error"),
        ("rate_limit", "rate_limit_error"),
        ("http 429", "rate_limit_error"),
        ("http 5", "server_error"),
        ("timed out", "timeout_error"),
        ("network", "network_error"),
    )
    for marker, category in categories:
        if marker in normalized:
            return f"<redacted:{category}>"
    return "<redacted:execution_error>"


def _recorded_provider(case: EvalCase) -> MockProvider:
    responses: list[ModelResponse | Exception] = []
    for turn in case.recorded_turns:
        if turn.error is not None:
            responses.append(AIProviderError(turn.error))
            continue
        responses.append(
            ModelResponse(
                content=(
                    json.dumps(turn.content, ensure_ascii=False)
                    if turn.content is not None
                    else None
                ),
                tool_calls=tuple(
                    ToolCall(call.id, call.name, call.arguments) for call in turn.tool_calls
                ),
            )
        )
    return MockProvider(responses=responses, name=f"eval-recording:{case.id}")


def run_evaluation(
    dataset_path: Path,
    work_directory: Path,
    *,
    live_provider: LLMProvider | None = None,
) -> EvaluationReport:
    """Run expectation-labelled recordings, or use a live provider on the same cases."""
    cases = load_eval_cases(dataset_path)
    reports = [
        _run_case(case, Path(work_directory) / case.id, live_provider)
        for case in cases
    ]
    passed_count = sum(report.passed for report in reports)
    completed_expected = [
        report for report in reports if report.expected_status == "completed"
    ]
    recovery_cases = [
        report for report in reports if report.recovery_passed is not None
    ]
    return EvaluationReport(
        generated_at=datetime.now(timezone.utc),
        dataset=str(dataset_path),
        live=live_provider is not None,
        interpretation=(
            "Live model performance on a small AI-assisted synthetic set."
            if live_provider is not None
            else "Deterministic regression replay; this is not model accuracy."
        ),
        passed=passed_count,
        total=len(reports),
        expectation_pass_rate=passed_count / len(reports),
        tool_sequence_pass_rate=_rate(reports, "tool_sequence_correct"),
        schema_pass_rate=_rate(completed_expected, "structured_output"),
        grounded_citation_pass_rate=_rate(completed_expected, "citations_grounded"),
        task_completion_rate=(
            sum(report.observed_status == "completed" for report in completed_expected)
            / len(completed_expected)
            if completed_expected
            else 0.0
        ),
        recovery_pass_rate=(
            _rate(recovery_cases, "recovery_passed") if recovery_cases else None
        ),
        latency_ms=_sum_optional(reports, "latency_ms"),
        input_tokens=_sum_optional_int(reports, "input_tokens"),
        output_tokens=_sum_optional_int(reports, "output_tokens"),
        total_tokens=_sum_optional_int(reports, "total_tokens"),
        retry_count=sum(report.retry_count for report in reports),
        estimated_cost_usd=_sum_optional(reports, "estimated_cost_usd"),
        cases=reports,
    )


def _run_case(
    case: EvalCase,
    case_home: Path,
    live_provider: LLMProvider | None,
) -> EvalCaseReport:
    case_home.joinpath("experiences").mkdir(parents=True, exist_ok=True)
    store = ExperienceStore(case_home)
    evidence_by_id: dict[str, set[str]] = {}
    for record in case.experiences:
        experience = Experience.new(**record)
        store.save(experience)
        evidence_by_id[experience.id] = {
            evidence.location for evidence in experience.evidence
        }

    provider = live_provider or _recorded_provider(case)
    checkpoints = WorkflowCheckpointStore(case_home)
    workflow = EvidenceBriefWorkflow(
        provider=provider,
        tools=ExperienceToolRegistry(store),
        checkpoints=checkpoints,
    )
    state: WorkflowState | None = None
    first_error: str | None = None
    final_error: str | None = None
    recovery_passed: bool | None = None
    try:
        state = workflow.start(case.question)
    except Exception as exc:
        first_error = str(exc)
        state = _load_latest_state(checkpoints)
        if case.resume_after_error and state is not None:
            try:
                state = workflow.resume(state.workflow_id)
                recovery_passed = state.status == "completed"
            except Exception as resume_exc:
                final_error = str(resume_exc)
                state = _load_latest_state(checkpoints)
                recovery_passed = False
        else:
            final_error = first_error

    if state is None:
        raise RuntimeError(f"evaluation case {case.id} produced no checkpoint")
    called_tools = _requested_tools(state)
    structured = state.output is not None and state.status == "completed"
    grounded = _citations_grounded(state, evidence_by_id)
    output_text = state.output.model_dump_json().casefold() if state.output else ""
    terms_present = all(term.casefold() in output_text for term in case.expected_terms)
    tool_sequence_correct = called_tools == case.expected_tool_sequence
    status_matches = state.status == case.expected_status
    observed_error = final_error or first_error
    error_matches = (
        case.expected_error_contains is None
        or (
            observed_error is not None
            and case.expected_error_contains.casefold() in observed_error.casefold()
        )
    )
    if case.expected_status == "completed":
        passed = (
            status_matches
            and structured
            and grounded
            and terms_present
            and tool_sequence_correct
            and final_error is None
            and (recovery_passed is not False)
        )
    else:
        passed = status_matches and tool_sequence_correct and error_matches

    calls = state.model_calls
    return EvalCaseReport(
        id=case.id,
        passed=passed,
        expected_status=case.expected_status,
        observed_status=state.status,
        structured_output=structured,
        tool_sequence_correct=tool_sequence_correct,
        citations_grounded=grounded,
        expected_terms_present=terms_present,
        recovery_passed=recovery_passed,
        called_tools=called_tools,
        latency_ms=_sum_call_values(calls, "latency_ms"),
        input_tokens=_sum_call_ints(calls, "input_tokens"),
        output_tokens=_sum_call_ints(calls, "output_tokens"),
        total_tokens=_sum_call_ints(calls, "total_tokens"),
        retry_count=sum(int(call.get("retry_count") or 0) for call in calls),
        estimated_cost_usd=_sum_call_values(calls, "estimated_cost_usd"),
        error=observed_error,
    )


def _load_latest_state(checkpoints: WorkflowCheckpointStore) -> WorkflowState | None:
    paths = sorted(checkpoints.directory.glob("wf_*.json"))
    return checkpoints.load(paths[-1].stem) if paths else None


def _requested_tools(state: WorkflowState) -> list[str]:
    names: list[str] = []
    for message in state.messages:
        if message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls", ()):
            function = call.get("function", {}) if isinstance(call, dict) else {}
            if function.get("name") is not None:
                names.append(str(function["name"]))
    return names


def _citations_grounded(
    state: WorkflowState,
    evidence_by_id: dict[str, set[str]],
) -> bool:
    if state.output is None:
        return state.status == "paused"
    return all(
        citation.experience_id in evidence_by_id
        and set(citation.evidence_locations) <= evidence_by_id[citation.experience_id]
        for citation in state.output.citations
    )


def _rate(reports: list[EvalCaseReport], field: str) -> float:
    if not reports:
        return 0.0
    return sum(bool(getattr(report, field)) for report in reports) / len(reports)


def _sum_optional(reports: list[EvalCaseReport], field: str) -> float | None:
    values = [float(value) for report in reports if (value := getattr(report, field)) is not None]
    return sum(values) if values else None


def _sum_optional_int(reports: list[EvalCaseReport], field: str) -> int | None:
    values = [int(value) for report in reports if (value := getattr(report, field)) is not None]
    return sum(values) if values else None


def _sum_call_values(calls: list[dict[str, Any]], field: str) -> float | None:
    values = [float(call[field]) for call in calls if call.get(field) is not None]
    return sum(values) if values else None


def _sum_call_ints(calls: list[dict[str, Any]], field: str) -> int | None:
    values = [int(call[field]) for call in calls if call.get(field) is not None]
    return sum(values) if values else None
