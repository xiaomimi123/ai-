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
