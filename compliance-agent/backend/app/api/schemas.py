"""API 请求/响应模型（v3 内控评价智能审核系统）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field


# ============================================================
# 认证 & 用户
# ============================================================
class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    full_name: str = ""
    unit_id: Optional[int] = None
    is_active: bool = True

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    token: str
    user: UserOut
    role_label: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str
    full_name: str = ""
    unit_id: Optional[int] = None


class PasswordChangeRequest(BaseModel):
    new_password: str
    old_password: Optional[str] = None  # 非管理员改自己时必填


class SetActiveRequest(BaseModel):
    active: bool


class AuditLogOut(BaseModel):
    id: int
    username: str
    action: str
    target_type: str
    target_id: Optional[int] = None
    detail: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ============================================================
# 系统设置（LLM API Key 等）
# ============================================================
class LLMSettings(BaseModel):
    provider: str = "stub"          # stub | deepseek | claude
    model: str = ""
    base_url: str = ""
    thinking_mode: str = "non_think"  # non_think | think_high | think_max
    has_api_key: bool = False         # 后端只回是否已配置，不回明文 key


class LLMSettingsUpdate(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None  # None=不变，""=清空，其他=覆盖
    thinking_mode: Optional[str] = None


# ============================================================
# 评价指标库 & 问题清单库
# ============================================================
class IndicatorIn(BaseModel):
    indicator_code: str
    level: str = "单位"
    category: str = ""
    subcategory: str = ""
    name: str
    description: str = ""
    max_score: float = 0.0
    audit_points: str = ""
    deduct_rules: str = ""
    common_deductions: str = ""
    required_materials: List[str] = Field(default_factory=list)


class IndicatorOut(BaseModel):
    id: int
    indicator_code: str
    level: str
    category: str
    subcategory: str
    name: str
    description: str
    max_score: float
    audit_points: str
    deduct_rules: str
    common_deductions: str
    required_materials: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ============================================================
# 工作底稿（AI 阅卷产物）
# ============================================================
class WorksheetRowOut(BaseModel):
    id: int
    indicator_id: int
    serial: int
    original_score: float
    audited_score: float
    audit_finding_text: str
    adjustment_note: str = ""
    material_flags: str
    linked_finding_ids: str

    class Config:
        from_attributes = True


class WorksheetOut(BaseModel):
    id: int
    task_id: int
    unit_name: str
    unit_code: str
    auditor_name: str
    reviewer_name: str
    status: str
    rows: List[WorksheetRowOut] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RegulationOut(BaseModel):
    id: int
    title: str
    doc_type: str
    region: str
    issuer: str
    doc_number: str
    effective_date: str
    description: str
    tags: str
    file_name: str
    file_size: int
    file_type: str
    chunks_count: int
    indexed: bool
    uploaded_by: Optional[int] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RegulationListResponse(BaseModel):
    regulations: List[RegulationOut]
    total: int
    doc_types: List[str]
    regions: List[str]


class CheckItemIn(BaseModel):
    item_code: str
    dimension: str
    subcategory: str = ""
    description: str
    applicable_indicators: List[str] = Field(default_factory=list)
    risk_level: str = "中"
    common_patterns: List[str] = Field(default_factory=list)
    check_method: str = "llm"  # rule | llm
    keywords: List[str] = Field(default_factory=list)


class CheckItemOut(BaseModel):
    id: int
    item_code: str
    dimension: str
    subcategory: str
    description: str
    applicable_indicators: str
    risk_level: str
    common_patterns: str
    check_method: str
    keywords: str
    is_active: bool

    class Config:
        from_attributes = True


# ============================================================
# 被检查单位
# ============================================================
class AuditUnitIn(BaseModel):
    name: str
    code: str = ""
    level: str = "单位"
    description: str = ""


class AuditUnitOut(BaseModel):
    id: int
    name: str
    code: str
    level: str
    description: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ============================================================
# 核查任务 & 材料 & 核查发现
# ============================================================
class AuditTaskCreate(BaseModel):
    unit_id: int
    name: str
    eval_year: int = 2025
    scope: str = "all"   # "all" | "selected"
    selected_indicator_ids: List[int] = Field(default_factory=list)
    fast_mode: bool = False


class AuditTaskOut(BaseModel):
    id: int
    unit_id: int
    name: str
    eval_year: int
    scope: str = "all"
    selected_indicator_ids: str = "[]"
    status: str
    summary: str
    stats: str
    progress_current: int = 0
    progress_total: int = 0
    progress_text: str = ""
    fast_mode: bool = False
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class MaterialOut(BaseModel):
    id: int
    task_id: int
    indicator_id: Optional[int] = None
    file_name: str
    file_type: str
    is_scanned: bool
    key_elements: str
    # v1.4 文件去重：上传时是否复用已有物理文件 / 节省的 MB
    reused: bool = False
    reused_size_mb: float = 0.0

    class Config:
        from_attributes = True


class FindingOut(BaseModel):
    id: int
    task_id: int
    material_id: Optional[int] = None
    indicator_id: Optional[int] = None
    check_item_id: Optional[int] = None
    finding_type: str
    severity: str
    description: str
    evidence_location: str
    legal_basis: str
    suggestion: str
    source: str
    review_status: str
    reviewer_id: Optional[int] = None
    review_note: str
    rectification_status: str
    rectification_note: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TaskDetailOut(BaseModel):
    task: AuditTaskOut
    unit: AuditUnitOut
    materials: List[MaterialOut] = []
    findings: List[FindingOut] = []


class FindingReviewRequest(BaseModel):
    status: str  # confirmed | ignored | adjusted
    note: str = ""


class FindingRectifyRequest(BaseModel):
    note: str


class FindingRectifyConfirmRequest(BaseModel):
    note: str = ""
