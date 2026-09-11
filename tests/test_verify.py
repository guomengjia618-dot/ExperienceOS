"""Evidence verification tests: offline fakes, no network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from experienceos.cli.app import app
from experienceos.connectors.github import GitHubAPIError
from experienceos.services.verify import (
    classify_location,
    save_report,
    summarize,
    verify_records,
)


class FakeGitHub:
    """GitHubAPI test double: canned payloads keyed by API path."""

    def __init__(self, responses: dict[str, dict[str, Any]]):
        self.responses = responses
        self.requested: list[str] = []

    def object(self, path: str) -> dict[str, Any]:
        self.requested.append(path)
        try:
            return self.responses[path]
        except KeyError as exc:
            raise GitHubAPIError(
                "GitHub repository or resource was not found"
            ) from exc


def make_probe(status_by_url: dict[str, int]):
    def probe(url: str) -> int:
        return status_by_url.get(url, 200)

    return probe


# -- location classification --------------------------------------------------


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("github.com/o/r", ("local", {})),  # no scheme -> treated as local path
        ("https://github.com/o/r", ("repo", {"slug": "o/r"})),
        ("https://www.github.com/o/r", ("repo", {"slug": "o/r"})),
        ("https://github.com/o/r/commit/abc123",
         ("commit", {"slug": "o/r", "sha": "abc123"})),
        ("https://github.com/o/r/pull/7", ("pull", {"slug": "o/r", "number": "7"})),
        ("https://github.com/o/r/pulls/7", ("pull", {"slug": "o/r", "number": "7"})),
        ("https://github.com/o/r/blob/main/readme.md",
         ("repo-resource", {"slug": "o/r"})),
        ("https://gitlab.com/o/r", ("external", {})),
        ("https://github.com/only-owner", ("invalid", {})),
        ("D:\\code\\project", ("local", {})),
    ],
)
def test_classify_location(location: str, expected: tuple[str, dict[str, str]]) -> None:
    assert classify_location(location) == expected


# -- per-kind verification ----------------------------------------------------


def test_repo_verified(make_experience) -> None:
    record = make_experience(
        evidence=[{"kind": "repo", "location": "https://github.com/o/r"}]
    )
    github = FakeGitHub({"/repos/o/r": {"full_name": "o/r"}})
    checks = verify_records([record], github=github, probe_url=make_probe({}))
    assert checks[0].status == "verified"
    assert checks[0].detail == "repository o/r exists"
    assert checks[0].experience_id == record.id


def test_commit_verified_reports_author(make_experience) -> None:
    record = make_experience(
        evidence=[
            {"kind": "commit", "location": "https://github.com/o/r/commit/abc123def"}
        ]
    )
    github = FakeGitHub(
        {
            "/repos/o/r/commits/abc123def": {
                "author": {"login": "octocat"},
                "commit": {"author": {"name": "Octo", "date": "2024-05-01T10:00:00Z"}},
            }
        }
    )
    checks = verify_records([record], github=github, probe_url=make_probe({}))
    assert checks[0].status == "verified"
    assert checks[0].detail == "commit abc123de authored by octocat on 2024-05-01"


def test_pull_verified_reports_state(make_experience) -> None:
    record = make_experience(
        evidence=[{"kind": "pull_request", "location": "https://github.com/o/r/pull/7"}]
    )
    github = FakeGitHub(
        {"/repos/o/r/pulls/7": {"user": {"login": "octocat"}, "state": "closed",
                                "merged": True}}
    )
    checks = verify_records([record], github=github, probe_url=make_probe({}))
    assert checks[0].status == "verified"
    assert checks[0].detail == "pull request #7 by octocat (closed, merged)"


def test_missing_evidence_detected(make_experience) -> None:
    record = make_experience(
        evidence=[{"kind": "repo", "location": "https://github.com/o/gone"}]
    )
    checks = verify_records([record], github=FakeGitHub({}), probe_url=make_probe({}))
    assert checks[0].status == "missing"


def test_rate_limit_is_error_not_missing(make_experience) -> None:
    class RateLimited:
        def object(self, path: str) -> dict[str, Any]:
            raise GitHubAPIError(
                "GitHub API rate limit exceeded; set GITHUB_TOKEN or retry"
            )

    record = make_experience(
        evidence=[{"kind": "repo", "location": "https://github.com/o/r"}]
    )
    checks = verify_records([record], github=RateLimited(), probe_url=make_probe({}))
    assert checks[0].status == "error"


@pytest.mark.parametrize(
    ("code", "expected"),
    [(200, "verified"), (404, "missing"), (503, "unreachable")],
)
def test_external_url_probe(make_experience, code: int, expected: str) -> None:
    record = make_experience(
        evidence=[{"kind": "url", "location": "https://blog.example.com/post"}]
    )
    checks = verify_records(
        [record], github=FakeGitHub({}), probe_url=make_probe(
            {"https://blog.example.com/post": code}
        )
    )
    assert checks[0].status == expected


def test_local_path_skipped(make_experience) -> None:
    record = make_experience(
        evidence=[{"kind": "file", "location": "D:\\code\\project"}]
    )
    checks = verify_records([record], github=FakeGitHub({}), probe_url=make_probe({}))
    assert checks[0].status == "skipped"


# -- aggregation and reporting -------------------------------------------------


def test_summarize_includes_zero_entries() -> None:
    counts = summarize([])
    assert counts == {
        "verified": 0, "missing": 0, "unreachable": 0, "error": 0, "skipped": 0,
    }


def test_save_report_writes_summary_and_checks(
    tmp_path: Path, make_experience
) -> None:
    record = make_experience(
        evidence=[{"kind": "repo", "location": "https://github.com/o/r"}]
    )
    checks = verify_records([record], github=FakeGitHub(
        {"/repos/o/r": {"full_name": "o/r"}}
    ), probe_url=make_probe({}))
    path = save_report(checks, tmp_path / "report.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["summary"]["verified"] == 1
    assert payload["checks"][0]["experience_id"] == record.id
    assert payload["checks"][0]["detail"] == "repository o/r exists"


# -- CLI surface ----------------------------------------------------------------


def test_verify_cli_reports_and_exits_nonzero_on_missing(
    cli_env: Any, monkeypatch: pytest.MonkeyPatch, make_experience
) -> None:
    import importlib

    from experienceos.services.verify import EvidenceCheck
    from experienceos.storage import ExperienceStore

    cli_module = importlib.import_module("experienceos.cli.app")
    ExperienceStore(Path(cli_env)).save(make_experience(title="Alpha"))
    checks = [
        EvidenceCheck("exp_1", "Alpha", 0, "repo", "https://github.com/o/r",
                      "verified", "repository o/r exists"),
        EvidenceCheck("exp_1", "Alpha", 1, "commit", "https://github.com/o/r/c/deadbeef",
                      "missing", "GitHub repository or resource was not found"),
    ]
    monkeypatch.setattr(
        cli_module.verify_services, "verify_records", lambda *args, **kwargs: checks
    )
    result = CliRunner().invoke(app, ["verify"])
    output = result.output
    assert result.exit_code == 1
    assert "repository o/r exists" in output
    assert "1 verified" in output and "1 missing" in output


def test_verify_cli_all_verified_exits_zero(
    cli_env: Any, monkeypatch: pytest.MonkeyPatch, make_experience, tmp_path: Path
) -> None:
    import importlib

    from experienceos.services.verify import EvidenceCheck
    from experienceos.storage import ExperienceStore

    cli_module = importlib.import_module("experienceos.cli.app")
    ExperienceStore(Path(cli_env)).save(make_experience(title="Alpha"))
    checks = [
        EvidenceCheck("exp_1", "Alpha", 0, "repo", "https://github.com/o/r",
                      "verified", "repository o/r exists"),
    ]
    monkeypatch.setattr(
        cli_module.verify_services, "verify_records", lambda *args, **kwargs: checks
    )
    report = tmp_path / "verify.json"
    result = CliRunner().invoke(app, ["verify", "--json", str(report)])
    assert result.exit_code == 0
    assert report.exists()
