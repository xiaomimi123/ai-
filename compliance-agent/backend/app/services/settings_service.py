"""系统设置服务：管理 LLM API Key 等运行时可改配置。

DB 中的 AppSetting 优先级高于环境变量。
管理员在后台填入 DeepSeek API Key 后立即生效，无需重启。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AppSetting

# 设置 key 命名约定
KEY_LLM_PROVIDER = "llm.provider"
KEY_LLM_MODEL = "llm.model"
KEY_LLM_BASE_URL = "llm.base_url"
KEY_LLM_API_KEY = "llm.api_key"
KEY_LLM_THINKING_MODE = "llm.thinking_mode"


def _get(db: Session, key: str, default: str = "") -> str:
    row = db.get(AppSetting, key)
    return row.value if row else default


def _set(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value


def get_llm_config(db: Session) -> dict:
    """读取当前 LLM 配置：DB 优先，缺省回退到 .env。"""
    provider = _get(db, KEY_LLM_PROVIDER) or settings.llm_provider
    model = _get(db, KEY_LLM_MODEL) or settings.llm_model
    base_url = _get(db, KEY_LLM_BASE_URL) or settings.llm_base_url
    api_key = _get(db, KEY_LLM_API_KEY) or settings.llm_api_key
    if not api_key and provider == "claude":
        api_key = settings.anthropic_api_key
    thinking = _get(db, KEY_LLM_THINKING_MODE) or settings.llm_thinking_mode
    return {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
        "thinking_mode": thinking,
    }


def update_llm_config(
    db: Session,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    thinking_mode: Optional[str] = None,
) -> dict:
    if provider is not None:
        _set(db, KEY_LLM_PROVIDER, provider.strip())
    if model is not None:
        _set(db, KEY_LLM_MODEL, model.strip())
    if base_url is not None:
        _set(db, KEY_LLM_BASE_URL, base_url.strip())
    if api_key is not None:
        # api_key="" 表示清空
        _set(db, KEY_LLM_API_KEY, api_key.strip())
    if thinking_mode is not None:
        _set(db, KEY_LLM_THINKING_MODE, thinking_mode.strip())
    db.commit()
    return get_llm_config(db)
