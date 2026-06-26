"""v1.7 改动测试：
1. 无绑定材料的指标不再写"完整性问题/低"finding
2. 扣分按 0.25 取整
"""
from __future__ import annotations

import pytest

from app.services.scoring_service import (
    DEDUCT_STEP, SEVERITY_DEDUCT_RATIO, _round_to_step, compute_task_scoring,
)


# ---------- 单元：取整函数 ----------

@pytest.mark.parametrize("raw, expected", [
    (0.00, 0.00),
    (0.10, 0.00),    # 向最近 0.25：0.10 → 0
    (0.13, 0.25),    # 0.13 → 0.25
    (0.25, 0.25),
    (0.30, 0.25),    # 向最近：0.30 → 0.25
    (0.40, 0.50),    # 向最近：0.40 → 0.50
    (0.50, 0.50),
    (0.75, 0.75),
    (1.40, 1.50),
    (2.00, 2.00),
])
def test_round_to_step_quarter(raw, expected):
    assert _round_to_step(raw) == pytest.approx(expected)


def test_deduct_step_constant():
    assert DEDUCT_STEP == 0.25


# ---------- 集成：评分扣分按 0.25 取整 ----------

def test_compute_task_scoring_rounds_to_quarter(admin_token):
    """max_score=3 + 一条"低"finding → raw 扣 0.30 → 取整 0.25。"""
    from app.main import app
    from app.models import (
        AuditTask, AuditUnit, Finding, Indicator, SessionLocal,
    )
    import uuid

    suffix = uuid.uuid4().hex[:6]
    db = SessionLocal()
    try:
        unit = AuditUnit(name=f"__V17_单位_{suffix}", code=f"V17{suffix}")
        db.add(unit); db.flush()
        task = AuditTask(unit_id=unit.id, name=f"__V17_任务_{suffix}",
                         eval_year=2026, scope="all")
        db.add(task); db.flush()
        ind = Indicator(indicator_code=f"I-V17-{suffix}",
                        name="V17扣分粒度指标", max_score=3.0)
        db.add(ind); db.flush()
        # 一条"低"finding：raw 扣 = 3 × 0.10 = 0.30 → 取整 0.25
        f = Finding(task_id=task.id, indicator_id=ind.id,
                    finding_type="合规性问题", severity="低",
                    description="V17 测试", review_status="pending",
                    source="rule")
        db.add(f); db.commit()

        result = compute_task_scoring(db, task)
        ind_out = next(i for i in result["indicators"]
                       if i["indicator_id"] == ind.id)
        assert ind_out["deducted"] == 0.25, f"应取整到 0.25，实际 {ind_out['deducted']}"
        assert ind_out["actual_score"] == 2.75
    finally:
        db.close()


# ---------- 集成：无材料指标不写 finding ----------

def test_orchestrator_skips_no_material_indicator():
    """orchestrator 的"无材料"分支已删 — 验证源码层不再有该 Finding 写入。"""
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "app" / "engine" / "orchestrator.py"
    text = src.read_text(encoding="utf-8")
    # 旧文案不应存在
    assert "未上传任何佐证材料" not in text, (
        "orchestrator 仍在为无材料指标写 finding（应删除）"
    )
    # 新注释应在
    assert "v1.7" in text and "无绑定材料的指标不写 finding" in text
