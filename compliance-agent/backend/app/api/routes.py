"""Phase 1 API 路由。"""
from __future__ import annotations

import os
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
from app.core.config import settings
from app.crosscheck import FinanceChain, ProcurementChain, ReportChain
from app.models import ChainCheckTask, CheckTask, Document, get_db
from app.parsers import SUPPORTED_EXTENSIONS
from app.parsers.dispatcher import UnsupportedFormatError, parse
from app.rules import list_templates
from app.services.chain_service import run_finance, run_procurement, run_report
from app.services.check_service import run_check
from app.services.report import build_report_docx

router = APIRouter(prefix="/api")


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
) -> Document:
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
    db.commit()
    db.refresh(doc)
    return doc


@router.post("/checks", response_model=CheckTaskOut)
def create_check(req: CheckRequest, db: Session = Depends(get_db)) -> CheckTask:
    doc = db.get(Document, req.document_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    try:
        task = run_check(db, doc, req.template_key)
    except KeyError as exc:
        raise HTTPException(400, str(exc))
    return task


@router.get("/checks/{task_id}", response_model=CheckTaskOut)
def get_check(task_id: int, db: Session = Depends(get_db)) -> CheckTask:
    task = db.get(CheckTask, task_id)
    if not task:
        raise HTTPException(404, "检查任务不存在")
    return task


def _check_doc_exists(db, doc_id):
    if doc_id is not None and db.get(Document, doc_id) is None:
        raise HTTPException(404, f"文档 {doc_id} 不存在")


@router.post("/chain-checks", response_model=ChainCheckTaskOut)
def create_chain_check(req: ChainCheckRequest, db: Session = Depends(get_db)) -> ChainCheckTask:
    """招采链：保留 /api/chain-checks 端点向后兼容。"""
    if not any([req.tender_doc_id, req.bid_doc_id, req.eval_doc_id, req.contract_doc_id]):
        raise HTTPException(400, "至少提供一份招采文档")
    for doc_id in (req.tender_doc_id, req.bid_doc_id, req.eval_doc_id, req.contract_doc_id):
        _check_doc_exists(db, doc_id)
    return run_procurement(db, ProcurementChain(
        tender_doc_id=req.tender_doc_id,
        bid_doc_id=req.bid_doc_id,
        eval_doc_id=req.eval_doc_id,
        contract_doc_id=req.contract_doc_id,
    ))


@router.post("/chain-checks/finance", response_model=ChainCheckTaskOut)
def create_finance_chain(req: FinanceChainRequest, db: Session = Depends(get_db)) -> ChainCheckTask:
    if not any([req.finance_doc_id, req.final_account_doc_id, req.asset_doc_id, req.contract_doc_ids]):
        raise HTTPException(400, "至少提供一份财务链文档")
    for doc_id in [req.finance_doc_id, req.final_account_doc_id, req.asset_doc_id, *req.contract_doc_ids]:
        _check_doc_exists(db, doc_id)
    return run_finance(db, FinanceChain(
        finance_doc_id=req.finance_doc_id,
        final_account_doc_id=req.final_account_doc_id,
        asset_doc_id=req.asset_doc_id,
        contract_doc_ids=list(req.contract_doc_ids),
    ))


@router.post("/chain-checks/report", response_model=ChainCheckTaskOut)
def create_report_chain(req: ReportChainRequest, db: Session = Depends(get_db)) -> ChainCheckTask:
    if not any([req.ic_doc_id, req.perf_doc_id, req.project_doc_id]):
        raise HTTPException(400, "至少提供一份报告链文档")
    for doc_id in (req.ic_doc_id, req.perf_doc_id, req.project_doc_id):
        _check_doc_exists(db, doc_id)
    return run_report(db, ReportChain(
        ic_doc_id=req.ic_doc_id,
        perf_doc_id=req.perf_doc_id,
        project_doc_id=req.project_doc_id,
    ))


@router.get("/chain-checks/{task_id}", response_model=ChainCheckTaskOut)
def get_chain_check(task_id: int, db: Session = Depends(get_db)) -> ChainCheckTask:
    task = db.get(ChainCheckTask, task_id)
    if not task:
        raise HTTPException(404, "联动校验任务不存在")
    return task


@router.get("/checks/{task_id}/report")
def download_report(task_id: int, db: Session = Depends(get_db)):
    task = db.get(CheckTask, task_id)
    if not task:
        raise HTTPException(404, "检查任务不存在")
    data = build_report_docx(db, task)
    filename = f"check_report_{task_id}.docx"
    return StreamingResponse(
        iter([data]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
