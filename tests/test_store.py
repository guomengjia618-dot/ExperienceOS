"""Storage layer tests: atomicity, corruption tolerance, id resolution."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from experienceos.core.errors import AmbiguousIdError, NotFoundError, StorageError
from experienceos.storage import ExperienceStore


def test_save_creates_pretty_json_file(store: ExperienceStore, make_experience) -> None:
    exp = make_experience(title="Stored")
    path = store.save(exp)
    assert path == store.experiences_dir / f"{exp.id}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["title"] == "Stored"
    assert raw["schema_version"] == 1


def test_save_bumps_updated_at(store: ExperienceStore, make_experience) -> None:
    exp = make_experience()
    store.save(exp)
    first = exp.updated_at
    time.sleep(0.002)
    store.save(exp)
    assert exp.updated_at > first


def test_save_leaves_no_temp_files(store: ExperienceStore, make_experience) -> None:
    store.save(make_experience())
    leftovers = list(store.experiences_dir.glob("*.tmp"))
    assert leftovers == []


def test_load_roundtrip(store: ExperienceStore, make_experience) -> None:
    exp = make_experience(title="Roundtrip", contribution=["did a thing"])
    store.save(exp)
    loaded = store.load(exp.id)
    assert loaded == exp


def test_load_missing_raises_not_found(store: ExperienceStore) -> None:
    with pytest.raises(NotFoundError):
        store.load("exp_" + "0" * 26)


def test_load_corrupt_raises_storage_error(store: ExperienceStore) -> None:
    bad_id = "exp_" + "0" * 26
    store.experiences_dir.mkdir(parents=True, exist_ok=True)
    (store.experiences_dir / f"{bad_id}.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(StorageError):
        store.load(bad_id)


def test_list_all_skips_corrupt_files(store: ExperienceStore, make_experience) -> None:
    good = make_experience(title="Good")
    store.save(good)
    (store.experiences_dir / "exp_broken0000000000000000.json").write_text(
        "{ not json", encoding="utf-8"
    )
    loaded = store.list_all()
    assert [e.id for e in loaded] == [good.id]


def test_list_all_newest_first(store: ExperienceStore, make_experience) -> None:
    ids = []
    for i in range(5):
        exp = make_experience(title=f"exp {i}")
        store.save(exp)
        ids.append(exp.id)
        time.sleep(0.002)  # ensure distinct ULID timestamps
    assert [e.id for e in store.list_all()] == list(reversed(ids))


def test_validate_reports_issues(store: ExperienceStore, make_experience) -> None:
    store.save(make_experience())
    broken = store.experiences_dir / "exp_broken0000000000000000.json"
    broken.write_text("{ not json", encoding="utf-8")
    issues = store.validate()
    assert len(issues) == 1
    assert issues[0].path == broken


def test_delete(store: ExperienceStore, make_experience) -> None:
    exp = make_experience()
    store.save(exp)
    assert store.delete(exp.id) is True
    assert not store.exists(exp.id)
    assert store.delete(exp.id) is False


def test_scratch_edit_files_are_ignored(store: ExperienceStore, make_experience) -> None:
    exp = make_experience()
    store.save(exp)
    (store.experiences_dir / f".{exp.id}.edit.tmp").write_text("{}", encoding="utf-8")
    assert [e.id for e in store.list_all()] == [exp.id]
    assert store.validate() == []


class TestResolve:
    def test_expands_unique_prefix(self, store: ExperienceStore, make_experience) -> None:
        exp = make_experience()
        store.save(exp)
        assert store.resolve(exp.id[:12]) == exp.id

    def test_bare_prefix_gets_exp_added(self, store, make_experience) -> None:
        exp = make_experience()
        store.save(exp)
        assert store.resolve(exp.id[4:12]) == exp.id

    def test_unknown_prefix_raises(self, store: ExperienceStore) -> None:
        with pytest.raises(NotFoundError):
            store.resolve("exp_zzzz")

    def test_ambiguous_prefix_raises(self, store: ExperienceStore, make_experience) -> None:
        for _ in range(2):
            store.save(make_experience())
        with pytest.raises(AmbiguousIdError):
            store.resolve("exp")


def test_works_without_experiences_dir(tmp_path: Path) -> None:
    store = ExperienceStore(tmp_path / "nowhere")
    assert store.list_all() == []
    assert store.all_ids() == []
    assert store.validate() == []
