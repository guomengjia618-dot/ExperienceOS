"""JSON Resume compatible exporter (#016).

Maps records onto the jsonresume.org shape — ``work`` for work and
internship types, ``projects`` for everything else, technologies as
``skills`` and project ``keywords``, url-kind evidence as ``url``.

Faithfulness rule: anything the target schema cannot represent
(reflection, tags, non-url evidence) is *dropped and reported* on the
exporter instance (``last_dropped``), never rewritten into a
neighbouring field. The output is validated against pydantic models
(strict, extra=forbid) before it is written — a mapping bug fails the
export instead of producing a broken resume.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from experienceos.core.errors import ExportError
from experienceos.core.models import EvidenceKind, Experience, ExperienceType

_WORK_TYPES = {ExperienceType.work, ExperienceType.internship}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Basics(_Strict):
    name: str | None = None
    label: str | None = None


class WorkItem(_Strict):
    name: str | None = None
    position: str | None = None
    startDate: str | None = None
    endDate: str | None = None
    summary: str | None = None
    highlights: list[str] = []


class ProjectItem(_Strict):
    name: str
    startDate: str | None = None
    endDate: str | None = None
    description: str | None = None
    highlights: list[str] = []
    keywords: list[str] = []
    roles: list[str] = []
    url: str | None = None


class SkillItem(_Strict):
    name: str


class JsonResume(_Strict):
    basics: Basics = Basics()
    work: list[WorkItem] = []
    projects: list[ProjectItem] = []
    skills: list[SkillItem] = []


class JsonResumeExporter:
    """Render records as a jsonresume.org-compatible JSON document."""

    name = "json-resume"
    suffix = ".json"

    def __init__(self) -> None:
        self.last_dropped: Counter[str] = Counter()

    def export(
        self,
        experiences: Sequence[Experience],
        target: Path,
        options: object | None = None,
    ) -> Path:
        if not experiences:
            raise ExportError("nothing to export: the selection is empty")
        self.last_dropped = Counter()
        work: list[WorkItem] = []
        projects: list[ProjectItem] = []
        technology: dict[str, str] = {}

        for exp in sorted(experiences, key=lambda e: (e.period.start, e.id), reverse=True):
            if exp.type in _WORK_TYPES:
                work.append(self._work_item(exp))
            else:
                projects.append(self._project_item(exp))
            for name in exp.technology:
                technology.setdefault(name.casefold(), name)
            if exp.reflection:
                self.last_dropped["reflection"] += 1
            if exp.tags:
                self.last_dropped["tags"] += 1
            for evidence in exp.evidence:
                if evidence.kind is not EvidenceKind.url:
                    self.last_dropped[f"evidence[{evidence.kind.value}]"] += 1

        document = JsonResume(
            work=work,
            projects=projects,
            skills=[SkillItem(name=name) for name in technology.values()],
        )
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                document.model_dump(exclude_none=True), ensure_ascii=False, indent=2
            )
            + "\n",
            encoding="utf-8",
        )
        return target

    def _work_item(self, exp: Experience) -> WorkItem:
        return WorkItem(
            name=exp.title,
            position=exp.role or exp.title,
            startDate=exp.period.start,
            endDate=exp.period.end,
            summary=exp.description or None,
            highlights=self._highlights(exp),
        )

    def _project_item(self, exp: Experience) -> ProjectItem:
        url = next(
            (
                evidence.location
                for evidence in exp.evidence
                if evidence.kind is EvidenceKind.url
            ),
            None,
        )
        return ProjectItem(
            name=exp.title,
            startDate=exp.period.start,
            endDate=exp.period.end,
            description=exp.description or exp.context or None,
            highlights=self._highlights(exp),
            keywords=list(exp.technology),
            roles=[exp.role] if exp.role else [],
            url=url,
        )

    @staticmethod
    def _highlights(exp: Experience) -> list[str]:
        items = [
            *exp.contribution,
            *exp.challenge,
            *exp.solution,
            *exp.result,
        ]
        seen: set[str] = set()
        unique: list[str] = []
        for item in items:
            key = item.casefold()
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique
