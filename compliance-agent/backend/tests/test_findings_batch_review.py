"""v1.6 finding 批量复核接口测试。

9 个 case：indicator 限定 / type 限定 / 两者交集 / 都不传拒绝 /
任务不存在 / 状态非法 / only_pending=False / 非审计员 403 / audit log 写入。

每个测试都通过 fixture 创建独立的测试任务（unit name 含 uuid 后缀避免冲突）。
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.main import app
from app.models import (
    AuditLog, AuditTask, AuditUnit, Finding, Indicator,
    SessionLocal, User, init_db,
)


@pytest.fixture(scope="module")
def client():
    init_db()
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def admin_token(client):
    r = client.post("/api/auth/login",
                    json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def seeded_task(client, admin_token):
    """每次调用创建一个独立测试任务 + 2 指标 + 6 finding。"""
    suffix = uuid.uuid4().hex[:8]
    db = SessionLocal()
    try:
        unit = AuditUnit(name=f"__BR_单位_{suffix}__", code=f"BR{suffix}")
        db.add(unit); db.flush()
        task = AuditTask(unit_id=unit.id, name=f"__BR_任务_{suffix}__",
                         eval_year=2026, scope="all")
        db.add(task); db.flush()
        ind_a = Indicator(indicator_code=f"I-BR-A-{suffix}",
                          name="批量测指标A")
        ind_b = Indicator(indicator_code=f"I-BR-B-{suffix}",
                          name="批量测指标B")
        db.add_all([ind_a, ind_b]); db.flush()
        fids = {"a_real_pending": [], "a_complete_pending": [],
                "a_real_confirmed": [], "b_real_pending": []}
        for _ in range(2):
            f = Finding(task_id=task.id, indicator_id=ind_a.id,
                        finding_type="真实性问题", severity="高",
                        description="A-真实-pending", review_status="pending",
                        source="rule")
            db.add(f); db.flush(); fids["a_real_pending"].append(f.id)
        f = Finding(task_id=task.id, indicator_id=ind_a.id,
                    finding_type="完整性问题", severity="中",
                    description="A-完整-pending", review_status="pending",
                    source="rule")
        db.add(f); db.flush(); fids["a_complete_pending"].append(f.id)
        f = Finding(task_id=task.id, indicator_id=ind_a.id,
                    finding_type="真实性问题", severity="高",
                    description="A-真实-已确认", review_status="confirmed",
                    source="rule")
        db.add(f); db.flush(); fids["a_real_confirmed"].append(f.id)
        for _ in range(2):
            f = Finding(task_id=task.id, indicator_id=ind_b.id,
                        finding_type="真实性问题", severity="低",
                        description="B-真实-pending", review_status="pending",
                        source="rule")
            db.add(f); db.flush(); fids["b_real_pending"].append(f.id)
        db.commit()
        return task.id, ind_a.id, ind_b.id, fids
    finally:
        db.close()


def _status_of(client, token, fid):
    r = client.get(f"/api/findings/{fid}", headers=_hdr(token))
    assert r.status_code == 200, r.text
    return r.json()["review_status"]


def test_batch_review_by_indicator(client, admin_token, seeded_task):
    task_id, ind_a, ind_b, fids = seeded_task
    r = client.post(
        f"/api/tasks/{task_id}/findings/batch-review",
        headers=_hdr(admin_token),
        json={"status": "ignored", "note": "批量忽略 A",
              "indicator_id": ind_a},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated"] == 3
    assert body["skipped"] == 1
    for fid in fids["a_real_pending"] + fids["a_complete_pending"]:
        assert _status_of(client, admin_token, fid) == "ignored"
    assert _status_of(client, admin_token,
                      fids["a_real_confirmed"][0]) == "confirmed"
    for fid in fids["b_real_pending"]:
        assert _status_of(client, admin_token, fid) == "pending"


def test_batch_review_by_finding_type(client, admin_token, seeded_task):
    task_id, ind_a, ind_b, fids = seeded_task
    r = client.post(
        f"/api/tasks/{task_id}/findings/batch-review",
        headers=_hdr(admin_token),
        json={"status": "ignored", "note": "忽略所有真实性",
              "finding_type": "真实性问题"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 4
    assert r.json()["skipped"] == 1
    assert _status_of(client, admin_token,
                      fids["a_complete_pending"][0]) == "pending"


def test_batch_review_intersection(client, admin_token, seeded_task):
    task_id, ind_a, ind_b, fids = seeded_task
    r = client.post(
        f"/api/tasks/{task_id}/findings/batch-review",
        headers=_hdr(admin_token),
        json={"status": "confirmed", "note": "确认 A 真实",
              "indicator_id": ind_a, "finding_type": "真实性问题"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 2
    assert r.json()["skipped"] == 1  # A 真实-已确认（confirmed）被 only_pending 跳过
    for fid in fids["a_real_pending"]:
        assert _status_of(client, admin_token, fid) == "confirmed"
    assert _status_of(client, admin_token,
                      fids["a_complete_pending"][0]) == "pending"
    assert _status_of(client, admin_token,
                      fids["b_real_pending"][0]) == "pending"
    # 已 confirmed 的 finding 不应被改写
    assert _status_of(client, admin_token,
                      fids["a_real_confirmed"][0]) == "confirmed"


def test_batch_review_requires_filter(client, admin_token, seeded_task):
    task_id, *_ = seeded_task
    r = client.post(
        f"/api/tasks/{task_id}/findings/batch-review",
        headers=_hdr(admin_token),
        json={"status": "ignored", "note": "x"},
    )
    assert r.status_code == 400
    assert "至少传一个" in r.text


def test_batch_review_task_not_found(client, admin_token):
    r = client.post(
        "/api/tasks/9999999/findings/batch-review",
        headers=_hdr(admin_token),
        json={"status": "ignored", "indicator_id": 1},
    )
    assert r.status_code == 404


def test_batch_review_invalid_status(client, admin_token, seeded_task):
    task_id, ind_a, *_ = seeded_task
    r = client.post(
        f"/api/tasks/{task_id}/findings/batch-review",
        headers=_hdr(admin_token),
        json={"status": "bogus", "indicator_id": ind_a},
    )
    assert r.status_code == 400


def test_batch_review_only_pending_false_overrides_confirmed(
        client, admin_token, seeded_task):
    task_id, ind_a, _, fids = seeded_task
    r = client.post(
        f"/api/tasks/{task_id}/findings/batch-review",
        headers=_hdr(admin_token),
        json={"status": "ignored", "indicator_id": ind_a,
              "only_pending": False},
    )
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 4
    assert r.json()["skipped"] == 0
    assert _status_of(client, admin_token,
                      fids["a_real_confirmed"][0]) == "ignored"


def test_batch_review_rejects_non_auditor(client, seeded_task):
    """单位角色用户应被 require_auditor 拒绝（403）。"""
    suffix = uuid.uuid4().hex[:8]
    username = f"__br_unit_user_{suffix}__"
    db = SessionLocal()
    try:
        u = User(username=username, role="unit", full_name="测单位用户",
                 password_hash=hash_password("p@ssw0rd!"))
        db.add(u); db.commit()
    finally:
        db.close()
    r = client.post("/api/auth/login",
                    json={"username": username, "password": "p@ssw0rd!"})
    assert r.status_code == 200, r.text
    unit_token = r.json()["token"]
    task_id, ind_a, *_ = seeded_task
    r = client.post(
        f"/api/tasks/{task_id}/findings/batch-review",
        headers=_hdr(unit_token),
        json={"status": "ignored", "indicator_id": ind_a},
    )
    assert r.status_code == 403


def test_batch_review_writes_audit_log(client, admin_token, seeded_task):
    task_id, ind_a, *_ = seeded_task
    r = client.post(
        f"/api/tasks/{task_id}/findings/batch-review",
        headers=_hdr(admin_token),
        json={"status": "ignored", "indicator_id": ind_a},
    )
    assert r.status_code == 200
    db = SessionLocal()
    try:
        log = (db.query(AuditLog)
                 .filter(AuditLog.action == "finding.batch_review",
                         AuditLog.target_id == task_id)
                 .order_by(AuditLog.id.desc())
                 .first())
        assert log is not None
        assert "status=ignored" in log.detail
        assert f"indicator_id={ind_a}" in log.detail
        assert "updated=3" in log.detail
        assert "skipped=1" in log.detail
        assert "candidates=4" in log.detail
    finally:
        db.close()


def test_batch_review_accepts_form_review_finding_type(
        client, admin_token, seeded_task):
    """v1.6 fix: 形式性 finding_type 必须可批量复核（rule 引擎产出）。"""
    task_id, ind_a, *_ = seeded_task
    # 给该任务下加一条"形式性" finding 作为目标
    db = SessionLocal()
    try:
        f = Finding(task_id=task_id, indicator_id=ind_a,
                    finding_type="形式性", severity="中",
                    description="测试-形式性-pending",
                    review_status="pending", source="rule")
        db.add(f); db.commit()
    finally:
        db.close()
    r = client.post(
        f"/api/tasks/{task_id}/findings/batch-review",
        headers=_hdr(admin_token),
        json={"status": "ignored", "finding_type": "形式性"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["updated"] >= 1
