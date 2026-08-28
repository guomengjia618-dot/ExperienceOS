"""OpenAI Responses API adapter for the provider-neutral workflow."""

from __future__ import annotations

import json
from typing import Any

from experienceos.ai.provider import Message, ModelResponse, ToolCall
from experienceos.ai.transport import HTTPResult, OpenAIHTTPTransport, RequestMetrics
from experienceos.config import AIConfig
from experienceos.core.errors import AIProviderError


class OpenAIResponsesProvider:
    """Stateless Responses API client with function-call item replay."""

    name = "openai-responses"

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
    ) -> ModelResponse:
        instructions, input_items = self._translate_messages(messages)
        payload: dict[str, Any] = {
            "model": self._config.model,
            "input": input_items,
            "store": False,
        }
        if instructions:
            payload["instructions"] = instructions
        if response_schema is not None:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": response_schema,
                }
            }
        if tools:
            payload["tools"] = [self._translate_tool(tool) for tool in tools]
            payload["tool_choice"] = "auto"

        result = self._post(payload)
        if isinstance(result, HTTPResult):
            data = result.data
            metrics = result.metrics
        else:  # Lightweight test seam.
            data = result
            metrics = None
        try:
            output = data["output"]
            if not isinstance(output, list):
                raise TypeError("output must be a list")
            calls = tuple(
                self._parse_tool_call(item)
                for item in output
                if isinstance(item, dict) and item.get("type") == "function_call"
            )
            content = self._extract_output_text(data, output)
            response_items = tuple(item for item in output if isinstance(item, dict))
            return ModelResponse(
                content=content,
                tool_calls=calls,
                response_items=response_items,
                metrics=metrics,
            )
        except (KeyError, TypeError) as exc:
            raise AIProviderError(
                f"Responses API returned an unexpected response: {exc}"
            ) from exc

    def complete(self, messages: list[Message]) -> str:
        response = self.generate(messages)
        if response.tool_calls:
            raise AIProviderError("plain completion unexpectedly requested a tool")
        if response.content is None:
            raise AIProviderError("Responses API returned no content")
        return response.content

    def _post(self, payload: dict[str, Any]) -> HTTPResult:
        return self._transport.post("responses", payload)

    @staticmethod
    def _translate_messages(messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
        instructions: list[str] = []
        input_items: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "system":
                if message.content:
                    instructions.append(message.content)
                continue
            if message.response_items:
                input_items.extend(message.response_items)
                continue
            if message.role == "tool":
                if not message.tool_call_id:
                    raise AIProviderError("tool message is missing tool_call_id")
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.tool_call_id,
                        "output": message.content or "",
                    }
                )
                continue
            input_items.append({"role": message.role, "content": message.content or ""})
        return "\n\n".join(instructions), input_items

    @staticmethod
    def _translate_tool(tool: dict[str, Any]) -> dict[str, Any]:
        try:
            function = tool["function"]
            translated = {
                "type": "function",
                "name": function["name"],
                "description": function.get("description", ""),
                "parameters": function["parameters"],
            }
            if "strict" in function:
                translated["strict"] = function["strict"]
            return translated
        except (KeyError, TypeError) as exc:
            raise AIProviderError(f"invalid function tool schema: {exc}") from exc

    @staticmethod
    def _parse_tool_call(item: dict[str, Any]) -> ToolCall:
        try:
            arguments = json.loads(item["arguments"])
            if not isinstance(arguments, dict):
                raise TypeError("arguments must be a JSON object")
            return ToolCall(
                id=str(item["call_id"]),
                name=str(item["name"]),
                arguments=arguments,
            )
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise AIProviderError(f"Responses API returned an invalid tool call: {exc}") from exc

    @staticmethod
    def _extract_output_text(data: dict[str, Any], output: list[Any]) -> str | None:
        if isinstance(data.get("output_text"), str):
            return str(data["output_text"])
        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for part in item.get("content", ()):
                if isinstance(part, dict) and part.get("type") == "output_text":
                    text = part.get("text")
                    if isinstance(text, str):
                        parts.append(text)
        return "".join(parts) or None
