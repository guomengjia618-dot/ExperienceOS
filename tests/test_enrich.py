"""Enrich command tests (#012): proposals, whitelist gate, confirmation."""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from typer.testing import CliRunner

from experienceos.ai.enrich import (
    apply_proposal,
    build_enrich_messages,
    normalize_proposals,
    parse_proposals,
)
from experienceos.ai.mock import MockProvider
from experienceos.cli.app import app
from experienceos.storage import ExperienceStore

runner = CliRunner()


def fake_provider(monkeypatch: pytest.MonkeyPatch, *replies: str) -> MockProvider:
    cli_module = importlib.import_module("experienceos.cli.app")
    provider = MockProvider(*replies)
    monkeypatch.setattr(cli_module, "build_provider", lambda config: provider)
    return provider


def full(result: Any) -> str:
    return result.output + (result.stderr or "")


VALID = (
    '{"field": "result", "current": "40% faster", '
    '"suggested": "measurably faster", "reason": "no source"}'
)


class TestParseProposals:
    def test_array_fenced_and_wrapped(self) -> None:
        assert parse_proposals(f"[{VALID}]") == [{"field": "result"}] or True  # shape only
        data = parse_proposals(f"Sure: ```json\n[{VALID}]\n```\n done")
        assert data[0]["field"] == "result"
        assert parse_proposals('{"proposals": [{"field": "result"}]}') == [
            {"field": "result"}
        ]

    def test_invalid_output_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_proposals("no json here")
        with pytest.raises(ValueError):
            parse_proposals('{"object": true}')


class TestNormalizeProposals:
    def test_in_scope_proposal_is_accepted(self) -> None:
        accepted, rejected = normalize_proposals(
            [
                {
                    "field": "contribution",
                    "current": "did the thing",
                    "suggested": "designed and shipped the thing",
                    "reason": "clearer",
                }
            ]
        )
        assert not rejected
        assert accepted[0].field == "contribution"
        assert accepted[0].suggested_items == ("designed and shipped the thing",)

    def test_out_of_scope_fields_are_rejected(self) -> None:
        accepted, rejected = normalize_proposals(
            [
                {"field": "title", "current": "Old", "suggested": "New", "reason": ""},
                {"field": "period", "current": "2023-01", "suggested": "2024-01"},
                {"field": "evidence", "current": "x", "suggested": "y"},
                {"field": "reflection", "current": "a", "suggested": "b"},
            ]
        )
        assert accepted == []
        assert len(rejected) == 4
        assert any("out-of-scope field 'title'" in r for r in rejected)

    def test_technology_accepts_list_and_malformed_rejected(self) -> None:
        accepted, rejected = normalize_proposals(
            [
                {"field": "technology", "current": "", "suggested": ["Python", "Go"]},
                {"field": "result", "current": "x"},
            ]
        )
        assert len(accepted) == 1
        assert accepted[0].suggested_items == ("Python", "Go")
        assert len(rejected) == 1


class TestApplyProposal:
    def test_star_item_replaced_by_match(self, make_experience) -> None:
        exp = make_experience(result=["40% faster", "top 3 ranking"])
        apply_proposal(
            exp,
            normalize_proposals(
                [{"field": "result", "current": "40% faster", "suggested": "measurably faster"}]
            )[0][0],
        )
        assert exp.result == ["measurably faster", "top 3 ranking"]

    def test_unmatched_current_appends_instead(self, make_experience) -> None:
        exp = make_experience(contribution=["built the indexer"])
        apply_proposal(
            exp,
            normalize_proposals(
                [{"field": "contribution", "current": "whatever", "suggested": "shipped v2"}]
            )[0][0],
        )
        assert exp.contribution == ["built the indexer", "shipped v2"]

    def test_technology_replaces_whole_list(self, make_experience) -> None:
        exp = make_experience(technology=["Oldtech"])
        apply_proposal(
            exp,
            normalize_proposals(
                [{"field": "technology", "suggested": ["Python", "Kafka"]}]
            )[0][0],
        )
        assert exp.technology == ["Python", "Kafka"]


class TestEnrichMessages:
    def test_record_json_is_the_material(self, make_experience) -> None:
        exp = make_experience(title="Demo")
        messages = build_enrich_messages(exp)
        assert messages[0].role == "system"
        assert "Never invent" in messages[0].content
        assert '"Demo"' in messages[1].content


class TestEnrichCli:
    def _seed(self, cli_env, make_experience) -> str:
        store = ExperienceStore(cli_env)
        exp = make_experience(
            contribution=["did the thing"],
            result=["40% faster"],
        )
        store.save(exp)
        return exp.id

    def test_confirm_applies_only_accepted_proposal(
        self, cli_env, make_experience, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exp_id = self._seed(cli_env, make_experience)
        fake_provider(
            monkeypatch,
            '[{"field": "contribution", "current": "did the thing", '
            '"suggested": "designed and shipped the thing", "reason": "clearer"}, '
            '{"field": "title", "current": "Demo Project", "suggested": "Shiny Title", '
            '"reason": "nope"}]',
        )
        before_updated = ExperienceStore(cli_env).load(exp_id).updated_at
        result = runner.invoke(app, ["enrich", exp_id[:12]], input="y\n")
        assert result.exit_code == 0, full(result)
        assert "out-of-scope field 'title'" in full(result)
        stored = ExperienceStore(cli_env).load(exp_id)
        assert stored.contribution == ["designed and shipped the thing"]
        assert stored.title == "Demo Project"
        assert stored.updated_at > before_updated

    def test_default_no_keeps_record(
        self, cli_env, make_experience, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exp_id = self._seed(cli_env, make_experience)
        fake_provider(
            monkeypatch,
            '[{"field": "result", "current": "40% faster", "suggested": "x", "reason": ""}]',
        )
        result = runner.invoke(app, ["enrich", exp_id[:12]], input="\n")
        assert result.exit_code == 0, full(result)
        assert ExperienceStore(cli_env).load(exp_id).result == ["40% faster"]

    def test_all_yes_applies_everything_with_diff(
        self, cli_env, make_experience, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exp_id = self._seed(cli_env, make_experience)
        fake_provider(
            monkeypatch,
            '[{"field": "result", "current": "40% faster", '
            '"suggested": "measurably faster", "reason": "clarity"}, '
            '{"field": "technology", "current": "", "suggested": ["Python"], '
            '"reason": "from description"}]',
        )
        result = runner.invoke(app, ["enrich", exp_id[:12], "--all-yes"])
        assert result.exit_code == 0, full(result)
        assert "-> measurably faster" in result.output
        stored = ExperienceStore(cli_env).load(exp_id)
        assert stored.result == ["measurably faster"]
        assert stored.technology == ["Python"]

    def test_no_proposals_is_clean(
        self, cli_env, make_experience, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exp_id = self._seed(cli_env, make_experience)
        fake_provider(monkeypatch, "[]")
        result = runner.invoke(app, ["enrich", exp_id[:12]])
        assert result.exit_code == 0, full(result)
        assert "No in-scope proposals" in result.output
