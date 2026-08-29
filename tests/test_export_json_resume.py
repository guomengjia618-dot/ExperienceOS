"""JSON Resume exporter tests (#016): mapping, validation, faithful drops."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from experienceos.cli.app import app
from experienceos.exporters.json_resume import JsonResume, JsonResumeExporter
from experienceos.storage import ExperienceStore

runner = CliRunner()


def full(result: Any) -> str:
    return result.output + (result.stderr or "")


def seed_library(cli_env, make_experience) -> None:
    """Five records across five of the nine types, incl. drops."""
    store = ExperienceStore(cli_env)
    store.save(
        make_experience(
            title="Acme Backend",
            type="work",
            period={"start": "2021-06", "end": "2023-02"},
            role="backend engineer",
            description="order service team",
            technology=["Python", "MySQL"],
            contribution=["shipped the order API"],
            result=["p99 down to 50ms"],
            reflection="queues are a discipline",
        )
    )
    store.save(
        make_experience(
            title="Acme Internship",
            type="internship",
            period={"start": "2020-07", "end": "2021-02"},
            role="intern",
            evidence=[{"kind": "file", "location": "/docs/intern.pdf"}],
        )
    )
    store.save(
        make_experience(
            title="Log Platform",
            type="open_source",
            period={"start": "2022-03", "end": None},
            description="ClickHouse-backed log search",
            technology=["ClickHouse"],
            evidence=[{"kind": "url", "location": "https://github.com/me/log"}],
        )
    )
    store.save(
        make_experience(
            title="Campus Search",
            type="course_project",
            period={"start": "2023-01", "end": "2023-06"},
            technology=["Python", "Whoosh"],
            challenge=["long-document recall was low"],
        )
    )
    store.save(
        make_experience(
            title="Hackday Bot",
            type="competition",
            period={"start": "2022-10", "end": "2022-10"},
            tags=["fun"],
            evidence=[{"kind": "commit", "location": "abc1234d"}],
        )
    )


class TestMapping:
    def test_work_and_projects_split_by_type(
        self, cli_env, make_experience, tmp_path: Path
    ) -> None:
        seed_library(cli_env, make_experience)
        out = tmp_path / "resume.json"
        result = runner.invoke(app, ["export", "json-resume", "--out", str(out)])
        assert result.exit_code == 0, full(result)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert len(data["work"]) == 2
        assert len(data["projects"]) == 3
        acme = next(item for item in data["work"] if item["name"] == "Acme Backend")
        assert acme["position"] == "backend engineer"
        assert acme["startDate"] == "2021-06" and acme["endDate"] == "2023-02"
        assert "shipped the order API" in acme["highlights"]
        log = next(item for item in data["projects"] if item["name"] == "Log Platform")
        assert log["url"] == "https://github.com/me/log"
        assert log["keywords"] == ["ClickHouse"]
        # ongoing record: endDate omitted, never invented
        assert "endDate" not in log
        skill_names = {skill["name"] for skill in data["skills"]}
        assert {"Python", "MySQL", "ClickHouse", "Whoosh"} <= skill_names

    def test_output_validates_against_strict_model(
        self, cli_env, make_experience, tmp_path: Path
    ) -> None:
        seed_library(cli_env, make_experience)
        out = tmp_path / "resume.json"
        result = runner.invoke(app, ["export", "json-resume", "--out", str(out)])
        assert result.exit_code == 0, full(result)
        parsed = json.loads(out.read_text(encoding="utf-8"))
        JsonResume.model_validate(parsed)  # must not raise

    def test_unexportable_fields_dropped_and_reported(
        self, cli_env, make_experience, tmp_path: Path
    ) -> None:
        seed_library(cli_env, make_experience)
        out = tmp_path / "resume.json"
        result = runner.invoke(app, ["export", "json-resume", "--out", str(out)])
        output = full(result)
        assert result.exit_code == 0, output
        assert "dropped unexportable fields" in output
        assert "reflection x1" in output
        assert "tags x1" in output
        assert "evidence[file] x1" in output
        assert "evidence[commit] x1" in output
        data = json.loads(out.read_text(encoding="utf-8"))
        text = json.dumps(data)
        assert "queues are a discipline" not in text  # reflection never leaks

    def test_challenge_mapped_into_highlights_not_dropped(
        self, cli_env, make_experience, tmp_path: Path
    ) -> None:
        seed_library(cli_env, make_experience)
        out = tmp_path / "resume.json"
        runner.invoke(app, ["export", "json-resume", "--out", str(out)])
        data = json.loads(out.read_text(encoding="utf-8"))
        campus = next(
            item for item in data["projects"] if item["name"] == "Campus Search"
        )
        assert "long-document recall was low" in campus["highlights"]


class TestExporterUnit:
    def test_empty_selection_rejected(self, tmp_path: Path) -> None:
        from experienceos.core.errors import ExportError

        importer = JsonResumeExporter()
        try:
            importer.export([], tmp_path / "x.json")
        except ExportError as exc:
            assert "nothing to export" in str(exc)
        else:
            raise AssertionError("expected ExportError")

    def test_registered(self) -> None:
        from experienceos.exporters import default_exporter_registry

        assert default_exporter_registry.get("json-resume").name == "json-resume"
