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
from app.models import AuditTask, AuditUnit, Material, User, get_db

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
