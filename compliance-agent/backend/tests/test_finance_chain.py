"""财务链联动校验：抽取器 + 比对器单元测试。"""
from app.crosscheck.finance_comparator import compare_finance_chain
from app.crosscheck.finance_extractor import (
    extract_asset_report,
    extract_final_account,
    extract_finance,
)
from app.crosscheck.schemas import (
    ContractPaymentFields,
    FinanceChainFields,
)
from app.parsers.txt_parser import parse_text_content
from tests.samples import (
    FIN_BAD_ASSET,
    FIN_BAD_FINAL_ACCOUNT,
    FIN_BAD_FINANCE,
    FIN_DIFFERENT_YEAR_ASSET,
    FIN_GOOD_ASSET,
    FIN_GOOD_FINAL_ACCOUNT,
    FIN_GOOD_FINANCE,
)


def _doc(text, name):
    return parse_text_content(text, file_name=name)


# ---------- 抽取器 ----------
def test_extract_finance_fields():
    f = extract_finance(_doc(FIN_GOOD_FINANCE, "fin.txt"))
    assert f.year == 2026
    assert f.total_assets == 30000000.0
    assert f.total_liabilities == 10000000.0
    assert f.total_net_assets == 20000000.0
    assert f.total_income == 5000000.0
    assert f.total_expense == 4800000.0


def test_extract_final_account_fields():
    f = extract_final_account(_doc(FIN_GOOD_FINAL_ACCOUNT, "fa.txt"))
    assert f.total_income == 5000000.0
    assert f.total_expense == 4800000.0
    assert f.budget_total == 5200000.0
    assert f.three_public_total == 80000.0


def test_extract_asset_report_fields():
    f = extract_asset_report(_doc(FIN_GOOD_ASSET, "asset.txt"))
    assert f.total_assets == 30000000.0
    assert f.fixed_assets == 20000000.0


# ---------- 比对器 ----------
def _build(finance=None, fa=None, asset=None, contracts=None):
    f = FinanceChainFields()
    if finance:
        f.finance = extract_finance(_doc(finance, "fin.txt"))
        f.finance_file = "fin.txt"
    if fa:
        f.final_account = extract_final_account(_doc(fa, "fa.txt"))
        f.final_account_file = "fa.txt"
    if asset:
        f.asset = extract_asset_report(_doc(asset, "asset.txt"))
        f.asset_file = "asset.txt"
    if contracts:
        f.contract_amounts = contracts
    return f


def test_good_finance_chain_no_issues():
    fields = _build(FIN_GOOD_FINANCE, FIN_GOOD_FINAL_ACCOUNT, FIN_GOOD_ASSET)
    issues = compare_finance_chain(fields)
    real = [i for i in issues if i.rule_id != "fin.completeness"]
    assert real == [], [i.description for i in real]


def test_balance_sheet_identity_violation():
    # bad finance: 30,000,000 ≠ 12,000,000 + 20,000,000 = 32,000,000
    fields = _build(FIN_BAD_FINANCE)
    rule_ids = {i.rule_id for i in compare_finance_chain(fields)}
    assert "fin.balance_sheet_identity" in rule_ids


def test_income_inconsistent_finance_vs_final():
    # finance: 5,000,000; final: 5,800,000 → 偏差 16%
    fields = _build(FIN_GOOD_FINANCE, FIN_BAD_FINAL_ACCOUNT)
    rule_ids = {i.rule_id for i in compare_finance_chain(fields)}
    assert "fin.income_vs_final" in rule_ids


def test_assets_inconsistent_finance_vs_asset_report():
    # finance: 30,000,000; asset report: 28,000,000
    fields = _build(FIN_GOOD_FINANCE, asset=FIN_BAD_ASSET)
    rule_ids = {i.rule_id for i in compare_finance_chain(fields)}
    assert "fin.assets_vs_asset_report" in rule_ids


def test_budget_vs_actual_diff_too_large():
    # budget: 4,000,000; actual income: 5,800,000 → 偏差 31%
    fields = _build(fa=FIN_BAD_FINAL_ACCOUNT)
    rule_ids = {i.rule_id for i in compare_finance_chain(fields)}
    assert "fin.budget_vs_actual" in rule_ids


def test_contracts_exceed_expense():
    # 合同金额合计 6,000,000 > 决算支出 4,800,000
    fields = _build(fa=FIN_GOOD_FINAL_ACCOUNT, contracts=[
        ContractPaymentFields(amount=3000000.0, file_name="c1.txt"),
        ContractPaymentFields(amount=3000000.0, file_name="c2.txt"),
    ])
    rule_ids = {i.rule_id for i in compare_finance_chain(fields)}
    assert "fin.contracts_vs_expense" in rule_ids


def test_year_mismatch_flagged():
    fields = _build(FIN_GOOD_FINANCE, asset=FIN_DIFFERENT_YEAR_ASSET)
    rule_ids = {i.rule_id for i in compare_finance_chain(fields)}
    assert "fin.year_mismatch" in rule_ids


def test_incomplete_chain_reports_missing():
    fields = _build(FIN_GOOD_FINANCE)
    completeness = [i for i in compare_finance_chain(fields)
                    if i.rule_id == "fin.completeness"]
    assert len(completeness) == 1
    assert "决算" in completeness[0].description
    assert "资产" in completeness[0].description
