"""AI layer: providers, tools, structured outputs, and durable workflows.

M0 shipped the contracts; #010 wired OpenAI-compatible endpoints; the
checkpointed evidence-brief workflow, its read-only tool registry, the
evaluation harness, and the provider factory make the layer a testable
system — "AI propose, human decide" throughout.
"""

from experienceos.ai.factory import create_provider
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
    ModelResponse,
    OpenAICompatibleProvider,
    RecordedProvider,
    ToolCall,
    complete_structured,
)
from experienceos.ai.responses import OpenAIResponsesProvider
from experienceos.ai.schemas import BriefCitation, EvidenceBrief, ProviderHealth
from experienceos.ai.tools import ExperienceToolRegistry
from experienceos.ai.workflow import EvidenceBriefWorkflow, WorkflowCheckpointStore

__all__ = [
    "ALL_PROMPTS",
    "EXTRACTION_PROMPT_V1",
    "INTAKE_INTERVIEW_PROMPT_V1",
    "BriefCitation",
    "EvidenceBrief",
    "EvidenceBriefWorkflow",
    "ExperienceToolRegistry",
    "LLMProvider",
    "Message",
    "MockProvider",
    "ModelResponse",
    "OpenAICompatibleProvider",
    "OpenAIResponsesProvider",
    "ProviderHealth",
    "RecordedProvider",
    "ToolCall",
    "WorkflowCheckpointStore",
    "complete_structured",
    "create_provider",
    "render_prompt",
]
