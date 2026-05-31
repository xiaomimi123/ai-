"""根据配置返回 LLM 客户端，离线默认 stub。"""
from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.llm.base import LLMClient


@lru_cache
def get_llm_client() -> LLMClient:
    if settings.use_real_llm:
        try:
            from app.llm.claude import ClaudeLLMClient

            return ClaudeLLMClient(settings.anthropic_api_key, settings.llm_model)
        except Exception:
            pass  # SDK 缺失或初始化失败 -> 降级 stub
    from app.llm.stub import StubLLMClient

    return StubLLMClient()
