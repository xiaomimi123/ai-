"""财务+决算联合检查模板（§3.4）。

行政事业单位财务/决算报告应包含：
资产负债表、收入支出表（部门决算用「财政拨款收支决算总表」「一般公共预算财政拨款支出表」等）、
现金流量表/净资产变动表、附注说明。还需核对预决算差异、三公经费等。
"""
from __future__ import annotations

from typing import List

from app.core.domain import Issue, IssueCategory, RiskLevel
from app.parsers.base import ParsedDocument
from app.rules.base import RigidRule, SoftRule
from app.rules.report_common import KeywordPresenceRule, _make_issue, common_report_rules

_RISK_MAP = {"高": RiskLevel.HIGH, "中": RiskLevel.MEDIUM, "低": RiskLevel.LOW}


class FinancialStatementsRule(RigidRule):
    id = "fin.statements"
    description = "三大主表是否齐全"
    STATEMENTS = {
        "资产负债表": ["资产负债表"],
        "收入支出表": ["收入支出表", "收支决算总表", "财政拨款收支决算"],
        "现金流量表/净资产变动表": ["现金流量表", "净资产变动表", "财政拨款支出决算"],
    }

    def check(self, doc: ParsedDocument) -> List[Issue]:
        issues: List[Issue] = []
        for name, keys in self.STATEMENTS.items():
            if not any(k in doc.text for k in keys):
                issues.append(_make_issue(
                    doc, self.id,
                    f"未检出「{name}」相关内容，财务/决算报告应附主要报表。",
                    f"补充「{name}」。",
                    risk=RiskLevel.HIGH, category=IssueCategory.PROCESS,
                ))
        return issues


FINANCE_FINAL_RIGID_RULES: List[RigidRule] = [
    *common_report_rules(),
    FinancialStatementsRule(),
    KeywordPresenceRule(
        id="fin.notes",
        description="附注/说明是否提供",
        keywords=["附注", "报表说明", "财务情况说明书", "决算说明", "情况说明"],
        missing_desc="未检出报表附注/财务情况说明书。",
        suggestion="编制报表附注或财务情况说明，对重要会计政策和项目作出说明。",
    ),
    KeywordPresenceRule(
        id="fin.budget_diff",
        description="预决算差异分析是否说明",
        keywords=["预决算差异", "预算与决算", "执行情况分析", "差异说明", "执行率"],
        missing_desc="未检出预决算差异/预算执行率分析。",
        suggestion="说明预算与决算的主要差异原因及执行情况。",
        category=IssueCategory.COMPLIANCE,
    ),
    KeywordPresenceRule(
        id="fin.three_public",
        description="三公经费披露是否完整",
        keywords=["三公经费", "公务接待", "公务用车", "因公出国", "因公出境"],
        missing_desc="未检出三公经费披露。",
        suggestion="按规定披露因公出国（境）、公务用车、公务接待经费支出。",
        category=IssueCategory.COMPLIANCE,
    ),
]


class FinanceComplianceSoftRule(SoftRule):
    id = "fin.compliance_llm"
    description = "财务/决算报告合规性（LLM+RAG）"
    RETRIEVE_QUERY = "政府会计制度 部门决算 财务报告 三公经费 预决算差异 披露要求"

    def check(self, doc, ctx):
        from app.core.domain import Issue, IssueCategory, Location
        if ctx is None:
            return []
        laws = ctx.retrieve(self.RETRIEVE_QUERY, category="财务报告", top_k=5)
        if not laws:
            laws = ctx.retrieve(self.RETRIEVE_QUERY, category=None, top_k=5)
        law_text = "\n".join(
            f"[{getattr(c, 'metadata', {}).get('citation', '法规')}] {getattr(c, 'text', '')}"
            for c in laws
        ) or "（暂无检索到的法规条款）"
        prompt = (
            "请基于以下『检索到的法规条款』审查这份财务/决算报告是否存在合规疑点。\n\n"
            f"【检索到的法规条款】\n{law_text}\n\n"
            f"【报告正文（节选）】\n{doc.text[:6000]}\n\n"
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


FINANCE_FINAL_SOFT_RULES = [FinanceComplianceSoftRule()]
