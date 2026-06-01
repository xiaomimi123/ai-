"""测试夹具：用临时目录隔离数据库与对象存储，全部走离线实现。"""
import os
import tempfile

import pytest

# 必须在导入 app 之前设置环境变量
_TMP = tempfile.mkdtemp(prefix="compliance_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["STORAGE_DIR"] = f"{_TMP}/storage"
os.environ["LLM_PROVIDER"] = "stub"
os.environ["EMBEDDER"] = "stub"
os.environ["VECTOR_STORE"] = "memory"


@pytest.fixture(scope="module")
def admin_token():
    """登录默认管理员账号并返回 Bearer token，供 e2e 测试使用。"""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.models import init_db

    init_db()  # 触发 admin / admin123 种子
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        assert r.status_code == 200, r.text
        return r.json()["token"]


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}
