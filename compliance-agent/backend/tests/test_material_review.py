"""材料审核聚合视图测试。"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(auth_headers):
    from app.main import app
    from app.seeds.load_indicators_55 import load
    load(replace=True)
    with TestClient(app, headers=auth_headers) as c:
        yield c


def _create_task(client, name):
    uid = client.post("/api/units", json={"name": name, "code": ""}).json()["id"]
    inds = client.get("/api/indicators").json()
    tid = client.post("/api/tasks", json={
        "unit_id": uid, "name": name, "eval_year": 2025,
        "scope": "selected", "selected_indicator_ids": [inds[0]["id"]],
    }).json()["id"]
    return tid, inds


def test_review_overview_structure(client):
    """聚合接口返回的 4 类数据字段齐全。"""
    task_id, _ = _create_task(client, "REVIEW-1")
    client.post(f"/api/tasks/{task_id}/materials",
                files={"file": ("a.txt", b"hello", "text/plain")})

    r = client.get(f"/api/tasks/{task_id}/material-review")
    assert r.status_code == 200, r.text
    data = r.json()
    for key in ("duplicates", "content_review", "matching", "timeline", "bind_sources"):
        assert key in data, f"缺字段 {key}"
    # duplicates 结构
    assert "same_task_groups" in data["duplicates"]
    assert "cross_task_pairs" in data["duplicates"]
    # matching 结构
    m = data["matching"]
    for k in ("total_materials", "bound", "unbound",
              "target_indicators", "covered_indicators", "uncovered_indicators"):
        assert k in m


def test_detect_same_task_duplicates(client):
    """同任务上传 3 份相同内容材料 → 应被识别为一组重复。"""
    task_id, _ = _create_task(client, "REVIEW-DUP")
    same_content = b"shared content for dedup test"
    for fname in ("a.txt", "b.txt", "c_copy.txt"):
        client.post(
            f"/api/tasks/{task_id}/materials",
            files={"file": (fname, same_content, "text/plain")},
        )

    r = client.get(f"/api/tasks/{task_id}/material-review")
    dup = r.json()["duplicates"]["same_task_groups"]
    assert len(dup) == 1
    assert dup[0]["count"] == 3
    assert len(dup[0]["materials"]) == 3
    file_names = [m["file_name"] for m in dup[0]["materials"]]
    assert set(file_names) == {"a.txt", "b.txt", "c_copy.txt"}


def test_merge_duplicates(client):
    """合并重复材料：保留 1 份，删除其余。"""
    task_id, _ = _create_task(client, "REVIEW-MERGE")
    same_content = b"dedupe payload"
    ids = []
    for fname in ("x1.txt", "x2.txt", "x3.txt"):
        m = client.post(
            f"/api/tasks/{task_id}/materials",
            files={"file": (fname, same_content, "text/plain")},
        ).json()
        ids.append(m["id"])

    # 取这组的 hash
    overview = client.get(f"/api/tasks/{task_id}/material-review").json()
    group = overview["duplicates"]["same_task_groups"][0]
    content_hash = group["content_hash"]
    keep = group["materials"][0]["id"]

    # 合并
    r = client.post(f"/api/tasks/{task_id}/materials/merge-duplicates",
                    json={"content_hash": content_hash, "keep_material_id": keep})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["removed"] == 2
    assert res["kept"] == keep

    # 再查应该没有重复组了
    overview = client.get(f"/api/tasks/{task_id}/material-review").json()
    assert overview["duplicates"]["same_task_groups"] == []


def test_cross_task_duplicate_detection(client):
    """两个任务用同份材料 → cross_task_pairs 应非空。"""
    t1, _ = _create_task(client, "REVIEW-CROSS-A")
    t2, _ = _create_task(client, "REVIEW-CROSS-B")
    same = b"shared across two units"
    client.post(f"/api/tasks/{t1}/materials",
                files={"file": ("doc.txt", same, "text/plain")})
    client.post(f"/api/tasks/{t2}/materials",
                files={"file": ("doc.txt", same, "text/plain")})

    overview = client.get(f"/api/tasks/{t2}/material-review").json()
    cross = overview["duplicates"]["cross_task_pairs"]
    assert len(cross) >= 1
    assert cross[0]["other_task_id"] == t1


def test_matching_overview_for_partial_coverage(client):
    """selected scope 选 1 个指标 + 上传 1 份材料 → 1/1 覆盖。"""
    task_id, inds = _create_task(client, "REVIEW-MATCH")
    client.post(f"/api/tasks/{task_id}/materials",
                files={"file": ("a.txt", b"x", "text/plain")},
                data={"indicator_id": str(inds[0]["id"])})

    overview = client.get(f"/api/tasks/{task_id}/material-review").json()
    m = overview["matching"]
    assert m["total_materials"] == 1
    assert m["bound"] == 1
    assert m["target_indicators"] == 1
    assert m["covered_indicators"] == 1
    assert m["uncovered_indicators"] == 0
