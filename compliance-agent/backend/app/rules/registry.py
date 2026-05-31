"""检查模板注册表（§3.4 的 7 套模板）。

Phase 1 实现「合同全流程检查模板」；其余模板登记占位，
Phase 2 逐步补全刚性/柔性规则。
"""
from __future__ import annotations

from typing import Dict, List

from app.rules.base import CheckTemplate
from app.rules.contract import CONTRACT_RIGID_RULES
from app.rules.contract_soft import CONTRACT_SOFT_RULES

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

# —— Phase 2 占位（规则后续补全）——
for key, name, applies in [
    ("institution", "制度合规检查模板", "内部制度"),
    ("procurement", "招采三合一检查模板", "采购招标"),
    ("internal_control", "内控报告检查模板", "内控报告"),
    ("finance_final", "财务+决算联合检查模板", "财务报告"),
    ("asset", "资产报告检查模板", "国有资产报告"),
    ("performance", "绩效评价报告检查模板", "绩效评价报告"),
]:
    _register(CheckTemplate(key=key, name=name, applies_to=applies))


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
