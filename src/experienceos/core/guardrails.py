"""Evidence guardrails (#013): flag unsupported quantitative claims.

Pure functions, no LLM. The rule: contribution/result bullets that
assert measurable impact — numbers, multiples, percentages, rankings —
should be backed by evidence. When a record carries no evidence at all,
its quantitative claims are reported so the user can link evidence,
rephrase the claim, or mark it as recalled from memory
(``source=interview``), matching ``EVIDENCE_GUARDRAIL_NOTE`` in the AI
layer.

Year-like numbers ("migrated in 2023") are deliberately ignored: they
rarely measure impact and would drown the signal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from experienceos.core.models import Experience

SUGGESTION = (
    "link an evidence item to this record, rephrase the claim without "
    "the number, or record it as a memory (source=interview)"
)

# specific measurable-impact patterns (CN + EN)
QUANTITATIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\d+(?:\.\d+)?\s*[%％]"),                                    # 40%
    re.compile(r"(?<![\w.])\d+(?:\.\d+)?\s*[xX](?![\w])"),                   # 3x
    re.compile(r"\d+(?:\.\d+)?\s*倍"),                                        # 3倍
    re.compile(r"\b\d+(?:\.\d+)?\s+times\b", re.IGNORECASE),                  # 3 times
    re.compile(r"\btop\s*\d+", re.IGNORECASE),                                # Top 10
    re.compile(r"前\s*\d+\s*名?"),                                             # 前3名
    re.compile(r"第\s*\d+\s*名"),                                              # 第1名
    re.compile(r"排名[^0-9]{0,2}\d+"),                                         # 排名 5
    re.compile(r"(?:^|\s)#\s*\d+\b"),                                         # #2
    re.compile(r"\bno\.\s*\d+\b", re.IGNORECASE),                             # No.1
    re.compile(r"\d+(?:\.\d+)?\s*[万亿]"),                                     # 10万
    re.compile(r"\b\d+(?:\.\d+)?[kKmMwW]\b"),                                 # 100k / 5w
    re.compile(r"\b\d+(?:,\d{3})+\b"),                                        # 10,000
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:ms|us|μs|qps|tps|rps)\b", re.IGNORECASE),  # 50ms
    re.compile(r"\b\d+\s*\+"),                                                # 30+
    re.compile(r"\d+\s*(?:个|人|台|条|次|名|位|家)"),                            # 50个服务
)
_GENERIC_NUMBER = re.compile(r"\b\d{2,}\b")  # 12, 100 — years filtered apart

CLAIM_FIELDS = ("contribution", "result")


@dataclass(frozen=True)
class ClaimIssue:
    """One quantitative sentence that no evidence backs."""

    experience_id: str
    field: str
    sentence: str
    suggestion: str = SUGGESTION


def quantitative_claim(sentence: str) -> bool:
    """True when *sentence* asserts something measurable."""
    for pattern in QUANTITATIVE_PATTERNS:
        if pattern.search(sentence):
            return True
    return any(
        not _is_year_like(match.group(0))
        for match in _GENERIC_NUMBER.finditer(sentence)
    )


def find_unsupported_claims(experience: Experience) -> list[ClaimIssue]:
    """Quantitative claims in *experience* that lack evidence.

    Evidence attaches at record level, so any evidence item clears the
    whole record — the guardrail never claims to know *which* evidence
    supports *which* sentence.
    """
    if experience.evidence:
        return []
    issues: list[ClaimIssue] = []
    for field_name in CLAIM_FIELDS:
        for sentence in getattr(experience, field_name):
            if quantitative_claim(sentence):
                issues.append(
                    ClaimIssue(
                        experience_id=experience.id,
                        field=field_name,
                        sentence=sentence,
                    )
                )
    return issues


def lint_experiences(experiences: list[Experience]) -> list[ClaimIssue]:
    """Aggregate unsupported claims across a set of records."""
    return [
        issue
        for experience in experiences
        for issue in find_unsupported_claims(experience)
    ]


def _is_year_like(token: str) -> bool:
    return len(token) == 4 and token.isdigit() and 1900 <= int(token) <= 2099
