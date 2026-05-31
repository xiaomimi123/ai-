"""合同全流程检查模板的刚性规则（§3.4 示例）。

均为确定性校验，不调用 LLM：关键词/正则/字段提取/一致性判断。
"""
from __future__ import annotations

import re
from typing import List

from app.core.domain import Issue, IssueCategory, Location, RiskLevel
from app.parsers.base import ParsedDocument
from app.rules.base import RigidRule
from app.rules.utils import locate, parse_arabic_amount, parse_cn_amount

# 大写金额子串：连续的大写数字/单位字符
_CN_AMOUNT_RUN = re.compile(r"[零壹贰叁肆伍陆柒捌玖拾佰仟万亿圆元角分整]{2,}")


class ContractNumberRule(RigidRule):
    id = "contract.number"
    description = "合同编号/合同文号是否存在"
    _re = re.compile(r"(合同[编文]?号|协议编号)\s*[:：]?\s*([A-Za-z0-9\-（）()]+)")

    def check(self, doc: ParsedDocument) -> List[Issue]:
        if self._re.search(doc.text):
            return []
        return [Issue(
            description="未检出合同编号/合同文号。合同应有唯一编号以便归档与追溯。",
            location=Location(file_name=doc.metadata.get("file_name", "")),
            category=IssueCategory.FORMAT,
            risk_level=RiskLevel.MEDIUM,
            suggestion="补充合同编号，并纳入合同台账统一编号管理。",
            rule_id=self.id,
        )]


class SignDateRule(RigidRule):
    id = "contract.sign_date"
    description = "签订日期是否存在"
    _re = re.compile(r"(签订|签署|订立)?\s*(日期|时间)?\s*[:：]?\s*\d{4}\s*[年./-]\s*\d{1,2}\s*[月./-]\s*\d{1,2}")

    def check(self, doc: ParsedDocument) -> List[Issue]:
        if self._re.search(doc.text):
            return []
        return [Issue(
            description="未检出明确的合同签订日期。",
            location=Location(file_name=doc.metadata.get("file_name", "")),
            category=IssueCategory.FORMAT,
            risk_level=RiskLevel.MEDIUM,
            suggestion="在合同落款处补充签订日期（年月日）。",
            rule_id=self.id,
        )]


class PartiesRule(RigidRule):
    id = "contract.parties"
    description = "甲方/乙方主体是否齐全"

    def check(self, doc: ParsedDocument) -> List[Issue]:
        issues: List[Issue] = []
        for label in ("甲方", "乙方"):
            # 要求「甲方：xxx」同一行内有非空主体（不跨行，避免误抓下一行内容）
            m = re.search(rf"{label}\s*[（(]?[^\n:：]*[:：][ \t]*([^\n，,。；;]*)", doc.text)
            present = bool(m and len(m.group(1).strip()) >= 2)
            if not present:
                issues.append(Issue(
                    description=f"未检出{label}主体名称，合同当事人信息可能不完整。",
                    location=locate(doc, label),
                    category=IssueCategory.FORMAT,
                    risk_level=RiskLevel.HIGH,
                    suggestion=f"补充{label}的完整法定名称。",
                    rule_id=self.id,
                ))
        return issues


class AmountConsistencyRule(RigidRule):
    id = "contract.amount_consistency"
    description = "金额大小写一致性"

    def check(self, doc: ParsedDocument) -> List[Issue]:
        issues: List[Issue] = []
        for block in doc.page_blocks:
            content = block.content
            cn_match = _CN_AMOUNT_RUN.search(content)
            if not cn_match:
                continue
            cn_val = parse_cn_amount(cn_match.group())
            ar_val = parse_arabic_amount(content)
            if cn_val is None or ar_val is None:
                continue
            if abs(cn_val - ar_val) > 0.01:
                issues.append(Issue(
                    description=(
                        f"金额大小写不一致：大写「{cn_match.group()}」解析为 {cn_val}，"
                        f"小写金额为 {ar_val}。"
                    ),
                    location=Location(file_name=doc.metadata.get("file_name", ""),
                                      page=block.page, section=block.section),
                    category=IssueCategory.CONSISTENCY,
                    risk_level=RiskLevel.HIGH,
                    suggestion="核对并统一合同金额的大写与小写。",
                    rule_id=self.id,
                ))
        return issues


class RequiredClausesRule(RigidRule):
    id = "contract.required_clauses"
    description = "必备条款是否缺失（付款方式/违约责任/合同期限）"
    REQUIRED = {
        "付款方式": ["付款方式", "支付方式", "付款条件", "价款支付"],
        "违约责任": ["违约责任", "违约金", "违约处理"],
        "合同期限": ["合同期限", "履行期限", "服务期限", "有效期"],
    }

    def check(self, doc: ParsedDocument) -> List[Issue]:
        issues: List[Issue] = []
        text = doc.text
        for clause, keywords in self.REQUIRED.items():
            if not any(k in text for k in keywords):
                issues.append(Issue(
                    description=f"未检出「{clause}」相关条款，合同要素可能缺失。",
                    location=Location(file_name=doc.metadata.get("file_name", "")),
                    category=IssueCategory.PROCESS,
                    risk_level=RiskLevel.MEDIUM,
                    suggestion=f"补充「{clause}」条款，明确双方权利义务。",
                    rule_id=self.id,
                ))
        return issues


class SealRule(RigidRule):
    id = "contract.seal"
    description = "签章/盖章留痕关键词是否缺失"
    KEYWORDS = ["盖章", "签章", "公章", "（盖章）", "(盖章)", "签字", "签名", "法定代表人"]

    def check(self, doc: ParsedDocument) -> List[Issue]:
        if any(k in doc.text for k in self.KEYWORDS):
            return []
        return [Issue(
            description="未检出签章/盖章/签字相关留痕，合同生效要件可能缺失。",
            location=Location(file_name=doc.metadata.get("file_name", "")),
            category=IssueCategory.PROCESS,
            risk_level=RiskLevel.HIGH,
            suggestion="确认合同已由双方签字并加盖公章，扫描件需清晰可见印章。",
            rule_id=self.id,
        )]


CONTRACT_RIGID_RULES = [
    ContractNumberRule(),
    SignDateRule(),
    PartiesRule(),
    AmountConsistencyRule(),
    RequiredClausesRule(),
    SealRule(),
]
