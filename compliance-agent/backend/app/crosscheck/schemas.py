"""招采链各环节的结构化字段 schema（§3.5）。

「先抽取、后比对」两阶段设计：每份文档独立抽取这些字段，
再由比对器做字段级交叉比对，不需要 LLM 一次性读完所有文档。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TenderFields:
    """招标文件抽取字段。"""
    project_name: Optional[str] = None      # 项目名称
    budget: Optional[float] = None          # 招标预算/最高限价
    budget_raw: str = ""                    # 原始金额文本（用于报告）
    deadline: str = ""                      # 投标截止时间（文本）
    purchaser: str = ""                     # 招标人/采购人
    tender_number: str = ""                 # 招标/项目编号


@dataclass
class BidFields:
    """投标文件抽取字段。"""
    project_name: Optional[str] = None      # 投标文件中的项目名称
    bidder_name: str = ""                   # 投标人名称
    bid_price: Optional[float] = None       # 投标报价
    bid_price_raw: str = ""                 # 原始报价文本
    validity_days: Optional[int] = None     # 投标有效期（天）


@dataclass
class EvalFields:
    """评标报告抽取字段。"""
    project_name: Optional[str] = None      # 项目名称
    winner_name: str = ""                   # 中标候选人第一名
    winner_price: Optional[float] = None    # 中标价（若报告中有）
    committee_size: Optional[int] = None    # 评委人数


@dataclass
class ContractFields:
    """合同文件抽取字段（来自合同模板已解析文档）。"""
    project_name: Optional[str] = None      # 合同标的/项目名称
    party_a: str = ""                       # 甲方
    party_b: str = ""                       # 乙方/中标方
    amount: Optional[float] = None          # 合同金额
    amount_raw: str = ""                    # 原始金额文本
    duration: str = ""                      # 合同期限


@dataclass
class ChainFields:
    """一套招采链的全部抽取结果。"""
    tender: Optional[TenderFields] = None
    bid: Optional[BidFields] = None
    eval: Optional[EvalFields] = None
    contract: Optional[ContractFields] = None
    # 来源文件名，用于问题定位
    tender_file: str = ""
    bid_file: str = ""
    eval_file: str = ""
    contract_file: str = ""


# ===================== 财务链 =====================
@dataclass
class FinanceFields:
    """财务报告抽取字段。"""
    year: Optional[int] = None              # 报告年度
    total_assets: Optional[float] = None    # 资产合计
    total_liabilities: Optional[float] = None  # 负债合计
    total_net_assets: Optional[float] = None   # 净资产合计
    total_income: Optional[float] = None    # 收入合计
    total_expense: Optional[float] = None   # 支出合计


@dataclass
class FinalAccountFields:
    """决算报告抽取字段。"""
    year: Optional[int] = None
    total_income: Optional[float] = None    # 决算收入
    total_expense: Optional[float] = None   # 决算支出
    budget_total: Optional[float] = None    # 预算总额（用于预决算差异判断）
    three_public_total: Optional[float] = None  # 三公经费合计


@dataclass
class AssetReportFields:
    """国有资产报告抽取字段。"""
    year: Optional[int] = None
    total_assets: Optional[float] = None    # 资产总额
    fixed_assets: Optional[float] = None    # 固定资产


@dataclass
class ContractPaymentFields:
    """合同付款相关：从合同正文抽（金额已在 ContractFields 中）。

    这里仅记录与财务链相关的辅助信息。
    """
    amount: Optional[float] = None
    file_name: str = ""


@dataclass
class FinanceChainFields:
    """财务链全部抽取结果。"""
    finance: Optional[FinanceFields] = None
    final_account: Optional[FinalAccountFields] = None
    asset: Optional[AssetReportFields] = None
    contract_amounts: List["ContractPaymentFields"] = field(default_factory=list)
    finance_file: str = ""
    final_account_file: str = ""
    asset_file: str = ""


# ===================== 报告链 =====================
@dataclass
class InternalControlReportFields:
    """内控报告抽取字段。"""
    year: Optional[int] = None
    project_mentions: List[str] = field(default_factory=list)  # 报告中提及的项目名称
    deficiency_count: Optional[int] = None                     # 披露的缺陷数量
    evaluation_result: str = ""                                # 自我评价结论


@dataclass
class PerformanceReportFields:
    """绩效评价报告抽取字段。"""
    year: Optional[int] = None
    project_name: str = ""
    score: Optional[float] = None        # 综合得分
    grade: str = ""                      # 评价等次：优/良/中/差
    has_problems: bool = False           # 是否列示问题


@dataclass
class ProjectMaterialFields:
    """项目资料（佐证材料）抽取字段。"""
    project_name: str = ""
    has_approval: bool = False           # 是否有立项/审批留痕
    has_completion: bool = False         # 是否有验收/完工留痕


@dataclass
class ReportChainFields:
    """报告链全部抽取结果。"""
    internal_control: Optional[InternalControlReportFields] = None
    performance: Optional[PerformanceReportFields] = None
    project_material: Optional[ProjectMaterialFields] = None
    ic_file: str = ""
    perf_file: str = ""
    project_file: str = ""
