"""检查编排服务。

两阶段设计（Phase 4 异步化）：
- create_pending_check：DB 写入 status=pending 的任务，返回任务对象
- execute_pending_check：Worker 调用，实际执行解析+规则引擎，写台账
- run_check：保留同步入口，先创建 pending 再立刻执行，向后兼容
"""
from __future__ import annotations

from collections import Counter
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.domain import Issue
from app.models.entities import CheckTask, Document, IssueRecord
from app.parsers import parse
from app.rules import RuleEngine, get_template
from app.rules.soft_context import LLMRagContext


def create_pending_check(db: Session, document: Document, template_key: str) -> CheckTask:
    """同步：创建一个 pending 状态的检查任务并提交。"""
    # 校验模板存在（早 fail）
    get_template(template_key)

    task = CheckTask(
        document_id=document.id,
        template_key=template_key,
        status="pending",
        summary="排队中…",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def execute_pending_check(db: Session, task: CheckTask, document: Optional[Document]) -> CheckTask:
    """Worker 调用：执行已 pending 的任务。"""
    if task is None:
        return task
    if document is None:
        task.status = "failed"
        task.summary = "检查失败：文档不存在"
        db.commit()
        return task

    template = get_template(task.template_key)
    task.status = "running"
    task.summary = "执行中…"
    db.commit()

    try:
        parsed = parse(document.storage_path)
        parsed.metadata.setdefault("file_name", document.file_name)
        if document.subcategory:
            parsed.metadata.setdefault("subcategory", document.subcategory)

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


def run_check(db: Session, document: Document, template_key: str) -> CheckTask:
    """同步路径：创建 pending → 立即执行。

    保留以向后兼容（部分测试 / 旧调用方仍用这条路径）。
    """
    task = create_pending_check(db, document, template_key)
    return execute_pending_check(db, task, document)


def _summarize(issues: List[Issue]) -> str:
    if not issues:
        return "未发现疑点（刚性规则通过；柔性规则未报告问题）。"
    by_risk = Counter(i.risk_level.value for i in issues)
    parts = [f"共 {len(issues)} 条疑点"]
    for level in ("高", "中", "低"):
        if by_risk.get(level):
            parts.append(f"{level}风险 {by_risk[level]}")
    return "；".join(parts) + "。"
