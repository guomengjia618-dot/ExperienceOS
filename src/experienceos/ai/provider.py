"""LLM provider abstraction.

ExperienceOS is provider-agnostic: anything that can turn a conversation
into text can drive the assistant. Providers must be registered by name
and configured through ``config.toml`` ([ai] section); API keys are read
from environment variables — secrets are never persisted.

The critical contract lives in :class:`LLMProvider`: providers only ever
*propose* content. Turning a proposal into a stored record is the
caller's job and must go through user confirmation (see ARCHITECTURE.md,
"AI propose, human decide").

``OpenAICompatibleProvider`` covers every OpenAI-compatible endpoint
(OpenAI, GLM, DeepSeek, vLLM, Ollama, ...). Network-class failures get
exactly one retry; HTTP 429/5xx responses are never retried but surface
as ``AIProviderError`` with a response summary. A raw ``client`` can be
injected for tests (#010).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from experienceos.config import AIConfig
from experienceos.core.errors import AIProviderError

_NETWORK_RETRIES = 1  # one retry after the first network-class failure
_BODY_SUMMARY_LIMIT = 200


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
    """Any OpenAI-compatible /chat/completions endpoint. Requires the
    optional ``[ai]`` extra."""

    name = "openai-compat"

    def __init__(self, config: AIConfig, client: Any | None = None) -> None:
        self._config = config
        self._client = client  # test injection point (needs .post(...))

    def complete(self, messages: list[Message]) -> str:
        httpx, api_key = self._dependencies()
        payload = {
            "model": self._config.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        response = self._send(httpx, api_key, payload)
        return self._extract_content(response)

    # -- plumbing ---------------------------------------------------------

    def _dependencies(self) -> tuple[Any, str]:
        try:
            import httpx
        except ImportError as exc:
            raise AIProviderError(
                "httpx is required for AI features: pip install 'experienceos[ai]'"
            ) from exc
        api_key = os.environ.get(self._config.api_key_env, "")
        if not api_key:
            raise AIProviderError(
                f"missing API key: set ${self._config.api_key_env} "
                "(configured in config.toml [ai])"
            )
        return httpx, api_key

    def _send(self, httpx: Any, api_key: str, payload: dict[str, Any]) -> Any:
        url = f"{self._config.base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}"}
        last_error: Exception | None = None
        for _attempt in range(1 + _NETWORK_RETRIES):
            try:
                response = self._post(httpx, url, headers, payload)
            except httpx.TransportError as exc:  # connection errors & timeouts
                last_error = exc
                continue
            if response.status_code == 429 or response.status_code >= 500:
                # server-side condition; single-shot CLI usage does not retry
                raise AIProviderError(
                    f"provider returned HTTP {response.status_code}: {_summary(response)}"
                )
            if response.status_code >= 400:
                raise AIProviderError(
                    f"provider rejected the request (HTTP {response.status_code}): "
                    f"{_summary(response)}"
                )
            return response
        raise AIProviderError(
            f"request to {self._config.base_url} failed after "
            f"{_NETWORK_RETRIES} retry: {last_error}"
        )

    def _post(self, httpx: Any, url: str, headers: dict[str, str], payload: Any) -> Any:
        if self._client is not None:
            return self._client.post(
                url, headers=headers, json=payload, timeout=self._config.timeout
            )
        with httpx.Client(timeout=self._config.timeout) as session:
            return session.post(url, headers=headers, json=payload)

    @staticmethod
    def _extract_content(response: Any) -> str:
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (AttributeError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise AIProviderError(
                f"provider returned an unexpected response shape: {_summary(response)}"
            ) from exc
        if not isinstance(content, str):
            raise AIProviderError(
                f"provider returned a non-string message content: {_summary(response)}"
            )
        return content


def build_provider(config: AIConfig) -> LLMProvider:
    """Build the provider adapter named by ``config.ai.provider``."""
    if config.provider in ("openai-compat", "openai", "openai-compatible"):
        return OpenAICompatibleProvider(config)
    raise AIProviderError(
        f"unknown ai.provider {config.provider!r}; supported: openai-compat"
    )


def _summary(response: Any, limit: int = _BODY_SUMMARY_LIMIT) -> str:
    try:
        text = (response.text or "").strip().replace("\n", " ")
    except Exception:  # pragma: no cover - defensive: fake responses
        text = ""
    return text[:limit] or "(no body)"
