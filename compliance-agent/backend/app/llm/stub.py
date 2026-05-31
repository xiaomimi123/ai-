"""离线 Stub LLM：不联网，返回结构稳定的占位结果，用于跑通/测试管线。

设计原则：对「合规疑点抽取」类 prompt 返回空疑点列表（保守，不编造），
这样离线运行时柔性规则不会产生假问题，刚性规则结果不受影响。
"""
from __future__ import annotations

import json

from app.llm.base import LLMClient


class StubLLMClient(LLMClient):
    def complete(self, prompt: str, system: str = "", max_tokens: int = 2048) -> str:
        # 若要求 JSON 疑点列表，返回空列表（保守）。
        if "JSON" in prompt or "json" in prompt or "疑点" in prompt:
            return json.dumps({"issues": []}, ensure_ascii=False)
        return "[离线 stub LLM] 未配置真实模型，已跳过柔性分析。"
