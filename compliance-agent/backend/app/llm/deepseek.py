"""DeepSeek V4 Pro 客户端（v3 §附录）。

兼容 OpenAI 格式（base_url=https://api.deepseek.com/v1）；
支持三种推理模式：non_think / think_high / think_max。
"""
from __future__ import annotations

from app.llm.base import LLMClient


class DeepSeekClient(LLMClient):
    def __init__(self, api_key: str, model: str,
                 base_url: str = "https://api.deepseek.com/v1",
                 thinking_mode: str = "non_think"):
        from openai import OpenAI  # 延迟导入

        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._thinking_mode = thinking_mode

    def _thinking_kwargs(self) -> dict:
        if self._thinking_mode == "think_high":
            return {"extra_body": {"thinking": {"type": "enabled", "budget_tokens": 8000}}}
        if self._thinking_mode == "think_max":
            return {"extra_body": {"thinking": {"type": "enabled", "budget_tokens": 32000}}}
        return {}

    def complete(self, prompt: str, system: str = "", max_tokens: int = 2048) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs = dict(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.1,  # 审查任务要求确定性
        )
        kwargs.update(self._thinking_kwargs())

        resp = self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    def extract_json(self, prompt: str, system: str = "", max_tokens: int = 2048):
        """DeepSeek 支持 response_format={"type":"json_object"} 强制 JSON 输出。"""
        from app.llm.base import _loads_lenient
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs = dict(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        kwargs.update(self._thinking_kwargs())

        resp = self._client.chat.completions.create(**kwargs)
        raw = resp.choices[0].message.content or ""
        return _loads_lenient(raw)
