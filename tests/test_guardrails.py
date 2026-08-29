"""Evidence guardrail tests (#013): pure functions, no LLM involved."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from experienceos.cli.app import app
from experienceos.core.guardrails import (
    ClaimIssue,
    find_unsupported_claims,
    lint_experiences,
    quantitative_claim,
)
from experienceos.storage import ExperienceStore

runner = CliRunner()


class TestQuantitativeClaim:
    @pytest.mark.parametrize(
        "sentence",
        [
            "cut p99 latency by 40%",
            "性能提升 3 倍",
            " throughput improved 3x ",
            "reduced cold start 2.5 times",
            "grew DAU 10万 -> 100万",
            "scaled to 100k QPS",
            "processed 10,000 events per second",
            "response time down to 50ms",
            "grew the team 30+",
            "支撑 50 个微服务",
            "top 3 in the course ranking",
            "竞赛排名 前10名",
            "获得 第1名",
            "led a team of 12 engineers",
            "served 100 users on day one",
        ],
    )
    def test_detects_measurable_claims(self, sentence: str) -> None:
        assert quantitative_claim(sentence) is True

    @pytest.mark.parametrize(
        "sentence",
        [
            "designed the ingestion pipeline",
            "migrated the service to Kubernetes",
            "led the search relevance effort",
            "released v2 of the API in 2023",
            "worked on it during 2022 and 2023",
            "paired with two teammates",
        ],
    )
    def test_ignores_prose_and_years(self, sentence: str) -> None:
        assert quantitative_claim(sentence) is False


class TestFindUnsupportedClaims:
    def test_reports_claim_without_evidence(self, make_experience) -> None:
        exp = make_experience(
            contribution=["cut p99 latency by 40%"],
            result=["top 3 in the demo day"],
            evidence=[],
        )
        issues = find_unsupported_claims(exp)
        assert [(i.field, i.sentence) for i in issues] == [
            ("contribution", "cut p99 latency by 40%"),
            ("result", "top 3 in the demo day"),
        ]
        assert all(i.experience_id == exp.id for i in issues)
        assert all("evidence" in i.suggestion for i in issues)

    def test_any_evidence_clears_the_record(self, make_experience) -> None:
        exp = make_experience(
            contribution=["cut p99 latency by 40%"],
            evidence=[{"kind": "url", "location": "https://example.com/post"}],
        )
        assert find_unsupported_claims(exp) == []

    def test_only_contribution_and_result_are_scanned(self, make_experience) -> None:
        exp = make_experience(
            description="handled 10,000 requests",
            challenge=["queued jobs piled to 50万"],
            solution=["grew throughput 3x"],
            contribution=[],
            result=[],
        )
        assert find_unsupported_claims(exp) == []


class TestLintExperiences:
    def test_aggregates_across_records(self, make_experience) -> None:
        first = make_experience(result=["40% faster"])
        clean = make_experience(contribution=["built the indexer"])
        issues = lint_experiences([first, clean])
        assert len(issues) == 1
        assert issues[0].experience_id == first.id
        assert isinstance(issues[0], ClaimIssue)


class TestLintCli:
    def test_clean_library_exits_zero(self, cli_env, make_experience) -> None:
        seed_clean(cli_env, make_experience)
        result = runner.invoke(app, ["lint"])
        assert result.exit_code == 0, result.output
        assert "No unsupported claims" in result.output

    def test_unsupported_claim_exits_one(self, cli_env, make_experience) -> None:
        store = ExperienceStore(cli_env)
        store.save(make_experience(contribution=["性能提升 3 倍"]))
        result = runner.invoke(app, ["lint"])
        output = result.output + (result.stderr or "")
        assert result.exit_code == 1, output
        assert "性能提升 3 倍" in output
        assert "source=interview" in output

    def test_archived_records_need_all_flag(self, cli_env, make_experience) -> None:
        store = ExperienceStore(cli_env)
        store.save(make_experience(result=["40% faster"], status="archived"))
        assert runner.invoke(app, ["lint"]).exit_code == 0
        assert runner.invoke(app, ["lint", "--all"]).exit_code == 1

    def test_stats_includes_lint_summary(self, cli_env, make_experience) -> None:
        seed_clean(cli_env, make_experience)
        result = runner.invoke(app, ["stats"])
        assert result.exit_code == 0
        assert "Unsupported claims (no evidence): 0" in result.output


def seed_clean(cli_env, make_experience) -> None:
    store = ExperienceStore(cli_env)
    store.save(make_experience(description="designed and built things"))
