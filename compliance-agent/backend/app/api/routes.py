"""主业务路由。所有受保护接口均要求 Bearer token 认证。"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.schemas import (
    ChainCheckRequest,
    ChainCheckTaskOut,
    CheckRequest,
    CheckTaskOut,
    DocumentOut,
    FinanceChainRequest,
    ReportChainRequest,
    TemplateOut,
)
from app.core.auth import get_current_user, log_action
from app.core.config import settings
from app.core.permissions import allowed_categories, can_access_category, is_admin
from app.crosscheck import FinanceChain, ProcurementChain, ReportChain
from app.models import ChainCheckTask, CheckTask, Document, User, get_db
from app.parsers import SUPPORTED_EXTENSIONS
from app.rules import list_templates
from app.services.chain_service import (
    create_finance_pending,
    create_procurement_pending,
    create_report_pending,
    run_finance,
    run_procurement,
    run_report,
)
from app.services.check_service import create_pending_check, run_check
from app.services.report import build_report_docx
from app.tasks import (
    run_check_task,
    run_finance_chain_task,
    run_procurement_chain_task,
    run_report_chain_task,
)

router = APIRouter(prefix="/api")


# ─── 公开接口（无需登录）──────────────────────────────
@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "llm": settings.llm_provider,
        "embedder": settings.embedder,
        "vector_store": settings.vector_store,
    }


@router.get("/templates", response_model=List[TemplateOut])
def get_templates() -> list:
    return list_templates()


# ─── 权限检查工具 ─────────────────────────────────────
def _ensure_doc_accessible(db: Session, doc_id: int, user: User) -> Document:
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, f"文档 {doc_id} 不存在")
    if not can_access_category(user.role, doc.category):
        raise HTTPException(403, f"无权访问分类「{doc.category}」的文档")
    return doc


# ─── 文档 ─────────────────────────────────────────────
@router.get("/documents", response_model=List[DocumentOut])
def list_documents(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list:
    """列出当前用户有权访问的文档。"""
    q = db.query(Document).order_by(Document.id.desc())
    if not is_admin(user.role):
        q = q.filter(Document.category.in_(allowed_categories(user.role)) | (Document.category == ""))
    return q.all()


@router.post("/documents", response_model=DocumentOut)
async def upload_document(
    file: UploadFile = File(...),
    category: str = Form(""),
    subcategory: str = Form(""),
    project_id: str = Form(""),
    year: str = Form(""),
    department: str = Form(""),
    batch: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Document:
    if not can_access_category(user.role, category):
        raise HTTPException(403, f"角色「{user.role}」无权上传「{category}」类文档")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"不支持的格式 {ext}，支持 {SUPPORTED_EXTENSIONS}")

    safe_name = f"{uuid.uuid4().hex}{ext}"
    dest = Path(settings.storage_dir) / safe_name
    dest.write_bytes(await file.read())

    doc = Document(
        file_name=file.filename or safe_name,
        storage_path=str(dest),
        category=category,
        subcategory=subcategory,
        project_id=project_id,
        year=year,
        department=department,
        batch=batch,
    )
    db.add(doc)
    db.flush()
    log_action(db, user, "document.upload", target_type="document", target_id=doc.id,
               detail=f"上传 {doc.file_name}（{doc.category or '未分类'}）")
    db.commit()
    db.refresh(doc)
    return doc


# ─── 单文件检查 ───────────────────────────────────────
@router.post("/checks", response_model=CheckTaskOut)
def create_check(
    req: CheckRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CheckTask:
    doc = _ensure_doc_accessible(db, req.document_id, user)
    try:
        task = run_check(db, doc, req.template_key)
    except KeyError as exc:
        raise HTTPException(400, str(exc))
    log_action(db, user, "check.run", target_type="check_task", target_id=task.id,
               detail=f"对文档 #{doc.id} 套用「{req.template_key}」模板")
    db.commit()
    return task


@router.post("/checks/async", response_model=CheckTaskOut)
def create_check_async(
    req: CheckRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CheckTask:
    """异步创建检查任务：立即返回 pending 任务，worker 后台执行。"""
    doc = _ensure_doc_accessible(db, req.document_id, user)
    try:
        task = create_pending_check(db, doc, req.template_key)
    except KeyError as exc:
        raise HTTPException(400, str(exc))
    log_action(db, user, "check.enqueue", target_type="check_task", target_id=task.id,
               detail=f"入队对文档 #{doc.id} 套用「{req.template_key}」模板")
    db.commit()
    # 入队（eager 模式同步执行；生产由 worker 消费）
    run_check_task.delay(task.id)
    db.refresh(task)
    return task


@router.get("/checks/{task_id}", response_model=CheckTaskOut)
def get_check(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CheckTask:
    task = db.get(CheckTask, task_id)
    if not task:
        raise HTTPException(404, "检查任务不存在")
    _ensure_doc_accessible(db, task.document_id, user)
    return task


@router.get("/checks/{task_id}/report")
def download_report(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = db.get(CheckTask, task_id)
    if not task:
        raise HTTPException(404, "检查任务不存在")
    _ensure_doc_accessible(db, task.document_id, user)
    data = build_report_docx(db, task)
    log_action(db, user, "report.download", target_type="check_task", target_id=task.id)
    db.commit()
    filename = f"check_report_{task_id}.docx"
    return StreamingResponse(
        iter([data]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ─── 联动校验 ─────────────────────────────────────────
def _validate_chain_docs(db: Session, user: User, doc_ids: list[Optional[int]]) -> None:
    for did in doc_ids:
        if did is None:
            continue
        _ensure_doc_accessible(db, did, user)


@router.post("/chain-checks", response_model=ChainCheckTaskOut)
def create_chain_check(
    req: ChainCheckRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChainCheckTask:
    if not any([req.tender_doc_id, req.bid_doc_id, req.eval_doc_id, req.contract_doc_id]):
        raise HTTPException(400, "至少提供一份招采文档")
    _validate_chain_docs(db, user, [req.tender_doc_id, req.bid_doc_id,
                                    req.eval_doc_id, req.contract_doc_id])
    task = run_procurement(db, ProcurementChain(
        tender_doc_id=req.tender_doc_id,
        bid_doc_id=req.bid_doc_id,
        eval_doc_id=req.eval_doc_id,
        contract_doc_id=req.contract_doc_id,
    ))
    log_action(db, user, "chain.procurement", target_type="chain_task", target_id=task.id)
    db.commit()
    return task


@router.post("/chain-checks/finance", response_model=ChainCheckTaskOut)
def create_finance_chain(
    req: FinanceChainRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChainCheckTask:
    if not any([req.finance_doc_id, req.final_account_doc_id, req.asset_doc_id, req.contract_doc_ids]):
        raise HTTPException(400, "至少提供一份财务链文档")
    _validate_chain_docs(db, user, [req.finance_doc_id, req.final_account_doc_id,
                                    req.asset_doc_id, *req.contract_doc_ids])
    task = run_finance(db, FinanceChain(
        finance_doc_id=req.finance_doc_id,
        final_account_doc_id=req.final_account_doc_id,
        asset_doc_id=req.asset_doc_id,
        contract_doc_ids=list(req.contract_doc_ids),
    ))
    log_action(db, user, "chain.finance", target_type="chain_task", target_id=task.id)
    db.commit()
    return task


@router.post("/chain-checks/report", response_model=ChainCheckTaskOut)
def create_report_chain(
    req: ReportChainRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChainCheckTask:
    if not any([req.ic_doc_id, req.perf_doc_id, req.project_doc_id]):
        raise HTTPException(400, "至少提供一份报告链文档")
    _validate_chain_docs(db, user, [req.ic_doc_id, req.perf_doc_id, req.project_doc_id])
    task = run_report(db, ReportChain(
        ic_doc_id=req.ic_doc_id,
        perf_doc_id=req.perf_doc_id,
        project_doc_id=req.project_doc_id,
    ))
    log_action(db, user, "chain.report", target_type="chain_task", target_id=task.id)
    db.commit()
    return task


# ─── 异步联动校验 ──────────────────────────────────────
@router.post("/chain-checks/async", response_model=ChainCheckTaskOut)
def create_procurement_chain_async(
    req: ChainCheckRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChainCheckTask:
    if not any([req.tender_doc_id, req.bid_doc_id, req.eval_doc_id, req.contract_doc_id]):
        raise HTTPException(400, "至少提供一份招采文档")
    _validate_chain_docs(db, user, [req.tender_doc_id, req.bid_doc_id,
                                    req.eval_doc_id, req.contract_doc_id])
    task = create_procurement_pending(db, ProcurementChain(
        tender_doc_id=req.tender_doc_id,
        bid_doc_id=req.bid_doc_id,
        eval_doc_id=req.eval_doc_id,
        contract_doc_id=req.contract_doc_id,
    ))
    log_action(db, user, "chain.procurement.enqueue",
               target_type="chain_task", target_id=task.id)
    db.commit()
    run_procurement_chain_task.delay(task.id)
    db.refresh(task)
    return task


@router.post("/chain-checks/finance/async", response_model=ChainCheckTaskOut)
def create_finance_chain_async(
    req: FinanceChainRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChainCheckTask:
    if not any([req.finance_doc_id, req.final_account_doc_id, req.asset_doc_id, req.contract_doc_ids]):
        raise HTTPException(400, "至少提供一份财务链文档")
    _validate_chain_docs(db, user, [req.finance_doc_id, req.final_account_doc_id,
                                    req.asset_doc_id, *req.contract_doc_ids])
    task = create_finance_pending(db, FinanceChain(
        finance_doc_id=req.finance_doc_id,
        final_account_doc_id=req.final_account_doc_id,
        asset_doc_id=req.asset_doc_id,
        contract_doc_ids=list(req.contract_doc_ids),
    ))
    log_action(db, user, "chain.finance.enqueue",
               target_type="chain_task", target_id=task.id)
    db.commit()
    run_finance_chain_task.delay(task.id)
    db.refresh(task)
    return task


@router.post("/chain-checks/report/async", response_model=ChainCheckTaskOut)
def create_report_chain_async(
    req: ReportChainRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChainCheckTask:
    if not any([req.ic_doc_id, req.perf_doc_id, req.project_doc_id]):
        raise HTTPException(400, "至少提供一份报告链文档")
    _validate_chain_docs(db, user, [req.ic_doc_id, req.perf_doc_id, req.project_doc_id])
    task = create_report_pending(db, ReportChain(
        ic_doc_id=req.ic_doc_id,
        perf_doc_id=req.perf_doc_id,
        project_doc_id=req.project_doc_id,
    ))
    log_action(db, user, "chain.report.enqueue",
               target_type="chain_task", target_id=task.id)
    db.commit()
    run_report_chain_task.delay(task.id)
    db.refresh(task)
    return task


@router.get("/chain-checks/{task_id}", response_model=ChainCheckTaskOut)
def get_chain_check(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChainCheckTask:
    task = db.get(ChainCheckTask, task_id)
    if not task:
        raise HTTPException(404, "联动校验任务不存在")
    # 管理员可看全部；其余角色：只要涉及的文档全部可见
    if not is_admin(user.role):
        doc_ids = [task.tender_doc_id, task.bid_doc_id, task.eval_doc_id,
                   task.contract_doc_id, task.finance_doc_id,
                   task.final_account_doc_id, task.asset_doc_id,
                   task.ic_doc_id, task.perf_doc_id, task.project_doc_id]
        for did in doc_ids:
            if did is None: continue
            doc = db.get(Document, did)
            if doc and not can_access_category(user.role, doc.category):
                raise HTTPException(403, "无权查看该联动校验任务")
    return task
