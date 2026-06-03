"""/api/tasks/{id}/run 防重复触发测试。"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(auth_headers):
    from app.main import app
    from app.seeds.load_indicators_55 import load
    load(replace=True)
    with TestClient(app, headers=auth_headers) as c:
        yield c


def _new_task_with_material(client, name):
    uid = client.post("/api/units", json={"name": name, "code": ""}).json()["id"]
    inds = client.get("/api/indicators").json()
    task_id = client.post("/api/tasks", json={
        "unit_id": uid, "name": name, "eval_year": 2025,
        "scope": "selected", "selected_indicator_ids": [inds[0]["id"]],
    }).json()["id"]
    client.post(f"/api/tasks/{task_id}/materials",
                files={"file": ("a.txt", b"x", "text/plain")})
    return task_id


def test_run_rejected_when_no_materials(client):
    """没材料 → 400。"""
    uid = client.post("/api/units", json={"name": "RUN-EMPTY", "code": ""}).json()["id"]
    inds = client.get("/api/indicators").json()
    task_id = client.post("/api/tasks", json={
        "unit_id": uid, "name": "empty", "eval_year": 2025,
        "scope": "selected", "selected_indicator_ids": [inds[0]["id"]],
    }).json()["id"]
    r = client.post(f"/api/tasks/{task_id}/run")
    assert r.status_code == 400


def test_run_rejected_when_already_done(client):
    """ai_done 状态不带 force → 400。"""
    task_id = _new_task_with_material(client, "RUN-DONE-1")
    # 第一次跑（eager 模式同步完成）
    r1 = client.post(f"/api/tasks/{task_id}/run")
    assert r1.status_code == 200
    assert r1.json()["status"] == "ai_done"

    # 第二次裸跑 → 400
    r2 = client.post(f"/api/tasks/{task_id}/run")
    assert r2.status_code == 400
    assert "force" in r2.json()["detail"]


def test_run_allowed_when_forced(client):
    """ai_done 状态带 force=true → 通过。"""
    task_id = _new_task_with_material(client, "RUN-DONE-2")
    r1 = client.post(f"/api/tasks/{task_id}/run")
    assert r1.status_code == 200

    r2 = client.post(f"/api/tasks/{task_id}/run?force=true")
    assert r2.status_code == 200, r2.text
    # 应再次进入 ai_done（eager 模式立刻完成）
    assert r2.json()["status"] == "ai_done"


def test_run_rejected_when_running(client):
    """status=running 时拒绝（人为构造）。"""
    task_id = _new_task_with_material(client, "RUN-LOCK")
    # 手动改 running
    from app.models import SessionLocal, AuditTask
    db = SessionLocal()
    t = db.get(AuditTask, task_id)
    t.status = "running"
    db.commit(); db.close()

    r = client.post(f"/api/tasks/{task_id}/run")
    assert r.status_code == 400
    assert "核查中" in r.json()["detail"]
