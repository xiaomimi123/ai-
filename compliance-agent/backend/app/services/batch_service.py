"""批次服务：批量上传 + 自动分类 + 自动批检 + 自动联动校验。

迎检场景：一次性上传一个项目全套资料（招标/投标/评标/合同/财务/决算/内控/绩效/...）
→ 自动识别每份文档分类 → 按分类映射到对应模板批量入队 →
凑齐链路时自动入队联动校验。
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.auth import log_action
from app.core.config import settings
from app.core.permissions import can_access_category
from app.crosscheck import FinanceChain, ProcurementChain, ReportChain
from app.models import Batch, Document, User
from app.parsers import parse, SUPPORTED_EXTENSIONS
from app.parsers.dispatcher import UnsupportedFormatError
from app.services.chain_service import (
    create_finance_pending,
    create_procurement_pending,
    create_report_pending,
)
from app.services.check_service import create_pending_check
from app.services.classifier import Classification, classify
from app.tasks import (
    run_check_task,
    run_finance_chain_task,
    run_procurement_chain_task,
    run_report_chain_task,
)


# 分类 → 默认模板 key（Phase 2 已注册）
_CATEGORY_TO_TEMPLATE: dict[str, str] = {
    "合同": "contract",
    "内部制度": "institution",
    "采购招标": "procurement",
    "内控报告": "internal_control",
    "财务报告": "finance_final",
    "决算报告": "finance_final",
    "国有资产报告": "asset",
    "绩效评价报告": "performance",
}


def create_batch(db: Session, *, name: str, project_id: str = "",
                 year: str = "", department: str = "",
                 description: str = "", user: User) -> Batch:
    batch = Batch(
        name=name, project_id=project_id, year=year,
        department=department, description=description,
        created_by=user.id if user else None,
    )
    db.add(batch); db.flush()
    log_action(db, user, "batch.create", target_type="batch", target_id=batch.id,
               detail=f"创建批次「{name}」")
    db.commit(); db.refresh(batch)
    return batch


def ingest_file(db: Session, batch: Batch, *, file_name: str,
                content: bytes, user: User) -> tuple[Document, Classification]:
    """单文件入库：写盘 + 自动分类 + 入队检查。返回 (Document, Classification)。"""
    ext = Path(file_name).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(
            f"不支持的格式 {ext}（支持 {', '.join(SUPPORTED_EXTENSIONS)}）"
        )

    safe = f"{uuid.uuid4().hex}{ext}"
    dest = Path(settings.storage_dir) / safe
    dest.write_bytes(content)

    # 自动分类（基于文件名 + 解析内容）
    parsed = None
    try:
        parsed = parse(str(dest))
    except Exception:
        parsed = None
    cls = classify(file_name, parsed)

    # 权限检查：分类必须是当前用户可访问的
    if not can_access_category(user.role, cls.category):
        # 自动分类落到无权分类 → 降级为「其他佐证资料」（通常对所有角色可见）
        cls = Classification(category="其他佐证资料", subcategory="",
                             confidence=cls.confidence,
                             method=cls.method + "+permission_downgrade")

    doc = Document(
        file_name=file_name,
        storage_path=str(dest),
        category=cls.category,
        subcategory=cls.subcategory,
        batch=batch.name,            # 兼容字符串字段
        batch_id=batch.id,
        project_id=batch.project_id,
        year=batch.year,
        department=batch.department,
    )
    db.add(doc); db.flush()

    # 自动入队单文件检查（若分类对应有模板）
    template = _CATEGORY_TO_TEMPLATE.get(cls.category)
    if template:
        task = create_pending_check(db, doc, template)
        log_action(db, user, "batch.enqueue_check", target_type="check_task",
                   target_id=task.id,
                   detail=f"批次 #{batch.id} 文档 #{doc.id} → 模板 {template}")
        db.commit()
        run_check_task.delay(task.id)
    else:
        db.commit()

    return doc, cls


def detect_and_enqueue_chains(db: Session, batch: Batch, user: User) -> dict:
    """检查批次内文档是否凑齐 3 条链中的任一条，凑齐则自动入队联动校验。

    返回触发的链路统计，例如 {"procurement": 1, "finance": 1}。
    """
    docs = list(batch.documents)
    triggered: dict[str, int] = {}

    # 招采链：合同 + 招采(招标/投标/评标)
    procurement_docs_by_sub = {"招标": None, "投标": None, "评标": None}
    contract_doc = None
    finance_doc = None
    final_account_doc = None
    asset_doc = None
    ic_doc = None
    perf_doc = None
    project_doc = None
    all_contract_ids: list[int] = []

    for d in docs:
        if d.category == "合同":
            contract_doc = contract_doc or d
            all_contract_ids.append(d.id)
        elif d.category == "采购招标":
            sub = d.subcategory or ""
            for k in procurement_docs_by_sub:
                if k in sub and procurement_docs_by_sub[k] is None:
                    procurement_docs_by_sub[k] = d
        elif d.category == "财务报告":
            finance_doc = finance_doc or d
        elif d.category == "决算报告":
            final_account_doc = final_account_doc or d
        elif d.category == "国有资产报告":
            asset_doc = asset_doc or d
        elif d.category == "内控报告":
            ic_doc = ic_doc or d
        elif d.category == "绩效评价报告":
            perf_doc = perf_doc or d
        elif d.category == "其他佐证资料":
            project_doc = project_doc or d

    # 招采链：至少包含 2 个环节才触发
    proc_present = [d for d in procurement_docs_by_sub.values() if d] + \
                   ([contract_doc] if contract_doc else [])
    if len(proc_present) >= 2:
        chain = ProcurementChain(
            tender_doc_id=getattr(procurement_docs_by_sub["招标"], "id", None),
            bid_doc_id=getattr(procurement_docs_by_sub["投标"], "id", None),
            eval_doc_id=getattr(procurement_docs_by_sub["评标"], "id", None),
            contract_doc_id=contract_doc.id if contract_doc else None,
        )
        task = create_procurement_pending(db, chain)
        log_action(db, user, "batch.enqueue_chain",
                   target_type="chain_task", target_id=task.id,
                   detail=f"批次 #{batch.id} 招采链")
        db.commit()
        run_procurement_chain_task.delay(task.id)
        triggered["procurement"] = task.id

    # 财务链：财务/决算/资产 至少 2 个
    fin_present = [x for x in (finance_doc, final_account_doc, asset_doc) if x]
    if len(fin_present) >= 2:
        chain = FinanceChain(
            finance_doc_id=finance_doc.id if finance_doc else None,
            final_account_doc_id=final_account_doc.id if final_account_doc else None,
            asset_doc_id=asset_doc.id if asset_doc else None,
            contract_doc_ids=all_contract_ids,
        )
        task = create_finance_pending(db, chain)
        log_action(db, user, "batch.enqueue_chain",
                   target_type="chain_task", target_id=task.id,
                   detail=f"批次 #{batch.id} 财务链")
        db.commit()
        run_finance_chain_task.delay(task.id)
        triggered["finance"] = task.id

    # 报告链：内控/绩效/项目资料 至少 2 个
    rep_present = [x for x in (ic_doc, perf_doc, project_doc) if x]
    if len(rep_present) >= 2:
        chain = ReportChain(
            ic_doc_id=ic_doc.id if ic_doc else None,
            perf_doc_id=perf_doc.id if perf_doc else None,
            project_doc_id=project_doc.id if project_doc else None,
        )
        task = create_report_pending(db, chain)
        log_action(db, user, "batch.enqueue_chain",
                   target_type="chain_task", target_id=task.id,
                   detail=f"批次 #{batch.id} 报告链")
        db.commit()
        run_report_chain_task.delay(task.id)
        triggered["report"] = task.id

    return triggered


def summarize_batch(db: Session, batch: Batch) -> dict:
    """汇总批次状态。"""
    from app.models import ChainCheckTask, CheckTask, IssueRecord

    docs = list(batch.documents)
    by_category: dict[str, int] = {}
    for d in docs:
        by_category[d.category or "未分类"] = by_category.get(d.category or "未分类", 0) + 1

    check_tasks = db.query(CheckTask).filter(
        CheckTask.document_id.in_([d.id for d in docs] or [-1])
    ).all()
    chain_tasks = db.query(ChainCheckTask).filter(
        # 简化：批次内文档 ID 命中任一字段即认为属本批次
        (ChainCheckTask.tender_doc_id.in_([d.id for d in docs] or [-1])) |
        (ChainCheckTask.bid_doc_id.in_([d.id for d in docs] or [-1])) |
        (ChainCheckTask.eval_doc_id.in_([d.id for d in docs] or [-1])) |
        (ChainCheckTask.contract_doc_id.in_([d.id for d in docs] or [-1])) |
        (ChainCheckTask.finance_doc_id.in_([d.id for d in docs] or [-1])) |
        (ChainCheckTask.final_account_doc_id.in_([d.id for d in docs] or [-1])) |
        (ChainCheckTask.asset_doc_id.in_([d.id for d in docs] or [-1])) |
        (ChainCheckTask.ic_doc_id.in_([d.id for d in docs] or [-1])) |
        (ChainCheckTask.perf_doc_id.in_([d.id for d in docs] or [-1])) |
        (ChainCheckTask.project_doc_id.in_([d.id for d in docs] or [-1]))
    ).all() if docs else []

    issue_count = 0
    risk_buckets = {"高": 0, "中": 0, "低": 0}
    if check_tasks:
        rows = db.query(IssueRecord).filter(
            IssueRecord.task_id.in_([t.id for t in check_tasks])
        ).all()
        chain_rows = db.query(IssueRecord).filter(
            IssueRecord.chain_task_id.in_([t.id for t in chain_tasks])
        ).all() if chain_tasks else []
        for r in rows + chain_rows:
            issue_count += 1
            risk_buckets[r.risk_level] = risk_buckets.get(r.risk_level, 0) + 1

    return {
        "documents_total": len(docs),
        "documents_by_category": by_category,
        "check_tasks": [{"id": t.id, "document_id": t.document_id,
                         "template_key": t.template_key, "status": t.status,
                         "summary": t.summary} for t in check_tasks],
        "chain_tasks": [{"id": t.id, "chain_type": t.chain_type,
                         "status": t.status, "summary": t.summary}
                        for t in chain_tasks],
        "issues_total": issue_count,
        "issues_by_risk": risk_buckets,
    }
