"""Knowledge-base statistics (#017).

Pure functions shared by the ``stats`` and ``profile`` commands and,
from M4 on, the API service layer. Everything here counts what is in
the records — nothing is inferred beyond the data.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass

from experienceos.core.guardrails import find_unsupported_claims
from experienceos.core.models import Experience


@dataclass(frozen=True)
class TechSpan:
    """One technology's footprint across the knowledge base."""

    name: str
    first: str  # earliest period.start month it appears in
    last: str  # latest month (start or end) it appears in
    records: int
    ongoing: bool  # still used by at least one open-ended record


def technology_timeline(experiences: list[Experience]) -> list[TechSpan]:
    """Technologies ordered by first use, with their month span.

    Technologies merge case-insensitively — one row per technology, like
    every other stats view; the first-seen spelling is displayed.
    """
    months_by_key: dict[str, list[str]] = {}
    display: dict[str, str] = {}
    counts: Counter[str] = Counter()
    ongoing: set[str] = set()
    for exp in experiences:
        months = [exp.period.start] + ([exp.period.end] if exp.period.end else [])
        for tech in exp.technology:
            key = tech.casefold()
            display.setdefault(key, tech)
            months_by_key.setdefault(key, []).extend(months)
            counts[key] += 1
            if exp.period.end is None:
                ongoing.add(key)
    result = [
        TechSpan(
            name=display[key],
            first=min(months),
            last=max(months),
            records=counts[key],
            ongoing=key in ongoing,
        )
        for key, months in months_by_key.items()
    ]
    return sorted(result, key=lambda span: (span.first, span.name.casefold()))


def technology_cooccurrence(
    experiences: list[Experience], top_n: int = 10
) -> list[tuple[str, str, int]]:
    """Most frequent technology pairs within a single record."""
    pairs: Counter[tuple[str, str]] = Counter()
    for exp in experiences:
        names = sorted({tech.casefold() for tech in exp.technology})
        for i, first in enumerate(names):
            for second in names[i + 1 :]:
                pairs[(first, second)] += 1
    return [
        (first, second, count)
        for (first, second), count in pairs.most_common(top_n)
    ]


def evidence_coverage_by_year(
    experiences: list[Experience],
) -> list[tuple[str, int, int]]:
    """(year, records with evidence, total records) by period start year,
    oldest first."""
    totals: Counter[str] = Counter()
    covered: Counter[str] = Counter()
    for exp in experiences:
        year = exp.period.start[:4]
        totals[year] += 1
        if exp.evidence:
            covered[year] += 1
    return [
        (year, covered[year], totals[year]) for year in sorted(totals)
    ]


def aggregate_stats(experiences: list[Experience]) -> dict:
    """Machine-readable summary backing `stats --json` (and the API)."""
    total = len(experiences)
    with_evidence = sum(1 for exp in experiences if exp.evidence)
    type_counts = Counter(exp.type.value for exp in experiences)
    status_counts = Counter(exp.status.value for exp in experiences)
    tech_counts = Counter(
        tech.casefold() for exp in experiences for tech in exp.technology
    )
    return {
        "total": total,
        "with_evidence": with_evidence,
        "evidence_coverage": round(with_evidence / total, 4) if total else 0.0,
        "with_reflection": sum(1 for exp in experiences if exp.reflection),
        "by_type": dict(type_counts.most_common()),
        "by_status": dict(status_counts.most_common()),
        "top_technologies": [name for name, _count in tech_counts.most_common(10)],
        "unsupported_claims": sum(
            len(find_unsupported_claims(exp)) for exp in experiences
        ),
        "median_technologies_per_record": (
            statistics.median(len(exp.technology) for exp in experiences)
            if total
            else 0
        ),
    }
