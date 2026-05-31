"""招采三合一柔性规则（LLM + RAG）：对标政府采购法等上位法（§3.4）。"""
from __future__ import annotations

from typing import List, Optional

from app.core.domain import Issue, IssueCategory, Location, RiskLevel
from app.parsers.base import ParsedDocument
from app.rules.base import SoftRule, SoftRuleContext
from app.rules.procurement import resolve_subtype

_RISK_MAP = {"高": RiskLevel.HIGH, "中": RiskLevel.MEDIUM, "低": RiskLevel.LOW}

_SUBTYPE_QUERIES = {
    "招标": "政府采购 招标文件 招标公告 投标人资格 评标办法 最高限价 合规要求",
    "投标": "政府采购 投标文件 投标报价 投标有效期 资格声明 合规要求",
    "评标": "政府采购 评标委员会 评标报告 中标候选人 评分标准 合规要求",
}


class ProcurementComplianceSoftRule(SoftRule):
    id = "proc.compliance_llm"
    description = "招采文件合规性（对标政府采购法，LLM+RAG）"

    def check(self, doc: ParsedDocument, ctx: Optional[SoftRuleContext]) -> List[Issue]:
        if ctx is None:
            return []
        subtype = resolve_subtype(doc)
        query = _SUBTYPE_QUERIES.get(subtype, _SUBTYPE_QUERIES["招标"])

        laws = ctx.retrieve(query, category="采购招标", top_k=5)
        if not laws:
            laws = ctx.retrieve(query, category=None, top_k=5)

        law_text = "\n".join(
            f"[{getattr(c, 'metadata', {}).get('citation', '法规')}] {getattr(c, 'text', '')}"
            for c in laws
        ) or "（暂无检索到的法规条款）"

        body = doc.text[:6000]
        prompt = (
            f"请基于以下『检索到的法规条款』审查这份【{subtype}文件】是否存在合规疑点。\n\n"
            f"【检索到的法规条款】\n{law_text}\n\n"
            f"【{subtype}文件正文（节选）】\n{body}\n\n"
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


PROCUREMENT_SOFT_RULES = [ProcurementComplianceSoftRule()]
