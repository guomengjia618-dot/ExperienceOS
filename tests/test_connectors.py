"""Connector framework tests (#006): routing, drafts, registry, import CLI."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from experienceos.cli.app import app
from experienceos.connectors import (
    ExperienceDraft,
    Extractor,
    Registry,
    default_registry,
    parse_source,
)
from experienceos.core.errors import ConnectorError, ValidationError
from experienceos.core.models import SourceOrigin, Status
from experienceos.storage import ExperienceStore

runner = CliRunner()


def full_output(result: Any) -> str:
    try:
        return result.output + (result.stderr or "")
    except (ValueError, AttributeError):  # pragma: no cover - click < 8.2
        return result.output


class FakeExtractor:
    """Minimal protocol implementation used to exercise the framework."""

    def __init__(
        self,
        name: str = "fake",
        schemes: tuple[str, ...] = ("fake",),
        drafts: list[ExperienceDraft] | None = None,
    ) -> None:
        self.name = name
        self._schemes = schemes
        self._drafts = drafts or []
        self.sources_seen: list[str] = []

    def can_handle(self, source: str) -> bool:
        scheme, _ = parse_source(source)
        return scheme in self._schemes

    def extract(self, source: str) -> Iterator[ExperienceDraft]:
        self.sources_seen.append(source)
        yield from self._drafts


@pytest.fixture
def drafts() -> list[ExperienceDraft]:
    return [
        ExperienceDraft.create(
            origin="import",
            ref="fake:source",
            title="Imported A",
            type="personal",
            period={"start": "2024-01"},
        ),
        ExperienceDraft.create(
            origin="import",
            ref="fake:source",
            title="Imported B",
            type="work",
            period={"start": "2023-05", "end": "2024-02"},
        ),
    ]


@pytest.fixture
def fake_connector(drafts: list[ExperienceDraft]) -> Iterator[FakeExtractor]:
    extractor = FakeExtractor(name="fake", schemes=("fake",), drafts=drafts)
    default_registry.register(extractor)
    yield extractor
    default_registry.unregister("fake")


class TestParseSource:
    def test_scheme_and_payload(self) -> None:
        assert parse_source("github:owner/repo") == ("github", "owner/repo")
        assert parse_source("resume:cv.md") == ("resume", "cv.md")

    def test_scheme_is_case_insensitive(self) -> None:
        assert parse_source("GitHub:o/r") == ("github", "o/r")

    def test_dashes_and_underscores_allowed(self) -> None:
        assert parse_source("git-repo_x:/p") == ("git-repo_x", "/p")

    @pytest.mark.parametrize(
        "source",
        ["C:\\Users\\repo", "/home/u/repo", "./rel:ative", "x:path", "no-colon"],
    )
    def test_paths_have_no_scheme(self, source: str) -> None:
        assert parse_source(source) == (None, source)


class TestExperienceDraft:
    def test_create_forces_draft_status_and_provenance(self, drafts) -> None:
        draft = drafts[0]
        assert draft.experience.status is Status.draft
        assert draft.experience.source.origin is SourceOrigin.import_
        assert draft.experience.source.ref == "fake:source"

    def test_create_wraps_validation_errors(self) -> None:
        with pytest.raises(ValidationError):
            ExperienceDraft.create(
                origin="github", title="", type="personal", period={"start": "2024-01"}
            )

    def test_rejects_non_draft_experience(self, make_experience) -> None:
        with pytest.raises(ValidationError):
            ExperienceDraft(make_experience())  # default status is active


class TestRegistry:
    def test_register_and_get(self, drafts) -> None:
        registry = Registry()
        extractor = FakeExtractor(name="one", drafts=drafts)
        registry.register(extractor)
        assert registry.get("one") is extractor
        assert registry.names() == ["one"]
        assert registry.unregister("one") is True
        assert registry.unregister("one") is False

    def test_duplicate_registration_rejected(self) -> None:
        registry = Registry()
        registry.register(FakeExtractor(name="dup"))
        with pytest.raises(ConnectorError, match="already registered"):
            registry.register(FakeExtractor(name="dup"))

    def test_unknown_name_lists_registered(self) -> None:
        registry = Registry()
        registry.register(FakeExtractor(name="known"))
        with pytest.raises(ConnectorError, match="known"):
            registry.get("missing")

    def test_find_handler_routes_by_scheme(self) -> None:
        registry = Registry()
        github = FakeExtractor(name="gh", schemes=("github",))
        resume = FakeExtractor(name="rs", schemes=("resume",))
        registry.register(github)
        registry.register(resume)
        assert registry.find_handler("github:o/r") is github
        assert registry.find_handler("resume:cv.md") is resume

    def test_find_handler_no_match_raises_with_hint(self) -> None:
        registry = Registry()
        registry.register(FakeExtractor(name="gh", schemes=("github",)))
        with pytest.raises(ConnectorError, match="no registered connector"):
            registry.find_handler("resume:cv.md")

    def test_find_handler_deterministic_first_wins(self) -> None:
        registry = Registry()
        first = FakeExtractor(name="first", schemes=("fake",))
        second = FakeExtractor(name="second", schemes=("fake",))
        registry.register(first)
        registry.register(second)
        assert registry.find_handler("fake:x") is first

    def test_fake_extractor_satisfies_protocol(self) -> None:
        assert isinstance(FakeExtractor(), Extractor)


class TestImportCommand:
    def test_import_saves_drafts_with_yes(self, cli_env, fake_connector, drafts) -> None:
        result = runner.invoke(app, ["import", "fake:anything", "--yes"])
        assert result.exit_code == 0, full_output(result)
        assert "2 draft(s)" in result.output
        store = ExperienceStore(cli_env)
        saved = store.list_all()
        assert {e.title for e in saved} == {"Imported A", "Imported B"}
        assert all(e.status is Status.draft for e in saved)
        assert fake_connector.sources_seen == ["fake:anything"]

    def test_import_prompts_and_discards(self, cli_env, fake_connector) -> None:
        result = runner.invoke(app, ["import", "fake:x"], input="n\n")
        assert result.exit_code == 0
        assert "Discarded" in result.output
        assert ExperienceStore(cli_env).list_all() == []

    def test_import_unknown_source_fails_cleanly(self, cli_env) -> None:
        result = runner.invoke(app, ["import", "resume:cv.md"])
        assert result.exit_code == 1
        assert "no registered connector" in full_output(result)

    def test_import_empty_result(self, cli_env) -> None:
        default_registry.register(FakeExtractor(name="empty", schemes=("empty",)))
        try:
            result = runner.invoke(app, ["import", "empty:x", "--yes"])
        finally:
            default_registry.unregister("empty")
        assert result.exit_code == 0
        assert "no drafts" in result.output

    def test_import_never_overwrites(self, cli_env, fake_connector, drafts) -> None:
        ExperienceStore(cli_env).save(drafts[0].experience)  # pre-existing id
        result = runner.invoke(app, ["import", "fake:x", "--yes"])
        assert result.exit_code == 1
        assert "never overwrites" in full_output(result)
        store = ExperienceStore(cli_env)
        assert len(store.list_all()) == 1  # nothing new was written
        assert store.load(drafts[0].experience.id).title == "Imported A"

    def test_import_requires_initialized_home(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("EXPERIENCEOS_HOME", str(tmp_path / "missing"))
        result = runner.invoke(app, ["import", "fake:x", "--yes"])
        assert result.exit_code == 1
        assert "init" in full_output(result)
