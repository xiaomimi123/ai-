"""v3 角色与权限（v3 §3.7）。

四角色：
- super_admin   超级管理员：全部权限（管理知识库、用户、任务）
- auditor       审查员：创建任务、查看结果、复核标注、生成报告
- unit          被检查单位：上传材料、查看本单位核查结果、填写整改说明
- readonly      只读用户：查看报告，不可操作
"""
from __future__ import annotations

ROLE_SUPER_ADMIN = "super_admin"
ROLE_AUDITOR = "auditor"
ROLE_UNIT = "unit"
ROLE_READONLY = "readonly"

# 向后兼容：旧种子 admin 角色直接映射到 super_admin
_LEGACY_ROLE_MAP = {"admin": ROLE_SUPER_ADMIN}

ALL_ROLES = frozenset([ROLE_SUPER_ADMIN, ROLE_AUDITOR, ROLE_UNIT, ROLE_READONLY])


def normalize_role(role: str) -> str:
    return _LEGACY_ROLE_MAP.get(role, role)


def role_label(role: str) -> str:
    return {
        ROLE_SUPER_ADMIN: "超级管理员",
        ROLE_AUDITOR: "审查员",
        ROLE_UNIT: "被检查单位",
        ROLE_READONLY: "只读用户",
    }.get(normalize_role(role), role)


def is_admin(role: str) -> bool:
    return normalize_role(role) == ROLE_SUPER_ADMIN


def is_auditor_or_above(role: str) -> bool:
    r = normalize_role(role)
    return r in (ROLE_SUPER_ADMIN, ROLE_AUDITOR)


def is_unit(role: str) -> bool:
    return normalize_role(role) == ROLE_UNIT


def can_manage_knowledge(role: str) -> bool:
    """管理知识库（指标库、问题清单库）：仅超级管理员。"""
    return is_admin(role)


def can_create_task(role: str) -> bool:
    """创建核查任务：审查员及以上。"""
    return is_auditor_or_above(role)


def can_review_findings(role: str) -> bool:
    """复核标注 finding：审查员及以上。"""
    return is_auditor_or_above(role)


def can_rectify_findings(role: str) -> bool:
    """填写整改说明：被检查单位 + 审查员（代填）。"""
    r = normalize_role(role)
    return r in (ROLE_SUPER_ADMIN, ROLE_AUDITOR, ROLE_UNIT)
