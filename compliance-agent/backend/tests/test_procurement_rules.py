"""招采三合一刚性规则单元测试。"""
from app.parsers.txt_parser import parse_text_content
from app.rules.procurement import (
    BidBidderRule,
    BidPriceRule,
    BidSignatureRule,
    BidValidityRule,
    EvalCommitteeRule,
    EvalResultRule,
    EvalSignatureRule,
    PROCUREMENT_RIGID_RULES,
    TenderBudgetRule,
    TenderDeadlineRule,
    TenderEvalMethodRule,
    TenderNumberRule,
    TenderQualificationRule,
    detect_subtype,
    resolve_subtype,
)
from tests.samples import (
    BAD_BID,
    BAD_EVAL,
    BAD_TENDER,
    GOOD_BID,
    GOOD_EVAL,
    GOOD_TENDER,
)


def _doc(text, subcategory=""):
    d = parse_text_content(text, file_name="proc.txt")
    if subcategory:
        d.metadata["subcategory"] = subcategory
    return d


# ---------- 子类识别 ----------
def test_detect_tender():
    assert detect_subtype(GOOD_TENDER) == "招标"

def test_detect_bid():
    assert detect_subtype(GOOD_BID) == "投标"

def test_detect_eval():
    assert detect_subtype(GOOD_EVAL) == "评标"

def test_resolve_uses_metadata_subcategory():
    doc = _doc(GOOD_TENDER, subcategory="投标")
    assert resolve_subtype(doc) == "投标"


# ---------- 招标刚性规则 ----------
def test_good_tender_passes_all_rigid():
    doc = _doc(GOOD_TENDER)
    issues = [i for r in PROCUREMENT_RIGID_RULES for i in r.check(doc)]
    assert issues == [], [i.description for i in issues]

def test_bad_tender_missing_number():
    assert len(TenderNumberRule().check(_doc(BAD_TENDER, "招标"))) == 1

def test_bad_tender_missing_budget():
    assert len(TenderBudgetRule().check(_doc(BAD_TENDER, "招标"))) == 1

def test_bad_tender_missing_deadline():
    assert len(TenderDeadlineRule().check(_doc(BAD_TENDER, "招标"))) == 1

def test_bad_tender_missing_qualification():
    assert len(TenderQualificationRule().check(_doc(BAD_TENDER, "招标"))) == 1

def test_bad_tender_missing_eval_method():
    assert len(TenderEvalMethodRule().check(_doc(BAD_TENDER, "招标"))) == 1


# ---------- 投标刚性规则 ----------
def test_good_bid_passes_all_rigid():
    doc = _doc(GOOD_BID)
    issues = [i for r in PROCUREMENT_RIGID_RULES for i in r.check(doc)]
    assert issues == [], [i.description for i in issues]

def test_bad_bid_missing_bidder():
    assert len(BidBidderRule().check(_doc(BAD_BID, "投标"))) == 1

def test_bad_bid_missing_price():
    assert len(BidPriceRule().check(_doc(BAD_BID, "投标"))) == 1

def test_bad_bid_missing_validity():
    assert len(BidValidityRule().check(_doc(BAD_BID, "投标"))) == 1

def test_bad_bid_missing_signature():
    assert len(BidSignatureRule().check(_doc(BAD_BID, "投标"))) == 1


# ---------- 评标刚性规则 ----------
def test_good_eval_passes_all_rigid():
    doc = _doc(GOOD_EVAL)
    issues = [i for r in PROCUREMENT_RIGID_RULES for i in r.check(doc)]
    assert issues == [], [i.description for i in issues]

def test_bad_eval_missing_committee():
    assert len(EvalCommitteeRule().check(_doc(BAD_EVAL, "评标"))) == 1

def test_bad_eval_missing_result():
    assert len(EvalResultRule().check(_doc(BAD_EVAL, "评标"))) == 1

def test_bad_eval_missing_signature():
    assert len(EvalSignatureRule().check(_doc(BAD_EVAL, "评标"))) == 1


# ---------- 子类隔离（招标规则不对投标文件生效）----------
def test_tender_rules_skip_bid_doc():
    doc = _doc(GOOD_BID)
    assert TenderNumberRule().check(doc) == []
    assert TenderBudgetRule().check(doc) == []

def test_bid_rules_skip_tender_doc():
    doc = _doc(GOOD_TENDER)
    assert BidBidderRule().check(doc) == []
    assert BidPriceRule().check(doc) == []

def test_eval_rules_skip_tender_doc():
    doc = _doc(GOOD_TENDER)
    assert EvalCommitteeRule().check(doc) == []
    assert EvalResultRule().check(doc) == []
