"""文档自动分类：先看文件名，再看内容关键词。

返回 9 大分类之一（§3.1），招采类还顺带返回子类。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.parsers.base import ParsedDocument
from app.rules.procurement import detect_subtype as detect_proc_subtype

# 关键词权重表：每命中一次加权
_CATEGORY_KEYWORDS: dict[str, list[tuple[str, int]]] = {
    "合同": [("合同", 3), ("协议", 2), ("甲方", 2), ("乙方", 2),
            ("付款方式", 2), ("违约责任", 2), ("合同期限", 2)],
    "采购招标": [("招标文件", 4), ("招标公告", 4), ("投标文件", 4),
                ("投标函", 3), ("评标报告", 4), ("评标委员会", 3),
                ("中标候选人", 3), ("最高限价", 2)],
    "内部制度": [("管理办法", 3), ("管理规定", 3), ("实施细则", 3),
                ("总则", 2), ("附则", 2), ("第一章", 2),
                ("自发布之日起施行", 3), ("自印发之日起施行", 3)],
    "内控报告": [("内部控制报告", 5), ("内控报告", 5),
                ("六大业务", 2), ("内控缺陷", 2),
                ("内部控制自我评价", 4)],
    "财务报告": [("财务报告", 5), ("资产负债表", 3),
                ("收入支出表", 3), ("现金流量表", 3)],
    "决算报告": [("决算报告", 5), ("部门决算", 4), ("决算总表", 3),
                ("决算说明", 3), ("收入决算", 2), ("支出决算", 2)],
    "国有资产报告": [("国有资产报告", 5), ("资产报告", 4),
                    ("资产总额", 2), ("资产盘点", 3),
                    ("固定资产", 2), ("资产管理", 2)],
    "绩效评价报告": [("绩效评价报告", 5), ("绩效评价", 4),
                    ("产出指标", 3), ("效益指标", 3),
                    ("满意度指标", 3), ("综合得分", 2), ("评价等次", 2)],
}

# 文件名直接命中的关键词（优先级最高）
_FILENAME_HINTS: list[tuple[str, str]] = [
    ("招标", "采购招标"),
    ("投标", "采购招标"),
    ("评标", "采购招标"),
    ("合同", "合同"),
    ("协议", "合同"),
    ("管理办法", "内部制度"),
    ("管理规定", "内部制度"),
    ("实施细则", "内部制度"),
    ("内控", "内控报告"),
    ("内部控制", "内控报告"),
    ("决算", "决算报告"),
    ("财务报告", "财务报告"),
    ("财务情况说明", "财务报告"),
    ("资产报告", "国有资产报告"),
    ("国有资产", "国有资产报告"),
    ("绩效", "绩效评价报告"),
]


@dataclass
class Classification:
    category: str
    subcategory: str = ""
    confidence: float = 0.0      # 0..1，简单评分
    method: str = ""             # filename | content | fallback


def classify(file_name: str, parsed: Optional[ParsedDocument]) -> Classification:
    # 1) 文件名直击
    fn = file_name or ""
    for hint, cat in _FILENAME_HINTS:
        if hint in fn:
            sub = ""
            if cat == "采购招标":
                # 招标/投标/评标 顺序在 _FILENAME_HINTS 中，已是子类名
                sub = hint
            return Classification(category=cat, subcategory=sub,
                                  confidence=0.9, method="filename")

    # 2) 内容关键词打分
    if parsed is not None and parsed.text:
        text = parsed.text[:5000]  # 看前 5000 字够用
        scores: dict[str, int] = {}
        for cat, kws in _CATEGORY_KEYWORDS.items():
            scores[cat] = sum(w * text.count(kw) for kw, w in kws)
        best = max(scores, key=scores.get)
        if scores[best] >= 4:  # 阈值：至少命中两次中频词
            sub = ""
            if best == "采购招标":
                sub_detected = detect_proc_subtype(text)
                if sub_detected != "未知":
                    sub = sub_detected
            total = sum(scores.values())
            return Classification(
                category=best, subcategory=sub,
                confidence=round(scores[best] / max(total, 1), 2),
                method="content",
            )

    # 3) 兜底
    return Classification(category="其他佐证资料", confidence=0.0, method="fallback")
