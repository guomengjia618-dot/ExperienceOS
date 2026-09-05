"""Interview conversation support (#011).

The extraction pipeline itself lives in :mod:`experienceos.ai.extraction`
(shared with the PDF resume path); this module keeps only what is
specific to the interactive conversation: the intake system prompt and
transcript recovery. The CLI owns every console interaction.

Privacy invariant: the transcript stays in memory during the
conversation; it only ever reaches the configured provider and, when
extraction fails twice, the local ``<home>/drafts/`` folder as a
recovery aid. Nothing is uploaded anywhere else.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from experienceos.ai.extraction import (
    MAX_EVIDENCE,
    UNDATED_START,
    AIExtraction,
    build_extraction_messages,
    collect_evidence_candidates,
    draft_from_extraction,
    parse_extraction_json,
)
from experienceos.ai.prompts import INTAKE_INTERVIEW_PROMPT_V1

__all__ = [
    "MAX_EVIDENCE",
    "UNDATED_START",
    "AIExtraction",
    "build_extraction_messages",
    "collect_evidence_candidates",
    "draft_from_extraction",
    "interview_system_prompt",
    "parse_extraction_json",
    "save_transcript",
]


def interview_system_prompt(language: str) -> str:
    """Rendered intake-interview system prompt (#011)."""
    return INTAKE_INTERVIEW_PROMPT_V1.format(language=language)


def save_transcript(
    home: Path, transcript: list[tuple[str, str]], model: str
) -> Path:
    """Persist a failed interview to ``<home>/drafts/`` for later retry."""
    drafts_dir = Path(home) / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    _ensure_gitignore(drafts_dir.parent)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = drafts_dir / f"interview-{stamp}.md"
    body = "\n".join(f"**{role}**: {text}\n" for role, text in transcript)
    path.write_text(
        f"# Interview transcript (extraction failed, kept for retry)\n\n"
        f"Model: ai:{model}\n\n{body}\n",
        encoding="utf-8",
    )
    return path


def _ensure_gitignore(home: Path) -> None:
    """Suggest keeping drafts out of version control when home is a repo."""
    if not (home / ".git").exists():
        return
    gitignore = home / ".gitignore"
    try:
        existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
        if "drafts/" not in existing.splitlines():
            gitignore.write_text(
                existing.rstrip("\n") + "\ndrafts/\n", encoding="utf-8"
            )
    except OSError:  # pragma: no cover - best-effort suggestion only
        pass
