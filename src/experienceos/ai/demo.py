"""Recorded model turns for the offline demo.

The model responses are deterministic, but all three tool calls, argument
validation, store reads, checkpoints, grounding checks, and structured-output
validation run through the same production path as a live model.
"""

from __future__ import annotations

from experienceos.ai.provider import MockProvider, ModelResponse, ToolCall
from experienceos.ai.schemas import BriefCitation, EvidenceBrief
from experienceos.core.errors import WorkflowError
from experienceos.storage import ExperienceStore


def build_recorded_demo_provider(store: ExperienceStore) -> MockProvider:
    experiences = store.list_all()
    if not experiences:
        raise WorkflowError(
            "the recorded demo needs at least one experience; add or import a record first"
        )
    experience = experiences[0]
    locations = [evidence.location for evidence in experience.evidence]
    gap = (
        []
        if locations
        else [f"{experience.title} has no linked evidence; add a repo, commit, PR, or document."]
    )
    output = EvidenceBrief(
        answer=f"{experience.title} is the newest experience in the local archive.",
        highlights=[
            experience.description or f"{experience.title} is recorded as {experience.type.value}.",
            *experience.result[:2],
        ],
        citations=[
            BriefCitation(
                experience_id=experience.id,
                claim=f"The archive contains the experience {experience.title}.",
                evidence_locations=locations,
            )
        ],
        evidence_gaps=gap,
        next_actions=[
            "Review the cited record and attach evidence for any unsupported result.",
        ],
    )
    return MockProvider(
        responses=[
            ModelResponse(
                tool_calls=(
                    ToolCall("demo_search", "search_experiences", {"query": "", "limit": 5}),
                    ToolCall(
                        "demo_get",
                        "get_experience",
                        {"id_or_prefix": experience.id},
                    ),
                    ToolCall("demo_stats", "get_evidence_stats", {}),
                )
            ),
            ModelResponse(content=output.model_dump_json()),
        ],
        name="recorded-demo",
    )
