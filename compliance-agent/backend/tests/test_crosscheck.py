"""跨文件联动校验：抽取器 + 比对器单元测试。"""
from app.crosscheck.comparator import compare_chain
from app.crosscheck.extractor import (
    extract_bid,
    extract_contract,
    extract_eval,
    extract_tender,
)
from app.crosscheck.schemas import ChainFields
from app.parsers.txt_parser import parse_text_content
from tests.samples import (
    CHAIN_BAD_BID,
    CHAIN_BAD_CONTRACT,
    CHAIN_BAD_EVAL,
    CHAIN_GOOD_BID,
    CHAIN_GOOD_CONTRACT,
    CHAIN_GOOD_EVAL,
    CHAIN_GOOD_TENDER,
)


def _doc(text, name):
    return parse_text_content(text, file_name=name)


# ---------- 抽取器 ----------
def test_extract_tender_fields():
    f = extract_tender(_doc(CHAIN_GOOD_TENDER, "tender.txt"))
    assert f.tender_number == "CGZB-2026-001"
    assert f.budget == 500000.0
    assert "2026年3月15日14:00" in f.deadline
    assert f.project_name == "办公设备采购项目"


def test_extract_bid_fields():
    f = extract_bid(_doc(CHAIN_GOOD_BID, "bid.txt"))
    assert f.bidder_name == "某某贸易有限公司"
    assert f.bid_price == 480000.0
    assert f.validity_days == 60


def test_extract_eval_fields():
    f = extract_eval(_doc(CHAIN_GOOD_EVAL, "eval.txt"))
    assert f.winner_name == "某某贸易有限公司"
    assert f.winner_price == 480000.0
    assert f.committee_size == 5


def test_extract_contract_fields():
    f = extract_contract(_doc(CHAIN_GOOD_CONTRACT, "contract.txt"))
    assert f.party_a == "某某市财政局"
    assert f.party_b == "某某贸易有限公司"
    assert f.amount == 480000.0


# ---------- 比对器 ----------
def _build_chain_fields(tender_text=None, bid_text=None, eval_text=None, contract_text=None):
    f = ChainFields()
    if tender_text:
        f.tender = extract_tender(_doc(tender_text, "tender.txt"))
        f.tender_file = "tender.txt"
    if bid_text:
        f.bid = extract_bid(_doc(bid_text, "bid.txt"))
        f.bid_file = "bid.txt"
    if eval_text:
        f.eval = extract_eval(_doc(eval_text, "eval.txt"))
        f.eval_file = "eval.txt"
    if contract_text:
        f.contract = extract_contract(_doc(contract_text, "contract.txt"))
        f.contract_file = "contract.txt"
    return f


def test_good_chain_has_no_inconsistency_issues():
    fields = _build_chain_fields(
        CHAIN_GOOD_TENDER, CHAIN_GOOD_BID, CHAIN_GOOD_EVAL, CHAIN_GOOD_CONTRACT
    )
    issues = compare_chain(fields)
    inconsistency = [i for i in issues if i.rule_id != "chain.completeness"]
    assert inconsistency == [], [i.description for i in inconsistency]


def test_bad_chain_flags_price_over_budget():
    # 招标预算 50w，投标报价 60w
    fields = _build_chain_fields(CHAIN_GOOD_TENDER, CHAIN_BAD_BID)
    rule_ids = {i.rule_id for i in compare_chain(fields)}
    assert "chain.price_over_budget" in rule_ids


def test_bad_chain_flags_winner_mismatch():
    # 投标人=甲贸易公司，评标中标人=甲贸易公司，合同乙方=乙服务有限公司
    fields = _build_chain_fields(
        bid_text=CHAIN_BAD_BID, eval_text=CHAIN_BAD_EVAL, contract_text=CHAIN_BAD_CONTRACT
    )
    rule_ids = {i.rule_id for i in compare_chain(fields)}
    assert "chain.contract_party_vs_winner" in rule_ids


def test_bad_chain_flags_contract_amount_mismatch():
    # 中标价 60w，合同金额 70w
    fields = _build_chain_fields(eval_text=CHAIN_BAD_EVAL, contract_text=CHAIN_BAD_CONTRACT)
    rule_ids = {i.rule_id for i in compare_chain(fields)}
    assert "chain.contract_amount_vs_bid" in rule_ids


def test_bad_chain_flags_contract_over_budget():
    # 预算 50w，合同金额 70w
    fields = _build_chain_fields(tender_text=CHAIN_GOOD_TENDER, contract_text=CHAIN_BAD_CONTRACT)
    rule_ids = {i.rule_id for i in compare_chain(fields)}
    assert "chain.contract_over_budget" in rule_ids


def test_bad_chain_flags_committee_size():
    # 评委 4 人（偶数且 < 5）
    fields = _build_chain_fields(eval_text=CHAIN_BAD_EVAL)
    rule_ids = {i.rule_id for i in compare_chain(fields)}
    assert "chain.committee_size" in rule_ids


def test_incomplete_chain_reports_missing():
    fields = _build_chain_fields(tender_text=CHAIN_GOOD_TENDER)
    issues = compare_chain(fields)
    completeness = [i for i in issues if i.rule_id == "chain.completeness"]
    assert len(completeness) == 1
    # 应列出 3 个缺失环节
    assert "投标" in completeness[0].description
    assert "评标" in completeness[0].description
    assert "合同" in completeness[0].description


def test_full_bad_chain_all_violations():
    fields = _build_chain_fields(
        CHAIN_GOOD_TENDER, CHAIN_BAD_BID, CHAIN_BAD_EVAL, CHAIN_BAD_CONTRACT
    )
    rule_ids = {i.rule_id for i in compare_chain(fields)}
    # 完整问题链应同时检出多个跨文件问题
    expected = {
        "chain.price_over_budget",
        "chain.contract_party_vs_winner",
        "chain.contract_amount_vs_bid",
        "chain.contract_over_budget",
        "chain.committee_size",
    }
    assert expected.issubset(rule_ids), rule_ids
