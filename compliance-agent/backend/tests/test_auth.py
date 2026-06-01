"""认证、权限、审计日志测试（§3.7）。"""
import io

import pytest


@pytest.fixture(scope="module")
def anon_client():
    """不带认证头的 TestClient，用于验证 401。"""
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
    assert anon_client.get("/api/health").status_code == 200


def test_templates_public(anon_client):
    assert anon_client.get("/api/templates").status_code == 200


# ---------- 401：未登录访问受保护接口 ----------
def test_anon_cannot_upload(anon_client):
    files = {"file": ("x.txt", io.BytesIO(b"x"), "text/plain")}
    r = anon_client.post("/api/documents", files=files, data={"category": "合同"})
    assert r.status_code == 401


def test_anon_cannot_list_documents(anon_client):
    assert anon_client.get("/api/documents").status_code == 401


def test_anon_cannot_create_check(anon_client):
    r = anon_client.post("/api/checks", json={"document_id": 1, "template_key": "contract"})
    assert r.status_code == 401


# ---------- 登录 ----------
def test_login_success(anon_client):
    r = anon_client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    body = r.json()
    assert body["token"]
    assert body["user"]["role"] == "admin"
    assert body["role_label"] == "管理员"
    assert "合同" in body["allowed_categories"]


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


# ---------- 用户管理（仅管理员）----------
def test_admin_can_create_finance_user(admin_client):
    r = admin_client.post("/api/users", json={
        "username": "finance1",
        "password": "fin12345",
        "role": "finance",
        "full_name": "财务张三",
    })
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "finance"


def test_admin_can_create_procurement_user(admin_client):
    r = admin_client.post("/api/users", json={
        "username": "proc1", "password": "proc12345", "role": "procurement"
    })
    assert r.status_code == 200, r.text


def test_create_user_with_invalid_role_rejected(admin_client):
    r = admin_client.post("/api/users", json={
        "username": "bogus", "password": "x", "role": "ceo"
    })
    assert r.status_code == 400


def test_duplicate_username_rejected(admin_client):
    r = admin_client.post("/api/users", json={
        "username": "admin", "password": "x", "role": "admin"
    })
    assert r.status_code == 400


def test_admin_can_list_users(admin_client):
    r = admin_client.get("/api/users")
    assert r.status_code == 200
    usernames = {u["username"] for u in r.json()}
    assert "admin" in usernames
    assert "finance1" in usernames


# ---------- 权限分类隔离 ----------
def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_finance_user_cannot_upload_procurement_doc(anon_client, admin_client):
    """财务专员不应能上传「采购招标」分类的文档。"""
    headers = _login(anon_client, "finance1", "fin12345")
    files = {"file": ("p.txt", io.BytesIO("招标".encode("utf-8")), "text/plain")}
    r = anon_client.post("/api/documents", headers=headers, files=files,
                         data={"category": "采购招标"})
    assert r.status_code == 403


def test_finance_user_can_upload_finance_doc(anon_client):
    headers = _login(anon_client, "finance1", "fin12345")
    files = {"file": ("f.txt", io.BytesIO("财务报告内容".encode("utf-8")), "text/plain")}
    r = anon_client.post("/api/documents", headers=headers, files=files,
                         data={"category": "财务报告"})
    assert r.status_code == 200, r.text


def test_procurement_user_cannot_access_finance_doc(anon_client, admin_client):
    """招采专员上传的合同 OK，但不应能访问到财务专员上传的财务报告。"""
    # 财务专员上传一份财务报告
    fin_headers = _login(anon_client, "finance1", "fin12345")
    files = {"file": ("rep.txt", io.BytesIO("财务".encode("utf-8")), "text/plain")}
    up = anon_client.post("/api/documents", headers=fin_headers, files=files,
                          data={"category": "财务报告"})
    assert up.status_code == 200
    doc_id = up.json()["id"]

    # 招采专员尝试用它跑检查 → 403
    proc_headers = _login(anon_client, "proc1", "proc12345")
    r = anon_client.post("/api/checks", headers=proc_headers,
                         json={"document_id": doc_id, "template_key": "finance_final"})
    assert r.status_code == 403


def test_list_documents_filtered_by_role(anon_client, admin_client):
    """招采专员的文档列表不应包含财务专员上传的财务文档。"""
    proc_headers = _login(anon_client, "proc1", "proc12345")
    r = anon_client.get("/api/documents", headers=proc_headers)
    assert r.status_code == 200
    cats = {d["category"] for d in r.json()}
    # 招采专员可见分类：合同/采购招标/其他佐证资料 + 空
    assert "财务报告" not in cats
    assert "国有资产报告" not in cats


# ---------- 非管理员不能创建用户 ----------
def test_non_admin_cannot_create_user(anon_client):
    headers = _login(anon_client, "finance1", "fin12345")
    r = anon_client.post("/api/users", headers=headers,
                         json={"username": "x", "password": "x", "role": "finance"})
    assert r.status_code == 403


def test_non_admin_cannot_read_audit_log(anon_client):
    headers = _login(anon_client, "finance1", "fin12345")
    r = anon_client.get("/api/audit-logs", headers=headers)
    assert r.status_code == 403


# ---------- 审计日志 ----------
def test_audit_log_records_operations(admin_client):
    r = admin_client.get("/api/audit-logs")
    assert r.status_code == 200
    logs = r.json()
    # 应记录前面测试中触发的多类操作
    actions = {l["action"] for l in logs}
    assert "auth.login" in actions
    assert "user.create" in actions
    assert "document.upload" in actions
    # admin 自身操作应出现
    assert any(l["username"] == "admin" for l in logs)


# ---------- 注销 ----------
def test_logout_invalidates_token(anon_client):
    # 单独登录一个新会话，避免影响 admin_client
    r = anon_client.post("/api/auth/login", json={"username": "finance1", "password": "fin12345"})
    token = r.json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    assert anon_client.get("/api/auth/me", headers=h).status_code == 200
    assert anon_client.post("/api/auth/logout", headers=h).status_code == 200
    # 注销后 token 不再可用
    assert anon_client.get("/api/auth/me", headers=h).status_code == 401
