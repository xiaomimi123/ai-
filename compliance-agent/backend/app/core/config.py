"""全局配置（v3 内控评价智能审核系统）。

所有外部依赖通过环境变量切换；默认走「离线回退实现」，零外部依赖可运行。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "内控评价智能审核系统"
    debug: bool = True

    # 数据库
    database_url: str = f"sqlite:///{BACKEND_DIR / 'audit.db'}"

    # 对象存储
    storage_dir: str = str(BACKEND_DIR / "storage")

    # Embedding：bge | stub
    embedder: str = "stub"
    embedding_dim: int = 256
    bge_model_name: str = "BAAI/bge-large-zh-v1.5"

    # 向量库：memory | qdrant
    vector_store: str = "memory"
    qdrant_url: str = "http://localhost:6333"

    # ===== LLM 配置 =====
    # provider: stub | deepseek | claude
    # 这些值是「默认值」，运行时管理员可通过 /api/settings/llm 在数据库覆盖
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-v4-pro"
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_thinking_mode: str = "non_think"   # non_think | think_high | think_max
    # Claude 兼容
    anthropic_api_key: str = ""

    # Celery / Redis
    redis_url: str = "redis://localhost:6379/0"
    celery_eager: bool = True


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    Path(s.storage_dir).mkdir(parents=True, exist_ok=True)
    return s


settings = get_settings()
