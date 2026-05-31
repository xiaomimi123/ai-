"""合同柔性规则（LLM + RAG）：条款对标上位法、合理性分析（§3.4）。"""
from __future__ import annotations

from typing import List, Optional

from app.core.domain import Issue, IssueCategory, Location, RiskLevel
from app.parsers.base import ParsedDocument
from app.rules.base import SoftRule, SoftRuleContext

_RISK_MAP = {"高": RiskLevel.HIGH, "中": RiskLevel.MEDIUM, "低": RiskLevel.LOW}


class ContractComplianceSoftRule(SoftRule):
    id = "contract.compliance_llm"
    description = "合同条款合规性（对标上位法，LLM+RAG）"

    # 检索法规用的查询语，触达政府采购/合同管理相关规范
    RETRIEVE_QUERY = "政府采购 合同 付款 履约 违约 验收 合规 要求"

    def check(self, doc: ParsedDocument, ctx: Optional[SoftRuleContext]) -> List[Issue]:
        if ctx is None:
            return []
        laws = ctx.retrieve(self.RETRIEVE_QUERY, category="合同", top_k=5)
        # 兼容 category 未命中时不带过滤再召回
        if not laws:
            laws = ctx.retrieve(self.RETRIEVE_QUERY, category=None, top_k=5)

        law_text = "\n".join(
            f"[{getattr(c, 'metadata', {}).get('citation', '法规')}] {getattr(c, 'text', '')}"
            for c in laws
        ) or "（暂无检索到的法规条款）"

        # 控制 token：截取合同正文片段
        body = doc.text[:6000]
        prompt = (
            "请基于以下『检索到的法规条款』审查这份合同是否存在合规疑点。\n\n"
            f"【检索到的法规条款】\n{law_text}\n\n"
            f"【合同正文（节选）】\n{body}\n\n"
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


CONTRACT_SOFT_RULES = [ContractComplianceSoftRule()]
