"""核查任务 / 材料 / Finding API（v3）。"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.schemas import (
    AuditTaskCreate,
    AuditTaskOut,
    AuditUnitIn,
    AuditUnitOut,
    FindingOut,
    FindingRectifyConfirmRequest,
    FindingRectifyRequest,
    FindingReviewRequest,
    MaterialOut,
    TaskDetailOut,
    WorksheetOut,
)
from app.core.auth import get_current_user, log_action, require_auditor
from app.core.permissions import is_admin, is_auditor_or_above, is_unit
from app.models import AuditTask, AuditUnit, Finding, Material, User, get_db
from app.parsers.dispatcher import UnsupportedFormatError
from app.services import audit_service
from app.services.report_service import build_report_docx
from app.services.worksheet_export import build_worksheet_xlsx
from app.services.worksheet_service import build_worksheet_draft, get_worksheet
from app.tasks import run_audit_task

units_router = APIRouter(prefix="/api/units", tags=["audit:units"])
tasks_router = APIRouter(prefix="/api/tasks", tags=["audit:tasks"])
findings_router = APIRouter(prefix="/api/findings", tags=["audit:findings"])


# ============================================================
# 单位
# ============================================================
@units_router.get("", response_model=List[AuditUnitOut])
def list_units(db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    q = db.query(AuditUnit).order_by(AuditUnit.id.desc())
    if is_unit(user.role) and user.unit_id:
        q = q.filter(AuditUnit.id == user.unit_id)
    return q.all()


@units_router.post("", response_model=AuditUnitOut)
def create_unit(req: AuditUnitIn,
                db: Session = Depends(get_db),
                user: User = Depends(require_auditor)):
    return audit_service.create_unit(
        db, name=req.name, code=req.code,
        level=req.level, description=req.description, user=user,
    )


# ============================================================
# 任务
# ============================================================
def _user_can_see_task(user: User, task: AuditTask) -> bool:
    if is_auditor_or_above(user.role):
        return True
    if is_unit(user.role) and user.unit_id == task.unit_id:
        return True
    return False


@tasks_router.get("", response_model=List[AuditTaskOut])
def list_tasks(db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    q = db.query(AuditTask).order_by(AuditTask.id.desc())
    if is_unit(user.role) and user.unit_id:
        q = q.filter(AuditTask.unit_id == user.unit_id)
    return q.all()


@tasks_router.post("", response_model=AuditTaskOut)
def create_task(req: AuditTaskCreate,
                db: Session = Depends(get_db),
                user: User = Depends(require_auditor)):
    return audit_service.create_task(
        db, unit_id=req.unit_id, name=req.name,
        eval_year=req.eval_year,
        scope=req.scope,
        selected_indicator_ids=req.selected_indicator_ids,
        user=user,
    )


@tasks_router.get("/{task_id}", response_model=TaskDetailOut)
def get_task_detail(task_id: int,
                    db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    task = db.get(AuditTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if not _user_can_see_task(user, task):
        raise HTTPException(403, "无权查看此任务")
    unit = db.get(AuditUnit, task.unit_id)

    # 老任务的 stats 里没 scoring → 临时回填一次（不写回 DB，纯展示）
    if task.status in ("ai_done", "reviewing", "finalized", "archived"):
        import json as _json
        try:
            stats = _json.loads(task.stats or "{}")
        except Exception:
            stats = {}
        if "scoring" not in stats:
            try:
                from app.services.scoring_service import compute_task_scoring
                stats["scoring"] = compute_task_scoring(db, task)
                task.stats = _json.dumps(stats, ensure_ascii=False)
                db.commit()
            except Exception as exc:
                print(f"[scoring backfill] {exc}")
                db.rollback()

    return TaskDetailOut(
        task=AuditTaskOut.model_validate(task),
        unit=AuditUnitOut.model_validate(unit),
        materials=[MaterialOut.model_validate(m) for m in task.materials],
        findings=[FindingOut.model_validate(f) for f in task.findings],
    )


@tasks_router.post("/{task_id}/materials", response_model=MaterialOut)
async def upload_material(
    task_id: int,
    file: UploadFile = File(...),
    indicator_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = db.get(AuditTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if not _user_can_see_task(user, task):
        raise HTTPException(403, "无权上传到此任务")
    try:
        content = await file.read()
        material = audit_service.upload_material(
            db, task, file_name=file.filename or "untitled",
            content=content, indicator_id=indicator_id, user=user,
        )
    except UnsupportedFormatError as exc:
        raise HTTPException(400, str(exc))
    return material


@tasks_router.post("/{task_id}/run", response_model=AuditTaskOut)
def run_task(task_id: int,
             db: Session = Depends(get_db),
             user: User = Depends(require_auditor)):
    """触发 AI 核查（异步入队，eager 模式立即返回 done）。"""
    task = db.get(AuditTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if not task.materials:
        raise HTTPException(400, "任务下尚无材料，请先上传")
    log_action(db, user, "task.run",
               target_type="task", target_id=task.id,
               detail=f"触发 AI 核查（{len(task.materials)} 份材料）")
    db.commit()
    run_audit_task.delay(task.id)
    db.refresh(task)
    return task


@tasks_router.post("/{task_id}/finalize", response_model=AuditTaskOut)
def finalize_task(task_id: int,
                  db: Session = Depends(get_db),
                  user: User = Depends(require_auditor)):
    return audit_service.finalize_task(db, task_id, user)


@tasks_router.delete("/{task_id}")
def delete_task(task_id: int,
                db: Session = Depends(get_db),
                user: User = Depends(require_auditor)):
    """删除任务（级联清理材料 + finding + 物理文件）。仅审查员及以上可删。"""
    task = db.get(AuditTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if not _user_can_see_task(user, task):
        raise HTTPException(403, "无权删除此任务")
    audit_service.delete_task(db, task_id, user)
    return {"status": "ok"}


@tasks_router.get("/{task_id}/report")
def download_task_report(task_id: int,
                         db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    """生成 Word 核查报告（v3 §3.6 5 章节）。"""
    task = db.get(AuditTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if not _user_can_see_task(user, task):
        raise HTTPException(403, "无权下载此任务报告")
    try:
        data = build_report_docx(db, task)
    except Exception as exc:
        raise HTTPException(500, f"报告生成失败：{exc}")
    safe_name = f"内控评价核查报告_{task.eval_year}_{task.id}.docx"
    # RFC 5987 编码中文文件名
    from urllib.parse import quote
    filename_quoted = quote(safe_name)
    return StreamingResponse(
        iter([data]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition":
                f"attachment; filename=report_{task.id}.docx; "
                f"filename*=UTF-8''{filename_quoted}"
        },
    )


# ============================================================
# 工作底稿（AI 阅卷 → 底稿 → 报告）
# ============================================================
@tasks_router.get("/{task_id}/worksheet", response_model=WorksheetOut)
def get_task_worksheet(task_id: int,
                       db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """获取任务的工作底稿（含 55 行明细）。AI 跑完后自动生成。"""
    task = db.get(AuditTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if not _user_can_see_task(user, task):
        raise HTTPException(403, "无权查看")
    ws = get_worksheet(db, task_id)
    if not ws:
        raise HTTPException(404, "底稿尚未生成（请先触发 AI 核查）")
    return ws


@tasks_router.post("/{task_id}/worksheet/rebuild", response_model=WorksheetOut)
def rebuild_task_worksheet(task_id: int,
                           db: Session = Depends(get_db),
                           user: User = Depends(require_auditor)):
    """根据当前 Finding 状态重建底稿（V1：覆盖式重跑）。"""
    task = db.get(AuditTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if not _user_can_see_task(user, task):
        raise HTTPException(403, "无权操作")
    ws = build_worksheet_draft(db, task)
    log_action(db, user, "worksheet.rebuild",
               target_type="task", target_id=task.id,
               detail=f"重建工作底稿 行数={len(ws.rows)}")
    db.commit()
    return ws


@tasks_router.get("/{task_id}/worksheet.xlsx")
def download_task_worksheet_xlsx(task_id: int,
                                 db: Session = Depends(get_db),
                                 user: User = Depends(get_current_user)):
    """下载 Excel 格式工作底稿（1:1 复刻模板）。"""
    task = db.get(AuditTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if not _user_can_see_task(user, task):
        raise HTTPException(403, "无权下载")
    ws = get_worksheet(db, task_id)
    if not ws:
        raise HTTPException(404, "底稿尚未生成")
    data = build_worksheet_xlsx(db, task, ws)
    safe_name = f"内控评价核查工作底稿_{task.eval_year}_{task.id}.xlsx"
    from urllib.parse import quote
    filename_quoted = quote(safe_name)
    return StreamingResponse(
        iter([data]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition":
                f"attachment; filename=worksheet_{task.id}.xlsx; "
                f"filename*=UTF-8''{filename_quoted}"
        },
    )


# ============================================================
# Finding 复核标注 + 整改闭环
# ============================================================
@findings_router.get("/{finding_id}", response_model=FindingOut)
def get_finding(finding_id: int,
                db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    finding = db.get(Finding, finding_id)
    if not finding:
        raise HTTPException(404, "Finding 不存在")
    task = db.get(AuditTask, finding.task_id)
    if not task or not _user_can_see_task(user, task):
        raise HTTPException(403, "无权查看")
    return finding


@findings_router.post("/{finding_id}/review", response_model=FindingOut)
def review_finding(finding_id: int, req: FindingReviewRequest,
                   db: Session = Depends(get_db),
                   user: User = Depends(require_auditor)):
    return audit_service.review_finding(db, finding_id, req.status, req.note, user)


@findings_router.post("/{finding_id}/rectify", response_model=FindingOut)
def submit_rectification(finding_id: int, req: FindingRectifyRequest,
                         db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    """被检查单位（或审查员代填）提交整改说明。"""
    finding = db.get(Finding, finding_id)
    if not finding:
        raise HTTPException(404, "Finding 不存在")
    task = db.get(AuditTask, finding.task_id)
    if not task or not _user_can_see_task(user, task):
        raise HTTPException(403, "无权提交整改")
    return audit_service.submit_rectification(db, finding_id, req.note, user)


@findings_router.post("/{finding_id}/resolve", response_model=FindingOut)
def resolve_rectification(finding_id: int, req: FindingRectifyConfirmRequest,
                          db: Session = Depends(get_db),
                          user: User = Depends(require_auditor)):
    return audit_service.resolve_rectification(db, finding_id, req.note, user)
