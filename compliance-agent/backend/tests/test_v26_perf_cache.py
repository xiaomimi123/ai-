"""v2.6 backend perf: list_tasks defer stats。

目的：让 GET /api/tasks 不 SELECT stats 大 JSON 字段（省序列化），
但 GET /api/tasks/{id} 详情端点仍返回完整 stats（详情页需要）。

断言：
- list 响应里每条 task.stats == ""（手动映射填空）
- detail 响应里 task.stats 有真实 JSON 内容
- list 数量 == db.count()（不漏任务）
"""
from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient


def _setup_task_with_stats(client, headers, stats_content: str):
    """建 unit + task + 手动写 stats 字段。"""
    from app.models import AuditTask, SessionLocal
    from app.seeds.load_indicators_55 import load as load_ind
    load_ind(replace=False)

    suffix = uuid.uuid4().hex[:6]
    r = client.post("/api/units",
                    json={"name": f"v26-{suffix}", "code": f"V26{suffix}"},
                    headers=headers)
    unit_id = r.json()["id"]

    inds = client.get("/api/indicators", headers=headers).json()
    i13 = next(i for i in inds if i["indicator_code"] == "I-13")

    r = client.post("/api/tasks", json={
        "unit_id": unit_id, "name": f"v26-{suffix}",
        "eval_year": 2026, "scope": "selected",
        "selected_indicator_ids": [i13["id"]],
    }, headers=headers)
    task_id = r.json()["id"]

    # 手动写 stats 到 DB（模拟核查完成后的 stats）
    db = SessionLocal()
    try:
        t = db.get(AuditTask, task_id)
        t.stats = stats_content
        db.commit()
    finally:
        db.close()

    return task_id


def test_list_tasks_response_omits_stats_content(auth_headers):
    """v2.6：GET /api/tasks 响应里 task.stats 字段为空字符串（defer 生效 + 手动映射）。"""
    from app.main import app

    STATS_JSON = json.dumps({
        "findings_by_type": {"合规性": 12, "完整性": 5, "重复性": 3},
        "score_summary": {"total": 87.5, "max": 100},
        "breakdown": [{"indicator": "I-13", "score": 4.5}] * 20,
    })

    with TestClient(app, headers=auth_headers) as client:
        task_id = _setup_task_with_stats(client, auth_headers, STATS_JSON)

        # GET list
        r = client.get("/api/tasks")
        assert r.status_code == 200
        tasks = r.json()

        # 找到刚建的 task
        me = next((t for t in tasks if t["id"] == task_id), None)
        assert me is not None, "刚建的 task 应在 list 里"

        # 关键断言：list 响应里 stats 是空字符串（defer + 手动映射效果）
        assert me["stats"] == "", (
            f"list 响应里 stats 应为空字符串（v2.6 defer 效果），实际: {me['stats']!r}"
        )


def test_task_detail_still_returns_full_stats(auth_headers):
    """v2.6：GET /api/tasks/{id} 详情端点仍返回完整 stats（不受 defer 影响）。"""
    from app.main import app

    STATS_JSON = json.dumps({
        "findings_by_type": {"合规性": 12},
        "score_summary": {"total": 87.5, "max": 100},
    })

    with TestClient(app, headers=auth_headers) as client:
        task_id = _setup_task_with_stats(client, auth_headers, STATS_JSON)

        # GET detail
        r = client.get(f"/api/tasks/{task_id}")
        assert r.status_code == 200
        detail = r.json()

        # 详情里 stats 应包含真实 JSON
        assert detail["task"]["stats"] == STATS_JSON, (
            f"详情 stats 应为真实内容，实际: {detail['task']['stats']!r}"
        )
        # 解析后应有 findings_by_type
        parsed = json.loads(detail["task"]["stats"])
        assert "findings_by_type" in parsed


def test_list_tasks_count_matches_db(auth_headers):
    """v2.6：GET /api/tasks 返回条数 == DB 里 AuditTask 总数（不漏不重）。"""
    from app.main import app
    from app.models import AuditTask, SessionLocal

    with TestClient(app, headers=auth_headers) as client:
        # 建 2 个新 task（在已有基础上）
        _setup_task_with_stats(client, auth_headers, '{}')
        _setup_task_with_stats(client, auth_headers, '{}')

        # DB 里的总数
        db = SessionLocal()
        try:
            db_count = db.query(AuditTask).count()
        finally:
            db.close()

        # API 返回条数
        r = client.get("/api/tasks")
        api_count = len(r.json())

        assert api_count == db_count, (
            f"API 返回 {api_count} 条，DB 实际 {db_count} 条"
        )
