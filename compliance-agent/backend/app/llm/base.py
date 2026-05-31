"""LLM 客户端接口。"""
from __future__ import annotations

import abc
import json
from typing import Any, Dict, Optional


class LLMClient(abc.ABC):
    @abc.abstractmethod
    def complete(self, prompt: str, system: str = "", max_tokens: int = 2048) -> str:
        """返回纯文本补全。"""

    def extract_json(self, prompt: str, system: str = "", max_tokens: int = 2048) -> Any:
        """要求模型返回 JSON，解析后返回对象。解析失败返回 None。"""
        raw = self.complete(prompt, system=system, max_tokens=max_tokens)
        return _loads_lenient(raw)


def _loads_lenient(raw: str) -> Optional[Any]:
    raw = (raw or "").strip()
    if not raw:
        return None
    # 去掉 ```json ... ``` 包裹
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lstrip().lower().startswith("json"):
            raw = raw.lstrip()[4:]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 尝试截取首个 { 或 [ 到末尾
        for open_ch, close_ch in (("[", "]"), ("{", "}")):
            start = raw.find(open_ch)
            end = raw.rfind(close_ch)
            if start != -1 and end > start:
                try:
                    return json.loads(raw[start:end + 1])
                except json.JSONDecodeError:
                    continue
    return None
