"""v2.8：修复历史错绑 —— file_name 里含"（X）XX业务控制/*岗位*"但绑到"制度"类指标。

生产实测：52003 份材料错绑，占含"岗位"字样材料的 71%。
根因：v1.8 material_matcher 只按一级子类走 protocol_fallback 到"制度"类指标，
不识别二级文件夹语义。v2.8 matcher 已修，此脚本清理历史存量。

支持：
- --dry-run：只报告不改（默认必须显式加 --apply 才真改）
- 幂等：跑第二次影响 0 行
- 事务保护：分批 500 条 commit，失败自动回滚该批
- 备份：--apply 时先 dump 原 indicator_id 到 /app/data/v28_rebind_backup.sql

用法：
    docker compose exec -T backend python -m app.scripts.rebind_wrong_bindings_v28 --dry-run
    docker compose exec -T backend python -m app.scripts.rebind_wrong_bindings_v28 --apply
"""
from __future__ import annotations

import argparse
import os
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Finding, Indicator, Material


# 匹配 file_name 里"（一）预算业务控制" 到 "（六）合同控制"前缀 → 目标 gangwei 指标 code
SUBCATEGORY_TO_GANGWEI: list[tuple[str, str]] = [
    (r"（一）\s*预算业务控制",       "I-14"),
    (r"（二）\s*收支业务控制",       "I-21"),
    (r"（三）\s*政府采购业务控制",   "I-26"),
    (r"（四）\s*资产控制",           "I-33"),
    (r"（五）\s*建设项目控制",       "I-38"),
    (r"（六）\s*合同控制",           "I-45"),
]

GANGWEI_KEYWORD = re.compile(r"岗位职责说明|岗位分离|岗位职责分工")


def find_wrong_bindings(db: Session) -> list[tuple[Material, Indicator]]:
    """返回 [(material, target_indicator), ...] 需要 rebind 的列表。"""
    zhidu_inds = db.query(Indicator).filter(Indicator.name.contains("制度")).all()
    zhidu_ids = {i.id for i in zhidu_inds}
    code2ind = {i.indicator_code: i for i in db.query(Indicator).all()}

    if not zhidu_ids:
        return []

    candidates = db.query(Material).filter(
        Material.indicator_id.in_(zhidu_ids),
        Material.file_name.contains("岗位"),
    ).all()

    to_fix: list[tuple[Material, Indicator]] = []
    for m in candidates:
        if not GANGWEI_KEYWORD.search(m.file_name or ""):
            continue
        target_code: Optional[str] = None
        for pattern, code in SUBCATEGORY_TO_GANGWEI:
            if re.search(pattern, m.file_name or ""):
                target_code = code
                break
        if not target_code:
            continue
        target_ind = code2ind.get(target_code)
        if target_ind and target_ind.id != m.indicator_id:
            to_fix.append((m, target_ind))
    return to_fix


def dump_backup(to_fix: list[tuple[Material, Indicator]], path: str, db: Session) -> None:
    """把当前 material.id + 原 indicator_id 备份成可回滚 SQL。

    同时备份 finding：rebind 会把 finding.indicator_id 从 old 同步到 new，
    回滚 SQL 里也要写 finding 的反向 UPDATE。

    若目标文件已存在，将其重命名为 path.old-YYYYMMDDHHMMSS 以保留历史备份。
    """
    if os.path.exists(path):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        old_path = f"{path}.old-{stamp}"
        os.rename(path, old_path)

    with open(path, "w") as f:
        f.write(f"-- v2.8 rebind backup {datetime.now(timezone.utc).isoformat()}\n")
        f.write(f"-- 共 {len(to_fix)} 条 material + 对应 finding\n\n")
        for m, target in to_fix:
            old_ind_id = m.indicator_id
            f.write(f"UPDATE materials SET indicator_id = {old_ind_id} WHERE id = {m.id};\n")
            f.write(f"UPDATE findings SET indicator_id = {old_ind_id} "
                    f"WHERE material_id = {m.id} AND indicator_id = {target.id};\n")


def report_impact(to_fix: list[tuple[Material, Indicator]], db: Session) -> None:
    """dry-run 报告：material 数 / finding 数 / 任务数 / 分布。"""
    mat_ids = [m.id for m, _ in to_fix]
    finding_count = (
        db.query(Finding).filter(Finding.material_id.in_(mat_ids)).count()
        if mat_ids else 0
    )
    task_ids = {m.task_id for m, _ in to_fix}
    by_target: Counter = Counter(target.indicator_code for _, target in to_fix)

    print(f"待改绑 material 数: {len(to_fix)}")
    print(f"关联 finding 数:    {finding_count}")
    print(f"涉及任务数:         {len(task_ids)}")
    print()
    print("按目标指标分布:")
    for code, n in sorted(by_target.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {code}: {n}")


def run(db: Session, dry_run: bool, batch: int = 500) -> dict:
    """核心执行函数。返回 {"matched": N, "updated_materials": M, "updated_findings": K}。"""
    to_fix = find_wrong_bindings(db)
    report_impact(to_fix, db)
    print()
    if dry_run:
        print("--dry-run: 不实际修改。加 --apply 真改。")
        return {"matched": len(to_fix), "updated_materials": 0, "updated_findings": 0}

    backup_path = "/app/data/v28_rebind_backup.sql"
    try:
        dump_backup(to_fix, backup_path, db)
        print(f"原绑定已备份到 {backup_path}")
    except OSError as e:
        # 单测/本地跑 /app/data 不存在，退化到 /tmp
        backup_path = "/tmp/v28_rebind_backup.sql"
        dump_backup(to_fix, backup_path, db)
        print(f"原绑定已备份到 {backup_path}（fallback）: {e!s}")

    updated_mats = 0
    updated_findings = 0
    for i in range(0, len(to_fix), batch):
        chunk = to_fix[i:i + batch]
        try:
            for m, target in chunk:
                old_ind_id = m.indicator_id
                f_updated = (
                    db.query(Finding)
                    .filter(Finding.material_id == m.id,
                            Finding.indicator_id == old_ind_id)
                    .update({Finding.indicator_id: target.id},
                            synchronize_session=False)
                )
                updated_findings += f_updated
                m.indicator_id = target.id
                updated_mats += 1
            db.commit()
        except Exception:
            db.rollback()
            raise
        print(f"  已处理 {i + len(chunk)}/{len(to_fix)}")

    print()
    print(f"完成：改绑 material {updated_mats} 条，同步 finding {updated_findings} 条")
    print(f"  回滚：psql -f {backup_path}")
    return {
        "matched": len(to_fix),
        "updated_materials": updated_mats,
        "updated_findings": updated_findings,
    }


if __name__ == "__main__":
    from app.models import SessionLocal

    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="只报告不改")
    group.add_argument("--apply",   action="store_true", help="真改")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        run(db, dry_run=args.dry_run)
    finally:
        db.close()
