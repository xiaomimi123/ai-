"""刚性规则检查器（v3 §3.4 路径 A）。

不调 LLM，仅根据 key_elements + 关键词匹配判断。
覆盖：真实性 / 年度一致性 / 正式性 / 要素完整性 / 关键词命中 / 补充指标总分。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import List, Optional

from app.models.entities import CheckItem, Indicator, Material
from app.parsers.base import KeyElements


@dataclass
class RuleFinding:
    finding_type: str
    severity: str           # 高 | 中 | 低
    description: str
    evidence_location: str = ""
    legal_basis: str = ""
    suggestion: str = ""
    check_item_id: Optional[int] = None


# ============================================================
# 真实性 / 完整性 / 年度 / 正式性（v3 §3.4 示例）
# ============================================================
def check_authenticity(material: Material, ke: KeyElements,
                       eval_year: int = 2025) -> List[RuleFinding]:
    """检查公章 / 签字 / 草稿 / 年度。

    V3 规则按文件类型分级：
    - PDF 扫描件（is_scanned=True）→ 公章/签字检查（高/中风险）
    - 普通 PDF / Word → 不检查公章签字（这些格式自带电子流转，签章在元数据里）
    - txt / md 等纯文本 → 完全跳过格式性检查
    草稿检测对所有格式都做。
    """
    findings: List[RuleFinding] = []
    ft = (material.file_type or "").lower()
    is_text_only = ft in ("txt", "md")
    is_scanned_pdf = ft == "pdf" and material.is_scanned

    if not is_text_only:
        # 仅对扫描件 PDF 严格查公章/签字（纸质件标配）
        if is_scanned_pdf and not ke.has_official_seal:
            findings.append(RuleFinding(
                finding_type="真实性问题",
                severity="中",
                description=f"材料《{material.file_name}》（扫描件）未检出公章/签章关键词。",
                evidence_location="全文",
                suggestion="确认原件已加盖单位公章并重新扫描清晰版本。",
            ))
        if is_scanned_pdf and not ke.has_signature:
            findings.append(RuleFinding(
                finding_type="真实性问题",
                severity="中",
                description=f"材料《{material.file_name}》（扫描件）未检出签字关键词。",
                evidence_location="全文",
                suggestion="补充负责人/经办人签字。",
            ))

    if ke.is_draft:
        findings.append(RuleFinding(
            finding_type="合规性问题",  # 草稿 = 形式合规问题，归入合规性
            severity="中",
            description=f"材料《{material.file_name}》疑似草稿/征求意见稿，非正式印发文件。",
            evidence_location="标题或正文开头",
            suggestion="提交正式印发版本。",
        ))

    return findings


def check_year_consistency(material: Material, ke: KeyElements,
                           eval_year: int) -> List[RuleFinding]:
    """V3：未检出日期改为低风险（只是无法验证年度）；明确不是评价年度才高风险。"""
    ft = (material.file_type or "").lower()
    if ft in ("txt", "md"):
        return []  # 纯文本完全跳过
    if ke.issue_year is None:
        return [RuleFinding(
            finding_type="真实性问题",   # 归一为真实性
            severity="低",                # 无法判定 ≠ 不合规，仅低风险提示
            description=f"材料《{material.file_name}》未检出日期，无法验证是否为 {eval_year} 年度材料。",
            evidence_location="全文",
            suggestion=f"在落款处补充明确的年月日，以确认 {eval_year} 年度归属。",
        )]
    if ke.issue_year != eval_year:
        return [RuleFinding(
            finding_type="真实性问题",
            severity="高",                # 错误年度 = 高风险
            description=f"材料《{material.file_name}》日期为 {ke.issue_year} 年，"
                        f"非评价对应年度 {eval_year} 年。",
            evidence_location=ke.issue_date or "全文",
            suggestion=f"替换为 {eval_year} 年度对应材料。",
        )]
    return []


def check_required_elements(material: Material, ke: KeyElements) -> List[RuleFinding]:
    """要素完整性 — 文号 / 日期。

    V3：纯文本（txt/md）不要求这些办公文件元数据。
    其它格式没有文号 / 日期只算"低风险提示"而非"中风险"。
    """
    findings: List[RuleFinding] = []
    ft = (material.file_type or "").lower()
    if ft in ("txt", "md"):
        return findings

    missing = []
    if not ke.document_number:
        missing.append("发文文号")
    if not ke.issue_date:
        missing.append("印发日期")
    if missing:
        findings.append(RuleFinding(
            finding_type="完整性问题",
            severity="低",     # 缺要素改为低风险，少扣分
            description=f"材料《{material.file_name}》缺少要素：{' / '.join(missing)}。",
            evidence_location="文首/落款",
            suggestion=f"在文档中补充 {' / '.join(missing)}。",
        ))
    return findings


# ============================================================
# 关键词命中型 CheckItem
# ============================================================
def check_by_check_item(material: Material, ke: KeyElements,
                        text: str, item: CheckItem) -> List[RuleFinding]:
    """运行单条 rule 类型 CheckItem。

    仅当问题清单中 check_method=rule 时被调用。
    """
    findings: List[RuleFinding] = []

    # 真实性子项：再次确认 has_official_seal/signature
    if item.subcategory == "真实性":
        findings.extend(check_authenticity(material, ke))
        return findings

    # 年度一致性
    if item.subcategory == "年度一致性":
        # 默认 2025；任务调用方应通过 eval_year 传入
        return []  # 在 orchestrator 层调 check_year_consistency

    # 正式性：扫描 draft 关键词
    if item.subcategory == "正式性":
        if ke.is_draft:
            findings.append(RuleFinding(
                finding_type="正式性问题",
                severity=item.risk_level,
                description=f"材料《{material.file_name}》疑似{', '.join(_kw_list(item))}。",
                evidence_location="文首",
                suggestion="提交正式印发版本。",
                check_item_id=item.id,
            ))
        return findings

    # 要素完整性：复用 check_required_elements
    if item.subcategory == "要素完整性":
        findings.extend(check_required_elements(material, ke))
        return findings

    # 普通关键词命中：keywords 中任一在 text 中出现即视为命中（不报警）；
    # 全都不在文中则报缺失
    keywords = _kw_list(item)
    if keywords:
        hit = any(k in text for k in keywords)
        if not hit:
            findings.append(RuleFinding(
                finding_type="完整性问题",
                severity=item.risk_level,
                description=f"材料《{material.file_name}》未检出关键词「{'、'.join(keywords)}」，"
                            f"问题清单条目 {item.item_code}（{item.description}）相关要素可能缺失。",
                evidence_location="全文",
                suggestion=f"核对材料内容是否覆盖：{item.description}",
                check_item_id=item.id,
            ))

    return findings


def _kw_list(item: CheckItem) -> List[str]:
    try:
        return json.loads(item.keywords or "[]")
    except Exception:
        return []


# ============================================================
# 编排：对单份材料跑全部刚性规则
# ============================================================
def run_rule_checks(
    material: Material,
    text: str,
    ke: KeyElements,
    indicator: Optional[Indicator],
    check_items: List[CheckItem],
    eval_year: int = 2025,
) -> List[RuleFinding]:
    """对单份材料执行所有适用的刚性规则。"""
    findings: List[RuleFinding] = []

    # 1) 通用：真实性 + 年度 + 完整性
    findings.extend(check_authenticity(material, ke, eval_year))
    findings.extend(check_year_consistency(material, ke, eval_year))
    findings.extend(check_required_elements(material, ke))

    # 2) 问题清单中 rule 类型的条目，过滤适用本指标的
    applicable = [it for it in check_items if it.check_method == "rule"]
    if indicator:
        applicable = [
            it for it in applicable
            if not it.applicable_indicators or
               indicator.indicator_code in _ind_list(it)
        ]
    for item in applicable:
        # 这些已在 1) 中覆盖了
        if item.subcategory in ("真实性", "年度一致性", "要素完整性"):
            continue
        findings.extend(check_by_check_item(material, ke, text, item))

    return findings


def _ind_list(item: CheckItem) -> List[str]:
    try:
        return json.loads(item.applicable_indicators or "[]")
    except Exception:
        return []
