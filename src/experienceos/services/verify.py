"""Evidence verification (P1): ask the network whether evidence holds up.

``experienceos verify`` re-reads each record's evidence and checks the
GitHub REST API for repositories, commits and pull requests the records
claim as proof. It verifies **existence**, reports authorship as plain
data, and never upgrades a record's content by itself — verification is
a mirror, not a mutator.

Scope is deliberately honest:

- GitHub URLs are classified (repo / commit / pull) and checked via the
  API; deep paths (blob/tree) verify at repository granularity and say
  so.
- Other external URLs get an existence probe only.
- Local paths (doc/file/image kinds) are skipped: the local filesystem,
  not the network, is their source of truth.

A 404 marks evidence ``missing``; any other API failure marks it
``error`` so a rate limit or outage is distinguishable from a dead link.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

from experienceos.connectors.github import GitHubAPI, GitHubAPIError
from experienceos.core.models import Evidence, Experience

Status = str  # verified | missing | unreachable | error | skipped

_VERIFIED = "verified"
_MISSING = "missing"
_UNREACHABLE = "unreachable"
_ERROR = "error"
_SKIPPED = "skipped"


@dataclass(frozen=True)
class EvidenceCheck:
    """One evidence item's verification outcome."""

    experience_id: str
    title: str
    evidence_index: int
    kind: str
    location: str
    status: Status
    detail: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def classify_location(location: str) -> tuple[str, dict[str, str]]:
    """Split a location into a checkable class and its parameters."""
    parsed = urlparse(location)
    if parsed.scheme not in {"http", "https"}:
        return "local", {}
    host = parsed.netloc.lower().removeprefix("www.")
    if host != "github.com":
        return "external", {}
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return "invalid", {}
    slug = f"{parts[0]}/{parts[1]}"
    if len(parts) == 2:
        return "repo", {"slug": slug}
    if len(parts) >= 4 and parts[2] == "commit":
        return "commit", {"slug": slug, "sha": parts[3]}
    if len(parts) >= 4 and parts[2] in {"pull", "pulls"} and parts[3].isdigit():
        return "pull", {"slug": slug, "number": parts[3]}
    return "repo-resource", {"slug": slug}


def verify_evidence(
    evidence: Evidence,
    *,
    github: GitHubAPI,
    probe_url: Callable[[str], int],
    experience_id: str = "",
    title: str = "",
    evidence_index: int = 0,
) -> EvidenceCheck:
    """Check one evidence item; every failure mode stays a result, not a raise."""

    def check(status: Status, detail: str) -> EvidenceCheck:
        return EvidenceCheck(
            experience_id=experience_id,
            title=title,
            evidence_index=evidence_index,
            kind=evidence.kind.value,
            location=evidence.location,
            status=status,
            detail=detail,
        )

    kind_class, params = classify_location(evidence.location)
    try:
        if kind_class == "local":
            return check(_SKIPPED, "local path — not network-verifiable")
        if kind_class == "invalid":
            return check(_SKIPPED, "URL does not point at an owner/repository")
        if kind_class == "external":
            code = probe_url(evidence.location)
            if code < 400:
                return check(_VERIFIED, f"URL reachable (HTTP {code})")
            if code < 500:
                return check(_MISSING, f"URL returned HTTP {code}")
            return check(_UNREACHABLE, f"server error (HTTP {code})")

        slug = params["slug"]
        if kind_class in {"repo", "repo-resource"}:
            payload = github.object(f"/repos/{slug}")
            detail = f"repository {payload.get('full_name', slug)} exists"
            if kind_class == "repo-resource":
                detail += "; deep path not verified"
            return check(_VERIFIED, detail)
        if kind_class == "commit":
            payload = github.object(f"/repos/{slug}/commits/{params['sha']}")
            author = payload.get("author") or {}
            commit_author = (payload.get("commit") or {}).get("author") or {}
            who = author.get("login") or commit_author.get("name") or "unknown"
            date = str(commit_author.get("date", ""))[:10]
            return check(
                _VERIFIED,
                f"commit {params['sha'][:8]} authored by {who}"
                + (f" on {date}" if date else ""),
            )
        # pull
        payload = github.object(f"/repos/{slug}/pulls/{params['number']}")
        who = (payload.get("user") or {}).get("login", "unknown")
        state = payload.get("state", "unknown")
        merged = ", merged" if payload.get("merged") else ""
        return check(
            _VERIFIED, f"pull request #{params['number']} by {who} ({state}{merged})"
        )
    except GitHubAPIError as exc:
        message = str(exc)
        if "not found" in message.casefold():
            return check(_MISSING, message)
        return check(_ERROR, message)
    except (OSError, ValueError) as exc:
        return check(_UNREACHABLE, f"probe failed: {exc}")


def verify_experience(
    experience: Experience,
    *,
    github: GitHubAPI,
    probe_url: Callable[[str], int],
) -> list[EvidenceCheck]:
    """Verify every evidence item of one record."""
    return [
        verify_evidence(
            evidence,
            github=github,
            probe_url=probe_url,
            experience_id=experience.id,
            title=experience.title,
            evidence_index=index,
        )
        for index, evidence in enumerate(experience.evidence)
    ]


def verify_records(
    records: list[Experience],
    *,
    github: GitHubAPI,
    probe_url: Callable[[str], int],
) -> list[EvidenceCheck]:
    """Verify every evidence item of every record, in record order."""
    checks: list[EvidenceCheck] = []
    for record in records:
        checks.extend(
            verify_experience(record, github=github, probe_url=probe_url)
        )
    return checks


def summarize(checks: list[EvidenceCheck]) -> dict[Status, int]:
    """Count checks per status; includes zero entries for stable output."""
    counts = {"verified": 0, "missing": 0, "unreachable": 0, "error": 0, "skipped": 0}
    for check in checks:
        counts[check.status] = counts.get(check.status, 0) + 1
    return counts


def save_report(checks: list[EvidenceCheck], path: Path) -> Path:
    """Write the machine-readable verification report (no secrets inside)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "report_version": 1,
        "summary": summarize(checks),
        "checks": [check.to_dict() for check in checks],
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path
