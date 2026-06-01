"""报告链联动校验：抽取器 + 比对器单元测试。"""
from app.crosscheck.report_comparator import compare_report_chain
from app.crosscheck.report_extractor import (
    extract_internal_control_report,
    extract_performance_report,
    extract_project_material,
)
from app.crosscheck.schemas import ReportChainFields
from app.parsers.txt_parser import parse_text_content
from tests.samples import (
    REP_BAD_IC,
    REP_BAD_PERF,
    REP_BAD_PROJECT,
    REP_GOOD_IC,
    REP_GOOD_PERF,
    REP_GOOD_PROJECT,
    REP_PERF_DIFFERENT,
)


def _doc(text, name):
    return parse_text_content(text, file_name=name)


# ---------- 抽取器 ----------
def test_extract_internal_control_report():
    f = extract_internal_control_report(_doc(REP_GOOD_IC, "ic.txt"))
    assert f.year == 2026
    assert any("智慧校园" in n for n in f.project_mentions)
    assert f.deficiency_count == 1
    assert "有效" in f.evaluation_result


def test_extract_performance_report():
    f = extract_performance_report(_doc(REP_GOOD_PERF, "perf.txt"))
    assert f.year == 2026
    assert f.project_name == "智慧校园建设项目"
    assert f.score == 92.0
    assert f.grade == "优"
    assert f.has_problems is True


def test_extract_project_material():
    f = extract_project_material(_doc(REP_GOOD_PROJECT, "p.txt"))
    assert f.project_name == "智慧校园建设项目"
    assert f.has_approval is True
    assert f.has_completion is True


def test_extract_project_material_no_completion():
    f = extract_project_material(_doc(REP_BAD_PROJECT, "p.txt"))
    assert f.has_approval is True
    assert f.has_completion is False


# ---------- 比对器 ----------
def _build(ic=None, perf=None, pm=None):
    f = ReportChainFields()
    if ic:
        f.internal_control = extract_internal_control_report(_doc(ic, "ic.txt"))
        f.ic_file = "ic.txt"
    if perf:
        f.performance = extract_performance_report(_doc(perf, "perf.txt"))
        f.perf_file = "perf.txt"
    if pm:
        f.project_material = extract_project_material(_doc(pm, "p.txt"))
        f.project_file = "p.txt"
    return f


def test_good_report_chain_no_issues():
    fields = _build(REP_GOOD_IC, REP_GOOD_PERF, REP_GOOD_PROJECT)
    real = [i for i in compare_report_chain(fields) if i.rule_id != "report.completeness"]
    assert real == [], [i.description for i in real]


def test_material_no_completion_flagged():
    fields = _build(pm=REP_BAD_PROJECT)
    rule_ids = {i.rule_id for i in compare_report_chain(fields)}
    assert "report.material_no_completion" in rule_ids


def test_ic_eval_vs_deficiency_flagged():
    # bad ic: 评价「有效」但披露 8 项缺陷
    fields = _build(ic=REP_BAD_IC)
    rule_ids = {i.rule_id for i in compare_report_chain(fields)}
    assert "report.ic_eval_vs_deficiency" in rule_ids


def test_score_vs_grade_mismatch_flagged():
    # bad perf: 得分 75 但等次「优」
    fields = _build(perf=REP_BAD_PERF)
    rule_ids = {i.rule_id for i in compare_report_chain(fields)}
    assert "report.score_vs_grade" in rule_ids


def test_perf_project_not_in_ic_flagged():
    # 内控提到「智慧校园」，绩效是「老旧小区改造」 → 项目不匹配
    fields = _build(ic=REP_GOOD_IC, perf=REP_PERF_DIFFERENT)
    rule_ids = {i.rule_id for i in compare_report_chain(fields)}
    assert "report.perf_in_ic" in rule_ids


def test_full_bad_report_chain_all_violations():
    fields = _build(REP_BAD_IC, REP_BAD_PERF, REP_BAD_PROJECT)
    rule_ids = {i.rule_id for i in compare_report_chain(fields)}
    expected = {
        "report.ic_eval_vs_deficiency",
        "report.score_vs_grade",
        "report.material_no_completion",
    }
    assert expected.issubset(rule_ids), rule_ids


def test_incomplete_report_chain():
    fields = _build(ic=REP_GOOD_IC)
    completeness = [i for i in compare_report_chain(fields) if i.rule_id == "report.completeness"]
    assert len(completeness) == 1
    assert "绩效" in completeness[0].description
    assert "项目资料" in completeness[0].description
