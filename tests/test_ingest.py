"""Ingest use-case tests (#028): the batch save is all-or-nothing."""

from __future__ import annotations

import pytest

from experienceos.connectors import ExperienceDraft
from experienceos.core.errors import StorageError
from experienceos.services.ingest import save_drafts
from experienceos.storage import ExperienceStore


@pytest.fixture
def drafts() -> list[ExperienceDraft]:
    return [
        ExperienceDraft.create(
            origin="import",
            ref="fake:source",
            title="Imported A",
            type="personal",
            period={"start": "2024-01"},
        ),
        ExperienceDraft.create(
            origin="import",
            ref="fake:source",
            title="Imported B",
            type="work",
            period={"start": "2023-05", "end": "2024-02"},
        ),
    ]


class TestSaveDrafts:
    def test_saves_everything_when_no_conflicts(
        self, home, drafts: list[ExperienceDraft]
    ) -> None:
        store = ExperienceStore(home)
        saved = save_drafts(store, drafts)
        assert saved == [draft.experience.id for draft in drafts]
        assert {exp.title for exp in store.list_all()} == {"Imported A", "Imported B"}

    def test_conflict_aborts_without_partial_save(
        self, home, drafts: list[ExperienceDraft]
    ) -> None:
        store = ExperienceStore(home)
        store.save(drafts[1].experience)  # conflict on the SECOND draft
        with pytest.raises(StorageError) as excinfo:
            save_drafts(store, drafts)
        assert "nothing was saved" in str(excinfo.value)
        # the first draft (no conflict) must not have been persisted either
        assert store.exists(drafts[0].experience.id) is False
        assert len(store.list_all()) == 1

    def test_reimporting_identical_drafts_conflicts(
        self, home, drafts: list[ExperienceDraft]
    ) -> None:
        store = ExperienceStore(home)
        save_drafts(store, drafts)
        with pytest.raises(StorageError):
            save_drafts(store, drafts)
        assert len(store.list_all()) == 2
