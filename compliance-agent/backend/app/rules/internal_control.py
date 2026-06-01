"""内控报告检查模板（§3.4）。

刚性规则：通用形式要素（年度/单位/日期/盖章）+ 内控特有必备章节。
《行政事业单位内部控制规范》明确报告应覆盖六大业务领域：
预算 / 收支 / 政府采购 / 资产 / 建设项目 / 合同。
"""
from __future__ import annotations

from typing import List

from app.core.domain import Issue, IssueCategory, RiskLevel
from app.parsers.base import ParsedDocument
from app.rules.base import RigidRule, SoftRule, SoftRuleContext
from app.rules.report_common import KeywordPresenceRule, _make_issue, common_report_rules

_RISK_MAP = {"高": RiskLevel.HIGH, "中": RiskLevel.MEDIUM, "低": RiskLevel.LOW}


class InternalControlBusinessAreasRule(RigidRule):
    id = "ic.business_areas"
    description = "内控报告六大业务领域覆盖情况"
    AREAS = {
        "预算业务": ["预算业务", "预算编制", "预算执行", "预算管理"],
        "收支业务": ["收支业务", "收入业务", "支出业务", "收支管理"],
        "政府采购业务": ["政府采购", "采购业务", "采购管理"],
        "资产业务": ["资产管理", "资产业务", "国有资产"],
        "建设项目": ["建设项目", "基本建设", "项目建设"],
        "合同业务": ["合同业务", "合同管理"],
    }

    def check(self, doc: ParsedDocument) -> List[Issue]:
        issues: List[Issue] = []
        for area, keywords in self.AREAS.items():
            if not any(k in doc.text for k in keywords):
                issues.append(_make_issue(
                    doc, self.id,
                    f"未检出「{area}」相关章节，内控报告应覆盖六大业务领域。",
                    f"补充「{area}」内控情况说明。",
                    risk=RiskLevel.MEDIUM, category=IssueCategory.PROCESS,
                ))
        return issues


INTERNAL_CONTROL_RIGID_RULES: List[RigidRule] = [
    *common_report_rules(),
    InternalControlBusinessAreasRule(),
    KeywordPresenceRule(
        id="ic.evaluation",
        description="内控自我评价结论是否载明",
        keywords=["自我评价", "评价结论", "内控有效性", "内部控制有效"],
        missing_desc="未检出内部控制自我评价结论。",
        suggestion="对本单位内控有效性给出明确评价结论。",
    ),
    KeywordPresenceRule(
        id="ic.deficiencies",
        description="内控缺陷与整改措施是否说明",
        keywords=["内控缺陷", "控制缺陷", "存在问题", "薄弱环节", "整改措施", "整改情况"],
        missing_desc="未检出内控缺陷与整改措施说明。",
        suggestion="逐项列示已识别的内控缺陷及整改计划。",
        category=IssueCategory.COMPLIANCE,
    ),
]


# ── 柔性规则 ──────────────────────────────────────────────
class InternalControlSoftRule(SoftRule):
    id = "ic.compliance_llm"
    description = "内控报告合规性（LLM+RAG）"
    RETRIEVE_QUERY = "行政事业单位 内部控制 报告 六大业务 自我评价 风险 缺陷"

    def check(self, doc, ctx):
        from app.core.domain import Issue, IssueCategory, Location
        if ctx is None:
            return []
        laws = ctx.retrieve(self.RETRIEVE_QUERY, category="内控报告", top_k=5)
        if not laws:
            laws = ctx.retrieve(self.RETRIEVE_QUERY, category=None, top_k=5)
        law_text = "\n".join(
            f"[{getattr(c, 'metadata', {}).get('citation', '法规')}] {getattr(c, 'text', '')}"
            for c in laws
        ) or "（暂无检索到的法规条款）"
        prompt = (
            "请基于以下『检索到的法规条款』审查这份内控报告是否存在合规疑点"
            "（如六大业务覆盖不全、自我评价缺乏依据、未披露重大内控缺陷等）。\n\n"
            f"【检索到的法规条款】\n{law_text}\n\n"
            f"【内控报告正文（节选）】\n{doc.text[:6000]}\n\n"
            "只依据上述法规判断，输出 JSON。"
        )
        raw_issues = ctx.llm_extract_issues(prompt)
        issues: List[Issue] = []
        file_name = doc.metadata.get("file_name", "")
        for item in raw_issues:
            if not isinstance(item, dict) or not item.get("description"):
                continue
            issues.append(Issue(
                description=str(item["description"]),
                location=Location(file_name=file_name),
                category=IssueCategory.COMPLIANCE,
                risk_level=_RISK_MAP.get(str(item.get("risk_level", "")), RiskLevel.MEDIUM),
                suggestion=str(item.get("suggestion", "")),
                legal_basis=str(item.get("legal_basis", "")),
                rule_id=self.id,
                source="soft",
            ))
        return issues


INTERNAL_CONTROL_SOFT_RULES = [InternalControlSoftRule()]
