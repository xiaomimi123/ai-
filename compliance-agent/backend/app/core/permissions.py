"""角色与权限（§3.7）。

四角色：管理员、招采专员、财务专员、内控专员。
权限按 §3.1 一级分类细分。
"""
from __future__ import annotations

from typing import FrozenSet, Set

ROLE_ADMIN = "admin"
ROLE_PROCUREMENT = "procurement"
ROLE_FINANCE = "finance"
ROLE_INTERNAL_CONTROL = "internal_control"

ALL_ROLES = frozenset([ROLE_ADMIN, ROLE_PROCUREMENT, ROLE_FINANCE, ROLE_INTERNAL_CONTROL])

# 角色 → 可访问的一级分类
_ROLE_CATEGORIES: dict[str, FrozenSet[str]] = {
    ROLE_ADMIN: frozenset({
        "内部制度", "合同", "采购招标", "内控报告",
        "决算报告", "财务报告", "国有资产报告",
        "绩效评价报告", "其他佐证资料",
    }),
    ROLE_PROCUREMENT: frozenset({"合同", "采购招标", "其他佐证资料"}),
    ROLE_FINANCE: frozenset({
        "财务报告", "决算报告", "国有资产报告",
        "合同",  # 合同付款涉及财务对账，需可见
        "其他佐证资料",
    }),
    ROLE_INTERNAL_CONTROL: frozenset({
        "内部制度", "内控报告", "绩效评价报告",
        "其他佐证资料",
    }),
}


def role_label(role: str) -> str:
    return {
        ROLE_ADMIN: "管理员",
        ROLE_PROCUREMENT: "招采专员",
        ROLE_FINANCE: "财务专员",
        ROLE_INTERNAL_CONTROL: "内控专员",
    }.get(role, role)


def allowed_categories(role: str) -> Set[str]:
    return set(_ROLE_CATEGORIES.get(role, frozenset()))


def can_access_category(role: str, category: str) -> bool:
    """空分类视为通用资料，对所有角色可见（保留向后兼容）。"""
    if not category:
        return True
    return category in _ROLE_CATEGORIES.get(role, frozenset())


def is_admin(role: str) -> bool:
    return role == ROLE_ADMIN
