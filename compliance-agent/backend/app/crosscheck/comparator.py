"""字段级 + 语义比对器（§3.5）。

完全确定性，不调 LLM。逐一比对招采链的关键字段，
不一致处产出 Issue（统一结构，与单文件检查共用）。
"""
from __future__ import annotations

from typing import List, Optional

from app.core.domain import Issue, IssueCategory, Location, RiskLevel
from app.crosscheck.schemas import ChainFields

# 金额比对容差（元）：处理 0.01 浮点舍入与小额尾差
_AMOUNT_TOL = 0.01


def _amount_close(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return True  # 缺失值另外报，不在此重复报
    return abs(a - b) <= _AMOUNT_TOL


def _name_similar(a: str, b: str) -> bool:
    """名称比对：去空白后任一为另一个的子串，或字符重叠率 ≥0.7。"""
    if not a or not b:
        return True
    a2 = "".join(a.split())
    b2 = "".join(b.split())
    if a2 in b2 or b2 in a2:
        return True
    if not a2 or not b2:
        return True
    overlap = len(set(a2) & set(b2))
    return overlap / max(len(set(a2)), len(set(b2))) >= 0.7


def _issue(description: str, files: list[str], rule_id: str,
           risk: RiskLevel = RiskLevel.HIGH,
           suggestion: str = "", category: IssueCategory = IssueCategory.CONSISTENCY) -> Issue:
    return Issue(
        description=description,
        location=Location(file_name=" + ".join(f for f in files if f)),
        category=category,
        risk_level=risk,
        suggestion=suggestion,
        rule_id=rule_id,
        source="crosscheck",
    )


def compare_chain(fields: ChainFields) -> List[Issue]:
    issues: List[Issue] = []
    t, b, e, c = fields.tender, fields.bid, fields.eval, fields.contract

    # 1. 项目名称一致性（招标 vs 投标 vs 评标 vs 合同）
    names = [(t.project_name if t else None, fields.tender_file),
             (b.project_name if b else None, fields.bid_file),
             (e.project_name if e else None, fields.eval_file),
             (c.project_name if c else None, fields.contract_file)]
    names_present = [(n, f) for n, f in names if n]
    if len(names_present) >= 2:
        base_name, base_file = names_present[0]
        for n, f in names_present[1:]:
            if not _name_similar(base_name, n):
                issues.append(_issue(
                    f"项目名称跨文件不一致：「{base_name}」（{base_file}） vs 「{n}」（{f}）。",
                    [base_file, f], "chain.project_name",
                    suggestion="核对各环节文件中的项目名称是否指向同一采购项目。",
                ))
                break

    # 2. 投标价 ≤ 招标预算（政府采购法实施条例：超控制价应作废）
    if t and b and t.budget is not None and b.bid_price is not None:
        if b.bid_price > t.budget + _AMOUNT_TOL:
            issues.append(_issue(
                f"投标报价 {b.bid_price} 元 超出招标预算/最高限价 {t.budget} 元。",
                [fields.tender_file, fields.bid_file], "chain.price_over_budget",
                category=IssueCategory.COMPLIANCE,
                suggestion="超过最高限价的投标应按规作废标处理，核实评审与中标决策。",
            ))

    # 3. 评标中标人 == 投标人（同一供应商，名称应能对应）
    if e and b and e.winner_name and b.bidder_name:
        if not _name_similar(e.winner_name, b.bidder_name):
            issues.append(_issue(
                f"评标中标人「{e.winner_name}」与投标人「{b.bidder_name}」名称不一致。",
                [fields.eval_file, fields.bid_file], "chain.winner_vs_bidder",
                suggestion="核对评标报告中的中标人与投标文件投标人是否一致。",
            ))

    # 4. 合同乙方 == 评标中标人（关键链路：评标 → 合同）
    if e and c and e.winner_name and c.party_b:
        if not _name_similar(e.winner_name, c.party_b):
            issues.append(_issue(
                f"合同乙方「{c.party_b}」与评标中标人「{e.winner_name}」不一致。",
                [fields.contract_file, fields.eval_file], "chain.contract_party_vs_winner",
                suggestion="合同应与评标确定的中标人签订，核实是否存在转包/变更。",
            ))

    # 5. 合同金额一致性：合同金额应与投标报价或评标中标价一致
    if c and c.amount is not None:
        # 优先比评标中标价（若有），否则比投标报价
        reference = None
        ref_file = ""
        ref_label = ""
        if e and e.winner_price is not None:
            reference, ref_file, ref_label = e.winner_price, fields.eval_file, "评标中标价"
        elif b and b.bid_price is not None:
            reference, ref_file, ref_label = b.bid_price, fields.bid_file, "投标报价"
        if reference is not None and not _amount_close(c.amount, reference):
            issues.append(_issue(
                f"合同金额 {c.amount} 元 与{ref_label} {reference} 元 不一致（差额 "
                f"{round(c.amount - reference, 2)} 元）。",
                [fields.contract_file, ref_file], "chain.contract_amount_vs_bid",
                category=IssueCategory.CONSISTENCY,
                suggestion="合同金额应与中标价/投标报价一致，差额需有书面变更依据。",
            ))

    # 6. 合同金额不得超出招标预算
    if t and c and t.budget is not None and c.amount is not None:
        if c.amount > t.budget + _AMOUNT_TOL:
            issues.append(_issue(
                f"合同金额 {c.amount} 元 超出招标预算 {t.budget} 元。",
                [fields.tender_file, fields.contract_file], "chain.contract_over_budget",
                category=IssueCategory.COMPLIANCE,
                suggestion="超预算签订合同应有书面追加预算批复，核实审批留痕。",
            ))

    # 7. 评委人数：政府采购法实施条例第 44 条 ≥ 5 且为单数
    if e and e.committee_size is not None:
        if e.committee_size < 5 or e.committee_size % 2 == 0:
            issues.append(_issue(
                f"评标委员会成员人数为 {e.committee_size}，不符合「5 人以上单数」规定。",
                [fields.eval_file], "chain.committee_size",
                category=IssueCategory.COMPLIANCE,
                suggestion="按《政府采购法实施条例》第四十四条调整评标委员会组成。",
            ))

    # 8. 链路完整性提示：缺失环节
    missing = []
    if t is None: missing.append("招标文件")
    if b is None: missing.append("投标文件")
    if e is None: missing.append("评标报告")
    if c is None: missing.append("合同")
    if missing:
        issues.append(_issue(
            f"招采链不完整，缺失：{'、'.join(missing)}。部分跨文件比对未执行。",
            [], "chain.completeness",
            risk=RiskLevel.LOW, category=IssueCategory.OTHER,
            suggestion="补齐缺失环节文件后重新运行联动校验。",
        ))

    return issues
