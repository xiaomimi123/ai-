"""批次管理 API（Phase 4 最后一块）。"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.schemas import (
    BatchCreateRequest,
    BatchDetailResponse,
    BatchIngestResponse,
    BatchIngestResultItem,
    BatchOut,
)
from app.core.auth import get_current_user
from app.models import Batch, CheckTask, Document, User, get_db
from app.parsers.dispatcher import UnsupportedFormatError
from app.services import batch_service

batch_router = APIRouter(prefix="/api/batches", tags=["batch"])


@batch_router.post("", response_model=BatchOut)
def create_batch(req: BatchCreateRequest,
                 db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    batch = batch_service.create_batch(
        db, name=req.name, project_id=req.project_id, year=req.year,
        department=req.department, description=req.description, user=user,
    )
    return batch


@batch_router.get("", response_model=List[BatchOut])
def list_batches(db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    return db.query(Batch).order_by(Batch.id.desc()).all()


@batch_router.post("/{batch_id}/upload", response_model=BatchIngestResponse)
async def batch_upload(
    batch_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """批量上传多个文件到批次：自动分类 → 入队检查 → 检测联动链。"""
    batch = db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(404, "批次不存在")
    if not files:
        raise HTTPException(400, "至少上传一个文件")

    items: List[BatchIngestResultItem] = []
    for upload in files:
        item = BatchIngestResultItem(file_name=upload.filename or "")
        try:
            content = await upload.read()
            doc, cls = batch_service.ingest_file(
                db, batch, file_name=upload.filename or "", content=content, user=user,
            )
            item.document_id = doc.id
            item.category = cls.category
            item.subcategory = cls.subcategory
            item.confidence = cls.confidence
            item.method = cls.method
            # 找到该文档刚创建的 check task（若有）
            latest_check = (db.query(CheckTask)
                            .filter_by(document_id=doc.id)
                            .order_by(CheckTask.id.desc())
                            .first())
            if latest_check:
                item.check_task_id = latest_check.id
        except UnsupportedFormatError as exc:
            item.error = str(exc)
        except Exception as exc:
            item.error = f"处理失败：{exc}"
        items.append(item)

    # 链路检测（同步触发入队，worker 异步执行）
    triggered = batch_service.detect_and_enqueue_chains(db, batch, user)

    return BatchIngestResponse(
        batch=BatchOut.model_validate(batch),
        items=items,
        triggered_chains=triggered,
    )


@batch_router.get("/{batch_id}", response_model=BatchDetailResponse)
def batch_detail(batch_id: int,
                 db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    batch = db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(404, "批次不存在")
    return BatchDetailResponse(
        batch=BatchOut.model_validate(batch),
        summary=batch_service.summarize_batch(db, batch),
    )


@batch_router.post("/{batch_id}/retrigger", response_model=dict)
def retrigger_chains(batch_id: int,
                     db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """手动重新触发联动校验（批次内文档发生变化时使用）。"""
    batch = db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(404, "批次不存在")
    triggered = batch_service.detect_and_enqueue_chains(db, batch, user)
    return {"triggered": triggered}
