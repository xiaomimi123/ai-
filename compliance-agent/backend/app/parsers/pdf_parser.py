"""PDF 解析器（PyMuPDF）。保留页码，扫描件可后续接 PaddleOCR。"""
from __future__ import annotations

from pathlib import Path

from app.parsers.base import ParsedDocument, PageBlock
from app.parsers.txt_parser import _SECTION_RE


def parse_pdf(path: str) -> ParsedDocument:
    import fitz  # PyMuPDF；延迟导入

    doc = fitz.open(path)
    blocks: list[PageBlock] = []
    texts: list[str] = []
    for page_index in range(len(doc)):
        page = doc[page_index]
        page_no = page_index + 1
        current_section = "正文"
        for line in page.get_text().splitlines():
            t = line.strip()
            if not t:
                continue
            if _SECTION_RE.match(t):
                current_section = t[:40]
            blocks.append(PageBlock(page=page_no, section=current_section, content=t))
            texts.append(t)
    doc.close()

    full = "\n".join(texts)
    metadata = {"file_name": Path(path).name, "parser": "pdf", "scanned": len(full.strip()) < 10}
    return ParsedDocument(text=full, page_blocks=blocks, tables=[], metadata=metadata)
