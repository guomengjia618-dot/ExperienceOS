"""Plugin discovery tests (#019): entry-point loading with fault isolation."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any

import pytest
from typer.testing import CliRunner

from experienceos.connectors.registry import default_registry
from experienceos.core.errors import ConnectorError
from experienceos.core.models import SourceOrigin
from experienceos.plugins import (
    CONNECTORS_GROUP,
    PluginInfo,
    load_plugins,
    plugin_summary,
)
from experienceos.storage import ExperienceStore

runner = CliRunner()


class FakeEntryPoint:
    def __init__(
        self,
        name: str,
        target: str,
        obj: Any = None,
        load_error: Exception | None = None,
        dist_name: str | None = None,
        version: str | None = None,
    ) -> None:
        self.name = name
        self.value = target
        self._obj = obj
        self._load_error = load_error
        self._dist_name = dist_name
        self._version = version
        self.group = CONNECTORS_GROUP

    @property
    def dist(self) -> Any:
        if self._dist_name is None:
            return None
        return self

    @property
    def metadata(self) -> dict[str, str]:
        return {"Name": self._dist_name or ""}

    @property
    def version(self) -> str | None:
        return self._version

    def load(self) -> Any:
        if self._load_error is not None:
            raise self._load_error
        return self._obj


@dataclass
class FakeExtractor:
    name: str = "fake-importer"
    seen: list = field(default_factory=list)

    def can_handle(self, source: str) -> bool:
        return source.startswith("fake:")

    def extract(self, source: str) -> Any:
        from experienceos.connectors.base import ExperienceDraft

        yield ExperienceDraft.create(
            origin=SourceOrigin.import_, title="From plugin",
            type="other", period={"start": "2024-01"},
        )


def fake_entry_points(monkeypatch: pytest.MonkeyPatch, eps: list[Any]) -> None:
    module = importlib.import_module("experienceos.plugins")
    monkeypatch.setattr(
        module, "entry_points", lambda group: [ep for ep in eps if ep.group == group]
    )


class TestLoadPlugins:
    def test_registers_third_party_connector(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_entry_points(
            monkeypatch,
            [FakeEntryPoint("fake-importer", "fakepkg:FakeExtractor", FakeExtractor,
                            dist_name="fakepkg", version="1.2.3")],
        )
        try:
            infos = load_plugins()
            assert len(infos) == 1
            assert infos[0].state == "registered"
            assert infos[0].version == "1.2.3"
            assert default_registry.get("fake-importer") is not None
        finally:
            default_registry.unregister("fake-importer")

    def test_broken_plugin_is_reported_not_raised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_entry_points(
            monkeypatch,
            [FakeEntryPoint("broken", "brokenpkg:Thing",
                            load_error=ImportError("no module named brokenpkg"))],
        )
        infos = load_plugins()
        assert infos[0].state == "failed"
        assert "no module named brokenpkg" in (infos[0].error or "")
        with pytest.raises(ConnectorError, match="broken"):
            default_registry.get("broken")

    def test_builtin_entry_point_skips_when_already_registered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from experienceos.connectors import ResumeExtractor  # already registered

        fake_entry_points(
            monkeypatch,
            [FakeEntryPoint("resume", "experienceos.connectors.resume:ResumeExtractor",
                            ResumeExtractor, dist_name="experienceos", version="0.5.0")],
        )
        infos = load_plugins()
        assert infos[0].state == "already-present"

    def test_plugin_connector_really_imports(
        self, cli_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_entry_points(
            monkeypatch,
            [FakeEntryPoint("fake-importer", "fakepkg:FakeExtractor", FakeExtractor)],
        )
        try:
            cli_module = importlib.import_module("experienceos.cli.app")
            result = runner.invoke(
                cli_module.app, ["import", "fake:thing", "--yes"]
            )
            output = result.output + (result.stderr or "")
            assert result.exit_code == 0, output
            assert any(exp.title == "From plugin" for exp in ExperienceStore(cli_env).list_all())
        finally:
            default_registry.unregister("fake-importer")


class TestPluginSummary:
    def test_rows_render_state_and_source(self) -> None:
        info = PluginInfo(
            name="x", group=CONNECTORS_GROUP, target="x:Y",
            version="2.0", dist="xpkg", state="failed", error="boom",
        )
        rows = plugin_summary([info])
        assert rows[0]["group"] == "connectors"
        assert rows[0]["state"] == "failed"


class TestCliList:
    def test_plugins_list_shows_registered_plugin(
        self, cli_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cli_module = importlib.import_module("experienceos.cli.app")
        fake_entry_points(
            monkeypatch,
            [FakeEntryPoint("fake-importer", "fakepkg:FakeExtractor", FakeExtractor,
                            dist_name="fakepkg", version="1.2.3")],
        )
        try:
            result = runner.invoke(cli_module.app, ["plugins", "list"])
            assert result.exit_code == 0, result.output
            assert "fake-importer" in result.output
            assert "fakepkg" in result.output
        finally:
            default_registry.unregister("fake-importer")

    def test_plugins_list_reports_failure(
        self, cli_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cli_module = importlib.import_module("experienceos.cli.app")
        fake_entry_points(
            monkeypatch,
            [FakeEntryPoint("broken", "brokenpkg:Thing",
                            load_error=ImportError("no module named brokenpkg"))],
        )
        result = runner.invoke(cli_module.app, ["plugins", "list"])
        output = result.output + (result.stderr or "")
        assert result.exit_code == 0, output  # a broken plugin never breaks the CLI
        assert "failed" in output
        assert "no module named brokenpkg" in output
