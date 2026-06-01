"""数据库引擎与会话。SQLite（本地）/ PostgreSQL（生产）通过 DATABASE_URL 切换。"""
from __future__ import annotations

from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """建表（首次初始化）+ 种子管理员账号。"""
    import app.models.entities  # noqa: F401  确保模型注册

    Base.metadata.create_all(bind=engine)
    _seed_admin()


def _seed_admin() -> None:
    """首次运行时创建默认管理员账号（admin / admin123）。

    生产部署后应立即在前端修改密码（Phase 4 余下功能）。
    """
    from app.core.security import hash_password
    from app.models.entities import User

    db = SessionLocal()
    try:
        if db.query(User).first() is not None:
            return
        db.add(User(
            username="admin",
            password_hash=hash_password("admin123"),
            role="super_admin",
            full_name="系统管理员",
            is_active=True,
        ))
        db.commit()
    finally:
        db.close()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
