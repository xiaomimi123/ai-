"""招采链联动校验服务：执行联动校验并持久化到台账。"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from typing import List

from sqlalchemy.orm import Session

from app.core.domain import Issue
from app.crosscheck import ProcurementChain, run_procurement_chain
from app.models.entities import ChainCheckTask, IssueRecord


def run_chain_check(db: Session, chain: ProcurementChain) -> ChainCheckTask:
    task = ChainCheckTask(
        chain_type="procurement",
        tender_doc_id=chain.tender_doc_id,
        bid_doc_id=chain.bid_doc_id,
        eval_doc_id=chain.eval_doc_id,
        contract_doc_id=chain.contract_doc_id,
        status="running",
    )
    db.add(task)
    db.flush()

    try:
        fields, issues = run_procurement_chain(db, chain)

        # 持久化抽取结果（便于报告/审计回看）
        task.extracted_fields = json.dumps({
            "tender": asdict(fields.tender) if fields.tender else None,
            "bid": asdict(fields.bid) if fields.bid else None,
            "eval": asdict(fields.eval) if fields.eval else None,
            "contract": asdict(fields.contract) if fields.contract else None,
        }, ensure_ascii=False)

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

        task.summary = _summarize(issues)
        task.status = "done"
    except Exception as exc:
        task.status = "failed"
        task.summary = f"联动校验失败：{exc}"

    db.commit()
    db.refresh(task)
    return task


def _summarize(issues: List[Issue]) -> str:
    if not issues:
        return "招采链跨文件比对未发现不一致。"
    by_risk = Counter(i.risk_level.value for i in issues)
    parts = [f"共 {len(issues)} 条跨文件疑点"]
    for level in ("高", "中", "低"):
        if by_risk.get(level):
            parts.append(f"{level}风险 {by_risk[level]}")
    return "；".join(parts) + "。"
