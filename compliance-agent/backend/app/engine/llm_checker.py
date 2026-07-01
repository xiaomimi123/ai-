"""LLM 语义检查器（v3 §3.4 路径 B）。

按 v3 §3.4 的 Prompt 模板组装：评价指标 + 评分细则 + 常见扣分情形 + 法规 + 问题清单 + 材料正文，
要求模型严格输出指定 JSON。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy.orm import Session

from app.engine.rule_checker import RuleFinding
from app.llm import LLMClient
from app.models.entities import CheckItem, Indicator, Material


SYSTEM_PROMPT = (
    "你是一名专业的行政事业单位内部控制评价审查专家。\n"
    "你的任务是：站在上级复核方视角，依据评价指标、评分细则、常见扣分情形、相关法规，"
    "审查被检查单位提交的材料是否真实、合规、完整。\n\n"
    "严格遵守：\n"
    "1) 只引用提供的法规条款和评价指南内容，绝不编造任何法规条款或扣分细则；\n"
    "2) 问题描述必须客观、简洁，并指明材料中的具体内容或位置；\n"
    "3) 如材料满足要求，findings 数组返回空 []；\n"
    "4) 只输出 JSON，不要任何额外解释文字。"
)


_USER_PROMPT_TMPL = """【评价指标】
{indicator_block}

【评分细则与扣分规则】
{deduct_rules}

【常见扣分情形】（来自编报指南附件1/2，是判断标准的黄金参照）
{common_deductions}

【相关法规条款】（来自检索结果）
{legal_basis}

【核查问题清单】（适用本指标的检查点）
{check_items_block}

【被核查材料】（文件名：{file_name}）
{material_content}

请严格按照以下 JSON 格式输出核查结果：
{{
  "overall_judgment": "pass|warning|fail",
  "findings": [
    {{
      "check_item_code": "对应的问题清单条目 code（无则填空）",
      "finding_type": "真实性问题|相关性问题|完整性问题|合规性问题|评分合规问题|复核规范问题|报告编报问题",
      "severity": "高|中|低",
      "description": "客观、简洁的问题描述，引用材料中的具体内容或位置",
      "evidence_location": "问题在材料中的页码/章节/段落",
      "legal_basis": "对应法规条款原文（只能引用上方提供的内容）",
      "suggestion": "整改建议"
    }}
  ],
  "missing_materials": ["材料中缺失但应有的内容清单"],
  "irrelevant_materials": ["与本指标不相关的材料/段落"]
}}
"""


@dataclass
class LLMFinding:
    finding_type: str
    severity: str
    description: str
    evidence_location: str = ""
    legal_basis: str = ""
    suggestion: str = ""
    check_item_code: str = ""


def _format_check_items(items: List[CheckItem]) -> str:
    if not items:
        return "（无）"
    lines = []
    for it in items:
        patterns = ""
        try:
            patterns_list = json.loads(it.common_patterns or "[]")
            if patterns_list:
                patterns = "（常见问题：" + "；".join(patterns_list) + "）"
        except Exception:
            pass
        lines.append(
            f"- [{it.item_code}] {it.dimension}/{it.subcategory}：{it.description}{patterns}"
        )
    return "\n".join(lines)


def _format_indicator_block(indicator: Optional[Indicator]) -> str:
    if indicator is None:
        return "（未指定指标）"
    return (
        f"指标编号：{indicator.indicator_code}\n"
        f"指标名称：{indicator.name}\n"
        f"分类：{indicator.category}/{indicator.subcategory}\n"
        f"满分：{indicator.max_score}\n"
        f"描述：{indicator.description}"
    )


def build_prompt(
    material: Material,
    text: str,
    indicator: Optional[Indicator],
    check_items: List[CheckItem],
    legal_basis: str = "（暂无检索到的法规条款）",
) -> str:
    """组装单份材料 + 单个指标 的核查 prompt。"""
    body = text[:8000]  # 控制 token 量
    return _USER_PROMPT_TMPL.format(
        indicator_block=_format_indicator_block(indicator),
        deduct_rules=(indicator.deduct_rules if indicator else "（未指定）") or "（无）",
        common_deductions=(indicator.common_deductions if indicator else "（未指定）") or "（无）",
        legal_basis=legal_basis,
        check_items_block=_format_check_items(check_items),
        file_name=material.file_name,
        material_content=body,
    )


def run_llm_checks(
    llm: LLMClient,
    material: Material,
    text: str,
    indicator: Optional[Indicator],
    check_items: List[CheckItem],
    legal_basis: str = "",
) -> List[LLMFinding]:
    """调用 LLM 输出结构化核查结果。"""
    # 只跑 llm 类型的 check_items
    llm_items = [it for it in check_items if it.check_method == "llm"]
    prompt = build_prompt(material, text, indicator, llm_items, legal_basis or "（暂无检索到的法规条款）")

    try:
        data = llm.extract_json(prompt, system=SYSTEM_PROMPT)
    except Exception as exc:
        # v2.2：余额不足是致命错误，向上抛让 orchestrator 顶层 except 分类 + 终止任务
        from app.engine.errors import is_insufficient_balance
        if is_insufficient_balance(exc):
            raise
        # 其它 LLM 抖动仍容忍：单次调用失败不阻塞整个任务，返回空 findings
        return []

    if not isinstance(data, dict):
        return []

    findings: List[LLMFinding] = []
    for item in data.get("findings", []) or []:
        if not isinstance(item, dict) or not item.get("description"):
            continue
        findings.append(LLMFinding(
            finding_type=str(item.get("finding_type", "合规性问题")),
            severity=str(item.get("severity", "中")),
            description=str(item["description"])[:2000],
            evidence_location=str(item.get("evidence_location", ""))[:500],
            legal_basis=str(item.get("legal_basis", ""))[:2000],
            suggestion=str(item.get("suggestion", ""))[:1000],
            check_item_code=str(item.get("check_item_code", "")),
        ))

    return findings
