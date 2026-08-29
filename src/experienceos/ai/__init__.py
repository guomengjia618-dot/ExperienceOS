"""AI layer: provider abstraction and prompt templates.

M0 shipped the contracts (protocol + prompts); #010 wires providers:
configurable OpenAI-compatible endpoints with retry/timeout semantics,
a scripted MockProvider for tests and ``--dry-run`` modes, and the
``experienceos config`` / ``experienceos ai check`` commands. The
interactive ``interview`` and ``enrich`` commands land with #011/#012 —
see docs/issues/m2-intelligence.md.
"""

from experienceos.ai.mock import MockProvider
from experienceos.ai.prompts import (
    ALL_PROMPTS,
    EXTRACTION_PROMPT_V1,
    INTAKE_INTERVIEW_PROMPT_V1,
    render_prompt,
)
from experienceos.ai.provider import (
    LLMProvider,
    Message,
    OpenAICompatibleProvider,
    build_provider,
)

__all__ = [
    "ALL_PROMPTS",
    "EXTRACTION_PROMPT_V1",
    "INTAKE_INTERVIEW_PROMPT_V1",
    "LLMProvider",
    "Message",
    "MockProvider",
    "OpenAICompatibleProvider",
    "build_provider",
    "render_prompt",
]
