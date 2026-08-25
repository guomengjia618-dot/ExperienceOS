"""AI layer: provider abstraction and prompt templates.

M0 ships the contracts only (protocol + prompts). Provider wiring, the
interactive `interview` command and `enrich` proposals land in M2 —
see docs/issues/m2-intelligence.md.
"""

from experienceos.ai.prompts import (
    ALL_PROMPTS,
    EXTRACTION_PROMPT_V1,
    INTAKE_INTERVIEW_PROMPT_V1,
    render_prompt,
)
from experienceos.ai.provider import LLMProvider, Message, OpenAICompatibleProvider

__all__ = [
    "ALL_PROMPTS",
    "EXTRACTION_PROMPT_V1",
    "INTAKE_INTERVIEW_PROMPT_V1",
    "LLMProvider",
    "Message",
    "OpenAICompatibleProvider",
    "render_prompt",
]
