"""FTS index tests (#022): the index is a disposable derivative."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from experienceos.cli.app import app
from experienceos.services.experiences import run_query
from experienceos.storage import ExperienceStore, SearchQuery, search
from experienceos.storage.fts import (
    build_index,
    delete_index,
    fts_search,
    index_doc_count,
    index_exists,
    index_path,
)

runner = CliRunner()


@pytest.fixture
def small_library(cli_env, make_experience) -> ExperienceStore:
    store = ExperienceStore(cli_env)
    store.save(
        make_experience(title="Payment Gateway", description="支付网关重构", technology=["Go"])
    )
    store.save(
        make_experience(
            title="Search Engine", description="inverted index pipeline", technology=["Python"]
        )
    )
    return store


class TestIndexLifecycle:
    def test_build_and_query(self, cli_env, small_library: ExperienceStore) -> None:
        assert index_exists(cli_env) is False
        count = build_index(cli_env, small_library.list_all())
        assert count == 2
        ids = fts_search(cli_env, "payment")
        assert len(ids) == 1
        assert ids[0].startswith("exp_")

    def test_cjk_query_finds_substring(self, cli_env, small_library: ExperienceStore) -> None:
        build_index(cli_env, small_library.list_all())
        assert len(fts_search(cli_env, "支付网关")) == 1
        assert len(fts_search(cli_env, "网关")) == 1

    def test_delete_index_is_harmless(self, cli_env, small_library: ExperienceStore) -> None:
        build_index(cli_env, small_library.list_all())
        assert delete_index(cli_env) is True
        assert index_exists(cli_env) is False
        assert fts_search(cli_env, "payment") == []
        assert delete_index(cli_env) is False

    def test_empty_query_returns_nothing(self, cli_env, small_library: ExperienceStore) -> None:
        build_index(cli_env, small_library.list_all())
        assert fts_search(cli_env, "   ") == []


class TestDispatch:
    def _ids(self, results: list) -> set[str]:
        return {exp.id for exp in results}

    def test_fts_and_memory_agree_under_threshold(
        self, cli_env, small_library: ExperienceStore
    ) -> None:
        build_index(cli_env, small_library.list_all())
        query = SearchQuery(text="engine")
        # below the default threshold the memory path runs even with an index
        assert not os.environ.get("EXPERIENCEOS_FTS_THRESHOLD")
        memory = run_query(small_library, query)
        assert len(memory) == 1

    def test_index_accelerates_when_threshold_met(
        self, cli_env, small_library: ExperienceStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EXPERIENCEOS_FTS_THRESHOLD", "1")
        build_index(cli_env, small_library.list_all())
        query = SearchQuery(text="engine")
        via_fts = run_query(small_library, query)
        assert {exp.title for exp in via_fts} == {"Search Engine"}

    def test_results_identical_with_and_without_index(
        self, cli_env, small_library: ExperienceStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        query = SearchQuery(text="engine")
        memory = run_query(small_library, query)
        monkeypatch.setenv("EXPERIENCEOS_FTS_THRESHOLD", "1")
        build_index(cli_env, small_library.list_all())
        indexed = run_query(small_library, query)
        assert self._ids(indexed) == self._ids(memory)

    def test_non_text_filters_survive_the_fts_path(
        self, cli_env, small_library: ExperienceStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EXPERIENCEOS_FTS_THRESHOLD", "1")
        build_index(cli_env, small_library.list_all())
        from experienceos.core.models import ExperienceType

        query = SearchQuery(text="search", types=(ExperienceType.personal,))
        results = run_query(small_library, query)
        assert {exp.title for exp in results} == {"Search Engine"}

    def test_stale_index_entries_dropped(
        self, cli_env, small_library: ExperienceStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EXPERIENCEOS_FTS_THRESHOLD", "1")
        build_index(cli_env, small_library.list_all())
        # a file disappears (source of truth moves on, index is stale)
        for path in (Path(cli_env) / "experiences").glob("*.json"):
            if "Search" in path.read_text(encoding="utf-8"):
                path.unlink()
        results = run_query(small_library, SearchQuery(text="engine"))
        assert results == []

    def test_threshold_zero_disables_fts(
        self, cli_env, small_library: ExperienceStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EXPERIENCEOS_FTS_THRESHOLD", "0")
        build_index(cli_env, small_library.list_all())
        assert run_query(small_library, SearchQuery(text="engine")) != []

    def test_reference_memory_implementation_still_works(
        self, small_library: ExperienceStore
    ) -> None:
        # the pure in-memory engine stays independently usable (ADR D1)
        results = search(small_library.list_all(), SearchQuery(text="engine"))
        assert len(results) == 1

    def test_scores_consistent_with_and_without_index(
        self, cli_env, small_library: ExperienceStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # the index only narrows candidates; scoring always comes from the
        # in-memory engine, so both paths return identical rankings (#029)
        from experienceos.services.experiences import query_results

        query = SearchQuery(text="engine")
        memory = query_results(small_library, query)
        monkeypatch.setenv("EXPERIENCEOS_FTS_THRESHOLD", "1")
        build_index(cli_env, small_library.list_all())
        indexed = query_results(small_library, query)
        assert [(r.experience.id, round(r.score, 6)) for r in indexed] == [
            (r.experience.id, round(r.score, 6)) for r in memory
        ]
        assert indexed[0].score > 0
        assert indexed[0].matched_fields


class TestIndexFreshness:
    """store.save/delete keep the index in step (no silent staleness)."""

    def test_save_after_rebuild_stays_searchable(
        self,
        cli_env,
        small_library: ExperienceStore,
        make_experience,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("EXPERIENCEOS_FTS_THRESHOLD", "1")
        build_index(cli_env, small_library.list_all())
        small_library.save(
            make_experience(title="Cache Layer", description="redis eviction policy")
        )
        results = run_query(small_library, SearchQuery(text="redis"))
        assert {exp.title for exp in results} == {"Cache Layer"}

    def test_delete_removes_from_index(
        self, cli_env, small_library: ExperienceStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EXPERIENCEOS_FTS_THRESHOLD", "1")
        build_index(cli_env, small_library.list_all())
        victim = next(
            exp for exp in small_library.list_all() if exp.title == "Payment Gateway"
        )
        assert small_library.delete(victim.id) is True
        assert fts_search(cli_env, "payment") == []
        remaining = run_query(small_library, SearchQuery(text="engine"))
        assert {exp.title for exp in remaining} == {"Search Engine"}

    def test_edit_reindexes_the_new_text(
        self, cli_env, small_library: ExperienceStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EXPERIENCEOS_FTS_THRESHOLD", "1")
        build_index(cli_env, small_library.list_all())
        record = next(
            exp for exp in small_library.list_all() if exp.title == "Payment Gateway"
        )
        record.title = "Checkout Service"
        small_library.save(record)
        assert fts_search(cli_env, "payment") == []
        results = run_query(small_library, SearchQuery(text="checkout"))
        assert {exp.id for exp in results} == {record.id}

    def test_all_stale_hits_fall_back_to_full_scan(
        self, cli_env, small_library: ExperienceStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from experienceos.services import experiences as experiences_service

        monkeypatch.setenv("EXPERIENCEOS_FTS_THRESHOLD", "1")
        build_index(cli_env, small_library.list_all())

        def bogus_hits(home, text, limit=None):
            return ["exp_does_not_exist"]

        monkeypatch.setattr(experiences_service.fts_module, "fts_search", bogus_hits)
        results = run_query(small_library, SearchQuery(text="engine"))
        assert {exp.title for exp in results} == {"Search Engine"}


class TestCli:
    def test_index_rebuild_reports_count(self, cli_env, small_library: ExperienceStore) -> None:
        result = runner.invoke(app, ["index", "rebuild"])
        output = result.output + (result.stderr or "")
        assert result.exit_code == 0, output
        assert "Indexed 2 record(s)" in output
        assert index_path(cli_env).exists()


class TestIndexResilience:
    def test_index_doc_count_tracks_rows(
        self, cli_env, small_library: ExperienceStore
    ) -> None:
        assert index_doc_count(cli_env) is None  # no index yet
        build_index(cli_env, small_library.list_all())
        assert index_doc_count(cli_env) == 2

    def test_busy_timeout_is_configured(
        self, cli_env, small_library: ExperienceStore
    ) -> None:
        from experienceos.storage.fts import BUSY_TIMEOUT_MS, _connect

        build_index(cli_env, small_library.list_all())
        connection = _connect(index_path(cli_env))
        try:
            timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
        finally:
            connection.close()
        assert timeout == BUSY_TIMEOUT_MS

    def test_stale_index_is_rebuilt_on_query(
        self, cli_env, small_library: ExperienceStore, make_experience, monkeypatch
    ) -> None:
        """A silently dropped upsert must not hide records from search."""
        import sqlite3

        monkeypatch.setenv("EXPERIENCEOS_FTS_THRESHOLD", "1")
        build_index(cli_env, small_library.list_all())
        third = make_experience(title="Data Platform", description="streaming etl")
        small_library.save(third)
        # simulate the failure mode: the best-effort upsert was lost
        connection = sqlite3.connect(index_path(cli_env))
        try:
            connection.execute("DELETE FROM experiences WHERE id = ?", (third.id,))
            connection.commit()
        finally:
            connection.close()
        assert index_doc_count(cli_env) == 2

        results = run_query(
            small_library, SearchQuery(text="platform")
        )
        assert [exp.id for exp in results] == [third.id]
        assert index_doc_count(cli_env) == 3  # rebuilt in the process
