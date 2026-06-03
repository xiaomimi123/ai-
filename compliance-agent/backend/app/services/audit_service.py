"""核查任务服务（v3 §3.4、§3.5、§3.7）。

主要职责：
- 创建被检查单位
- 创建任务、上传材料（绑定指标 + 自动抽取 key_elements）
- 触发 AI 核查（异步入队）
- 复核标注（确认/忽略/调整）
- 整改闭环（提交整改 → 销号）
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.auth import log_action
from app.core.config import settings
from app.models import (
    AuditTask,
    AuditUnit,
    Finding,
    Indicator,
    Material,
    User,
)
from app.parsers import parse, SUPPORTED_EXTENSIONS
from app.parsers.dispatcher import UnsupportedFormatError


# ============================================================
# 单位管理
# ============================================================
def create_unit(db: Session, *, name: str, code: str = "", level: str = "单位",
                description: str = "", user: Optional[User] = None) -> AuditUnit:
    if db.query(AuditUnit).filter(AuditUnit.name == name).first():
        raise HTTPException(400, f"单位「{name}」已存在")
    unit = AuditUnit(name=name, code=code, level=level, description=description)
    db.add(unit); db.flush()
    log_action(db, user, "unit.create",
               target_type="unit", target_id=unit.id, detail=f"创建单位 {name}")
    db.commit(); db.refresh(unit)
    return unit


# ============================================================
# 任务
# ============================================================
def create_task(db: Session, *, unit_id: int, name: str, eval_year: int = 2025,
                scope: str = "all",
                selected_indicator_ids: Optional[list] = None,
                user: Optional[User] = None) -> AuditTask:
    unit = db.get(AuditUnit, unit_id)
    if not unit:
        raise HTTPException(404, "单位不存在")
    if scope not in ("all", "selected"):
        raise HTTPException(400, f"无效 scope: {scope}")
    sel_ids = selected_indicator_ids or []
    if scope == "selected" and not sel_ids:
        raise HTTPException(400, "「仅核查选定指标」时必须选择至少一个指标")

    import json as _json
    task = AuditTask(
        unit_id=unit_id, name=name, eval_year=eval_year,
        scope=scope,
        selected_indicator_ids=_json.dumps(sel_ids),
        status="pending", summary="等待上传材料",
        created_by=user.id if user else None,
    )
    db.add(task); db.flush()
    scope_label = "全部指标" if scope == "all" else f"选定 {len(sel_ids)} 个指标"
    log_action(db, user, "task.create",
               target_type="task", target_id=task.id,
               detail=f"为「{unit.name}」创建任务「{name}」（{eval_year}，{scope_label}）")
    db.commit(); db.refresh(task)
    return task


# ============================================================
# 上传材料 + 解析 + 抽取 key_elements
# ============================================================
def upload_material(db: Session, task: AuditTask, *,
                    file_name: str, content: bytes,
                    indicator_id: Optional[int],
                    user: Optional[User] = None) -> Material:
    ext = Path(file_name).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(
            f"不支持的格式 {ext}（支持 {', '.join(SUPPORTED_EXTENSIONS)}）"
        )

    safe = f"{uuid.uuid4().hex}{ext}"
    dest = Path(settings.storage_dir) / safe
    dest.write_bytes(content)

    # 解析 + 自动抽取 key_elements
    parsed = parse(str(dest))
    ke = parsed.key_elements

    # 校验指标存在
    indicator = None
    if indicator_id:
        indicator = db.get(Indicator, indicator_id)
        if not indicator:
            raise HTTPException(404, f"指标 {indicator_id} 不存在")

    material = Material(
        task_id=task.id,
        indicator_id=indicator_id,
        file_name=file_name,
        storage_path=str(dest),
        file_type=ext.lstrip("."),
        is_scanned=parsed.metadata.get("scanned", False),
        key_elements=json.dumps(ke.__dict__, ensure_ascii=False, default=str),
        parsed_text=parsed.text[:200000],  # 截断防爆
    )
    db.add(material); db.flush()
    log_action(db, user, "material.upload",
               target_type="material", target_id=material.id,
               detail=f"任务 #{task.id} 上传材料 {file_name} "
                      f"指标={indicator.indicator_code if indicator else '未绑定'}")
    db.commit(); db.refresh(material)
    return material


# ============================================================
# 复核标注（v3 §3.5）
# ============================================================
def review_finding(db: Session, finding_id: int, status: str,
                   note: str, user: User) -> Finding:
    if status not in ("confirmed", "ignored", "adjusted"):
        raise HTTPException(400, f"无效复核状态：{status}")
    finding = db.get(Finding, finding_id)
    if not finding:
        raise HTTPException(404, "Finding 不存在")
    finding.review_status = status
    finding.review_note = (note or "").strip()
    finding.reviewer_id = user.id
    finding.reviewed_at = datetime.utcnow()
    log_action(db, user, "finding.review",
               target_type="finding", target_id=finding.id,
               detail=f"标注为 {status}：{note[:200]}")
    db.commit(); db.refresh(finding)
    return finding


# ============================================================
# 整改闭环（v3 §3.7）
# ============================================================
def submit_rectification(db: Session, finding_id: int, note: str,
                         user: User) -> Finding:
    if not note.strip():
        raise HTTPException(400, "整改说明不能为空")
    finding = db.get(Finding, finding_id)
    if not finding:
        raise HTTPException(404, "Finding 不存在")
    finding.rectification_status = "submitted"
    finding.rectification_note = note.strip()
    log_action(db, user, "finding.rectify",
               target_type="finding", target_id=finding.id,
               detail=note[:200])
    db.commit(); db.refresh(finding)
    return finding


def resolve_rectification(db: Session, finding_id: int, confirm_note: str,
                          user: User) -> Finding:
    finding = db.get(Finding, finding_id)
    if not finding:
        raise HTTPException(404, "Finding 不存在")
    if finding.rectification_status not in ("submitted", "open"):
        raise HTTPException(400, f"当前整改状态「{finding.rectification_status}」不允许销号")
    finding.rectification_status = "resolved"
    finding.rectified_at = datetime.utcnow()
    if confirm_note:
        finding.rectification_note = (finding.rectification_note + "\n\n[复核确认] " + confirm_note).strip()
    log_action(db, user, "finding.resolve",
               target_type="finding", target_id=finding.id,
               detail=f"销号：{confirm_note[:200]}")
    db.commit(); db.refresh(finding)
    return finding


# ============================================================
# 任务状态推进
# ============================================================
def delete_task(db: Session, task_id: int, user: User) -> None:
    """级联删除任务：清理 Material 物理文件 + 删 DB 行 + 删 Finding。

    AuditTask 的 relationships (materials, findings) 已配 cascade="all, delete-orphan"，
    DB 层会自动级联。但 Material 文件需手工清理。
    """
    import os
    task = db.get(AuditTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")

    # 清理物理文件
    for m in list(task.materials):
        if m.storage_path and os.path.exists(m.storage_path):
            try:
                os.remove(m.storage_path)
            except OSError as exc:
                print(f"[task.delete] 清理文件失败 {m.storage_path}: {exc}")

    task_name = task.name
    db.delete(task)  # ← 级联删 materials / findings
    log_action(db, user, "task.delete",
               target_type="task", target_id=task_id,
               detail=f"删除任务「{task_name}」")
    db.commit()


def finalize_task(db: Session, task_id: int, user: User) -> AuditTask:
    """审查员完成复核后，将任务定稿为 finalized。"""
    task = db.get(AuditTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if task.status not in ("ai_done", "reviewing"):
        raise HTTPException(400, f"当前任务状态「{task.status}」不允许定稿")
    task.status = "finalized"
    log_action(db, user, "task.finalize",
               target_type="task", target_id=task.id,
               detail=f"任务 {task.name} 定稿")
    db.commit(); db.refresh(task)
    return task
