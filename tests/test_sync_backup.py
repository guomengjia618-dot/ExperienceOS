"""Sync and backup tests (#021): real git, real zip, no network."""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from experienceos.cli.app import app
from experienceos.storage import ExperienceStore

runner = CliRunner()

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git executable not available"
)


def full(result: Any) -> str:
    return result.output + (result.stderr or "")


@pytest.fixture(autouse=True)
def git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    # commits need an author; env vars work without global git config
    monkeypatch.setenv("GIT_AUTHOR_NAME", "ExperienceOS Tests")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "tests@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "ExperienceOS Tests")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "tests@example.com")


def git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.fixture
def seeded_home(cli_env, make_experience) -> Path:
    store = ExperienceStore(cli_env)
    store.save(make_experience(title="Synced Record"))
    (Path(cli_env) / "config.toml").write_text("schema_version = 1\n", encoding="utf-8")
    return Path(cli_env)


class TestSync:
    def test_requires_repo_or_init_flag(self, seeded_home: Path) -> None:
        result = runner.invoke(app, ["sync"])
        output = full(result)
        assert result.exit_code == 1, output
        assert "--init" in output

    def test_init_then_commit_with_record_count(self, seeded_home: Path) -> None:
        result = runner.invoke(app, ["sync", "--init"])
        output = full(result)
        assert result.exit_code == 0, output
        assert "Initialized" in output
        assert "1 record(s)" in output
        log = git(seeded_home, "log", "-1", "--pretty=%s")
        assert "experienceos sync: 1 record(s)" in log

    def test_second_sync_reports_clean(self, seeded_home: Path) -> None:
        runner.invoke(app, ["sync", "--init"])
        result = runner.invoke(app, ["sync"])
        output = full(result)
        assert result.exit_code == 0, output
        assert "nothing to commit" in output

    def test_push_to_local_bare_remote(self, seeded_home: Path, tmp_path: Path) -> None:
        remote = tmp_path / "remote.git"
        subprocess.run(
            ["git", "init", "--bare", "-b", "main", str(remote)], check=True
        )
        runner.invoke(app, ["sync", "--init"])
        git(seeded_home, "remote", "add", "origin", str(remote))
        result = runner.invoke(app, ["sync", "--push", "origin"])
        output = full(result)
        assert result.exit_code == 0, output
        assert "Pushed" in output
        heads = git(remote, "for-each-ref", "--format=%(refname:short)")
        assert "main" in heads


class TestBackup:
    def test_zip_contains_config_and_records_excludes_noise(
        self, seeded_home: Path, tmp_path: Path
    ) -> None:
        home = seeded_home
        (home / "backup").mkdir()
        (home / "backup" / "old.json").write_text("{}", encoding="utf-8")
        (home / "experiences" / ".scratch.edit.tmp").write_text("{}", encoding="utf-8")
        out = tmp_path / "bundle.zip"
        result = runner.invoke(app, ["backup", "--out", str(out)])
        output = full(result)
        assert result.exit_code == 0, output
        assert "1 file" not in output  # config + record + gitignore-free count
        with zipfile.ZipFile(out) as archive:
            names = archive.namelist()
        assert "config.toml" in names
        assert any(name.startswith("experiences/") for name in names)
        assert not any(".git/" in name for name in names)
        assert not any("backup/" in name for name in names)
        assert not any(name.endswith(".tmp") for name in names)

    def test_default_target_in_cwd(
        self, seeded_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["backup"])
        assert result.exit_code == 0, full(result)
        archives = list(tmp_path.glob("experienceos-backup-*.zip"))
        assert len(archives) == 1
