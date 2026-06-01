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


def run_audit(db: Session, task: AuditTask) -> AuditTask:
    """对 AuditTask 执行完整核查。"""
    task.status = "running"
    task.summary = "AI 核查中…"
    db.commit()

    try:
        # 加载活跃的全部问题清单
        check_items = db.query(CheckItem).filter(CheckItem.is_active == True).all()

        # 清理旧 finding（重新核查）
        db.query(Finding).filter(Finding.task_id == task.id).delete()
        db.flush()

        # 准备 LLM 客户端（按当前 AppSetting 配置）
        llm = get_llm_client(db)
        from app.llm.stub import StubLLMClient
        llm_available = not isinstance(llm, StubLLMClient)

        materials = list(task.materials)
        for material in materials:
            indicator = db.get(Indicator, material.indicator_id) if material.indicator_id else None
            text = material.parsed_text or ""
            ke = _ke_from_json(material.key_elements)

            # 1) 刚性规则
            rule_results = run_rule_checks(
                material, text, ke, indicator, check_items,
                eval_year=task.eval_year,
            )
            for r in rule_results:
                db.add(_to_finding(task.id, material.id, indicator, r, source="rule"))

            # 2) LLM 语义（仅在 LLM 可用时执行）
            if llm_available:
                legal_basis = _retrieve_legal_basis(indicator)
                llm_results = run_llm_checks(
                    llm, material, text, indicator, check_items, legal_basis=legal_basis,
                )
                for l in llm_results:
                    db.add(_to_finding(task.id, material.id, indicator, l, source="llm"))

        db.flush()

        # 聚合统计
        all_findings = db.query(Finding).filter(Finding.task_id == task.id).all()
        stats = _build_stats(materials, all_findings)
        task.stats = json.dumps(stats, ensure_ascii=False)
        task.summary = _build_summary(stats, llm_available)
        task.status = "ai_done"
        task.completed_at = datetime.utcnow()
    except Exception as exc:
        task.status = "failed"
        task.summary = f"核查失败：{exc}"

    db.commit()
    db.refresh(task)
    return task


def _to_finding(task_id: int, material_id: int,
                indicator: Optional[Indicator],
                fr, source: str) -> Finding:
    """RuleFinding | LLMFinding → DB Finding。"""
    ind_id = indicator.id if indicator else None
    if isinstance(fr, RuleFinding):
        return Finding(
            task_id=task_id, material_id=material_id, indicator_id=ind_id,
            check_item_id=fr.check_item_id,
            finding_type=fr.finding_type, severity=fr.severity,
            description=fr.description, evidence_location=fr.evidence_location,
            legal_basis=fr.legal_basis, suggestion=fr.suggestion,
            source=source,
        )
    if isinstance(fr, LLMFinding):
        return Finding(
            task_id=task_id, material_id=material_id, indicator_id=ind_id,
            check_item_id=None,
            finding_type=fr.finding_type, severity=fr.severity,
            description=fr.description, evidence_location=fr.evidence_location,
            legal_basis=fr.legal_basis, suggestion=fr.suggestion,
            source=source,
        )
    raise TypeError(f"未知 finding 类型：{type(fr)}")


def _build_stats(materials: List[Material], findings: List[Finding]) -> dict:
    severity = Counter(f.severity for f in findings)
    by_type = Counter(f.finding_type for f in findings)
    indicators_checked = len({m.indicator_id for m in materials if m.indicator_id})
    return {
        "materials_total": len(materials),
        "indicators_checked": indicators_checked,
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
    if total == 0:
        return "AI 初核完成，未发现问题（刚性规则通过；柔性规则无报告）。"
    sev = stats["by_severity"]
    suffix = "" if llm_used else "（LLM 未配置 API Key，仅运行了刚性规则）"
    return (f"AI 初核完成，共 {total} 条疑点："
            f"高 {sev['高']} / 中 {sev['中']} / 低 {sev['低']}{suffix}")
