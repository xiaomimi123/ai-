"""ocr_qwen_vl 模块单元测试：mock dashscope 不真调 API。"""
import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import fitz


def _make_pdf_with_pages(n_pages: int) -> bytes:
    """生成 n 页空白 PDF（每页写"page i"文本，方便区分）。

    PyMuPDF 1.24+ 不允许保存 0 页文档，故 n_pages=0 时直接返回
    一个合法的空页数 PDF 字节串（xref 手工构造）。
    """
    if n_pages == 0:
        # 手工构造一个合法的 0 页 PDF，fitz.open() 可正常解析
        return (
            b"%PDF-1.4\n"
            b"1 0 obj<</Type /Catalog /Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type /Pages /Kids [] /Count 0>>endobj\n"
            b"xref\n0 3\n"
            b"0000000000 65535 f \n"
            b"0000000009 00000 n \n"
            b"0000000058 00000 n \n"
            b"trailer<</Root 1 0 R /Size 3>>\n"
            b"startxref\n110\n%%EOF"
        )
    doc = fitz.open()
    for i in range(n_pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"page {i}")
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


# ---------- get_vision_client ----------

def test_get_vision_client_returns_none_when_db_is_none():
    from app.parsers.ocr_qwen_vl import get_vision_client
    assert get_vision_client(None) is None


def test_get_vision_client_returns_none_when_disabled(monkeypatch):
    from app.parsers.ocr_qwen_vl import get_vision_client
    monkeypatch.setattr(
        "app.services.settings_service.get_vision_config",
        lambda db: {"enabled": False, "api_key": "sk", "model": "qwen-vl-plus"},
    )
    fake_db = MagicMock()
    assert get_vision_client(fake_db) is None


def test_get_vision_client_returns_none_when_no_api_key(monkeypatch):
    from app.parsers.ocr_qwen_vl import get_vision_client
    monkeypatch.setattr(
        "app.services.settings_service.get_vision_config",
        lambda db: {"enabled": True, "api_key": "", "model": "qwen-vl-plus"},
    )
    assert get_vision_client(MagicMock()) is None


def test_get_vision_client_returns_dict_when_configured(monkeypatch):
    from app.parsers.ocr_qwen_vl import get_vision_client
    monkeypatch.setattr(
        "app.services.settings_service.get_vision_config",
        lambda db: {"enabled": True, "api_key": "sk-abc", "model": "qwen-vl-plus"},
    )
    client = get_vision_client(MagicMock())
    assert client is not None
    assert client["model"] == "qwen-vl-plus"
    assert "_sdk" in client


# ---------- _render_pdf_pages_to_png ----------

def test_render_pdf_pages_first_and_last(tmp_path):
    from app.parsers.ocr_qwen_vl import _render_pdf_pages_to_png
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(_make_pdf_with_pages(3))
    imgs = _render_pdf_pages_to_png(str(pdf), [0, 2])
    assert len(imgs) == 2
    assert all(img.startswith(b"\x89PNG") for img in imgs)


def test_render_pdf_pages_single_page(tmp_path):
    from app.parsers.ocr_qwen_vl import _render_pdf_pages_to_png
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(_make_pdf_with_pages(1))
    imgs = _render_pdf_pages_to_png(str(pdf), [0, 0])
    # 函数不去重，调用方负责。给定 page_indices 是 [0,0] → 渲染两次同一页
    assert len(imgs) == 2
    assert all(img.startswith(b"\x89PNG") for img in imgs)


# ---------- ocr_pdf_first_and_last_page ----------

def test_ocr_pdf_returns_none_on_empty_pdf(tmp_path):
    from app.parsers.ocr_qwen_vl import ocr_pdf_first_and_last_page
    pdf = tmp_path / "empty.pdf"
    pdf.write_bytes(_make_pdf_with_pages(0))
    client = {"_sdk": MagicMock(), "model": "qwen-vl-plus"}
    assert ocr_pdf_first_and_last_page(str(pdf), client) is None


def test_ocr_pdf_merges_results_across_pages(tmp_path):
    """2 页 PDF，mock dashscope 第 1 页返回印章信息，第 2 页返回文号 → 合并。"""
    from app.parsers.ocr_qwen_vl import ocr_pdf_first_and_last_page
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(_make_pdf_with_pages(2))

    responses = [
        # 第 1 页（首页）：识别到红头标题 + issuer
        _fake_response({
            "text": "XX 市财政局\n关于...",
            "has_seal": False, "seal_text": "",
            "issue_date": "", "document_number": "", "issuer": "XX 市财政局",
        }),
        # 第 2 页（末页）：识别到印章 + 日期 + 文号
        _fake_response({
            "text": "...特此通知。",
            "has_seal": True, "seal_text": "XX 市财政局 财务专用章",
            "issue_date": "2025-03-15", "document_number": "财办〔2025〕12号",
            "issuer": "",
        }),
    ]

    sdk = MagicMock()
    sdk.MultiModalConversation.call.side_effect = responses
    client = {"_sdk": sdk, "model": "qwen-vl-plus"}
    out = ocr_pdf_first_and_last_page(str(pdf), client)
    assert out is not None
    assert "XX 市财政局" in out["text"]
    assert "特此通知" in out["text"]
    assert out["has_seal"] is True
    assert out["seal_text"] == "XX 市财政局 财务专用章"
    assert out["issue_date"] == "2025-03-15"
    assert out["document_number"] == "财办〔2025〕12号"
    assert out["issuer"] == "XX 市财政局"


def test_ocr_pdf_returns_none_when_all_pages_fail(tmp_path):
    """dashscope 全部 raise → 合并结果全空 → 返回 None。"""
    from app.parsers.ocr_qwen_vl import ocr_pdf_first_and_last_page
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(_make_pdf_with_pages(2))
    sdk = MagicMock()
    sdk.MultiModalConversation.call.side_effect = RuntimeError("API down")
    client = {"_sdk": sdk, "model": "qwen-vl-plus"}
    assert ocr_pdf_first_and_last_page(str(pdf), client) is None


def _fake_response(payload: dict, status_code: int = 200):
    """模拟 dashscope MultiModalConversation.call 的返回结构。"""
    import json
    r = MagicMock()
    r.status_code = status_code  # 真实 dashscope 成功返回 200
    r.output.choices = [MagicMock()]
    r.output.choices[0].message.content = json.dumps(payload, ensure_ascii=False)
    return r
