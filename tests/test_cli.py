"""End-to-end CLI tests via typer's CliRunner (no real terminal needed)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from experienceos.cli.app import app
from experienceos.storage import ExperienceStore

runner = CliRunner()


def full_output(result: Any) -> str:
    """stdout + stderr across click versions (old runners mix them)."""
    try:
        return result.output + (result.stderr or "")
    except (ValueError, AttributeError):  # pragma: no cover - click < 8.2
        return result.output


def seed(cli_env: Any, make_experience, **overrides: Any) -> str:
    store = ExperienceStore(cli_env)
    exp = make_experience(**overrides)
    store.save(exp)
    return exp.id


def first_id(cli_env: Any) -> str:
    return next((Path(cli_env) / "experiences").glob("exp_*.json")).stem


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "experienceos" in result.output


def test_init_creates_home_and_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "fresh-home"
    monkeypatch.setenv("EXPERIENCEOS_HOME", str(home))
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert (home / "experiences").is_dir()
    assert (home / "config.toml").is_file()

    again = runner.invoke(app, ["init"])
    assert again.exit_code == 0
    assert "Already initialized" in again.output


def test_add_wizard_saves_record(cli_env: Any) -> None:
    inputs = "\n".join(
        [
            "Demo App",       # title
            "personal",       # type
            "2024-01",        # start
            "",               # end -> ongoing
            "",               # role
            "A tiny demo",    # description
            "python, typer",  # technologies
            "",               # tags
            "y",              # confirm save
        ]
    )
    result = runner.invoke(app, ["add"], input=inputs)
    assert result.exit_code == 0, full_output(result)
    exp_id = first_id(cli_env)
    store = ExperienceStore(cli_env)
    exp = store.load(exp_id)
    assert exp.title == "Demo App"
    assert exp.period.is_ongoing
    assert exp.technology == ["python", "typer"]
    assert "Saved" in full_output(result)


def test_add_retries_invalid_month(cli_env: Any) -> None:
    inputs = "\n".join(["X", "personal", "2024-13", "2024-01", "", "", "", "", "", "y"])
    result = runner.invoke(app, ["add"], input=inputs)
    assert result.exit_code == 0, full_output(result)
    assert "Expected format YYYY-MM" in full_output(result)


def test_list_and_show(cli_env: Any, make_experience) -> None:
    exp_id = seed(cli_env, make_experience, title="Listed Experience")
    listed = runner.invoke(app, ["list"])
    assert listed.exit_code == 0
    assert "Listed Experience" in listed.output

    shown = runner.invoke(app, ["show", exp_id[:12]])
    assert shown.exit_code == 0
    assert "Listed Experience" in shown.output
    assert exp_id in shown.output




def test_show_uses_ascii_safe_rendering(cli_env: Any, make_experience) -> None:
    exp_id = seed(
        cli_env,
        make_experience,
        contribution=["Built the connector"],
        evidence=[{"kind": "repo", "location": "https://github.com/octo/demo"}],
    )

    shown = runner.invoke(app, ["show", exp_id[:12]])

    assert shown.exit_code == 0
    assert "- Built the connector" in shown.output
    assert "repo: https://github.com/octo/demo" in shown.output
    assert "manual | created_by user" in shown.output
    assert "•" not in shown.output
    assert "·" not in shown.output


def test_search_ranks_and_filters(cli_env: Any, make_experience) -> None:
    seed(cli_env, make_experience, title="Ranking Star", tags=["searchable"])
    seed(cli_env, make_experience, title="Other", description="mentions ranking deep inside")

    hit = runner.invoke(app, ["search", "ranking"])
    assert hit.exit_code == 0
    assert "Ranking Star" in hit.output
    assert "Other" in hit.output

    only = runner.invoke(app, ["search", "ranking", "--tag", "searchable"])
    assert only.exit_code == 0
    assert "Ranking Star" in only.output
    assert "Other" not in only.output


def test_set_updates_and_validates(cli_env: Any, make_experience) -> None:
    exp_id = seed(cli_env, make_experience)
    ok = runner.invoke(app, ["set", exp_id[:12], "title", "Renamed"])
    assert ok.exit_code == 0, full_output(ok)
    assert ExperienceStore(cli_env).load(exp_id).title == "Renamed"

    ok_period = runner.invoke(app, ["set", exp_id[:12], "period.start", "2023-09"])
    assert ok_period.exit_code == 0
    assert ExperienceStore(cli_env).load(exp_id).period.start == "2023-09"

    bad = runner.invoke(app, ["set", exp_id[:12], "status", "bogus"])
    assert bad.exit_code == 1
    assert "error" in full_output(bad)

    unknown = runner.invoke(app, ["set", exp_id[:12], "nope", "x"])
    assert unknown.exit_code == 1


def test_add_item_appends_to_list_fields(cli_env: Any, make_experience) -> None:
    exp_id = seed(cli_env, make_experience)
    result = runner.invoke(
        app, ["add-item", exp_id[:12], "contribution", "Did X", "Did Y"]
    )
    assert result.exit_code == 0, full_output(result)
    exp = ExperienceStore(cli_env).load(exp_id)
    assert exp.contribution == ["Did X", "Did Y"]

    bad = runner.invoke(app, ["add-item", exp_id[:12], "title", "nope"])
    assert bad.exit_code == 1


def test_delete_confirm_and_yes(cli_env: Any, make_experience) -> None:
    exp_id = seed(cli_env, make_experience)

    cancelled = runner.invoke(app, ["delete", exp_id[:12]], input="n\n")
    assert cancelled.exit_code == 0
    assert ExperienceStore(cli_env).exists(exp_id)

    deleted = runner.invoke(app, ["delete", exp_id[:12], "--yes"])
    assert deleted.exit_code == 0
    assert not ExperienceStore(cli_env).exists(exp_id)


def test_stats_reports_counts(cli_env: Any, make_experience) -> None:
    seed(cli_env, make_experience, title="A", technology=["Python"])
    seed(cli_env, make_experience, title="B", technology=["Python", "Rust"])
    result = runner.invoke(app, ["stats"])
    assert result.exit_code == 0
    assert "2 experiences" in result.output
    assert "python" in result.output.lower()


def test_validate_detects_corrupt_files(cli_env: Any, make_experience) -> None:
    seed(cli_env, make_experience)
    broken = Path(cli_env) / "experiences" / "exp_broken0000000000000000.json"
    broken.write_text("{ nope", encoding="utf-8")

    result = runner.invoke(app, ["validate"])
    assert result.exit_code == 1
    assert "exp_broken" in full_output(result)

    broken.unlink()
    ok = runner.invoke(app, ["validate"])
    assert ok.exit_code == 0
    assert "valid" in ok.output


def test_show_unknown_id_fails_cleanly(cli_env: Any) -> None:
    result = runner.invoke(app, ["show", "exp_zzzz"])
    assert result.exit_code == 1
    assert "error" in full_output(result)


def test_uninitialized_home_fails_with_hint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EXPERIENCEOS_HOME", str(tmp_path / "missing"))
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 1
    assert "init" in full_output(result)


def test_path_command(cli_env: Any) -> None:
    result = runner.invoke(app, ["path"])
    assert result.exit_code == 0
    assert str(cli_env) in result.output


@pytest.fixture
def fake_editor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """An 'editor' that appends ' (edited)' to the record's title."""
    script = tmp_path / "fake_editor.py"
    script.write_text(
        "import json, sys\n"
        "path = sys.argv[1]\n"
        "with open(path, encoding='utf-8') as fh:\n"
        "    data = json.load(fh)\n"
        "data['title'] = data['title'] + ' (edited)'\n"
        "with open(path, 'w', encoding='utf-8') as fh:\n"
        "    json.dump(data, fh, indent=2)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EDITOR", f'"{sys.executable}" "{script}"')
    return script


def test_edit_roundtrip_through_editor(cli_env: Any, make_experience, fake_editor: Path) -> None:
    exp_id = seed(cli_env, make_experience, title="Before Edit")
    result = runner.invoke(app, ["edit", exp_id[:12]])
    assert result.exit_code == 0, full_output(result)
    assert ExperienceStore(cli_env).load(exp_id).title == "Before Edit (edited)"
    # scratch file cleaned up after a successful save
    assert not (Path(cli_env) / "experiences" / f".{exp_id}.edit.tmp").exists()


def test_edit_rejects_invalid_json(
    cli_env: Any, make_experience, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exp_id = seed(cli_env, make_experience)
    script = tmp_path / "breaking_editor.py"
    script.write_text(
        "import sys\n"
        "open(sys.argv[1], 'w', encoding='utf-8').write('{ broken')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EDITOR", f'"{sys.executable}" "{script}"')

    result = runner.invoke(app, ["edit", exp_id[:12]])
    assert result.exit_code == 1
    assert "Invalid JSON" in full_output(result)
    # the original record is untouched and the edits are kept for retry
    assert ExperienceStore(cli_env).load(exp_id).title == "Demo Project"
    assert (Path(cli_env) / "experiences" / f".{exp_id}.edit.tmp").exists()
