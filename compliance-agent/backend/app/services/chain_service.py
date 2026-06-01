"""跨链联动校验服务：执行联动校验并持久化到台账。

支持三种链：procurement / finance / report。
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, is_dataclass
from typing import List

from sqlalchemy.orm import Session

from app.core.domain import Issue
from app.crosscheck import (
    FinanceChain,
    ProcurementChain,
    ReportChain,
    run_finance_chain,
    run_procurement_chain,
    run_report_chain,
)
from app.models.entities import ChainCheckTask, IssueRecord


def _fields_to_json(fields) -> str:
    def to_dict(obj):
        if obj is None: return None
        if is_dataclass(obj): return asdict(obj)
        if isinstance(obj, list): return [to_dict(x) for x in obj]
        return obj
    return json.dumps(to_dict(fields), ensure_ascii=False, default=str)


def run_procurement(db: Session, chain: ProcurementChain) -> ChainCheckTask:
    task = ChainCheckTask(
        chain_type="procurement",
        tender_doc_id=chain.tender_doc_id,
        bid_doc_id=chain.bid_doc_id,
        eval_doc_id=chain.eval_doc_id,
        contract_doc_id=chain.contract_doc_id,
        status="running",
    )
    return _execute(db, task, lambda: run_procurement_chain(db, chain))


def run_finance(db: Session, chain: FinanceChain) -> ChainCheckTask:
    task = ChainCheckTask(
        chain_type="finance",
        finance_doc_id=chain.finance_doc_id,
        final_account_doc_id=chain.final_account_doc_id,
        asset_doc_id=chain.asset_doc_id,
        contract_doc_ids=json.dumps(chain.contract_doc_ids),
        status="running",
    )
    return _execute(db, task, lambda: run_finance_chain(db, chain))


def run_report(db: Session, chain: ReportChain) -> ChainCheckTask:
    task = ChainCheckTask(
        chain_type="report",
        ic_doc_id=chain.ic_doc_id,
        perf_doc_id=chain.perf_doc_id,
        project_doc_id=chain.project_doc_id,
        status="running",
    )
    return _execute(db, task, lambda: run_report_chain(db, chain))


# 兼容旧 API
def run_chain_check(db: Session, chain: ProcurementChain) -> ChainCheckTask:
    return run_procurement(db, chain)


def _execute(db: Session, task: ChainCheckTask, runner) -> ChainCheckTask:
    db.add(task)
    db.flush()
    try:
        fields, issues = runner()
        task.extracted_fields = _fields_to_json(fields)
        for issue in issues:
            d = issue.to_dict()
            db.add(IssueRecord(
                chain_task_id=task.id,
                description=d["description"],
                location=d["location"],
                legal_basis=d["legal_basis"],
                category=d["category"],
                risk_level=d["risk_level"],
                suggestion=d["suggestion"],
                rule_id=d["rule_id"],
                source=d["source"],
            ))
        task.summary = _summarize(issues, task.chain_type)
        task.status = "done"
    except Exception as exc:
        task.status = "failed"
        task.summary = f"联动校验失败：{exc}"
    db.commit()
    db.refresh(task)
    return task


_CHAIN_LABEL = {"procurement": "招采链", "finance": "财务链", "report": "报告链"}


def _summarize(issues: List[Issue], chain_type: str) -> str:
    label = _CHAIN_LABEL.get(chain_type, chain_type)
    if not issues:
        return f"{label}跨文件比对未发现不一致。"
    by_risk = Counter(i.risk_level.value for i in issues)
    parts = [f"{label}共 {len(issues)} 条跨文件疑点"]
    for level in ("高", "中", "低"):
        if by_risk.get(level):
            parts.append(f"{level}风险 {by_risk[level]}")
    return "；".join(parts) + "。"
