"""财务链字段比对（§3.5）。

财务报告 ↔ 决算报告 ↔ 资产报告 ↔ 合同付款 数据交叉互验。
完全确定性，不调 LLM。
"""
from __future__ import annotations

from typing import List

from app.core.domain import Issue, IssueCategory, Location, RiskLevel
from app.crosscheck.schemas import FinanceChainFields

# 金额比对容差（按比例）：报表数字常有元/万元转换尾差，允许 0.5% 偏差
_REL_TOL = 0.005


def _close(a, b) -> bool:
    if a is None or b is None:
        return True  # 缺失另外报
    if a == 0 and b == 0:
        return True
    return abs(a - b) / max(abs(a), abs(b), 1.0) <= _REL_TOL


def _issue(desc, files, rule_id, risk=RiskLevel.HIGH,
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


def compare_finance_chain(fields: FinanceChainFields) -> List[Issue]:
    issues: List[Issue] = []
    fin = fields.finance
    fa = fields.final_account
    asset = fields.asset

    # 1. 财务报告：资产 = 负债 + 净资产（会计恒等式）
    if fin and fin.total_assets is not None and \
       fin.total_liabilities is not None and fin.total_net_assets is not None:
        expected = round(fin.total_liabilities + fin.total_net_assets, 2)
        if not _close(fin.total_assets, expected):
            issues.append(_issue(
                f"会计恒等式不成立：资产 {fin.total_assets} ≠ 负债 {fin.total_liabilities} "
                f"+ 净资产 {fin.total_net_assets}（合计 {expected}）。",
                [fields.finance_file], "fin.balance_sheet_identity",
                suggestion="核对资产负债表勾稽关系，确认录入/口径无误。",
            ))

    # 2. 财务报告 vs 决算报告：年度收入/支出应一致
    if fin and fa:
        if fin.total_income is not None and fa.total_income is not None and \
                not _close(fin.total_income, fa.total_income):
            issues.append(_issue(
                f"收入数据不一致：财务报告 {fin.total_income} vs 决算报告 {fa.total_income}。",
                [fields.finance_file, fields.final_account_file], "fin.income_vs_final",
                suggestion="核对财务报告与决算报告收入口径与编报基础。",
            ))
        if fin.total_expense is not None and fa.total_expense is not None and \
                not _close(fin.total_expense, fa.total_expense):
            issues.append(_issue(
                f"支出数据不一致：财务报告 {fin.total_expense} vs 决算报告 {fa.total_expense}。",
                [fields.finance_file, fields.final_account_file], "fin.expense_vs_final",
                suggestion="核对财务报告与决算报告支出口径。",
            ))

    # 3. 财务报告资产总额 vs 资产报告总额
    if fin and asset and fin.total_assets is not None and asset.total_assets is not None:
        if not _close(fin.total_assets, asset.total_assets):
            issues.append(_issue(
                f"资产总额不一致：财务报告 {fin.total_assets} vs 资产报告 {asset.total_assets}。",
                [fields.finance_file, fields.asset_file], "fin.assets_vs_asset_report",
                suggestion="核对资产负债表与资产报告口径，必要时附差异说明。",
            ))

    # 4. 预决算差异：决算收入 vs 预算总额
    if fa and fa.budget_total is not None and fa.total_income is not None:
        diff = abs(fa.total_income - fa.budget_total)
        max_v = max(fa.budget_total, fa.total_income, 1.0)
        if diff / max_v > 0.10:  # 偏差 > 10% 提示
            issues.append(_issue(
                f"预决算偏差较大：预算 {fa.budget_total} vs 决算 {fa.total_income}，"
                f"偏差 {round(diff/max_v*100,1)}%。",
                [fields.final_account_file], "fin.budget_vs_actual",
                risk=RiskLevel.MEDIUM, category=IssueCategory.COMPLIANCE,
                suggestion="预决算差异超过 10% 应在决算说明中重点解释。",
            ))

    # 5. 合同付款 vs 支出科目：所有合同金额之和不应超过决算支出
    if fields.contract_amounts and fa and fa.total_expense is not None:
        total_contracts = sum(c.amount for c in fields.contract_amounts if c.amount is not None)
        if total_contracts > fa.total_expense * 1.005:  # 留 0.5% 容差
            issues.append(_issue(
                f"合同金额合计 {round(total_contracts,2)} 超出决算支出 {fa.total_expense}，"
                f"合同付款与决算支出不匹配。",
                [fields.final_account_file], "fin.contracts_vs_expense",
                risk=RiskLevel.MEDIUM, category=IssueCategory.CONSISTENCY,
                suggestion="核对合同付款是否全部纳入决算支出。",
            ))

    # 6. 年度一致性
    years = [(fin.year if fin else None, fields.finance_file),
             (fa.year if fa else None, fields.final_account_file),
             (asset.year if asset else None, fields.asset_file)]
    years_present = [(y, f) for y, f in years if y]
    if len(years_present) >= 2:
        base_y, base_f = years_present[0]
        for y, f in years_present[1:]:
            if y != base_y:
                issues.append(_issue(
                    f"报告年度不一致：{base_y}年（{base_f}） vs {y}年（{f}）。",
                    [base_f, f], "fin.year_mismatch",
                    risk=RiskLevel.MEDIUM,
                    suggestion="确认所对比的报告为同一年度。",
                ))
                break

    # 7. 链路完整性
    missing = []
    if fin is None: missing.append("财务报告")
    if fa is None: missing.append("决算报告")
    if asset is None: missing.append("资产报告")
    if missing:
        issues.append(_issue(
            f"财务链不完整，缺失：{'、'.join(missing)}。部分跨文件比对未执行。",
            [], "fin.completeness", risk=RiskLevel.LOW,
            category=IssueCategory.OTHER,
            suggestion="补齐缺失环节文件后重新运行联动校验。",
        ))

    return issues
