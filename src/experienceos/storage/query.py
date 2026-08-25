"""In-memory search over loaded experiences.

Scale rationale: a personal knowledge base holds hundreds, not millions,
of records, so scanning in memory is instant and keeps files as the only
source of truth. When corpora grow past ~1k records we will add an FTS
index (see ROADMAP M4); until then correctness beats infrastructure.

Semantics:

- Free-text terms are AND-ed; each term must appear somewhere in the
  record (case-insensitive substring).
- Ranking is a small weighted sum: a hit in the title outweighs one in
  the body. Deterministic tie-break: newer experiences first.
- Filters (type/status/tags/technology/period) are applied before text
  scoring; tag and technology filters are case-insensitive OR within a
  filter, and multiple filters AND together.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from experienceos.core.models import (
    Experience,
    ExperienceType,
    Status,
    is_valid_year_month,
)

# (field getter, weight) pairs used for scoring; order documents intent.
_WEIGHTS: tuple[tuple[str, float], ...] = (
    ("title", 5.0),
    ("tags", 3.0),
    ("technology", 3.0),
    ("contribution", 2.0),
    ("result", 2.0),
    ("challenge", 1.5),
    ("solution", 1.5),
    ("role", 1.0),
    ("context", 1.0),
    ("description", 1.0),
    ("reflection", 1.0),
)


@dataclass(frozen=True)
class SearchQuery:
    text: str = ""
    types: tuple[ExperienceType, ...] = ()
    tags: tuple[str, ...] = ()
    technology: tuple[str, ...] = ()
    status: Status | None = None
    since: str | None = None  # YYYY-MM, inclusive
    until: str | None = None  # YYYY-MM, inclusive
    limit: int | None = None

    def __post_init__(self) -> None:
        for label, value in (("since", self.since), ("until", self.until)):
            if value is not None and not is_valid_year_month(value):
                raise ValueError(f"{label} must be YYYY-MM, got {value!r}")


@dataclass
class SearchResult:
    experience: Experience
    score: float = 0.0
    matched_fields: list[str] = field(default_factory=list)


def _terms(query: SearchQuery) -> list[str]:
    return [t.casefold() for t in query.text.split() if t.strip()]


def _period_overlaps(exp: Experience, since: str | None, until: str | None) -> bool:
    start, end = exp.period.start, exp.period.end or "9999-12"
    return not (until is not None and start > until) and not (
        since is not None and end < since
    )


def _passes_filters(exp: Experience, query: SearchQuery) -> bool:
    if query.status is not None and exp.status != query.status:
        return False
    if query.types and exp.type not in query.types:
        return False
    if query.tags:
        exp_tags = {t.casefold() for t in exp.tags}
        if not exp_tags & {t.casefold() for t in query.tags}:
            return False
    if query.technology:
        exp_tech = {t.casefold() for t in exp.technology}
        if not exp_tech & {t.casefold() for t in query.technology}:
            return False
    return _period_overlaps(exp, query.since, query.until)


def _field_text(exp: Experience, field_name: str) -> str:
    value = getattr(exp, field_name)
    return " ".join(value).casefold() if isinstance(value, list) else value.casefold()


def _score_terms(exp: Experience, terms: list[str]) -> tuple[float, list[str]]:
    """Score = per-term best-field weights, summed and normalized to [0, W].

    A record matches only when every term appears somewhere (any field);
    scoring then rewards terms landing in high-weight fields (title > tags
    and technology > body).
    """
    union = " ".join(_field_text(exp, name) for name, _ in _WEIGHTS)
    if not all(term in union for term in terms):
        return 0.0, []
    total = 0.0
    matched: list[str] = []
    for name, weight in _WEIGHTS:
        text = _field_text(exp, name)
        hits = sum(1 for term in terms if term in text)
        if hits:
            total += weight * hits / len(terms)
            matched.append(name)
    return total, matched


def search(experiences: list[Experience], query: SearchQuery) -> list[SearchResult]:
    """Filter and rank experiences against a query, best first."""
    terms = _terms(query)
    results: list[SearchResult] = []
    for exp in experiences:
        if not _passes_filters(exp, query):
            continue
        if not terms:
            results.append(SearchResult(experience=exp))
            continue
        score, matched = _score_terms(exp, terms)
        if score > 0:
            results.append(SearchResult(experience=exp, score=score, matched_fields=matched))
    # two stable sorts: newest first, then score descending on top of it,
    # so ties in score keep the newer experience first
    results.sort(key=lambda r: r.experience.id, reverse=True)
    results.sort(key=lambda r: r.score, reverse=True)
    if query.limit is not None:
        results = results[: query.limit]
    return results
