"""AI layer contract tests: prompts, provider protocol and wiring (#010).

Provider behavior is exercised through an injected fake client — no
network, and no real HTTP traffic ever leaves the test process.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from experienceos.ai.mock import MockProvider
from experienceos.ai.prompts import (
    ALL_PROMPTS,
    EVIDENCE_GUARDRAIL_NOTE,
    render_prompt,
)
from experienceos.ai.provider import (
    LLMProvider,
    Message,
    OpenAICompatibleProvider,
    build_provider,
)
from experienceos.config import AIConfig
from experienceos.core.errors import AIProviderError


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: Any = None) -> None:
        if payload is None:
            payload = {"choices": [{"message": {"content": "ok"}}]}
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> Any:
        return self._payload


class FakeClient:
    """Records .post calls; replays scripted outcomes in order."""

    def __init__(self, *outcomes: FakeResponse | Exception) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, headers=None, json=None, timeout=None) -> FakeResponse:
        self.calls.append(
            {"url": url, "headers": headers, "json": json, "timeout": timeout}
        )
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    @property
    def call_count(self) -> int:
        return len(self.calls)


def _provider(client: FakeClient, **config_kwargs: Any) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(AIConfig(**config_kwargs), client=client)


def _messages() -> list[Message]:
    return [Message(role="user", content="hello")]


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

    def test_message_is_simple_data(self) -> None:
        message = Message(role="user", content="hello")
        assert message.role == "user"


class TestOpenAICompatibleProvider:
    @pytest.fixture(autouse=True)
    def _api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def test_success_returns_message_content(self) -> None:
        client = FakeClient(FakeResponse())
        reply = _provider(client).complete(_messages())
        assert reply == "ok"
        assert client.call_count == 1
        request = client.calls[0]
        assert request["json"]["messages"] == [{"role": "user", "content": "hello"}]
        assert request["headers"]["Authorization"].startswith("Bearer ")

    def test_configured_timeout_is_passed_to_transport(self) -> None:
        client = FakeClient(FakeResponse())
        _provider(client, timeout=7.5).complete(_messages())
        assert client.calls[0]["timeout"] == 7.5

    def test_url_uses_configured_base_url(self) -> None:
        client = FakeClient(FakeResponse())
        _provider(client, base_url="https://open.bigmodel.cn/api/paas/v4/").complete(
            _messages()
        )
        assert client.calls[0]["url"] == (
            "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        )

    def test_network_error_is_retried_once_then_succeeds(self) -> None:
        client = FakeClient(
            httpx.ConnectError("boom"), FakeResponse(payload={"choices": [
                {"message": {"content": "second try"}}
            ]})
        )
        reply = _provider(client).complete(_messages())
        assert reply == "second try"
        assert client.call_count == 2

    def test_two_network_errors_raise_after_retry(self) -> None:
        client = FakeClient(httpx.ReadTimeout("slow"), httpx.ConnectError("down"))
        with pytest.raises(AIProviderError, match="after 1 retry"):
            _provider(client).complete(_messages())
        assert client.call_count == 2

    def test_429_is_not_retried_and_carries_summary(self) -> None:
        client = FakeClient(FakeResponse(429, {"error": "rate limited"}))
        with pytest.raises(AIProviderError, match=r"HTTP 429.*rate limited"):
            _provider(client).complete(_messages())
        assert client.call_count == 1

    def test_5xx_is_not_retried(self) -> None:
        client = FakeClient(FakeResponse(503, {"error": "overloaded"}))
        with pytest.raises(AIProviderError, match="HTTP 503"):
            _provider(client).complete(_messages())
        assert client.call_count == 1

    def test_4xx_reports_rejection(self) -> None:
        client = FakeClient(FakeResponse(401, {"error": "bad key"}))
        with pytest.raises(AIProviderError, match=r"HTTP 401.*bad key"):
            _provider(client).complete(_messages())

    def test_unexpected_response_shape_is_actionable(self) -> None:
        client = FakeClient(FakeResponse(200, {"unexpected": True}))
        with pytest.raises(AIProviderError, match="unexpected response shape"):
            _provider(client).complete(_messages())

    def test_missing_api_key_names_the_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        provider = OpenAICompatibleProvider(AIConfig(api_key_env="OPENAI_API_KEY"))
        with pytest.raises(AIProviderError, match=r"\$OPENAI_API_KEY"):
            provider.complete(_messages())

    def test_api_key_only_ever_read_from_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # the key must flow to the transport, never to disk-bound config
        monkeypatch.setenv("TEST_AI_KEY", "secret-value")
        client = FakeClient(FakeResponse())
        _provider(client, api_key_env="TEST_AI_KEY").complete(_messages())
        assert client.calls[0]["headers"]["Authorization"] == "Bearer secret-value"
        assert "secret-value" not in json.dumps(client.calls[0]["json"])


class TestMockProvider:
    def test_satisfies_protocol(self) -> None:
        assert isinstance(MockProvider("ok"), LLMProvider)

    def test_replays_scripted_replies_in_order(self) -> None:
        provider = MockProvider("first", "second")
        assert provider.complete(_messages()) == "first"
        assert provider.complete(_messages()) == "second"

    def test_repeats_last_reply_when_exhausted(self) -> None:
        provider = MockProvider("only")
        provider.complete(_messages())
        assert provider.complete(_messages()) == "only"
        assert provider.replies_used == 2

    def test_records_every_request(self) -> None:
        provider = MockProvider("ok")
        provider.complete([Message(role="system", content="s")])
        provider.complete([Message(role="user", content="u")])
        assert [len(call) for call in provider.calls] == [1, 1]
        assert provider.calls[1][0].content == "u"

    def test_requires_at_least_one_reply(self) -> None:
        with pytest.raises(ValueError):
            MockProvider()


class TestBuildProvider:
    def test_builds_openai_compatible_from_config(self) -> None:
        provider = build_provider(AIConfig())
        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.name == "openai-compat"

    def test_unknown_provider_name_is_actionable(self) -> None:
        with pytest.raises(AIProviderError, match=r"unknown ai.provider"):
            build_provider(AIConfig(provider="quantum"))
