"""v2.2 LLM 余额不足友好提示测试。

单元测试直接验证 orchestrator._classify_run_audit_error 分类逻辑；
集成测试在 Task 4 追加，通过 monkeypatch LLM 让 run_audit 走 402 分支。
"""
from __future__ import annotations

import pytest


# ============================================================
# 单元：_classify_run_audit_error 分类逻辑
# ============================================================
def test_classify_insufficient_balance_deepseek_style():
    """DeepSeek 官方 402 报文的字符串形式，应归类为 insufficient_balance。"""
    from app.engine.orchestrator import _classify_run_audit_error

    exc = Exception(
        "Error code: 402 - {'error': "
        "{'message': 'Insufficient Balance', 'type': 'authentication_error', "
        "'code': 'insufficient_balance'}}"
    )
    kind, summary = _classify_run_audit_error(exc)
    assert kind == "insufficient_balance", f"kind={kind!r}"
    assert "余额不足" in summary, f"summary={summary!r}"
    assert "联系管理员" in summary
    assert "重新运行" in summary


def test_classify_generic_error():
    """非余额类的通用异常应回退到 generic 分类 + 保留技术错误信息。"""
    from app.engine.orchestrator import _classify_run_audit_error

    exc = Exception("网络超时 timeout after 30s")
    kind, summary = _classify_run_audit_error(exc)
    assert kind == "generic"
    assert summary.startswith("核查失败：")
    assert "网络超时" in summary


def test_classify_case_insensitive_and_chinese_needles():
    """匹配应大小写不敏感；中文 needle（余额不足 / 账户欠费）也应命中。"""
    from app.engine.orchestrator import _classify_run_audit_error

    # 大写变种
    kind1, _ = _classify_run_audit_error(Exception("INSUFFICIENT BALANCE!!!"))
    assert kind1 == "insufficient_balance"

    # 中文变种
    kind2, s2 = _classify_run_audit_error(Exception("请求失败：账户欠费"))
    assert kind2 == "insufficient_balance"
    assert "余额不足" in s2

    # payment required 变种
    kind3, _ = _classify_run_audit_error(Exception("HTTP 402 Payment Required"))
    assert kind3 == "insufficient_balance"


# ============================================================
# 集成：run_audit 在 LLM 抛 402 时应把友好 summary 写进 task
# ============================================================
def test_run_audit_insufficient_balance_end_to_end(monkeypatch):
    """
    monkeypatch app.engine.orchestrator.get_llm_client 让它返回一个总是抛
    "Error code: 402" 的假 client；再对 run_audit 传入一个含材料的任务，
    断言最终 task.status='failed' 且 task.summary 走友好文案。
    """
    import uuid

    from app.engine import orchestrator
    from app.models import (
        AuditTask, AuditUnit, Indicator, Material, SessionLocal,
    )

    class _FakeLLM402:
        """所有 API 都抛 402 的假 LLM client。"""
        def complete(self, *args, **kwargs):
            raise Exception(
                "Error code: 402 - {'error': {'message': 'Insufficient Balance', "
                "'code': 'insufficient_balance'}}"
            )
        def extract_json(self, *args, **kwargs):
            raise Exception(
                "Error code: 402 - {'error': {'message': 'Insufficient Balance', "
                "'code': 'insufficient_balance'}}"
            )

    monkeypatch.setattr(
        orchestrator, "get_llm_client",
        lambda db: _FakeLLM402(),
    )

    # 确保指标已 seed
    from app.seeds.load_indicators_55 import load as load_indicators
    load_indicators(replace=False)

    suffix = uuid.uuid4().hex[:6]
    db = SessionLocal()
    try:
        unit = AuditUnit(name=f"v22-{suffix}", code=f"V22{suffix}")
        db.add(unit); db.flush()

        ind = db.query(Indicator).filter_by(indicator_code="I-13").first()
        assert ind is not None, "种子指标 I-13 缺失"

        import json as _json
        task = AuditTask(
            unit_id=unit.id, name=f"v22-{suffix}",
            eval_year=2026, scope="selected",
            selected_indicator_ids=_json.dumps([ind.id]),
        )
        db.add(task); db.flush()

        m = Material(
            task_id=task.id, indicator_id=ind.id,
            file_name=f"v22-{suffix}.txt",
            storage_path=f"/tmp/v22-{suffix}",
            file_type="txt", is_scanned=False,
            parsed_text="预算管理办法第一条 " * 30,
        )
        db.add(m); db.commit()
        task_id = task.id
    finally:
        db.close()

    # 触发核查
    db = SessionLocal()
    try:
        task = db.get(AuditTask, task_id)
        orchestrator.run_audit(db, task)
    finally:
        db.close()

    # 验证
    db = SessionLocal()
    try:
        t = db.get(AuditTask, task_id)
        assert t.status == "failed", f"status={t.status!r}"
        assert "余额不足" in (t.summary or ""), f"summary={t.summary!r}"
        assert "联系管理员" in t.summary
    finally:
        db.close()
