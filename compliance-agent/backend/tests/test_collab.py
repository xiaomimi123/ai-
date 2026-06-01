"""协同复核 + 在线批注测试（§3.7）。"""
import io

import pytest

from tests.samples import BAD_CONTRACT


@pytest.fixture(scope="module")
def setup_users_and_issue(auth_headers):
    """登录 admin → 创建 procurement 用户 → 上传问题合同 → 跑检查 → 返回第一条问题 id。"""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models import init_db

    init_db()
    with TestClient(app, headers=auth_headers) as c:
        # 创建一个 procurement 用户作为被指派人
        r = c.post("/api/users", json={
            "username": "proc_collab", "password": "pwd12345",
            "role": "procurement", "full_name": "招采李四",
        })
        assert r.status_code == 200, r.text
        proc_user_id = r.json()["id"]

        # 上传问题合同 + 跑检查
        files = {"file": ("bad.txt", io.BytesIO(BAD_CONTRACT.encode("utf-8")), "text/plain")}
        up = c.post("/api/documents", files=files, data={"category": "合同"})
        doc_id = up.json()["id"]
        chk = c.post("/api/checks",
                     json={"document_id": doc_id, "template_key": "contract"})
        task = chk.json()
        issue_id = task["issues"][0]["id"]

    # 单独登录 proc 用户拿 token
    with TestClient(app) as c2:
        r = c2.post("/api/auth/login", json={"username": "proc_collab", "password": "pwd12345"})
        proc_token = r.json()["token"]

    return {"proc_user_id": proc_user_id, "proc_token": proc_token, "issue_id": issue_id}


@pytest.fixture(scope="module")
def admin_test_client(auth_headers):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, headers=auth_headers) as c:
        yield c


@pytest.fixture(scope="module")
def proc_test_client(setup_users_and_issue):
    from fastapi.testclient import TestClient
    from app.main import app
    h = {"Authorization": f"Bearer {setup_users_and_issue['proc_token']}"}
    with TestClient(app, headers=h) as c:
        yield c


# ─── 状态机：完整正向流程 ────────────────────────────
def test_full_workflow_assign_to_resolved(admin_test_client, proc_test_client,
                                          setup_users_and_issue):
    iid = setup_users_and_issue["issue_id"]
    pid = setup_users_and_issue["proc_user_id"]

    # 1. 管理员指派 → assigned
    r = admin_test_client.post(f"/api/issues/{iid}/assign",
                               json={"assignee_id": pid})
    assert r.status_code == 200, r.text
    assert r.json()["handle_status"] == "assigned"
    assert r.json()["assignee_id"] == pid

    # 2. 被指派人开始整改 → fixing
    r = proc_test_client.post(f"/api/issues/{iid}/start")
    assert r.status_code == 200, r.text
    assert r.json()["handle_status"] == "fixing"

    # 3. 被指派人提交整改 → reviewing
    r = proc_test_client.post(f"/api/issues/{iid}/submit",
                              json={"fix_note": "已补充合同编号 HT-2026-XX"})
    assert r.status_code == 200, r.text
    assert r.json()["handle_status"] == "reviewing"
    assert "合同编号" in r.json()["fix_note"]

    # 4. 管理员销号 → resolved
    r = admin_test_client.post(f"/api/issues/{iid}/approve",
                               json={"review_note": "已核实"})
    assert r.status_code == 200, r.text
    assert r.json()["handle_status"] == "resolved"
    assert r.json()["review_note"] == "已核实"


# ─── 打回 + 重新打开循环 ──────────────────────────────
def test_reject_then_reopen_cycle(admin_test_client, proc_test_client,
                                  auth_headers, setup_users_and_issue):
    """单独跑一遍：提交后被打回 → 重新打开 → 重新提交 → 销号。"""
    from fastapi.testclient import TestClient
    from app.main import app
    import io as _io
    from tests.samples import BAD_CONTRACT as _BAD

    with TestClient(app, headers=auth_headers) as c:
        files = {"file": ("r.txt", _io.BytesIO(_BAD.encode("utf-8")), "text/plain")}
        doc_id = c.post("/api/documents", files=files,
                        data={"category": "合同"}).json()["id"]
        task = c.post("/api/checks",
                      json={"document_id": doc_id, "template_key": "contract"}).json()
        iid = task["issues"][0]["id"]
        # 指派给 proc_test_client 登录的那个用户
        pid = setup_users_and_issue["proc_user_id"]

    admin_test_client.post(f"/api/issues/{iid}/assign", json={"assignee_id": pid})
    proc_test_client.post(f"/api/issues/{iid}/start")
    proc_test_client.post(f"/api/issues/{iid}/submit",
                          json={"fix_note": "初步整改"})

    # 管理员打回 → rejected
    r = admin_test_client.post(f"/api/issues/{iid}/reject",
                               json={"review_note": "证据不足，请补充"})
    assert r.status_code == 200
    assert r.json()["handle_status"] == "rejected"

    # 被指派人重新打开 → fixing
    r = proc_test_client.post(f"/api/issues/{iid}/reopen")
    assert r.status_code == 200
    assert r.json()["handle_status"] == "fixing"

    # 重新提交 + 销号
    proc_test_client.post(f"/api/issues/{iid}/submit",
                          json={"fix_note": "已补充证据"})
    r = admin_test_client.post(f"/api/issues/{iid}/approve", json={"review_note": ""})
    assert r.json()["handle_status"] == "resolved"


# ─── 状态机非法转移 ───────────────────────────────────
def test_cannot_submit_before_assign(admin_test_client, auth_headers):
    """open 状态直接 submit 应被拒。"""
    from fastapi.testclient import TestClient
    from app.main import app
    import io as _io
    from tests.samples import BAD_CONTRACT as _BAD

    with TestClient(app, headers=auth_headers) as c:
        files = {"file": ("x.txt", _io.BytesIO(_BAD.encode("utf-8")), "text/plain")}
        doc_id = c.post("/api/documents", files=files,
                        data={"category": "合同"}).json()["id"]
        task = c.post("/api/checks",
                      json={"document_id": doc_id, "template_key": "contract"}).json()
        iid = task["issues"][0]["id"]

    r = admin_test_client.post(f"/api/issues/{iid}/submit", json={"fix_note": "x"})
    assert r.status_code == 400
    assert "不允许" in r.json()["detail"]


def test_cannot_approve_when_not_reviewing(admin_test_client, auth_headers):
    """open 状态直接 approve 应被拒。"""
    from fastapi.testclient import TestClient
    from app.main import app
    import io as _io
    from tests.samples import BAD_CONTRACT as _BAD

    with TestClient(app, headers=auth_headers) as c:
        files = {"file": ("y.txt", _io.BytesIO(_BAD.encode("utf-8")), "text/plain")}
        doc_id = c.post("/api/documents", files=files,
                        data={"category": "合同"}).json()["id"]
        task = c.post("/api/checks",
                      json={"document_id": doc_id, "template_key": "contract"}).json()
        iid = task["issues"][0]["id"]

    r = admin_test_client.post(f"/api/issues/{iid}/approve", json={"review_note": ""})
    assert r.status_code == 400


# ─── 权限规则 ─────────────────────────────────────────
def test_non_admin_cannot_assign(proc_test_client, setup_users_and_issue):
    iid = setup_users_and_issue["issue_id"]
    r = proc_test_client.post(f"/api/issues/{iid}/assign",
                              json={"assignee_id": setup_users_and_issue["proc_user_id"]})
    assert r.status_code == 403


def test_non_admin_cannot_approve(proc_test_client, setup_users_and_issue):
    iid = setup_users_and_issue["issue_id"]
    r = proc_test_client.post(f"/api/issues/{iid}/approve", json={"review_note": ""})
    # 即使状态不对，权限校验也应优先（实际上权限先抛 403）
    assert r.status_code in (400, 403)


def test_reject_requires_review_note(admin_test_client, auth_headers,
                                     setup_users_and_issue):
    """打回必须填写复核意见。"""
    from fastapi.testclient import TestClient
    from app.main import app
    import io as _io
    from tests.samples import BAD_CONTRACT as _BAD

    with TestClient(app, headers=auth_headers) as c:
        files = {"file": ("rn.txt", _io.BytesIO(_BAD.encode("utf-8")), "text/plain")}
        doc_id = c.post("/api/documents", files=files,
                        data={"category": "合同"}).json()["id"]
        task = c.post("/api/checks",
                      json={"document_id": doc_id, "template_key": "contract"}).json()
        iid = task["issues"][0]["id"]

    # 推进到 reviewing 状态（admin 操作贯穿，无关被指派人具体是谁）
    pid = setup_users_and_issue["proc_user_id"]
    admin_test_client.post(f"/api/issues/{iid}/assign", json={"assignee_id": pid})
    # 用 admin 客户端推进流程也成立（管理员可代被指派人操作）
    admin_test_client.post(f"/api/issues/{iid}/start")
    admin_test_client.post(f"/api/issues/{iid}/submit", json={"fix_note": "x"})

    r = admin_test_client.post(f"/api/issues/{iid}/reject", json={"review_note": ""})
    assert r.status_code == 400


# ─── 在线批注 ─────────────────────────────────────────
def test_comment_thread(admin_test_client, proc_test_client, setup_users_and_issue):
    iid = setup_users_and_issue["issue_id"]
    # admin 发评论
    r = admin_test_client.post(f"/api/issues/{iid}/comments",
                               json={"body": "请尽快整改"})
    assert r.status_code == 200, r.text
    assert "请尽快" in r.json()["body"]

    # proc 用户回评
    r = proc_test_client.post(f"/api/issues/{iid}/comments",
                              json={"body": "收到，今天处理"})
    assert r.status_code == 200, r.text

    # 列表按 id 升序
    r = admin_test_client.get(f"/api/issues/{iid}/comments")
    assert r.status_code == 200
    comments = r.json()
    assert len(comments) >= 2
    assert comments[0]["body"] == "请尽快整改"
    assert comments[0]["author_name"] in ("admin", "系统管理员")
    assert any("收到" in c["body"] for c in comments)


def test_empty_comment_rejected(admin_test_client, setup_users_and_issue):
    iid = setup_users_and_issue["issue_id"]
    r = admin_test_client.post(f"/api/issues/{iid}/comments", json={"body": "   "})
    assert r.status_code == 400


# ─── 审计日志记录 ─────────────────────────────────────
def test_workflow_actions_logged(admin_test_client):
    r = admin_test_client.get("/api/audit-logs")
    assert r.status_code == 200
    actions = {l["action"] for l in r.json()}
    expected = {"issue.assign", "issue.start", "issue.submit",
                "issue.approve", "issue.comment"}
    assert expected.issubset(actions), f"missing: {expected - actions}"


# ─── 401 未登录 ───────────────────────────────────────
def test_unauth_cannot_access_issue():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        assert c.get("/api/issues/1").status_code == 401
        assert c.post("/api/issues/1/assign",
                      json={"assignee_id": 1}).status_code == 401
        assert c.post("/api/issues/1/comments",
                      json={"body": "x"}).status_code == 401
