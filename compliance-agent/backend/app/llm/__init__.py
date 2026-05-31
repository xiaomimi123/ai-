"""LLM 适配层（§1）：封装便于切换 Claude / 国产模型 / 离线 stub。"""
from app.llm.base import LLMClient
from app.llm.factory import get_llm_client

__all__ = ["LLMClient", "get_llm_client"]
