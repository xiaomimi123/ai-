"""业务实体：文档、检查任务、问题台账条目。"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_name: Mapped[str] = mapped_column(String(512))
    storage_path: Mapped[str] = mapped_column(String(1024))
    # §3.1 metadata
    category: Mapped[str] = mapped_column(String(64), default="")
    subcategory: Mapped[str] = mapped_column(String(64), default="")
    project_id: Mapped[str] = mapped_column(String(64), default="")
    year: Mapped[str] = mapped_column(String(16), default="")
    department: Mapped[str] = mapped_column(String(128), default="")
    batch: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    checks: Mapped[List["CheckTask"]] = relationship(back_populates="document")


class CheckTask(Base):
    __tablename__ = "check_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    template_key: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="done")  # pending|running|done|failed
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="checks")
    issues: Mapped[List["IssueRecord"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class ChainCheckTask(Base):
    """跨文件联动校验任务（§3.5）。引用多份文档，产出跨文件问题。"""
    __tablename__ = "chain_check_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chain_type: Mapped[str] = mapped_column(String(32), default="procurement")  # procurement|finance|report
    tender_doc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bid_doc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    eval_doc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    contract_doc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="done")
    summary: Mapped[str] = mapped_column(Text, default="")
    extracted_fields: Mapped[str] = mapped_column(Text, default="")  # JSON 序列化
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    issues: Mapped[List["IssueRecord"]] = relationship(
        back_populates="chain_task", cascade="all, delete-orphan"
    )


class IssueRecord(Base):
    """§3.6 问题条目统一结构的持久化。"""
    __tablename__ = "issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[Optional[int]] = mapped_column(ForeignKey("check_tasks.id"), nullable=True)
    chain_task_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("chain_check_tasks.id"), nullable=True
    )
    description: Mapped[str] = mapped_column(Text)
    location: Mapped[str] = mapped_column(String(512), default="")
    legal_basis: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(32), default="")
    risk_level: Mapped[str] = mapped_column(String(8), default="")
    suggestion: Mapped[str] = mapped_column(Text, default="")
    rule_id: Mapped[str] = mapped_column(String(64), default="")
    source: Mapped[str] = mapped_column(String(16), default="rigid")
    # 整改流转：open|fixing|resolved
    handle_status: Mapped[str] = mapped_column(String(16), default="open")

    task: Mapped[Optional["CheckTask"]] = relationship(back_populates="issues")
    chain_task: Mapped[Optional["ChainCheckTask"]] = relationship(back_populates="issues")
