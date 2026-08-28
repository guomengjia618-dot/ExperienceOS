"""Local git repository connector tests (#008): real tmp-repo integration."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from experienceos.cli.app import app
from experienceos.connectors import (
    AuthoredExtractor,
    Extractor,
    GitRepoError,
    GitRepoExtractor,
    default_registry,
)
from experienceos.core.errors import ConnectorError
from experienceos.core.models import EvidenceKind, SourceOrigin, Status
from experienceos.storage import ExperienceStore

runner = CliRunner()

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git executable not available"
)

ALICE = "alice@example.com"
BOB = "bob@example.com"


def git(path: Path, *args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, **(env or {})},
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def commit(
    repo: Path,
    message: str,
    files: dict[str, str],
    date: str,
    author: tuple[str, str] | None = None,
) -> None:
    for name, content in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    git(repo, "add", "-A")
    extra: list[str] = []
    env: dict[str, str] = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    if author is not None:
        extra = ["--author", f"{author[0]} <{author[1]}>"]
    git(repo, "commit", "-m", message, *extra, env=env)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A three-commit repository: two by Alice (repo config), one by Bob."""
    path = tmp_path / "proj"
    path.mkdir()
    git(path.parent, "-c", "init.defaultBranch=main", "init", str(path))
    git(path, "config", "user.name", "Alice")
    git(path, "config", "user.email", ALICE)
    commit(path, "init search engine", {"engine.py": "x = 1\n" * 10}, "2024-01-15T10:00:00+0000")
    commit(
        path,
        "bob notes ideas",
        {"ideas.txt": "think\n"},
        "2024-03-20T10:00:00+0000",
        author=("Bob", BOB),
    )
    commit(
        path,
        "add ranker module",
        {"ranker.py": "y = 2\n" * 30},
        "2024-06-01T10:00:00+0000",
    )
    return path


@pytest.fixture
def extractor() -> GitRepoExtractor:
    return GitRepoExtractor()


class TestCanHandle:
    def test_git_directory_claims_bare_path(
        self, repo: Path, extractor: GitRepoExtractor
    ) -> None:
        assert extractor.can_handle(str(repo)) is True

    def test_git_repo_scheme(self, repo: Path, extractor: GitRepoExtractor) -> None:
        assert extractor.can_handle(f"git-repo:{repo}") is True

    def test_rejects_plain_directory(
        self, tmp_path: Path, extractor: GitRepoExtractor
    ) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        assert extractor.can_handle(str(plain)) is False

    def test_rejects_missing_path(
        self, tmp_path: Path, extractor: GitRepoExtractor
    ) -> None:
        assert extractor.can_handle(str(tmp_path / "missing")) is False

    def test_rejects_other_schemes(self, extractor: GitRepoExtractor) -> None:
        assert extractor.can_handle("github:owner/repo") is False
        assert extractor.can_handle("resume:cv.md") is False

    def test_accepts_gitfile_worktrees_and_submodules(
        self, tmp_path: Path, extractor: GitRepoExtractor
    ) -> None:
        path = tmp_path / "linked"
        path.mkdir()
        (path / ".git").write_text("gitdir: ../elsewhere/.git\n", encoding="utf-8")
        assert extractor.can_handle(str(path)) is True


class TestExtract:
    def test_protocol_conformance(self, extractor: GitRepoExtractor) -> None:
        assert isinstance(extractor, Extractor)
        assert isinstance(extractor, AuthoredExtractor)
        assert default_registry.get("git-repo") is not None

    def test_repo_config_email_identifies_author(
        self, repo: Path, extractor: GitRepoExtractor
    ) -> None:
        draft = next(extractor.extract(str(repo)))
        exp = draft.experience
        assert exp.status is Status.draft
        assert exp.source.origin is SourceOrigin.git_repo
        assert exp.source.ref == str(repo)
        assert exp.title == "proj"
        assert exp.type.value == "personal"
        assert exp.period.start == "2024-01" and exp.period.end == "2024-06"
        assert exp.technology == ["Python"]
        assert "add ranker module" in exp.contribution
        assert "init search engine" in exp.contribution
        assert "bob notes ideas" not in exp.contribution
        assert exp.tags == ["git"]

    def test_context_and_result_are_factual(self, repo: Path, extractor: GitRepoExtractor) -> None:
        exp = next(extractor.extract(str(repo))).experience
        assert f"Local git activity for {ALICE}: 2 commit(s) out of 3 total." in exp.context
        assert "Authored 2 of 3 commits" in exp.result
        # churn per Alice commit: +10 and +30 -> median 20
        assert any("Median change size: 20 lines per commit" in r for r in exp.result)
        assert any("Languages by tracked files: Python 100%" in r for r in exp.result)

    def test_repo_evidence_present_without_remote(
        self, repo: Path, extractor: GitRepoExtractor
    ) -> None:
        exp = next(extractor.extract(str(repo))).experience
        kinds = {(e.kind, e.location) for e in exp.evidence}
        assert (EvidenceKind.repo, str(repo)) in kinds
        assert all(kind is not EvidenceKind.url for kind, _ in kinds)

    def test_explicit_author_attribute(self, repo: Path, extractor: GitRepoExtractor) -> None:
        exp = next(extractor.extract_for_author(str(repo), BOB)).experience
        assert f"Local git activity for {BOB}: 1 commit(s) out of 3 total." in exp.context
        assert exp.contribution == ["bob notes ideas"]
        assert "Authored 1 of 3 commits" in exp.result

    def test_author_pattern_matches_name_too(self, repo: Path, extractor: GitRepoExtractor) -> None:
        exp = next(extractor.extract_for_author(str(repo), "Bob")).experience
        assert "Authored 1 of 3 commits" in exp.result

    def test_github_remote_evidence_https(self, repo: Path, extractor: GitRepoExtractor) -> None:
        git(repo, "remote", "add", "origin", "https://github.com/alice/proj.git")
        exp = next(extractor.extract(str(repo))).experience
        urls = [e for e in exp.evidence if e.kind is EvidenceKind.url]
        assert [u.location for u in urls] == ["https://github.com/alice/proj"]

    def test_github_remote_evidence_ssh(self, repo: Path, extractor: GitRepoExtractor) -> None:
        git(repo, "remote", "add", "origin", f"git@github.com:alice/{repo.name}.git")
        exp = next(extractor.extract(str(repo))).experience
        assert any(e.location == f"https://github.com/alice/{repo.name}" for e in exp.evidence)

    def test_non_github_remote_is_ignored(self, repo: Path, extractor: GitRepoExtractor) -> None:
        git(repo, "remote", "add", "origin", "https://gitlab.com/alice/proj.git")
        exp = next(extractor.extract(str(repo))).experience
        assert all(e.kind is not EvidenceKind.url for e in exp.evidence)

    def test_contributions_capped_with_context_note(
        self, tmp_path: Path, extractor: GitRepoExtractor
    ) -> None:
        path = tmp_path / "busy"
        path.mkdir()
        git(path.parent, "-c", "init.defaultBranch=main", "init", str(path))
        git(path, "config", "user.name", "Alice")
        git(path, "config", "user.email", ALICE)
        for i in range(35):
            commit(path, f"commit number {i}", {f"f{i}.txt": "x\n"}, "2024-05-01T10:00:00+0000")
        exp = next(extractor.extract(str(path))).experience
        assert len(exp.contribution) == 30
        assert "latest 30 commit subjects" in exp.context


class TestErrors:
    def test_non_git_directory_readable_error(
        self, tmp_path: Path, extractor: GitRepoExtractor
    ) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        with pytest.raises(GitRepoError, match="not a git repository"):
            next(extractor.extract(str(plain)))

    def test_directory_without_git_raises_when_extracting(
        self, tmp_path: Path, extractor: GitRepoExtractor
    ) -> None:
        # can_handle lies for a fake .git file; extract must fail readably.
        path = tmp_path / "fake"
        path.mkdir()
        (path / ".git").write_text("gitdir: ../missing\n", encoding="utf-8")
        with pytest.raises(ConnectorError, match="rev-parse failed"):
            next(extractor.extract(str(path)))

    def test_empty_repository_readable_error(
        self, tmp_path: Path, extractor: GitRepoExtractor
    ) -> None:
        path = tmp_path / "empty"
        path.mkdir()
        git(path.parent, "-c", "init.defaultBranch=main", "init", str(path))
        with pytest.raises(GitRepoError, match="no commits yet"):
            next(extractor.extract(str(path)))

    def test_unknown_author_readable_error(
        self, repo: Path, extractor: GitRepoExtractor
    ) -> None:
        with pytest.raises(GitRepoError, match="no commits found for author"):
            next(extractor.extract_for_author(str(repo), "nobody@nowhere.io"))

    def test_missing_config_email_readable_error(
        self, tmp_path: Path, extractor: GitRepoExtractor, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        neutral = tmp_path / "neutral.gitconfig"
        neutral.touch()
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(neutral))
        monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(neutral))
        fresh = tmp_path / "noemail"
        fresh.mkdir()
        git(tmp_path, "-c", "init.defaultBranch=main", "init", str(fresh))
        git(fresh, "config", "user.name", "Alice")
        git(fresh, "config", "user.email", ALICE)
        commit(fresh, "work", {"a.py": "1\n"}, "2024-02-02T10:00:00+0000")
        git(fresh, "config", "--unset", "user.email")
        with pytest.raises(GitRepoError, match=r"user\.email"):
            next(extractor.extract(str(fresh)))

    def test_missing_git_binary_readable_error(
        self, repo: Path, extractor: GitRepoExtractor, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import experienceos.connectors.gitrepo as module

        monkeypatch.setattr(module, "GIT_BINARY", "git-experienceos-missing")
        with pytest.raises(GitRepoError, match="git executable not found"):
            next(extractor.extract(str(repo)))


class TestRobustness:
    def test_shallow_clone_does_not_crash(
        self, repo: Path, tmp_path: Path, extractor: GitRepoExtractor
    ) -> None:
        clone = tmp_path / "shallow"
        result = subprocess.run(
            ["git", "clone", "--depth", "1", repo.as_uri(), str(clone)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        exp = next(extractor.extract_for_author(str(clone), ALICE)).experience
        assert exp.period.start == "2024-06" and exp.period.end == "2024-06"
        assert "Authored 1 of 1 commits" in exp.result

    def test_submodule_parent_and_child(
        self, repo: Path, tmp_path: Path, extractor: GitRepoExtractor
    ) -> None:
        parent = tmp_path / "parent"
        parent.mkdir()
        git(parent.parent, "-c", "init.defaultBranch=main", "init", str(parent))
        git(parent, "config", "user.name", "Alice")
        git(parent, "config", "user.email", ALICE)
        git(
            parent,
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            str(repo),
            "vendor/proj",
        )
        git(parent, "commit", "-m", "add submodule")
        # child: .git is a file (gitlink layout) and still analyzes cleanly
        child = parent / "vendor" / "proj"
        assert extractor.can_handle(str(child)) is True
        exp = next(extractor.extract_for_author(str(child), ALICE)).experience
        assert exp.title == "proj"
        # parent: gitlink entry does not break language stats or logging
        parent_exp = next(extractor.extract(str(parent))).experience
        assert "Authored 1 of 1 commits" in parent_exp.result


class TestCliImport:
    def test_import_local_repo_saves_draft(self, cli_env, repo: Path) -> None:
        result = runner.invoke(app, ["import", str(repo), "--yes"])
        output = result.output + str(getattr(result, "stderr", "") or "")
        assert result.exit_code == 0, output
        assert "1 draft(s)" in output
        saved = ExperienceStore(cli_env).list_all()
        assert len(saved) == 1
        assert saved[0].source.origin is SourceOrigin.git_repo
        assert saved[0].status is Status.draft

    def test_import_with_author_option(self, cli_env, repo: Path) -> None:
        result = runner.invoke(app, ["import", str(repo), "--author", BOB, "--yes"])
        assert result.exit_code == 0
        saved = ExperienceStore(cli_env).list_all()
        assert len(saved) == 1
        assert f"{BOB}: 1 commit(s)" in saved[0].context
