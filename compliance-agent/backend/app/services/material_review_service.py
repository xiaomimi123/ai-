"""材料审核聚合视图 — 把分散在各模块的"材料级"信息集中到一个 API。

4 个数据集：
1. duplicates    — 同任务内 + 跨任务的重复检测（基于 content_hash / fingerprint）
2. content_review — 每份材料的 key_elements + 5 维度判定结果
3. matching      — 材料绑定来源分布 / 指标覆盖率 / 低匹配项
4. timeline      — 从 audit_log 聚合的关键操作时间线
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import (
    AuditLog, AuditTask, Finding, Indicator, Material,
    Worksheet, WorksheetRow,
)


# ============================================================
# 重复性检测
# ============================================================
def detect_duplicates(db: Session, task: AuditTask) -> dict:
    """返回 {same_task: [...组...], cross_task: [...条...]}.

    same_task 组：同一任务内 content_hash 完全相同的多份材料
    cross_task 条：本任务材料 vs 其它任务材料 content_hash 命中
    """
    my_materials = list(task.materials)
    if not my_materials:
        return {"same_task_groups": [], "cross_task_pairs": []}

    # 同任务内：按 content_hash 分组
    by_hash: dict[str, list[Material]] = defaultdict(list)
    for m in my_materials:
        if m.content_hash:
            by_hash[m.content_hash].append(m)

    same_task_groups = []
    for h, group in by_hash.items():
        if len(group) > 1:
            same_task_groups.append({
                "content_hash": h,
                "count": len(group),
                "materials": [
                    {
                        "id": m.id,
                        "file_name": m.file_name,
                        "indicator_id": m.indicator_id,
                        "uploaded_at": m.created_at.isoformat() if m.created_at else None,
                    }
                    for m in sorted(group, key=lambda x: x.created_at or datetime.min)
                ],
            })

    # 跨任务：当前任务的每个 hash 在其它任务里是否出现
    my_hashes = {m.content_hash for m in my_materials if m.content_hash}
    cross_task_pairs = []
    if my_hashes:
        external = (
            db.query(Material)
            .filter(Material.task_id != task.id)
            .filter(Material.content_hash.in_(my_hashes))
            .all()
        )
        for ext in external:
            # 找本任务对应那份
            mine = next(
                (m for m in my_materials if m.content_hash == ext.content_hash),
                None,
            )
            if mine is None:
                continue
            other_task = db.get(AuditTask, ext.task_id)
            cross_task_pairs.append({
                "my_material": {"id": mine.id, "file_name": mine.file_name},
                "other_task_id": ext.task_id,
                "other_task_name": other_task.name if other_task else "—",
                "other_material": {"id": ext.id, "file_name": ext.file_name},
            })

    return {
        "same_task_groups": same_task_groups,
        "cross_task_pairs": cross_task_pairs,
    }


# ============================================================
# 内容审核（每份材料的 KE + flag 判定）
# ============================================================
def collect_content_review(db: Session, task: AuditTask) -> list[dict]:
    """每份材料一行：文件 / key_elements / 来自工作底稿的 5 对 flag。"""
    # 拉本任务底稿，把 material_flags 映射到 material
    ws = db.query(Worksheet).filter(Worksheet.task_id == task.id).first()
    flags_by_material: dict[int, dict] = {}
    if ws:
        for row in ws.rows:
            try:
                fl = json.loads(row.material_flags or "{}")
            except Exception:
                fl = {}
            # 同一指标的所有材料共享这一行的 flags（粒度限制）
            # 找该指标下的材料
            for m in task.materials:
                if m.indicator_id == row.indicator_id:
                    flags_by_material[m.id] = fl

    results = []
    inds_by_id = {ind.id: ind for ind in db.query(Indicator).all()}
    for m in task.materials:
        try:
            ke = json.loads(m.key_elements or "{}")
        except Exception:
            ke = {}
        ind = inds_by_id.get(m.indicator_id) if m.indicator_id else None
        flags = flags_by_material.get(m.id, {})
        results.append({
            "material_id": m.id,
            "file_name": m.file_name,
            "file_type": m.file_type,
            "is_scanned": m.is_scanned,
            "indicator_code": ind.indicator_code if ind else None,
            "indicator_name": ind.name if ind else None,
            "key_elements": {
                "has_official_seal": ke.get("has_official_seal"),
                "has_signature": ke.get("has_signature"),
                "issue_year": ke.get("issue_year"),
                "issue_date": ke.get("issue_date"),
                "document_number": ke.get("document_number"),
                "is_draft": ke.get("is_draft"),
            },
            "flags": {
                "real": flags.get("real"),
                "fake": flags.get("fake"),
                "complete": flags.get("complete"),
                "incomplete": flags.get("incomplete"),
                "compliant": flags.get("compliant"),
                "non_compliant": flags.get("non_compliant"),
                "unique": flags.get("unique"),
                "duplicate": flags.get("duplicate"),
                "match_high": flags.get("match_high"),
                "match_low": flags.get("match_low"),
            },
            "uploaded_at": m.created_at.isoformat() if m.created_at else None,
        })
    return results


# ============================================================
# 匹配情况（绑定分布 + 覆盖度 + 低匹配项）
# ============================================================
def matching_overview(db: Session, task: AuditTask) -> dict:
    materials = list(task.materials)
    total_materials = len(materials)
    bound = sum(1 for m in materials if m.indicator_id)
    unbound = total_materials - bound

    # 指标覆盖度
    if task.scope == "selected":
        try:
            sel_ids = json.loads(task.selected_indicator_ids or "[]")
        except Exception:
            sel_ids = []
        target_ids = set(sel_ids)
    else:
        target_ids = {i.id for i in db.query(Indicator).all()}
    covered_ids = {m.indicator_id for m in materials if m.indicator_id and m.indicator_id in target_ids}
    uncovered_ids = target_ids - covered_ids
    uncovered = [
        {"indicator_code": i.indicator_code, "name": i.name}
        for i in db.query(Indicator).filter(Indicator.id.in_(uncovered_ids)).order_by(Indicator.indicator_code).all()
    ]

    # 从底稿读匹配度（按 indicator 维度）
    ws = db.query(Worksheet).filter(Worksheet.task_id == task.id).first()
    low_match_materials = []
    if ws:
        for row in ws.rows:
            try:
                fl = json.loads(row.material_flags or "{}")
            except Exception:
                fl = {}
            if fl.get("match_low"):
                for m in materials:
                    if m.indicator_id == row.indicator_id:
                        ind = db.get(Indicator, row.indicator_id)
                        low_match_materials.append({
                            "material_id": m.id,
                            "file_name": m.file_name,
                            "indicator_code": ind.indicator_code if ind else None,
                            "indicator_name": ind.name if ind else None,
                        })

    return {
        "total_materials": total_materials,
        "bound": bound,
        "unbound": unbound,
        "target_indicators": len(target_ids),
        "covered_indicators": len(covered_ids),
        "uncovered_indicators": len(uncovered_ids),
        "uncovered_list": uncovered[:20],   # 限前 20 条
        "low_match_materials": low_match_materials,
    }


# ============================================================
# 时间线（从 audit_log 聚合关键事件）
# ============================================================
_KEY_ACTIONS = {
    "task.create":       "📌 创建任务",
    "task.run":          "▶️ 触发 AI 核查",
    "material.upload":   "📎 上传材料",
    "material.bind":     "🔗 改绑材料指标",
    "material.auto_bind":"🤖 AI 自动绑定",
    "finding.review":    "✏️ 复核疑点",
    "worksheet.rebuild": "🔄 重建工作底稿",
    "worksheet.row.edit":"✏️ 编辑底稿单元格",
    "worksheet.finalize":"🔒 完成复核定稿",
    "worksheet.unlock":  "🔓 解锁底稿",
    "task.finalize":     "✅ 任务定稿",
}


def build_timeline(db: Session, task: AuditTask, limit: int = 50) -> list[dict]:
    """从 audit_log 聚合任务相关操作，返回时间倒序列表。"""
    logs = (
        db.query(AuditLog)
        .filter(AuditLog.action.in_(list(_KEY_ACTIONS.keys())))
        .filter(
            (AuditLog.target_type == "task") & (AuditLog.target_id == task.id)
            | (AuditLog.detail.like(f"%任务 #{task.id}%"))
            | (AuditLog.detail.like(f"%task#{task.id}%"))
        )
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .all()
    )

    out = []
    for log in logs:
        label = _KEY_ACTIONS.get(log.action, log.action)
        out.append({
            "at": log.created_at.isoformat() if log.created_at else None,
            "user": log.username,
            "action": log.action,
            "label": label,
            "detail": (log.detail or "")[:200],
        })
    return out


# ============================================================
# 聚合入口：整合 4 类数据
# ============================================================
def review_overview(db: Session, task: AuditTask) -> dict:
    materials = list(task.materials)
    bind_sources = {"by_keyword": 0, "by_ai": 0, "by_manual": 0, "unbound": 0}
    # 简化版分布判定：用 audit_log 中的 material.auto_bind / material.bind 记录
    bind_logs = (
        db.query(AuditLog)
        .filter(AuditLog.action.in_(("material.bind", "material.auto_bind")))
        .filter(AuditLog.detail.like(f"%任务 #{task.id}%"))
        .all()
    )
    # 启发式：auto_bind 一条记录代表多项；material.bind 单份手改
    has_auto_bind = any(l.action == "material.auto_bind" for l in bind_logs)
    manual_bound = sum(1 for l in bind_logs if l.action == "material.bind")

    for m in materials:
        if not m.indicator_id:
            bind_sources["unbound"] += 1
        elif has_auto_bind:
            bind_sources["by_ai"] += 1
        else:
            bind_sources["by_manual"] += 1
    # 简单粗略：把手改的数量从 by_ai 里扣回到 by_manual
    if manual_bound > 0 and bind_sources["by_ai"] >= manual_bound:
        bind_sources["by_manual"] += manual_bound
        bind_sources["by_ai"] -= manual_bound

    return {
        "task_id": task.id,
        "duplicates": detect_duplicates(db, task),
        "content_review": collect_content_review(db, task),
        "matching": matching_overview(db, task),
        "timeline": build_timeline(db, task),
        "bind_sources": bind_sources,
    }


# ============================================================
# 合并重复材料（保留首份，其它删除）
# ============================================================
def merge_duplicate_group(db: Session, task: AuditTask,
                         content_hash: str, keep_material_id: int,
                         user_id: Optional[int] = None) -> dict:
    """同任务下 content_hash 相同的一组材料里，保留 keep_material_id，删除其余。

    被删材料关联的 finding / worksheet_row.linked_finding_ids 不动（保留历史）。
    """
    group = (
        db.query(Material)
        .filter(
            Material.task_id == task.id,
            Material.content_hash == content_hash,
        ).all()
    )
    if not group:
        return {"removed": 0, "kept": None, "error": "未找到该重复组"}

    keep = next((m for m in group if m.id == keep_material_id), None)
    if not keep:
        return {"removed": 0, "kept": None, "error": "保留的材料 id 不在该组"}

    removed_ids = []
    for m in group:
        if m.id == keep_material_id:
            continue
        # 把它的 finding 解绑（material_id 设 NULL，保留 finding 本身）
        for f in db.query(Finding).filter(Finding.material_id == m.id).all():
            f.material_id = None
        # 删材料本身（不删物理文件，仅 DB 记录）
        removed_ids.append(m.id)
        db.delete(m)
    db.commit()
    return {
        "removed": len(removed_ids),
        "removed_ids": removed_ids,
        "kept": keep.id,
    }
