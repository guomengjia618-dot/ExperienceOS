"""Three read-only tools that connect the model to the real local store."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from experienceos.core.errors import ToolExecutionError
from experienceos.storage import ExperienceStore, SearchQuery, search


class SearchExperiencesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    limit: int = Field(ge=1, le=20)


class GetExperienceArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_or_prefix: str = Field(min_length=1)


class EvidenceStatsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class ToolDefinition:
    """Function schema plus its local, read-only implementation."""

    name: str
    description: str
    arguments_model: type[BaseModel]
    handler: Callable[[BaseModel], Any]

    def api_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "strict": True,
                "parameters": self.arguments_model.model_json_schema(),
            },
        }

    def execute(self, arguments: dict[str, Any]) -> Any:
        try:
            parsed = self.arguments_model.model_validate(arguments)
        except PydanticValidationError as exc:
            raise ToolExecutionError(f"invalid arguments for {self.name}: {exc}") from exc
        return self.handler(parsed)


class ExperienceToolRegistry:
    """Dispatch and describe the three ExperienceOS data tools."""

    def __init__(self, store: ExperienceStore) -> None:
        self.store = store
        self._tools = {
            "search_experiences": ToolDefinition(
                name="search_experiences",
                description=(
                    "Search the local experience archive. Use an empty query to list recent "
                    "records. Returns IDs and short summaries, not full records."
                ),
                arguments_model=SearchExperiencesArgs,
                handler=self._search,
            ),
            "get_experience": ToolDefinition(
                name="get_experience",
                description=(
                    "Load one complete experience by full ID or unique ID prefix before "
                    "making a detailed claim about it."
                ),
                arguments_model=GetExperienceArgs,
                handler=self._get,
            ),
            "get_evidence_stats": ToolDefinition(
                name="get_evidence_stats",
                description=(
                    "Measure evidence coverage across the local archive and summarize "
                    "evidence kinds. Use it before discussing evidence quality or gaps."
                ),
                arguments_model=EvidenceStatsArgs,
                handler=self._evidence_stats,
            ),
        }

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def api_schemas(self) -> list[dict[str, Any]]:
        return [tool.api_schema() for tool in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        try:
            tool = self._tools[name]
        except KeyError as exc:
            raise ToolExecutionError(f"unknown tool: {name}") from exc
        result = tool.execute(arguments)
        return json.dumps(result, ensure_ascii=False, sort_keys=True)

    def _search(self, args: BaseModel) -> list[dict[str, Any]]:
        parsed = SearchExperiencesArgs.model_validate(args)
        results = search(
            self.store.list_all(),
            SearchQuery(text=parsed.query, limit=parsed.limit),
        )
        return [
            {
                "id": result.experience.id,
                "title": result.experience.title,
                "type": result.experience.type.value,
                "period": result.experience.period.display(),
                "score": result.score,
                "evidence_count": len(result.experience.evidence),
                "description": result.experience.description,
            }
            for result in results
        ]

    def _get(self, args: BaseModel) -> dict[str, Any]:
        parsed = GetExperienceArgs.model_validate(args)
        full_id = self.store.resolve(parsed.id_or_prefix)
        return self.store.load(full_id).to_dict()

    def _evidence_stats(self, args: BaseModel) -> dict[str, Any]:
        EvidenceStatsArgs.model_validate(args)
        experiences = self.store.list_all()
        with_evidence = sum(bool(experience.evidence) for experience in experiences)
        kinds = Counter(
            evidence.kind.value
            for experience in experiences
            for evidence in experience.evidence
        )
        total = len(experiences)
        return {
            "total_experiences": total,
            "experiences_with_evidence": with_evidence,
            "experiences_without_evidence": total - with_evidence,
            "coverage": with_evidence / total if total else 0.0,
            "evidence_kinds": dict(kinds),
        }
