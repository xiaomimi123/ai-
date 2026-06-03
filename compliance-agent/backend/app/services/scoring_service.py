"""任务评分汇总服务。

扣分系数（先用固定值，未来支持管理员可配置）：
- 高风险 finding：扣指标满分 × 50%
- 中风险 finding：扣指标满分 × 25%
- 低风险 finding：扣指标满分 × 10%

复核状态权重：
- pending（未复核）：100%
- confirmed（已确认）：100%
- ignored（已忽略）：0%（不扣分）
- adjusted（已调整）：50%

等级阈值（百分比）：
- 优 ≥ 90
- 良 ≥ 80
- 中 ≥ 60
- 差 < 60
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Optional

from sqlalchemy.orm import Session

from app.models import AuditTask, Finding, Indicator


# 扣分系数 — TODO: 后续做成 AppSetting 可配置
SEVERITY_DEDUCT_RATIO = {
    "高": 0.50,
    "中": 0.25,
    "低": 0.10,
}

REVIEW_WEIGHT = {
    "pending": 1.0,
    "confirmed": 1.0,
    "ignored": 0.0,
    "adjusted": 0.5,
}


def _grade(score_pct: float) -> str:
    if score_pct >= 90:
        return "优"
    if score_pct >= 80:
        return "良"
    if score_pct >= 60:
        return "中"
    return "差"


def compute_task_scoring(db: Session, task: AuditTask) -> dict:
    """计算一个任务的评分明细 + 总分。

    返回结构：
    {
      "total_max": 100.0,
      "total_score": 76.5,
      "total_deducted": 23.5,
      "score_pct": 76.5,
      "grade": "良",
      "indicators": [{
        "indicator_id": 1, "indicator_code": "1-1-1", "name": "...",
        "category": "...", "max_score": 4.0,
        "deducted": 1.0, "actual_score": 3.0,
        "findings": {"高": 0, "中": 2, "低": 0, "ignored": 1},
      }, ...]
    }
    """
    # 决定要核查的指标集
    if task.scope == "selected":
        try:
            ids = json.loads(task.selected_indicator_ids or "[]")
        except Exception:
            ids = []
        indicators = db.query(Indicator).filter(Indicator.id.in_(ids)).all() if ids else []
    else:
        indicators = db.query(Indicator).order_by(Indicator.indicator_code).all()

    if not indicators:
        return {
            "total_max": 0, "total_score": 0, "total_deducted": 0,
            "score_pct": 0, "grade": "—", "indicators": [],
        }

    # 按 indicator_id 索引 finding
    findings = db.query(Finding).filter(Finding.task_id == task.id).all()
    by_indicator = defaultdict(list)
    for f in findings:
        if f.indicator_id:
            by_indicator[f.indicator_id].append(f)

    indicators_out = []
    total_max = 0.0
    total_deducted = 0.0

    for ind in indicators:
        max_sc = float(ind.max_score or 0)
        total_max += max_sc

        ind_findings = by_indicator.get(ind.id, [])
        sev_count = {"高": 0, "中": 0, "低": 0, "ignored": 0}
        deducted = 0.0
        for f in ind_findings:
            sev = f.severity if f.severity in SEVERITY_DEDUCT_RATIO else "中"
            review = f.review_status or "pending"
            if review == "ignored":
                sev_count["ignored"] += 1
                continue
            sev_count[sev] = sev_count.get(sev, 0) + 1
            ratio = SEVERITY_DEDUCT_RATIO[sev] * REVIEW_WEIGHT.get(review, 1.0)
            deducted += max_sc * ratio

        # 裁剪到 [0, max_sc]
        deducted = min(deducted, max_sc)
        actual = max(0.0, max_sc - deducted)
        total_deducted += deducted

        indicators_out.append({
            "indicator_id": ind.id,
            "indicator_code": ind.indicator_code,
            "name": ind.name,
            "category": ind.category,
            "level": ind.level,
            "max_score": max_sc,
            "deducted": round(deducted, 2),
            "actual_score": round(actual, 2),
            "findings_total": len(ind_findings),
            "by_severity": sev_count,
        })

    total_score = total_max - total_deducted
    score_pct = (total_score / total_max * 100) if total_max > 0 else 0.0

    return {
        "total_max": round(total_max, 2),
        "total_score": round(total_score, 2),
        "total_deducted": round(total_deducted, 2),
        "score_pct": round(score_pct, 2),
        "grade": _grade(score_pct),
        "indicators": indicators_out,
        "rules": {
            "severity_deduct": SEVERITY_DEDUCT_RATIO,
            "review_weight": REVIEW_WEIGHT,
            "grades": {"优": ">=90", "良": ">=80", "中": ">=60", "差": "<60"},
        },
    }
