"""一次性 seed：把桌面底稿 reverse 出的 55 项指标灌入库。

策略：按 indicator_code（I-01..I-55）upsert——
- 已存在：覆盖 name/category/subcategory/max_score/audit_points/deduct_rules
- 不存在：新增
- 老的 8 项（不同 code 前缀）保留不动

用法：
    python -m app.seeds.load_indicators_55              # 默认导入
    python -m app.seeds.load_indicators_55 --replace    # 删除老指标库再导入（V1 期推荐）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from app.models import Indicator, SessionLocal, init_db


def _seed_path() -> Path:
    return Path(__file__).parent / "indicators_55.json"


def load(replace: bool = False) -> tuple[int, int, int]:
    """返回 (created, updated, removed_stale)。

    removed_stale：seed 文件里没有但库里残留的 I-* 指标会被自动清掉
    （仅清没有 Material / Finding / WorksheetRow 引用的，保证幂等）
    """
    init_db()  # 确保表 + 新列已就绪
    items = json.loads(_seed_path().read_text(encoding="utf-8"))
    seed_codes = {it["code"] for it in items}

    from app.models import Material, Finding, WorksheetRow

    db = SessionLocal()
    try:
        if replace:
            db.query(Indicator).delete()
            db.commit()

        created, updated = 0, 0
        for it in items:
            code = it["code"]
            ind = db.query(Indicator).filter(Indicator.indicator_code == code).first()
            payload = {
                "level": "单位",
                "category": it["category"],
                "subcategory": it["subcategory"],
                "name": it["name"],
                "max_score": float(it["max_score"]),
                "audit_points": it["audit_points"],
                "deduct_rules": it["deduction_rule"],
            }
            if ind:
                for k, v in payload.items():
                    setattr(ind, k, v)
                updated += 1
            else:
                db.add(Indicator(indicator_code=code, **payload))
                created += 1
        db.commit()

        # 清除残留：seed 文件已删除但库里仍有的 I-* 指标
        # 跳过有引用的（避免破坏老任务 / 工作底稿）
        removed = 0
        stale = db.query(Indicator).filter(
            Indicator.indicator_code.like("I-%"),
            ~Indicator.indicator_code.in_(seed_codes) if seed_codes else True,
        ).all()
        for ind in stale:
            in_use = (
                db.query(Material).filter(Material.indicator_id == ind.id).count()
                + db.query(Finding).filter(Finding.indicator_id == ind.id).count()
                + db.query(WorksheetRow).filter(WorksheetRow.indicator_id == ind.id).count()
            )
            if in_use:
                # 有引用 → 改名标记 deleted_*，从指标库列表里隐去（用 indicator_code 前缀过滤）
                # 简单做法：跳过，后续手工处理
                continue
            db.delete(ind)
            removed += 1
        db.commit()
        return created, updated, removed
    finally:
        db.close()


if __name__ == "__main__":
    replace = "--replace" in sys.argv
    c, u, r = load(replace=replace)
    print(f"seed 完成：新增 {c} / 更新 {u} / 清残留 {r}"
          + ('（已先清空老指标）' if replace else ''))
