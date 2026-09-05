"""Layering guard (#028): dependency direction is enforced by test.

ARCHITECTURE.md's layering rules were previously convention; the M5
review found the ai ↔ connectors cycle had crept in despite them. These
tests parse every module's imports (AST, no execution) and fail when a
tier reaches where it must not:

- core imports nothing above itself;
- ai never imports connectors (the injection protocols point the other
  way);
- connectors never import ai (AI help arrives via injected protocols);
- storage and exporters depend on core only (services may orchestrate
  all of them; cli/api are composition roots and unrestricted).
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "experienceos"

# tiers that may never be touched by the tier on the left
_FORBIDDEN: dict[str, tuple[str, ...]] = {
    "core": (
        "storage", "connectors", "ai", "exporters",
        "services", "cli", "api", "plugins", "stats",
    ),
    "storage": ("connectors", "ai", "exporters", "services", "cli", "api", "plugins", "stats"),
    "connectors": ("ai", "storage", "exporters", "services", "cli", "api", "plugins", "stats"),
    "ai": ("connectors", "storage", "exporters", "services", "cli", "api", "plugins", "stats"),
    "exporters": ("connectors", "ai", "storage", "services", "cli", "api", "plugins", "stats"),
    "stats": ("storage", "connectors", "ai", "exporters", "services", "cli", "api", "plugins"),
}


def _tier_modules(tier: str) -> dict[Path, str]:
    """module dotted-path per file under src/experienceos/<tier>/."""
    root = SRC / tier
    return {
        path: f"experienceos.{rel}:{path.stem}"
        for path in sorted(root.rglob("*.py"))
        for rel in [path.parent.relative_to(SRC).as_posix()]
    }


def _imported_roots(path: Path) -> set[str]:
    """Third-party + first-party import roots/parents used by *path*."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def _violations(tier: str) -> list[str]:
    bad: list[str] = []
    for path, where in _tier_modules(tier).items():
        for imported in _imported_roots(path):
            parts = imported.split(".")
            if parts[0] != "experienceos" or len(parts) < 2:
                continue
            target = parts[1]
            if target in _FORBIDDEN.get(tier, ()):
                bad.append(f"{where} imports {imported}")
    return bad


class TestLayering:
    def test_no_tier_reaches_where_it_must_not(self) -> None:
        violations: list[str] = []
        for tier in _FORBIDDEN:
            violations.extend(_violations(tier))
        assert violations == []

    def test_core_has_zero_upward_dependencies(self) -> None:
        # stronger statement of intent: core is the leaf of the first-party graph
        assert _violations("core") == []
