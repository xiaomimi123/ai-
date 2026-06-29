"""一次性数据清理（v1.8）：删除历史"未上传任何佐证材料"的 Finding。

背景：v1.7（commit 40c7e76）已让 orchestrator 不再为无材料指标写
"完整性问题：未上传任何佐证材料"finding，但**老任务里这条历史数据仍残留**。
本脚本把它们清空，让老任务的审计页面/工作底稿也回到 v1.7 之后的语义。

幂等：跑两次结果一样，第二次 deleted=0。

用法：
    docker compose exec backend python -m app.scripts.clean_legacy_no_material_findings
    # 或在测试中：from app.scripts.clean_legacy_no_material_findings import run
    #            result = run(db)
"""
from __future__ import annotations

from typing import Dict

from sqlalchemy.orm import Session

from app.models import Finding


# v1.7 之前 orchestrator 写入的固定文案（commit 40c7e76 diff 里的 description）
LEGACY_DESC_NEEDLE = "未上传任何佐证材料"


def run(db: Session, dry_run: bool = False) -> Dict[str, int]:
    """删除所有 description 含 `LEGACY_DESC_NEEDLE` 的 Finding。

    返回 {"matched": N, "deleted": M}：dry_run=True 时 matched=M 但 deleted=0。
    """
    matched = (
        db.query(Finding)
        .filter(Finding.description.like(f"%{LEGACY_DESC_NEEDLE}%"))
        .all()
    )
    n = len(matched)
    if dry_run or n == 0:
        return {"matched": n, "deleted": 0}
    for f in matched:
        db.delete(f)
    db.commit()
    return {"matched": n, "deleted": n}


if __name__ == "__main__":
    import sys

    from app.models import SessionLocal

    dry = "--dry-run" in sys.argv
    db = SessionLocal()
    try:
        result = run(db, dry_run=dry)
        mode = "(dry-run)" if dry else ""
        print(
            f"v1.8 清理 {mode}：命中 {result['matched']} 条，"
            f"已删除 {result['deleted']} 条"
        )
    finally:
        db.close()
