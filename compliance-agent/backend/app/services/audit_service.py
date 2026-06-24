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
                fast_mode: bool = False,
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
        fast_mode=bool(fast_mode),
        status="pending", summary="等待上传材料",
        created_by=user.id if user else None,
    )
    db.add(task); db.flush()
    scope_label = "全部指标" if scope == "all" else f"选定 {len(sel_ids)} 个指标"
    mode_label = "快速模式" if fast_mode else "精确模式"
    log_action(db, user, "task.create",
               target_type="task", target_id=task.id,
               detail=f"为「{unit.name}」创建任务「{name}」（{eval_year}，{scope_label}，{mode_label}）")
    db.commit(); db.refresh(task)
    return task


# ============================================================
# 上传材料 + 解析 + 抽取 key_elements
# ============================================================
def upload_material(db: Session, task: AuditTask, *,
                    file_name: str, content: bytes,
                    indicator_id: Optional[int],
                    relative_path: str = "",       # v1.5 新增
                    user: Optional[User] = None) -> Material:
    ext = Path(file_name).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(
            f"不支持的格式 {ext}（支持 {', '.join(SUPPORTED_EXTENSIONS)}）"
        )

    # ---- v1.4 文件去重：先算 hash，再查 DB 看物理文件能否复用 ----
    import hashlib as _hashlib
    content_hash = _hashlib.md5(content).hexdigest()
    reused = False
    reused_size_mb = 0.0
    existing = (db.query(Material)
                  .filter(Material.content_hash == content_hash,
                          Material.content_hash != "")
                  .first())
    if existing and existing.storage_path \
            and Path(existing.storage_path).exists():
        # 复用：不写新物理文件
        dest_path = existing.storage_path
        reused = True
        reused_size_mb = round(len(content) / (1024 * 1024), 2)
    else:
        # 首次或物理文件丢失 → 按现规则落盘
        safe = f"{uuid.uuid4().hex}{ext}"
        dest = Path(settings.storage_dir) / safe
        dest.write_bytes(content)
        dest_path = str(dest)

    # 解析 + 自动抽取 key_elements（v1.3: 传 db 让扫描件 PDF 自动 OCR）
    parsed = parse(dest_path, db=db)
    ke = parsed.key_elements

    # 校验指标存在
    indicator = None
    if indicator_id:
        indicator = db.get(Indicator, indicator_id)
        if not indicator:
            raise HTTPException(404, f"指标 {indicator_id} 不存在")

    # 自动绑定（仅当未显式指定时） — v1.5 改用路径感知匹配
    binding_confidence = "none"
    binding_source = "none"
    if not indicator_id:
        from app.services.material_matcher import match_indicator_by_path_and_content
        all_inds = db.query(Indicator).all()
        auto, conf, src = match_indicator_by_path_and_content(
            relative_path or "", file_name, parsed.text or "", all_inds,
        )
        if auto:
            indicator_id = auto.id
            indicator = auto
        binding_confidence = conf
        binding_source = src

    # 跨任务材料查重指纹：MD5(前 5000 字解析文本归一化)
    import re as _re
    norm_text = _re.sub(r"\s+", "", (parsed.text or "")[:5000])
    content_fp = _hashlib.md5(norm_text.encode("utf-8")).hexdigest() if norm_text else ""

    material = Material(
        task_id=task.id,
        indicator_id=indicator_id,
        file_name=file_name,
        storage_path=dest_path,
        file_type=ext.lstrip("."),
        is_scanned=parsed.metadata.get("scanned", False),
        key_elements=json.dumps(ke.__dict__, ensure_ascii=False, default=str),
        parsed_text=parsed.text[:200000],  # 截断防爆
        content_hash=content_hash,
        content_fingerprint=content_fp,
    )
    db.add(material); db.flush()
    detail = (f"任务 #{task.id} 上传材料 {file_name} "
              f"指标={indicator.indicator_code if indicator else '未绑定'}")
    if reused:
        detail += f"（复用文件，省 {reused_size_mb} MB）"
    log_action(db, user, "material.upload",
               target_type="material", target_id=material.id,
               detail=detail)
    db.commit(); db.refresh(material)
    # v1.4: 内存属性传给 API 层（不入 DB）
    material._reused = reused
    material._reused_size_mb = reused_size_mb
    material._binding_confidence = binding_confidence   # v1.5 新增
    material._binding_source = binding_source           # v1.5 新增

    # v1.5: 上传后自动形式审查 → Finding（受 AppSetting 开关控制）
    # 仅当文件有实质文本内容时运行（< 50 字符视为空文件 / 测试占位，跳过）
    try:
        from app.services.settings_service import get_auto_form_review_enabled
        if (get_auto_form_review_enabled(db)
                and material.indicator_id
                and len(material.parsed_text or "") >= 50):
            try:
                ke_dict = json.loads(material.key_elements or "{}")
            except Exception:
                ke_dict = {}
            _create_form_review_findings(db, task, material, ke_dict)
    except Exception as exc:
        print(f"[form_review] 上传后自动审查失败（不阻塞）: {exc}")

    return material


# ============================================================
# 材料批量自动绑定（关键词 + AI 阅读双阶段）
# ============================================================
def auto_bind_materials(db: Session, task: AuditTask, user: Optional[User] = None,
                        use_ai: bool = True) -> dict:
    """对任务下未绑定指标的材料做批量自动绑定。

    两阶段：
    1) **关键词匹配**：文件名/路径含指标关键词的直接命中（毫秒级，准）
    2) **AI 阅读分类**：剩余未绑定材料发给 LLM，根据文件名+解析文本分类
       （30 秒 - 2 分钟，大幅提高命中率）

    返回：
    {checked, keyword_bound, ai_bound, still_unbound, samples, ai_used}
    """
    from app.services.material_matcher import match_indicator_by_content
    indicators = db.query(Indicator).all()

    # 第 1 阶段：关键词匹配
    unbound_materials: list[Material] = [m for m in task.materials if not m.indicator_id]
    checked = len(unbound_materials)
    keyword_bound = 0
    still_unbound: list[Material] = []
    samples: list[dict] = []

    for m in unbound_materials:
        ind = match_indicator_by_content(
            m.file_name, m.parsed_text or "", indicators,
        )
        if ind:
            m.indicator_id = ind.id
            keyword_bound += 1
            if len(samples) < 5:
                samples.append({
                    "file": (m.file_name or "")[:60],
                    "indicator_code": ind.indicator_code,
                    "source": "keyword",
                })
        else:
            still_unbound.append(m)

    db.flush()

    # 第 2 阶段：AI 阅读分类（可选）
    ai_bound = 0
    ai_used = False
    if use_ai and still_unbound:
        new_still: list[Material] = list(still_unbound)
        try:
            from app.llm.factory import get_llm_client
            from app.llm.stub import StubLLMClient
            from app.services.ai_material_classifier import ai_classify_materials
            llm = get_llm_client(db)
            ai_used = not isinstance(llm, StubLLMClient)
            mapping = ai_classify_materials(db, task, llm, still_unbound, indicators)
            new_still = []  # 重新累加
            for m in still_unbound:
                iid = mapping.get(m.id)
                if iid is None:
                    new_still.append(m)
                    continue
                m.indicator_id = iid
                ai_bound += 1
                if len(samples) < 10:
                    ind = next((x for x in indicators if x.id == iid), None)
                    samples.append({
                        "file": (m.file_name or "")[:60],
                        "indicator_code": ind.indicator_code if ind else "?",
                        "source": "ai",
                    })
        except Exception as exc:
            print(f"[auto_bind] AI 分类失败（仅关键词生效）: {exc}")
        still_unbound = new_still

    # 第 3 阶段：subcategory 兜底（v1.1 新增）—— 尽量将 still_unbound 降为 0
    # 注意：若 fallback 表里某指标在库中缺失（如 I-55 未 seed），该材料仍保留未绑定
    from app.services.material_matcher import (
        match_subcategory, fallback_indicator_for_subcategory,
    )
    fallback_bound = 0
    for m in list(still_unbound):
        if m.indicator_id is not None:
            still_unbound.remove(m)
            continue
        signal = (m.file_name or "") + " " + (m.parsed_text or "")[:500]
        sub = match_subcategory(signal) or "补充指标"
        ind = fallback_indicator_for_subcategory(sub, indicators)
        if not ind:
            print(f"[auto_bind] 兜底失败：材料 {m.file_name!r} subcategory={sub!r} "
                  f"fallback 找不到对应指标（库中缺失 I-55？）")
            continue
        m.indicator_id = ind.id
        fallback_bound += 1
        still_unbound.remove(m)
        if len(samples) < 15:
            samples.append({
                "file": (m.file_name or "")[:60],
                "indicator_code": ind.indicator_code,
                "source": "fallback",
            })

    db.flush()

    if keyword_bound or ai_bound or fallback_bound:
        log_action(db, user, "material.auto_bind",
                   target_type="task", target_id=task.id,
                   detail=(f"自动绑定 关键词 {keyword_bound} + AI {ai_bound} "
                           f"+ 兜底 {fallback_bound} / 共 {checked}"))
    db.commit()
    return {
        "checked": checked,
        "keyword_bound": keyword_bound,
        "ai_bound": ai_bound,
        "fallback_bound": fallback_bound,
        "bound_now": keyword_bound + ai_bound + fallback_bound,
        "still_unbound": len(still_unbound),
        "ai_used": ai_used,
        "samples": samples,
    }


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

    # v1.4 引用计数：被其它 Material 引用的物理文件不删
    deleted_physical, kept_physical = 0, 0
    for m in list(task.materials):
        if not m.storage_path:
            continue
        if m.content_hash:
            other_refs = (db.query(Material)
                            .filter(Material.content_hash == m.content_hash,
                                    Material.id != m.id)
                            .count())
            if other_refs > 0:
                kept_physical += 1
                continue
        if os.path.exists(m.storage_path):
            try:
                os.remove(m.storage_path)
                deleted_physical += 1
            except Exception as exc:
                print(f"[task.delete] 清理文件失败 {m.storage_path}: {exc}")

    task_name = task.name
    db.delete(task)  # ← 级联删 materials / findings
    log_action(db, user, "task.delete",
               target_type="task", target_id=task_id,
               detail=f"删除任务「{task_name}」(物理删除:{deleted_physical} 保留:{kept_physical})")
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


# ============================================================
# v1.5 上传后自动形式审查 → Finding
# ============================================================
_FORM_REVIEW_RULES = [
    # (rule_key, 检测 key, 触发条件 lambda, finding_type, severity, description, suggestion)
    ("seal",
     "has_official_seal",
     lambda v: v is False,
     "形式性", "中",
     "材料未识别到公章 / 印章 / 签章",
     "请确认材料是否为正式盖章版本；扫描件请确保印章清晰可辨"),
    ("date",
     "issue_date",
     lambda v: not v,
     "形式性", "中",
     "材料未识别到落款日期",
     "正式文件应包含发文/印发日期"),
    ("docno",
     "document_number",
     lambda v: not v,
     "形式性", "低",
     "材料未识别到正式文号",
     "如属内部材料可忽略；正式发文应包含文件编号"),
    ("draft",
     "is_draft",
     lambda v: bool(v),
     "形式性", "高",
     "材料疑似草稿 / 征求意见稿",
     "正式核查应使用定稿版本"),
]


def _create_form_review_findings(db: Session, task: AuditTask,
                                  material: Material,
                                  key_elements: dict) -> int:
    """v1.5: 对 material 跑 4 项形式审查 → 创建 Finding。返回创建条数。

    不在 material.indicator_id 为空时创建（避免孤儿 finding）。
    幂等：同一 material + rule_key 组合已存在则跳过。
    """
    if not material.indicator_id:
        return 0
    # 查询已有 rule findings（evidence_location 编码了 rule_key，防重复）
    existing_locs: set[str] = set()
    existing = (db.query(Finding.evidence_location)
                  .filter(Finding.material_id == material.id,
                          Finding.source == "rule")
                  .all())
    existing_locs = {row[0] for row in existing}

    created = 0
    for rule_key, ke_key, trigger_fn, ftype, severity, desc, suggest in _FORM_REVIEW_RULES:
        actual = key_elements.get(ke_key)
        if not trigger_fn(actual):
            continue
        loc = f"material#{material.id}#{rule_key}"
        if loc in existing_locs:
            continue
        finding = Finding(
            task_id=task.id,
            material_id=material.id,
            indicator_id=material.indicator_id,
            finding_type=ftype,
            severity=severity,
            description=f"{desc}（文件：{material.file_name[:50] if material.file_name else ''}）",
            evidence_location=loc,
            suggestion=suggest,
            source="rule",
        )
        db.add(finding)
        created += 1
    if created:
        db.commit()
    return created
