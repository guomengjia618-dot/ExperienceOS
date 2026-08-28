"""LLM provider abstraction and OpenAI-compatible HTTP implementation.

The contract exposes strict structured output and function tool calls. API
keys are resolved from an environment variable at request time and are never
copied into messages, checkpoints, or config files.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from experienceos.ai.transport import HTTPResult, OpenAIHTTPTransport, RequestMetrics
from experienceos.config import AIConfig
from experienceos.core.errors import AIProviderError


@dataclass(frozen=True)
class Message:
    """One provider-neutral message, including replay metadata."""

    role: str  # system | user | assistant | tool
    content: str | None
    tool_calls: tuple[dict[str, Any], ...] = ()
    tool_call_id: str | None = None
    response_items: tuple[dict[str, Any], ...] = ()

    def to_api(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            payload["tool_calls"] = list(self.tool_calls)
        if self.tool_call_id is not None:
            payload["tool_call_id"] = self.tool_call_id
        return payload

    def to_dict(self) -> dict[str, Any]:
        payload = self.to_api()
        if self.response_items:
            payload["response_items"] = list(self.response_items)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        return cls(
            role=str(data["role"]),
            content=data.get("content"),
            tool_calls=tuple(data.get("tool_calls", ())),
            tool_call_id=data.get("tool_call_id"),
            response_items=tuple(data.get("response_items", ())),
        )


@dataclass(frozen=True)
class ToolCall:
    """A validated representation of one model-requested function call."""

    id: str
    name: str
    arguments: dict[str, Any]

    def to_api(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ToolCall:
        try:
            function = data["function"]
            arguments = json.loads(function["arguments"])
            if not isinstance(arguments, dict):
                raise TypeError("tool arguments must be a JSON object")
            return cls(id=str(data["id"]), name=str(function["name"]), arguments=arguments)
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise AIProviderError(f"model returned an invalid tool call: {exc}") from exc


@dataclass(frozen=True)
class ModelResponse:
    """One assistant turn: either final content, tool calls, or both."""

    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    response_items: tuple[dict[str, Any], ...] = ()
    metrics: RequestMetrics | None = None

    def as_message(self) -> Message:
        return Message(
            role="assistant",
            content=self.content,
            tool_calls=tuple(call.to_api() for call in self.tool_calls),
            response_items=self.response_items,
        )


@runtime_checkable
class LLMProvider(Protocol):
    """Provider contract used by ExperienceOS workflows."""

    name: str

    def generate(
        self,
        messages: list[Message],
        *,
        response_schema: dict[str, Any] | None = None,
        schema_name: str = "response",
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelResponse:
        """Generate an assistant turn with optional schema and function tools."""
        ...  # pragma: no cover

    def complete(self, messages: list[Message]) -> str:
        """Compatibility helper for plain text completions."""
        ...  # pragma: no cover


class OpenAICompatibleProvider:
    """Real /chat/completions client for OpenAI-compatible endpoints."""

    name = "openai-compat"

    def __init__(
        self,
        config: AIConfig,
        *,
        transport: OpenAIHTTPTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport or OpenAIHTTPTransport(config, provider_name=self.name)

    @property
    def model(self) -> str:
        return self._config.model

    @property
    def last_metrics(self) -> RequestMetrics | None:
        return self._transport.last_metrics

    def generate(
        self,
        messages: list[Message],
        *,
        response_schema: dict[str, Any] | None = None,
        schema_name: str = "response",
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelResponse:  # pragma: no cover - network I/O is mocked in tests
        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": [message.to_api() for message in messages],
        }
        if response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": response_schema,
                },
            }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        result = self._post(payload)
        if isinstance(result, HTTPResult):
            data = result.data
            metrics = result.metrics
        else:  # Backwards-compatible seam for lightweight provider tests.
            data = result
            metrics = None
        try:
            message = data["choices"][0]["message"]
            calls = tuple(ToolCall.from_api(call) for call in message.get("tool_calls", ()))
            return ModelResponse(
                content=message.get("content"),
                tool_calls=calls,
                metrics=metrics,
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError(f"model API returned an unexpected response: {exc}") from exc

    def complete(self, messages: list[Message]) -> str:
        response = self.generate(messages)
        if response.tool_calls:
            raise AIProviderError("plain completion unexpectedly requested a tool")
        if response.content is None:
            raise AIProviderError("model API returned no content")
        return response.content

    def _post(self, payload: dict[str, Any]) -> HTTPResult:
        return self._transport.post("chat/completions", payload)


@dataclass
class MockProvider:
    """Deterministic recorded-response provider for tests, evals, and demos."""

    responses: list[ModelResponse | Exception]
    name: str = "mock"
    calls: list[dict[str, Any]] = field(default_factory=list)

    def generate(
        self,
        messages: list[Message],
        *,
        response_schema: dict[str, Any] | None = None,
        schema_name: str = "response",
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelResponse:
        self.calls.append(
            {
                "messages": [message.to_dict() for message in messages],
                "response_schema": response_schema,
                "schema_name": schema_name,
                "tools": tools,
            }
        )
        if not self.responses:
            raise AIProviderError("mock response queue is empty")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def complete(self, messages: list[Message]) -> str:
        response = self.generate(messages)
        if response.content is None or response.tool_calls:
            raise AIProviderError("mock plain completion did not return text")
        return response.content


def complete_structured(
    provider: LLMProvider,
    messages: list[Message],
    output_model: type[BaseModel],
    *,
    schema_name: str,
) -> BaseModel:
    """Request strict JSON Schema output and validate it again locally."""
    response = provider.generate(
        messages,
        response_schema=output_model.model_json_schema(),
        schema_name=schema_name,
    )
    if response.tool_calls or response.content is None:
        raise AIProviderError("structured completion did not return final JSON content")
    try:
        return output_model.model_validate_json(response.content)
    except PydanticValidationError as exc:
        raise AIProviderError(f"structured output failed local validation: {exc}") from exc
