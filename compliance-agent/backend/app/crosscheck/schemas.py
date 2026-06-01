"""招采链各环节的结构化字段 schema（§3.5）。

「先抽取、后比对」两阶段设计：每份文档独立抽取这些字段，
再由比对器做字段级交叉比对，不需要 LLM 一次性读完所有文档。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


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
