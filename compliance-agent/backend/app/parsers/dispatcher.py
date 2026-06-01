"""统一入口 + 策略分发：按扩展名路由到解析器，结果缓存避免重复解析。"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable, Dict

from app.parsers.base import ParsedDocument
from app.parsers.element_extractor import extract_key_elements
from app.parsers.txt_parser import parse_txt
from app.parsers.docx_parser import parse_docx
from app.parsers.pdf_parser import parse_pdf
from app.parsers.xlsx_parser import parse_xlsx

_PARSERS: Dict[str, Callable[[str], ParsedDocument]] = {
    ".txt": parse_txt,
    ".md": parse_txt,
    ".docx": parse_docx,
    ".pdf": parse_pdf,
    ".xlsx": parse_xlsx,
}

SUPPORTED_EXTENSIONS = sorted(_PARSERS.keys())

# 进程内缓存：file content hash -> ParsedDocument
_cache: Dict[str, ParsedDocument] = {}


def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class UnsupportedFormatError(ValueError):
    pass


def parse(path: str, use_cache: bool = True) -> ParsedDocument:
    ext = Path(path).suffix.lower()
    parser = _PARSERS.get(ext)
    if parser is None:
        raise UnsupportedFormatError(
            f"不支持的文件格式: {ext}（支持 {', '.join(SUPPORTED_EXTENSIONS)}）"
        )
    key = None
    if use_cache:
        key = _file_hash(path)
        if key in _cache:
            return _cache[key]
    result = parser(path)
    # v3 §3.3：自动抽取 key_elements
    file_name = Path(path).name
    result.key_elements = extract_key_elements(result.text, file_name=file_name)
    if use_cache and key is not None:
        _cache[key] = result
    return result
