"""合同刚性规则单元测试。"""
from app.parsers.txt_parser import parse_text_content
from app.rules.contract import (
    AmountConsistencyRule,
    ContractNumberRule,
    PartiesRule,
    RequiredClausesRule,
    SealRule,
)
from tests.samples import BAD_CONTRACT, GOOD_CONTRACT


def _doc(text):
    return parse_text_content(text, file_name="contract.txt")


def test_good_contract_number_present():
    assert ContractNumberRule().check(_doc(GOOD_CONTRACT)) == []


def test_bad_contract_number_missing():
    issues = ContractNumberRule().check(_doc(BAD_CONTRACT))
    assert len(issues) == 1
    assert issues[0].rule_id == "contract.number"


def test_amount_consistency_detects_mismatch():
    # BAD 合同：大写 10 万 vs 小写 9 万
    issues = AmountConsistencyRule().check(_doc(BAD_CONTRACT))
    assert len(issues) == 1
    assert "不一致" in issues[0].description
    assert issues[0].risk_level.value == "高"


def test_amount_consistency_passes_when_matching():
    assert AmountConsistencyRule().check(_doc(GOOD_CONTRACT)) == []


def test_parties_missing_party_b():
    issues = PartiesRule().check(_doc(BAD_CONTRACT))
    # 乙方为空 -> 至少一条
    assert any("乙方" in i.description for i in issues)


def test_required_clauses_missing():
    issues = RequiredClausesRule().check(_doc(BAD_CONTRACT))
    descs = " ".join(i.description for i in issues)
    assert "违约责任" in descs  # BAD 合同缺违约责任
    assert "合同期限" in descs  # 也缺期限


def test_seal_missing():
    issues = SealRule().check(_doc(BAD_CONTRACT))
    assert len(issues) == 1


def test_good_contract_seal_present():
    assert SealRule().check(_doc(GOOD_CONTRACT)) == []
