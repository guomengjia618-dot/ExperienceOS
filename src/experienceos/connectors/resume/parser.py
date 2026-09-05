"""Rule-based resume parsing (#009): pure regex heuristics, no LLM.

The parser recognises the common 80% of resume layouts: an experience
section (``项目经历 / 工作经历 / Projects / Experience``, ...) whose
entries start with an ATX heading, a bold line, or a date-bearing line.
It is deliberately conservative:

- Section boundaries are only ever *known* heading names; free-form
  text never opens or closes a section.
- Entry wording is preserved verbatim (only bullet markers are
  stripped); the parser never rewrites sentences.
- Technology names come from a curated keyword list plus inline code
  spans — unknown words are never guessed as technology.

Dates parse to ``YYYY-MM``. Entries without any parseable period keep
an explicit undated placeholder (``core.models.UNDATED_START``, tagged
``undated`` by the extractor) because the record schema requires a
start month; the user confirms or fixes it during the import preview.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from experienceos.core.models import UNDATED_START

MAX_TECHNOLOGY = 10

_MONTH_POINT = r"(\d{4})(?!\d)(?:\s*[年./\-]\s*(\d{1,2})\s*月?|\s*年)?"
MONTH_POINT_RE = re.compile(_MONTH_POINT)
YEAR_RANGE_RE = re.compile(r"(\d{4})\s*年?\s*[-–—~至到]\s*(\d{4})\s*年?")
PRESENT_RE = re.compile(r"至今|现在|\b(?:present|now|current)\b", re.IGNORECASE)
BULLET_RE = re.compile(r"^\s*(?:[-*•·▪◦]|\d{1,2}[.、)]|[（(]\d{1,2}[)）])\s+")
ATX_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*#*\s*$")
BOLD_RE = re.compile(r"^\s*\*\*(.+?)\*\*")
CODE_SPAN_RE = re.compile(r"`([^`]+)`")

_MAX_HEADING_LINE = 40
_MIN_YEAR, _MAX_YEAR = 1900, 2100

# normalized heading -> entry category
SECTION_CATEGORIES: dict[str, str] = {
    "项目经历": "projects",
    "项目经验": "projects",
    "主要项目": "projects",
    "个人项目": "projects",
    "projects": "projects",
    "project experience": "projects",
    "selected projects": "projects",
    "工作经历": "work",
    "工作经验": "work",
    "职业经历": "work",
    "experience": "work",
    "work experience": "work",
    "professional experience": "work",
    "employment": "work",
    "employment history": "work",
    "career history": "work",
    "industry experience": "work",
    "实习经历": "internship",
    "实习经验": "internship",
    "internship": "internship",
    "internships": "internship",
    "internship experience": "internship",
    "开源经历": "open_source",
    "开源经验": "open_source",
    "开源项目": "open_source",
    "open source": "open_source",
    "open source experience": "open_source",
    "open-source projects": "open_source",
    "科研经历": "research",
    "研究经历": "research",
    "research experience": "research",
    "research": "research",
}

# known headings that merely close the current experience section
BOUNDARY_HEADINGS: frozenset[str] = frozenset(
    {
        "教育经历", "教育背景", "教育", "education", "academic background",
        "专业技能", "技能", "技能特长", "技术栈", "skills", "technical skills",
        "证书", "资格证书", "certifications", "certificates",
        "奖项", "获奖情况", "荣誉", "awards", "honors",
        "自我评价", "个人评价", "自我介绍", "self assessment", "about me",
        "summary", "profile", "objective",
        "兴趣爱好", "hobbies", "interests", "语言能力", "languages",
        "出版物", "publications", "专利", "patents", "演讲", "talks",
        "联系方式", "contact", "个人信息",
    }
)

_CJK_KEY_RE = re.compile(r"[\u4e00-\u9fff]")
_HEADING_SUFFIX_RE = re.compile(r"^[：:（(【[，,、|｜/·.\-–—\s]")

# curated technology keywords; order matters only for the containment
# check (longer names first suppress their substrings, e.g. "Spring Boot"
# suppresses "Spring"). Bare "C" and "R" are excluded on purpose: as
# single letters they match far too much prose.
TECHNOLOGY_KEYWORDS: tuple[str, ...] = (
    "GitHub Actions", "Ruby on Rails", "Spring Boot", "Next.js", "Node.js",
    "scikit-learn", "ASP.NET", ".NET", "Kubernetes", "Elasticsearch",
    "JavaScript", "TypeScript", "ActionScript",
    "FastAPI", "TensorFlow", "PostgreSQL", "WebSocket", "Terraform",
    "PyTorch", "LangChain", "Django", "Kafka", "Hadoop", "Flink",
    "Airflow", "Celery", "Prometheus", "Grafana", "Memcached", "MongoDB",
    "Cassandra", "ClickHouse", "RabbitMQ", "RocketMQ", "ZooKeeper",
    "Consul", "MATLAB", "NoSQL", "SQLite", "OpenCV", "Keras", "Helm",
    "Istio", "Ansible", "Jenkins", "GitLab", "Nginx", "Redis", "MySQL",
    "Angular", "Docker", "Linux", "Spark", "Hive", "Spring", "Rails",
    "Laravel", "Express", "GraphQL", "gRPC", "Tornado", "Flask", "React",
    "Swift", "Kotlin", "Scala", "Groovy", "Ruby", "Rust", "Golang", "Go",
    "Java", "Python", "PHP", "HTML", "CSS", "Sass", "SQL", "Git", "SVN",
    "K8s", "etcd", "C++", "C#", "Vue", "Koa", "REST", "Unix",
    "阿里云", "腾讯云", "华为云", "微信小程序", "微服务",
)


@dataclass(frozen=True)
class ResumeEntry:
    """One resume entry, ready to become a draft."""

    title: str
    category: str  # work | internship | projects | open_source | research
    start: str  # YYYY-MM; UNDATED_START when the entry carries no date
    end: str | None  # None = ongoing or unknown
    technology: list[str] = field(default_factory=list)
    description: list[str] = field(default_factory=list)  # original lines
    dated: bool = False


def parse_resume(text: str) -> list[ResumeEntry]:
    """Parse resume text into experience entries (may return none)."""
    entries: list[ResumeEntry] = []
    category: str | None = None
    label = ""
    lines: list[str] = []

    for line in text.splitlines():
        known = _heading_of(line)
        if known is not None:
            if category is not None and lines:
                entries.extend(_entries_from_section(category, label, lines))
            _, known_category, known_label = known
            category = known_category
            label = known_label
            lines = []
            continue
        if category is not None:
            lines.append(line)
    if category is not None and lines:
        entries.extend(_entries_from_section(category, label, lines))
    return entries


def parse_period(text: str) -> tuple[str | None, str | None]:
    """Extract a ``(start, end)`` month pair; ``end`` is None if ongoing.

    Returns ``(None, None)`` when no plausible date appears in *text*.
    Handles "2021.06 - 2023.01", "2020年7月", "2018 - 2020" (year-only
    ranges become January–December) and "至今/present" endings.
    """
    raw = [
        (match.group(1), match.group(2))
        for match in MONTH_POINT_RE.finditer(text)
        if _MIN_YEAR <= int(match.group(1)) <= _MAX_YEAR
    ]
    if len(raw) >= 2:
        start = _norm_point(raw[0][0], raw[0][1], default=1)
        end = _norm_point(raw[-1][0], raw[-1][1], default=12)
        if start is not None:
            return start, None if PRESENT_RE.search(text) else end
        return None, None
    range_match = YEAR_RANGE_RE.search(text)
    if range_match and all(
        _MIN_YEAR <= int(group) <= _MAX_YEAR for group in range_match.groups()
    ):
        start = f"{range_match.group(1)}-01"
        end = f"{range_match.group(2)}-12"
        return start, None if PRESENT_RE.search(text) else end
    if raw:
        start = _norm_point(raw[0][0], raw[0][1], default=1)
        if start is not None:
            return start, None
    return None, None


def extract_technology(text: str) -> list[str]:
    """Curated-keyword + inline-code-span extraction, capped, in order."""
    found: list[str] = []
    for span in CODE_SPAN_RE.findall(text):
        name = span.strip()
        if name and _novel(name, found):
            found.append(name)
    for name in sorted(TECHNOLOGY_KEYWORDS, key=len, reverse=True):
        if _tech_pattern(name).search(text) and _novel(name, found):
            found.append(name)
    return found[:MAX_TECHNOLOGY]


# -- internals ---------------------------------------------------------------


def _novel(name: str, found: list[str]) -> bool:
    key = name.casefold()
    return key not in {other.casefold() for other in found} and not any(
        key in other.casefold() for other in found
    )


def _tech_pattern(name: str) -> re.Pattern[str]:
    escaped = re.escape(name)
    if re.fullmatch(r"[A-Za-z0-9+#.]+", name):
        return re.compile(
            rf"(?<![A-Za-z0-9+#]){escaped}(?![A-Za-z0-9+#])", re.IGNORECASE
        )
    return re.compile(escaped)  # CJK / mixed names: plain substring


def _norm_point(year: str, month: str | None, default: int) -> str | None:
    value = int(month) if month else default
    if not 1 <= value <= 12:
        # e.g. "2021-2023" sliced as month "20" — fall back to year-only
        value = default
    return f"{int(year):04d}-{value:02d}"


def _normalize(line: str) -> str:
    text = line.strip()
    atx = ATX_RE.match(text)
    if atx:
        text = atx.group(1)
    text = text.strip(" \t:：、，,;；.。|｜/()（）【】[]·—–-")
    return re.sub(r"\s+", " ", text).casefold()


def _heading_of(line: str) -> tuple[str, str | None, str] | None:
    """Classify *line* as ``(kind, category_or_None, label)`` or None.

    Only *known* heading names qualify (with or without ATX markers);
    unknown ATX lines inside an experience section are entry headers,
    not section boundaries — free-form text never splits a section.
    """
    stripped = line.strip()
    if not stripped or len(stripped) > _MAX_HEADING_LINE:
        return None
    norm = _normalize(line)
    if not norm:
        return None
    for key in sorted(SECTION_CATEGORIES, key=len, reverse=True):
        if _matches_key(norm, key):
            return "experience", SECTION_CATEGORIES[key], norm
    for key in sorted(BOUNDARY_HEADINGS, key=len, reverse=True):
        if _matches_key(norm, key):
            return "boundary", None, norm
    return None


def _matches_key(norm: str, key: str) -> bool:
    if norm == key:
        return True
    if not norm.startswith(key):
        return False
    rest = norm[len(key):]
    if _CJK_KEY_RE.search(key):
        # CJK headings tolerate decorations: "工作经历（2018-2023）"
        return bool(_HEADING_SUFFIX_RE.match(rest) or rest == "")
    return False  # latin keys must match exactly ("experienced" != "experience")


def _entries_from_section(
    category: str, label: str, lines: list[str]
) -> list[ResumeEntry]:
    starts = _entry_starts(lines)
    if not starts:
        # fallback: each top-level bullet block is an entry
        starts = [
            i
            for i, line in enumerate(lines)
            if not line[:1].isspace() and BULLET_RE.match(line)
        ]
    entries: list[ResumeEntry] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(lines)
        entry = _entry_from_block(category, label, lines[start:end])
        if entry is not None:
            entries.append(entry)
    return entries


def _entry_starts(lines: list[str]) -> list[int]:
    starts: list[int] = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        is_header = ATX_RE.match(line) is not None or BOLD_RE.match(line) is not None
        dated = _has_date(line)
        # a date-bearing line starts an entry unless it is an indented
        # detail bullet of an entry that already started
        if is_header or (dated and (not BULLET_RE.match(line) or not starts)):
            starts.append(index)
    return starts


def _has_date(line: str) -> bool:
    return PRESENT_RE.search(line) is not None or any(
        _MIN_YEAR <= int(m.group(1)) <= _MAX_YEAR
        for m in MONTH_POINT_RE.finditer(line)
    )


def _entry_from_block(
    category: str, label: str, block: list[str]
) -> ResumeEntry | None:
    title_line = block[0]
    start, end = parse_period(title_line)
    dated = start is not None
    body = block[1:]
    if not dated:
        for index, line in enumerate(body):
            line_start, line_end = parse_period(line)
            if line_start is not None:
                start, end, dated = line_start, line_end, True
                body = body[:index] + body[index + 1 :]
                break
    title = _clean_title(title_line)
    if not title:
        for line in body:
            title = _clean_title(line)
            if title:
                break
    if not title:
        title = label or category
    description = _description_lines(body)
    if not dated:
        start, end = UNDATED_START, None
    return ResumeEntry(
        title=title,
        category=category,
        start=start or UNDATED_START,
        end=end,
        technology=extract_technology("\n".join(block)),
        description=description,
        dated=dated,
    )


def _clean_title(line: str) -> str:
    text = line.strip()
    atx = ATX_RE.match(text)
    if atx:
        text = atx.group(1)
    bold = BOLD_RE.match(text)
    if bold:
        text = bold.group(1) + text[bold.end():]
    text = BULLET_RE.sub("", text, count=1)
    text = YEAR_RANGE_RE.sub(" ", text)
    text = MONTH_POINT_RE.sub(" ", text)
    text = PRESENT_RE.sub(" ", text)
    text = text.strip(" \t|｜·—–-、，,;；：:/()（）【】[]")
    return re.sub(r"\s{2,}", " ", text).strip()


def _description_lines(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        text = BULLET_RE.sub("", line.rstrip(), count=1) if BULLET_RE.match(line) else line.rstrip()
        if text.strip():
            out.append(text.strip())
    return out
