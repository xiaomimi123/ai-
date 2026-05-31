"""解析输出的统一结构（§3.2）。

让位置信息（页码/章节）贯穿全流程，后续问题定位需要标注「资料具体位置」。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class PageBlock:
    page: int
    section: str
    content: str


@dataclass
class ParsedDocument:
    text: str
    page_blocks: List[PageBlock] = field(default_factory=list)
    tables: List[List[List[str]]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "page_blocks": [vars(b) for b in self.page_blocks],
            "tables": self.tables,
            "metadata": self.metadata,
        }
