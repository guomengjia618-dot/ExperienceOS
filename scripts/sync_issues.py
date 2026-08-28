#!/usr/bin/env python3
"""Sync docs/issues/*.md to GitHub issues, labels and milestones.

Reads the milestone files under docs/issues/, creates the labels and
milestones they need, then creates one GitHub issue per "## #NNN ..."
section — attaching labels, milestone, and closing sections already
marked done (✅). Cross references like "#007" are rewritten to
"issue 007" so GitHub does not auto-link them to unrelated issue numbers.

Idempotent: existing issues (matched by title) and existing labels /
milestones are skipped, so it is safe to re-run after an interruption.

Usage:
    python scripts/sync_issues.py --repo OWNER/REPO [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "issues"

# milestone file stem -> (milestone title, state)
MILESTONES = {
    "m0-foundation": ("v0.1.0 · M0 基础", "closed"),
    "m1-import": ("v0.2.0 · M1 导入", "open"),
    "m2-intelligence": ("v0.3.0 · M2 智能", "open"),
    "m3-output": ("v0.4.0 · M3 输出", "open"),
    "m4-platform": ("v0.5.0 · M4 平台", "open"),
}

# label -> (color, description)
LABELS = {
    "area/core": ("0e8a16", "domain models, storage, errors"),
    "area/cli": ("1d76db", "command line interface"),
    "area/ai": ("5319e7", "LLM providers, prompts, guardrails"),
    "area/connector": ("f9d0c4", "import sources (github, git repo, resume)"),
    "area/exporter": ("c5def5", "markdown / json-resume output"),
    "area/docs": ("0075ca", "documentation"),
    "area/infra": ("d4c5f9", "CI, packaging, api service, plugins"),
    "P0": ("b60205", "must have for the milestone"),
    "P1": ("d93f0b", "should have"),
    "P2": ("94a3b8", "nice to have"),
    "intermediate": ("c2e0c6", "moderate difficulty"),
    "advanced": ("5319e7", "high difficulty"),
    # "good first issue" exists as a GitHub default label; reused, not created
}

DONE_NOTES = {
    "001": "Delivered in v0.1.0 (tag v0.1.0).",
    "002": "Delivered in v0.1.0 (tag v0.1.0).",
    "003": "Delivered in v0.1.0 (tag v0.1.0).",
    "004": "Delivered in v0.1.0 (tag v0.1.0).",
    "005": "Delivered in v0.1.0 (tag v0.1.0).",
    "005b": "Delivered in v0.1.0 (tag v0.1.0).",
    "006": "Implemented in commit c9d0cd8 (connector framework + import command).",
}

DIFFICULTY_LABELS = {"good first issue", "intermediate", "advanced"}


def gh(*args: str, check: bool = True) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
    if check and result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def parse_section(section: str) -> dict | None:
    lines = section.strip().splitlines()
    if not lines:
        return None
    match = re.match(r"^#(\d+[a-z]?)\s+(.*)$", lines[0].strip())
    if not match:
        return None
    code, title = match.groups()
    done = "✅" in title
    title = re.sub(r"\s*\d{4}-\d{2}-\d{2}\s*$", "", title.replace("✅", "")).strip()
    labels: list[str] = []
    body_lines: list[str] = []
    for line in lines[1:]:
        label_line = re.match(r"^(?:-\s*)?\*\*Labels\*\*:\s*(.*)$", line.strip())
        if label_line:
            labels += re.findall(r"`([^`]+)`", label_line.group(1))
            labels += [token for token in DIFFICULTY_LABELS if token in line]
            priority = re.search(r"\bP[012]\b", line)
            if priority:
                labels.append(priority.group(0))
        else:
            body_lines.append(line)
    deduped: list[str] = []
    for name in labels:
        if name not in deduped:
            deduped.append(name)
    return {
        "code": code,
        "title": title,
        "done": done,
        "labels": deduped,
        "body": "\n".join(body_lines).strip(),
    }


def rewrite_refs(text: str) -> str:
    """'#007' -> 'issue 007' to prevent GitHub auto-linking to wrong numbers."""
    return re.sub(r"#(\d{3}[a-z]?)\b", r"issue \1", text)


def parse_file(path: Path) -> tuple[str, list[dict]]:
    content = path.read_text(encoding="utf-8")
    parts = re.split(r"^## ", content, flags=re.M)
    preamble = parts[0].strip()
    sections = [s for s in (parse_section(part) for part in parts[1:]) if s]
    return preamble, sections


def body_for(preamble: str, section: dict, milestone: str) -> str:
    quote = "\n".join(f"> {ln}" for ln in rewrite_refs(preamble).splitlines() if ln)
    status = "✅ delivered" if section["done"] else "open"
    blocks = [f"> Milestone: **{milestone}** · Status: {status}"]
    if quote:
        blocks.append(quote)
    blocks.append(rewrite_refs(section["body"]))
    return "\n\n".join(blocks)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="OWNER/REPO")
    parser.add_argument("--dry-run", action="store_true", help="parse and print, no gh calls")
    args = parser.parse_args()

    parsed: list[tuple[str, str, list[dict]]] = []  # (milestone, preamble, sections)
    for stem, (milestone, _state) in MILESTONES.items():
        path = DOCS_DIR / f"{stem}.md"
        if not path.exists():
            print(f"warning: {path} missing, skipped", file=sys.stderr)
            continue
        preamble, sections = parse_file(path)
        parsed.append((milestone, preamble, sections))

    total = sum(len(sections) for _, _, sections in parsed)
    print(f"parsed {total} issues from {len(parsed)} milestone files")
    for milestone, _preamble, sections in parsed:
        for section in sections:
            marker = "x" if section["done"] else " "
            labels = ",".join(section["labels"]) or "-"
            print(f" [{marker}] [{milestone}] #{section['code']} {section['title']} ({labels})")

    if args.dry_run:
        print("\ndry run: no gh calls made")
        return 0

    # labels ------------------------------------------------------------------
    existing_labels = set(
        gh("label", "list", "--limit", "200", "--json", "name", "--jq", ".[].name").splitlines()
    )
    for name, (color, description) in LABELS.items():
        if name in existing_labels:
            continue
        gh("label", "create", name, "--color", color, "--description", description)
        print(f"created label {name}")

    # milestones — created open (gh issue create cannot target a closed
    # milestone); milestones marked closed in MILESTONES are closed afterwards
    for _stem, (title, _state) in MILESTONES.items():
        listing = json.loads(gh("api", f"repos/{args.repo}/milestones?state=all"))
        if any(m["title"] == title for m in listing):
            continue
        gh("api", f"repos/{args.repo}/milestones", "-f", f"title={title}")
        print(f"created milestone {title} (open)")

    # issues --------------------------------------------------------------------
    existing_titles = {
        title
        for title in gh(
            "issue", "list", "--repo", args.repo, "--state", "all", "--limit", "300",
            "--json", "title", "--jq", ".[].title",
        ).splitlines()
        if title
    }

    created: dict[str, str] = {}  # internal code -> github issue number
    for milestone, preamble, sections in parsed:
        label = milestone.split("·")[1].strip()  # e.g. "M1"
        for section in sections:
            title = f"[{label}] {section['title']} (#{section['code']})"
            if title in existing_titles:
                print(f"skip existing: {title}")
                continue
            with tempfile.NamedTemporaryFile(
                "w", suffix=".md", delete=False, encoding="utf-8"
            ) as fh:
                fh.write(body_for(preamble, section, milestone))
                body_file = fh.name
            cmd = [
                "issue", "create", "--repo", args.repo,
                "--title", title, "--body-file", body_file, "--milestone", milestone,
            ]
            for name in section["labels"]:
                cmd += ["--label", name]
            url = gh(*cmd)
            issue_number = url.rsplit("/", 1)[-1]
            created[section["code"]] = issue_number
            print(f"created #{issue_number}: {title}")
            if section["done"]:
                note = DONE_NOTES.get(section["code"], "Delivered.")
                gh("issue", "close", issue_number, "--repo", args.repo, "--reason", "completed")
                gh("issue", "comment", issue_number, "--repo", args.repo, "--body", note)
                print("  closed (completed)")

    print("\nissue number mapping (internal code -> github):")
    for code, number in sorted(created.items()):
        print(f"  {code} -> #{number}")

    # close milestones that should be closed, now that their issues exist
    for _stem, (title, state) in MILESTONES.items():
        if state != "closed":
            continue
        listing = json.loads(gh("api", f"repos/{args.repo}/milestones?state=all"))
        entry = next((m for m in listing if m["title"] == title), None)
        if entry and entry["state"] != "closed":
            gh(
                "api", f"repos/{args.repo}/milestones/{entry['number']}",
                "-X", "PATCH", "-f", "state=closed",
            )
            print(f"closed milestone {title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
