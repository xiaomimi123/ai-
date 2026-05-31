"""数据库初始化入口：python -m app.init_db（§7.2）。"""
from __future__ import annotations

from app.models import init_db

if __name__ == "__main__":
    init_db()
    print("数据库初始化完成。")
