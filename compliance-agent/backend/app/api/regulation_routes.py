"""法规库 API（v3 §3.1）。

支持：上传文件 / 查看列表 / 查看详情 / 下载原始文件 / 删除。
写权限：仅 super_admin；读权限：所有登录用户。
"""
from __future__ import annotations

import json
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.schemas import RegulationListResponse, RegulationOut
from app.core.auth import get_current_user, require_admin
from app.models import Regulation, User, get_db
from app.parsers.dispatcher import UnsupportedFormatError
from app.services import regulation_service
from app.services.regulation_service import DOC_TYPES, REGIONS

regulations_router = APIRouter(prefix="/api/regulations", tags=["knowledge:regulations"])


@regulations_router.get("", response_model=RegulationListResponse)
def list_regulations(
    doc_type: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(Regulation).order_by(Regulation.id.desc())
    if doc_type:
        q = q.filter(Regulation.doc_type == doc_type)
    if region:
        q = q.filter(Regulation.region == region)
    if search:
        like = f"%{search}%"
        q = q.filter(
            (Regulation.title.ilike(like)) |
            (Regulation.file_name.ilike(like)) |
            (Regulation.issuer.ilike(like)) |
            (Regulation.doc_number.ilike(like))
        )
    items = q.all()
    return RegulationListResponse(
        regulations=[RegulationOut.model_validate(r) for r in items],
        total=len(items),
        doc_types=DOC_TYPES,
        regions=REGIONS,
    )


@regulations_router.post("", response_model=RegulationOut)
async def upload_regulation(
    file: UploadFile = File(...),
    title: str = Form(...),
    doc_type: str = Form("其它"),
    region: str = Form("国家"),
    issuer: str = Form(""),
    doc_number: str = Form(""),
    effective_date: str = Form(""),
    description: str = Form(""),
    tags: str = Form("[]"),  # JSON 字符串
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """上传法规文件 + 自动解析 + 入向量库。"""
    if not title.strip():
        raise HTTPException(400, "标题不能为空")
    try:
        tag_list = json.loads(tags) if tags else []
        if not isinstance(tag_list, list):
            tag_list = []
    except json.JSONDecodeError:
        tag_list = []
    try:
        content = await file.read()
        reg = regulation_service.ingest_regulation(
            db,
            file_name=file.filename or "untitled",
            content=content,
            title=title.strip(),
            doc_type=doc_type,
            region=region,
            issuer=issuer,
            doc_number=doc_number,
            effective_date=effective_date,
            description=description,
            tags=tag_list,
            user=admin,
        )
    except UnsupportedFormatError as exc:
        raise HTTPException(400, str(exc))
    return reg


@regulations_router.get("/{reg_id}", response_model=RegulationOut)
def get_regulation(
    reg_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    reg = db.get(Regulation, reg_id)
    if not reg:
        raise HTTPException(404, "法规不存在")
    return reg


@regulations_router.get("/{reg_id}/download")
def download_regulation(
    reg_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    reg = regulation_service.get_regulation_file(db, reg_id)
    return FileResponse(
        path=reg.storage_path,
        filename=reg.file_name,
        media_type="application/octet-stream",
    )


@regulations_router.delete("/{reg_id}")
def delete_regulation(
    reg_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    regulation_service.delete_regulation(db, reg_id, admin)
    return {"status": "ok"}
