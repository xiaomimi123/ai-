"""统一入口 + 策略分发：按扩展名路由到解析器，结果缓存避免重复解析。"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

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

_cache: Dict[str, ParsedDocument] = {}


def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class UnsupportedFormatError(ValueError):
    pass


def parse(path: str, use_cache: bool = True,
          db: Optional[Session] = None) -> ParsedDocument:
    """v1.3: 新增可选 db 参数 — 传入后扫描件 PDF 自动 OCR。"""
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
    file_name = Path(path).name
    result.key_elements = extract_key_elements(result.text, file_name=file_name)

    # v1.3: 扫描件 PDF + db 在 + 视觉模型启用 → 调 OCR 增强
    if (ext == ".pdf"
            and result.metadata.get("scanned")
            and db is not None):
        try:
            from app.parsers import ocr_qwen_vl
            client = ocr_qwen_vl.get_vision_client(db)
            if client is not None:
                ocr = ocr_qwen_vl.ocr_pdf_first_and_last_page(path, client)
                if ocr:
                    _merge_ocr_into_result(result, ocr)
        except Exception as exc:
            print(f"[ocr] 增强失败（已降级）: {exc}")

    if use_cache and key is not None:
        _cache[key] = result
    return result


def _merge_ocr_into_result(result: ParsedDocument, ocr: dict) -> None:
    """OCR 结果合并到 ParsedDocument：text 追加；key_elements 只填空字段。"""
    if ocr.get("text"):
        result.text = (result.text + "\n" + str(ocr["text"])).strip()
        result.metadata["ocr_applied"] = True
    ke = result.key_elements
    if ocr.get("has_seal"):
        ke.has_official_seal = True
        if ocr.get("seal_text") and not ke.seal_text:
            ke.seal_text = str(ocr["seal_text"])
    if ocr.get("issue_date") and not ke.issue_date:
        ke.issue_date = str(ocr["issue_date"])
        try:
            ke.issue_year = int(ocr["issue_date"][:4])
        except Exception:
            pass
    if ocr.get("document_number") and not ke.document_number:
        ke.document_number = str(ocr["document_number"])
    if ocr.get("issuer") and not ke.issuer:
        ke.issuer = str(ocr["issuer"])
