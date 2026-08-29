"""Schema migration framework tests (#020): the v1 -> v2 drill."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import experienceos.core.models as models_module
from experienceos.cli.app import app
from experienceos.core.errors import StorageError, ValidationError
from experienceos.storage import ExperienceStore
from experienceos.storage.migrations import (
    MIGRATIONS,
    needs_migration,
    register_migration,
    run_migrations,
)

runner = CliRunner()


@pytest.fixture
def v2_world(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Drill: imagine v2 adds a required `source.ref`-like provenance note.

    Registers an ad-hoc v1 -> v2 step and raises the build's schema
    version — exactly the path a real schema change would take.
    """
    monkeypatch.setattr(models_module, "SCHEMA_VERSION", 2)
    steps: list[int] = []

    @register_migration(1)
    def _v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
        steps.append(1)
        data.setdefault("reflection", "imported before schema v2")
        return data

    yield steps
    MIGRATIONS.pop(1, None)


def make_raw_record(tmp_path: Path, schema_version: int = 1) -> Path:
    store = ExperienceStore(tmp_path)
    store.experiences_dir.mkdir(parents=True, exist_ok=True)
    exp = ExperienceStore(tmp_path)  # noqa: F841 - layout only
    path = store.experiences_dir / "exp_01H00000000000000000000000.json"
    data = {
        "schema_version": schema_version,
        "id": "exp_01H00000000000000000000000",
        "title": "Ancient Record",
        "type": "personal",
        "period": {"start": "2020-01", "end": "2020-12"},
    }
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


class TestRunMigrations:
    def test_applies_pending_steps_in_order(self, v2_world) -> None:
        data = {"schema_version": 1, "title": "x"}
        migrated, applied = run_migrations(data)
        assert migrated["schema_version"] == 2
        assert applied == [2]
        assert migrated["reflection"] == "imported before schema v2"
        assert v2_world == [1]

    def test_current_version_is_a_noop(self, v2_world) -> None:
        data = {"schema_version": 2, "title": "x"}
        migrated, applied = run_migrations(data)
        assert applied == []
        assert migrated == {"schema_version": 2, "title": "x"}  # untouched
        assert v2_world == []

    def test_missing_step_is_actionable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(models_module, "SCHEMA_VERSION", 2)
        with pytest.raises(StorageError, match="no migration path from schema v1"):
            run_migrations({"schema_version": 1, "title": "x"})

    def test_future_version_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="unsupported schema_version"):
            run_migrations({"schema_version": 99, "title": "x"})

    def test_needs_migration_classifies_versions(self) -> None:
        assert needs_migration({"schema_version": 1}) is False
        assert needs_migration({"schema_version": 1}, latest=2) is True
        assert needs_migration({"schema_version": 2}, latest=2) is False
        assert needs_migration({"schema_version": 5}, latest=2) is False
        assert needs_migration("not a record") is False


class TestStoreIntegration:
    def test_read_path_migrates_and_backs_up(self, tmp_path: Path, v2_world) -> None:
        path = make_raw_record(tmp_path)
        store = ExperienceStore(tmp_path)
        records = store.list_all()
        assert [r.title for r in records] == ["Ancient Record"]
        assert records[0].schema_version == 2
        assert records[0].reflection == "imported before schema v2"
        # original preserved under backup/, live file rewritten
        backups = list((tmp_path / "backup").glob("exp_*.json"))
        assert len(backups) == 1
        assert json.loads(backups[0].read_text(encoding="utf-8"))["schema_version"] == 1
        assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 2
        # second read: already migrated, no extra backup
        store.list_all()
        assert len(list((tmp_path / "backup").glob("*.json"))) == 1

    def test_pending_migrations_reports_old_files(
        self, tmp_path: Path, v2_world
    ) -> None:
        path = make_raw_record(tmp_path)
        store = ExperienceStore(tmp_path)
        pending = store.pending_migrations()
        assert [(p.name, v) for p, v in pending] == [(path.name, 1)]
        new_version = store.migrate_file(path)
        assert new_version == 2
        assert store.pending_migrations() == []


class TestMigrateCli:
    def test_check_only_reports_and_exits_one(
        self, tmp_path: Path, v2_world, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        make_raw_record(tmp_path)
        monkeypatch.setenv("EXPERIENCEOS_HOME", str(tmp_path))
        result = runner.invoke(app, ["migrate", "--check"])
        output = result.output + (result.stderr or "")
        assert result.exit_code == 1, output
        assert "pending" in output
        # nothing changed
        assert json.loads(
            (tmp_path / "experiences" / "exp_01H00000000000000000000000.json").read_text(
                encoding="utf-8"
            )
        )["schema_version"] == 1

    def test_execute_migrates_all_pending(
        self, tmp_path: Path, v2_world, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = make_raw_record(tmp_path)
        monkeypatch.setenv("EXPERIENCEOS_HOME", str(tmp_path))
        result = runner.invoke(app, ["migrate"])
        output = result.output + (result.stderr or "")
        assert result.exit_code == 0, output
        assert "migrated" in output and "backup" in output
        assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 2

    def test_up_to_date_library_is_clean(self, cli_env) -> None:
        result = runner.invoke(app, ["migrate", "--check"])
        assert result.exit_code == 0
        assert "schema v1" in result.output
