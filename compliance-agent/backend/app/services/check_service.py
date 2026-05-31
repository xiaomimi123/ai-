"""检查编排服务：解析 → 规则引擎 → 写入问题台账（Phase 1 同步执行）。"""
from __future__ import annotations

from collections import Counter
from typing import List

from sqlalchemy.orm import Session

from app.core.domain import Issue
from app.models.entities import CheckTask, Document, IssueRecord
from app.parsers import parse
from app.rules import RuleEngine, get_template
from app.rules.soft_context import LLMRagContext


def run_check(db: Session, document: Document, template_key: str) -> CheckTask:
    template = get_template(template_key)

    task = CheckTask(document_id=document.id, template_key=template_key, status="running")
    db.add(task)
    db.flush()

    try:
        parsed = parse(document.storage_path)
        parsed.metadata.setdefault("file_name", document.file_name)
        # 子类供招采等模板按子类（招标/投标/评标）分流规则
        if document.subcategory:
            parsed.metadata.setdefault("subcategory", document.subcategory)

        # 柔性规则上下文：离线自动降级，不会因 LLM/向量库缺失而报错
        soft_ctx = LLMRagContext()
        engine = RuleEngine(soft_ctx=soft_ctx)
        issues: List[Issue] = engine.run(template, parsed)

        for issue in issues:
            d = issue.to_dict()
            db.add(IssueRecord(
                task_id=task.id,
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
        task.summary = f"检查失败：{exc}"

    db.commit()
    db.refresh(task)
    return task


def _summarize(issues: List[Issue]) -> str:
    if not issues:
        return "未发现疑点（刚性规则通过；柔性规则未报告问题）。"
    by_risk = Counter(i.risk_level.value for i in issues)
    parts = [f"共 {len(issues)} 条疑点"]
    for level in ("高", "中", "低"):
        if by_risk.get(level):
            parts.append(f"{level}风险 {by_risk[level]}")
    return "；".join(parts) + "。"
