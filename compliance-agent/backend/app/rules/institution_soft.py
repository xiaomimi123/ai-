"""内部制度柔性规则（LLM + RAG）：对标上位法、权责匹配、合理性（§3.4）。"""
from __future__ import annotations

from typing import List, Optional

from app.core.domain import Issue, IssueCategory, Location, RiskLevel
from app.parsers.base import ParsedDocument
from app.rules.base import SoftRule, SoftRuleContext

_RISK_MAP = {"高": RiskLevel.HIGH, "中": RiskLevel.MEDIUM, "低": RiskLevel.LOW}


class InstitutionComplianceSoftRule(SoftRule):
    id = "institution.compliance_llm"
    description = "制度合规性（对标内部控制规范等上位法，LLM+RAG）"

    RETRIEVE_QUERY = "行政事业单位 内部控制 制度 职责 不相容岗位 授权审批 风险 规范要求"

    def check(self, doc: ParsedDocument, ctx: Optional[SoftRuleContext]) -> List[Issue]:
        if ctx is None:
            return []
        laws = ctx.retrieve(self.RETRIEVE_QUERY, category="内部制度", top_k=5)
        if not laws:
            laws = ctx.retrieve(self.RETRIEVE_QUERY, category=None, top_k=5)

        law_text = "\n".join(
            f"[{getattr(c, 'metadata', {}).get('citation', '法规')}] {getattr(c, 'text', '')}"
            for c in laws
        ) or "（暂无检索到的法规条款）"

        body = doc.text[:6000]
        prompt = (
            "请基于以下『检索到的法规/规范条款』审查这份内部制度是否存在合规疑点"
            "（如与上位法冲突、权责不清、缺少不相容岗位分离或授权审批要求等）。\n\n"
            f"【检索到的法规/规范条款】\n{law_text}\n\n"
            f"【内部制度正文（节选）】\n{body}\n\n"
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


INSTITUTION_SOFT_RULES = [InstitutionComplianceSoftRule()]
