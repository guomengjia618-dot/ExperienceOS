"""Chinese presentation labels for the stable ExperienceOS data model.

Wire values stay in English so existing records, commands, and JSON Resume
integrations remain compatible.  User-facing renderers use this module.
"""

from __future__ import annotations

from experienceos.core.models import (
    EvidenceKind,
    ExperienceType,
    Period,
    SourceOrigin,
    Status,
)

EXPERIENCE_TYPE_LABELS: dict[ExperienceType, str] = {
    ExperienceType.work: "工作经历",
    ExperienceType.internship: "实习经历",
    ExperienceType.open_source: "开源贡献",
    ExperienceType.competition: "竞赛项目",
    ExperienceType.course_project: "课程项目",
    ExperienceType.graduation_project: "毕业设计",
    ExperienceType.personal: "个人项目",
    ExperienceType.research: "科研经历",
    ExperienceType.other: "其他经历",
}

STATUS_LABELS: dict[Status, str] = {
    Status.draft: "草稿",
    Status.active: "已确认",
    Status.archived: "已归档",
}

EVIDENCE_KIND_LABELS: dict[EvidenceKind, str] = {
    EvidenceKind.url: "链接",
    EvidenceKind.repo: "代码仓库",
    EvidenceKind.commit: "代码提交",
    EvidenceKind.pull_request: "合并请求",
    EvidenceKind.issue: "问题单",
    EvidenceKind.file: "文件",
    EvidenceKind.doc: "文档",
    EvidenceKind.image: "图片",
    EvidenceKind.other: "其他证据",
}

SOURCE_ORIGIN_LABELS: dict[SourceOrigin, str] = {
    SourceOrigin.manual: "手动录入",
    SourceOrigin.github: "GitHub 导入",
    SourceOrigin.git_repo: "本地 Git 仓库导入",
    SourceOrigin.resume: "简历导入",
    SourceOrigin.interview: "访谈录入",
    SourceOrigin.import_: "外部导入",
}

TOOL_LABELS: dict[str, str] = {
    "search_experiences": "搜索经历",
    "get_experience": "读取经历详情",
    "get_evidence_stats": "统计证据覆盖情况",
}


def experience_type_label(value: ExperienceType) -> str:
    return EXPERIENCE_TYPE_LABELS[value]


def status_label(value: Status) -> str:
    return STATUS_LABELS[value]


def evidence_kind_label(value: EvidenceKind) -> str:
    return EVIDENCE_KIND_LABELS[value]


def source_origin_label(value: SourceOrigin) -> str:
    return SOURCE_ORIGIN_LABELS[value]


def period_label(period: Period) -> str:
    if period.start is None:
        return "时间待补充"
    return f"{period.start} 至 {period.end or '至今'}"


def tool_label(name: str) -> str:
    return TOOL_LABELS.get(name, name)
