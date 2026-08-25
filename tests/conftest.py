"""Shared fixtures for the ExperienceOS test suite."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest

from experienceos.core.models import Experience
from experienceos.storage import ExperienceStore


@pytest.fixture
def home(tmp_path: Any) -> Any:
    """An initialized home directory (experiences/ exists, no config)."""
    experiences = tmp_path / "experiences"
    experiences.mkdir()
    return tmp_path


@pytest.fixture
def store(home: Any) -> ExperienceStore:
    return ExperienceStore(home)


@pytest.fixture
def make_experience() -> Callable[..., Experience]:
    """Factory building a valid minimal Experience with overrides."""

    def _make(**overrides: Any) -> Experience:
        data: dict[str, Any] = {
            "title": "Demo Project",
            "type": "personal",
            "period": {"start": "2024-01", "end": "2024-06"},
        }
        data.update(overrides)
        return Experience.new(**data)

    return _make


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch, home: Any) -> Iterator[Any]:
    """Point the CLI at the temp home and yield it."""
    monkeypatch.setenv("EXPERIENCEOS_HOME", str(home))
    yield home
