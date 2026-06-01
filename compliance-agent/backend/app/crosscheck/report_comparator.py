"""报告链比对（§3.5）：内控报告 ↔ 绩效报告 ↔ 项目资料。"""
from __future__ import annotations

from typing import List

from app.core.domain import Issue, IssueCategory, Location, RiskLevel
from app.crosscheck.schemas import ReportChainFields


def _name_similar(a: str, b: str) -> bool:
    if not a or not b:
        return True
    a2 = "".join(a.split())
    b2 = "".join(b.split())
    if a2 in b2 or b2 in a2:
        return True
    overlap = len(set(a2) & set(b2))
    return overlap / max(len(set(a2)), len(set(b2))) >= 0.7


def _issue(desc, files, rule_id, risk=RiskLevel.MEDIUM,
           suggestion="", category=IssueCategory.CONSISTENCY) -> Issue:
    return Issue(
        description=desc,
        location=Location(file_name=" + ".join(f for f in files if f)),
        category=category,
        risk_level=risk,
        suggestion=suggestion,
        rule_id=rule_id,
        source="crosscheck",
    )


def compare_report_chain(fields: ReportChainFields) -> List[Issue]:
    issues: List[Issue] = []
    ic = fields.internal_control
    perf = fields.performance
    pm = fields.project_material

    # 1. 年度一致性
    years = [(ic.year if ic else None, fields.ic_file),
             (perf.year if perf else None, fields.perf_file)]
    years_present = [(y, f) for y, f in years if y]
    if len(years_present) >= 2:
        base_y, base_f = years_present[0]
        for y, f in years_present[1:]:
            if y != base_y:
                issues.append(_issue(
                    f"报告年度不一致：{base_y}年（{base_f}） vs {y}年（{f}）。",
                    [base_f, f], "report.year_mismatch",
                    suggestion="确认所对比的报告为同一年度。",
                ))
                break

    # 2. 绩效报告项目 vs 内控报告中提及的项目（互相印证）
    if perf and ic and perf.project_name and ic.project_mentions:
        matched = any(_name_similar(perf.project_name, n) for n in ic.project_mentions)
        if not matched:
            issues.append(_issue(
                f"绩效评价的项目「{perf.project_name}」未在内控报告中提及，"
                f"内控报告范围可能未覆盖该项目。",
                [fields.perf_file, fields.ic_file], "report.perf_in_ic",
                category=IssueCategory.LOGIC,
                suggestion="核实内控报告是否覆盖了绩效评价对应的项目。",
            ))

    # 3. 绩效报告项目 vs 项目资料一致性
    if perf and pm and perf.project_name and pm.project_name:
        if not _name_similar(perf.project_name, pm.project_name):
            issues.append(_issue(
                f"绩效评价项目「{perf.project_name}」与项目资料「{pm.project_name}」"
                f"名称不一致。",
                [fields.perf_file, fields.project_file],
                "report.perf_vs_material_name",
                suggestion="确认对应同一项目，或附说明。",
            ))

    # 4. 项目资料完整性：有项目就应有立项与验收两套留痕
    if pm and pm.project_name:
        if not pm.has_approval:
            issues.append(_issue(
                f"项目资料中未见立项/审批留痕（项目：{pm.project_name}）。",
                [fields.project_file], "report.material_no_approval",
                risk=RiskLevel.HIGH, category=IssueCategory.PROCESS,
                suggestion="补充立项批复/审批文件作为佐证。",
            ))
        if not pm.has_completion:
            issues.append(_issue(
                f"项目资料中未见验收/完工留痕（项目：{pm.project_name}）。",
                [fields.project_file], "report.material_no_completion",
                risk=RiskLevel.MEDIUM, category=IssueCategory.PROCESS,
                suggestion="补充验收报告/结项材料作为佐证。",
            ))

    # 5. 绩效得分与评价等次的一致性（自我对照）
    if perf and perf.score is not None and perf.grade:
        # 通常：≥90 优，80-89 良，60-79 中，<60 差
        expected = ""
        if perf.score >= 90: expected = "优"
        elif perf.score >= 80: expected = "良"
        elif perf.score >= 60: expected = "中"
        else: expected = "差"
        if perf.grade not in (expected, ""):
            issues.append(_issue(
                f"绩效得分 {perf.score} 与评价等次「{perf.grade}」不匹配"
                f"（按常用标准应为「{expected}」）。",
                [fields.perf_file], "report.score_vs_grade",
                category=IssueCategory.LOGIC,
                suggestion="复核评价等次划分标准与得分对应关系。",
            ))

    # 6. 内控自评结论 vs 缺陷数量的逻辑合理性
    if ic and ic.evaluation_result and ic.deficiency_count is not None:
        if "有效" in ic.evaluation_result and ic.deficiency_count >= 5:
            issues.append(_issue(
                f"内控自我评价结论为「{ic.evaluation_result}」，但披露内控缺陷 "
                f"{ic.deficiency_count} 项，结论与缺陷数量可能不匹配。",
                [fields.ic_file], "report.ic_eval_vs_deficiency",
                category=IssueCategory.LOGIC,
                suggestion="复核自我评价结论是否与已识别缺陷情况相一致。",
            ))

    # 7. 链路完整性
    missing = []
    if ic is None: missing.append("内控报告")
    if perf is None: missing.append("绩效报告")
    if pm is None: missing.append("项目资料")
    if missing:
        issues.append(_issue(
            f"报告链不完整，缺失：{'、'.join(missing)}。",
            [], "report.completeness", risk=RiskLevel.LOW,
            category=IssueCategory.OTHER,
            suggestion="补齐缺失环节后重新运行联动校验。",
        ))

    return issues
