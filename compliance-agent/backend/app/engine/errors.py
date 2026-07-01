"""v2.2 新增：orchestrator / llm_checker 共享的异常分类工具。

抽出的目的：`llm_checker.run_llm_checks` 里也需要区分"余额不足"（要向上抛）
和"其它 LLM 抖动"（吞掉返回空），跟 orchestrator 顶层 except 的分类共用同一套
needle 定义，避免双重维护。
"""
from __future__ import annotations


INSUFFICIENT_BALANCE_NEEDLES = (
    "insufficient balance",
    "insufficient_balance",
    "error code: 402",
    "payment required",
    "余额不足",
    "账户欠费",
)


def is_insufficient_balance(exc: Exception) -> bool:
    """判断异常是否属于 LLM 余额不足 / 402 类。大小写不敏感。"""
    text = str(exc).lower()
    return any(needle in text for needle in INSUFFICIENT_BALANCE_NEEDLES)


def classify_run_audit_error(exc: Exception) -> tuple[str, str]:
    """把 run_audit 主循环抛出的异常分类成 (kind, user_facing_summary)。

    kind: "insufficient_balance" 或 "generic"，用于 log 分类。
    user_facing_summary: 显示在 AuditTask.summary 里的中文文案。
    """
    if is_insufficient_balance(exc):
        return (
            "insufficient_balance",
            "LLM 服务余额不足，请联系管理员充值后重新运行任务。",
        )
    return ("generic", f"核查失败：{exc}")
