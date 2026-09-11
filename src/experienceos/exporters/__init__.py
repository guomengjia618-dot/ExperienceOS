"""Exporters: project the knowledge base into shareable artifacts.

#014 ships the framework (protocol, options, registry, export command);
built-in formats: #015 (Markdown profile/timeline), #016 (JSON Resume)
and the print-ready HTML profile (M6).
"""

from experienceos.exporters.base import Exporter, ExportOptions
from experienceos.exporters.html import HtmlExporter
from experienceos.exporters.json_resume import JsonResumeExporter
from experienceos.exporters.markdown import MarkdownExporter
from experienceos.exporters.registry import (
    ExporterRegistry,
    default_exporter_registry,
)

default_exporter_registry.register(MarkdownExporter())
default_exporter_registry.register(JsonResumeExporter())
default_exporter_registry.register(HtmlExporter())

__all__ = [
    "ExportOptions",
    "Exporter",
    "ExporterRegistry",
    "HtmlExporter",
    "JsonResumeExporter",
    "MarkdownExporter",
    "default_exporter_registry",
]
