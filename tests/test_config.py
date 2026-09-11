"""Configuration tests: resolution priority and TOML round-trip."""

from __future__ import annotations

from pathlib import Path

from experienceos.config import AIConfig, AppConfig, load_config, resolve_home, save_config


def test_default_home_when_nothing_set(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("EXPERIENCEOS_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert resolve_home() == tmp_path / ".experienceos"


def test_env_var_overrides_home(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EXPERIENCEOS_HOME", str(tmp_path / "from-env"))
    assert resolve_home() == tmp_path / "from-env"


def test_explicit_override_wins(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EXPERIENCEOS_HOME", str(tmp_path / "from-env"))
    assert resolve_home(tmp_path / "explicit") == tmp_path / "explicit"


def test_config_roundtrip(tmp_path) -> None:
    config = AppConfig(
        ai=AIConfig(
            model="glm-4.7",
            api_key_env="GLM_API_KEY",
            max_retries=5,
            timeout_seconds=12.5,
            input_cost_per_million_usd=0.15,
        )
    )
    save_config(tmp_path, config)
    loaded = load_config(tmp_path)
    assert loaded.ai.model == "glm-4.7"
    assert loaded.ai.api_key_env == "GLM_API_KEY"
    assert loaded.ai.max_retries == 5
    assert loaded.ai.timeout_seconds == 12.5
    assert loaded.ai.input_cost_per_million_usd == 0.15
    assert loaded.schema_version == 1


def test_load_missing_config_returns_defaults(tmp_path) -> None:
    assert load_config(tmp_path / "nowhere") == AppConfig()


def test_unknown_keys_are_ignored(tmp_path) -> None:
    tmp_path.joinpath("config.toml").write_text(
        'schema_version = 1\n[ai]\nmodel = "m"\nfuture_key = "x"\n', encoding="utf-8"
    )
    loaded = load_config(tmp_path)
    assert loaded.ai.model == "m"


def test_timeout_roundtrips_as_bare_number(tmp_path) -> None:
    config = AppConfig(ai=AIConfig(timeout_seconds=12.5))
    save_config(tmp_path, config)
    raw = tmp_path.joinpath("config.toml").read_text(encoding="utf-8")
    assert "timeout_seconds = 12.5" in raw  # unquoted, so TOML sees a float
    assert load_config(tmp_path).ai.timeout_seconds == 12.5


def test_hand_edited_string_timeout_is_coerced(tmp_path) -> None:
    tmp_path.joinpath("config.toml").write_text(
        '[ai]\ntimeout_seconds = "30"\n', encoding="utf-8"
    )
    assert load_config(tmp_path).ai.timeout_seconds == 30.0


def test_invalid_timeout_fails_with_validation_error(tmp_path) -> None:
    import pytest

    from experienceos.core.errors import ValidationError

    tmp_path.joinpath("config.toml").write_text(
        '[ai]\ntimeout_seconds = "soon"\n', encoding="utf-8"
    )
    with pytest.raises(ValidationError, match=r"invalid \[ai\]"):
        load_config(tmp_path)
