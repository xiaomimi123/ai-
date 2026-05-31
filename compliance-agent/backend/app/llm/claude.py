"""Claude LLM 客户端（生产）。需要 anthropic SDK 与 ANTHROPIC_API_KEY。"""
from __future__ import annotations

from app.llm.base import LLMClient


class ClaudeLLMClient(LLMClient):
    def __init__(self, api_key: str, model: str):
        from anthropic import Anthropic  # 延迟导入

        self._client = Anthropic(api_key=api_key)
        self._model = model

    def complete(self, prompt: str, system: str = "", max_tokens: int = 2048) -> str:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system or "你是行政事业单位文档合规审计助手。",
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )
