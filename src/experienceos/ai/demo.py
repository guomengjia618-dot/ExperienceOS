# ruff: noqa: RUF001
"""Recorded model turns for the offline demo.

The model responses are deterministic, but all three tool calls, argument
validation, store reads, checkpoints, grounding checks, and structured-output
validation run through the same production path as a live model.
"""

from __future__ import annotations

from experienceos.ai.provider import ModelResponse, RecordedProvider, ToolCall
from experienceos.ai.schemas import BriefCitation, EvidenceBrief
from experienceos.core.errors import WorkflowError
from experienceos.storage import ExperienceStore


def build_recorded_demo_provider(store: ExperienceStore) -> RecordedProvider:
    experiences = store.list_all()
    if not experiences:
        raise WorkflowError("离线演示至少需要一条经历，请先新增或导入经历")
    experience = experiences[0]
    locations = [evidence.location for evidence in experience.evidence]
    gap = (
        []
        if locations
        else [f"{experience.title} 尚未关联证据，请补充仓库、提交、PR 或文档。"]
    )
    output = EvidenceBrief(
        answer=f"本地经历库中最近录入的项目是“{experience.title}”。",
        highlights=[
            experience.description or f"已记录项目“{experience.title}”。",
            *experience.result[:2],
        ],
        citations=[
            BriefCitation(
                experience_id=experience.id,
                claim=f"本地经历库包含项目“{experience.title}”。",
                evidence_locations=locations,
            )
        ],
        evidence_gaps=gap,
        next_actions=["核对引用记录，并为尚无证据支撑的成果补充材料。"],
    )
    return RecordedProvider(
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
