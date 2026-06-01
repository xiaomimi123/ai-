"""跨文件联动校验编排器（§3.5）。

三条联动链：
- 招采链：招标 → 投标 → 评标 → 合同
- 财务链：财务 → 决算 → 资产 → 合同付款
- 报告链：内控 → 绩效 → 项目资料

均按「先抽取、后比对」两阶段执行，比对完全确定性、不调 LLM。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.domain import Issue
from app.crosscheck.comparator import compare_chain
from app.crosscheck.extractor import (
    extract_bid,
    extract_contract,
    extract_eval,
    extract_tender,
)
from app.crosscheck.finance_comparator import compare_finance_chain
from app.crosscheck.finance_extractor import (
    extract_asset_report,
    extract_final_account,
    extract_finance,
)
from app.crosscheck.report_comparator import compare_report_chain
from app.crosscheck.report_extractor import (
    extract_internal_control_report,
    extract_performance_report,
    extract_project_material,
)
from app.crosscheck.schemas import (
    ChainFields,
    ContractPaymentFields,
    FinanceChainFields,
    ReportChainFields,
)
from app.models.entities import Document
from app.parsers import parse


# ===================== 招采链 =====================
@dataclass
class ProcurementChain:
    tender_doc_id: Optional[int] = None
    bid_doc_id: Optional[int] = None
    eval_doc_id: Optional[int] = None
    contract_doc_id: Optional[int] = None


# ===================== 财务链 =====================
@dataclass
class FinanceChain:
    finance_doc_id: Optional[int] = None
    final_account_doc_id: Optional[int] = None
    asset_doc_id: Optional[int] = None
    contract_doc_ids: List[int] = field(default_factory=list)


# ===================== 报告链 =====================
@dataclass
class ReportChain:
    ic_doc_id: Optional[int] = None
    perf_doc_id: Optional[int] = None
    project_doc_id: Optional[int] = None


def _load_and_parse(db: Session, doc_id: Optional[int]):
    if doc_id is None:
        return None, ""
    doc = db.get(Document, doc_id)
    if doc is None:
        return None, ""
    parsed = parse(doc.storage_path)
    parsed.metadata.setdefault("file_name", doc.file_name)
    if doc.subcategory:
        parsed.metadata.setdefault("subcategory", doc.subcategory)
    return parsed, doc.file_name


# ===================== 编排器 =====================
def run_procurement_chain(db: Session, chain: ProcurementChain) -> Tuple[ChainFields, List[Issue]]:
    fields = ChainFields()
    t_doc, fields.tender_file = _load_and_parse(db, chain.tender_doc_id)
    if t_doc: fields.tender = extract_tender(t_doc)
    b_doc, fields.bid_file = _load_and_parse(db, chain.bid_doc_id)
    if b_doc: fields.bid = extract_bid(b_doc)
    e_doc, fields.eval_file = _load_and_parse(db, chain.eval_doc_id)
    if e_doc: fields.eval = extract_eval(e_doc)
    c_doc, fields.contract_file = _load_and_parse(db, chain.contract_doc_id)
    if c_doc: fields.contract = extract_contract(c_doc)
    return fields, compare_chain(fields)


def run_finance_chain(db: Session, chain: FinanceChain) -> Tuple[FinanceChainFields, List[Issue]]:
    fields = FinanceChainFields()
    f_doc, fields.finance_file = _load_and_parse(db, chain.finance_doc_id)
    if f_doc: fields.finance = extract_finance(f_doc)
    fa_doc, fields.final_account_file = _load_and_parse(db, chain.final_account_doc_id)
    if fa_doc: fields.final_account = extract_final_account(fa_doc)
    a_doc, fields.asset_file = _load_and_parse(db, chain.asset_doc_id)
    if a_doc: fields.asset = extract_asset_report(a_doc)
    # 合同付款：从已抽取的合同金额聚合
    for cid in chain.contract_doc_ids:
        c_doc, c_name = _load_and_parse(db, cid)
        if c_doc:
            cf = extract_contract(c_doc)
            fields.contract_amounts.append(
                ContractPaymentFields(amount=cf.amount, file_name=c_name)
            )
    return fields, compare_finance_chain(fields)


def run_report_chain(db: Session, chain: ReportChain) -> Tuple[ReportChainFields, List[Issue]]:
    fields = ReportChainFields()
    ic_doc, fields.ic_file = _load_and_parse(db, chain.ic_doc_id)
    if ic_doc: fields.internal_control = extract_internal_control_report(ic_doc)
    p_doc, fields.perf_file = _load_and_parse(db, chain.perf_doc_id)
    if p_doc: fields.performance = extract_performance_report(p_doc)
    pm_doc, fields.project_file = _load_and_parse(db, chain.project_doc_id)
    if pm_doc: fields.project_material = extract_project_material(pm_doc)
    return fields, compare_report_chain(fields)
