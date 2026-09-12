"""SQLite FTS5 search index (#022): a rebuildable derivative.

ADR D1 stays intact: the JSON files are the source of truth; this index
is a pure cache. Deleting ``<home>/search.index`` costs nothing — the
next rebuild recreates it, and every query path falls back to the
in-memory scan whenever the index is absent or the library is smaller
than the threshold (services layer decides).

Tokenizer: FTS5 ``unicode61`` plus a CJK unigram split — contiguous
CJK runs are spaced out so each character becomes its own token
("搜索引擎" -> "搜 索 引 擎"). The same transform runs on queries, so
CJK AND-queries behave like substring search. Bigram tokenization was
evaluated and deferred: unigrams keep single-character queries working
and cost one extra join row per character — plenty at personal-library
scale.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from experienceos.core.models import Experience

INDEX_FILENAME = "search.index"
DEFAULT_THRESHOLD = 1000
FETCH_LIMIT = 500  # FTS hits fetched before in-memory filters narrow them
BUSY_TIMEOUT_MS = 5000  # wait for a concurrent writer instead of failing

_CJK_RE = re.compile(r"([\u4e00-\u9fff])")

logger = logging.getLogger("experienceos.storage")


def index_path(home: Path) -> Path:
    return Path(home) / INDEX_FILENAME


def index_exists(home: Path) -> bool:
    return index_path(home).exists()


def _connect(path: Path) -> sqlite3.Connection:
    """One index connection with a lock-wait budget.

    ``timeout`` and the PRAGMA configure the same SQLite busy handler;
    stating both keeps the intent visible regardless of which API a
    caller reads. Without it a concurrent writer used to surface as an
    immediate "database is locked" and the update was silently dropped.
    """
    connection = sqlite3.connect(path, timeout=BUSY_TIMEOUT_MS / 1000)
    connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    return connection


def delete_index(home: Path) -> bool:
    path = index_path(home)
    if not path.exists():
        return False
    path.unlink()
    return True


def build_index(home: Path, experiences: Iterable[Experience]) -> int:
    """(Re)create the index from *experiences*; return the record count."""
    path = index_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = _connect(path)
    try:
        connection.execute("DROP TABLE IF EXISTS experiences")
        connection.execute(
            "CREATE VIRTUAL TABLE experiences USING fts5("
            "id UNINDEXED, title, body, tokenize='unicode61')"
        )
        count = 0
        for experience in experiences:
            connection.execute(
                "INSERT INTO experiences (id, title, body) VALUES (?, ?, ?)",
                (experience.id, _tokenize(experience.title), _tokenize(_flatten(experience))),
            )
            count += 1
        connection.commit()
    finally:
        connection.close()
    return count


def index_doc_count(home: Path) -> int | None:
    """Live row count of an existing index; None when absent or unreadable.

    The services layer compares this against the number of record files
    to detect a silently stale index (a failed best-effort upsert, an
    index built before an import) and rebuild from the source of truth.
    An index from an older build without the expected table also reads
    as None, which triggers the same one-time rebuild.
    """
    if not index_exists(home):
        return None
    try:
        connection = _connect(index_path(home))
        try:
            row = connection.execute("SELECT count(*) FROM experiences").fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return None
    return int(row[0]) if row is not None else None


def upsert_experience(home: Path, experience: Experience) -> bool:
    """Refresh one record's row in an existing index; best-effort.

    Keeps the index in step with ``store.save`` so records created or
    edited after a rebuild stay searchable. Never raises: the index is a
    cache, and a failed update only means it is stale until the next
    rebuild (callers fall back to the in-memory scan when needed).
    """
    if not index_exists(home):
        return False
    try:
        connection = _connect(index_path(home))
        try:
            # FTS5 tables have no UNIQUE constraint on `id`, so an upsert
            # is delete-then-insert inside one transaction.
            connection.execute(
                "DELETE FROM experiences WHERE id = ?", (experience.id,)
            )
            connection.execute(
                "INSERT INTO experiences (id, title, body) VALUES (?, ?, ?)",
                (experience.id, _tokenize(experience.title), _tokenize(_flatten(experience))),
            )
            connection.commit()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        logger.warning("could not update search index for %s: %s", experience.id, exc)
        return False
    return True


def remove_experience(home: Path, experience_id: str) -> bool:
    """Drop one record's row from an existing index; best-effort."""
    if not index_exists(home):
        return False
    try:
        connection = _connect(index_path(home))
        try:
            connection.execute("DELETE FROM experiences WHERE id = ?", (experience_id,))
            connection.commit()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        logger.warning("could not remove %s from search index: %s", experience_id, exc)
        return False
    return True


def fts_search(home: Path, text: str, limit: int | None = None) -> list[str]:
    """Ranked experience ids for *text*; empty query or index -> []."""
    terms = _tokenize(text).split()
    if not terms or not index_exists(home):
        return []
    connection = _connect(index_path(home))
    try:
        rows = connection.execute(
            "SELECT id FROM experiences WHERE experiences MATCH ? "
            "ORDER BY rank LIMIT ?",
            (" ".join(terms), min(limit or FETCH_LIMIT, FETCH_LIMIT)),
        ).fetchall()
    except sqlite3.OperationalError:
        return []  # malformed MATCH string etc. — callers fall back safely
    finally:
        connection.close()
    return [row[0] for row in rows]


def _flatten(experience: Experience) -> str:
    parts = [
        experience.title,
        experience.context,
        experience.role,
        experience.description,
        experience.reflection,
        *experience.technology,
        *experience.contribution,
        *experience.challenge,
        *experience.solution,
        *experience.result,
        *experience.tags,
        *(evidence.location for evidence in experience.evidence),
    ]
    return " ".join(part for part in parts if part)


def _tokenize(text: str) -> str:
    """Space out CJK characters so unicode61 indexes each as a token."""
    return _CJK_RE.sub(r" \1 ", text)
