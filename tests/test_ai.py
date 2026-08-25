"""AI layer contract tests: prompts and provider protocol (no network)."""

from __future__ import annotations

import pytest

from experienceos.ai.prompts import (
    ALL_PROMPTS,
    EVIDENCE_GUARDRAIL_NOTE,
    render_prompt,
)
from experienceos.ai.provider import LLMProvider, Message, OpenAICompatibleProvider
from experienceos.config import AIConfig


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
