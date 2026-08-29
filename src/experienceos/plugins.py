"""Plugin discovery via package entry points (#019).

Third-party packages register connectors/exporters by declaring entry
points in their own metadata::

    [project.entry-points."experienceos.connectors"]
    my-source = "my_package.connector:MyExtractor"

``load_plugins`` imports every entry point in the two groups and
registers what it finds. Import and registration failures are
*contained per plugin*: one broken plugin is reported (see
``experienceos plugins list``) and never takes the CLI down.

Built-in connectors/exporters are declared through the same mechanism
in ExperienceOS's own pyproject (eating our own dog food); when the
registry already holds a name — e.g. from the import-time builtin
registration that keeps source checkouts working without reinstall —
the entry point is skipped rather than treated as a conflict.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any

from experienceos.connectors.registry import default_registry
from experienceos.core.errors import ExperienceOSError
from experienceos.exporters.registry import default_exporter_registry

CONNECTORS_GROUP = "experienceos.connectors"
EXPORTERS_GROUP = "experienceos.exporters"


@dataclass
class PluginInfo:
    """Outcome of loading one entry point."""

    name: str
    group: str
    target: str
    version: str | None = None
    dist: str | None = None
    state: str = "failed"  # registered | already-present | failed
    error: str | None = None


def load_plugins() -> list[PluginInfo]:
    """Discover and register all entry-point plugins (idempotent)."""
    infos: list[PluginInfo] = []
    for group, registry in (
        (CONNECTORS_GROUP, default_registry),
        (EXPORTERS_GROUP, default_exporter_registry),
    ):
        for ep in entry_points(group=group):
            info = PluginInfo(name=ep.name, group=group, target=ep.value)
            dist = getattr(ep, "dist", None)
            if dist is not None:
                info.dist = dist.metadata["Name"]
                info.version = dist.version
            try:
                obj = ep.load()
                instance = obj() if isinstance(obj, type) else obj
                if ep.name in registry.names():
                    info.state = "already-present"
                else:
                    registry.register(instance)
                    info.state = "registered"
            except ExperienceOSError as exc:
                # e.g. duplicate registration: keep the existing one
                info.state = "already-present"
                info.error = str(exc)
            except Exception as exc:
                info.state = "failed"
                info.error = f"{type(exc).__name__}: {exc}"
            infos.append(info)
    return infos


def plugin_summary(infos: list[PluginInfo]) -> list[dict[str, Any]]:
    """Render-friendly rows for `plugins list`."""
    return [
        {
            "name": info.name,
            "group": info.group.rsplit(".", 1)[-1],
            "version": info.version or "-",
            "source": info.dist or "(external)",
            "target": info.target,
            "state": info.state,
            "error": info.error,
        }
        for info in infos
    ]
