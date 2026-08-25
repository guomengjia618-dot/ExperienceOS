"""Domain model tests: validation rules, cleaning, round-trips."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from experienceos.core.models import (
    SCHEMA_VERSION,
    Evidence,
    Experience,
    Period,
    Source,
    SourceOrigin,
    Status,
    utcnow,
)


def test_new_generates_valid_record(make_experience) -> None:
    exp = make_experience()
    assert exp.id.startswith("exp_") and len(exp.id) == 30
    assert exp.schema_version == SCHEMA_VERSION
    assert exp.status is Status.active
    assert exp.source.origin is SourceOrigin.manual
    assert exp.source.created_by == "user"
    assert exp.created_at <= exp.updated_at


class TestPeriod:
    def test_valid(self) -> None:
        period = Period(start="2024-01", end="2024-06")
        assert not period.is_ongoing
        assert period.display() == "2024-01 ~ 2024-06"

    def test_ongoing_when_end_missing(self) -> None:
        assert Period(start="2024-01").is_ongoing
        assert "present" in Period(start="2024-01").display()

    @pytest.mark.parametrize("bad", ["2024-13", "2024-1", "24-01", "2024/01", "202401"])
    def test_rejects_malformed_months(self, bad: str) -> None:
        with pytest.raises(PydanticValidationError):
            Period(start=bad)

    def test_rejects_end_before_start(self) -> None:
        with pytest.raises(PydanticValidationError):
            Period(start="2024-06", end="2024-01")

    def test_assignment_validates(self) -> None:
        period = Period(start="2024-01")
        with pytest.raises(PydanticValidationError):
            period.start = "2025-13"


class TestExperienceValidation:
    def test_rejects_empty_title(self) -> None:
        with pytest.raises(PydanticValidationError):
            Experience.new(title="  ", type="personal", period={"start": "2024-01"})

    def test_rejects_unknown_keys(self) -> None:
        with pytest.raises(PydanticValidationError):
            Experience.from_dict(
                {
                    "id": "exp_" + "0" * 26,
                    "title": "x",
                    "type": "personal",
                    "period": {"start": "2024-01"},
                    "typo_field": 1,
                }
            )

    def test_rejects_bad_id(self) -> None:
        with pytest.raises(PydanticValidationError):
            Experience.new(
                title="x",
                type="personal",
                period={"start": "2024-01"},
                id="exp_not_a_ulid",
            )

    def test_rejects_future_schema_version(self) -> None:
        with pytest.raises(PydanticValidationError):
            Experience.from_dict(
                {
                    "schema_version": 99,
                    "id": "exp_" + "0" * 26,
                    "title": "x",
                    "type": "personal",
                    "period": {"start": "2024-01"},
                }
            )

    def test_assignment_validates_enum(self) -> None:
        exp = Experience.new(title="x", type="personal", period={"start": "2024-01"})
        with pytest.raises(PydanticValidationError):
            exp.status = "bogus"  # type: ignore[assignment]
        exp.status = Status.draft
        assert exp.status is Status.draft


class TestListCleaning:
    def test_strips_and_drops_empty_and_dupes(self, make_experience) -> None:
        exp = make_experience(
            title="x",
            technology=[" Python ", "", "python", "FastAPI"],
            tags=["backend", "Backend", " ai "],
        )
        assert exp.technology == ["Python", "FastAPI"]
        assert exp.tags == ["backend", "ai"]

    def test_accepts_bare_string_as_single_item(self, make_experience) -> None:
        exp = make_experience(tags="backend")
        assert exp.tags == ["backend"]


class TestEvidenceAndSource:
    def test_evidence_generates_id(self) -> None:
        evidence = Evidence(location="https://github.com/org/repo")
        assert evidence.id.startswith("ev_")

    def test_evidence_requires_location(self) -> None:
        with pytest.raises(PydanticValidationError):
            Evidence(location="")

    def test_source_origin_import_alias(self) -> None:
        source = Source(origin="import")
        assert source.origin is SourceOrigin.import_


def test_roundtrip_dict_is_stable(make_experience) -> None:
    exp = make_experience(
        title="Roundtrip",
        contribution=["built the thing"],
        evidence=[{"kind": "repo", "location": "org/repo"}],
    )
    data = exp.to_dict()
    restored = Experience.from_dict(data)
    assert restored == exp
    # datetimes serialized as ISO 8601 strings on the wire
    assert isinstance(data["created_at"], str)
    assert data["created_at"].endswith("+00:00") or data["created_at"].endswith("Z")
    assert restored.created_at.tzinfo is not None


def test_utcnow_is_timezone_aware() -> None:
    assert utcnow().tzinfo is not None
