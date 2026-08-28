"""Agent tools, structured output, checkpoint, recovery, and eval tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from experienceos.ai.evaluation import run_evaluation, save_evaluation_report
from experienceos.ai.provider import MockProvider, ModelResponse, ToolCall
from experienceos.ai.reporting import save_run_report
from experienceos.ai.schemas import BriefCitation, EvidenceBrief
from experienceos.ai.tools import ExperienceToolRegistry
from experienceos.ai.workflow import EvidenceBriefWorkflow, WorkflowCheckpointStore
from experienceos.core.errors import AIProviderError, ToolExecutionError, WorkflowError


def final_brief(exp: Any, *, locations: list[str] | None = None) -> ModelResponse:
    output = EvidenceBrief(
        answer=f"{exp.title} is grounded in the local archive.",
        highlights=[*exp.result],
        citations=[
            BriefCitation(
                experience_id=exp.id,
                claim=f"The archive contains {exp.title}.",
                evidence_locations=(
                    locations
                    if locations is not None
                    else [evidence.location for evidence in exp.evidence]
                ),
            )
        ],
        evidence_gaps=[],
        next_actions=["Review the source artifact."],
    )
    return ModelResponse(content=output.model_dump_json())


def test_three_real_tools_read_the_store(store, make_experience) -> None:
    exp = make_experience(
        title="Search Project",
        description="BM25 retrieval",
        evidence=[{"kind": "repo", "location": "github.com/example/search"}],
    )
    store.save(exp)
    tools = ExperienceToolRegistry(store)

    found = json.loads(
        tools.execute("search_experiences", {"query": "BM25", "limit": 5})
    )
    loaded = json.loads(tools.execute("get_experience", {"id_or_prefix": exp.id[:12]}))
    stats = json.loads(tools.execute("get_evidence_stats", {}))

    assert tools.names == (
        "search_experiences",
        "get_experience",
        "get_evidence_stats",
    )
    assert found[0]["id"] == exp.id
    assert loaded["title"] == "Search Project"
    assert stats["coverage"] == 1.0


def test_tool_arguments_are_strict(store) -> None:
    tools = ExperienceToolRegistry(store)
    with pytest.raises(ToolExecutionError):
        tools.execute(
            "search_experiences",
            {"query": "", "limit": 5, "unexpected": True},
        )
    with pytest.raises(ToolExecutionError):
        tools.execute("unknown", {})


def test_workflow_calls_tools_and_validates_structured_output(
    home, store, make_experience
) -> None:
    exp = make_experience(
        title="Search Project",
        result=["Reached 92% hit rate."],
        evidence=[{"kind": "repo", "location": "github.com/example/search"}],
    )
    store.save(exp)
    provider = MockProvider(
        [
            ModelResponse(
                tool_calls=(
                    ToolCall("search", "search_experiences", {"query": "Search", "limit": 5}),
                    ToolCall("get", "get_experience", {"id_or_prefix": exp.id}),
                    ToolCall("stats", "get_evidence_stats", {}),
                )
            ),
            final_brief(exp),
        ]
    )
    checkpoints = WorkflowCheckpointStore(home)
    workflow = EvidenceBriefWorkflow(
        provider=provider,
        tools=ExperienceToolRegistry(store),
        checkpoints=checkpoints,
    )

    state = workflow.start("Summarize my search project")

    assert state.status == "completed"
    assert state.output is not None
    assert [event.name for event in state.tool_events] == list(
        ExperienceToolRegistry(store).names
    )
    assert checkpoints.path_of(state.workflow_id).is_file()
    assert provider.calls[-1]["schema_name"] == "evidence_brief"
    assert len(provider.calls[-1]["tools"]) == 3


def test_workflow_resumes_after_provider_failure(home, store, make_experience) -> None:
    exp = make_experience(
        title="Recoverable Project",
        evidence=[{"kind": "repo", "location": "github.com/example/recover"}],
    )
    store.save(exp)
    first_provider = MockProvider(
        [
            ModelResponse(
                tool_calls=(
                    ToolCall("get-once", "get_experience", {"id_or_prefix": exp.id}),
                )
            ),
            AIProviderError("temporary network failure"),
        ]
    )
    checkpoints = WorkflowCheckpointStore(home)
    first = EvidenceBriefWorkflow(
        provider=first_provider,
        tools=ExperienceToolRegistry(store),
        checkpoints=checkpoints,
    )

    with pytest.raises(WorkflowError, match="Resume with --resume"):
        first.start("Summarize the recoverable project")

    checkpoint_path = next((Path(home) / "workflows").glob("wf_*.json"))
    workflow_id = checkpoint_path.stem
    paused = checkpoints.load(workflow_id)
    assert paused.status == "paused"
    assert [event.name for event in paused.tool_events] == ["get_experience"]

    resumed = EvidenceBriefWorkflow(
        provider=MockProvider([final_brief(exp)]),
        tools=ExperienceToolRegistry(store),
        checkpoints=checkpoints,
    ).resume(workflow_id)
    assert resumed.status == "completed"
    assert len(resumed.tool_events) == 1


def test_duplicate_tool_call_id_executes_only_once(home, store, make_experience) -> None:
    exp = make_experience(title="Idempotent Project")
    store.save(exp)
    duplicate = ToolCall("same-call", "get_experience", {"id_or_prefix": exp.id})
    workflow = EvidenceBriefWorkflow(
        provider=MockProvider(
            [
                ModelResponse(tool_calls=(duplicate, duplicate)),
                final_brief(exp),
            ]
        ),
        tools=ExperienceToolRegistry(store),
        checkpoints=WorkflowCheckpointStore(home),
    )

    state = workflow.start("Summarize once")

    assert [event.call_id for event in state.tool_events] == ["same-call"]


def test_sanitized_report_excludes_question_and_tool_results(
    home, store, make_experience
) -> None:
    exp = make_experience(title="Private Question Project")
    store.save(exp)
    workflow = EvidenceBriefWorkflow(
        provider=MockProvider(
            [
                ModelResponse(
                    tool_calls=(
                        ToolCall("get", "get_experience", {"id_or_prefix": exp.id}),
                    )
                ),
                final_brief(exp),
            ]
        ),
        tools=ExperienceToolRegistry(store),
        checkpoints=WorkflowCheckpointStore(home),
    )
    state = workflow.start("This question must not appear in the report")

    path = save_run_report(state, Path(home) / "reports" / "run.json")
    report_text = path.read_text(encoding="utf-8")

    assert "This question" not in report_text
    assert exp.title not in report_text
    assert '"tool_call_count": 1' in report_text


def test_workflow_rejects_hallucinated_evidence_location(
    home, store, make_experience
) -> None:
    exp = make_experience(
        evidence=[{"kind": "repo", "location": "github.com/example/real"}],
    )
    store.save(exp)
    workflow = EvidenceBriefWorkflow(
        provider=MockProvider(
            [
                ModelResponse(
                    tool_calls=(
                        ToolCall("get", "get_experience", {"id_or_prefix": exp.id}),
                    )
                ),
                final_brief(exp, locations=["github.com/example/invented"]),
            ]
        ),
        tools=ExperienceToolRegistry(store),
        checkpoints=WorkflowCheckpointStore(home),
    )

    with pytest.raises(WorkflowError, match="unknown evidence locations"):
        workflow.start("Summarize this project")


def test_recorded_eval_dataset_passes(tmp_path) -> None:
    dataset = Path(__file__).resolve().parents[1] / "evals" / "experience_brief.jsonl"
    report = run_evaluation(dataset, tmp_path / "eval-work")
    assert report.total == 9
    assert report.passed == 9
    assert report.expectation_pass_rate == 1.0
    assert report.tool_sequence_pass_rate == 1.0
    assert report.schema_pass_rate == 1.0
    assert report.grounded_citation_pass_rate == 1.0
    assert report.recovery_pass_rate == 1.0
    assert "not model accuracy" in report.interpretation

    saved = save_evaluation_report(report, tmp_path / "eval-report.json")
    saved_text = saved.read_text(encoding="utf-8")
    assert str(tmp_path) not in saved_text
    assert "<redacted:tool_argument_error>" in saved_text
