"""解析输出的统一结构（v3 §3.3）。

包含位置信息（页码/章节）+ key_elements（公章/签字/日期/文号自动抽取）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PageBlock:
    page: int
    section: str
    content: str


@dataclass
class KeyElements:
    """v3 §3.3 的 key_elements：用于真实性核查的刚性判断。"""
    has_official_seal: bool = False     # 是否有公章
    has_signature: bool = False         # 是否有签字
    has_red_header: bool = False        # 是否为红头文件
    issue_date: str = ""                # 发文/印发日期（YYYY-MM-DD）
    issue_year: Optional[int] = None    # 年度（int）
    document_number: str = ""           # 文件编号 如「XXX发[2025]5号」
    is_draft: bool = False              # 是否为草稿/征求意见稿
    # v1.3 新增（OCR 提取的章上文字 + 发文机关）
    seal_text: str = ""
    issuer: str = ""


@dataclass
class ParsedDocument:
    text: str
    page_blocks: List[PageBlock] = field(default_factory=list)
    tables: List[List[List[str]]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    key_elements: KeyElements = field(default_factory=KeyElements)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "page_blocks": [vars(b) for b in self.page_blocks],
            "tables": self.tables,
            "metadata": self.metadata,
            "key_elements": self.key_elements.__dict__,
        }
