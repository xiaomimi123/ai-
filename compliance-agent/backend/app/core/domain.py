"""跨模块共享的领域类型。

核心是 §3.6 的「问题条目统一结构」，规则引擎、台账、报告都用它。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field, asdict
from typing import List, Optional


class RiskLevel(str, enum.Enum):
    HIGH = "高"
    MEDIUM = "中"
    LOW = "低"


class IssueCategory(str, enum.Enum):
    FORMAT = "格式要素"          # 刚性：发文文号、签章等
    PROCESS = "流程留痕"          # 刚性：审批/留痕缺失
    CONSISTENCY = "数据一致性"    # 刚性：大小写金额、前后矛盾
    COMPLIANCE = "条款合规"       # 柔性：对标上位法
    LOGIC = "逻辑合理性"          # 柔性
    OTHER = "其他"


# 文档一级分类（§3.1 的 9 大分类）
DOC_CATEGORIES = [
    "内部制度",
    "合同",
    "采购招标",
    "内控报告",
    "决算报告",
    "财务报告",
    "国有资产报告",
    "绩效评价报告",
    "其他佐证资料",
]


@dataclass
class Location:
    """资料具体位置：文件名 + 页码 + 段落/章节。"""
    file_name: str = ""
    page: Optional[int] = None
    section: str = ""

    def human(self) -> str:
        parts = [self.file_name or "未知文件"]
        if self.page is not None:
            parts.append(f"第{self.page}页")
        if self.section:
            parts.append(self.section)
        return " / ".join(parts)


@dataclass
class Issue:
    """§3.6 统一问题条目结构。"""
    description: str                      # 疑点描述
    location: Location                    # 资料位置
    category: IssueCategory               # 问题类别
    risk_level: RiskLevel                 # 风险等级
    suggestion: str = ""                  # 整改建议
    legal_basis: str = ""                 # 法规依据（柔性规则由 RAG 召回填充）
    rule_id: str = ""                     # 触发的规则标识
    source: str = "rigid"                 # rigid | soft(llm)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["category"] = self.category.value
        d["risk_level"] = self.risk_level.value
        d["location"] = self.location.human()
        return d
