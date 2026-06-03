"""AI 阅读材料 → 自动分类到评价指标。

批量将未绑定材料发给 LLM，让它根据文件名 + 解析文本内容，决定材料属于
哪个指标。LLM 一次性返回 {material_id: indicator_code} 映射。

设计要点：
- 分批处理（默认 15 份/批），避免单次 prompt 超 32K token
- 每份材料只截取前 800 字（够 LLM 判断主题）
- stub 模式（无真实 LLM）直接返回空，让 fallback 用关键词
- LLM 返回的 indicator_code 不在 55 项内 → 忽略
- 1 份材料最多绑 1 个指标
"""
from __future__ import annotations

import json
from typing import Dict, Iterable, List

from sqlalchemy.orm import Session

from app.llm.base import LLMClient
from app.llm.stub import StubLLMClient
from app.models import AuditTask, Indicator, Material


SYSTEM_PROMPT = (
    "你是内控评价审计的资深辅助员。任务：根据用户提供的材料内容，"
    "把每份材料映射到对应的「评价指标」编号（I-01 ~ I-55）。"
    "判断依据：材料的主题、制度名称、章节、关键词。"
    "严格要求：① 每份材料最多绑 1 个指标 ② 只能用提供的 indicator_code "
    "③ 实在判断不出来就省略该材料 ④ 严禁臆造 indicator_code。"
)


BATCH_SIZE = 15
TEXT_PREVIEW = 800


def _format_indicator_list(indicators: List[Indicator]) -> str:
    lines = []
    for ind in indicators:
        sub = ind.subcategory or ind.category or ""
        lines.append(f"- {ind.indicator_code} [{sub}] {ind.name}")
    return "\n".join(lines)


def _format_materials(batch: List[Material]) -> str:
    chunks = []
    for m in batch:
        text = (m.parsed_text or "").strip().replace("\n", " ")
        if len(text) > TEXT_PREVIEW:
            text = text[:TEXT_PREVIEW] + "…"
        chunks.append(
            f"材料 ID={m.id}\n"
            f"文件名: {m.file_name}\n"
            f"内容预览: {text or '（解析为空）'}\n"
        )
    return "\n".join(chunks)


def _build_prompt(batch: List[Material], indicators: List[Indicator]) -> str:
    return (
        "请阅读以下 N 份内控评价材料，把每份材料分类到对应指标。\n\n"
        "【指标库】（共 55 项，必须使用其中的 indicator_code）\n"
        f"{_format_indicator_list(indicators)}\n\n"
        "【待分类材料】\n"
        f"{_format_materials(batch)}\n\n"
        "请返回严格 JSON：\n"
        '{"mappings": [{"material_id": 数字, "indicator_code": "I-XX", "reason": "≤40字理由"}]}\n'
        "未能判断的材料不要出现在 mappings 里。"
    )


def ai_classify_materials(db: Session, task: AuditTask,
                          llm: LLMClient,
                          materials: List[Material],
                          indicators: List[Indicator]) -> Dict[int, int]:
    """让 LLM 阅读材料决定绑定。返回 {material_id: indicator.id}。"""
    if isinstance(llm, StubLLMClient):
        return {}
    if not materials:
        return {}

    # 让 LLM 用快速模式（这是分类任务，不需要深度思考）
    if hasattr(llm, "thinking_mode"):
        try:
            llm.thinking_mode = "off"
        except Exception:
            pass

    code2id = {ind.indicator_code: ind.id for ind in indicators}

    results: Dict[int, int] = {}
    for i in range(0, len(materials), BATCH_SIZE):
        batch = materials[i:i + BATCH_SIZE]
        prompt = _build_prompt(batch, indicators)
        try:
            data = llm.extract_json(prompt, system=SYSTEM_PROMPT, max_tokens=4096)
        except Exception as exc:
            print(f"[ai_classify] batch {i//BATCH_SIZE + 1} LLM 失败: {exc}")
            continue

        if not isinstance(data, dict):
            continue
        for item in data.get("mappings", []) or []:
            if not isinstance(item, dict):
                continue
            try:
                mid = int(item.get("material_id"))
            except (TypeError, ValueError):
                continue
            code = str(item.get("indicator_code", "")).strip()
            iid = code2id.get(code)
            if iid is None:
                continue
            # 校验 material_id 确实在当前 batch
            if not any(m.id == mid for m in batch):
                continue
            results[mid] = iid

    return results
