"""刚性规则用到的确定性工具：定位、金额大小写解析。"""
from __future__ import annotations

import re
from typing import Optional

from app.core.domain import Location
from app.parsers.base import ParsedDocument


def locate(doc: ParsedDocument, needle: str) -> Location:
    """在解析块中查找包含 needle 的位置，返回 Location。找不到则返回文件级位置。"""
    file_name = doc.metadata.get("file_name", "")
    for block in doc.page_blocks:
        if needle and needle in block.content:
            return Location(file_name=file_name, page=block.page, section=block.section)
    return Location(file_name=file_name)


# ---------- 中文大写金额解析 ----------
_CN_DIGIT = {
    "零": 0, "壹": 1, "贰": 2, "叁": 3, "肆": 4,
    "伍": 5, "陆": 6, "柒": 7, "捌": 8, "玖": 9,
    # 兼容小写
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "两": 2,
}
_CN_UNIT = {"拾": 10, "佰": 100, "仟": 1000, "十": 10, "百": 100, "千": 1000}
_CN_SECTION = {"万": 10000, "亿": 100000000}
_CN_DECIMAL = {"角": 0.1, "分": 0.01}


def parse_cn_amount(text: str) -> Optional[float]:
    """解析「人民币壹拾万元整」「壹佰贰拾叁元肆角伍分」等大写金额为数值。

    解析失败返回 None。仅做尽力而为，足以支撑「大小写一致性」校验。
    """
    if not text:
        return None
    s = re.sub(r"(人民币|RMB|¥|元整|整|元|圆)", lambda m: "元" if m.group() in ("元", "圆", "元整") else "", text)
    s = s.replace("圆", "元")
    if not any(c in s for c in list(_CN_DIGIT) + list(_CN_UNIT) + ["元"]):
        return None

    total = 0.0
    section = 0.0
    number = 0
    i = 0
    has_any = False
    while i < len(s):
        ch = s[i]
        if ch in _CN_DIGIT:
            number = _CN_DIGIT[ch]
            has_any = True
        elif ch in _CN_UNIT:
            section += (number or 1) * _CN_UNIT[ch]
            number = 0
            has_any = True
        elif ch in _CN_SECTION:
            section += number
            total += section * _CN_SECTION[ch]
            section = 0.0
            number = 0
            has_any = True
        elif ch == "元":
            section += number
            total += section
            section = 0.0
            number = 0
        elif ch in _CN_DECIMAL:
            total += number * _CN_DECIMAL[ch]
            number = 0
            has_any = True
        i += 1
    total += section + number  # 收尾（无「元」字时）
    return round(total, 2) if has_any else None


_NUM_AMOUNT_RE = re.compile(r"(?:¥|￥|RMB|人民币)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*元?")


def parse_arabic_amount(text: str) -> Optional[float]:
    """从形如 '¥100,000.00' / '100000元' 中提取数值。"""
    m = _NUM_AMOUNT_RE.search(text or "")
    if not m:
        return None
    try:
        return round(float(m.group(1).replace(",", "")), 2)
    except ValueError:
        return None
