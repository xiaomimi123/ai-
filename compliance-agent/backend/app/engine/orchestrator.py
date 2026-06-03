"""核查任务编排（v3 §3.4）。

run_audit：对一个 AuditTask 内所有材料执行完整核查流程
（先刚性规则、后 LLM 语义、聚合 Finding 写入 DB）。
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.engine.llm_checker import LLMFinding, run_llm_checks
from app.engine.rule_checker import RuleFinding, run_rule_checks
from app.llm import get_llm_client
from app.models import AuditTask, CheckItem, Finding, Indicator, Material
from app.parsers.base import KeyElements


def _ke_from_json(raw: str) -> KeyElements:
    """从 Material.key_elements JSON 还原为对象。"""
    try:
        d = json.loads(raw or "{}")
    except Exception:
        d = {}
    ke = KeyElements()
    for k, v in d.items():
        if hasattr(ke, k):
            setattr(ke, k, v)
    return ke


def _retrieve_legal_basis(indicator: Optional[Indicator]) -> str:
    """根据指标从 RAG 向量库召回法规条款（v3 §3.1、§3.4）。

    检索来源：法规库上传的法规（通过 regulation_service 已 chunk 入 Qdrant）。
    召回结果与指标自身的扣分细则 + 常见扣分情形 一起注入 LLM Prompt。
    """
    if indicator is None:
        return "（暂无指标关联法规）"

    parts = []

    # 1) 从向量库 RAG 召回（v3 §3.4 强调"来自 RAG 检索附件 1/2"）
    try:
        from app.rag import get_retriever

        # 多角度检索：指标名 + 子类 + 分类 + 评价办法关键词
        query = (
            f"{indicator.name} {indicator.category} {indicator.subcategory} "
            f"内控评价 评价指标 扣分细则"
        )
        retriever = get_retriever()
        hits = retriever.retrieve(query, top_k=5)
        if hits:
            rag_lines = []
            for h in hits:
                meta = getattr(h, "metadata", {}) or {}
                citation = meta.get("citation") or meta.get("law_name") or meta.get("source") or "法规"
                # 截断单条法规以控制 token
                text = (h.text or "").strip()[:600]
                rag_lines.append(f"[{citation}] {text}")
            parts.append("【RAG 召回法规条款】\n" + "\n\n".join(rag_lines))
    except Exception as exc:
        print(f"[RAG] 召回失败: {exc}")

    # 2) 指标自身的扣分细则作为黄金参照（v3 §3.1 黄金数据）
    if indicator.deduct_rules:
        parts.append(f"【评分细则】{indicator.deduct_rules}")
    if indicator.common_deductions:
        parts.append(f"【常见扣分情形】{indicator.common_deductions}")

    return "\n\n".join(parts) if parts else "（暂无指标关联法规）"


def _resolve_target_indicators(db: Session, task: AuditTask) -> List[Indicator]:
    """根据任务 scope 决定要核查的指标集。"""
    if task.scope == "selected":
        try:
            ids = json.loads(task.selected_indicator_ids or "[]")
        except Exception:
            ids = []
        if not ids:
            return []
        return db.query(Indicator).filter(Indicator.id.in_(ids)).all()
    # scope=all：全部入库指标
    return db.query(Indicator).order_by(Indicator.indicator_code).all()


def _materials_for_indicator(materials: List[Material], indicator: Indicator) -> List[Material]:
    """为某个指标筛选关联材料：
    1) 显式绑定该指标的材料优先（最强信号）
    2) 未绑定材料按文件名/路径关键词命中本指标 subcategory → 子集参与
    3) 都没有 → 返回空，orchestrator 会记一条"缺失材料"warning（不再调 LLM）

    设计取舍：不走共享池兜底（旧行为）——那会导致 23 份材料 × 55 指标 = 1265 次
    LLM 调用的爆炸。宁可让 17 个组织层面指标标"未上传"，也比 3 小时核查强。
    """
    bound = [m for m in materials if m.indicator_id == indicator.id]
    if bound:
        return bound
    from app.services.material_matcher import filter_materials_by_subcategory
    unbound = [m for m in materials if not m.indicator_id]
    if not unbound:
        return []
    return filter_materials_by_subcategory(unbound, indicator)


def run_audit(db: Session, task: AuditTask) -> AuditTask:
    """对 AuditTask 执行完整核查（v3 §3.4）。

    新版逻辑（支持全量/选定指标核查 + 文件夹批量材料）：
    1. 根据 task.scope 确定要核查的「指标集」
    2. 对每个指标，挑选「关联材料」（显式绑定优先，否则用共享未绑定材料）
    3. 对每个 (指标, 材料) 跑：刚性规则 + LLM 语义
    4. 聚合 finding，写入 DB

    若任务下没有任何指标关联材料，会在该指标维度产生一条「缺失材料」warning。
    """
    task.status = "running"
    task.summary = "AI 核查中…"
    task.progress_current = 0
    task.progress_total = 0
    task.progress_text = "准备中…"
    db.commit()

    try:
        check_items = db.query(CheckItem).filter(CheckItem.is_active == True).all()

        # 清理旧 finding（重新核查）
        db.query(Finding).filter(Finding.task_id == task.id).delete()
        db.flush()

        # 准备 LLM 客户端（支持快速模式：跳过思考过程）
        llm = get_llm_client(db)
        from app.llm.stub import StubLLMClient
        llm_available = not isinstance(llm, StubLLMClient)
        if task.fast_mode and hasattr(llm, "thinking_mode"):
            try:
                llm.thinking_mode = "off"   # type: ignore[attr-defined]
            except Exception:
                pass

        materials = list(task.materials)
        target_indicators = _resolve_target_indicators(db, task)

        # 没有目标指标 → 用户没选指标 / 知识库空
        if not target_indicators:
            task.stats = json.dumps({
                "materials_total": len(materials),
                "indicators_checked": 0,
                "findings_total": 0,
                "by_severity": {"高": 0, "中": 0, "低": 0},
                "by_type": {},
            }, ensure_ascii=False)
            task.summary = "未匹配到任何评价指标，请先在「评价指标库」录入指标。"
            task.status = "ai_done"
            task.completed_at = datetime.utcnow()
            db.commit()
            db.refresh(task)
            return task

        # 主循环：对每个指标 × 关联材料 跑核查
        task.progress_total = len(target_indicators)
        db.commit()

        indicators_checked = 0
        for idx, indicator in enumerate(target_indicators, start=1):
            # 进度回写（让前端轮询能看到）
            label_name = (indicator.name or "")[:28]
            task.progress_text = f"{indicator.indicator_code} {label_name}"
            db.commit()

            related = _materials_for_indicator(materials, indicator)
            if not related:
                # V3：未上传材料 → 低风险提示（不再按中风险扣 25%，改为只扣 10%）
                db.add(Finding(
                    task_id=task.id,
                    material_id=None,
                    indicator_id=indicator.id,
                    check_item_id=None,
                    finding_type="完整性问题",
                    severity="低",
                    description=f"指标【{indicator.indicator_code} {indicator.name}】未上传任何佐证材料。",
                    evidence_location="—",
                    legal_basis=indicator.deduct_rules or "",
                    suggestion=f"请补充与指标【{indicator.name}】相关的材料（建议：{indicator.required_materials or '查看指标定义'}）",
                    source="rule",
                ))
                task.progress_current = idx
                db.commit()
                continue

            indicators_checked += 1
            for material in related:
                text = material.parsed_text or ""
                ke = _ke_from_json(material.key_elements)

                # 1) 刚性规则
                rule_results = run_rule_checks(
                    material, text, ke, indicator, check_items,
                    eval_year=task.eval_year,
                )
                for r in rule_results:
                    db.add(_to_finding(task.id, material.id, indicator, r, source="rule"))

                # 2) LLM 语义
                if llm_available:
                    legal_basis = _retrieve_legal_basis(indicator)
                    llm_results = run_llm_checks(
                        llm, material, text, indicator, check_items, legal_basis=legal_basis,
                    )
                    for l in llm_results:
                        db.add(_to_finding(task.id, material.id, indicator, l, source="llm"))

            task.progress_current = idx
            db.commit()

        db.flush()
        # V3：去重聚合 — 同 (material, indicator, type) 下只保留最严重 1 条
        _dedupe_findings(db, task.id)
        task.progress_text = "汇总评分中…"
        db.commit()

        # 聚合统计 + 评分
        all_findings = db.query(Finding).filter(Finding.task_id == task.id).all()
        stats = _build_stats(materials, all_findings, target_indicators, indicators_checked)

        # 附加评分汇总（功能 3）
        from app.services.scoring_service import compute_task_scoring
        try:
            scoring = compute_task_scoring(db, task)
            stats["scoring"] = scoring
        except Exception as exc:
            print(f"[scoring] 计算失败: {exc}")

        task.stats = json.dumps(stats, ensure_ascii=False)
        task.summary = _build_summary(stats, llm_available)
        task.status = "ai_done"
        task.completed_at = datetime.utcnow()
        task.progress_text = "底稿生成中…"
        db.commit()

        # 生成工作底稿草案（V1：AI 阅卷产物）
        from app.services.worksheet_service import build_worksheet_draft
        try:
            build_worksheet_draft(db, task)
        except Exception as exc:
            print(f"[worksheet] 底稿生成失败: {exc}")

        # 标记进度完成
        task.progress_text = "完成"
    except Exception as exc:
        task.status = "failed"
        task.summary = f"核查失败：{exc}"
        task.progress_text = f"失败：{exc}"[:256]

    db.commit()
    db.refresh(task)
    return task


# V3：所有 finding_type 统一归类到 5 种（不再有"正式性""年度一致性""相关性"等细分）
_TYPE_CANONICAL_MAP = {
    "真实性问题": "真实性问题",
    "正式性问题": "真实性问题",
    "年度一致性问题": "真实性问题",
    "完整性问题": "完整性问题",
    "要素完整性问题": "完整性问题",
    "合规性问题": "合规性问题",
    "相关性问题": "合规性问题",
    "评分合规问题": "合规性问题",
    "复核规范问题": "合规性问题",
    "报告编报问题": "合规性问题",
    "重复性问题": "重复性问题",
    "匹配性问题": "匹配性问题",
}

_VALID_TYPES = {"真实性问题", "完整性问题", "合规性问题", "重复性问题", "匹配性问题"}


def canonical_finding_type(raw: str) -> str:
    """把任何 raw finding_type 映射到 5 种规范类型之一。"""
    if not raw:
        return "合规性问题"
    if raw in _VALID_TYPES:
        return raw
    return _TYPE_CANONICAL_MAP.get(raw, "合规性问题")


def _to_finding(task_id: int, material_id: Optional[int],
                indicator: Optional[Indicator],
                fr, source: str) -> Finding:
    """RuleFinding | LLMFinding → DB Finding。

    若 indicator 有 description 且 RuleFinding 自身没设置 legal_basis，
    则把指标要求作为「评价标准」附在 legal_basis 字段，便于报告引用。
    """
    ind_id = indicator.id if indicator else None
    # 补全 legal_basis（评价标准 + 法规依据）
    def _enrich(fr_legal: str) -> str:
        if fr_legal:
            return fr_legal
        if indicator and indicator.deduct_rules:
            return f"【评价指标要求】{indicator.name}：{indicator.description or indicator.name}\n【扣分细则】{indicator.deduct_rules}"
        if indicator:
            return f"【评价指标要求】{indicator.indicator_code} {indicator.name}"
        return ""

    if isinstance(fr, RuleFinding):
        return Finding(
            task_id=task_id, material_id=material_id, indicator_id=ind_id,
            check_item_id=fr.check_item_id,
            finding_type=canonical_finding_type(fr.finding_type), severity=fr.severity,
            description=fr.description, evidence_location=fr.evidence_location,
            legal_basis=_enrich(fr.legal_basis), suggestion=fr.suggestion,
            source=source,
        )
    if isinstance(fr, LLMFinding):
        return Finding(
            task_id=task_id, material_id=material_id, indicator_id=ind_id,
            check_item_id=None,
            finding_type=canonical_finding_type(fr.finding_type), severity=fr.severity,
            description=fr.description, evidence_location=fr.evidence_location,
            legal_basis=_enrich(fr.legal_basis), suggestion=fr.suggestion,
            source=source,
        )
    raise TypeError(f"未知 finding 类型：{type(fr)}")


SEVERITY_ORDER = {"高": 0, "中": 1, "低": 2}


def _dedupe_findings(db: Session, task_id: int) -> int:
    """同 (material_id, indicator_id, finding_type) 去重，保留最严重的 1 条。

    返回删除的条数。会把被删条目的关键描述追加到保留条的 description。
    """
    findings = db.query(Finding).filter(Finding.task_id == task_id).all()
    by_key: dict[tuple, list[Finding]] = {}
    for f in findings:
        key = (f.material_id, f.indicator_id, f.finding_type)
        by_key.setdefault(key, []).append(f)

    deleted = 0
    for key, group in by_key.items():
        if len(group) <= 1:
            continue
        group.sort(key=lambda f: SEVERITY_ORDER.get(f.severity, 9))
        keep = group[0]
        merged_extras = []
        for dup in group[1:]:
            if dup.description and dup.description not in (keep.description or ""):
                # 只保留前 30 字摘要
                snippet = dup.description.strip().split("。")[0][:30]
                if snippet:
                    merged_extras.append(snippet)
            db.delete(dup)
            deleted += 1
        if merged_extras:
            extra = "；".join(merged_extras[:2])  # 最多附 2 条摘要
            keep.description = f"{keep.description}\n（同时检出：{extra}）"
    if deleted:
        db.flush()
    return deleted


def _build_stats(materials: List[Material], findings: List[Finding],
                 target_indicators: List[Indicator] = None,
                 indicators_with_materials: int = 0) -> dict:
    severity = Counter(f.severity for f in findings)
    by_type = Counter(f.finding_type for f in findings)
    return {
        "materials_total": len(materials),
        "indicators_total": len(target_indicators or []),
        "indicators_checked": indicators_with_materials,
        "indicators_no_material": (len(target_indicators or []) - indicators_with_materials)
                                   if target_indicators else 0,
        "findings_total": len(findings),
        "by_severity": {
            "高": severity.get("高", 0),
            "中": severity.get("中", 0),
            "低": severity.get("低", 0),
        },
        "by_type": dict(by_type),
    }


def _build_summary(stats: dict, llm_used: bool) -> str:
    total = stats["findings_total"]
    indicators_total = stats.get("indicators_total", 0)
    indicators_checked = stats.get("indicators_checked", 0)
    no_material = stats.get("indicators_no_material", 0)
    scoring = stats.get("scoring") or {}

    coverage = f"（覆盖 {indicators_checked}/{indicators_total} 项指标"
    if no_material:
        coverage += f"，{no_material} 项指标无材料"
    coverage += "）"

    score_part = ""
    if scoring and scoring.get("total_max"):
        score_part = (f" · 评分 {scoring['total_score']}/{scoring['total_max']} "
                      f"({scoring['score_pct']}%，等级 {scoring['grade']})")

    if total == 0:
        return f"AI 初核完成，未发现问题{coverage}{score_part}。"
    sev = stats["by_severity"]
    suffix = "" if llm_used else "（LLM 未配置 API Key，仅运行了刚性规则）"
    return (f"AI 初核完成，共 {total} 条疑点："
            f"高 {sev['高']} / 中 {sev['中']} / 低 {sev['低']}{coverage}{score_part}{suffix}")
