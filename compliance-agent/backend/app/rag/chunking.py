"""法规文档分块（§3.3）。

针对法规文档：按「条款」切分而非固定长度，每个 chunk 保留
法规名称、条款号作为 metadata，检索回来能直接引用「《XX法》第 X 条」。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# 匹配「第X条」条款起始：仅在行首（避免匹配正文中对条款的引用）
_ARTICLE_RE = re.compile(r"(?m)^\s*第[一二三四五六七八九十百千零\d]+条")
# 从文件首行/标题猜测法规名：《...》
_LAW_NAME_RE = re.compile(r"《([^》]+)》")


@dataclass
class Chunk:
    text: str
    metadata: Dict[str, str] = field(default_factory=dict)


def _guess_law_name(text: str, fallback: str) -> str:
    m = _LAW_NAME_RE.search(text[:200])
    return m.group(1) if m else fallback


def chunk_regulation(
    text: str,
    law_name: Optional[str] = None,
    category: str = "",
    source: str = "",
) -> List[Chunk]:
    """按条款切分法规文本。无「第X条」结构时退化为按段落切分。"""
    law = law_name or _guess_law_name(text, fallback=source or "未命名法规")

    matches = list(_ARTICLE_RE.finditer(text))
    chunks: List[Chunk] = []

    if matches:
        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[start:end].strip()
            if not body:
                continue
            article_no = m.group().strip()
            chunks.append(Chunk(
                text=body,
                metadata={
                    "law_name": law,
                    "article": article_no,
                    "category": category,
                    "source": source,
                    "citation": f"《{law}》{article_no}",
                },
            ))
    else:
        # 退化：按空行段落切，每段一个 chunk
        for para in (p.strip() for p in re.split(r"\n\s*\n", text)):
            if len(para) < 10:
                continue
            chunks.append(Chunk(
                text=para,
                metadata={"law_name": law, "category": category, "source": source,
                          "citation": f"《{law}》"},
            ))
    return chunks
