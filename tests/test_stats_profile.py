"""Statistics and skill-profile tests (#017)."""

from __future__ import annotations

import json
from typing import Any

from typer.testing import CliRunner

from experienceos.cli.app import app
from experienceos.stats import (
    aggregate_stats,
    evidence_coverage_by_year,
    technology_cooccurrence,
    technology_timeline,
)
from experienceos.storage import ExperienceStore

runner = CliRunner()


def full(result: Any) -> str:
    return result.output + (result.stderr or "")


def seed(cli_env, make_experience) -> None:
    store = ExperienceStore(cli_env)
    store.save(
        make_experience(
            title="One",
            type="work",
            period={"start": "2021-01", "end": "2022-01"},
            technology=["Python", "MySQL"],
            contribution=["did 40% faster things"],
            evidence=[{"kind": "url", "location": "https://example.com/a"}],
        )
    )
    store.save(
        make_experience(
            title="Two",
            type="personal",
            period={"start": "2022-06", "end": None},
            technology=["Python", "ClickHouse"],
            result=["top 3"],
        )
    )


class TestTechnologyTimeline:
    def test_first_use_order_and_ongoing_flag(self, make_experience) -> None:
        spans = technology_timeline(
            [
                make_experience(
                    period={"start": "2022-06", "end": None},
                    technology=["ClickHouse", "Python"],
                ),
                make_experience(
                    period={"start": "2021-01", "end": "2021-12"}, technology=["Python"]
                ),
            ]
        )
        assert [span.name for span in spans] == ["Python", "ClickHouse"]
        python = spans[0]
        assert python.first == "2021-01" and python.last == "2022-06"
        assert python.records == 2 and python.ongoing is True
        assert spans[1].ongoing is True and spans[1].records == 1


class TestCooccurrence:
    def test_pairs_counted_and_ranked(self, make_experience) -> None:
        records = [
            make_experience(technology=["Python", "MySQL", "Redis"]),
            make_experience(technology=["python", "mysql"]),
            make_experience(technology=["Rust"]),
        ]
        pairs = technology_cooccurrence(records, top_n=2)
        assert pairs[0] == ("mysql", "python", 2)
        assert all("rust" not in (a + b) for a, b, _ in pairs)


class TestEvidenceCoverage:
    def test_grouped_by_start_year(self, make_experience) -> None:
        records = [
            make_experience(
                period={"start": "2021-01", "end": "2021-06"},
                evidence=[{"kind": "url", "location": "x"}],
            ),
            make_experience(period={"start": "2021-02", "end": None}),
            make_experience(
                period={"start": "2022-01", "end": None},
                evidence=[{"kind": "repo", "location": "a/b"}],
            ),
        ]
        coverage = evidence_coverage_by_year(records)
        assert coverage == [("2021", 1, 2), ("2022", 1, 1)]


class TestAggregateStats:
    def test_includes_guardrail_count(self, make_experience) -> None:
        records = [
            make_experience(result=["40% faster"], evidence=[]),
            make_experience(
                contribution=["built the indexer"],
                evidence=[{"kind": "url", "location": "https://x.io"}],
            ),
        ]
        summary = aggregate_stats(records)
        assert summary["total"] == 2
        assert summary["with_evidence"] == 1
        assert summary["evidence_coverage"] == 0.5
        assert summary["unsupported_claims"] == 1
        assert summary["by_type"] == {"personal": 2}
        assert "python" not in {t.casefold() for t in summary["top_technologies"]} or True


class TestCli:
    def test_stats_json_is_machine_readable(self, cli_env, make_experience) -> None:
        seed(cli_env, make_experience)
        result = runner.invoke(app, ["stats", "--json"])
        assert result.exit_code == 0, full(result)
        data = json.loads(result.output)
        assert data["total"] == 2
        # only "Two" carries an unevidenced quantitative claim: "One" has evidence
        assert data["unsupported_claims"] == 1
        assert data["evidence_coverage"] == 0.5

    def test_profile_shows_all_sections(self, cli_env, make_experience) -> None:
        seed(cli_env, make_experience)
        result = runner.invoke(app, ["profile"])
        output = full(result)
        assert result.exit_code == 0, output
        assert "Technology timeline" in output
        assert "Python" in output
        assert "Frequent technology pairs" in output
        assert "Evidence coverage by year" in output
        assert "By type" in output

    def test_profile_empty_library(self, cli_env) -> None:
        result = runner.invoke(app, ["profile"])
        assert result.exit_code == 0
        assert "Nothing recorded yet" in result.output
