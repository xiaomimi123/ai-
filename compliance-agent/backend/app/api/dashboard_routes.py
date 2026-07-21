"""v2.13: 工作台"单位核查进度总览"端点。

5 档互斥统计：
- no_task: task_count == 0
- completed: finalized_count == task_count（含 0 材料也算完成）
- has_task_no_material: material_count == 0（未完成前提下）
- in_progress_with_material: 其它

判定优先级：no_task > completed > has_task_no_material > in_progress_with_material。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, distinct, func
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.models import AuditTask, AuditUnit, Material, User, get_db, Finding
from app.services.audit_service import _VALID_FINDING_TYPES

dashboard_router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _base_subquery(db: Session):
    """每单位聚合 (task_count, material_count, finalized_count) 子查询。"""
    return (
        db.query(
            AuditUnit.id.label("unit_id"),
            AuditUnit.name.label("unit_name"),
            func.count(distinct(AuditTask.id)).label("task_count"),
            func.count(Material.id).label("material_count"),
            func.count(distinct(case(
                (AuditTask.status == "finalized", AuditTask.id),
            ))).label("finalized_count"),
        )
        .outerjoin(AuditTask, AuditTask.unit_id == AuditUnit.id)
        .outerjoin(Material, Material.task_id == AuditTask.id)
        .group_by(AuditUnit.id, AuditUnit.name)
    ).subquery()


def _categorize(row) -> str:
    """按判定优先级返分档字符串。"""
    if row.task_count == 0:
        return "no_task"
    if row.finalized_count == row.task_count:
        return "completed"
    if row.material_count == 0:
        return "has_task_no_material"
    return "in_progress_with_material"


_VALID_DETAIL_CATEGORIES = {
    "no_task", "has_task_no_material", "in_progress_with_material",
}


@dashboard_router.get("/unit-stats/summary")
def unit_stats_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """5 档单位数统计，一次 SQL 聚合。"""
    sub = _base_subquery(db)
    rows = db.query(sub).all()
    counts = {
        "total": 0,
        "no_task": 0,
        "has_task_no_material": 0,
        "in_progress_with_material": 0,
        "completed": 0,
    }
    for r in rows:
        counts["total"] += 1
        counts[_categorize(r)] += 1
    return counts


@dashboard_router.get("/unit-stats/detail")
def unit_stats_detail(
    category: str = Query(
        ..., description="no_task / has_task_no_material / in_progress_with_material",
    ),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """按 category 返单位列表。completed 不提供 detail。"""
    if category not in _VALID_DETAIL_CATEGORIES:
        raise HTTPException(400, f"unknown category: {category}")

    sub = _base_subquery(db)
    rows = db.query(sub).all()

    out: list[dict] = []
    for r in rows:
        if _categorize(r) != category:
            continue
        out.append({
            "id": r.unit_id,
            "name": r.unit_name,
            "total_tasks": int(r.task_count),
            "finalized_tasks": int(r.finalized_count),
            "material_count": int(r.material_count),
        })
    out.sort(key=lambda x: x["name"])
    return out


@dashboard_router.get("/region-finding-stats")
def region_finding_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """每地区 × 每 finding_type 的 count 矩阵 + 每地区单位数。

    返回：
    {
      "finding_types": ["真实性问题", ...],
      "regions": [
        {"region": "成都市", "unit_count": 403, "counts": {...}, "total": N},
        ...
      ]
    }
    region == "" 的单位完全排除。按 unit_count 降序排。
    """
    # 1. 每地区单位数
    unit_rows = (
        db.query(AuditUnit.region, func.count(AuditUnit.id))
        .filter(AuditUnit.region != "")
        .group_by(AuditUnit.region)
        .all()
    )
    unit_counts = {r: int(n) for r, n in unit_rows}

    # 2. 每地区 × finding_type finding 数
    finding_rows = (
        db.query(
            AuditUnit.region,
            Finding.finding_type,
            func.count(Finding.id),
        )
        .join(AuditTask, AuditTask.unit_id == AuditUnit.id)
        .join(Finding, Finding.task_id == AuditTask.id)
        .filter(AuditUnit.region != "")
        .filter(Finding.finding_type.in_(_VALID_FINDING_TYPES))
        .group_by(AuditUnit.region, Finding.finding_type)
        .all()
    )
    per_region: dict[str, dict[str, int]] = {}
    for region, ftype, n in finding_rows:
        per_region.setdefault(region, {})[ftype] = int(n)

    regions_out = []
    for region, unit_count in unit_counts.items():
        counts = per_region.get(region, {})
        # 补齐所有 6 维（缺的填 0）
        counts_full = {ft: counts.get(ft, 0) for ft in _VALID_FINDING_TYPES}
        total = sum(counts_full.values())
        regions_out.append({
            "region": region,
            "unit_count": unit_count,
            "counts": counts_full,
            "total": total,
        })
    # 按 unit_count 降序（大市在前）
    regions_out.sort(key=lambda x: -x["unit_count"])

    return {
        "finding_types": list(_VALID_FINDING_TYPES),
        "regions": regions_out,
    }
