"""绩效评价报告检查模板（§3.4）。

按《财政部预算绩效管理》要求，绩效评价报告应包含：
项目概况、目标设定、指标体系（产出/效益/满意度）、得分/等次、问题与建议。
"""
from __future__ import annotations

from typing import List

from app.core.domain import IssueCategory, RiskLevel
from app.rules.base import RigidRule, SoftRule
from app.rules.report_common import KeywordPresenceRule, common_report_rules

_RISK_MAP = {"高": RiskLevel.HIGH, "中": RiskLevel.MEDIUM, "低": RiskLevel.LOW}


PERFORMANCE_RIGID_RULES: List[RigidRule] = [
    *common_report_rules(),
    KeywordPresenceRule(
        id="perf.project_overview",
        description="项目/资金概况是否说明",
        keywords=["项目概况", "资金概况", "项目背景", "资金来源", "立项依据"],
        missing_desc="未检出项目/资金概况。",
        suggestion="说明被评价项目的背景、资金规模、来源及实施周期。",
    ),
    KeywordPresenceRule(
        id="perf.objectives",
        description="绩效目标是否载明",
        keywords=["绩效目标", "总体目标", "工作目标", "目标设定", "预期目标"],
        missing_desc="未检出绩效目标。",
        suggestion="载明项目设定的绩效目标，便于实施评价对照。",
        risk=RiskLevel.HIGH, category=IssueCategory.PROCESS,
    ),
    KeywordPresenceRule(
        id="perf.indicators",
        description="绩效指标体系（产出/效益/满意度）是否覆盖",
        keywords=["产出指标", "效益指标", "满意度指标", "三级指标", "指标体系"],
        missing_desc="未检出完整的绩效指标体系（产出/效益/满意度）。",
        suggestion="按三类指标搭建评价指标体系：产出、效益、服务对象满意度。",
        category=IssueCategory.PROCESS,
    ),
    KeywordPresenceRule(
        id="perf.score",
        description="评价得分/等次是否明确",
        keywords=["综合得分", "评价得分", "评价等次", "评价等级", "总分"],
        missing_desc="未检出评价得分/等次。",
        suggestion="给出综合得分及评价等次（优/良/中/差）。",
        risk=RiskLevel.HIGH,
    ),
    KeywordPresenceRule(
        id="perf.problems",
        description="存在问题与改进建议是否说明",
        keywords=["存在问题", "主要问题", "改进建议", "整改建议", "问题与建议"],
        missing_desc="未检出存在问题/改进建议。",
        suggestion="列示评价发现的问题及改进建议，用于结果应用。",
        category=IssueCategory.COMPLIANCE,
    ),
]


class PerformanceComplianceSoftRule(SoftRule):
    id = "perf.compliance_llm"
    description = "绩效评价报告合规性（LLM+RAG）"
    RETRIEVE_QUERY = "预算绩效管理 绩效评价 产出指标 效益指标 满意度 评价结果 应用"

    def check(self, doc, ctx):
        from app.core.domain import Issue, Location
        if ctx is None:
            return []
        laws = ctx.retrieve(self.RETRIEVE_QUERY, category="绩效评价报告", top_k=5)
        if not laws:
            laws = ctx.retrieve(self.RETRIEVE_QUERY, category=None, top_k=5)
        law_text = "\n".join(
            f"[{getattr(c, 'metadata', {}).get('citation', '法规')}] {getattr(c, 'text', '')}"
            for c in laws
        ) or "（暂无检索到的法规条款）"
        prompt = (
            "请基于以下『检索到的法规条款』审查这份绩效评价报告是否存在合规疑点"
            "（如指标设计不科学、得分依据不足、评价结果未用于预算管理等）。\n\n"
            f"【检索到的法规条款】\n{law_text}\n\n"
            f"【绩效评价报告正文（节选）】\n{doc.text[:6000]}\n\n"
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


PERFORMANCE_SOFT_RULES = [PerformanceComplianceSoftRule()]
