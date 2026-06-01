"""跨文件联动校验引擎（§3.5）。

三条联动链：招采链 / 财务链 / 报告链。
"""
from app.crosscheck.chain import (
    FinanceChain,
    ProcurementChain,
    ReportChain,
    run_finance_chain,
    run_procurement_chain,
    run_report_chain,
)

__all__ = [
    "ProcurementChain", "FinanceChain", "ReportChain",
    "run_procurement_chain", "run_finance_chain", "run_report_chain",
]
