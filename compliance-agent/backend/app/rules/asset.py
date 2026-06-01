"""国有资产报告检查模板（§3.4）。

资产报告应说明：资产总额/结构、新增/处置、盘点结果、出租出借、资产管理责任等。
"""
from __future__ import annotations

from typing import List

from app.core.domain import IssueCategory, RiskLevel
from app.rules.base import RigidRule, SoftRule
from app.rules.report_common import KeywordPresenceRule, common_report_rules

_RISK_MAP = {"高": RiskLevel.HIGH, "中": RiskLevel.MEDIUM, "低": RiskLevel.LOW}


ASSET_RIGID_RULES: List[RigidRule] = [
    *common_report_rules(),
    KeywordPresenceRule(
        id="asset.total",
        description="资产总额/分类构成是否披露",
        keywords=["资产总额", "资产构成", "资产规模", "资产合计", "总资产"],
        missing_desc="未检出资产总额/构成情况。",
        suggestion="按流动/非流动、固定/无形等口径披露资产规模与结构。",
        risk=RiskLevel.HIGH, category=IssueCategory.PROCESS,
    ),
    KeywordPresenceRule(
        id="asset.changes",
        description="资产增减变动情况是否说明",
        keywords=["新增资产", "增加情况", "处置", "减少情况", "变动情况", "增减变动"],
        missing_desc="未检出资产增减变动说明。",
        suggestion="说明本期资产增加、处置（报废/转让/捐赠）情况。",
    ),
    KeywordPresenceRule(
        id="asset.inventory",
        description="资产盘点情况是否说明",
        keywords=["资产盘点", "实物盘点", "盘点结果", "盘盈盘亏"],
        missing_desc="未检出资产盘点情况。",
        suggestion="说明本期资产盘点开展情况与盘盈盘亏处理。",
        category=IssueCategory.COMPLIANCE,
    ),
    KeywordPresenceRule(
        id="asset.lease",
        description="资产出租出借是否披露",
        keywords=["出租", "出借", "对外投资", "资产使用情况"],
        missing_desc="未检出资产出租/出借/对外投资披露。",
        suggestion="按规定披露资产出租出借及对外投资情况，明确审批程序。",
        category=IssueCategory.COMPLIANCE,
    ),
    KeywordPresenceRule(
        id="asset.responsibility",
        description="资产管理责任/制度是否说明",
        keywords=["管理制度", "管理责任", "责任人", "管理办法", "管理职责"],
        missing_desc="未检出资产管理责任/制度说明。",
        suggestion="说明本单位资产管理制度与责任分工。",
    ),
]


class AssetComplianceSoftRule(SoftRule):
    id = "asset.compliance_llm"
    description = "国有资产报告合规性（LLM+RAG）"
    RETRIEVE_QUERY = "行政事业单位 国有资产管理 报告 盘点 处置 出租出借 披露"

    def check(self, doc, ctx):
        from app.core.domain import Issue, Location
        if ctx is None:
            return []
        laws = ctx.retrieve(self.RETRIEVE_QUERY, category="国有资产报告", top_k=5)
        if not laws:
            laws = ctx.retrieve(self.RETRIEVE_QUERY, category=None, top_k=5)
        law_text = "\n".join(
            f"[{getattr(c, 'metadata', {}).get('citation', '法规')}] {getattr(c, 'text', '')}"
            for c in laws
        ) or "（暂无检索到的法规条款）"
        prompt = (
            "请基于以下『检索到的法规条款』审查这份国有资产报告是否存在合规疑点。\n\n"
            f"【检索到的法规条款】\n{law_text}\n\n"
            f"【资产报告正文（节选）】\n{doc.text[:6000]}\n\n"
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


ASSET_SOFT_RULES = [AssetComplianceSoftRule()]
