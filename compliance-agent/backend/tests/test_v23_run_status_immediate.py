"""v2.3 POST /api/tasks/{id}/run 立即设 task.status=running。

修复"celery 异步 → 前端拿 stale status → polling 不启动"的时序 bug。
"""
from __future__ import annotations

import io
import json
import uuid

import pytest
from fastapi.testclient import TestClient


def _setup_task(client, headers):
    """建 unit + task（scope=selected 只含 I-13）+ 1 份绑到 I-13 的材料。

    返回 task_id。
    """
    suffix = uuid.uuid4().hex[:6]
    r = client.post("/api/units",
                    json={"name": f"v23-{suffix}", "code": f"V23{suffix}"},
                    headers=headers)
    assert r.status_code == 200, r.text
    unit_id = r.json()["id"]

    inds = client.get("/api/indicators", headers=headers).json()
    i13 = next(i for i in inds if i["indicator_code"] == "I-13")

    r = client.post("/api/tasks", json={
        "unit_id": unit_id, "name": f"v23-{suffix}",
        "eval_year": 2026, "scope": "selected",
        "selected_indicator_ids": [i13["id"]],
    }, headers=headers)
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]

    # 上传一份材料绑到 I-13
    files = {"file": (f"v23-{suffix}.txt",
                      io.BytesIO(b"v23 test content 32bytes padding padding"),
                      "text/plain")}
    data = {"indicator_id": str(i13["id"])}
    r = client.post(f"/api/tasks/{task_id}/materials",
                    files=files, data=data, headers=headers)
    assert r.status_code == 200, r.text

    return task_id


def test_run_task_sets_status_running_immediately(auth_headers, monkeypatch):
    """v2.3：POST /run 应立即把 task.status 设为 running（+ 特定 progress_text），
    不必等 celery worker 跑到 orchestrator.run_audit 才生效。

    通过 monkeypatch run_audit_task.delay 让它 no-op，隔离 celery 效果，
    这样断言的 status/progress_text 只可能来自 backend 主动设置。
    """
    from app.main import app
    from app.seeds.load_indicators_55 import load as load_indicators
    load_indicators(replace=False)

    # 让 delay 变成 no-op，避免 eager 模式下 celery 同步跑完覆盖 status
    from app import tasks as _tasks_pkg
    from app.api import audit_routes as _audit_routes_mod
    monkeypatch.setattr(
        _tasks_pkg.run_audit_task, "delay",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        _audit_routes_mod.run_audit_task, "delay",
        lambda *a, **kw: None,
    )

    with TestClient(app, headers=auth_headers) as client:
        task_id = _setup_task(client, auth_headers)

        r = client.post(f"/api/tasks/{task_id}/run")
        assert r.status_code == 200, r.text
        body = r.json()
        # backend 立即设 running，delay 被 mock 掉不会往下推进
        assert body["status"] == "running", (
            f"POST /run 响应体 status={body['status']!r}，期望 running"
        )
        # v2.3 明确写入的 progress_text 字面量
        assert body["progress_text"] == "已提交，等待 worker 拾取…", (
            f"progress_text={body['progress_text']!r}"
        )
        assert body["progress_current"] == 0
        assert body["progress_total"] == 0

        # 独立 GET 也应保持 running（因为 delay 被 mock，orchestrator 没跑）
        r = client.get(f"/api/tasks/{task_id}")
        assert r.status_code == 200
        detail = r.json()
        assert detail["task"]["status"] == "running"


def test_run_task_rejects_when_already_running(auth_headers):
    """v2.3：如果任务已在 running 状态，二次 POST /run 应 400，
    避免用户重复点击导致并发 orchestrator。"""
    from app.main import app
    from app.models import AuditTask, SessionLocal
    from app.seeds.load_indicators_55 import load as load_indicators
    load_indicators(replace=False)

    with TestClient(app, headers=auth_headers) as client:
        task_id = _setup_task(client, auth_headers)

        # 手动把 task.status 设 running 模拟"正在跑"场景
        db = SessionLocal()
        try:
            task = db.get(AuditTask, task_id)
            task.status = "running"
            db.commit()
        finally:
            db.close()

        # 二次 POST /run 应 400
        r = client.post(f"/api/tasks/{task_id}/run")
        assert r.status_code == 400, r.text
        assert "正在核查中" in r.json().get("detail", "")
