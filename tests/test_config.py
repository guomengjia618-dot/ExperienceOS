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
    config = AppConfig(ai=AIConfig(model="glm-4.7", api_key_env="GLM_API_KEY"))
    save_config(tmp_path, config)
    loaded = load_config(tmp_path)
    assert loaded.ai.model == "glm-4.7"
    assert loaded.ai.api_key_env == "GLM_API_KEY"
    assert loaded.schema_version == 1


def test_load_missing_config_returns_defaults(tmp_path) -> None:
    assert load_config(tmp_path / "nowhere") == AppConfig()


def test_unknown_keys_are_ignored(tmp_path) -> None:
    tmp_path.joinpath("config.toml").write_text(
        'schema_version = 1\n[ai]\nmodel = "m"\nfuture_key = "x"\n', encoding="utf-8"
    )
    loaded = load_config(tmp_path)
    assert loaded.ai.model == "m"
