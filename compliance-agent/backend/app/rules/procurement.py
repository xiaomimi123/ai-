"""招采三合一检查模板的刚性规则（§3.4）。

覆盖招标 / 投标 / 评标三个子类的单文件形式与要素校验。
单份文档先确定子类（优先用上传标注的 subcategory，否则按内容识别），
各规则只对自己负责的子类生效；其字段抽取也为 Phase 3 招采链联动打基础。
"""
from __future__ import annotations

import re
from typing import List, Optional

from app.core.domain import Issue, IssueCategory, Location, RiskLevel
from app.parsers.base import ParsedDocument
from app.rules.base import RigidRule

# ---------- 子类识别 ----------
_SUBTYPE_ANCHORS = {
    "招标": [("招标文件", 3), ("招标公告", 3), ("招标编号", 3), ("最高限价", 2),
            ("招标人", 2), ("采购人", 1), ("投标人须知", 2)],
    "投标": [("投标文件", 3), ("投标函", 3), ("投标书", 3), ("投标报价", 2),
            ("投标总价", 2), ("法定代表人授权", 1)],
    "评标": [("评标报告", 4), ("评标委员会", 3), ("中标候选人", 3), ("评标办法", 2),
            ("评标结果", 2), ("评委", 2)],
}


def detect_subtype(text: str) -> str:
    scores = {st: sum(w * text.count(kw) for kw, w in anchors)
              for st, anchors in _SUBTYPE_ANCHORS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "未知"


def resolve_subtype(doc: ParsedDocument) -> str:
    sub = doc.metadata.get("subcategory", "") or ""
    for st in ("招标", "投标", "评标"):
        if st in sub:
            return st
    return detect_subtype(doc.text)


def _loc(doc: ParsedDocument) -> Location:
    return Location(file_name=doc.metadata.get("file_name", ""))


class ProcurementRule(RigidRule):
    """招采规则基类：仅当文档子类与 target_subtype 匹配时执行 _check。"""
    target_subtype: str = ""

    def check(self, doc: ParsedDocument) -> List[Issue]:
        if resolve_subtype(doc) != self.target_subtype:
            return []
        return self._check(doc)

    def _check(self, doc: ParsedDocument) -> List[Issue]:  # pragma: no cover
        raise NotImplementedError


def _missing(doc, rule_id, desc, suggestion, risk=RiskLevel.MEDIUM,
             category=IssueCategory.FORMAT) -> Issue:
    return Issue(description=desc, location=_loc(doc), category=category,
                 risk_level=risk, suggestion=suggestion, rule_id=rule_id)


# ===================== 招标文件 =====================
class TenderNumberRule(ProcurementRule):
    id = "proc.tender.number"
    target_subtype = "招标"
    description = "招标/项目编号是否存在"
    _re = re.compile(r"(招标|项目|采购)\s*编号\s*[:：]?\s*\S+")

    def _check(self, doc):
        if self._re.search(doc.text):
            return []
        return [_missing(doc, self.id, "未检出招标/项目编号。",
                         "补充唯一招标编号，便于全流程追溯。")]


class TenderBudgetRule(ProcurementRule):
    id = "proc.tender.budget"
    target_subtype = "招标"
    description = "招标预算/最高限价是否公开"
    KEYWORDS = ("预算金额", "招标控制价", "最高限价", "预算价", "采购预算")

    def _check(self, doc):
        if any(k in doc.text for k in self.KEYWORDS):
            return []
        return [_missing(doc, self.id, "未检出招标预算金额/最高限价。",
                         "依规公开招标预算或最高限价。",
                         risk=RiskLevel.HIGH, category=IssueCategory.COMPLIANCE)]


class TenderDeadlineRule(ProcurementRule):
    id = "proc.tender.deadline"
    target_subtype = "招标"
    description = "投标截止/开标时间是否明确"
    KEYWORDS = ("投标截止", "递交投标文件截止", "开标时间", "投标文件递交截止")

    def _check(self, doc):
        if any(k in doc.text for k in self.KEYWORDS):
            return []
        return [_missing(doc, self.id, "未检出投标截止时间/开标时间。",
                         "明确投标截止时间与开标时间、地点。")]


class TenderQualificationRule(ProcurementRule):
    id = "proc.tender.qualification"
    target_subtype = "招标"
    description = "投标人资格要求是否载明"
    KEYWORDS = ("资格要求", "资格条件", "投标人资格", "资质要求", "资格审查")

    def _check(self, doc):
        if any(k in doc.text for k in self.KEYWORDS):
            return []
        return [_missing(doc, self.id, "未检出投标人资格要求。",
                         "明确投标人资格条件与资格审查方式。")]


class TenderEvalMethodRule(ProcurementRule):
    id = "proc.tender.eval_method"
    target_subtype = "招标"
    description = "评标办法/评审标准是否载明"
    KEYWORDS = ("评标办法", "评审办法", "评标标准", "评分标准", "评审标准", "综合评分")

    def _check(self, doc):
        if any(k in doc.text for k in self.KEYWORDS):
            return []
        return [_missing(doc, self.id, "未检出评标办法/评审标准。",
                         "载明评标办法与评分标准，确保评审可量化、可追溯。",
                         category=IssueCategory.COMPLIANCE)]


# ===================== 投标文件 =====================
class BidBidderRule(ProcurementRule):
    id = "proc.bid.bidder"
    target_subtype = "投标"
    description = "投标人名称是否明确"
    _re = re.compile(r"投标人\s*[（(]?\s*(名称)?\s*[：:][ \t]*([^\n，,。；;]*)")

    def _check(self, doc):
        m = self._re.search(doc.text)
        if m and len(m.group(2).strip()) >= 2:
            return []
        return [_missing(doc, self.id, "未检出投标人名称。", "补充投标人完整名称。")]


class BidPriceRule(ProcurementRule):
    id = "proc.bid.price"
    target_subtype = "投标"
    description = "投标报价是否明确"
    KEYWORDS = ("投标报价", "投标总价", "投标总报价", "报价金额", "投标价")

    def _check(self, doc):
        if any(k in doc.text for k in self.KEYWORDS):
            return []
        return [_missing(doc, self.id, "未检出投标报价。",
                         "明确投标总报价（含大小写金额）。",
                         risk=RiskLevel.HIGH)]


class BidValidityRule(ProcurementRule):
    id = "proc.bid.validity"
    target_subtype = "投标"
    description = "投标有效期是否载明"
    KEYWORDS = ("投标有效期", "有效期为", "投标文件有效期")

    def _check(self, doc):
        if any(k in doc.text for k in self.KEYWORDS):
            return []
        return [_missing(doc, self.id, "未检出投标有效期。", "载明投标有效期天数。")]


class BidSignatureRule(ProcurementRule):
    id = "proc.bid.signature"
    target_subtype = "投标"
    description = "签字/盖章/授权是否齐全"
    KEYWORDS = ("法定代表人", "授权委托", "签字", "盖章", "公章", "签章")

    def _check(self, doc):
        if any(k in doc.text for k in self.KEYWORDS):
            return []
        return [_missing(doc, self.id, "未检出投标文件签字/盖章/授权委托留痕。",
                         "由法定代表人或授权代表签字并加盖单位公章。",
                         risk=RiskLevel.HIGH, category=IssueCategory.PROCESS)]


# ===================== 评标报告 =====================
class EvalCommitteeRule(ProcurementRule):
    id = "proc.eval.committee"
    target_subtype = "评标"
    description = "评标委员会组成是否载明"
    KEYWORDS = ("评标委员会", "评审委员会", "评标专家", "评委会")

    def _check(self, doc):
        if any(k in doc.text for k in self.KEYWORDS):
            return []
        return [_missing(doc, self.id, "未检出评标委员会组成。",
                         "载明评标委员会人数与组成（专家/采购人代表）。",
                         category=IssueCategory.COMPLIANCE)]


class EvalResultRule(ProcurementRule):
    id = "proc.eval.result"
    target_subtype = "评标"
    description = "中标候选人/评标结果是否明确"
    KEYWORDS = ("中标候选人", "推荐中标", "评标结果", "排名", "中标人")

    def _check(self, doc):
        if any(k in doc.text for k in self.KEYWORDS):
            return []
        return [_missing(doc, self.id, "未检出中标候选人/评标结果。",
                         "明确中标候选人排序及推荐结果。", risk=RiskLevel.HIGH)]


class EvalMethodAppliedRule(ProcurementRule):
    id = "proc.eval.method"
    target_subtype = "评标"
    description = "评标办法/打分依据是否体现"
    KEYWORDS = ("评标办法", "评分", "打分", "评审因素", "得分")

    def _check(self, doc):
        if any(k in doc.text for k in self.KEYWORDS):
            return []
        return [_missing(doc, self.id, "未检出评分/评标办法的执行过程。",
                         "附评分汇总表，体现各评审因素得分。")]


class EvalSignatureRule(ProcurementRule):
    id = "proc.eval.signature"
    target_subtype = "评标"
    description = "评委签字是否齐全"
    KEYWORDS = ("评委签字", "评标委员会成员签字", "专家签字", "签字确认", "签名")

    def _check(self, doc):
        if any(k in doc.text for k in self.KEYWORDS):
            return []
        return [_missing(doc, self.id, "未检出评标委员会成员签字。",
                         "评标报告应由全体评委签字确认。",
                         risk=RiskLevel.HIGH, category=IssueCategory.PROCESS)]


# ===================== 子类识别提示 =====================
class SubtypeRule(RigidRule):
    id = "proc.subtype"
    description = "招采文件子类是否可识别"

    def check(self, doc: ParsedDocument) -> List[Issue]:
        if resolve_subtype(doc) != "未知":
            return []
        return [Issue(
            description="无法识别该招采文件子类（招标/投标/评标），相关要素检查可能未执行。",
            location=_loc(doc),
            category=IssueCategory.OTHER,
            risk_level=RiskLevel.LOW,
            suggestion="上传时标注子类（subcategory=招标/投标/评标），或确认文件内容完整。",
            rule_id=self.id,
        )]


PROCUREMENT_RIGID_RULES = [
    SubtypeRule(),
    # 招标
    TenderNumberRule(), TenderBudgetRule(), TenderDeadlineRule(),
    TenderQualificationRule(), TenderEvalMethodRule(),
    # 投标
    BidBidderRule(), BidPriceRule(), BidValidityRule(), BidSignatureRule(),
    # 评标
    EvalCommitteeRule(), EvalResultRule(), EvalMethodAppliedRule(), EvalSignatureRule(),
]
