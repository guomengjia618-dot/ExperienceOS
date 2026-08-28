"""Runtime configuration for an ExperienceOS home directory.

The home directory layout (all user data lives here and only here):

    <home>/
      config.toml          # settings, human-editable
      experiences/         # one JSON file per experience (source of truth)

``resolve_home`` priority: ``--home`` CLI flag > ``EXPERIENCEOS_HOME``
environment variable > ``~/.experienceos``.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

try:  # Python >= 3.11
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib

ENV_HOME = "EXPERIENCEOS_HOME"
CONFIG_FILENAME = "config.toml"


@dataclass
class AIConfig:
    """LLM settings. Secrets are never stored — only the env variable name."""

    provider: str = "openai-compat"
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: float = 60.0
    max_retries: int = 3
    retry_base_seconds: float = 0.5
    retry_max_seconds: float = 8.0
    retry_jitter_seconds: float = 0.25
    retry_time_budget_seconds: float = 30.0
    input_cost_per_million_usd: float = 0.0
    output_cost_per_million_usd: float = 0.0

    def __post_init__(self) -> None:
        self.timeout_seconds = float(self.timeout_seconds)
        self.max_retries = int(self.max_retries)
        self.retry_base_seconds = float(self.retry_base_seconds)
        self.retry_max_seconds = float(self.retry_max_seconds)
        self.retry_jitter_seconds = float(self.retry_jitter_seconds)
        self.retry_time_budget_seconds = float(self.retry_time_budget_seconds)
        self.input_cost_per_million_usd = float(self.input_cost_per_million_usd)
        self.output_cost_per_million_usd = float(self.output_cost_per_million_usd)
        if self.timeout_seconds <= 0:
            raise ValueError("ai.timeout_seconds must be positive")
        if self.max_retries < 0:
            raise ValueError("ai.max_retries must not be negative")
        if min(
            self.retry_base_seconds,
            self.retry_max_seconds,
            self.retry_jitter_seconds,
            self.retry_time_budget_seconds,
            self.input_cost_per_million_usd,
            self.output_cost_per_million_usd,
        ) < 0:
            raise ValueError("AI retry and cost settings must not be negative")


@dataclass
class AppConfig:
    schema_version: int = 1
    ai: AIConfig = field(default_factory=AIConfig)


def resolve_home(override: str | Path | None = None) -> Path:
    if override:
        return Path(override)
    env = os.environ.get(ENV_HOME)
    if env:
        return Path(env)
    return Path.home() / ".experienceos"


def config_path(home: Path) -> Path:
    return Path(home) / CONFIG_FILENAME


def load_config(home: Path) -> AppConfig:
    """Load config.toml, falling back to defaults; unknown keys are ignored."""
    path = config_path(home)
    if not path.exists():
        return AppConfig()
    data: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    ai_data = data.get("ai", {})
    ai_kwargs = {
        f.name: ai_data[f.name] for f in fields(AIConfig) if f.name in ai_data
    }
    return AppConfig(
        schema_version=int(data.get("schema_version", 1)),
        ai=AIConfig(**ai_kwargs),
    )


def save_config(home: Path, config: AppConfig) -> Path:
    """Write config.toml (simple key=value writer; our schema is flat)."""
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    path = config_path(home)
    lines = [
        "# ExperienceOS configuration. Edit freely; delete the file to reset.",
        f"schema_version = {config.schema_version}",
        "",
        "[ai]",
    ]
    for key, value in asdict(config.ai).items():
        if isinstance(value, str):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key} = "{escaped}"')
        elif isinstance(value, bool):
            lines.append(f"{key} = {str(value).lower()}")
        else:
            lines.append(f"{key} = {value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
