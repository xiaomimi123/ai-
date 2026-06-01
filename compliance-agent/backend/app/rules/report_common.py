"""报告类模板的共用规则与构造器（内控/财务+决算/资产/绩效共享）。

这些规则的形态高度一致：检查「报告年度」「编制单位」「编制日期」「关键章节关键词」
等通用要素。抽出来避免在 4 个模板里重复同样的代码。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Sequence

from app.core.domain import Issue, IssueCategory, Location, RiskLevel
from app.parsers.base import ParsedDocument
from app.rules.base import RigidRule

_YEAR_RE = re.compile(r"(20\d{2}|19\d{2})\s*年(?!\s*\d{1,2}\s*月\s*\d{1,2}\s*日)")
_FULL_DATE_RE = re.compile(r"(20\d{2}|19\d{2})\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日")
_UNIT_LABEL_RE = re.compile(
    r"(编制单位|报送单位|填报单位|本单位名称|单位名称)\s*[（(]?[盖章公章]*[)）]?\s*[:：][ \t]*([^\n，,。；;]{2,30})"
)


def _loc(doc: ParsedDocument) -> Location:
    return Location(file_name=doc.metadata.get("file_name", ""))


def _make_issue(doc, rule_id, desc, suggestion,
                risk=RiskLevel.MEDIUM, category=IssueCategory.FORMAT) -> Issue:
    return Issue(description=desc, location=_loc(doc), category=category,
                 risk_level=risk, suggestion=suggestion, rule_id=rule_id)


# ── 通用规则类 ───────────────────────────────────────────

@dataclass
class KeywordPresenceRule(RigidRule):
    """检查文档中是否出现任一关键词；缺失则报问题。"""
    id: str = ""
    description: str = ""
    keywords: Sequence[str] = ()
    missing_desc: str = ""
    suggestion: str = ""
    risk: RiskLevel = RiskLevel.MEDIUM
    category: IssueCategory = IssueCategory.FORMAT

    def check(self, doc: ParsedDocument) -> List[Issue]:
        if any(k in doc.text for k in self.keywords):
            return []
        return [_make_issue(doc, self.id, self.missing_desc,
                            self.suggestion, risk=self.risk, category=self.category)]


class ReportYearRule(RigidRule):
    id = "report.year"
    description = "报告年度是否明确"

    def check(self, doc: ParsedDocument) -> List[Issue]:
        # 全文找「XXXX年」即可（不要求恰在标题），首 800 字优先
        if _YEAR_RE.search(doc.text[:800]) or _YEAR_RE.search(doc.text):
            return []
        return [_make_issue(doc, self.id,
                            "未检出明确的报告年度（如「2026年度」）。",
                            "在标题或封面明确报告年度。")]


class ReportUnitRule(RigidRule):
    id = "report.unit"
    description = "编制单位是否载明"

    def check(self, doc: ParsedDocument) -> List[Issue]:
        m = _UNIT_LABEL_RE.search(doc.text)
        if m and len(m.group(2).strip()) >= 2:
            return []
        # 退化：标题/首段提到「XX单位」或「XX局」「XX中心」也算
        head = doc.text[:300]
        if re.search(r"[一-龥]{2,15}(单位|局|中心|学校|医院|机关|委员会|办公室|部|处|科)", head):
            return []
        return [_make_issue(doc, self.id,
                            "未检出明确的编制单位/报送单位。",
                            "在报告封面或落款处载明编制单位完整名称。")]


class ReportDateRule(RigidRule):
    id = "report.date"
    description = "编制/报送日期是否明确"

    def check(self, doc: ParsedDocument) -> List[Issue]:
        if _FULL_DATE_RE.search(doc.text):
            return []
        return [_make_issue(doc, self.id,
                            "未检出明确的编制/报送日期（年月日）。",
                            "在落款处补充编制日期。")]


class ReportSealRule(RigidRule):
    id = "report.seal"
    description = "盖章/签字留痕是否存在"
    KEYWORDS = ("盖章", "公章", "签字", "签发", "（盖章）", "(盖章)", "负责人")

    def check(self, doc: ParsedDocument) -> List[Issue]:
        if any(k in doc.text for k in self.KEYWORDS):
            return []
        return [_make_issue(doc, self.id,
                            "未检出盖章/签字留痕，正式报告应有单位盖章与负责人签字。",
                            "补充编制单位盖章、负责人签字。",
                            risk=RiskLevel.HIGH, category=IssueCategory.PROCESS)]


def common_report_rules() -> List[RigidRule]:
    """4 个报告类模板都会用到的形式要素规则。"""
    return [ReportYearRule(), ReportUnitRule(), ReportDateRule(), ReportSealRule()]
