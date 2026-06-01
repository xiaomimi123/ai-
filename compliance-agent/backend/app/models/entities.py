"""业务实体（v3：内控评价智能审核系统）。

v3 角色：超级管理员 / 审查员 / 被检查单位 / 只读用户。
v3 核心：评价指标库 + 问题清单库 + 核查任务 + 核查发现 + 整改闭环。
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


# ============================================================
# 用户 & 认证 & 审计 & 系统设置
# ============================================================
class User(Base):
    """用户 + 角色（v3 §3.7）：super_admin | auditor | unit | readonly。"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(32))
    full_name: Mapped[str] = mapped_column(String(64), default="")
    # 若为 unit 角色，绑定对应被检查单位（仅能看自己单位的数据）
    unit_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("audit_units.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuditLog(Base):
    """操作审计日志（v3 §3.7「全程留痕可溯源」）。"""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str] = mapped_column(String(32), default="")
    target_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AppSetting(Base):
    """系统全局配置 key/value 存储（如 LLM API Key）。

    敏感配置如 API Key 也存在这里（数据库级隔离即可，避免环境变量层级硬编码）。
    """
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


# ============================================================
# 评价指标库 & 问题清单库（v3 §3.1、§3.2 黄金数据）
# ============================================================
class Indicator(Base):
    """评价指标（编报指南 附件1/附件2）。

    例：1-1-1「三重一大」决策制度建立与执行情况，4 分。
    """
    __tablename__ = "indicators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    indicator_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    # 层级分类（组织层面/业务层面/内部监督；单位评价/部门评价）
    level: Mapped[str] = mapped_column(String(32), default="")        # 单位 | 部门
    category: Mapped[str] = mapped_column(String(64), default="")     # 6 大业务分类
    subcategory: Mapped[str] = mapped_column(String(64), default="")
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    max_score: Mapped[float] = mapped_column(default=0.0)
    deduct_rules: Mapped[str] = mapped_column(Text, default="")       # 扣分细则原文
    common_deductions: Mapped[str] = mapped_column(Text, default="")  # 常见扣分情形（黄金数据）
    required_materials: Mapped[str] = mapped_column(Text, default="") # JSON 数组：要求的材料类型
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CheckItem(Base):
    """问题清单条目（v3 §3.2）。

    例：ZS-001 真实性 - 材料是否加盖公章、签字齐全、要素完整
    """
    __tablename__ = "check_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    # 维度（v3 §1.3）：总体合规性|相关性核查|评分合规性|复核规范性|报告编报合规性
    dimension: Mapped[str] = mapped_column(String(32))
    subcategory: Mapped[str] = mapped_column(String(64), default="")   # 真实性/年度一致性/正式性/要素完整性...
    description: Mapped[str] = mapped_column(Text)
    applicable_indicators: Mapped[str] = mapped_column(Text, default="")  # JSON: 适用的指标 code 列表（[]=全部）
    risk_level: Mapped[str] = mapped_column(String(8), default="中")   # 高|中|低
    common_patterns: Mapped[str] = mapped_column(Text, default="")     # JSON 数组
    check_method: Mapped[str] = mapped_column(String(16), default="llm")  # rule|llm
    keywords: Mapped[str] = mapped_column(Text, default="")            # JSON 数组（rule 用）
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ============================================================
# 被检查单位
# ============================================================
class AuditUnit(Base):
    """被检查单位（v3 §3.7 一个独立角色范畴）。"""
    __tablename__ = "audit_units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    code: Mapped[str] = mapped_column(String(64), default="")
    level: Mapped[str] = mapped_column(String(32), default="单位")  # 单位 | 部门
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    tasks: Mapped[List["AuditTask"]] = relationship(back_populates="unit")


# ============================================================
# 核查任务 & 材料
# ============================================================
class AuditTask(Base):
    """一个单位一次核查任务（v3 §3.5）。

    一个任务对应一个被检查单位的内控评价报告核查，包含多个材料和多个指标。
    """
    __tablename__ = "audit_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("audit_units.id"), index=True)
    name: Mapped[str] = mapped_column(String(256))
    eval_year: Mapped[int] = mapped_column(Integer, default=2025)
    # AI 初核状态：pending → running → ai_done → reviewing(人工复核中) → finalized(已定稿) → archived
    status: Mapped[str] = mapped_column(String(32), default="pending")
    summary: Mapped[str] = mapped_column(Text, default="")
    # 任务级统计（JSON 序列化）
    stats: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    unit: Mapped["AuditUnit"] = relationship(back_populates="tasks")
    materials: Mapped[List["Material"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    findings: Mapped[List["Finding"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class Material(Base):
    """被检查单位上传的佐证材料（v3 §3.3）。

    每份材料**必须**绑定一个评价指标（v3 §3.3 明确要求）。
    """
    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("audit_tasks.id"), index=True)
    indicator_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("indicators.id"), nullable=True, index=True
    )
    file_name: Mapped[str] = mapped_column(String(512))
    storage_path: Mapped[str] = mapped_column(String(1024))
    file_type: Mapped[str] = mapped_column(String(16), default="")
    is_scanned: Mapped[bool] = mapped_column(Boolean, default=False)
    # v3 §3.3 key_elements（公章/签字/日期/文号），JSON 序列化
    key_elements: Mapped[str] = mapped_column(Text, default="")
    parsed_text: Mapped[str] = mapped_column(Text, default="")  # 解析后全文（截断）
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    task: Mapped["AuditTask"] = relationship(back_populates="materials")
    indicator: Mapped[Optional["Indicator"]] = relationship()


# ============================================================
# 核查发现 & 整改闭环
# ============================================================
class Finding(Base):
    """AI 核查发现（v3 §3.4）。

    finding 是 v3 的核心输出对象，每条都对应一个具体的合规疑点，
    支持人工复核标注（确认/忽略/调整）和整改闭环。
    """
    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("audit_tasks.id"), index=True)
    material_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("materials.id"), nullable=True, index=True
    )
    indicator_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("indicators.id"), nullable=True, index=True
    )
    check_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("check_items.id"), nullable=True
    )

    # 维度（v3 §1.3）：真实性|相关性|完整性|合规性|评分合规|复核规范|报告编报
    finding_type: Mapped[str] = mapped_column(String(32), default="")
    severity: Mapped[str] = mapped_column(String(8), default="中")  # 高|中|低
    description: Mapped[str] = mapped_column(Text)
    evidence_location: Mapped[str] = mapped_column(String(512), default="")
    legal_basis: Mapped[str] = mapped_column(Text, default="")
    suggestion: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(16), default="rule")  # rule | llm

    # 人工复核标注（v3 §3.5）
    review_status: Mapped[str] = mapped_column(String(16), default="pending")
    # pending(未复核) | confirmed(确认) | ignored(忽略) | adjusted(调整)
    reviewer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    review_note: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 整改闭环（v3 §3.7）
    rectification_status: Mapped[str] = mapped_column(String(16), default="open")
    # open(未整改) | submitted(已提交整改) | resolved(已销号)
    rectification_note: Mapped[str] = mapped_column(Text, default="")
    rectified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    task: Mapped["AuditTask"] = relationship(back_populates="findings")
    material: Mapped[Optional["Material"]] = relationship()
    indicator: Mapped[Optional["Indicator"]] = relationship()
