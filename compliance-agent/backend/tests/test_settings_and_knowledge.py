"""LLM 设置 + 知识库（指标/问题清单）测试。"""
import io
import json

import pytest


@pytest.fixture(scope="module")
def admin_client(auth_headers):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models import init_db
    init_db()
    with TestClient(app, headers=auth_headers) as c:
        yield c


# ============================================================
# 系统设置 - LLM
# ============================================================
def test_get_llm_settings_default(admin_client):
    r = admin_client.get("/api/settings/llm")
    assert r.status_code == 200
    data = r.json()
    # 默认无 API Key
    assert data["has_api_key"] is False
    # provider 默认为环境变量值（deepseek 或 stub）
    assert data["provider"] in ("deepseek", "stub", "claude")


def test_update_llm_api_key(admin_client):
    r = admin_client.put("/api/settings/llm", json={
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "sk-test-dummy-key-not-real",
        "thinking_mode": "non_think",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["provider"] == "deepseek"
    assert data["has_api_key"] is True
    # 切勿在响应中泄露 api_key 明文
    assert "sk-test-dummy" not in json.dumps(data)


def test_clear_llm_api_key(admin_client):
    r = admin_client.put("/api/settings/llm", json={"api_key": ""})
    assert r.status_code == 200
    assert r.json()["has_api_key"] is False


def test_non_admin_cannot_access_settings():
    """非管理员访问 /api/settings/* 应被拒。"""
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        # 用 anon
        assert c.get("/api/settings/llm").status_code == 401
        # 创建普通审查员后用它访问
        admin = c.post("/api/auth/login",
                       json={"username": "admin", "password": "admin123"}).json()
        h = {"Authorization": f"Bearer {admin['token']}"}
        c.post("/api/users", headers=h,
               json={"username": "audit2", "password": "audit2pass",
                     "role": "auditor"})
        au = c.post("/api/auth/login",
                    json={"username": "audit2", "password": "audit2pass"}).json()
        ah = {"Authorization": f"Bearer {au['token']}"}
        assert c.get("/api/settings/llm", headers=ah).status_code == 403


# ============================================================
# 评价指标库
# ============================================================
def test_create_and_list_indicator(admin_client):
    r = admin_client.post("/api/indicators", json={
        "indicator_code": "TEST-1-1-1",
        "level": "单位",
        "category": "组织层面",
        "name": "测试三重一大",
        "max_score": 4,
        "deduct_rules": "无制度扣4分",
        "common_deductions": "缺少制度文件",
        "required_materials": ["制度文件", "会议纪要"],
    })
    assert r.status_code == 200, r.text
    ind = r.json()
    assert ind["indicator_code"] == "TEST-1-1-1"
    assert "制度文件" in ind["required_materials"]

    r2 = admin_client.get("/api/indicators")
    assert r2.status_code == 200
    codes = {i["indicator_code"] for i in r2.json()}
    assert "TEST-1-1-1" in codes


def test_duplicate_indicator_rejected(admin_client):
    r = admin_client.post("/api/indicators", json={
        "indicator_code": "TEST-1-1-1", "name": "重复"
    })
    assert r.status_code == 400


def test_import_indicators_json(admin_client):
    payload = json.dumps([
        {"indicator_code": "IMP-1", "name": "导入1", "max_score": 3,
         "category": "预算业务", "required_materials": ["预算文件"]},
        {"indicator_code": "IMP-2", "name": "导入2", "max_score": 5,
         "category": "收支业务"},
    ]).encode("utf-8")
    r = admin_client.post(
        "/api/indicators/import",
        files={"file": ("indicators.json", io.BytesIO(payload), "application/json")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 2


# ============================================================
# 问题清单库
# ============================================================
def test_create_check_item(admin_client):
    r = admin_client.post("/api/check-items", json={
        "item_code": "TEST-TZ-001",
        "dimension": "总体合规性",
        "subcategory": "真实性",
        "description": "测试 - 公章检测",
        "applicable_indicators": [],
        "risk_level": "高",
        "check_method": "rule",
        "keywords": ["盖章", "公章"],
    })
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["item_code"] == "TEST-TZ-001"
    assert item["check_method"] == "rule"


def test_list_check_items_filtered(admin_client):
    admin_client.post("/api/check-items", json={
        "item_code": "TEST-XG-001", "dimension": "相关性核查",
        "description": "LLM 测试", "check_method": "llm",
    })
    r = admin_client.get("/api/check-items?dimension=相关性核查")
    assert r.status_code == 200
    items = r.json()
    assert all(i["dimension"] == "相关性核查" for i in items)
    assert any(i["item_code"] == "TEST-XG-001" for i in items)


def test_import_check_items(admin_client):
    payload = json.dumps([
        {"item_code": "IMP-TZ-001", "dimension": "总体合规性",
         "description": "导入测试 1", "check_method": "rule"},
        {"item_code": "IMP-TZ-002", "dimension": "评分合规性",
         "description": "导入测试 2"},
    ]).encode("utf-8")
    r = admin_client.post(
        "/api/check-items/import",
        files={"file": ("items.json", io.BytesIO(payload), "application/json")},
    )
    assert r.status_code == 200
    assert r.json()["created"] == 2


def test_unauth_cannot_create_indicator():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        r = c.post("/api/indicators", json={"indicator_code": "X", "name": "x"})
        assert r.status_code == 401


def test_get_vision_default_empty(auth_headers):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        r = c.get("/api/settings/vision", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["enabled"] is False
        assert "api_key" in body  # 默认空串
        assert body["model"] == "qwen-vl-plus"


def test_save_vision_roundtrip(auth_headers):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        r = c.post("/api/settings/vision", headers=auth_headers, json={
            "enabled": True, "api_key": "sk-vision-test",
            "model": "qwen-vl-max-latest",
        })
        assert r.status_code == 200, r.text
        # 再 GET 一次验证
        r2 = c.get("/api/settings/vision", headers=auth_headers)
        body = r2.json()
        assert body["enabled"] is True
        assert body["api_key"] == "sk-vision-test"
        assert body["model"] == "qwen-vl-max-latest"
