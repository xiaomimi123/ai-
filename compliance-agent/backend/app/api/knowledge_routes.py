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
from app.parsers.dispatcher import UnsupportedFormatError
from app.services import extract_service

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


def _normalize_indicator_item(d: dict) -> dict:
    """统一字段，确保 required_materials 是字符串 JSON。"""
    req_mats = d.get("required_materials", [])
    if isinstance(req_mats, list):
        req_mats_str = json.dumps(req_mats, ensure_ascii=False)
    else:
        req_mats_str = req_mats or "[]"
    return {
        "indicator_code": str(d.get("indicator_code", "")).strip(),
        "level": d.get("level", "单位") or "单位",
        "category": d.get("category", "") or "",
        "subcategory": d.get("subcategory", "") or "",
        "name": d.get("name", "") or "",
        "description": d.get("description", "") or "",
        "max_score": float(d.get("max_score", 0) or 0),
        "deduct_rules": d.get("deduct_rules", "") or "",
        "common_deductions": d.get("common_deductions", "") or "",
        "required_materials": req_mats_str,
    }


def _persist_indicators(db: Session, items: list[dict], admin: User) -> dict:
    """批量入库，按 code 去重。"""
    created, skipped, errors = 0, 0, []
    for item in items:
        try:
            norm = _normalize_indicator_item(item)
            if not norm["indicator_code"] or not norm["name"]:
                skipped += 1
                continue
            if db.query(Indicator).filter(
                Indicator.indicator_code == norm["indicator_code"]
            ).first():
                skipped += 1
                continue
            db.add(Indicator(**norm))
            created += 1
        except Exception as exc:
            errors.append(f"{item.get('indicator_code') or '?'}: {exc}")
            skipped += 1
    if created:
        log_action(db, admin, "indicator.import",
                   detail=f"创建 {created}，跳过 {skipped}")
    db.commit()
    return {"created": created, "skipped": skipped, "errors": errors}


@indicators_router.post("/import-from-file", response_model=dict)
async def import_indicators_from_file(
    file: UploadFile = File(...),
    dry_run: bool = Query(False, description="true 仅返回预览不入库"),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """从 PDF / Word / Excel / TXT / JSON 自动解析并抽取评价指标。

    - 若文件为 .json：直接按数组解析
    - 其它格式：LLM 抽取（缺 key 时回退正则启发式）
    - dry_run=true 时只返回 preview，不写库
    """
    raw = await file.read()
    file_name = file.filename or "untitled"
    note = ""
    items: list[dict] = []

    if file_name.lower().endswith(".json"):
        try:
            items = json.loads(raw.decode("utf-8"))
            if not isinstance(items, list):
                raise HTTPException(400, "JSON 顶层必须为数组")
            note = f"JSON 直传（共 {len(items)} 条）"
        except json.JSONDecodeError as exc:
            raise HTTPException(400, f"JSON 解析失败：{exc}")
    else:
        try:
            items, note = extract_service.extract_indicators(db, file_name, raw)
        except UnsupportedFormatError as exc:
            raise HTTPException(400, str(exc))
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    if not items:
        return {
            "preview": [],
            "created": 0,
            "skipped": 0,
            "errors": [],
            "note": note + "（未抽到任何条目，请检查文件格式或填入 LLM API Key 重试）",
        }

    preview_items = [_normalize_indicator_item(d) for d in items[:50]]
    if dry_run:
        return {
            "preview": preview_items,
            "total": len(items),
            "note": note,
        }

    result = _persist_indicators(db, items, admin)
    result["preview"] = preview_items[:10]
    result["note"] = note
    return result


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


def _normalize_check_item(d: dict) -> dict:
    apps = d.get("applicable_indicators", [])
    pats = d.get("common_patterns", [])
    kws = d.get("keywords", [])
    return {
        "item_code": str(d.get("item_code", "")).strip(),
        "dimension": d.get("dimension", "") or "",
        "subcategory": d.get("subcategory", "") or "",
        "description": d.get("description", "") or "",
        "applicable_indicators": json.dumps(apps if isinstance(apps, list) else [], ensure_ascii=False),
        "risk_level": d.get("risk_level", "中") or "中",
        "common_patterns": json.dumps(pats if isinstance(pats, list) else [], ensure_ascii=False),
        "check_method": d.get("check_method", "llm") or "llm",
        "keywords": json.dumps(kws if isinstance(kws, list) else [], ensure_ascii=False),
    }


def _persist_check_items(db: Session, items: list[dict], admin: User) -> dict:
    created, skipped, errors = 0, 0, []
    for d in items:
        try:
            norm = _normalize_check_item(d)
            if not norm["item_code"] or not norm["description"]:
                skipped += 1
                continue
            if db.query(CheckItem).filter(CheckItem.item_code == norm["item_code"]).first():
                skipped += 1
                continue
            db.add(CheckItem(**norm))
            created += 1
        except Exception as exc:
            errors.append(f"{d.get('item_code') or '?'}: {exc}")
            skipped += 1
    if created:
        log_action(db, admin, "check_item.import",
                   detail=f"创建 {created}，跳过 {skipped}")
    db.commit()
    return {"created": created, "skipped": skipped, "errors": errors}


@checkitems_router.post("/import-from-file", response_model=dict)
async def import_check_items_from_file(
    file: UploadFile = File(...),
    dry_run: bool = Query(False, description="true 仅返回预览不入库"),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """从 PDF/Word/Excel/TXT/JSON 自动解析并抽取问题清单条目。"""
    raw = await file.read()
    file_name = file.filename or "untitled"
    note = ""
    items: list[dict] = []

    if file_name.lower().endswith(".json"):
        try:
            items = json.loads(raw.decode("utf-8"))
            if not isinstance(items, list):
                raise HTTPException(400, "JSON 顶层必须为数组")
            note = f"JSON 直传（共 {len(items)} 条）"
        except json.JSONDecodeError as exc:
            raise HTTPException(400, f"JSON 解析失败：{exc}")
    else:
        try:
            items, note = extract_service.extract_check_items(db, file_name, raw)
        except UnsupportedFormatError as exc:
            raise HTTPException(400, str(exc))
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    if not items:
        return {
            "preview": [],
            "created": 0,
            "skipped": 0,
            "errors": [],
            "note": note + "（未抽到任何条目）",
        }

    preview_items = [_normalize_check_item(d) for d in items[:50]]
    if dry_run:
        return {
            "preview": preview_items,
            "total": len(items),
            "note": note,
        }

    result = _persist_check_items(db, items, admin)
    result["preview"] = preview_items[:10]
    result["note"] = note
    return result


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
