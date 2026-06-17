"""核查任务 / 材料 / Finding API（v3）。"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
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
from app.models import AuditTask, AuditUnit, Finding, Indicator, Material, User, get_db
from app.parsers.dispatcher import UnsupportedFormatError
from app.services import audit_service
from app.services.report_service import build_report_docx
from app.services.worksheet_export import build_worksheet_xlsx
from app.services.worksheet_service import build_worksheet_draft, get_worksheet
from app.tasks import run_audit_task

units_router = APIRouter(prefix="/api/units", tags=["audit:units"])
tasks_router = APIRouter(prefix="/api/tasks", tags=["audit:tasks"])
findings_router = APIRouter(prefix="/api/findings", tags=["audit:findings"])
materials_router = APIRouter(prefix="/api/materials", tags=["audit:materials"])


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


@units_router.delete("/{unit_id}")
def delete_unit(unit_id: int,
                db: Session = Depends(get_db),
                user: User = Depends(require_auditor)):
    """删除被检查单位（含任务引用校验）。"""
    unit = db.get(AuditUnit, unit_id)
    if not unit:
        raise HTTPException(404, "单位不存在")
    n_tasks = db.query(AuditTask).filter(AuditTask.unit_id == unit_id).count()
    if n_tasks > 0:
        raise HTTPException(
            400,
            f"该单位下还有 {n_tasks} 个核查任务，请先删除任务再删除单位",
        )
    # 把绑定的 unit 用户解绑
    db.query(User).filter(User.unit_id == unit_id).update({User.unit_id: None})
    name = unit.name
    db.delete(unit)
    log_action(db, user, "unit.delete",
               target_type="unit", target_id=unit_id,
               detail=f"删除单位「{name}」")
    db.commit()
    return {"status": "ok"}


@units_router.post("/import-from-file", response_model=dict)
async def import_units_from_file_api(
    file: UploadFile = File(...),
    dry_run: bool = Query(False, description="true 仅返回预览不入库"),
    db: Session = Depends(get_db),
    user: User = Depends(require_auditor),
):
    """Excel / CSV 批量导入被检查单位（已存在同名 → 跳过）。"""
    from app.services.unit_import_service import import_units_from_file
    raw = await file.read()
    try:
        return import_units_from_file(db, raw, file.filename or "u.xlsx",
                                      dry_run=dry_run, user=user)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


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
        fast_mode=req.fast_mode,
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


class MaterialBindRequest(BaseModel):
    indicator_id: Optional[int] = None  # null=解绑


@tasks_router.patch("/{task_id}/materials/{material_id}", response_model=MaterialOut)
def bind_material_indicator(task_id: int, material_id: int,
                            req: MaterialBindRequest,
                            db: Session = Depends(get_db),
                            user: User = Depends(require_auditor)):
    """改/解绑某份材料的指标。"""
    task = db.get(AuditTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if not _user_can_see_task(user, task):
        raise HTTPException(403, "无权操作此任务")
    material = db.get(Material, material_id)
    if not material or material.task_id != task_id:
        raise HTTPException(404, "材料不存在或不属于本任务")
    if req.indicator_id is not None:
        ind = db.get(Indicator, req.indicator_id)
        if not ind:
            raise HTTPException(400, f"指标 {req.indicator_id} 不存在")
    old_iid = material.indicator_id
    material.indicator_id = req.indicator_id
    log_action(db, user, "material.bind",
               target_type="material", target_id=material.id,
               detail=f"任务 #{task_id} 材料 {material.file_name} 绑定 "
                      f"{old_iid} → {req.indicator_id}")
    db.commit(); db.refresh(material)
    return material


@tasks_router.post("/{task_id}/materials/auto-bind")
def auto_bind_materials(task_id: int,
                        db: Session = Depends(get_db),
                        user: User = Depends(require_auditor)):
    """对未绑定指标的材料按文件名关键词批量自动绑定。"""
    task = db.get(AuditTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if not _user_can_see_task(user, task):
        raise HTTPException(403, "无权操作此任务")
    return audit_service.auto_bind_materials(db, task, user)


@tasks_router.post("/{task_id}/run", response_model=AuditTaskOut)
def run_task(task_id: int,
             force: bool = Query(False, description="已完成的任务必须设 true 才允许重跑"),
             db: Session = Depends(get_db),
             user: User = Depends(require_auditor)):
    """触发 AI 核查（异步入队，eager 模式立即返回 done）。

    防呆：
    - status=running：拒绝（避免并行重复跑）
    - status in ai_done/reviewing/finalized/archived：要求 force=true（避免误点重跑）
    """
    task = db.get(AuditTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if not task.materials:
        raise HTTPException(400, "任务下尚无材料，请先上传")
    if task.status == "running":
        raise HTTPException(400, "任务正在核查中，请等待完成后再操作")
    if task.status in ("ai_done", "reviewing", "finalized", "archived") and not force:
        raise HTTPException(
            400,
            "任务已完成核查。重新核查会清空已有疑点与工作底稿，请确认后带 force=true 参数",
        )
    log_action(db, user, "task.run",
               target_type="task", target_id=task.id,
               detail=f"触发 AI 核查（{len(task.materials)} 份材料"
                      f"{'，强制重跑' if force else ''}）")
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
# 材料审核聚合视图（4 类数据）
# ============================================================
@tasks_router.get("/{task_id}/material-review")
def get_material_review(task_id: int,
                        db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """聚合：重复检测 / 内容审核 / 匹配情况 / 操作时间线。"""
    from app.services import material_review_service
    task = db.get(AuditTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if not _user_can_see_task(user, task):
        raise HTTPException(403, "无权查看")
    return material_review_service.review_overview(db, task)


class MergeDuplicatesRequest(BaseModel):
    content_hash: str
    keep_material_id: int


@tasks_router.post("/{task_id}/materials/merge-duplicates")
def merge_duplicate_materials(task_id: int,
                              req: MergeDuplicatesRequest,
                              db: Session = Depends(get_db),
                              user: User = Depends(require_auditor)):
    """同任务内 content_hash 相同的多份材料，保留 keep_material_id，删除其余。

    被删材料关联的 Finding 不删，只 material_id 设 NULL（保留可追溯）。
    """
    from app.services import material_review_service
    task = db.get(AuditTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if not _user_can_see_task(user, task):
        raise HTTPException(403, "无权操作此任务")
    res = material_review_service.merge_duplicate_group(
        db, task, req.content_hash, req.keep_material_id,
        user_id=user.id if user else None,
    )
    if res.get("error"):
        raise HTTPException(400, res["error"])
    log_action(db, user, "material.merge",
               target_type="task", target_id=task.id,
               detail=f"合并重复材料：保留 #{res['kept']}，删除 {res['removed']} 份")
    db.commit()
    return res


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
    ws = get_worksheet(db, task_id)
    if ws and ws.status == "finalized":
        raise HTTPException(400, "底稿已定稿，请先解锁后再重建")
    ws = build_worksheet_draft(db, task)
    log_action(db, user, "worksheet.rebuild",
               target_type="task", target_id=task.id,
               detail=f"重建工作底稿 行数={len(ws.rows)}")
    db.commit()
    return ws


# ============================================================
# V2：在线编辑 + 定稿状态机
# ============================================================
class WorksheetRowPatch(BaseModel):
    audited_score: Optional[float] = None
    audit_finding_text: Optional[str] = None
    adjustment_note: Optional[str] = None
    material_flags: Optional[dict] = None
    unit_name: Optional[str] = None
    unit_code: Optional[str] = None
    auditor_name: Optional[str] = None
    reviewer_name: Optional[str] = None


@tasks_router.patch("/{task_id}/worksheet/rows/{row_id}")
def patch_worksheet_row(task_id: int, row_id: int,
                        req: WorksheetRowPatch,
                        db: Session = Depends(get_db),
                        user: User = Depends(require_auditor)):
    """编辑底稿单元格：核查后得分 / 核查情况说明 / 7 对 14 项复选框。

    finalized 状态拒绝（必须先解锁）。
    """
    from app.models import WorksheetRow
    task = db.get(AuditTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if not _user_can_see_task(user, task):
        raise HTTPException(403, "无权操作此任务")
    row = db.get(WorksheetRow, row_id)
    if not row:
        raise HTTPException(404, "底稿行不存在")
    ws = get_worksheet(db, task_id)
    if not ws or row.worksheet_id != ws.id:
        raise HTTPException(404, "底稿行不属于此任务")
    if ws.status == "finalized":
        raise HTTPException(400, "底稿已定稿，请先解锁再编辑")

    changes: list[str] = []
    if req.audited_score is not None:
        try:
            v = float(req.audited_score)
        except (TypeError, ValueError):
            raise HTTPException(400, "audited_score 必须是数字")
        max_sc = float(row.indicator.max_score) if row.indicator else None
        if max_sc is not None and (v < 0 or v > max_sc):
            raise HTTPException(400, f"audited_score 必须在 [0, {max_sc}] 之间")
        if abs(row.audited_score - v) > 1e-9:
            changes.append(f"audited_score {row.audited_score} → {v}")
            row.audited_score = v
    if req.audit_finding_text is not None:
        if row.audit_finding_text != req.audit_finding_text:
            changes.append("audit_finding_text 已更新")
            row.audit_finding_text = req.audit_finding_text[:2000]
    if req.adjustment_note is not None:
        if row.adjustment_note != req.adjustment_note:
            changes.append("adjustment_note 已更新")
            row.adjustment_note = req.adjustment_note[:2000]
    if req.material_flags is not None:
        import json as _json
        new_flags = _json.dumps(req.material_flags, ensure_ascii=False)
        if row.material_flags != new_flags:
            changes.append("material_flags 已更新")
            row.material_flags = new_flags

    # 同时支持改底稿元数据（unit_name 等）
    if any(x is not None for x in (req.unit_name, req.unit_code,
                                   req.auditor_name, req.reviewer_name)):
        if req.unit_name is not None:
            ws.unit_name = req.unit_name[:256]
        if req.unit_code is not None:
            ws.unit_code = req.unit_code[:64]
        if req.auditor_name is not None:
            ws.auditor_name = req.auditor_name[:64]
        if req.reviewer_name is not None:
            ws.reviewer_name = req.reviewer_name[:64]
        changes.append("底稿元数据已更新")

    # 首次编辑时把底稿状态升到 reviewing
    if ws.status == "draft" and changes:
        ws.status = "reviewing"

    if changes:
        log_action(db, user, "worksheet.row.edit",
                   target_type="worksheet_row", target_id=row.id,
                   detail=f"任务 #{task_id} 行 #{row.serial}：" + "；".join(changes))
        db.commit()
    db.refresh(row)
    return {
        "id": row.id, "serial": row.serial,
        "audited_score": row.audited_score,
        "audit_finding_text": row.audit_finding_text,
        "adjustment_note": row.adjustment_note,
        "material_flags": row.material_flags,
        "worksheet_status": ws.status,
    }


@tasks_router.post("/{task_id}/worksheet/finalize", response_model=WorksheetOut)
def finalize_worksheet(task_id: int,
                       db: Session = Depends(get_db),
                       user: User = Depends(require_auditor)):
    """定稿底稿：锁定为只读，禁止再编辑单元格。"""
    task = db.get(AuditTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if not _user_can_see_task(user, task):
        raise HTTPException(403, "无权操作")
    ws = get_worksheet(db, task_id)
    if not ws:
        raise HTTPException(404, "底稿不存在")
    if ws.status == "finalized":
        return ws  # 幂等
    ws.status = "finalized"
    # 同步任务状态
    if task.status in ("ai_done", "reviewing"):
        task.status = "finalized"
    log_action(db, user, "worksheet.finalize",
               target_type="task", target_id=task.id,
               detail="底稿定稿")
    db.commit(); db.refresh(ws)
    return ws


@tasks_router.post("/{task_id}/worksheet/unlock", response_model=WorksheetOut)
def unlock_worksheet(task_id: int,
                     db: Session = Depends(get_db),
                     user: User = Depends(require_auditor)):
    """解锁底稿（仅超级管理员）→ 回到 reviewing 状态可继续编辑。"""
    if not is_admin(user.role):
        raise HTTPException(403, "仅超级管理员可解锁定稿底稿")
    task = db.get(AuditTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    ws = get_worksheet(db, task_id)
    if not ws:
        raise HTTPException(404, "底稿不存在")
    if ws.status != "finalized":
        return ws
    ws.status = "reviewing"
    if task.status == "finalized":
        task.status = "reviewing"
    log_action(db, user, "worksheet.unlock",
               target_type="task", target_id=task.id,
               detail="解锁底稿")
    db.commit(); db.refresh(ws)
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


# ============================================================
# 材料预览 / 下载（用于点击核查发现里的"材料出处"打开原文件）
# ============================================================
_INLINE_MIME = {
    "pdf":  "application/pdf",
    "png":  "image/png",
    "jpg":  "image/jpeg", "jpeg": "image/jpeg",
    "gif":  "image/gif",
    "webp": "image/webp",
    "svg":  "image/svg+xml",
    "txt":  "text/plain; charset=utf-8",
    "md":   "text/markdown; charset=utf-8",
}
_OFFICE_MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc":  "application/msword",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls":  "application/vnd.ms-excel",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "ppt":  "application/vnd.ms-powerpoint",
}


@materials_router.get("/{material_id}/preview")
def preview_material(material_id: int,
                     db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """打开 / 下载材料原文件。

    - PDF / 图片 / 纯文本 → Content-Disposition: inline（浏览器内联预览）
    - docx / xlsx 等办公文件 → attachment（强制下载，由本地 Office 打开）
    - 其它未知格式 → attachment 兜底
    """
    from pathlib import Path
    material = db.get(Material, material_id)
    if not material:
        raise HTTPException(404, "材料不存在")
    task = db.get(AuditTask, material.task_id)
    if not task or not _user_can_see_task(user, task):
        raise HTTPException(403, "无权查看此材料")

    path = Path(material.storage_path or "")
    if not path.exists():
        raise HTTPException(404, "材料文件已丢失")

    ext = (material.file_type or path.suffix.lstrip(".") or "").lower()
    if ext in _INLINE_MIME:
        media_type = _INLINE_MIME[ext]
        disposition = "inline"
    elif ext in _OFFICE_MIME:
        media_type = _OFFICE_MIME[ext]
        disposition = "attachment"
    else:
        media_type = "application/octet-stream"
        disposition = "attachment"

    from urllib.parse import quote
    fname = material.file_name or path.name
    # 文件名只取最后一段（去掉路径前缀）
    short_name = Path(fname).name
    quoted = quote(short_name)
    # HTTP header 必须 latin-1；中文文件名只能放 filename*=UTF-8''
    # 给一个 ASCII fallback（材料编号）
    ascii_fallback = f"material_{material.id}{path.suffix}"

    def _stream():
        with open(path, "rb") as f:
            while True:
                chunk = f.read(64 * 1024)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(
        _stream(),
        media_type=media_type,
        headers={
            "Content-Disposition":
                f'{disposition}; filename="{ascii_fallback}"; '
                f"filename*=UTF-8''{quoted}",
            "Content-Length": str(path.stat().st_size),
            "X-Content-Type-Options": "nosniff",
        },
    )
