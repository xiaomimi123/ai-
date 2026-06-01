"""全局配置。

所有外部依赖（数据库、向量库、LLM、对象存储）通过环境变量切换，
默认走「离线回退实现」，保证零外部依赖即可本地运行与测试。
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根（backend/）目录
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "行政事业单位文档合规检查智能体"
    debug: bool = True

    # 数据库：默认 SQLite 本地文件；生产用 postgresql://...
    database_url: str = f"sqlite:///{BACKEND_DIR / 'compliance.db'}"

    # 对象存储：默认本地目录
    storage_dir: str = str(BACKEND_DIR / "storage")

    # Embedding：bge | stub（离线默认 stub）
    embedder: str = "stub"
    embedding_dim: int = 256
    bge_model_name: str = "BAAI/bge-large-zh-v1.5"

    # 向量库：memory | qdrant（离线默认 memory）
    vector_store: str = "memory"
    qdrant_url: str = "http://localhost:6333"

    # LLM：stub | claude（离线默认 stub）
    llm_provider: str = "stub"
    anthropic_api_key: str = ""
    llm_model: str = "claude-opus-4-8"

    # Celery / Redis
    redis_url: str = "redis://localhost:6379/0"
    # eager 模式：任务在调用线程内同步执行（默认开，离线测试零依赖）
    # 生产部署关闭后由 Celery worker 进程异步消费
    celery_eager: bool = True

    @property
    def use_real_llm(self) -> bool:
        return self.llm_provider == "claude" and bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    Path(s.storage_dir).mkdir(parents=True, exist_ok=True)
    return s


settings = get_settings()
