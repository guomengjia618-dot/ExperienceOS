"""AI layer contract tests: prompts and provider protocol (no network)."""

from __future__ import annotations

import json

import httpx
import pytest

from experienceos.ai.prompts import (
    ALL_PROMPTS,
    EVIDENCE_GUARDRAIL_NOTE,
    render_prompt,
)
from experienceos.ai.provider import (
    LLMProvider,
    Message,
    MockProvider,
    ModelResponse,
    OpenAICompatibleProvider,
    complete_structured,
)
from experienceos.ai.responses import OpenAIResponsesProvider
from experienceos.ai.schemas import ProviderHealth
from experienceos.config import AIConfig
from experienceos.core.errors import AIProviderError


class _FakeHTTPResponse:
    def __init__(
        self,
        status_code: int,
        data: dict,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._data = data
        self.headers = headers or {}
        self.text = json.dumps(data)

    def json(self) -> dict:
        return self._data


class TestPrompts:
    @pytest.mark.parametrize("name", list(ALL_PROMPTS))
    def test_templates_encode_the_no_fabrication_rule(self, name: str) -> None:
        prompt = ALL_PROMPTS[name].lower()
        assert "never invent" in prompt or "only" in prompt

    def test_intake_prompt_mentions_evidence(self) -> None:
        assert "evidence" in ALL_PROMPTS["intake_interview"].lower()

    def test_extraction_prompt_demands_json(self) -> None:
        assert "json" in ALL_PROMPTS["extraction"].lower()
        assert "ai:" in ALL_PROMPTS["extraction"]  # provenance marking

    def test_render_prompt_fills_variables(self) -> None:
        rendered = render_prompt("intake_interview", language="Chinese")
        assert "Chinese" in rendered

    def test_render_prompt_rejects_unknown_template(self) -> None:
        with pytest.raises(KeyError):
            render_prompt("nope")

    def test_guardrail_note_links_claims_to_evidence(self) -> None:
        assert "without linked evidence" in EVIDENCE_GUARDRAIL_NOTE


class TestProviderProtocol:
    def test_openai_compatible_satisfies_protocol(self) -> None:
        provider = OpenAICompatibleProvider(AIConfig())
        assert isinstance(provider, LLMProvider)

    def test_responses_adapter_satisfies_protocol(self) -> None:
        provider = OpenAIResponsesProvider(AIConfig(provider="openai-responses"))
        assert isinstance(provider, LLMProvider)

    def test_message_is_simple_data(self) -> None:
        message = Message(role="user", content="hello")
        assert message.role == "user"

    def test_provider_sends_strict_schema_and_tools(self, monkeypatch) -> None:
        provider = OpenAICompatibleProvider(AIConfig(model="test-model"))
        captured = {}

        def fake_post(payload):
            captured.update(payload)
            return {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "lookup",
                                        "arguments": '{"query": "x"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            }

        monkeypatch.setattr(provider, "_post", fake_post)
        response = provider.generate(
            [Message(role="user", content="hello")],
            response_schema=ProviderHealth.model_json_schema(),
            schema_name="provider_health",
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "parameters": {"type": "object"},
                    },
                }
            ],
        )

        assert captured["model"] == "test-model"
        assert captured["response_format"]["type"] == "json_schema"
        assert captured["response_format"]["json_schema"]["strict"] is True
        assert captured["tool_choice"] == "auto"
        assert response.tool_calls[0].arguments == {"query": "x"}

    def test_missing_api_key_names_only_the_environment_variable(
        self, monkeypatch
    ) -> None:
        monkeypatch.delenv("TEST_EXPERIENCEOS_KEY", raising=False)
        provider = OpenAICompatibleProvider(AIConfig(api_key_env="TEST_EXPERIENCEOS_KEY"))
        with pytest.raises(AIProviderError, match="TEST_EXPERIENCEOS_KEY"):
            provider.generate([Message(role="user", content="hello")])

    def test_real_http_path_uses_bearer_key_without_putting_it_in_payload(
        self, monkeypatch
    ) -> None:
        monkeypatch.setenv("TEST_EXPERIENCEOS_KEY", "super-secret")
        captured = {}

        class FakeResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json():
                return {"choices": [{"message": {"content": "hello"}}]}

        def fake_post(url, *, headers, json, timeout):
            captured.update(
                {"url": url, "headers": headers, "payload": json, "timeout": timeout}
            )
            return FakeResponse()

        monkeypatch.setattr(httpx, "post", fake_post)
        provider = OpenAICompatibleProvider(
            AIConfig(
                base_url="https://models.example/v1",
                model="real-model",
                api_key_env="TEST_EXPERIENCEOS_KEY",
            )
        )
        assert provider.complete([Message(role="user", content="hello")]) == "hello"
        assert captured["url"] == "https://models.example/v1/chat/completions"
        assert captured["headers"]["Authorization"] == "Bearer super-secret"
        assert "super-secret" not in json.dumps(captured["payload"])

    def test_network_error_is_retried_once(self, monkeypatch) -> None:
        monkeypatch.setenv("TEST_EXPERIENCEOS_KEY", "secret")
        calls = 0

        class FakeResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json():
                return {"choices": [{"message": {"content": "recovered"}}]}

        def flaky_post(url, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise httpx.ConnectError("offline", request=httpx.Request("POST", url))
            return FakeResponse()

        monkeypatch.setattr(httpx, "post", flaky_post)
        provider = OpenAICompatibleProvider(
            AIConfig(
                api_key_env="TEST_EXPERIENCEOS_KEY",
                max_retries=1,
                retry_base_seconds=0,
                retry_jitter_seconds=0,
            )
        )
        assert provider.complete([Message(role="user", content="hello")]) == "recovered"
        assert calls == 2

    def test_rate_limit_retry_records_request_id_and_usage(self, monkeypatch) -> None:
        monkeypatch.setenv("TEST_EXPERIENCEOS_KEY", "secret")
        responses = [
            _FakeHTTPResponse(
                429,
                {"error": "slow down"},
                headers={"retry-after": "0", "x-request-id": "req_rate"},
            ),
            _FakeHTTPResponse(
                200,
                {
                    "choices": [{"message": {"content": "recovered"}}],
                    "usage": {
                        "prompt_tokens": 11,
                        "completion_tokens": 4,
                        "total_tokens": 15,
                    },
                },
                headers={"x-request-id": "req_ok"},
            ),
        ]
        monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: responses.pop(0))
        provider = OpenAICompatibleProvider(
            AIConfig(
                api_key_env="TEST_EXPERIENCEOS_KEY",
                max_retries=1,
                retry_base_seconds=0,
                retry_jitter_seconds=0,
            )
        )

        assert provider.complete([Message(role="user", content="hello")]) == "recovered"
        assert provider.last_metrics is not None
        assert provider.last_metrics.retry_count == 1
        assert provider.last_metrics.request_id == "req_ok"
        assert provider.last_metrics.total_tokens == 15

    @pytest.mark.parametrize(
        ("status_code", "error_type"),
        [(429, "rate_limit"), (503, "server_error")],
    )
    def test_exhausted_http_failures_are_classified(
        self, monkeypatch, status_code, error_type
    ) -> None:
        monkeypatch.setenv("TEST_EXPERIENCEOS_KEY", "secret")
        monkeypatch.setattr(
            httpx,
            "post",
            lambda *args, **kwargs: _FakeHTTPResponse(
                status_code,
                {"error": "unavailable"},
                headers={"x-request-id": "req_failed"},
            ),
        )
        provider = OpenAICompatibleProvider(
            AIConfig(api_key_env="TEST_EXPERIENCEOS_KEY", max_retries=0)
        )

        with pytest.raises(AIProviderError) as captured:
            provider.complete([Message(role="user", content="hello")])

        assert captured.value.metadata["error_type"] == error_type
        assert captured.value.metadata["request_id"] == "req_failed"

    def test_timeout_is_bounded_and_classified(self, monkeypatch) -> None:
        monkeypatch.setenv("TEST_EXPERIENCEOS_KEY", "secret")
        attempts = 0

        def timeout(url, **kwargs):
            nonlocal attempts
            attempts += 1
            raise httpx.ReadTimeout("slow", request=httpx.Request("POST", url))

        monkeypatch.setattr(httpx, "post", timeout)
        provider = OpenAICompatibleProvider(
            AIConfig(
                api_key_env="TEST_EXPERIENCEOS_KEY",
                max_retries=1,
                retry_base_seconds=0,
                retry_jitter_seconds=0,
            )
        )

        with pytest.raises(AIProviderError) as captured:
            provider.complete([Message(role="user", content="hello")])

        assert attempts == 2
        assert captured.value.metadata["error_type"] == "timeout"
        assert captured.value.metadata["retry_count"] == 1

    def test_responses_adapter_replays_function_call_items(self, monkeypatch) -> None:
        provider = OpenAIResponsesProvider(
            AIConfig(provider="openai-responses", model="test-responses")
        )
        payloads = []
        replies = [
            {
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_1",
                        "name": "lookup",
                        "arguments": '{"query":"x"}',
                    }
                ]
            },
            {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"ok":true}'}],
                    }
                ]
            },
        ]

        def fake_post(payload):
            payloads.append(payload)
            return replies.pop(0)

        monkeypatch.setattr(provider, "_post", fake_post)
        first = provider.generate(
            [
                Message(role="system", content="Be grounded."),
                Message(role="user", content="x"),
            ],
            response_schema=ProviderHealth.model_json_schema(),
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "description": "Lookup x",
                        "strict": True,
                        "parameters": {"type": "object"},
                    },
                }
            ],
        )
        second = provider.generate(
            [
                Message(role="system", content="Be grounded."),
                Message(role="user", content="x"),
                first.as_message(),
                Message(role="tool", content='{"value":1}', tool_call_id="call_1"),
            ]
        )

        assert first.tool_calls[0].name == "lookup"
        assert payloads[0]["tools"][0]["name"] == "lookup"
        assert payloads[0]["text"]["format"]["strict"] is True
        assert payloads[1]["input"][-2]["type"] == "function_call"
        assert payloads[1]["input"][-1] == {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": '{"value":1}',
        }
        assert second.content == '{"ok":true}'

    def test_structured_output_is_validated_locally(self) -> None:
        provider = MockProvider([ModelResponse(content='{"ok": "not-a-bool"}')])
        with pytest.raises(AIProviderError, match="local validation"):
            complete_structured(
                provider,
                [Message(role="user", content="check")],
                ProviderHealth,
                schema_name="provider_health",
            )
