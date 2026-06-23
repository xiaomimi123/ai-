"""系统设置 API：LLM 配置（含 API Key）。仅超级管理员可访问。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas import LLMSettings, LLMSettingsUpdate
from app.core.auth import get_current_user, log_action, require_admin
from app.llm import get_llm_client
from app.models import User, get_db
from app.services import settings_service

settings_router = APIRouter(prefix="/api/settings", tags=["settings"])


def _to_response(cfg: dict) -> LLMSettings:
    return LLMSettings(
        provider=cfg.get("provider", "stub"),
        model=cfg.get("model", ""),
        base_url=cfg.get("base_url", ""),
        thinking_mode=cfg.get("thinking_mode", "non_think"),
        has_api_key=bool(cfg.get("api_key", "")),
    )


@settings_router.get("/llm", response_model=LLMSettings)
def get_llm(db: Session = Depends(get_db),
            _: User = Depends(require_admin)):
    """获取当前 LLM 配置（不回显 API Key 明文，只回是否已配置）。"""
    return _to_response(settings_service.get_llm_config(db))


@settings_router.put("/llm", response_model=LLMSettings)
def update_llm(req: LLMSettingsUpdate,
               db: Session = Depends(get_db),
               admin: User = Depends(require_admin)):
    """更新 LLM 配置；api_key=None 表示不变，""表示清空。"""
    cfg = settings_service.update_llm_config(
        db,
        provider=req.provider,
        model=req.model,
        base_url=req.base_url,
        api_key=req.api_key,
        thinking_mode=req.thinking_mode,
    )
    log_action(db, admin, "settings.llm_update",
               target_type="settings",
               detail=f"provider={cfg['provider']} model={cfg['model']} "
                      f"has_key={'是' if cfg['api_key'] else '否'}")
    db.commit()
    return _to_response(cfg)


@settings_router.post("/llm/test", response_model=dict)
def test_llm_connection(db: Session = Depends(get_db),
                        admin: User = Depends(require_admin)):
    """测试当前 LLM 配置是否能正常调用（发一个最小提示词验证）。"""
    cfg = settings_service.get_llm_config(db)
    client = get_llm_client(db)
    client_cls = type(client).__name__

    try:
        # 最小测试调用
        result = client.complete('你好，请回复 OK 两个字。', max_tokens=20)
        ok = bool(result)
    except Exception as exc:
        return {
            "success": False,
            "provider": cfg.get("provider"),
            "client": client_cls,
            "error": str(exc),
        }
    return {
        "success": True,
        "provider": cfg.get("provider"),
        "client": client_cls,
        "preview": (result or "")[:200],
    }


# ============================================================
# v1.3 视觉模型（Qwen-VL OCR）配置 GET/POST
# ============================================================
from pydantic import BaseModel as _BaseModel


class VisionConfigIn(_BaseModel):
    enabled: bool
    api_key: str
    model: str = "qwen-vl-plus"


@settings_router.get("/vision", response_model=dict)
def get_vision_settings(db: Session = Depends(get_db),
                        _: User = Depends(require_admin)):
    """读取 Qwen-VL OCR 配置（管理员）。"""
    return settings_service.get_vision_config(db)


@settings_router.post("/vision", response_model=dict)
def save_vision_settings(req: VisionConfigIn,
                         db: Session = Depends(get_db),
                         admin: User = Depends(require_admin)):
    """保存 Qwen-VL OCR 配置（管理员）。"""
    settings_service.save_vision_config(
        db, enabled=req.enabled, api_key=req.api_key, model=req.model,
    )
    return {"ok": True}
