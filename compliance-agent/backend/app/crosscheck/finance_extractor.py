"""财务链字段抽取（§3.5）。

按报表关键标签提取金额。正则优先，简单稳定。
"""
from __future__ import annotations

import re
from typing import Optional

from app.crosscheck.schemas import (
    AssetReportFields,
    FinalAccountFields,
    FinanceFields,
)
from app.parsers.base import ParsedDocument
from app.rules.utils import parse_arabic_amount, parse_cn_amount

_CN_AMOUNT_RUN = re.compile(r"[零壹贰叁肆伍陆柒捌玖拾佰仟万亿圆元角分整]{3,}")
_YEAR_RE = re.compile(r"(20\d{2}|19\d{2})\s*年")


def _label_amount(text: str, label_pattern: str) -> Optional[float]:
    """通用：在标签后 80 字符内寻找金额（大写优先，再阿拉伯）。

    支持金额带「万元」「亿元」单位，自动换算。
    """
    m = re.search(label_pattern + r"[^:：\n]{0,15}[:：]?[ \t]*", text)
    if not m:
        return None
    snippet = text[m.end(): m.end() + 100]

    # 大写金额优先
    cn = _CN_AMOUNT_RUN.search(snippet)
    if cn:
        val = parse_cn_amount(cn.group())
        if val:
            return val

    # 阿拉伯数字 + 单位
    num_m = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(亿元|万元|元)?", snippet)
    if not num_m:
        return None
    try:
        val = float(num_m.group(1).replace(",", ""))
    except ValueError:
        return None
    unit = num_m.group(2)
    if unit == "万元":
        val *= 10000
    elif unit == "亿元":
        val *= 100000000
    return round(val, 2)


def _year(text: str) -> Optional[int]:
    m = _YEAR_RE.search(text[:500]) or _YEAR_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def extract_finance(doc: ParsedDocument) -> FinanceFields:
    text = doc.text
    return FinanceFields(
        year=_year(text),
        total_assets=_label_amount(text, r"资产合计|资产总计|资产总额"),
        total_liabilities=_label_amount(text, r"负债合计|负债总计"),
        total_net_assets=_label_amount(text, r"净资产合计|净资产总计"),
        total_income=_label_amount(text, r"收入合计|本年收入合计"),
        total_expense=_label_amount(text, r"支出合计|本年支出合计|费用合计"),
    )


def extract_final_account(doc: ParsedDocument) -> FinalAccountFields:
    text = doc.text
    return FinalAccountFields(
        year=_year(text),
        total_income=_label_amount(text, r"决算收入合计|收入决算数|收入合计"),
        total_expense=_label_amount(text, r"决算支出合计|支出决算数|支出合计"),
        budget_total=_label_amount(text, r"预算总额|年初预算数|预算数"),
        three_public_total=_label_amount(text, r"三公经费合计|三公经费支出合计|三公经费"),
    )


def extract_asset_report(doc: ParsedDocument) -> AssetReportFields:
    text = doc.text
    return AssetReportFields(
        year=_year(text),
        total_assets=_label_amount(text, r"资产总额|资产合计|总资产"),
        fixed_assets=_label_amount(text, r"固定资产"),
    )
