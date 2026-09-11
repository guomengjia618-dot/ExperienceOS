# ruff: noqa: RUF001
"""Explicitly synthetic demo data and deterministic model turns."""

from __future__ import annotations

import json
import time
from typing import Any

from experienceos.ai.provider import Message, ModelResponse, ToolCall
from experienceos.ai.schemas import BriefCitation, EvidenceBrief
from experienceos.core.errors import AIProviderError
from experienceos.core.models import Experience
from experienceos.storage import ExperienceStore

DEMO_QUESTION = "整理示例经历中的成果、证据与缺口"


def seed_demo(store: ExperienceStore) -> None:
    if store.list_all():
        return
    samples = [
        (
            "校园搜索引擎",
            "Python · BM25",
            "实现中文文档检索与排序。",
            "设计倒排索引与查询流水线",
            "在示例评测中完成 200 条查询测试。",
            "demo://campus-search/evaluation",
            "示例评测记录",
        ),
        (
            "开源任务队列",
            "Python · Redis",
            "为后台任务提供重试与状态追踪。",
            "实现任务重试与执行记录",
            "示例测试覆盖失败后的任务重试。",
            "demo://task-queue/tests",
            "示例测试记录",
        ),
        (
            "个人知识库",
            "TypeScript · SQLite",
            "整理文章、笔记和项目材料。",
            "实现标签与全文检索",
            "已完成检索原型，尚未记录效果评测。",
            "",
            "",
        ),
    ]
    for title, tech, description, contribution, result, location, evidence_name in samples:
        store.save(
            Experience.new(
                title=title,
                type="personal",
                period={"start": "2025-01", "end": "2025-06"},
                description=description,
                role="开发者",
                technology=tech.split(" · "),
                contribution=[contribution],
                result=[result],
                status="draft",
                evidence=(
                    [{"kind": "doc", "location": location, "description": evidence_name}]
                    if location
                    else []
                ),
                source={
                    "origin": "import",
                    "created_by": "ai:synthetic-demo",
                    "ref": "ExperienceOS workbench synthetic examples",
                },
            )
        )


class WorkbenchDemoProvider:
    """Replay fixed tool choices; construct the brief only from real tool results.

    Phase selection uses checkpoint messages, so a fresh provider can resume.
    The delay is presentation pacing, never reported as model latency.
    """

    name = "workbench-recorded"
    model = "synthetic-demo-v1"

    def __init__(self, *, fail_after_tools: bool = False, delay: float = 0.35):
        self.fail_after_tools = fail_after_tools
        self.delay = delay

    def generate(self, messages: list[Message], **kwargs: Any) -> ModelResponse:
        time.sleep(self.delay)
        results = {
            m.tool_call_id: json.loads(m.content or "null") for m in messages if m.role == "tool"
        }
        if "demo-search" not in results:
            return ModelResponse(
                tool_calls=(
                    ToolCall("demo-search", "search_experiences", {"query": "", "limit": 3}),
                )
            )
        if not any(key and key.startswith("demo-get-") for key in results):
            records = results["demo-search"]
            return ModelResponse(
                tool_calls=tuple(
                    ToolCall(
                        f"demo-get-{record['id']}", "get_experience", {"id_or_prefix": record["id"]}
                    )
                    for record in records
                )
            )
        if "demo-stats" not in results:
            return ModelResponse(tool_calls=(ToolCall("demo-stats", "get_evidence_stats", {}),))
        if self.fail_after_tools:
            raise AIProviderError("Intentional demo interruption after tools")
        records = [value for key, value in results.items() if key and key.startswith("demo-get-")]
        output = EvidenceBrief(
            answer=f"已读取 {len(records)} 条示例经历。以下整理来自本次工具读取的记录。",
            highlights=[f"{r['title']}：{result}" for r in records for result in r["result"]],
            citations=[
                BriefCitation(
                    experience_id=r["id"],
                    claim=f"{r['title']}：{r['description']}",
                    evidence_locations=[e["location"] for e in r["evidence"]],
                )
                for r in records
            ],
            evidence_gaps=[
                f"{r['title']}：尚未关联证据，不能据此确认成果。"
                for r in records
                if not r["evidence"]
            ],
            next_actions=["核对个人贡献与成果；为缺少证据的记录补充评测、提交或文档。"],
        )
        return ModelResponse(content=output.model_dump_json())

    def complete(self, messages: list[Message]) -> str:
        return self.generate(messages).content or ""
