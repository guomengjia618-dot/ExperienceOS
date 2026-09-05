"""Resume connector tests (#009): rule-based parsing, CN + EN fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from experienceos.cli.app import app
from experienceos.connectors import Extractor, ResumeError, ResumeExtractor
from experienceos.connectors.resume import parse_resume
from experienceos.core.errors import ConnectorError
from experienceos.core.models import EvidenceKind, ExperienceType, SourceOrigin, Status
from experienceos.storage import ExperienceStore

runner = CliRunner()

FIXTURES = Path(__file__).parent / "fixtures"
CV_CN = FIXTURES / "resume_cn.md"
CV_EN = FIXTURES / "resume_en.md"
CV_EMPTY = FIXTURES / "resume_empty.md"


@pytest.fixture
def extractor() -> ResumeExtractor:
    return ResumeExtractor()


class TestCanHandle:
    def test_claims_resume_scheme(self, extractor: ResumeExtractor) -> None:
        assert extractor.can_handle(f"resume:{CV_CN}") is True

    def test_claims_bare_markdown_and_text_files(
        self, extractor: ResumeExtractor
    ) -> None:
        assert extractor.can_handle(str(CV_CN)) is True
        assert extractor.can_handle(str(CV_EN)) is True
        txt = FIXTURES.with_name("fixtures") / "resume_cn.md"  # sanity: fixture exists
        assert txt.exists()
        bare_txt = txt.with_suffix(".txt")
        bare_txt.write_text("x", encoding="utf-8")
        try:
            assert extractor.can_handle(str(bare_txt)) is True
        finally:
            bare_txt.unlink()

    def test_claims_pdf_for_deferred_error(self, extractor: ResumeExtractor) -> None:
        pdf = CV_CN.with_suffix(".pdf")
        pdf.write_bytes(b"%PDF-1.4 fake")
        try:
            assert extractor.can_handle(str(pdf)) is True
        finally:
            pdf.unlink()

    def test_rejects_other_schemes_and_missing_files(
        self, extractor: ResumeExtractor, tmp_path: Path
    ) -> None:
        assert extractor.can_handle("github:owner/repo") is False
        assert extractor.can_handle(str(tmp_path / "missing.md")) is False
        assert extractor.can_handle(str(tmp_path)) is False


class TestParsePeriod:
    def test_month_points_and_ongoing(self) -> None:
        from experienceos.connectors.resume.parser import parse_period

        assert parse_period("云帆科技 2021.06 - 至今") == ("2021-06", None)
        assert parse_period("2020.07 - 2021.02") == ("2020-07", "2021-02")
        assert parse_period("2019-06 - Present") == ("2019-06", None)
        assert parse_period("2018/03 - 2018/12") == ("2018-03", "2018-12")
        assert parse_period("2023年4月-至今") == ("2023-04", None)

    def test_year_only_range_becomes_jan_to_dec(self) -> None:
        from experienceos.connectors.resume.parser import parse_period

        assert parse_period("某公司 2018 - 2020") == ("2018-01", "2020-12")
        assert parse_period("2016年-2020年") == ("2016-01", "2020-12")

    def test_no_or_implausible_dates(self) -> None:
        from experienceos.connectors.resume.parser import parse_period

        assert parse_period("led the team to victory") == (None, None)
        assert parse_period("scaled from 1000 - 2000 nodes") == (None, None)


class TestParseResume:
    def test_chinese_fixture_yields_three_entries(self) -> None:
        entries = parse_resume(CV_CN.read_text(encoding="utf-8"))
        assert [entry.category for entry in entries] == ["work", "work", "projects"]
        assert entries[0].title == "云帆科技 | 后端开发工程师"
        assert entries[0].start == "2021-06" and entries[0].end is None
        assert entries[1].title == "星河网络 | 后端开发实习生"
        assert entries[1].start == "2020-07" and entries[1].end == "2021-02"
        assert entries[2].title == "开源日志平台"
        assert entries[2].start == "2022-03" and entries[2].end == "2023-01"

    def test_english_fixture_yields_three_entries(self) -> None:
        entries = parse_resume(CV_EN.read_text(encoding="utf-8"))
        assert [entry.category for entry in entries] == ["work", "work", "projects"]
        assert entries[0].title == "Senior Engineer, Acme Corp"
        assert entries[0].start == "2019-06" and entries[0].end is None
        assert entries[1].title == "Software Engineer, Beta LLC"
        assert entries[2].title == "Weather CLI"
        assert entries[2].start == "2018-03" and entries[2].end == "2018-12"

    def test_description_preserves_original_wording(self) -> None:
        entries = parse_resume(CV_CN.read_text(encoding="utf-8"))
        assert "负责订单服务的设计与落地，使用 Python 与 MySQL" in entries[0].description
        assert "推动服务容器化，将核心服务迁移至 Kubernetes" in entries[0].description

    def test_technology_heuristics(self) -> None:
        entries = parse_resume(CV_CN.read_text(encoding="utf-8"))
        tech = {name.casefold() for name in entries[0].technology}
        assert {"python", "mysql", "kubernetes", "redis"} <= tech
        code_span = {name.casefold() for name in entries[2].technology}
        assert {"clickhouse", "fastapi"} <= code_span

    def test_technology_dedupes_contained_names(self) -> None:
        from experienceos.connectors.resume.parser import extract_technology

        names = extract_technology("Built it with Spring Boot and spring data")
        casefolded = [name.casefold() for name in names]
        assert "spring boot" in casefolded
        assert "spring" not in casefolded

    def test_undated_entry_gets_placeholder(self) -> None:
        text = "\n".join(
            ["## 项目经历", "", "**神秘项目**", "", "- 做了一些事情", ""]
        )
        entries = parse_resume(text)
        assert len(entries) == 1
        assert entries[0].start == "1970-01"
        assert entries[0].end is None
        assert entries[0].dated is False

    def test_boundaries_stop_the_section(self) -> None:
        text = "\n".join(
            [
                "## 工作经历",
                "A公司 2020-01 - 2021-01",
                "## 教育经历",
                "B大学 2016.09 - 2020.06",
            ]
        )
        entries = parse_resume(text)
        assert len(entries) == 1
        assert entries[0].title == "A公司"
        assert entries[0].category == "work"


class TestExtract:
    def test_protocol_conformance(self, extractor: ResumeExtractor) -> None:
        assert isinstance(extractor, Extractor)

    def test_chinese_resume_produces_drafts(self, extractor: ResumeExtractor) -> None:
        drafts = list(extractor.extract(f"resume:{CV_CN}"))
        assert len(drafts) == 3
        first = drafts[0].experience
        assert first.status is Status.draft
        assert first.source.origin is SourceOrigin.resume
        assert first.source.ref == str(CV_CN)
        assert first.type is ExperienceType.work
        assert first.period.start == "2021-06" and first.period.end is None
        assert first.tags == ["resume"]
        evidence = first.evidence[0]
        assert evidence.kind is EvidenceKind.file
        assert evidence.location == str(CV_CN)

    def test_category_maps_to_type(self, extractor: ResumeExtractor) -> None:
        drafts = list(extractor.extract(str(CV_CN)))
        assert drafts[1].experience.type is ExperienceType.internship
        assert drafts[2].experience.type is ExperienceType.personal

    def test_english_resume_produces_drafts(self, extractor: ResumeExtractor) -> None:
        drafts = list(extractor.extract(str(CV_EN)))
        assert len(drafts) == 3
        assert drafts[0].experience.title == "Senior Engineer, Acme Corp"
        assert drafts[0].experience.period.is_ongoing is True
        assert drafts[2].experience.type is ExperienceType.personal


class TestErrors:
    def test_no_entries_readable_error(self, extractor: ResumeExtractor) -> None:
        with pytest.raises(ResumeError, match="no experience entries"):
            list(extractor.extract(str(CV_EMPTY)))

    def test_missing_file_readable_error(
        self, extractor: ResumeExtractor, tmp_path: Path
    ) -> None:
        with pytest.raises(ResumeError, match="resume file not found"):
            list(extractor.extract(str(tmp_path / "missing.md")))

    def test_pdf_without_ai_configuration_fails_readably(
        self, extractor: ResumeExtractor, tmp_path: Path
    ) -> None:
        pdf = tmp_path / "cv.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        with pytest.raises(ResumeError, match="PDF resumes need AI extraction"):
            list(extractor.extract(str(pdf)))

    def test_pdf_goes_through_ai_extraction_pipeline(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import experienceos.connectors.resume.extractor as module
        from experienceos.ai.extraction import AIExtraction
        from experienceos.ai.mock import MockProvider

        monkeypatch.setattr(
            module, "_extract_pdf_text", lambda path: "Jane built pipelines"
        )
        provider = MockProvider(
            '{"title": "Billing Pipeline", "type": "work", '
            '"period": {"start": "2022-01"}}'
        )
        extractor = ResumeExtractor(AIExtraction(provider, "test-model"))
        pdf = tmp_path / "cv.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        drafts = list(extractor.extract(str(pdf)))
        assert len(drafts) == 1
        exp = drafts[0].experience
        assert exp.source.origin is SourceOrigin.resume
        assert exp.source.ref == str(pdf)
        assert exp.source.created_by == "ai:test-model"
        assert exp.title == "Billing Pipeline"
        assert any(e.kind is EvidenceKind.file for e in exp.evidence)

    def test_pdf_extraction_retry_then_readable_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import experienceos.connectors.resume.extractor as module
        from experienceos.ai.extraction import AIExtraction
        from experienceos.ai.mock import MockProvider

        monkeypatch.setattr(module, "_extract_pdf_text", lambda path: "text")
        provider = MockProvider("nope", "still nope")
        extractor = ResumeExtractor(AIExtraction(provider, "m"))
        pdf = tmp_path / "cv.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        with pytest.raises(ResumeError, match="failed twice"):
            list(extractor.extract(str(pdf)))
        assert provider.replies_used == 2

    def test_foreign_scheme_readable_error(self, extractor: ResumeExtractor) -> None:
        with pytest.raises(ConnectorError, match="does not handle scheme"):
            list(extractor.extract("github:owner/repo"))

    def test_registered_in_default_registry(self) -> None:
        from experienceos.connectors import default_registry

        assert default_registry.get("resume") is not None


class TestCliImport:
    def test_import_resume_saves_drafts(self, cli_env) -> None:
        result = runner.invoke(app, ["import", f"resume:{CV_CN}", "--yes"])
        output = result.output + str(getattr(result, "stderr", "") or "")
        assert result.exit_code == 0, output
        assert "3 draft(s)" in output
        saved = ExperienceStore(cli_env).list_all()
        assert len(saved) == 3
        assert all(exp.source.origin is SourceOrigin.resume for exp in saved)
        assert all(exp.status is Status.draft for exp in saved)

    def test_import_bare_path_also_routes(self, cli_env) -> None:
        result = runner.invoke(app, ["import", str(CV_EN), "--yes"])
        assert result.exit_code == 0
        assert len(ExperienceStore(cli_env).list_all()) == 3

    def test_import_pdf_without_pypdf_fails_with_guidance(
        self, cli_env, tmp_path: Path
    ) -> None:
        pdf = tmp_path / "cv.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        result = runner.invoke(app, ["import", f"resume:{pdf}", "--yes"])
        output = result.output + str(getattr(result, "stderr", "") or "")
        assert result.exit_code == 1
        assert "experienceos[pdf]" in output
