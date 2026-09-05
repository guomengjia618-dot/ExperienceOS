"""Interview command tests (#011): MockProvider end-to-end, no network."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from experienceos.ai.interview import (
    collect_evidence_candidates,
    draft_from_extraction,
    parse_extraction_json,
)
from experienceos.ai.mock import MockProvider
from experienceos.cli.app import app
from experienceos.core.models import SourceOrigin, Status
from experienceos.storage import ExperienceStore

runner = CliRunner()


def fake_provider(monkeypatch: pytest.MonkeyPatch, *replies: str) -> MockProvider:
    """Replace the CLI's provider factory with a scripted MockProvider."""
    cli_module = importlib.import_module("experienceos.cli.app")
    provider = MockProvider(*replies)
    monkeypatch.setattr(cli_module, "build_provider", lambda config: provider)
    return provider


def full(result: Any) -> str:
    return result.output + (result.stderr or "")


class TestCollectEvidenceCandidates:
    def test_url_sha_and_slug(self) -> None:
        text = (
            "pushed the fix in https://example.com/pr/7 and commit abc1234d, "
            "see repo me/engine"
        )
        candidates = collect_evidence_candidates(text)
        locations = [c["location"] for c in candidates]
        assert "https://example.com/pr/7" in locations
        assert "abc1234d" in locations
        assert "me/engine" in locations
        kinds = {c["location"]: c["kind"] for c in candidates}
        assert kinds["abc1234d"] == "commit"
        assert kinds["me/engine"] == "repo"

    def test_github_bare_link_becomes_url_evidence(self) -> None:
        candidates = collect_evidence_candidates("source at github.com/me/engine")
        assert candidates[0]["kind"] == "url"
        assert candidates[0]["location"] == "https://github.com/me/engine"

    def test_dates_are_not_slugs_and_urls_not_double_counted(self) -> None:
        candidates = collect_evidence_candidates(
            "since 2023/04 see https://github.com/me/engine/commit/abc1234d"
        )
        locations = [c["location"] for c in candidates]
        assert "2023/04" not in locations
        assert not any(location.startswith("abc1234d") for location in locations)

    def test_deduplicates_and_caps(self) -> None:
        text = " ".join(["repo a/b"] * 5) + " " + " ".join(
            f"repo owner{i}/repo{i}" for i in range(20)
        )
        candidates = collect_evidence_candidates(text)
        assert len(candidates) == 10
        assert len({c["location"] for c in candidates}) == 10


class TestParseExtractionJson:
    def test_plain_fenced_and_prose_wrapped(self) -> None:
        assert parse_extraction_json('{"title": "x"}') == {"title": "x"}
        assert parse_extraction_json('```json\n{"title": "x"}\n```') == {"title": "x"}
        assert parse_extraction_json('Sure! {"title": "x"} hope it helps') == {
            "title": "x"
        }

    def test_invalid_shapes_raise_value_error(self) -> None:
        with pytest.raises(ValueError):
            parse_extraction_json("not json")
        with pytest.raises(ValueError):
            parse_extraction_json('["a list"]')


class TestDraftFromExtraction:
    def test_whitelist_mapping_and_provenance(self) -> None:
        draft = draft_from_extraction(
            {
                "title": "Campus Search",
                "type": "course_project",
                "period": {"start": "2023-01", "end": "2023-06"},
                "role": "engine lead",
                "result": ["top 3 in class demo"],
                "evidence": [{"kind": "repo", "location": "me/engine"}],
                "fabricated_secret": "dropped",
            },
            model="glm-4.7",
        )
        exp = draft.experience
        assert exp.status is Status.draft
        assert exp.source.origin is SourceOrigin.interview
        assert exp.source.created_by == "ai:glm-4.7"
        assert exp.title == "Campus Search"
        assert exp.period.start == "2023-01" and exp.period.end == "2023-06"
        assert exp.result == ["top 3 in class demo"]
        assert not hasattr(exp, "fabricated_secret")

    def test_invalid_type_and_period_fall_back_safely(self) -> None:
        draft = draft_from_extraction(
            {"title": "Mystery", "type": "wizardry", "period": {"start": "recently"}},
            model="m",
        )
        assert draft.experience.type.value == "other"
        assert draft.experience.period.start == "1970-01"
        assert draft.experience.period.end is None

    def test_conversation_candidates_are_merged(self) -> None:
        candidates = [{"kind": "url", "location": "https://x.io/a", "description": ""}]
        draft = draft_from_extraction(
            {"title": "T"}, model="m", candidates=candidates
        )
        assert [e.location for e in draft.experience.evidence] == ["https://x.io/a"]


class TestInterviewCli:
    def test_full_ai_flow_saves_confirmed_draft(
        self, cli_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = fake_provider(
            monkeypatch,
            "What did you build?",
            '{"title": "Search Engine", "type": "personal", '
            '"period": {"start": "2023-01", "end": "2023-06"}}',
        )
        result = runner.invoke(
            app,
            ["interview", "--language", "English"],
            input=(
                "I built a search engine, source at github.com/me/engine, "
                "commit abc1234d\n"
                "/done\n"
                "\n\n\n\n"
                "y\n"
            ),
        )
        assert result.exit_code == 0, full(result)
        assert "What did you build?" in result.output
        # the intake prompt went to the provider with the chosen language
        system_call = provider.calls[0][0]
        assert "intake interviewer" in system_call.content
        assert "English" in system_call.content

        saved = ExperienceStore(cli_env).list_all()
        assert len(saved) == 1
        exp = saved[0]
        assert exp.source.origin is SourceOrigin.interview
        assert exp.source.created_by == "ai:gpt-4o-mini"
        assert exp.status is Status.draft
        assert exp.title == "Search Engine"
        locations = [e.location for e in exp.evidence]
        assert "https://github.com/me/engine" in locations
        assert "abc1234d" in locations
        # a successful run keeps no transcript on disk
        assert not (Path(cli_env) / "drafts").exists()

    def test_ai_harvested_evidence_can_be_dropped(
        self, cli_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Evidence passes the same human gate as every other field."""
        fake_provider(
            monkeypatch,
            "What did you build?",
            '{"title": "Dropped Evidence", "type": "personal", '
            '"period": {"start": "2023-01"}}',
        )
        result = runner.invoke(
            app,
            ["interview"],
            input=(
                "built a thing, repo me/engine\n"
                "/done\n"
                "\n\n\n"  # keep title / type / period
                "d\n"  # drop the harvested evidence
                "y\n"
            ),
        )
        assert result.exit_code == 0, full(result)
        exp = ExperienceStore(cli_env).list_all()[0]
        assert exp.evidence == []

    def test_invalid_json_retried_once_then_saved(
        self, cli_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_provider(
            monkeypatch,
            "Tell me more.",
            "oops, not json",
            '{"title": "Retry Engine", "type": "work", "period": {"start": "2022-02"}}',
        )
        result = runner.invoke(
            app,
            ["interview"],
            input="built a thing\n/done\n\n\n\ny\n",
        )
        assert result.exit_code == 0, full(result)
        assert ExperienceStore(cli_env).list_all()[0].title == "Retry Engine"

    def test_double_failure_keeps_transcript_in_drafts(
        self, cli_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_provider(monkeypatch, "Start.", "bad one", "even worse")
        result = runner.invoke(
            app,
            ["interview"],
            input="built a thing\n/done\n",
        )
        output = full(result)
        assert result.exit_code == 1, output
        assert "drafts" in output
        drafts = list(Path(cli_env, "drafts").glob("interview-*.md"))
        assert len(drafts) == 1
        assert "built a thing" in drafts[0].read_text(encoding="utf-8")

    def test_no_ai_wizard_needs_no_provider(self, cli_env) -> None:
        result = runner.invoke(
            app,
            ["interview", "--no-ai"],
            input="Manual Story\npersonal\n2021-01\n\n\n\n\n\n\n",
        )
        assert result.exit_code == 0, full(result)
        saved = ExperienceStore(cli_env).list_all()
        assert len(saved) == 1
        exp = saved[0]
        assert exp.source.origin is SourceOrigin.interview
        assert exp.source.created_by == "user"
        assert exp.status is Status.draft
        assert exp.title == "Manual Story"

    def test_missing_key_fails_with_env_hint(
        self, cli_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        result = runner.invoke(app, ["interview"], input="hello\n/done\n")
        output = full(result)
        assert result.exit_code == 1, output
        assert "$OPENAI_API_KEY" in output
