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


def apply(db: Session, items: List[Dict]) -> Dict:
    """按 indicator_code UPDATE name + required_materials；I-55 单独改名。

    返回 {updated: int, skipped: list[str], i55_renamed: bool}
    """
    updated = 0
    skipped: List[str] = []
    for it in items:
        code = it["indicator_code"]
        ind = db.query(Indicator).filter_by(indicator_code=code).first()
        if not ind:
            skipped.append(code)
            continue
        ind.name = it["name"]
        ind.required_materials = json.dumps(
            it["required_materials"], ensure_ascii=False,
        )
        updated += 1

    # I-55 单独改名：典型 items 不含 I-55（它在 txt 里没有），所以这里的 rename
    # 不计入 updated 计数。调用方需检查 i55_renamed 才能知道兜底指标改没改。
    i55 = db.query(Indicator).filter_by(indicator_code="I-55").first()
    if i55:
        i55.name = "未分类/人工复核"
        # 兜底指标，required_materials 留空
    db.commit()
    return {
        "updated": updated,
        "skipped": skipped,
        "i55_renamed": bool(i55),
    }


if __name__ == "__main__":
    # 仅在容器内执行：docker compose exec backend python -m app.seeds.load_indicators_54_v2
    # 默认 txt 路径 /app/app/seeds/indicators_54_v2.txt 是容器内路径，
    # 本机直接 python -m ... 需显式传 txt 路径作为 sys.argv[1]
    import sys
    txt_path = (
        sys.argv[1] if len(sys.argv) > 1
        else "/app/app/seeds/indicators_54_v2.txt"
    )
    items = parse_new_indicators(txt_path)
    print(f"解析到 {len(items)} 项新指标")
    with SessionLocal() as db:
        result = apply(db, items)
    print(
        f"更新 {result['updated']} / 跳过 {result['skipped']} "
        f"/ I-55 改名 {result['i55_renamed']}"
    )
