"""v3 领域常量。

5 大检查维度（来自 v3 §1.3）+ 风险等级 + 状态枚举。
"""
from __future__ import annotations

import enum


class Severity(str, enum.Enum):
    HIGH = "高"
    MEDIUM = "中"
    LOW = "低"


# 维度（v3 §1.3）
DIMENSIONS = [
    "总体合规性",      # 真实性/年度一致性/正式性/要素完整性
    "相关性核查",      # 6 大业务分类
    "评分合规性",      # 轮岗扣分、不适用业务、整改时点、补充指标=10
    "复核规范性",      # 复核权限/分离/内容/流程
    "报告编报合规性",  # 报告信息/内控描述/整改填报/系统操作
]

# Finding 的 finding_type（细分类，便于报告聚合）
FINDING_TYPES = [
    "真实性问题",
    "年度一致性问题",
    "正式性问题",
    "完整性问题",
    "相关性问题",
    "合规性问题",
    "评分合规问题",
    "复核规范问题",
    "报告编报问题",
]

# 6 大业务分类（v3 §1.3 维度二）
BUSINESS_CATEGORIES = [
    "组织层面",         # 三重一大、轮岗、内控会议、内控培训
    "预算业务",         # 预算制度、公开、绩效管理
    "收支业务",         # 票据台账、支出审批
    "政府采购",         # 采购全流程
    "资产建设合同",     # 盘点表、项目全流程、合同台账
    "内部监督",         # 检查方案、整改闭环
]


# 任务状态机
class TaskStatus(str, enum.Enum):
    PENDING = "pending"          # 任务已创建，材料还未上传完成
    RUNNING = "running"          # AI 核查中
    AI_DONE = "ai_done"          # AI 初核完成，待人工复核
    REVIEWING = "reviewing"      # 人工复核中
    FINALIZED = "finalized"      # 已定稿，已生成正式报告
    ARCHIVED = "archived"        # 已归档（整改闭环）
    FAILED = "failed"


# Finding 复核状态
class ReviewStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    IGNORED = "ignored"
    ADJUSTED = "adjusted"


# 整改状态
class RectificationStatus(str, enum.Enum):
    OPEN = "open"
    SUBMITTED = "submitted"
    RESOLVED = "resolved"
