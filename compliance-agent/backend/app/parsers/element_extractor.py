"""key_elements 自动抽取器（v3 §3.3）。

根据文本内容识别：公章 / 签字 / 发文日期 / 文件编号 / 草稿标记 / 红头文件等。
所有判断都是文本层面的关键词匹配，无法检测图片层面的 PS/篡改（v3 §六明确边界）。
"""
from __future__ import annotations

import re
from typing import Optional

from app.parsers.base import KeyElements

# ----- 公章 / 签字 关键词 -----
_SEAL_KEYWORDS = (
    "（盖章）", "(盖章)", "盖章", "公章", "印章", "签章",
    "（印）", "（公章）", "(公章)", "已加盖公章",
)
_SIGNATURE_KEYWORDS = (
    "签字", "签发", "签名", "（签字）", "(签字)",
    "法定代表人", "单位负责人", "分管领导", "经办人",
)

# ----- 红头文件标记 -----
_RED_HEADER_KEYWORDS = (
    "印发", "发文机关", "中共", "人民政府", "财政厅", "财政局",
    "委员会文件", "政府文件",
)

# ----- 草稿 / 征求意见稿 -----
_DRAFT_KEYWORDS = (
    "草稿", "征求意见稿", "讨论稿", "送审稿", "审议稿",
    "（草案）", "(草案)", "草案", "白条",
)

# ----- 文件编号：XXX发〔2025〕5号 / 财办发〔2025〕12号 / XX字[2025]X号 -----
_DOC_NUMBER_RE = re.compile(
    r"([一-龥A-Za-z]{1,15})\s*[〔\[【（]\s*(\d{4})\s*[〕\]】）]\s*第?\s*\d+\s*号"
)

# ----- 日期匹配 -----
_DATE_RES = [
    re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"),
    re.compile(r"(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})"),
    # 二〇二五年三月十五日
    re.compile(r"([一二三四五六七八九〇○零]{4})\s*年\s*[一二三四五六七八九十]{1,3}\s*月\s*[一二三四五六七八九十]{1,3}\s*日"),
]

# 中文数字 → 阿拉伯
_CN_DIGITS = {"〇": 0, "○": 0, "零": 0,
              "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}


def _parse_cn_year(cn: str) -> Optional[int]:
    if len(cn) != 4:
        return None
    try:
        digits = [_CN_DIGITS[c] for c in cn]
    except KeyError:
        return None
    return digits[0] * 1000 + digits[1] * 100 + digits[2] * 10 + digits[3]


def _extract_date(text: str) -> tuple[str, Optional[int]]:
    """优先返回正文中靠后的（落款日期通常在末尾）。"""
    candidates = []
    for pat in _DATE_RES:
        for m in pat.finditer(text):
            candidates.append((m.start(), m))
    if not candidates:
        return "", None
    # 文档末尾的日期更可能是落款日期
    candidates.sort(key=lambda x: x[0])
    last = candidates[-1][1]
    g = last.group(1)
    if g.isdigit():
        year = int(g)
        month = int(last.group(2))
        day = int(last.group(3))
        return f"{year:04d}-{month:02d}-{day:02d}", year
    # 中文年
    year = _parse_cn_year(g)
    if year is None:
        return "", None
    return f"{year:04d}-01-01", year


def extract_key_elements(text: str, file_name: str = "") -> KeyElements:
    """从全文文本（可附文件名提示）抽取关键要素。"""
    elements = KeyElements()
    if not text:
        return elements

    # 公章 / 签字
    elements.has_official_seal = any(k in text for k in _SEAL_KEYWORDS)
    elements.has_signature = any(k in text for k in _SIGNATURE_KEYWORDS)
    elements.has_red_header = any(k in text for k in _RED_HEADER_KEYWORDS)

    # 草稿 / 白条
    head = text[:500] + " " + (file_name or "")
    elements.is_draft = any(k in head for k in _DRAFT_KEYWORDS)

    # 文件编号
    dm = _DOC_NUMBER_RE.search(text)
    if dm:
        elements.document_number = dm.group(0).strip()

    # 日期
    date_str, year = _extract_date(text)
    elements.issue_date = date_str
    elements.issue_year = year

    # 从文件编号补充年份（〔2025〕中的 2025）
    if elements.issue_year is None and dm:
        try:
            elements.issue_year = int(dm.group(2))
        except ValueError:
            pass

    return elements
