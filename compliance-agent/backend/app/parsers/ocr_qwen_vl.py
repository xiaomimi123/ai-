"""Qwen-VL 视觉 OCR：把扫描件 PDF 首末两页转图，一次返回 OCR + 关键要素 JSON。

接入阿里云 dashscope（Qwen-VL-Plus / Max）。失败静默降级。
"""
from __future__ import annotations

import base64
import json
from typing import Optional, Dict, Any, List

from sqlalchemy.orm import Session


VISION_PROMPT = (
    "这是一份内控评价材料的扫描页。请仔细识别后严格返回 JSON：\n"
    "{\n"
    '  "text": "页面全部文字内容（按阅读顺序）",\n'
    '  "has_seal": true/false（是否看到红色椭圆/圆形公章/印章/签章）,\n'
    '  "seal_text": "印章上的文字（如「XX 财政厅 财务专用章」），无则空串",\n'
    '  "issue_date": "落款日期 YYYY-MM-DD，无则空串",\n'
    '  "document_number": "文件编号如「财办〔2025〕12号」，无则空串",\n'
    '  "issuer": "发文机关（红头大标题），无则空串"\n'
    "}\n"
    "只返回 JSON，不要其它解释文字。"
)


def get_vision_client(db: Optional[Session]) -> Optional[Dict[str, Any]]:
    """从 DB AppSetting 拿 Qwen-VL 配置。disabled / 缺 key / SDK 未装 → None。"""
    if db is None:
        return None
    from app.services.settings_service import get_vision_config
    cfg = get_vision_config(db)
    if not cfg.get("enabled") or not cfg.get("api_key"):
        return None
    try:
        import dashscope
        dashscope.api_key = cfg["api_key"]
        return {
            "model": cfg.get("model") or "qwen-vl-plus",
            "_sdk": dashscope,
        }
    except ImportError:
        print("[ocr] dashscope SDK 未装，跳过 OCR")
        return None


def _render_pdf_pages_to_png(pdf_path: str, page_indices: List[int],
                             dpi: int = 150) -> List[bytes]:
    """用 PyMuPDF 把指定 page_indices 渲染为 PNG bytes。

    不对 page_indices 去重 — 调用方自己负责。越界的 index 静默跳过。
    """
    import fitz
    doc = fitz.open(pdf_path)
    out: List[bytes] = []
    for i in page_indices:
        if 0 <= i < len(doc):
            page = doc[i]
            pix = page.get_pixmap(dpi=dpi)
            out.append(pix.tobytes("png"))
    doc.close()
    return out


def _extract_content_from_response(response: Any) -> str:
    """从 dashscope MultiModalConversation 响应里取 content 字符串。

    兼容 content 是 str 或 list[dict]（dashscope 不同版本返回不同）。
    """
    # dashscope 失败时不抛异常，返回 status_code != 200 + None output
    status_code = getattr(response, "status_code", None)
    if status_code is not None and status_code != 200:
        code = getattr(response, "code", "") or ""
        msg = getattr(response, "message", "") or ""
        print(f"[ocr] dashscope 返回错误 HTTP {status_code} {code}: {msg}")
        return ""
    if not getattr(response, "output", None):
        return ""
    content = response.output.choices[0].message.content
    if isinstance(content, list):
        content = "".join(
            c.get("text", "") for c in content if isinstance(c, dict)
        )
    return str(content)


def _parse_json_loose(content: str) -> Optional[dict]:
    """从 LLM 返回里解析 JSON，兼容 ```json ... ``` 包裹。失败返回 None。"""
    s = content.strip()
    # 去掉常见的 markdown code fence
    if s.startswith("```"):
        s = s.lstrip("`")
        if s.startswith("json"):
            s = s[4:]
        s = s.strip().rstrip("`").strip()
    try:
        return json.loads(s)
    except Exception:
        return None


def ocr_pdf_first_and_last_page(pdf_path: str,
                                client: Dict[str, Any]) -> Optional[dict]:
    """OCR 首末两页（仅 1 页时 dedup 后只 OCR 一次）。

    返回合并字典 {text, has_seal, seal_text, issue_date, document_number, issuer}。
    全部失败或都没识别到任何内容 → 返回 None。
    """
    import fitz
    doc = fitz.open(pdf_path)
    n_pages = len(doc)
    doc.close()
    if n_pages == 0:
        return None
    page_indices = sorted({0, n_pages - 1})
    images = _render_pdf_pages_to_png(pdf_path, page_indices)
    if not images:
        return None

    combined = {
        "text": "", "has_seal": False, "seal_text": "",
        "issue_date": "", "document_number": "", "issuer": "",
    }
    sdk = client["_sdk"]
    model = client["model"]
    success_count = 0

    for img_bytes in images:
        b64 = base64.b64encode(img_bytes).decode()
        try:
            response = sdk.MultiModalConversation.call(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"image": f"data:image/png;base64,{b64}"},
                        {"text": VISION_PROMPT},
                    ],
                }],
                timeout=60,
            )
        except Exception as exc:
            print(f"[ocr] dashscope 调用失败: {exc}")
            continue

        content = _extract_content_from_response(response)
        data = _parse_json_loose(content)
        if data is None:
            print(f"[ocr] JSON 解析失败，原始内容前 100 字: {content[:100]}")
            continue

        success_count += 1
        page_text = str(data.get("text", "")).strip()
        if page_text:
            combined["text"] = (combined["text"] + "\n" + page_text).strip()
        if data.get("has_seal"):
            combined["has_seal"] = True
        for key in ("seal_text", "issue_date", "document_number", "issuer"):
            if not combined[key] and data.get(key):
                combined[key] = str(data[key]).strip()

    if success_count == 0:
        return None
    if not combined["text"] and not combined["has_seal"]:
        return None
    return combined
