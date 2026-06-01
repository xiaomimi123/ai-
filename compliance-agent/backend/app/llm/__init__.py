"""LLM 适配层（v3 §附录）：DeepSeek V4 Pro 主用 / Claude 备选 / stub 兜底。"""
from app.llm.base import LLMClient
from app.llm.factory import get_llm_client

__all__ = ["LLMClient", "get_llm_client"]
