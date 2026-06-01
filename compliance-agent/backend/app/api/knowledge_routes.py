"""知识库管理 API（v3 §3.1、§3.2）：评价指标库 + 问题清单库。

权限：超级管理员可增删改；审查员可读；其他角色无权限。
"""
from __future__ import annotations

import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session

from app.api.schemas import (
    CheckItemIn,
    CheckItemOut,
    IndicatorIn,
    IndicatorOut,
)
from app.core.auth import get_current_user, log_action, require_admin, require_auditor
from app.models import CheckItem, Finding, Indicator, Material, User, get_db

indicators_router = APIRouter(prefix="/api/indicators", tags=["knowledge:indicators"])
checkitems_router = APIRouter(prefix="/api/check-items", tags=["knowledge:check-items"])


# ============================================================
# 评价指标库
# ============================================================
@indicators_router.get("", response_model=List[IndicatorOut])
def list_indicators(
    level: Optional[str] = Query(None, description="单位 / 部门"),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_auditor),
):
    q = db.query(Indicator).order_by(Indicator.indicator_code)
    if level:
        q = q.filter(Indicator.level == level)
    if category:
        q = q.filter(Indicator.category == category)
    return q.all()


@indicators_router.post("", response_model=IndicatorOut)
def create_indicator(req: IndicatorIn,
                     db: Session = Depends(get_db),
                     admin: User = Depends(require_admin)):
    if db.query(Indicator).filter(Indicator.indicator_code == req.indicator_code).first():
        raise HTTPException(400, f"指标 {req.indicator_code} 已存在")
    ind = Indicator(
        indicator_code=req.indicator_code,
        level=req.level,
        category=req.category,
        subcategory=req.subcategory,
        name=req.name,
        description=req.description,
        max_score=req.max_score,
        deduct_rules=req.deduct_rules,
        common_deductions=req.common_deductions,
        required_materials=json.dumps(req.required_materials, ensure_ascii=False),
    )
    db.add(ind); db.flush()
    log_action(db, admin, "indicator.create",
               target_type="indicator", target_id=ind.id,
               detail=f"{ind.indicator_code} {ind.name}")
    db.commit(); db.refresh(ind)
    return ind


@indicators_router.put("/{indicator_id}", response_model=IndicatorOut)
def update_indicator(indicator_id: int, req: IndicatorIn,
                     db: Session = Depends(get_db),
                     admin: User = Depends(require_admin)):
    ind = db.get(Indicator, indicator_id)
    if not ind:
        raise HTTPException(404, "指标不存在")
    for k, v in req.dict().items():
        if k == "required_materials":
            ind.required_materials = json.dumps(v, ensure_ascii=False)
        else:
            setattr(ind, k, v)
    log_action(db, admin, "indicator.update",
               target_type="indicator", target_id=ind.id,
               detail=f"{ind.indicator_code}")
    db.commit(); db.refresh(ind)
    return ind


@indicators_router.delete("/{indicator_id}")
def delete_indicator(indicator_id: int,
                     db: Session = Depends(get_db),
                     admin: User = Depends(require_admin)):
    ind = db.get(Indicator, indicator_id)
    if not ind:
        raise HTTPException(404, "指标不存在")
    # 引用检查：有材料或 Finding 引用时不允许删除
    in_use_materials = db.query(Material).filter(Material.indicator_id == indicator_id).count()
    in_use_findings = db.query(Finding).filter(Finding.indicator_id == indicator_id).count()
    if in_use_materials or in_use_findings:
        raise HTTPException(
            400,
            f"该指标已被引用：{in_use_materials} 份材料 / {in_use_findings} 条核查发现，无法删除。"
            f"如需移除，请先删除引用它的核查任务。",
        )
    code = ind.indicator_code
    db.delete(ind)
    log_action(db, admin, "indicator.delete",
               target_type="indicator", target_id=indicator_id,
               detail=code)
    db.commit()
    return {"status": "ok"}


@indicators_router.post("/import", response_model=dict)
async def import_indicators(file: UploadFile = File(...),
                            db: Session = Depends(get_db),
                            admin: User = Depends(require_admin)):
    """批量导入指标（JSON 数组）。已存在的按 indicator_code 跳过。"""
    raw = await file.read()
    try:
        items = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(400, f"JSON 解析失败：{exc}")
    if not isinstance(items, list):
        raise HTTPException(400, "JSON 顶层必须为数组")
    created, skipped = 0, 0
    for item in items:
        code = item.get("indicator_code")
        if not code:
            skipped += 1
            continue
        if db.query(Indicator).filter(Indicator.indicator_code == code).first():
            skipped += 1
            continue
        req_mats = item.get("required_materials", [])
        if isinstance(req_mats, list):
            req_mats = json.dumps(req_mats, ensure_ascii=False)
        ind = Indicator(
            indicator_code=code,
            level=item.get("level", "单位"),
            category=item.get("category", ""),
            subcategory=item.get("subcategory", ""),
            name=item.get("name", ""),
            description=item.get("description", ""),
            max_score=float(item.get("max_score", 0)),
            deduct_rules=item.get("deduct_rules", ""),
            common_deductions=item.get("common_deductions", ""),
            required_materials=req_mats if isinstance(req_mats, str) else "[]",
        )
        db.add(ind)
        created += 1
    log_action(db, admin, "indicator.import",
               detail=f"创建 {created}，跳过 {skipped}")
    db.commit()
    return {"created": created, "skipped": skipped}


# ============================================================
# 问题清单库
# ============================================================
@checkitems_router.get("", response_model=List[CheckItemOut])
def list_check_items(
    dimension: Optional[str] = Query(None),
    method: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_auditor),
):
    q = db.query(CheckItem).filter(CheckItem.is_active == True).order_by(CheckItem.item_code)
    if dimension:
        q = q.filter(CheckItem.dimension == dimension)
    if method:
        q = q.filter(CheckItem.check_method == method)
    return q.all()


@checkitems_router.post("", response_model=CheckItemOut)
def create_check_item(req: CheckItemIn,
                      db: Session = Depends(get_db),
                      admin: User = Depends(require_admin)):
    if db.query(CheckItem).filter(CheckItem.item_code == req.item_code).first():
        raise HTTPException(400, f"问题清单条目 {req.item_code} 已存在")
    item = CheckItem(
        item_code=req.item_code,
        dimension=req.dimension,
        subcategory=req.subcategory,
        description=req.description,
        applicable_indicators=json.dumps(req.applicable_indicators, ensure_ascii=False),
        risk_level=req.risk_level,
        common_patterns=json.dumps(req.common_patterns, ensure_ascii=False),
        check_method=req.check_method,
        keywords=json.dumps(req.keywords, ensure_ascii=False),
    )
    db.add(item); db.flush()
    log_action(db, admin, "check_item.create",
               target_type="check_item", target_id=item.id,
               detail=f"{item.item_code} {item.dimension}")
    db.commit(); db.refresh(item)
    return item


@checkitems_router.put("/{item_id}", response_model=CheckItemOut)
def update_check_item(item_id: int, req: CheckItemIn,
                      db: Session = Depends(get_db),
                      admin: User = Depends(require_admin)):
    item = db.get(CheckItem, item_id)
    if not item:
        raise HTTPException(404, "条目不存在")
    item.dimension = req.dimension
    item.subcategory = req.subcategory
    item.description = req.description
    item.applicable_indicators = json.dumps(req.applicable_indicators, ensure_ascii=False)
    item.risk_level = req.risk_level
    item.common_patterns = json.dumps(req.common_patterns, ensure_ascii=False)
    item.check_method = req.check_method
    item.keywords = json.dumps(req.keywords, ensure_ascii=False)
    log_action(db, admin, "check_item.update",
               target_type="check_item", target_id=item.id)
    db.commit(); db.refresh(item)
    return item


@checkitems_router.delete("/{item_id}")
def delete_check_item(item_id: int,
                      db: Session = Depends(get_db),
                      admin: User = Depends(require_admin)):
    item = db.get(CheckItem, item_id)
    if not item:
        raise HTTPException(404, "条目不存在")
    item.is_active = False  # 软删
    log_action(db, admin, "check_item.delete",
               target_type="check_item", target_id=item_id)
    db.commit()
    return {"status": "ok"}


@checkitems_router.post("/import", response_model=dict)
async def import_check_items(file: UploadFile = File(...),
                             db: Session = Depends(get_db),
                             admin: User = Depends(require_admin)):
    raw = await file.read()
    try:
        items = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(400, f"JSON 解析失败：{exc}")
    if not isinstance(items, list):
        raise HTTPException(400, "JSON 顶层必须为数组")
    created, skipped = 0, 0
    for d in items:
        code = d.get("item_code")
        if not code:
            skipped += 1
            continue
        if db.query(CheckItem).filter(CheckItem.item_code == code).first():
            skipped += 1
            continue
        item = CheckItem(
            item_code=code,
            dimension=d.get("dimension", ""),
            subcategory=d.get("subcategory", ""),
            description=d.get("description", ""),
            applicable_indicators=json.dumps(d.get("applicable_indicators", []), ensure_ascii=False),
            risk_level=d.get("risk_level", "中"),
            common_patterns=json.dumps(d.get("common_patterns", []), ensure_ascii=False),
            check_method=d.get("check_method", "llm"),
            keywords=json.dumps(d.get("keywords", []), ensure_ascii=False),
        )
        db.add(item)
        created += 1
    log_action(db, admin, "check_item.import",
               detail=f"创建 {created}，跳过 {skipped}")
    db.commit()
    return {"created": created, "skipped": skipped}
