"""检查模板注册表（§3.4 的 7 套模板）。

Phase 1 实现「合同全流程检查模板」；其余模板登记占位，
Phase 2 逐步补全刚性/柔性规则。
"""
from __future__ import annotations

from typing import Dict, List

from app.rules.base import CheckTemplate
from app.rules.contract import CONTRACT_RIGID_RULES
from app.rules.contract_soft import CONTRACT_SOFT_RULES
from app.rules.institution import INSTITUTION_RIGID_RULES
from app.rules.institution_soft import INSTITUTION_SOFT_RULES
from app.rules.procurement import PROCUREMENT_RIGID_RULES
from app.rules.procurement_soft import PROCUREMENT_SOFT_RULES
from app.rules.internal_control import (
    INTERNAL_CONTROL_RIGID_RULES,
    INTERNAL_CONTROL_SOFT_RULES,
)
from app.rules.finance_final import FINANCE_FINAL_RIGID_RULES, FINANCE_FINAL_SOFT_RULES
from app.rules.asset import ASSET_RIGID_RULES, ASSET_SOFT_RULES
from app.rules.performance import PERFORMANCE_RIGID_RULES, PERFORMANCE_SOFT_RULES

_TEMPLATES: Dict[str, CheckTemplate] = {}


def _register(t: CheckTemplate) -> None:
    _TEMPLATES[t.key] = t


# —— Phase 1：合同 ——
_register(CheckTemplate(
    key="contract",
    name="合同全流程检查模板",
    applies_to="合同",
    rigid_rules=list(CONTRACT_RIGID_RULES),
    soft_rules=list(CONTRACT_SOFT_RULES),
))

# —— Phase 2：内部制度 ——
_register(CheckTemplate(
    key="institution",
    name="制度合规检查模板",
    applies_to="内部制度",
    rigid_rules=list(INSTITUTION_RIGID_RULES),
    soft_rules=list(INSTITUTION_SOFT_RULES),
))

# —— Phase 2：招采三合一 ——
_register(CheckTemplate(
    key="procurement",
    name="招采三合一检查模板",
    applies_to="采购招标",
    rigid_rules=list(PROCUREMENT_RIGID_RULES),
    soft_rules=list(PROCUREMENT_SOFT_RULES),
))

# —— Phase 2：内控报告 / 财务+决算 / 资产报告 / 绩效评价 ——
_register(CheckTemplate(
    key="internal_control",
    name="内控报告检查模板",
    applies_to="内控报告",
    rigid_rules=list(INTERNAL_CONTROL_RIGID_RULES),
    soft_rules=list(INTERNAL_CONTROL_SOFT_RULES),
))
_register(CheckTemplate(
    key="finance_final",
    name="财务+决算联合检查模板",
    applies_to="财务报告",
    rigid_rules=list(FINANCE_FINAL_RIGID_RULES),
    soft_rules=list(FINANCE_FINAL_SOFT_RULES),
))
_register(CheckTemplate(
    key="asset",
    name="资产报告检查模板",
    applies_to="国有资产报告",
    rigid_rules=list(ASSET_RIGID_RULES),
    soft_rules=list(ASSET_SOFT_RULES),
))
_register(CheckTemplate(
    key="performance",
    name="绩效评价报告检查模板",
    applies_to="绩效评价报告",
    rigid_rules=list(PERFORMANCE_RIGID_RULES),
    soft_rules=list(PERFORMANCE_SOFT_RULES),
))


def get_template(key: str) -> CheckTemplate:
    if key not in _TEMPLATES:
        raise KeyError(f"未知检查模板: {key}，可用: {', '.join(_TEMPLATES)}")
    return _TEMPLATES[key]


def list_templates() -> List[dict]:
    return [
        {
            "key": t.key,
            "name": t.name,
            "applies_to": t.applies_to,
            "rigid_rules": len(t.rigid_rules),
            "soft_rules": len(t.soft_rules),
            "ready": bool(t.rigid_rules or t.soft_rules),
        }
        for t in _TEMPLATES.values()
    ]
