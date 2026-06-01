"""跨文件联动校验引擎（§3.5）。

Phase 3 实现招采链：招标 → 投标 → 评标 → 合同。
"""
from app.crosscheck.chain import ProcurementChain, run_procurement_chain

__all__ = ["ProcurementChain", "run_procurement_chain"]
