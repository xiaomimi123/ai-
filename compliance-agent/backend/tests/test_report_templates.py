"""Phase 2 报告类 4 个模板（内控/财务+决算/资产/绩效）单元测试。"""
import pytest

from app.parsers.txt_parser import parse_text_content
from app.rules import get_template
from app.rules.base import RuleEngine
from tests.samples import (
    BAD_ASSET, BAD_FINANCE_FINAL, BAD_INTERNAL_CONTROL, BAD_PERFORMANCE,
    GOOD_ASSET, GOOD_FINANCE_FINAL, GOOD_INTERNAL_CONTROL, GOOD_PERFORMANCE,
)

_GOOD_BAD = {
    "internal_control": (GOOD_INTERNAL_CONTROL, BAD_INTERNAL_CONTROL),
    "finance_final": (GOOD_FINANCE_FINAL, BAD_FINANCE_FINAL),
    "asset": (GOOD_ASSET, BAD_ASSET),
    "performance": (GOOD_PERFORMANCE, BAD_PERFORMANCE),
}


@pytest.mark.parametrize("template_key", list(_GOOD_BAD.keys()))
def test_good_doc_passes_all_rigid(template_key):
    good, _ = _GOOD_BAD[template_key]
    doc = parse_text_content(good, file_name=f"{template_key}_good.txt")
    template = get_template(template_key)
    issues = []
    for rule in template.rigid_rules:
        issues.extend(rule.check(doc))
    assert issues == [], [(i.rule_id, i.description) for i in issues]


@pytest.mark.parametrize("template_key", list(_GOOD_BAD.keys()))
def test_bad_doc_flags_common_form_issues(template_key):
    _, bad = _GOOD_BAD[template_key]
    doc = parse_text_content(bad, file_name=f"{template_key}_bad.txt")
    template = get_template(template_key)
    issues = []
    for rule in template.rigid_rules:
        issues.extend(rule.check(doc))
    # bad 样本应触发通用形式要素（unit/date/seal）和模板特有规则
    rule_ids = {i.rule_id for i in issues}
    assert "report.unit" in rule_ids or "report.date" in rule_ids or "report.seal" in rule_ids
    # 也应触发该模板的至少一条特有规则
    template_specific = {rid for rid in rule_ids
                         if not rid.startswith("report.")}
    assert template_specific, (template_key, rule_ids)


def test_internal_control_six_areas():
    """内控报告应检出六大业务领域缺失。"""
    doc = parse_text_content(BAD_INTERNAL_CONTROL, file_name="bad_ic.txt")
    template = get_template("internal_control")
    issues = []
    for rule in template.rigid_rules:
        issues.extend(rule.check(doc))
    ic_issues = [i for i in issues if i.rule_id == "ic.business_areas"]
    # 6 大业务领域全部缺失
    assert len(ic_issues) == 6


def test_finance_three_main_statements():
    doc = parse_text_content(BAD_FINANCE_FINAL, file_name="bad_fin.txt")
    template = get_template("finance_final")
    issues = []
    for rule in template.rigid_rules:
        issues.extend(rule.check(doc))
    stmt_issues = [i for i in issues if i.rule_id == "fin.statements"]
    # 3 张主表全部缺失
    assert len(stmt_issues) == 3


def test_engine_runs_all_templates_via_engine():
    """通过 RuleEngine 跑全部 4 个新模板的合规样本，应无刚性疑点。"""
    engine = RuleEngine()
    for key, (good, _) in _GOOD_BAD.items():
        doc = parse_text_content(good, file_name=f"{key}.txt")
        issues = [i for i in engine.run(get_template(key), doc) if i.source == "rigid"]
        assert issues == [], (key, [(i.rule_id, i.description) for i in issues])
