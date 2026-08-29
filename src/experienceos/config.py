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

from experienceos.core.errors import ValidationError

ENV_HOME = "EXPERIENCEOS_HOME"
CONFIG_FILENAME = "config.toml"
DEFAULT_AI_TIMEOUT = 60.0


@dataclass
class AIConfig:
    """LLM settings. Secrets are never stored — only the env variable name."""

    provider: str = "openai-compat"
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    api_key_env: str = "OPENAI_API_KEY"
    timeout: float = DEFAULT_AI_TIMEOUT


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
    config = AppConfig(
        schema_version=int(data.get("schema_version", 1)),
        ai=AIConfig(**ai_kwargs),
    )
    config.ai.timeout = _coerce_timeout(config.ai.timeout)
    return config


def _coerce_timeout(value: Any) -> float:
    """Accept hand-edited numeric strings ("30") for the timeout field."""
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            f"config [ai] timeout must be a number of seconds, got {value!r}"
        ) from exc
    if timeout <= 0:
        raise ValidationError(f"config [ai] timeout must be positive, got {timeout}")
    return timeout


def _format_toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return f'"{value}"'


def save_config(home: Path, config: AppConfig) -> Path:
    """Write config.toml (flat sections; strings quoted, numbers bare)."""
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
        lines.append(f"{key} = {_format_toml_value(value)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
