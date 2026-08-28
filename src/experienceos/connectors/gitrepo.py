"""Local git repository connector (#008).

The connector analyzes a local checkout with read-only ``git`` plumbing
(``rev-parse``, ``log``, ``ls-files``, ``config``, ``remote``): it never
writes to the repository, never touches the network, and never invents
achievements beyond what the commit history shows.

Attribution follows the same rule as the GitHub connector: when ``--author``
is omitted, the repository's ``git config user.email`` identifies "me".
Languages are estimated from tracked-file extensions via a built-in map —
no linguist dependency.
"""

from __future__ import annotations

import re
import statistics
import subprocess
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from experienceos.connectors.base import ExperienceDraft, parse_source
from experienceos.core.errors import ConnectorError
from experienceos.core.models import EvidenceKind, ExperienceType, SourceOrigin

GIT_BINARY = "git"
GIT_TIMEOUT_SECONDS = 60
MAX_CONTRIBUTIONS = 30
MAX_LANGUAGES = 8

_SCHEME = "git-repo"
_GITHUB_REMOTE_RE = re.compile(
    r"^(?:https?://|ssh://git@|git@)github\.com[/:]"
    r"(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)

# Built-in file-extension -> language map (keep curated, no linguist dep).
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


class GitRepoError(ConnectorError):
    """A local git repository could not be analyzed."""


class GitRepoExtractor:
    """Extract one evidence-backed draft from a local git checkout."""

    name = _SCHEME

    def can_handle(self, source: str) -> bool:
        scheme, payload = parse_source(source)
        if scheme is not None and scheme != _SCHEME:
            return False
        path = Path(payload.strip()).expanduser()
        return path.is_dir() and (path / ".git").exists()

    def extract(self, source: str) -> Iterator[ExperienceDraft]:
        yield self._draft_for(self._repository_path(source), author=None)

    def extract_for_author(self, source: str, author: str) -> Iterator[ExperienceDraft]:
        author = author.strip()
        if not author:
            raise GitRepoError("--author must not be empty")
        yield self._draft_for(self._repository_path(source), author=author)

    # -- plumbing ---------------------------------------------------------

    def _run(self, path: Path, *args: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [GIT_BINARY, "-C", str(path), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=GIT_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as exc:
            raise GitRepoError(
                "git executable not found; install Git to use the git-repo connector"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise GitRepoError(f"git command timed out in '{path}'") from exc

    def _git(self, path: Path, *args: str) -> str:
        result = self._run(path, *args)
        if result.returncode != 0:
            raise GitRepoError(
                f"git {args[0]} failed in '{path}': {_first_line(result.stderr)}"
            )
        return result.stdout

    def _repository_path(self, source: str) -> Path:
        scheme, payload = parse_source(source)
        if scheme is not None and scheme != _SCHEME:
            raise GitRepoError(f"the git-repo connector does not handle scheme '{scheme}:'")
        path = Path(payload.strip()).expanduser()
        if not path.is_dir():
            raise GitRepoError(f"not a directory: {path}")
        resolved = path.resolve()
        if not (resolved / ".git").exists():
            raise GitRepoError(f"not a git repository (no .git found): {resolved}")
        self._git(resolved, "rev-parse", "--git-dir")
        return resolved

    def _configured_email(self, path: Path) -> str:
        result = self._run(path, "config", "user.email")
        email = result.stdout.strip() if result.returncode == 0 else ""
        if not email:
            raise GitRepoError(
                f"no --author given and 'git config user.email' is not set for "
                f"'{path}'; pass --author <email> to attribute the activity"
            )
        return email

    def _draft_for(self, path: Path, author: str | None) -> ExperienceDraft:
        head = self._run(path, "rev-parse", "--verify", "-q", "HEAD")
        if head.returncode != 0:
            raise GitRepoError(f"'{path}' has no commits yet")
        dates = [
            line.strip()
            for line in self._git(path, "log", "--pretty=format:%aI").splitlines()
            if line.strip()
        ]
        if not dates:
            raise GitRepoError(f"'{path}' has no commits yet")
        if author is None:
            author = self._configured_email(path)
        months = {value[:7] for value in dates if len(value) >= 7}
        total_commits = len(dates)

        authored, subjects, churn = self._author_activity(path, author)
        if authored == 0:
            raise GitRepoError(
                f"no commits found for author '{author}' in '{path}'; "
                "git matches --author against 'Name <email>'"
            )

        languages = self._language_counts(path)
        evidence: list[dict[str, str]] = [
            {
                "kind": EvidenceKind.repo.value,
                "location": str(path),
                "description": "Local git repository",
            }
        ]
        github_url = self._github_remote_url(path)
        if github_url is not None:
            evidence.append(
                {
                    "kind": EvidenceKind.url.value,
                    "location": github_url,
                    "description": "GitHub remote (origin)",
                }
            )

        recognized = sum(languages.values())
        technology = [name for name, _count in languages.most_common(MAX_LANGUAGES)]
        contributions: list[str] = []
        seen: set[str] = set()
        for subject in subjects:  # newest first, deduplicated
            key = subject.casefold()
            if key in seen:
                continue
            seen.add(key)
            contributions.append(subject)
            if len(contributions) >= MAX_CONTRIBUTIONS:
                break

        context = (
            f"Local git activity for {author}: {authored} commit(s) "
            f"out of {total_commits} total."
        )
        if len(contributions) < len(set(s.casefold() for s in subjects)):
            context += f" Showing the latest {len(contributions)} commit subjects."

        result: list[str] = [f"Authored {authored} of {total_commits} commits"]
        if churn:
            result.append(
                f"Median change size: {round(statistics.median(churn))} "
                "lines per commit"
            )
        if languages:
            top = ", ".join(
                f"{name} {round(100 * count / recognized)}%"
                for name, count in languages.most_common(3)
            )
            result.append(f"Languages by tracked files: {top}")

        return ExperienceDraft.create(
            origin=SourceOrigin.git_repo,
            ref=str(path),
            title=path.name,
            type=ExperienceType.personal,
            period={"start": min(months), "end": max(months)},
            context=context,
            description=f"Imported from local git repository at {path}",
            technology=technology,
            contribution=contributions,
            result=result,
            evidence=evidence,
            tags=["git"],
        )

    def _author_activity(
        self, path: Path, author: str
    ) -> tuple[int, list[str], list[int]]:
        """Return (commit count, newest-first subjects, per-commit churn)."""
        output = self._git(
            path,
            "log",
            "--author",
            author,
            "--pretty=format:%H%x01%s",
            "--numstat",
        )
        authored = 0
        subjects: list[str] = []
        churn: list[int] = []
        for line in output.splitlines():
            if "\x01" in line:
                authored += 1
                subjects.append(line.split("\x01", 1)[1].strip())
                continue
            parts = line.split("\t")
            if len(parts) >= 2 and _count_or_none(parts[0]) is not None:
                added = _count_or_none(parts[0]) or 0
                removed = _count_or_none(parts[1]) or 0
                churn.append(added + removed)
        return authored, subjects, churn

    def _language_counts(self, path: Path) -> Counter[str]:
        listing = self._git(path, "ls-files", "-z")
        counts: Counter[str] = Counter()
        for name in listing.split("\0"):
            if not name:
                continue
            language = EXTENSION_LANGUAGES.get(Path(name).suffix.lower())
            if language is not None:
                counts[language] += 1
        return counts

    def _github_remote_url(self, path: Path) -> str | None:
        result = self._run(path, "remote", "get-url", "origin")
        if result.returncode != 0:
            return None
        match = _GITHUB_REMOTE_RE.fullmatch(result.stdout.strip())
        if match is None:
            return None
        return f"https://github.com/{match.group('owner')}/{match.group('repo')}"


def _count_or_none(value: str) -> int | None:
    return int(value) if value.isdigit() else None


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else "unknown error"
