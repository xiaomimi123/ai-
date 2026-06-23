"""dispatcher 的 OCR 分支 + 合并逻辑测试（mock OCR 不真调）。"""
import io
from unittest.mock import MagicMock, patch

import pytest
import fitz


def _make_text_pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def _make_blank_pdf(n_pages: int = 1) -> bytes:
    """空白扫描件（无文字，纯空页面）—— PyMuPDF 抽不到文字。"""
    doc = fitz.open()
    for _ in range(n_pages):
        doc.new_page()
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


# ---------- _merge_ocr_into_result ----------

def test_merge_ocr_fills_empty_fields():
    from app.parsers.base import ParsedDocument, KeyElements
    from app.parsers.dispatcher import _merge_ocr_into_result
    pd = ParsedDocument(text="原文本", key_elements=KeyElements())
    pd.metadata = {}
    _merge_ocr_into_result(pd, {
        "text": "OCR 文本",
        "has_seal": True, "seal_text": "XX 章",
        "issue_date": "2025-03-15", "document_number": "X〔2025〕1号",
        "issuer": "XX 局",
    })
    assert "OCR 文本" in pd.text
    assert pd.key_elements.has_official_seal is True
    assert pd.key_elements.seal_text == "XX 章"
    assert pd.key_elements.issue_date == "2025-03-15"
    assert pd.key_elements.issue_year == 2025
    assert pd.key_elements.document_number == "X〔2025〕1号"
    assert pd.key_elements.issuer == "XX 局"
    assert pd.metadata["ocr_applied"] is True


def test_merge_ocr_does_not_override_existing_nonempty():
    """原 key_elements 已有 issue_date → OCR 也给值 → 保留原值。"""
    from app.parsers.base import ParsedDocument, KeyElements
    from app.parsers.dispatcher import _merge_ocr_into_result
    pd = ParsedDocument(text="原文本")
    pd.key_elements.issue_date = "2024-01-01"
    pd.key_elements.document_number = "原文号"
    _merge_ocr_into_result(pd, {
        "text": "", "has_seal": False, "seal_text": "",
        "issue_date": "2025-03-15", "document_number": "新文号",
        "issuer": "",
    })
    # 原值不被覆盖
    assert pd.key_elements.issue_date == "2024-01-01"
    assert pd.key_elements.document_number == "原文号"


def test_merge_ocr_text_appended_not_replaced():
    """OCR 文本应追加到 result.text 末尾，不删除原文本。"""
    from app.parsers.base import ParsedDocument
    from app.parsers.dispatcher import _merge_ocr_into_result
    pd = ParsedDocument(text="原 PyMuPDF 文本")
    _merge_ocr_into_result(pd, {"text": "OCR 补充", "has_seal": False})
    assert "原 PyMuPDF 文本" in pd.text
    assert "OCR 补充" in pd.text


# ---------- dispatcher.parse(db=...) ----------

def test_parse_text_pdf_no_ocr_even_when_db_given(tmp_path):
    """文字 PDF（PyMuPDF 抽到正文）→ scanned=False → 不触发 OCR。"""
    from app.parsers.dispatcher import parse
    pdf = tmp_path / "text.pdf"
    pdf.write_bytes(_make_text_pdf("有正文有正文有正文有正文"))
    fake_db = MagicMock()
    with patch("app.parsers.ocr_qwen_vl.get_vision_client") as m_get:
        result = parse(str(pdf), use_cache=False, db=fake_db)
    m_get.assert_not_called()  # 文字 PDF 不该走 OCR 路径
    assert not result.metadata.get("ocr_applied", False)


def test_parse_scanned_pdf_no_ocr_when_db_none(tmp_path):
    """扫描件 + db=None → OCR 不触发。"""
    from app.parsers.dispatcher import parse
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(_make_blank_pdf(1))
    result = parse(str(pdf), use_cache=False, db=None)
    assert result.metadata.get("scanned") is True
    assert not result.metadata.get("ocr_applied", False)


def test_parse_scanned_pdf_no_ocr_when_vision_disabled(tmp_path):
    """扫描件 + db 在 + vision_enabled=False → OCR 不触发。"""
    from app.parsers.dispatcher import parse
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(_make_blank_pdf(1))
    fake_db = MagicMock()
    with patch("app.parsers.ocr_qwen_vl.get_vision_client",
               return_value=None) as m_get:
        result = parse(str(pdf), use_cache=False, db=fake_db)
    m_get.assert_called_once_with(fake_db)
    assert not result.metadata.get("ocr_applied", False)


def test_parse_scanned_pdf_triggers_ocr_and_merges(tmp_path):
    """扫描件 + db + enabled → OCR 触发 → key_elements 被填充。"""
    from app.parsers.dispatcher import parse
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(_make_blank_pdf(1))
    fake_db = MagicMock()
    fake_client = {"_sdk": MagicMock(), "model": "qwen-vl-plus"}
    fake_ocr = {
        "text": "OCR 出的内容",
        "has_seal": True, "seal_text": "XX 局印章",
        "issue_date": "2025-06-01", "document_number": "X〔2025〕5号",
        "issuer": "XX 局",
    }
    with patch("app.parsers.ocr_qwen_vl.get_vision_client",
               return_value=fake_client), \
         patch("app.parsers.ocr_qwen_vl.ocr_pdf_first_and_last_page",
               return_value=fake_ocr):
        result = parse(str(pdf), use_cache=False, db=fake_db)
    assert result.metadata.get("ocr_applied") is True
    assert result.key_elements.has_official_seal is True
    assert result.key_elements.seal_text == "XX 局印章"
    assert result.key_elements.issue_date == "2025-06-01"
    assert result.key_elements.document_number == "X〔2025〕5号"
    assert result.key_elements.issuer == "XX 局"


def test_parse_pdf_ocr_failure_falls_through(tmp_path):
    """OCR 抛异常 → dispatcher 不再抛 → 仍返回原始 ParsedDocument。"""
    from app.parsers.dispatcher import parse
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(_make_blank_pdf(1))
    fake_db = MagicMock()
    fake_client = {"_sdk": MagicMock(), "model": "qwen-vl-plus"}
    with patch("app.parsers.ocr_qwen_vl.get_vision_client",
               return_value=fake_client), \
         patch("app.parsers.ocr_qwen_vl.ocr_pdf_first_and_last_page",
               side_effect=RuntimeError("network down")):
        # 不应抛出
        result = parse(str(pdf), use_cache=False, db=fake_db)
    assert result is not None
    assert not result.metadata.get("ocr_applied", False)
