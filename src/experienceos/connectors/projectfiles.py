"""Plain project directory connector: non-git project folders -> drafts.

Completes the input matrix from the project brief: code (git repos and
GitHub) and documents (resumes) were covered; this connector reads a
*project folder without version control* — an unpacked archive, a
downloaded snapshot, a coursework directory.

Honesty rules, same as every connector:

- Title is the folder name; the description is a verbatim excerpt of
  the project's README when one exists, never invented.
- No timeline exists without version control, so the period keeps the
  explicit undated placeholder (``core.models.UNDATED_START``) and the
  draft is tagged ``undated`` — the user fills it in at preview.
- Contribution lists stay empty: file listings say nothing about what
  a person contributed, and ExperienceOS never asserts it.
- Languages come from the shared curated extension map
  (:mod:`experienceos.connectors.languages`); unknown files are ignored.

Walk safety: junk/build directories are pruned, directory symlinks are
never followed, and the scan stops at :data:`MAX_FILES` entries.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from experienceos.connectors.base import ExperienceDraft, parse_source
from experienceos.connectors.languages import count_languages, prune_walk
from experienceos.core.errors import ConnectorError
from experienceos.core.models import (
    UNDATED_START,
    EvidenceKind,
    ExperienceType,
    SourceOrigin,
)

_SCHEME = "project-files"
MAX_FILES = 20000
MAX_DESCRIPTION_LINES = 4
MAX_DESCRIPTION_CHARS = 400

README_CANDIDATES = ("README.md", "README.rst", "README.txt", "README")

JUNK_DIRS = frozenset(
    {
        ".git", ".hg", ".svn", ".tox", ".idea", ".vscode", ".gradle",
        "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
        "node_modules", "bower_components", "vendor",
        "venv", ".venv", "env",
        "build", "dist", "out", "target", "coverage", "htmlcov",
        ".next", ".nuxt",
    }
)

_DESCRIPTION_JUNK_PREFIXES = ("#!",)  # shebangs are plumbing, not description


class ProjectFilesError(ConnectorError):
    """A project directory could not be analyzed."""


class ProjectFilesExtractor:
    """Extract one evidence-backed draft from a plain project directory."""

    name = _SCHEME

    def can_handle(self, source: str) -> bool:
        scheme, payload = parse_source(source)
        if scheme is not None and scheme != _SCHEME:
            return False
        path = Path(payload.strip()).expanduser()
        if not path.is_dir():
            return False
        # schemeless sources that are git repositories belong to the
        # git-repo connector (which registers first); an explicit
        # project-files: scheme always claims the directory
        return not (scheme is None and (path / ".git").exists())

    def extract(self, source: str) -> Iterator[ExperienceDraft]:
        yield self._draft_for(self._directory(source))

    # -- plumbing ---------------------------------------------------------

    def _directory(self, source: str) -> Path:
        scheme, payload = parse_source(source)
        if scheme is not None and scheme != _SCHEME:
            raise ProjectFilesError(
                f"the project-files connector does not handle scheme '{scheme}:'"
            )
        path = Path(payload.strip()).expanduser()
        if not path.is_dir():
            raise ProjectFilesError(f"not a directory: {path}")
        return path.resolve()

    def _draft_for(self, path: Path) -> ExperienceDraft:
        files = prune_walk(path, JUNK_DIRS, MAX_FILES)
        languages = count_languages([Path(name).name for name in files])
        if not languages:
            raise ProjectFilesError(
                f"no recognizable source files in '{path}'; the connector "
                "estimates languages from known file extensions (py, js, "
                "java, go, ...)"
            )
        recognized = sum(languages.values())
        technology = [name for name, _count in languages.most_common()]

        description_lines = _readme_excerpt(path)
        if description_lines:
            description = " ".join(description_lines)
        else:
            description = (
                f"Project directory with {recognized} recognized source "
                f"file(s); no README found"
            )

        return ExperienceDraft.create(
            origin=SourceOrigin.project_files,
            ref=str(path),
            title=path.name,
            type=ExperienceType.personal,
            period={"start": UNDATED_START, "end": None},
            context=(
                f"Project directory containing {recognized} recognized source "
                f"file(s) across {len(languages)} language(s)."
            ),
            description=description,
            technology=technology,
            evidence=[
                {
                    "kind": EvidenceKind.file.value,
                    "location": str(path),
                    "description": "Project directory",
                }
            ],
            tags=["project-files", "undated"],
        )


def _readme_excerpt(path: Path) -> list[str]:
    """First meaningful lines of the project README, verbatim."""
    for name in README_CANDIDATES:
        candidate = path / name
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            try:
                text = candidate.read_text(encoding="gb18030")
            except (OSError, UnicodeDecodeError):
                continue
        lines: list[str] = []
        for line in text.splitlines():
            stripped = line.strip().lstrip("#").strip()
            if not stripped or stripped in _DESCRIPTION_JUNK_PREFIXES:
                continue
            lines.append(stripped)
            if len(lines) >= MAX_DESCRIPTION_LINES:
                break
        if not lines:
            continue
        excerpt = " ".join(lines)
        return [excerpt[:MAX_DESCRIPTION_CHARS]]
    return []
