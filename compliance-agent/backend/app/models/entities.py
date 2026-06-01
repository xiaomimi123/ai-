"""业务实体：用户、文档、检查任务、问题台账、审计日志（§3.7）。"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class User(Base):
    """用户 + 角色（§3.7）。"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(32))  # admin | procurement | finance | internal_control
    full_name: Mapped[str] = mapped_column(String(64), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuthToken(Base):
    """用户登录令牌（简单 token，不引入 JWT 依赖）。"""
    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuditLog(Base):
    """操作审计日志（§3.7「全程留痕可溯源」）。"""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    username: Mapped[str] = mapped_column(String(64), default="")  # 冗余存名，便于事后回看
    action: Mapped[str] = mapped_column(String(64))                # 如 document.upload / check.run
    target_type: Mapped[str] = mapped_column(String(32), default="")
    target_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


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
    # 招采链 4 个文档
    tender_doc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bid_doc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    eval_doc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    contract_doc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # 财务链 3 个文档 + 多份合同（JSON 数组）
    finance_doc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    final_account_doc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    asset_doc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    contract_doc_ids: Mapped[str] = mapped_column(Text, default="")  # JSON 字符串
    # 报告链 3 个文档
    ic_doc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    perf_doc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    project_doc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

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
    # 整改流转（§3.7）：open(新建) -> assigned(已下发) -> fixing(整改中)
    #                  -> reviewing(待复核) -> resolved(已销号) | rejected(打回)
    handle_status: Mapped[str] = mapped_column(String(16), default="open")
    assignee_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    reviewer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    fix_note: Mapped[str] = mapped_column(Text, default="")        # 整改说明（被复核人填）
    review_note: Mapped[str] = mapped_column(Text, default="")     # 复核意见（复核人填）
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    task: Mapped[Optional["CheckTask"]] = relationship(back_populates="issues")
    chain_task: Mapped[Optional["ChainCheckTask"]] = relationship(back_populates="issues")
    comments: Mapped[List["IssueComment"]] = relationship(
        back_populates="issue", cascade="all, delete-orphan", order_by="IssueComment.id"
    )


class IssueComment(Base):
    """在线批注：附在某条问题上的评论线程（§3.7 协同复核）。"""
    __tablename__ = "issue_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    author_name: Mapped[str] = mapped_column(String(64), default="")  # 冗余存名
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    issue: Mapped["IssueRecord"] = relationship(back_populates="comments")
