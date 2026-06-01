"""法规库服务：文件上传 / 解析 / 索引 / 删除。

文件上传后：
- 存到对象存储目录
- 用 parsers 解析全文
- 按条款 chunk → Qdrant（v3 §3.3 黄金数据）
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.auth import log_action
from app.core.config import settings
from app.models import Regulation, User
from app.parsers import parse, SUPPORTED_EXTENSIONS
from app.parsers.dispatcher import UnsupportedFormatError
from app.rag import chunk_regulation, get_retriever


# 法规分类（v3 §3.1）
DOC_TYPES = [
    "上位法",        # 国家法律
    "评价办法",      # 内控评价办法
    "编报指南",      # 财政部编报指南附件 1/2
    "地方法规",      # 省/市级地方规范性文件
    "部门规章",      # 部门发布的管理办法
    "高频问题",      # 历年审计问题清单
    "其它",
]

REGIONS = ["国家", "省", "市", "区县", "部门", "其它"]


def ingest_regulation(
    db: Session, *,
    file_name: str, content: bytes,
    title: str,
    doc_type: str,
    region: str = "国家",
    issuer: str = "",
    doc_number: str = "",
    effective_date: str = "",
    description: str = "",
    tags: Optional[List[str]] = None,
    user: Optional[User] = None,
) -> Regulation:
    """上传一份法规文件 → 解析 → 入库 → 入向量库。"""
    if doc_type not in DOC_TYPES:
        raise HTTPException(400, f"无效文档类型: {doc_type}")

    ext = Path(file_name).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(
            f"不支持的格式 {ext}（支持 {', '.join(SUPPORTED_EXTENSIONS)}）"
        )

    # 写文件
    safe = f"reg_{uuid.uuid4().hex}{ext}"
    dest = Path(settings.storage_dir) / safe
    dest.write_bytes(content)
    file_size = dest.stat().st_size

    # 解析（已自动抽 key_elements，这里只关注全文）
    parsed = parse(str(dest))
    full_text = parsed.text or ""

    # 分块 + 入向量库
    chunks_count = 0
    indexed = False
    try:
        chunks = chunk_regulation(
            full_text,
            law_name=title or None,
            category=doc_type,
            source=file_name,
        )
        retriever = get_retriever()
        chunks_count = retriever.index_chunks(chunks)
        indexed = True
    except Exception as exc:
        # 入向量库失败不阻塞入库（可后续重试 reindex）
        print(f"[regulation] 向量库索引失败: {exc}")
        indexed = False

    # 写 DB
    reg = Regulation(
        title=title,
        doc_type=doc_type,
        region=region,
        issuer=issuer,
        doc_number=doc_number,
        effective_date=effective_date,
        description=description,
        tags=json.dumps(tags or [], ensure_ascii=False),
        file_name=file_name,
        storage_path=str(dest),
        file_size=file_size,
        file_type=ext.lstrip("."),
        parsed_text=full_text[:200000],
        chunks_count=chunks_count,
        indexed=indexed,
        uploaded_by=user.id if user else None,
    )
    db.add(reg)
    db.flush()
    log_action(
        db, user, "regulation.upload",
        target_type="regulation", target_id=reg.id,
        detail=f"上传法规《{title}》({doc_type}, {region}, {chunks_count} 条款块)",
    )
    db.commit()
    db.refresh(reg)
    return reg


def delete_regulation(db: Session, reg_id: int, user: Optional[User]) -> None:
    reg = db.get(Regulation, reg_id)
    if not reg:
        raise HTTPException(404, "法规不存在")
    # 清理文件
    try:
        if reg.storage_path and os.path.exists(reg.storage_path):
            os.remove(reg.storage_path)
    except Exception as exc:
        print(f"[regulation] 清理文件失败: {exc}")
    # 注意：向量库内的 chunk 暂不清理（向量库无 cascade，删除文件后引用失效，
    # RAG 仍可工作，只是会出现「来源法规已删除」的引用。后续可加 reindex 清理任务）

    title = reg.title
    db.delete(reg)
    log_action(
        db, user, "regulation.delete",
        target_type="regulation", target_id=reg_id,
        detail=f"删除法规《{title}》",
    )
    db.commit()


def get_regulation_file(db: Session, reg_id: int) -> Regulation:
    reg = db.get(Regulation, reg_id)
    if not reg:
        raise HTTPException(404, "法规不存在")
    if not reg.storage_path or not os.path.exists(reg.storage_path):
        raise HTTPException(410, "原始文件已丢失")
    return reg
