"""从 PDF/Word/Excel 等办公文件结构化抽取评价指标 / 问题清单。

主路径：LLM JSON-mode 抽取（DeepSeek 已支持 response_format=json_object）
兜底路径：正则启发式识别"X-X-X" 编号 + 后续文字
"""
from __future__ import annotations

import json
import re
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.domain import DIMENSIONS
from app.llm import get_llm_client
from app.llm.stub import StubLLMClient
from app.parsers import parse, SUPPORTED_EXTENSIONS
from app.parsers.dispatcher import UnsupportedFormatError


SYSTEM_PROMPT_INDICATORS = (
    "你是行政事业单位内部控制评价数据整理助手。"
    "我会给你一段从编报指南附件 1/2（评价指标手册）中解析出的文本，"
    "请抽取其中的『评价指标条目』，输出严格 JSON。\n"
    "严格遵守：\n"
    "1) 只输出 JSON，不要任何额外文字或 markdown 包裹；\n"
    "2) 不要编造原文中没有的指标；\n"
    "3) indicator_code 必须是原文中的指标编号（如 1-1-1 / 2-3-2）；\n"
    "4) max_score 必须是原文中明确写的数值；如果没有写则填 0；\n"
    "5) 没有的字段填空字符串或空数组，不要瞎填。"
)

INDICATOR_USER_TMPL = """从下面的文本抽取评价指标，输出格式严格为：
{{
  "indicators": [
    {{
      "indicator_code": "1-1-1",
      "level": "单位",
      "category": "组织层面",
      "subcategory": "决策机制",
      "name": "三重一大决策制度建立与执行",
      "description": "...",
      "max_score": 4,
      "deduct_rules": "原文中的扣分规则",
      "common_deductions": "原文中列举的常见扣分情形",
      "required_materials": ["三重一大制度文件", "会议纪要"]
    }}
  ]
}}

每个指标的 level 字段值只能是「单位」或「部门」。
category 字段为业务大类（组织层面/预算业务/收支业务/政府采购/资产建设合同/内部监督）。

【文本（前 {limit} 字符）】
{text}
"""


SYSTEM_PROMPT_CHECK_ITEMS = (
    "你是行政事业单位内部控制评价数据整理助手。"
    "我会给你一段从『佐证材料核查清单』或『常见问题清单』中解析出的文本，"
    "请抽取其中的『核查清单条目』，输出严格 JSON。\n"
    "严格遵守：\n"
    "1) 只输出 JSON，不要任何额外文字；\n"
    "2) 不要编造原文中没有的条目；\n"
    "3) dimension 字段必须是以下之一：" + " / ".join(DIMENSIONS) + "；\n"
    "4) check_method 只能是 'rule' 或 'llm'；如果条目主要靠关键词/格式检测就用 rule，需要语义理解用 llm；\n"
    "5) risk_level 只能是 高 / 中 / 低。"
)

CHECK_ITEMS_USER_TMPL = """从下面的文本抽取核查清单条目，输出格式严格为：
{{
  "items": [
    {{
      "item_code": "TZ-001",
      "dimension": "总体合规性",
      "subcategory": "真实性",
      "description": "材料是否加盖公章、签字齐全",
      "applicable_indicators": [],
      "risk_level": "高",
      "common_patterns": ["缺公章", "签字缺失"],
      "check_method": "rule",
      "keywords": ["盖章", "签字"]
    }}
  ]
}}

每条目至少要有 item_code / dimension / description 字段，其余可缺省。
item_code 可参照原文编号；若原文无编号则按文本顺序生成 EXT-001、EXT-002…

【文本（前 {limit} 字符）】
{text}
"""


def _parse_to_text(file_name: str, content: bytes) -> str:
    """解析文件内容到文本。失败抛 UnsupportedFormatError。"""
    from pathlib import Path
    import tempfile
    import uuid

    suffix = Path(file_name).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(
            f"不支持的格式 {suffix}（支持 {', '.join(SUPPORTED_EXTENSIONS)}）"
        )
    # 写临时文件再 parse（parsers 接受路径）
    tmp = Path(tempfile.gettempdir()) / f"extract_{uuid.uuid4().hex}{suffix}"
    tmp.write_bytes(content)
    try:
        parsed = parse(str(tmp), use_cache=False)
        return parsed.text or ""
    finally:
        try:
            tmp.unlink()
        except Exception:
            pass


# ----- 正则兜底 -----
_INDICATOR_LINE_RE = re.compile(
    r"^[\s\d]*(\d{1,2}-\d{1,2}-\d{1,2})[\s\.、,]+([^\n]{2,80})"
)
_SCORE_RE = re.compile(r"(满分|分值|分数|总分)[^0-9]{0,5}(\d+(?:\.\d+)?)")


def _heuristic_indicators(text: str) -> list[dict]:
    """无 LLM 时的兜底：按行扫描 N-N-N 开头的行。"""
    results = []
    for line in text.splitlines():
        line = line.strip()
        m = _INDICATOR_LINE_RE.match(line)
        if not m:
            continue
        code, name = m.group(1), m.group(2).strip()
        # 截掉名称里的尾部数字（满分）
        score_m = re.search(r"(\d+(?:\.\d+)?)\s*分?\s*$", name)
        max_score = 0
        if score_m:
            try:
                max_score = float(score_m.group(1))
                name = name[: score_m.start()].rstrip("：:—-。 \t")
            except ValueError:
                pass
        results.append({
            "indicator_code": code,
            "level": "单位",
            "category": "",
            "subcategory": "",
            "name": name[:80],
            "description": "",
            "max_score": max_score,
            "deduct_rules": "",
            "common_deductions": "",
            "required_materials": [],
        })
    return results


def _heuristic_check_items(text: str) -> list[dict]:
    """兜底：扫描"X-001"形式的清单条目。"""
    pattern = re.compile(r"^([A-Z]{1,4}-\d{3})[\s\.、:：,]+([^\n]{4,200})", re.MULTILINE)
    results = []
    for m in pattern.finditer(text):
        code = m.group(1).strip()
        desc = m.group(2).strip()
        results.append({
            "item_code": code,
            "dimension": "总体合规性",
            "subcategory": "",
            "description": desc[:200],
            "applicable_indicators": [],
            "risk_level": "中",
            "common_patterns": [],
            "check_method": "llm",
            "keywords": [],
        })
    return results


# ----- 主入口 -----
def extract_indicators(db: Session, file_name: str, content: bytes,
                       max_chars: int = 12000) -> tuple[list[dict], str]:
    """从办公文件抽取指标。返回 (条目列表, 来源说明)。"""
    text = _parse_to_text(file_name, content)
    if not text.strip():
        raise ValueError("文件解析后为空，可能是扫描件或受损")

    llm = get_llm_client(db)
    if not isinstance(llm, StubLLMClient):
        # 优先 LLM 抽取
        try:
            prompt = INDICATOR_USER_TMPL.format(limit=max_chars, text=text[:max_chars])
            data = llm.extract_json(prompt, system=SYSTEM_PROMPT_INDICATORS, max_tokens=8000)
            if isinstance(data, dict):
                items = data.get("indicators") or []
                if items:
                    return items, f"LLM 抽取（共 {len(items)} 条）"
        except Exception as exc:
            print(f"[extract] LLM 抽取失败，回退正则：{exc}")

    # 兜底
    items = _heuristic_indicators(text)
    return items, f"正则启发式抽取（共 {len(items)} 条，建议配置 LLM API Key 获得更准结果）"


def extract_check_items(db: Session, file_name: str, content: bytes,
                        max_chars: int = 12000) -> tuple[list[dict], str]:
    text = _parse_to_text(file_name, content)
    if not text.strip():
        raise ValueError("文件解析后为空")

    llm = get_llm_client(db)
    if not isinstance(llm, StubLLMClient):
        try:
            prompt = CHECK_ITEMS_USER_TMPL.format(limit=max_chars, text=text[:max_chars])
            data = llm.extract_json(prompt, system=SYSTEM_PROMPT_CHECK_ITEMS, max_tokens=8000)
            if isinstance(data, dict):
                items = data.get("items") or []
                if items:
                    return items, f"LLM 抽取（共 {len(items)} 条）"
        except Exception as exc:
            print(f"[extract] LLM 抽取失败，回退正则：{exc}")

    items = _heuristic_check_items(text)
    return items, f"正则启发式抽取（共 {len(items)} 条）"
