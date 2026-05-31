"""柔性规则运行上下文：注入 RAG 检索 + LLM 调用能力。"""
from __future__ import annotations

from typing import List, Optional

from app.llm import get_llm_client
from app.rag import get_retriever

SYSTEM_PROMPT = (
    "你是行政事业单位文档合规审计助手。严格遵守："
    "1) 只能依据提供的『检索到的法规条款』判断，不得编造法规或条款号；"
    "2) 没有把握时不要报告疑点；"
    "3) 仅输出 JSON，格式为 {\"issues\":[{\"description\":..,\"legal_basis\":..,"
    "\"risk_level\":\"高/中/低\",\"suggestion\":..}]}。"
)


class LLMRagContext:
    def __init__(self):
        self._llm = get_llm_client()
        self._retriever = get_retriever()

    def retrieve(self, query: str, category: Optional[str], top_k: int) -> list:
        return self._retriever.retrieve(query, category=category, top_k=top_k)

    def llm_extract_issues(self, prompt: str) -> list:
        data = self._llm.extract_json(prompt, system=SYSTEM_PROMPT)
        if isinstance(data, dict):
            return data.get("issues", []) or []
        if isinstance(data, list):
            return data
        return []
