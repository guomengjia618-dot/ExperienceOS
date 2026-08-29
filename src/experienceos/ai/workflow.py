"""Checkpointed evidence-brief workflow with a model/tool loop."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from experienceos.ai.provider import LLMProvider, Message, ToolCall
from experienceos.ai.schemas import EvidenceBrief
from experienceos.ai.tools import ExperienceToolRegistry
from experienceos.core.errors import AIProviderError, StorageError, WorkflowError
from experienceos.core.models import utcnow
from experienceos.core.ulid import new_ulid

_WORKFLOW_ID_RE = re.compile(r"^wf_[0-9A-HJKMNP-TV-Z]{26}$")

EVIDENCE_BRIEF_SYSTEM_PROMPT = """\
You are the evidence brief agent for ExperienceOS.

Use the provided read-only tools to inspect the local archive before answering.
Search to discover candidates, load a full record before making a detailed
claim about it, and use evidence statistics before judging evidence coverage.
Use only facts returned by tools. Never invent metrics, dates, technologies,
IDs, or evidence locations. A citation's evidence_locations must be copied
verbatim from its retrieved experience; use an empty list if none exists.
Return the final answer in the required JSON schema and in the user's language.
"""


class ToolEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str
    name: str
    arguments: dict[str, Any]
    result: str
    completed_at: datetime


class WorkflowState(BaseModel):
    """Durable state; no credentials or plaintext hidden reasoning are stored."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    workflow_id: str
    question: str
    status: Literal["running", "paused", "completed"]
    provider: str = "unknown"
    model: str
    messages: list[dict[str, Any]]
    tool_events: list[ToolEvent] = Field(default_factory=list)
    model_calls: list[dict[str, Any]] = Field(default_factory=list)
    output: EvidenceBrief | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class WorkflowCheckpointStore:
    """Atomic JSON checkpoints under <home>/workflows."""

    def __init__(self, root: Path) -> None:
        self.directory = Path(root) / "workflows"

    def path_of(self, workflow_id: str) -> Path:
        if not _WORKFLOW_ID_RE.match(workflow_id):
            raise WorkflowError(f"invalid workflow id: {workflow_id}")
        return self.directory / f"{workflow_id}.json"

    def save(self, state: WorkflowState) -> Path:
        state.updated_at = utcnow()
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.path_of(state.workflow_id)
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(state.model_dump_json(indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, target)
        return target

    def load(self, workflow_id: str) -> WorkflowState:
        path = self.path_of(workflow_id)
        if not path.exists():
            raise WorkflowError(f"workflow checkpoint not found: {workflow_id}")
        try:
            return WorkflowState.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, PydanticValidationError) as exc:
            raise StorageError(f"cannot load workflow checkpoint {path.name}: {exc}") from exc


class EvidenceBriefWorkflow:
    """Run or resume a bounded, checkpointed model/tool conversation."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        tools: ExperienceToolRegistry,
        checkpoints: WorkflowCheckpointStore,
        max_model_rounds: int = 8,
    ) -> None:
        self.provider = provider
        self.tools = tools
        self.checkpoints = checkpoints
        self.max_model_rounds = max_model_rounds

    def start(self, question: str) -> WorkflowState:
        if not question.strip():
            raise WorkflowError("question must not be empty")
        now = utcnow()
        state = WorkflowState(
            workflow_id=f"wf_{new_ulid()}",
            question=question.strip(),
            status="running",
            provider=self.provider.name,
            model=str(getattr(self.provider, "model", self.provider.name)),
            messages=[
                Message(role="system", content=EVIDENCE_BRIEF_SYSTEM_PROMPT).to_dict(),
                Message(role="user", content=question.strip()).to_dict(),
            ],
            created_at=now,
            updated_at=now,
        )
        self.checkpoints.save(state)
        return self._continue(state)

    def resume(self, workflow_id: str) -> WorkflowState:
        state = self.checkpoints.load(workflow_id)
        if state.status == "completed":
            return state
        current_provider = self.provider.name
        current_model = str(getattr(self.provider, "model", current_provider))
        if state.provider not in {"unknown", current_provider}:
            raise WorkflowError(
                f"workflow provider mismatch: checkpoint uses {state.provider!r}, "
                f"configured provider is {current_provider!r}"
            )
        if state.model != current_model:
            raise WorkflowError(
                f"workflow model mismatch: checkpoint uses {state.model!r}, "
                f"configured model is {current_model!r}"
            )
        state.provider = current_provider
        state.status = "running"
        state.last_error = None
        self.checkpoints.save(state)
        return self._continue(state)

    def _continue(self, state: WorkflowState) -> WorkflowState:
        try:
            for _round in range(self.max_model_rounds):
                self._execute_pending_tools(state)
                response = self.provider.generate(
                    [Message.from_dict(message) for message in state.messages],
                    response_schema=EvidenceBrief.model_json_schema(),
                    schema_name="evidence_brief",
                    tools=self.tools.api_schemas(),
                )
                if response.metrics is not None:
                    self._record_metrics(state, response.metrics.to_dict())
                state.messages.append(response.as_message().to_dict())
                self.checkpoints.save(state)

                if response.tool_calls:
                    continue
                if response.content is None:
                    raise WorkflowError("model returned neither tool calls nor final content")
                try:
                    output = EvidenceBrief.model_validate_json(response.content)
                except PydanticValidationError as exc:
                    raise WorkflowError(
                        f"final output failed local schema validation: {exc}"
                    ) from exc
                self._validate_grounding(state, output)
                state.output = output
                state.status = "completed"
                state.last_error = None
                self.checkpoints.save(state)
                return state

            raise WorkflowError(
                f"workflow exceeded the limit of {self.max_model_rounds} model rounds"
            )
        except Exception as exc:
            if isinstance(exc, AIProviderError) and exc.metadata:
                self._record_metrics(state, exc.metadata)
            state.status = "paused"
            state.last_error = str(exc)
            checkpoint = self.checkpoints.save(state)
            raise WorkflowError(
                f"workflow {state.workflow_id} paused: {exc}. "
                f"Checkpoint: {checkpoint}. Resume with --resume {state.workflow_id}"
            ) from exc

    def _execute_pending_tools(self, state: WorkflowState) -> None:
        completed_ids = {
            str(message["tool_call_id"])
            for message in state.messages
            if message.get("role") == "tool" and message.get("tool_call_id")
        }
        pending: list[ToolCall] = []
        seen_ids = set(completed_ids)
        for message in state.messages:
            if message.get("role") != "assistant":
                continue
            for raw_call in message.get("tool_calls", ()):
                call = ToolCall.from_api(raw_call)
                if call.id not in seen_ids:
                    pending.append(call)
                    seen_ids.add(call.id)

        for call in pending:
            result = self.tools.execute(call.name, call.arguments)
            state.messages.append(
                Message(
                    role="tool",
                    content=result,
                    tool_call_id=call.id,
                ).to_dict()
            )
            state.tool_events.append(
                ToolEvent(
                    call_id=call.id,
                    name=call.name,
                    arguments=call.arguments,
                    result=result,
                    completed_at=utcnow(),
                )
            )
            self.checkpoints.save(state)

    @staticmethod
    def _record_metrics(state: WorkflowState, metrics: dict[str, Any]) -> None:
        safe_metrics = dict(metrics)
        if not state.model_calls or state.model_calls[-1] != safe_metrics:
            state.model_calls.append(safe_metrics)

    @staticmethod
    def _validate_grounding(state: WorkflowState, output: EvidenceBrief) -> None:
        retrieved: dict[str, dict[str, Any]] = {}
        for event in state.tool_events:
            if event.name != "get_experience":
                continue
            try:
                record = json.loads(event.result)
                retrieved[str(record["id"])] = record
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise WorkflowError("get_experience returned an invalid record") from exc

        for citation in output.citations:
            record = retrieved.get(citation.experience_id)
            if record is None:
                raise WorkflowError(
                    f"citation {citation.experience_id} was not loaded with get_experience"
                )
            allowed_locations = {
                str(evidence["location"])
                for evidence in record.get("evidence", ())
                if isinstance(evidence, dict) and "location" in evidence
            }
            unknown = set(citation.evidence_locations) - allowed_locations
            if unknown:
                raise WorkflowError(
                    f"citation contains unknown evidence locations: {sorted(unknown)}"
                )
