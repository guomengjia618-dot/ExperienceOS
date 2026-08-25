"""LLM provider abstraction.

ExperienceOS is provider-agnostic: anything that can turn a conversation
into text can drive the assistant. Providers must be registered by name
and configured through ``config.toml`` ([ai] section); API keys are read
from environment variables — secrets are never persisted.

The critical contract lives in :class:`LLMProvider`: providers only ever
*propose* content. Turning a proposal into a stored record is the
caller's job and must go through user confirmation (see ARCHITECTURE.md,
"AI propose, human decide").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from experienceos.config import AIConfig
from experienceos.core.errors import AIProviderError


@dataclass(frozen=True)
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str


@runtime_checkable
class LLMProvider(Protocol):
    """Minimal chat-completion interface all providers must implement."""

    name: str

    def complete(self, messages: list[Message]) -> str:
        """Return the assistant reply for a message list."""
        ...  # pragma: no cover


class OpenAICompatibleProvider:
    """Any OpenAI-compatible /chat/completions endpoint (OpenAI, GLM,
    DeepSeek, vLLM, Ollama, ...). Requires the optional ``[ai]`` extra."""

    name = "openai-compat"

    def __init__(self, config: AIConfig) -> None:
        self._config = config

    def complete(self, messages: list[Message]) -> str:  # pragma: no cover - network I/O
        try:
            import httpx
        except ImportError as exc:
            raise AIProviderError(
                "httpx is required for AI features: pip install 'experienceos[ai]'"
            ) from exc

        import os

        api_key = os.environ.get(self._config.api_key_env, "")
        if not api_key:
            raise AIProviderError(
                f"missing API key: set ${self._config.api_key_env} "
                f"(configured in config.toml [ai])"
            )
        try:
            response = httpx.post(
                f"{self._config.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": self._config.model,
                    "messages": [{"role": m.role, "content": m.content} for m in messages],
                },
                timeout=60,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except httpx.HTTPError as exc:
            raise AIProviderError(f"request to {self._config.base_url} failed: {exc}") from exc
