"""认证、权限、审计日志测试（v3 §3.7）。"""
import pytest


@pytest.fixture(scope="module")
def anon_client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models import init_db
    init_db()
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def admin_client(auth_headers):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, headers=auth_headers) as c:
        yield c


# ---------- 公开接口 ----------
def test_health_public(anon_client):
    r = anon_client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["app"] == "内控评价智能审核系统"


# ---------- 401：未登录访问受保护接口 ----------
def test_anon_cannot_list_users(anon_client):
    assert anon_client.get("/api/users").status_code == 401


def test_anon_cannot_read_audit_log(anon_client):
    assert anon_client.get("/api/audit-logs").status_code == 401


# ---------- 登录 ----------
def test_login_success(anon_client):
    r = anon_client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    body = r.json()
    assert body["token"]
    assert body["user"]["role"] == "super_admin"
    assert body["role_label"] == "超级管理员"


def test_login_wrong_password(anon_client):
    r = anon_client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_login_unknown_user(anon_client):
    r = anon_client.post("/api/auth/login", json={"username": "ghost", "password": "x"})
    assert r.status_code == 401


def test_me_returns_admin(admin_client):
    r = admin_client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["user"]["username"] == "admin"


# ---------- 用户管理 ----------
def test_admin_can_create_auditor(admin_client):
    r = admin_client.post("/api/users", json={
        "username": "auditor1",
        "password": "audit12345",
        "role": "auditor",
        "full_name": "审查员小张",
    })
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "auditor"


def test_admin_can_create_unit_user(admin_client):
    r = admin_client.post("/api/users", json={
        "username": "unit1", "password": "unit12345", "role": "unit",
    })
    assert r.status_code == 200, r.text


def test_create_user_with_invalid_role_rejected(admin_client):
    r = admin_client.post("/api/users", json={
        "username": "bogus", "password": "x", "role": "ceo",
    })
    assert r.status_code == 400


def test_duplicate_username_rejected(admin_client):
    r = admin_client.post("/api/users", json={
        "username": "admin", "password": "x", "role": "auditor",
    })
    assert r.status_code == 400


def test_admin_can_list_users(admin_client):
    r = admin_client.get("/api/users")
    assert r.status_code == 200
    names = {u["username"] for u in r.json()}
    assert "admin" in names
    assert "auditor1" in names


# ---------- 权限：非管理员不能管理用户/读审计日志 ----------
def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_non_admin_cannot_create_user(anon_client):
    h = _login(anon_client, "auditor1", "audit12345")
    r = anon_client.post("/api/users", headers=h,
                         json={"username": "x", "password": "x", "role": "auditor"})
    assert r.status_code == 403


def test_non_admin_cannot_read_audit(anon_client):
    h = _login(anon_client, "auditor1", "audit12345")
    r = anon_client.get("/api/audit-logs", headers=h)
    assert r.status_code == 403


# ---------- 审计日志 ----------
def test_audit_log_records_login_and_user_create(admin_client):
    r = admin_client.get("/api/audit-logs")
    assert r.status_code == 200
    actions = {l["action"] for l in r.json()}
    assert "auth.login" in actions
    assert "user.create" in actions


# ---------- 注销 ----------
def test_logout_invalidates_token(anon_client):
    r = anon_client.post("/api/auth/login",
                         json={"username": "auditor1", "password": "audit12345"})
    token = r.json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    assert anon_client.get("/api/auth/me", headers=h).status_code == 200
    assert anon_client.post("/api/auth/logout", headers=h).status_code == 200
    assert anon_client.get("/api/auth/me", headers=h).status_code == 401
