"""ULID generation invariants: format, uniqueness, monotonic ordering."""

from __future__ import annotations

import re

import pytest

from experienceos.core.ulid import new_ulid

_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def test_format_is_26_char_crockford_base32() -> None:
    assert _ULID_RE.match(new_ulid())


def test_unique_across_many_generations() -> None:
    ids = [new_ulid() for _ in range(5000)]
    assert len(set(ids)) == len(ids)


def test_lexicographic_order_matches_generation_order() -> None:
    ids = [new_ulid() for _ in range(1000)]
    assert ids == sorted(ids)


def test_monotonic_within_same_millisecond() -> None:
    ids = [new_ulid() for _ in range(100)]  # far faster than 1/ms
    assert ids == sorted(ids)


@pytest.mark.parametrize("invalid", ["", "abc", "l" * 26, "I" * 26, "0" * 27])
def test_format_regex_rejects_non_ulid_strings(invalid: str) -> None:
    # documents the charset contract used by Experience.id validation
    assert not _ULID_RE.match(invalid)
