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


# ============================================================
# v1.3 视觉模型（Qwen-VL）配置：用于扫描件 PDF OCR
# ============================================================
def get_vision_config(db: Session) -> dict:
    """读 Qwen-VL OCR 配置。未保存过 → 默认 disabled + 空 key + qwen-vl-plus。"""
    keys = ["vision_enabled", "vision_api_key", "vision_model"]
    rows = db.query(AppSetting).filter(AppSetting.key.in_(keys)).all()
    cfg = {r.key: r.value for r in rows}
    return {
        "enabled": (cfg.get("vision_enabled") or "false").lower() == "true",
        "api_key": cfg.get("vision_api_key", ""),
        "model": cfg.get("vision_model", "qwen-vl-plus"),
    }


def save_vision_config(db: Session, enabled: bool,
                       api_key: str, model: str) -> None:
    """upsert 3 个 key 到 AppSetting。"""
    pairs = [
        ("vision_enabled", "true" if enabled else "false"),
        ("vision_api_key", api_key),
        ("vision_model", model or "qwen-vl-plus"),
    ]
    for key, val in pairs:
        row = db.query(AppSetting).filter_by(key=key).first()
        if row:
            row.value = val
        else:
            db.add(AppSetting(key=key, value=val))
    db.commit()


# ============================================================
# v1.5 上传后自动形式审查开关
# ============================================================
def get_auto_form_review_enabled(db: Session) -> bool:
    row = db.query(AppSetting).filter_by(key="auto_form_review_enabled").first()
    if not row:
        return True  # 默认开启
    return (row.value or "true").lower() == "true"


def set_auto_form_review_enabled(db: Session, enabled: bool) -> None:
    row = db.query(AppSetting).filter_by(key="auto_form_review_enabled").first()
    val = "true" if enabled else "false"
    if row:
        row.value = val
    else:
        db.add(AppSetting(key="auto_form_review_enabled", value=val))
    db.commit()
