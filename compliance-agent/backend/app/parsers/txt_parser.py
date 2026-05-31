"""纯文本解析器。也用于离线测试与法规导入。

按空行或「第X章/第X条」标题粗略切分 section，便于位置标注。
"""
from __future__ import annotations

import re
from pathlib import Path

from app.parsers.base import ParsedDocument, PageBlock

_SECTION_RE = re.compile(r"^\s*(第[一二三四五六七八九十百零\d]+[章条节]|[一二三四五六七八九十]+、)")


def parse_txt(path: str) -> ParsedDocument:
    raw = Path(path).read_text(encoding="utf-8", errors="ignore")
    return parse_text_content(raw, file_name=Path(path).name)


def parse_text_content(raw: str, file_name: str = "") -> ParsedDocument:
    blocks: list[PageBlock] = []
    current_section = "正文"
    for para in (p.strip() for p in raw.split("\n")):
        if not para:
            continue
        if _SECTION_RE.match(para):
            current_section = para[:40]
        blocks.append(PageBlock(page=1, section=current_section, content=para))
    return ParsedDocument(
        text=raw,
        page_blocks=blocks,
        tables=[],
        metadata={"file_name": file_name, "parser": "txt"},
    )
