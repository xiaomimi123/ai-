"""内部制度合规检查模板的刚性规则（§3.4）。

确定性校验，不调用 LLM。针对行政事业单位内部制度（管理办法/规定/细则等）
的通用形式要素与必备章节。
"""
from __future__ import annotations

import re
from typing import List

from app.core.domain import Issue, IssueCategory, Location, RiskLevel
from app.parsers.base import ParsedDocument
from app.rules.base import RigidRule
from app.rules.utils import locate

# 制度类文件名/标题常见后缀
_TITLE_KEYWORDS = ("制度", "办法", "规定", "细则", "规程", "准则", "规范", "章程", "方案")

# 发文文号：机关代字 + 〔年份〕 + 序号 + 号，兼容 〔〕[]【】（）
_DOC_NUMBER_RE = re.compile(
    r"[一-龥A-Za-z]{1,15}\s*[〔\[【（]\s*\d{4}\s*[〕\]】）]\s*第?\s*\d+\s*号"
)


class InstitutionNameRule(RigidRule):
    id = "institution.name"
    description = "制度名称/标题是否存在"

    def check(self, doc: ParsedDocument) -> List[Issue]:
        head = doc.text[:300]
        if "《" in head and "》" in head:
            return []
        if any(k in head for k in _TITLE_KEYWORDS):
            return []
        return [Issue(
            description="未检出明确的制度名称/标题，制度文件应有规范名称（如《XX管理办法》）。",
            location=Location(file_name=doc.metadata.get("file_name", "")),
            category=IssueCategory.FORMAT,
            risk_level=RiskLevel.MEDIUM,
            suggestion="补充规范的制度名称，置于文首。",
            rule_id=self.id,
        )]


class DocumentNumberRule(RigidRule):
    id = "institution.doc_number"
    description = "发文文号是否存在"

    def check(self, doc: ParsedDocument) -> List[Issue]:
        if _DOC_NUMBER_RE.search(doc.text):
            return []
        return [Issue(
            description="未检出发文文号（如「XX发〔2026〕X号」），正式印发制度应有发文文号。",
            location=Location(file_name=doc.metadata.get("file_name", "")),
            category=IssueCategory.FORMAT,
            risk_level=RiskLevel.MEDIUM,
            suggestion="按公文格式补充发文文号，并纳入发文登记。",
            rule_id=self.id,
        )]


class EffectiveDateRule(RigidRule):
    id = "institution.effective_date"
    description = "施行/生效日期是否明确"
    _re = re.compile(r"(自|于).{0,20}(起)?\s*(施行|实行|生效|执行)")

    def check(self, doc: ParsedDocument) -> List[Issue]:
        if self._re.search(doc.text) or "施行日期" in doc.text:
            return []
        return [Issue(
            description="未检出明确的施行/生效日期，制度应载明生效时间。",
            location=Location(file_name=doc.metadata.get("file_name", "")),
            category=IssueCategory.FORMAT,
            risk_level=RiskLevel.MEDIUM,
            suggestion="在附则中明确「自X年X月X日起施行」。",
            rule_id=self.id,
        )]


class BasisRule(RigidRule):
    id = "institution.basis"
    description = "制定依据（上位法）是否说明"
    KEYWORDS = ("根据《", "依据《", "按照《", "根据国家", "依据有关", "为了规范", "为规范", "为加强")

    def check(self, doc: ParsedDocument) -> List[Issue]:
        if any(k in doc.text for k in self.KEYWORDS):
            return []
        return [Issue(
            description="未检出制定依据，制度应说明依据的上位法或规范（如《行政事业单位内部控制规范》）。",
            location=Location(file_name=doc.metadata.get("file_name", "")),
            category=IssueCategory.COMPLIANCE,
            risk_level=RiskLevel.MEDIUM,
            suggestion="在总则中写明制定依据，引用对应上位法。",
            rule_id=self.id,
        )]


class RequiredSectionsRule(RigidRule):
    id = "institution.required_sections"
    description = "必备章节是否齐全（总则/适用范围/职责/附则）"
    REQUIRED = {
        "总则": ["总则"],
        "适用范围": ["适用范围", "适用对象", "适用于", "适用本"],
        "职责分工": ["职责", "权限", "分工", "岗位"],
        "附则": ["附则", "解释权", "自发布", "自印发"],
    }

    def check(self, doc: ParsedDocument) -> List[Issue]:
        issues: List[Issue] = []
        text = doc.text
        for section, keywords in self.REQUIRED.items():
            if not any(k in text for k in keywords):
                issues.append(Issue(
                    description=f"未检出「{section}」相关内容，制度结构要素可能缺失。",
                    location=Location(file_name=doc.metadata.get("file_name", "")),
                    category=IssueCategory.PROCESS,
                    risk_level=RiskLevel.LOW,
                    suggestion=f"补充「{section}」部分，使制度结构完整。",
                    rule_id=self.id,
                ))
        return issues


class ApprovalRule(RigidRule):
    id = "institution.approval"
    description = "审议/批准/印发留痕是否存在"
    KEYWORDS = ("审议通过", "审定", "批准", "印发", "签发", "会议通过", "研究通过", "经.*同意")

    def check(self, doc: ParsedDocument) -> List[Issue]:
        text = doc.text
        if any(re.search(k, text) if "." in k else (k in text) for k in self.KEYWORDS):
            return []
        return [Issue(
            description="未检出审议/批准/印发等决策留痕，制度出台应有相应审批程序记录。",
            location=Location(file_name=doc.metadata.get("file_name", "")),
            category=IssueCategory.PROCESS,
            risk_level=RiskLevel.MEDIUM,
            suggestion="补充制度经会议审议通过/领导批准/正式印发的留痕信息。",
            rule_id=self.id,
        )]


INSTITUTION_RIGID_RULES = [
    InstitutionNameRule(),
    DocumentNumberRule(),
    EffectiveDateRule(),
    BasisRule(),
    RequiredSectionsRule(),
    ApprovalRule(),
]
