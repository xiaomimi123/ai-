"""检查规则引擎（§3.4）：刚性规则 + 柔性规则 + 检查模板。"""
from app.rules.base import RigidRule, SoftRule, CheckTemplate, RuleEngine
from app.rules.registry import get_template, list_templates

__all__ = [
    "RigidRule",
    "SoftRule",
    "CheckTemplate",
    "RuleEngine",
    "get_template",
    "list_templates",
]
