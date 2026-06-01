"""异步任务测试。

eager 模式下 .delay() 同步执行，所以这些测试在测试环境里无需 Redis。
"""
import io

import pytest

from tests.samples import BAD_CONTRACT, CHAIN_BAD_BID, CHAIN_GOOD_TENDER


@pytest.fixture(scope="module")
def client(auth_headers):
    """带管理员 token 的 TestClient（每个测试模块独立）。"""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models import init_db
    init_db()
    with TestClient(app, headers=auth_headers) as c:
        yield c


def _upload(client, text, name, category="合同", subcategory=""):
    files = {"file": (name, io.BytesIO(text.encode("utf-8")), "text/plain")}
    r = client.post("/api/documents", files=files,
                    data={"category": category, "subcategory": subcategory})
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ─── 单文件检查异步 ───────────────────────────────────
def test_check_async_returns_pending_then_done(client):
    """eager 模式下 .delay() 同步执行，提交后任务已直接完成。"""
    doc_id = _upload(client, BAD_CONTRACT, "ba.txt")
    r = client.post("/api/checks/async",
                    json={"document_id": doc_id, "template_key": "contract"})
    assert r.status_code == 200, r.text
    task = r.json()
    # eager 模式下任务已经执行完毕
    assert task["status"] in ("done", "running", "pending")
    # 轮询确认最终状态（eager 模式下应该已经 done）
    final = client.get(f"/api/checks/{task['id']}").json()
    assert final["status"] == "done"
    assert len(final["issues"]) > 0  # bad contract → 至少有疑点


def test_check_async_invalid_template_returns_400(client):
    doc_id = _upload(client, BAD_CONTRACT, "bb.txt")
    r = client.post("/api/checks/async",
                    json={"document_id": doc_id, "template_key": "nope_template"})
    assert r.status_code == 400


def test_check_async_unauth():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        r = c.post("/api/checks/async",
                   json={"document_id": 1, "template_key": "contract"})
        assert r.status_code == 401


# ─── 联动校验异步 ─────────────────────────────────────
def test_procurement_chain_async(client):
    t = _upload(client, CHAIN_GOOD_TENDER, "t.txt", category="采购招标", subcategory="招标")
    b = _upload(client, CHAIN_BAD_BID, "b.txt", category="采购招标", subcategory="投标")
    r = client.post("/api/chain-checks/async", json={
        "tender_doc_id": t, "bid_doc_id": b,
    })
    assert r.status_code == 200, r.text
    task = r.json()
    final = client.get(f"/api/chain-checks/{task['id']}").json()
    assert final["status"] == "done"
    # 投标超预算应被检出
    rule_ids = {i["rule_id"] for i in final["issues"]}
    assert "chain.price_over_budget" in rule_ids


def test_finance_chain_async_empty_input_400(client):
    r = client.post("/api/chain-checks/finance/async", json={})
    assert r.status_code == 400


def test_report_chain_async_empty_input_400(client):
    r = client.post("/api/chain-checks/report/async", json={})
    assert r.status_code == 400


# ─── 审计日志记录入队事件 ────────────────────────────
def test_enqueue_logged_to_audit(client):
    doc_id = _upload(client, BAD_CONTRACT, "audit.txt")
    client.post("/api/checks/async",
                json={"document_id": doc_id, "template_key": "contract"})
    logs = client.get("/api/audit-logs").json()
    actions = {l["action"] for l in logs}
    assert "check.enqueue" in actions


# ─── 直接调用 task 函数（worker 视角）─────────────────
def test_execute_pending_check_directly(client):
    """模拟 worker 进程：service 层 + task 函数直调，绕过 HTTP。"""
    from app.models import SessionLocal, Document, CheckTask
    from app.services.check_service import create_pending_check, execute_pending_check
    from app.tasks.jobs import run_check_task

    # 用 API 上传一份文档，然后用 service 创建 pending
    doc_id = _upload(client, BAD_CONTRACT, "worker.txt")
    db = SessionLocal()
    try:
        doc = db.get(Document, doc_id)
        task = create_pending_check(db, doc, "contract")
        assert task.status == "pending"
        task_id = task.id
    finally:
        db.close()

    # 直接调用 task 函数（生产中由 worker 进程发起）
    run_check_task(task_id)

    db = SessionLocal()
    try:
        task = db.get(CheckTask, task_id)
        assert task.status == "done"
        assert task.summary.startswith("共 ")  # eg "共 7 条疑点..."
    finally:
        db.close()


# ─── eager 模式失败传播 ──────────────────────────────
def test_failed_task_marks_status_failed(client):
    """文档不存在的场景 → task 标记 failed 而非崩溃。"""
    from app.models import SessionLocal, CheckTask
    from app.services.check_service import execute_pending_check

    db = SessionLocal()
    try:
        # 手工构造一条引用不存在文档的 pending 任务
        task = CheckTask(document_id=99999, template_key="contract",
                         status="pending", summary="x")
        db.add(task); db.commit(); db.refresh(task)
        task_id = task.id
    finally:
        db.close()

    db = SessionLocal()
    try:
        task = db.get(CheckTask, task_id)
        execute_pending_check(db, task, None)
        db.refresh(task)
        assert task.status == "failed"
        assert "不存在" in task.summary
    finally:
        db.close()
