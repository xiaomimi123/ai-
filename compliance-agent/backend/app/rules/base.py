"""规则引擎抽象。

- RigidRule：确定性校验，不依赖 LLM，快且准（§3.4）。
- SoftRule：文档片段 + RAG 召回法规 → LLM 输出疑点。
- CheckTemplate：一套规则集合（对应 7 套模板之一）。
- RuleEngine：遍历模板规则，汇总 Issue。
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import List, Optional, Protocol

from app.core.domain import Issue
from app.parsers.base import ParsedDocument


class RigidRule(abc.ABC):
    """确定性规则基类。子类实现 check()，不得调用 LLM。"""

    id: str = ""
    description: str = ""

    @abc.abstractmethod
    def check(self, doc: ParsedDocument) -> List[Issue]:
        ...


class SoftRuleContext(Protocol):
    """柔性规则运行所需的能力（LLM + RAG），由引擎注入。"""

    def retrieve(self, query: str, category: Optional[str], top_k: int) -> list: ...
    def llm_extract_issues(self, prompt: str) -> list: ...


class SoftRule(abc.ABC):
    """柔性规则基类：组装 文档 + 召回法规 → LLM。"""

    id: str = ""
    description: str = ""

    @abc.abstractmethod
    def check(self, doc: ParsedDocument, ctx: Optional[SoftRuleContext]) -> List[Issue]:
        ...


@dataclass
class CheckTemplate:
    key: str
    name: str
    applies_to: str                       # 适用文件类型（一级分类）
    rigid_rules: List[RigidRule] = field(default_factory=list)
    soft_rules: List[SoftRule] = field(default_factory=list)


class RuleEngine:
    """对单份文档执行一套模板，返回问题台账。"""

    def __init__(self, soft_ctx: Optional[SoftRuleContext] = None):
        self.soft_ctx = soft_ctx

    def run(self, template: CheckTemplate, doc: ParsedDocument) -> List[Issue]:
        issues: List[Issue] = []
        for rule in template.rigid_rules:
            try:
                issues.extend(rule.check(doc))
            except Exception as exc:  # 单条规则失败不影响整体
                issues.append(self._rule_error(rule.id, exc))
        for rule in template.soft_rules:
            try:
                issues.extend(rule.check(doc, self.soft_ctx))
            except Exception as exc:
                issues.append(self._rule_error(rule.id, exc))
        return issues

    @staticmethod
    def _rule_error(rule_id: str, exc: Exception) -> Issue:
        from app.core.domain import IssueCategory, Location, RiskLevel

        return Issue(
            description=f"规则 {rule_id} 执行异常：{exc}",
            location=Location(),
            category=IssueCategory.OTHER,
            risk_level=RiskLevel.LOW,
            suggestion="请检查规则配置或文档解析结果。",
            rule_id=rule_id,
            source="engine-error",
        )
