"""工作底稿服务（V1：AI 阅卷 → 底稿草案）。

流程：AI 跑完 → build_worksheet_draft：
1. 列出本任务范围内的全部指标（scope=all / selected）
2. 对每条指标：
   - original_score：先 AI 抽自评分；找不到 fallback = max_score
   - audited_score：复用 scoring_service 的扣分公式
   - audit_finding_text：拼该指标下 Finding 的 description（≤150 字），无 finding 时用模板
   - material_flags：7 对 14 项布尔
     真实/虚假、相关/无关、有效/无效、完整/不完整、合规/不合规、重复/独有、匹配高/匹配低
3. 1:1 写入 Worksheet + WorksheetRow（旧底稿先删后写）

V1 保持"重跑覆盖"：每次跑 AI 审都重建底稿；V2 引入定稿锁。
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Dict, List, Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.models import (
    AuditTask,
    AuditUnit,
    Finding,
    Indicator,
    Material,
    Worksheet,
    WorksheetRow,
)
from app.services.scoring_service import (
    REVIEW_WEIGHT, SEVERITY_DEDUCT_RATIO, _round_to_step,
)


# 新底稿模板 5 对 10 项（按新版列顺序）
FLAG_PAIRS: List[tuple[str, str, str, str]] = [
    # (pos_key, pos_label, neg_key, neg_label)
    ("real",       "材料真实可靠",        "fake",          "材料涉嫌造假"),
    ("complete",   "材料完整",            "incomplete",    "材料不完整"),
    ("compliant",  "材料内容合法合规",    "non_compliant", "材料内容可能违法违规"),
    ("unique",     "材料与其他单位不重复", "duplicate",     "材料与其他单位重复"),
    ("match_high", "材料匹配度高",        "match_low",     "材料匹配度低"),
]

# 旧字段保留兼容（不在 UI 展示，仅 DB 仍写入用于回溯）
LEGACY_FLAG_KEYS = ("relevant", "irrelevant", "effective", "ineffective")


MATCH_THRESHOLD = 0.70  # ≥70% 算匹配度高


# ============================================================
# 工具：自评分（AI 抽 / fallback）
# ============================================================
def _extract_self_scores(db: Session, task: AuditTask,
                         indicators: List[Indicator]) -> Dict[int, float]:
    """从任务下材料文本里抽出每条指标的"核查前得分"。

    V1 用一次性 prompt：给 LLM 一段自评汇总文本 + 全部指标的 (code, name, max_score)，
    要求返回 {indicator_code: score}。Stub 模式或抽不到时回退 = max_score。
    """
    fallback = {ind.id: float(ind.max_score) for ind in indicators}

    materials: List[Material] = list(task.materials)
    if not materials:
        return fallback

    # 拼一段汇总文本（截断防爆 prompt）
    blob_parts: List[str] = []
    for m in materials:
        if m.parsed_text:
            blob_parts.append(f"### 材料《{m.file_name}》\n{m.parsed_text[:3000]}")
        if sum(len(p) for p in blob_parts) > 30000:
            break
    blob = "\n\n".join(blob_parts)

    # 仅当 blob 里出现典型自评字样才请求 LLM，否则直接 fallback
    if not any(kw in blob for kw in ("自评", "自评分", "自我评价", "得分情况")):
        return fallback

    try:
        from app.llm.factory import get_llm_client
        llm = get_llm_client(db)
        index = [
            {"code": ind.indicator_code, "name": ind.name, "max_score": ind.max_score}
            for ind in indicators
        ]
        system = "你是内控评价审计助理。仅从给定材料文本中抽取被检查单位的自评分。"
        prompt = (
            "请阅读以下被检查单位上传的材料，找出其对每项指标的自评分数。"
            f"指标列表（共 {len(index)} 项）：\n```json\n"
            f"{json.dumps(index, ensure_ascii=False)}\n```\n\n"
            f"材料文本：\n{blob}\n\n"
            "请仅返回纯 JSON：{\"scores\": {\"I-01\": 2.0, ...}}。"
            "找不到的指标不要列。score 不要超过 max_score。"
        )
        raw = llm.extract_json(prompt, system=system, max_tokens=4096)
        if isinstance(raw, dict):
            scores = raw.get("scores", {})
            if isinstance(scores, dict):
                # code -> id 映射
                code2id = {ind.indicator_code: ind.id for ind in indicators}
                for code, val in scores.items():
                    iid = code2id.get(code)
                    if iid is None:
                        continue
                    try:
                        v = float(val)
                        # 裁剪 [0, max_score]
                        max_sc = fallback[iid]
                        fallback[iid] = max(0.0, min(v, max_sc))
                    except Exception:
                        pass
    except Exception as exc:
        print(f"[worksheet] 自评分抽取失败（fallback 满分）: {exc}")

    return fallback


# ============================================================
# 工具：材料查重 + 匹配度
# ============================================================
def _material_dup_check(db: Session, task: AuditTask,
                        indicator_id: int) -> bool:
    """该指标下任一份材料的指纹在其他任务出现过 → 视为 duplicate。"""
    my_mats = [m for m in task.materials if m.indicator_id == indicator_id]
    if not my_mats:
        return False
    hashes = {m.content_hash for m in my_mats if m.content_hash}
    fps = {m.content_fingerprint for m in my_mats if m.content_fingerprint}
    if not hashes and not fps:
        return False
    # 在 Material 表里找 task_id != 当前 task 且 hash/fp 命中
    q = db.query(Material).filter(Material.task_id != task.id)
    matched = q.filter(
        (Material.content_hash.in_(hashes) if hashes else False) |
        (Material.content_fingerprint.in_(fps) if fps else False)
    ).first()
    return matched is not None


def _material_match_ratio(indicator: Indicator,
                          task_materials: List[Material]) -> float:
    """required_materials vs 实际上传材料的语义匹配率（V1 用关键字命中近似）。"""
    try:
        required = json.loads(indicator.required_materials or "[]")
    except Exception:
        required = []
    if not required:
        return 1.0  # 未声明要求 → 视为已满足

    # 仅看绑定到本指标的材料文件名 + 解析文本头部
    my_mats = [m for m in task_materials if m.indicator_id == indicator.id]
    if not my_mats:
        return 0.0

    haystack = " ".join(
        (m.file_name or "") + " " + (m.parsed_text or "")[:2000]
        for m in my_mats
    )
    hit = sum(1 for req in required if str(req).strip() and str(req) in haystack)
    return hit / len(required) if required else 1.0


# ============================================================
# 工具：核查情况说明（基于 finding 拼接）
# ============================================================
def _build_audit_text(indicator: Indicator,
                      findings: List[Finding],
                      score_delta: float) -> str:
    """生成"核查情况说明"（≤150 字）。

    V1 用规则化拼接（避免每条指标都调一次 LLM）：
    - 无 finding：「材料齐全，未发现疑点。」
    - 有 finding：按严重度排序，列前 2 条 description + 扣分总额
    """
    if not findings:
        return "材料齐全，未发现疑点，建议维持核查前得分。"

    sev_order = {"高": 0, "中": 1, "低": 2}
    valid = [f for f in findings if (f.review_status or "pending") != "ignored"]
    valid.sort(key=lambda f: sev_order.get(f.severity, 9))

    bullets = []
    for f in valid[:2]:
        desc = (f.description or "").strip().replace("\n", "")
        if len(desc) > 50:
            desc = desc[:50] + "…"
        bullets.append(f"{f.severity}：{desc}")
    suffix = f" 合计扣 {score_delta:.2f} 分。" if score_delta > 0 else ""
    text = "；".join(bullets) + "。" + suffix
    if len(text) > 150:
        text = text[:147] + "…"
    return text


# ============================================================
# 主函数：build_worksheet_draft
# ============================================================
def build_worksheet_draft(db: Session, task: AuditTask) -> Worksheet:
    """根据任务的 Finding + 材料情况，构建/覆盖一份工作底稿草案。"""
    # 1) 任务的指标范围
    if task.scope == "selected":
        try:
            sel_ids = json.loads(task.selected_indicator_ids or "[]")
        except Exception:
            sel_ids = []
        indicators = db.query(Indicator).filter(Indicator.id.in_(sel_ids))\
            .order_by(Indicator.indicator_code).all() if sel_ids else []
    else:
        indicators = db.query(Indicator).order_by(Indicator.indicator_code).all()

    # 2) 删除旧底稿（重跑覆盖）
    old = db.query(Worksheet).filter(Worksheet.task_id == task.id).first()
    if old:
        db.delete(old); db.flush()

    # 3) 拉单位信息
    unit = db.get(AuditUnit, task.unit_id)

    ws = Worksheet(
        task_id=task.id,
        unit_name=(unit.name if unit else ""),
        unit_code=(unit.code if unit else ""),
        auditor_name="",
        reviewer_name="",
        status="draft",
    )
    db.add(ws); db.flush()

    # 4) 自评分（一次性抽取）
    self_scores = _extract_self_scores(db, task, indicators)

    # 5) Finding 按 indicator 分组
    all_findings = db.query(Finding).filter(Finding.task_id == task.id).all()
    by_ind: Dict[int, List[Finding]] = defaultdict(list)
    for f in all_findings:
        if f.indicator_id:
            by_ind[f.indicator_id].append(f)

    # 6) 每条指标一行
    for serial, ind in enumerate(indicators, start=1):
        ind_findings = by_ind.get(ind.id, [])
        max_sc = float(ind.max_score or 0)
        orig = float(self_scores.get(ind.id, max_sc))

        # 算扣分（复用 scoring_service 的公式）
        deducted = 0.0
        for f in ind_findings:
            review = f.review_status or "pending"
            if review == "ignored":
                continue
            sev = f.severity if f.severity in SEVERITY_DEDUCT_RATIO else "中"
            ratio = SEVERITY_DEDUCT_RATIO[sev] * REVIEW_WEIGHT.get(review, 1.0)
            deducted += max_sc * ratio
        deducted = min(deducted, max_sc)
        deducted = _round_to_step(deducted)  # v1.7：扣分粒度 0.25
        audited = max(0.0, max_sc - deducted)

        # 7 对 14 项打标
        finding_types = " ".join(f.finding_type or "" for f in ind_findings)
        finding_descs = " ".join(f.description or "" for f in ind_findings)

        is_dup = _material_dup_check(db, task, ind.id)
        match_ratio = _material_match_ratio(ind, list(task.materials))

        any_material_for_ind = any(m.indicator_id == ind.id for m in task.materials)

        flags = {
            # 真实性
            "real":       not ("真实" in finding_types or "虚假" in finding_descs),
            "fake":       ("虚假" in finding_descs or "真实" in finding_types),
            # 相关性
            "relevant":   any_material_for_ind,
            "irrelevant": (not any_material_for_ind),
            # 有效性
            "effective":  not ("无效" in finding_descs),
            "ineffective": ("无效" in finding_descs),
            # 完整性
            "complete":   not ("完整" in finding_types or "不完整" in finding_descs or "缺" in finding_descs),
            "incomplete": ("完整" in finding_types or "不完整" in finding_descs or "缺" in finding_descs),
            # 合规性
            "compliant":  not ("合规" in finding_types or "不符合" in finding_descs),
            "non_compliant": ("合规" in finding_types or "不符合" in finding_descs),
            # 跨任务查重
            "duplicate":  is_dup,
            "unique":     not is_dup,
            # 匹配度
            "match_high": match_ratio >= MATCH_THRESHOLD,
            "match_low":  match_ratio < MATCH_THRESHOLD,
        }

        # V3：material_flags 触发的"重复性 / 匹配性"Finding 也写入数据库
        # （让维度分布统计和"按维度批量忽略"能命中）
        # v1.8：无任何绑定材料的指标直接跳过这两类 finding——既无材料可言，
        # 不应再产生"匹配率 0%"或"材料重复"这种针对性误报（与 v1.7 orchestrator
        # 跳过逻辑对齐）
        if any_material_for_ind and is_dup:
            # 先看是否已存在同 indicator 的重复性问题
            existed = any(f.finding_type == "重复性问题" for f in ind_findings)
            if not existed:
                from app.models import Finding as _F
                dup_finding = _F(
                    task_id=task.id, material_id=None, indicator_id=ind.id,
                    check_item_id=None,
                    finding_type="重复性问题", severity="中",
                    description=f"指标【{ind.indicator_code} {ind.name}】下的材料与其他任务/单位存在重复，疑似抄送。",
                    evidence_location="材料指纹",
                    legal_basis="审计材料应为本单位真实产出，跨单位重复材料不应作为独立佐证。",
                    suggestion="核实该材料的原始来源；若确为本单位材料应提供说明。",
                    source="rule",
                )
                db.add(dup_finding)
                ind_findings.append(dup_finding)
        if any_material_for_ind and match_ratio < MATCH_THRESHOLD:
            existed_match = any(f.finding_type == "匹配性问题" for f in ind_findings)
            if not existed_match:
                from app.models import Finding as _F
                match_finding = _F(
                    task_id=task.id, material_id=None, indicator_id=ind.id,
                    check_item_id=None,
                    finding_type="匹配性问题", severity="低",
                    description=f"指标【{ind.indicator_code} {ind.name}】上传材料与"
                                f"指标要求的材料类型匹配率仅 {match_ratio:.0%}（阈值 70%）。",
                    evidence_location="—",
                    legal_basis=f"指标要求材料：{ind.required_materials or '查看指标定义'}",
                    suggestion="补充更对口的佐证材料，或确认绑定到正确指标。",
                    source="rule",
                )
                db.add(match_finding)
                ind_findings.append(match_finding)

        row = WorksheetRow(
            worksheet_id=ws.id,
            indicator_id=ind.id,
            serial=serial,
            original_score=orig,
            audited_score=audited,
            audit_finding_text=_build_audit_text(ind, ind_findings, deducted),
            material_flags=json.dumps(flags, ensure_ascii=False),
            linked_finding_ids=json.dumps([f.id for f in ind_findings if f.id], ensure_ascii=False),
        )
        db.add(row)

    db.commit()
    db.refresh(ws)
    return ws


# ============================================================
# 查询
# ============================================================
def get_worksheet(db: Session, task_id: int) -> Optional[Worksheet]:
    return db.query(Worksheet).filter(Worksheet.task_id == task_id).first()
