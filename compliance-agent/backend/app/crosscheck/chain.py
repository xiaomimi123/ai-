"""招采链联动校验编排器（§3.5）。

输入：一组同一项目的招采文档（招标/投标/评标/合同，可缺）；
输出：跨文件不一致问题清单（Issue 统一结构）。

设计为分两阶段：
1) 抽取阶段：对每份文档独立抽取结构化字段
2) 比对阶段：字段级 + 名称相似度比对，确定性，不调 LLM
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.domain import Issue
from app.crosscheck.comparator import compare_chain
from app.crosscheck.extractor import (
    extract_bid,
    extract_contract,
    extract_eval,
    extract_tender,
)
from app.crosscheck.schemas import ChainFields
from app.models.entities import Document
from app.parsers import parse


@dataclass
class ProcurementChain:
    """一组招采链文档（每环节单文件）。"""
    tender_doc_id: Optional[int] = None
    bid_doc_id: Optional[int] = None
    eval_doc_id: Optional[int] = None
    contract_doc_id: Optional[int] = None


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


def run_procurement_chain(db: Session, chain: ProcurementChain) -> tuple[ChainFields, List[Issue]]:
    """阶段 1：解析+抽取；阶段 2：比对。返回抽取结果与问题清单。"""
    fields = ChainFields()

    tender_doc, fields.tender_file = _load_and_parse(db, chain.tender_doc_id)
    if tender_doc is not None:
        fields.tender = extract_tender(tender_doc)

    bid_doc, fields.bid_file = _load_and_parse(db, chain.bid_doc_id)
    if bid_doc is not None:
        fields.bid = extract_bid(bid_doc)

    eval_doc, fields.eval_file = _load_and_parse(db, chain.eval_doc_id)
    if eval_doc is not None:
        fields.eval = extract_eval(eval_doc)

    contract_doc, fields.contract_file = _load_and_parse(db, chain.contract_doc_id)
    if contract_doc is not None:
        fields.contract = extract_contract(contract_doc)

    issues = compare_chain(fields)
    return fields, issues
