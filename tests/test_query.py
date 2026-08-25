"""Query engine tests: filters, AND semantics, ranking, period overlap."""

from __future__ import annotations

import pytest

from experienceos.core.models import Experience, ExperienceType, Status
from experienceos.storage.query import SearchQuery, search


@pytest.fixture
def corpus(make_experience) -> list[Experience]:
    return [
        make_experience(
            title="Campus Search Engine",
            type="course_project",
            period={"start": "2023-01", "end": "2023-06"},
            technology=["Python"],
            contribution=["built the inverted index"],
            tags=["ir"],
        ),
        make_experience(
            title="CLI Note Tool",
            type="personal",
            period={"start": "2024-01", "end": None},
            description="a search engine for personal notes",
            technology=["Rust", "CLI"],
        ),
        make_experience(
            title="Search Engine 2.0",
            type="work",
            period={"start": "2024-06", "end": "2025-01"},
            technology=["Python", "FastAPI"],
            tags=["backend", "search"],
            status=Status.draft,
        ),
    ]


def test_title_hits_outrank_body_hits(corpus) -> None:
    results = search(corpus, SearchQuery(text="search engine"))
    assert results[0].experience.title == "Search Engine 2.0"
    titles = [r.experience.title for r in results]
    assert "CLI Note Tool" in titles  # matched via description, ranked lower


def test_terms_are_anded_across_fields(corpus) -> None:
    # "search" lives in description, "rust" in technology -> still a match
    results = search(corpus, SearchQuery(text="search rust"))
    assert [r.experience.title for r in results] == ["CLI Note Tool"]


def test_no_match_returns_empty(corpus) -> None:
    assert search(corpus, SearchQuery(text="kubernetes")) == []


def test_filter_by_type(corpus) -> None:
    results = search(corpus, SearchQuery(types=(ExperienceType.work,)))
    assert [r.experience.title for r in results] == ["Search Engine 2.0"]


def test_filter_by_status(corpus) -> None:
    results = search(corpus, SearchQuery(status=Status.draft))
    assert len(results) == 1 and results[0].experience.status is Status.draft


def test_filter_by_tag_case_insensitive(corpus) -> None:
    results = search(corpus, SearchQuery(tags=("SEARCH",)))
    assert [r.experience.title for r in results] == ["Search Engine 2.0"]


def test_filter_by_technology(corpus) -> None:
    results = search(corpus, SearchQuery(technology=("python",)))
    assert {r.experience.title for r in results} == {
        "Campus Search Engine",
        "Search Engine 2.0",
    }


def test_filters_combine_with_and(corpus) -> None:
    results = search(corpus, SearchQuery(technology=("python",), types=(ExperienceType.work,)))
    assert [r.experience.title for r in results] == ["Search Engine 2.0"]


class TestPeriodOverlap:
    def test_since_excludes_older_records(self, corpus) -> None:
        results = search(corpus, SearchQuery(since="2024-01"))
        assert "Campus Search Engine" not in [r.experience.title for r in results]

    def test_until_excludes_newer_records(self, corpus) -> None:
        results = search(corpus, SearchQuery(until="2023-12"))
        assert [r.experience.title for r in results] == ["Campus Search Engine"]

    def test_ongoing_overlaps_future_windows(self, corpus) -> None:
        results = search(corpus, SearchQuery(since="2025-06"))
        assert "CLI Note Tool" in [r.experience.title for r in results]


def test_limit(corpus) -> None:
    assert len(search(corpus, SearchQuery(limit=2))) == 2


def test_empty_text_returns_all_newest_first(corpus) -> None:
    results = search(corpus, SearchQuery())
    assert len(results) == 3
    ids = [r.experience.id for r in results]
    assert ids == sorted(ids, reverse=True)


def test_matched_fields_reported(corpus) -> None:
    results = search(corpus, SearchQuery(text="inverted index"))
    assert "contribution" in results[0].matched_fields


@pytest.mark.parametrize("bad", ["2024-1", "2024/01", "garbage"])
def test_invalid_period_filter_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        SearchQuery(since=bad)
