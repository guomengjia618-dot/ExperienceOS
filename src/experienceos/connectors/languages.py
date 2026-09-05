"""Shared file-extension -> language mapping for content connectors.

Both the git-repo and project-files connectors estimate language
composition from file extensions via this curated map (no linguist
dependency). Keep the map curated: unknown extensions are never guessed
as languages — a conservative estimate beats a wrong one.
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

# Order-independent; longest suffix match wins via exact lookup.
EXTENSION_LANGUAGES: dict[str, str] = {
    ".py": "Python",
    ".pyw": "Python",
    ".ipynb": "Jupyter Notebook",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".scala": "Scala",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".hh": "C++",
    ".cs": "C#",
    ".m": "Objective-C",
    ".mm": "Objective-C",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".ps1": "PowerShell",
    ".bat": "Batch",
    ".cmd": "Batch",
    ".r": "R",
    ".sql": "SQL",
    ".pl": "Perl",
    ".lua": "Lua",
    ".dart": "Dart",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".erl": "Erlang",
    ".hs": "Haskell",
    ".clj": "Clojure",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".less": "Less",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".md": "Markdown",
    ".rst": "reStructuredText",
    ".tex": "TeX",
}


def count_languages(filenames: list[str]) -> Counter[str]:
    """Count recognized languages for *filenames* (paths or bare names)."""
    counts: Counter[str] = Counter()
    for name in filenames:
        language = EXTENSION_LANGUAGES.get(Path(name).suffix.lower())
        if language is not None:
            counts[language] += 1
    return counts


def prune_walk(root: Path, junk_dirs: frozenset[str], max_files: int) -> list[str]:
    """Walk *root* depth-first, skipping junk directories and symlinks.

    Returns up to *max_files* file paths (as strings) in walk order.
    Directory symlinks are never followed: an import must not escape the
    given project folder or loop through cycles.
    """
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in junk_dirs)
        for name in sorted(filenames):
            files.append(os.path.join(dirpath, name))
            if len(files) >= max_files:
                return files
    return files
