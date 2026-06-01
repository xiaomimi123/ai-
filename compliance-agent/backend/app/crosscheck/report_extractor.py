"""报告链字段抽取：内控/绩效/项目资料（§3.5）。"""
from __future__ import annotations

import re
from typing import List, Optional

from app.crosscheck.schemas import (
    InternalControlReportFields,
    PerformanceReportFields,
    ProjectMaterialFields,
)
from app.parsers.base import ParsedDocument

_YEAR_RE = re.compile(r"(20\d{2}|19\d{2})\s*年")
_PROJECT_NAME_LABELS = re.compile(r"项目名称\s*[:：]\s*([^\n，,。；;]{2,30})")
_PROJECT_QUOTE = re.compile(r"《([^》]{2,30}(?:项目|工程|计划|建设))》")
_SCORE_RE = re.compile(r"(综合得分|评价得分|总分)\s*[:：]?\s*([0-9]{1,3}(?:\.\d+)?)\s*分?")
_GRADE_RE = re.compile(r"(评价等次|评价等级|评定等级)\s*[:：]?\s*([优良中差合格不合格]{1,3})")
_DEFICIENCY_COUNT_RE = re.compile(
    r"(识别|发现|存在)?\s*(?:内控)?\s*缺陷\s*(?:共|计)?\s*(\d+)\s*[项个条]"
)


def _year(text: str) -> Optional[int]:
    m = _YEAR_RE.search(text[:500]) or _YEAR_RE.search(text)
    return int(m.group(1)) if m else None


_NEGATION = ("未", "尚未", "暂未", "无", "没有")


def _present_without_negation(text: str, keywords) -> bool:
    """检查关键词出现且不在否定语境（前 8 个字符内含否定词）中。

    例：'验收尚未完成' / '未验收' / '尚未结项' 不应算作存在该事项。
    """
    for kw in keywords:
        for m in re.finditer(re.escape(kw), text):
            start = max(0, m.start() - 8)
            window = text[start:m.end() + 4]
            if any(n in window for n in _NEGATION):
                continue
            return True
    return False


def _projects(text: str) -> List[str]:
    names: list[str] = []
    for m in _PROJECT_NAME_LABELS.finditer(text):
        n = m.group(1).strip()
        if n and n not in names:
            names.append(n)
    for m in _PROJECT_QUOTE.finditer(text):
        n = m.group(1).strip()
        if n and n not in names:
            names.append(n)
    return names


def extract_internal_control_report(doc: ParsedDocument) -> InternalControlReportFields:
    text = doc.text
    # 自我评价结论：在「评价结论/自我评价」标签后 200 字范围内找包含「有效/无效/健全/不健全」的短句
    evaluation_result = ""
    label_m = re.search(r"(评价结论|自我评价|内控.{0,4}有效性|内部控制.{0,2}评价)", text)
    if label_m:
        tail = text[label_m.end(): label_m.end() + 200]
        concl = re.search(r"([^\n。；;]*?(?:基本)?(?:有效|健全|无效|不健全|存在缺陷)[^\n。；;]*)",
                          tail)
        if concl:
            evaluation_result = concl.group(1).strip("：: \t")

    def_m = _DEFICIENCY_COUNT_RE.search(text)
    deficiency_count = int(def_m.group(2)) if def_m else None

    return InternalControlReportFields(
        year=_year(text),
        project_mentions=_projects(text),
        deficiency_count=deficiency_count,
        evaluation_result=evaluation_result,
    )


def extract_performance_report(doc: ParsedDocument) -> PerformanceReportFields:
    text = doc.text
    projects = _projects(text)
    project_name = projects[0] if projects else ""

    sm = _SCORE_RE.search(text)
    score = float(sm.group(2)) if sm else None
    gm = _GRADE_RE.search(text)
    grade = gm.group(2) if gm else ""

    has_problems = any(k in text for k in ("存在问题", "主要问题", "改进建议", "整改建议"))

    return PerformanceReportFields(
        year=_year(text),
        project_name=project_name,
        score=score,
        grade=grade,
        has_problems=has_problems,
    )


def extract_project_material(doc: ParsedDocument) -> ProjectMaterialFields:
    text = doc.text
    projects = _projects(text)
    has_approval = _present_without_negation(text, ("立项批复", "立项申请", "立项报告", "审批", "批复"))
    has_completion = _present_without_negation(text, ("验收", "竣工", "完工", "验收报告", "结项"))
    return ProjectMaterialFields(
        project_name=projects[0] if projects else "",
        has_approval=has_approval,
        has_completion=has_completion,
    )
