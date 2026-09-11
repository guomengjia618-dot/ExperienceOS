"""HTML exporter tests: escaping, evidence links, determinism, guards."""

from __future__ import annotations

from pathlib import Path

import pytest

from experienceos.core.errors import ExportError
from experienceos.exporters import html as html_module
from experienceos.exporters.base import ExportOptions
from experienceos.exporters.html import HtmlExporter


@pytest.fixture(autouse=True)
def frozen_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(html_module, "_now", lambda: html_module.datetime(2026, 9, 11, 8, 30))


def export_records(make_experience, tmp_path: Path) -> tuple[str, Path]:
    record = make_experience(
        title="Campus Search <Engine>",
        type="course_project",
        technology=["Python", "Whoosh"],
        contribution=["Designed the inverted index"],
        result=["92% top-10 hit rate"],
        reflection="Evaluation sets matter.",
        evidence=[
            {"kind": "repo", "location": "https://github.com/you/campus-search",
             "description": "source code"},
            {"kind": "file", "location": "D:\\archive\\project"},
        ],
    )
    target = tmp_path / "profile.html"
    path = HtmlExporter().export([record], target)
    return path.read_text(encoding="utf-8"), path


def test_renders_escaped_content(make_experience, tmp_path: Path) -> None:
    document, _ = export_records(make_experience, tmp_path)
    assert "Campus Search &lt;Engine&gt;" in document
    assert "<Engine>" not in document


def test_external_evidence_becomes_link_local_stays_text(
    make_experience, tmp_path: Path
) -> None:
    document, _ = export_records(make_experience, tmp_path)
    assert "<a href='https://github.com/you/campus-search'>" in document
    assert "source code" in document
    assert "<span class='local'>D:\\archive\\project</span>" in document
    assert "<a href='D:" not in document


def test_document_is_self_contained(make_experience, tmp_path: Path) -> None:
    document, _ = export_records(make_experience, tmp_path)
    assert document.startswith("<!doctype html>")
    assert "<style>" in document
    assert "@media print" in document
    assert "2 record(s)" not in document
    assert "1 record(s)" in document
    assert "exported 2026-09-11 08:30" in document


def test_star_sections_present(make_experience, tmp_path: Path) -> None:
    document, _ = export_records(make_experience, tmp_path)
    for section in ("Contribution", "Result", "Evidence"):
        assert f"<h3>{section}</h3>" in document
    assert "<li>Designed the inverted index</li>" in document
    assert "<blockquote>Evaluation sets matter.</blockquote>" in document


def test_empty_selection_rejected(tmp_path: Path) -> None:
    with pytest.raises(ExportError, match="selection is empty"):
        HtmlExporter().export([], tmp_path / "empty.html")


def test_timeline_not_supported(tmp_path: Path, make_experience) -> None:
    record = make_experience()
    with pytest.raises(ExportError, match="timeline"):
        HtmlExporter().export(
            [record], tmp_path / "t.html", ExportOptions(timeline=True)
        )


def test_deterministic_output(make_experience, tmp_path: Path) -> None:
    record = make_experience(title="Same", result=["r1"])
    first = tmp_path / "a.html"
    second = tmp_path / "b.html"
    HtmlExporter().export([record], first)
    HtmlExporter().export([record], second)
    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")
