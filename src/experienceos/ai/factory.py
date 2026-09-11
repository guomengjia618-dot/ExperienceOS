"""Configured model-provider selection."""

from experienceos.ai.provider import LLMProvider, OpenAICompatibleProvider
from experienceos.ai.responses import OpenAIResponsesProvider
from experienceos.config import AIConfig
from experienceos.core.errors import AIProviderError


def create_provider(config: AIConfig) -> LLMProvider:
    """Create the selected adapter while keeping the workflow provider-neutral."""
    if config.provider == OpenAICompatibleProvider.name:
        return OpenAICompatibleProvider(config)
    if config.provider == OpenAIResponsesProvider.name:
        return OpenAIResponsesProvider(config)
    raise AIProviderError(
        f"unsupported ai.provider {config.provider!r}; expected "
        f"{OpenAICompatibleProvider.name!r} or {OpenAIResponsesProvider.name!r}"
    )
