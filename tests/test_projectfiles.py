"""Project-files connector tests (#028): plain project folders -> drafts."""

from __future__ import annotations

from pathlib import Path

import pytest

from experienceos.connectors import default_registry
from experienceos.connectors.base import parse_source
from experienceos.connectors.projectfiles import (
    JUNK_DIRS,
    ProjectFilesError,
    ProjectFilesExtractor,
)
from experienceos.core.models import SourceOrigin, Status


@pytest.fixture
def extractor() -> ProjectFilesExtractor:
    return ProjectFilesExtractor()


def _make_project(tmp_path: Path) -> Path:
    root = tmp_path / "my-tool"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "src" / "util.py").write_text("", encoding="utf-8")
    (root / "app.js").write_text("console.log(1)\n", encoding="utf-8")
    (root / "README.md").write_text(
        "# My Tool\n\nA tiny utility for demoing the connector.\n",
        encoding="utf-8",
    )
    return root


class TestRouting:
    def test_claims_plain_directories(self, extractor, tmp_path) -> None:
        root = tmp_path / "plain"
        root.mkdir()
        assert extractor.can_handle(str(root)) is True

    def test_leaves_git_repositories_to_git_repo_connector(
        self, extractor, tmp_path
    ) -> None:
        root = tmp_path / "repo"
        (root / ".git").mkdir(parents=True)
        assert extractor.can_handle(str(root)) is False

    def test_explicit_scheme_claims_even_git_directories(
        self, extractor, tmp_path
    ) -> None:
        root = tmp_path / "repo"
        (root / ".git").mkdir(parents=True)
        assert extractor.can_handle(f"project-files:{root}") is True

    def test_rejects_files_and_missing_paths(self, extractor, tmp_path) -> None:
        a_file = tmp_path / "cv.md"
        a_file.write_text("x", encoding="utf-8")
        assert extractor.can_handle(str(a_file)) is False
        assert extractor.can_handle(str(tmp_path / "missing")) is False

    def test_foreign_scheme_rejected(self, extractor) -> None:
        assert extractor.can_handle("github:owner/repo") is False

    def test_registered_in_default_registry(self) -> None:
        assert default_registry.get("project-files") is not None


class TestExtraction:
    def test_draft_facts(self, extractor, tmp_path) -> None:
        root = _make_project(tmp_path)
        drafts = list(extractor.extract(str(root)))
        assert len(drafts) == 1
        exp = drafts[0].experience
        assert exp.status is Status.draft
        assert exp.title == "my-tool"
        assert exp.source.origin is SourceOrigin.project_files
        assert exp.source.ref == str(root.resolve())
        # languages come from the shared curated map (README counts as Markdown);
        # tied counts order by scan order, so compare as a set
        assert set(exp.technology) == {"Python", "JavaScript", "Markdown"}
        assert exp.technology[0] == "Python"  # 2 files, strictly most common
        # the README excerpt is verbatim, never invented
        assert "A tiny utility for demoing the connector." in exp.description
        # no version control -> no honest timeline, and no contribution claims
        assert exp.period.start == "1970-01"
        assert exp.period.end is None
        assert set(exp.tags) == {"project-files", "undated"}
        assert exp.contribution == []
        assert any(e.kind.value == "file" for e in exp.evidence)

    def test_context_counts_are_factual(self, extractor, tmp_path) -> None:
        root = _make_project(tmp_path)
        exp = next(iter(extractor.extract(str(root)))).experience
        assert "4 recognized source file(s)" in exp.context
        assert "3 language(s)" in exp.context

    def test_junk_directories_are_pruned(self, extractor, tmp_path) -> None:
        root = tmp_path / "with-junk"
        (root / "node_modules" / "left-pad").mkdir(parents=True)
        (root / "node_modules" / "left-pad" / "index.js").write_text("x", encoding="utf-8")
        (root / "__pycache__").mkdir()
        (root / "__pycache__" / "a.cpython-312.pyc").write_text("x", encoding="utf-8")
        (root / "main.py").write_text("x", encoding="utf-8")
        exp = next(iter(extractor.extract(str(root)))).experience
        assert exp.technology == ["Python"]

    def test_no_recognizable_files_fails_readably(self, extractor, tmp_path) -> None:
        root = tmp_path / "empty-ish"
        root.mkdir()
        (root / "blob.bin").write_bytes(b"\x00\x01")
        with pytest.raises(ProjectFilesError, match="no recognizable source files"):
            list(extractor.extract(str(root)))

    def test_missing_directory_readable_error(self, extractor, tmp_path) -> None:
        with pytest.raises(ProjectFilesError, match="not a directory"):
            list(extractor.extract(str(tmp_path / "nope")))

    def test_undated_period_is_explicit_not_invented(
        self, extractor, tmp_path
    ) -> None:
        root = _make_project(tmp_path)
        exp = next(iter(extractor.extract(str(root)))).experience
        assert exp.period.start != "" and exp.period.start == "1970-01"


def test_junk_dirs_cover_common_build_and_vcs_names() -> None:
    for name in (".git", "node_modules", "__pycache__", ".venv", "dist", "build"):
        assert name in JUNK_DIRS


def test_parse_source_keeps_windows_drive_paths() -> None:
    scheme, payload = parse_source(r"C:\projects\tool")
    assert scheme is None
    assert payload == r"C:\projects\tool"
