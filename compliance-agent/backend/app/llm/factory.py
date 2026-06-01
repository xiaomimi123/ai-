"""LLM 客户端工厂：根据当前配置（DB 优先，.env 兜底）构造客户端。

不缓存：管理员在后台改了 API Key 后立即生效。
若 provider=deepseek 但缺 API Key 或 openai SDK 未装，自动降级到 stub。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.llm.base import LLMClient
from app.llm.stub import StubLLMClient


def get_llm_client(db: Optional[Session] = None) -> LLMClient:
    """根据 DB 中的 AppSetting 或 .env 构造 LLM 客户端。

    db=None 时直接走 .env（用于无 DB 上下文的场景，如启动时探测）。
    """
    if db is not None:
        from app.services.settings_service import get_llm_config
        cfg = get_llm_config(db)
    else:
        from app.core.config import settings
        cfg = {
            "provider": settings.llm_provider,
            "model": settings.llm_model,
            "base_url": settings.llm_base_url,
            "api_key": settings.llm_api_key or settings.anthropic_api_key,
            "thinking_mode": settings.llm_thinking_mode,
        }

    provider = (cfg.get("provider") or "stub").lower()

    if provider == "deepseek" and cfg.get("api_key"):
        try:
            from app.llm.deepseek import DeepSeekClient
            return DeepSeekClient(
                api_key=cfg["api_key"],
                model=cfg.get("model") or "deepseek-v4-pro",
                base_url=cfg.get("base_url") or "https://api.deepseek.com/v1",
                thinking_mode=cfg.get("thinking_mode") or "non_think",
            )
        except Exception:
            pass  # openai SDK 未装或初始化失败 → 降级 stub

    if provider == "claude" and cfg.get("api_key"):
        try:
            from app.llm.claude import ClaudeLLMClient
            return ClaudeLLMClient(cfg["api_key"], cfg.get("model") or "claude-opus-4-8")
        except Exception:
            pass

    return StubLLMClient()
