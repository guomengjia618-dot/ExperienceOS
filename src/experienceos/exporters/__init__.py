"""Exporters: project the knowledge base into shareable artifacts.

#014 ships the framework (protocol, options, registry, export command);
built-in formats: #015 (Markdown profile/timeline) and #016 (JSON
Resume).
"""

from experienceos.exporters.base import Exporter, ExportOptions
from experienceos.exporters.json_resume import JsonResumeExporter
from experienceos.exporters.markdown import MarkdownExporter
from experienceos.exporters.registry import (
    ExporterRegistry,
    default_exporter_registry,
)

default_exporter_registry.register(MarkdownExporter())
default_exporter_registry.register(JsonResumeExporter())

__all__ = [
    "ExportOptions",
    "Exporter",
    "ExporterRegistry",
    "JsonResumeExporter",
    "MarkdownExporter",
    "default_exporter_registry",
]
