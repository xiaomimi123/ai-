"""DeepSeek V4 Pro 客户端（v3 §附录）。

兼容 OpenAI 格式（base_url=https://api.deepseek.com/v1）；
支持三种推理模式：non_think / think_high / think_max。
"""
from __future__ import annotations

from app.llm.base import LLMClient
import json
import os
from datetime import datetime, timezone


# ============================================================
# v2.12：LLM usage 埋点（供批量脚本读，估算成本）
# ============================================================
# 单价：元 / 1M tokens（DeepSeek 官方 2026-01 价格；缓存未命中价）
_PRICE_PER_M_INPUT = {
    "deepseek-v4-flash":  0.10,
    "deepseek-v4-pro":    0.50,
    "deepseek-chat":      0.10,   # 兼容别名
    "deepseek-reasoner":  0.50,
}
_PRICE_PER_M_OUTPUT = {
    "deepseek-v4-flash":  0.50,
    "deepseek-v4-pro":    2.00,
    "deepseek-chat":      0.50,
    "deepseek-reasoner":  2.00,
}
_USAGE_LOG_PATH = "/app/data/llm_usage.jsonl"


def _log_usage(model: str, usage) -> None:
    """把一次调用的 usage 追加到 jsonl；异常吞掉不影响主流程。"""
    if usage is None:
        return
    try:
        pt = int(getattr(usage, "prompt_tokens", 0) or 0)
        ct = int(getattr(usage, "completion_tokens", 0) or 0)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "prompt_tokens": pt,
            "completion_tokens": ct,
        }
        path = _USAGE_LOG_PATH
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except OSError:
            path = "/tmp/llm_usage.jsonl"
        with open(path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 埋点不能影响主流程


def sum_usage_cost(path: str = _USAGE_LOG_PATH) -> tuple[int, int, float]:
    """扫描 jsonl，返回 (prompt_tokens_total, completion_tokens_total, cost_yuan)。

    未知模型按贵档 (0.5/2.0) 兜底，防止低估。
    """
    if not os.path.exists(path):
        return (0, 0, 0.0)
    tp = tc = 0
    cost = 0.0
    with open(path) as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            model = e.get("model", "")
            pt = int(e.get("prompt_tokens", 0) or 0)
            ct = int(e.get("completion_tokens", 0) or 0)
            in_rate = _PRICE_PER_M_INPUT.get(model, 0.5)
            out_rate = _PRICE_PER_M_OUTPUT.get(model, 2.0)
            tp += pt
            tc += ct
            cost += (pt / 1_000_000 * in_rate) + (ct / 1_000_000 * out_rate)
    return (tp, tc, cost)


class DeepSeekClient(LLMClient):
    def __init__(self, api_key: str, model: str,
                 base_url: str = "https://api.deepseek.com/v1",
                 thinking_mode: str = "non_think"):
        from openai import OpenAI  # 延迟导入

        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._thinking_mode = thinking_mode

    @property
    def thinking_mode(self) -> str:
        return self._thinking_mode

    @thinking_mode.setter
    def thinking_mode(self, value: str) -> None:
        # 兼容快速模式："off" 视为 non_think
        self._thinking_mode = "non_think" if value in ("off", "none", "fast") else value

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
        _log_usage(self._model, resp.usage)  # v2.12: 埋点
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
        _log_usage(self._model, resp.usage)  # v2.12: 埋点
        raw = resp.choices[0].message.content or ""
        return _loads_lenient(raw)
