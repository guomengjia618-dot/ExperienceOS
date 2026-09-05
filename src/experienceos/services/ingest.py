"""Ingest use cases: source -> drafts -> (confirmed) records.

The import flow is shared plumbing: route the source through the
registry, wire optional AI capability into whatever connector declares
it (no per-connector special cases in the CLI), and persist confirmed
drafts under the same never-overwrite rule the API creation path uses.
"""

from __future__ import annotations

from experienceos.connectors import (
    AcceptsMaterialExtractor,
    AuthoredExtractor,
    ExperienceDraft,
    default_registry,
)
from experienceos.core.errors import StorageError, ValidationError
from experienceos.storage import ExperienceStore


def resolve_drafts(
    source: str,
    *,
    author: str | None = None,
    material_extractor: object | None = None,
) -> tuple[str, list[ExperienceDraft]]:
    """Find the connector for *source* and extract its drafts.

    ``material_extractor`` (typically ``ai.extraction.AIExtraction``) is
    wired into any connector implementing ``AcceptsMaterialExtractor``;
    connectors that don't need it are unaffected. Returns the connector
    name (for reporting) and the extracted drafts.
    """
    extractor = default_registry.find_handler(source)
    if material_extractor is not None and isinstance(
        extractor, AcceptsMaterialExtractor
    ):
        extractor.set_material_extractor(material_extractor)  # type: ignore[attr-defined]
    if author is not None:
        if not isinstance(extractor, AuthoredExtractor):
            raise ValidationError(
                f"connector '{extractor.name}' does not support --author"
            )
        drafts = list(extractor.extract_for_author(source, author))
    else:
        drafts = list(extractor.extract(source))
    return extractor.name, drafts


def save_drafts(store: ExperienceStore, drafts: list[ExperienceDraft]) -> list[str]:
    """Persist confirmed drafts; creation never overwrites records.

    Every id is checked before anything is written, so a mid-batch
    conflict aborts the whole import instead of leaving a partial save.
    """
    conflicts = [
        draft.experience.id for draft in drafts if store.exists(draft.experience.id)
    ]
    if conflicts:
        raise StorageError(
            f"record id conflict: {', '.join(conflicts[:3])} already exists "
            f"({len(conflicts)} of {len(drafts)} conflict; import never "
            "overwrites records, nothing was saved)"
        )
    saved_ids: list[str] = []
    for draft in drafts:
        store.save(draft.experience)
        saved_ids.append(draft.experience.id)
    return saved_ids
