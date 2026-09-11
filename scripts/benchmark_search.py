#!/usr/bin/env python3
"""Benchmark in-memory search vs the FTS5 index (#022).

Generates synthetic libraries (default 1k / 5k / 10k records) in a
temporary home, builds the index once per size, and times both query
paths over a mixed CN/EN query set. Usage:

    python scripts/benchmark_search.py [--sizes 1000,5000,10000]

Expectation to validate: below the threshold
(``services.experiences``/``fts.DEFAULT_THRESHOLD``) the in-memory scan
is fine; at larger scale the FTS path wins on text queries. Nothing is
written outside a temp directory.
"""

from __future__ import annotations

import argparse
import shutil
import statistics
import tempfile
import time
from pathlib import Path

from experienceos.core.models import Experience
from experienceos.storage import SearchQuery, search
from experienceos.storage.fts import build_index, fts_search

_QUERIES = ["search", "kubernetes", "支付", "pipeline latency", "搜索引擎"]

_TOPICS_EN = ("search engine", "billing pipeline", "data platform", "mobile app")
_TOPICS_CN = ("支付网关", "搜索引擎", "日志平台", "推荐系统")
_TECH = ("Python", "Go", "Kubernetes", "MySQL", "Kafka", "Redis", "TypeScript")


def _make_record(index: int) -> Experience:
    topic_en = _TOPICS_EN[index % len(_TOPICS_EN)]
    topic_cn = _TOPICS_CN[index % len(_TOPICS_CN)]
    year = 2015 + (index % 10)
    month = 1 + (index % 12)
    tech = [_TECH[(index + offset) % len(_TECH)] for offset in range(3)]
    return Experience.new(
        title=f"{topic_en.title()} {index}",
        type="personal",
        period={"start": f"{year}-{month:02d}", "end": f"{year + 1}-{month:02d}"},
        description=f"{topic_en} / {topic_cn} project number {index}",
        technology=tech,
        contribution=[f"built component {index} of the {topic_en}"],
        result=["latency p99 100ms", f"served {10 * index} requests"],
    )


def _time_memory(home: Path, rounds: int) -> float:
    store_samples: list[float] = []
    from experienceos.storage import ExperienceStore

    experiences = ExperienceStore(home).list_all()
    for _ in range(rounds):
        for text in _QUERIES:
            started = time.perf_counter()
            search(experiences, SearchQuery(text=text))
            store_samples.append(time.perf_counter() - started)
    return statistics.median(store_samples) * 1000


def _time_fts(home: Path, rounds: int) -> float:
    samples: list[float] = []
    for _ in range(rounds):
        for text in _QUERIES:
            started = time.perf_counter()
            fts_search(home, text)
            samples.append(time.perf_counter() - started)
    return statistics.median(samples) * 1000


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sizes", default="1000,5000,10000",
        help="Comma-separated record counts (default: 1000,5000,10000)",
    )
    parser.add_argument("--rounds", type=int, default=5, help="Timing rounds per query")
    parser.add_argument("--keep", action="store_true", help="Keep the temp home")
    args = parser.parse_args()
    sizes = [int(size) for size in args.sizes.split(",") if size.strip()]

    home = Path(tempfile.mkdtemp(prefix="experienceos-bench-"))
    try:
        print(f"{'records':>8} | {'memory (ms)':>12} | {'fts (ms)':>10} | {'winner':>8}")
        print("-" * 52)
        for size in sizes:
            experiences = [_make_record(i) for i in range(size)]
            build_index(home, experiences)
            memory_ms = _time_memory(home, args.rounds)
            fts_ms = _time_fts(home, args.rounds)
            winner = "fts" if fts_ms < memory_ms else "memory"
            print(f"{size:>8} | {memory_ms:>12.1f} | {fts_ms:>10.1f} | {winner:>8}")
    finally:
        if args.keep:
            print(f"home kept at {home}")
        else:
            shutil.rmtree(home, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
