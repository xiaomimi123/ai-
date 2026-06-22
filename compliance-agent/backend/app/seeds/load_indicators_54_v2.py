"""把用户给的 54 项新指标清单批量写入 indicators 表。

策略：按 indicator_code (I-01..I-54) UPDATE name + required_materials；
I-55 改名"未分类/人工复核"；零删除、零插入，保留所有历史关联。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Dict

from sqlalchemy.orm import Session

from app.models import Indicator, SessionLocal


def parse_new_indicators(txt_path: str) -> List[Dict]:
    """解析 txt 文件：奇数行 'NN 新名称'，偶数行 '材料1、材料2、...'。

    支持全角/半角逗号、顿号作分隔符。
    返回 [{indicator_code: 'I-XX', name: str, required_materials: list[str]}]
    """
    lines = [
        l.strip()
        for l in Path(txt_path).read_text(encoding="utf-8-sig").splitlines()
        if l.strip()
    ]
    items: List[Dict] = []
    for i in range(0, len(lines), 2):
        head = lines[i]
        mats_line = lines[i + 1] if i + 1 < len(lines) else ""
        # 拆 'NN 名称'
        parts = head.split(" ", 1)
        if len(parts) < 2:
            continue
        num, name = parts
        # 统一切分符为 '、'
        unified = (
            mats_line
            .replace(",", "、")
            .replace("，", "、")
        )
        materials = [m.strip() for m in unified.split("、") if m.strip()]
        items.append({
            "indicator_code": f"I-{num.zfill(2)}",
            "name": name.strip(),
            "required_materials": materials,
        })
    return items
