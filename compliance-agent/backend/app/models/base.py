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
    """建表（首次初始化）+ 老库自动补列 + 种子管理员账号。"""
    import app.models.entities  # noqa: F401  确保模型注册

    Base.metadata.create_all(bind=engine)
    _ensure_columns()
    _seed_admin()


# 历次新增的列（旧库自动补全）
_EXTRA_COLUMNS: list[tuple[str, str, str]] = [
    # (table, column, ddl)
    ("indicators", "audit_points", "TEXT NOT NULL DEFAULT ''"),
    ("materials", "content_hash", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("materials", "content_fingerprint", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("audit_tasks", "progress_current", "INTEGER NOT NULL DEFAULT 0"),
    ("audit_tasks", "progress_total", "INTEGER NOT NULL DEFAULT 0"),
    ("audit_tasks", "progress_text", "VARCHAR(256) NOT NULL DEFAULT ''"),
    ("audit_tasks", "fast_mode", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("worksheet_rows", "adjustment_note", "TEXT NOT NULL DEFAULT ''"),
]


def _ensure_columns() -> None:
    """对存量库幂等地 ALTER TABLE ADD COLUMN（SQLite/PG 兼容子集）。"""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    for table, col, ddl in _EXTRA_COLUMNS:
        if table not in existing_tables:
            continue
        cols = {c["name"] for c in insp.get_columns(table)}
        if col in cols:
            continue
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))


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
