"""v1.5 批量删除材料测试。"""
import io
from fastapi.testclient import TestClient


def _setup_task(client, headers, name_suffix=""):
    r = client.post("/api/units",
                    json={"name": f"BATCHDEL-{name_suffix}", "code": "BD"},
                    headers=headers)
    assert r.status_code == 200, r.text
    unit_id = r.json()["id"]
    r = client.post("/api/tasks",
                    json={"unit_id": unit_id, "name": f"bd {name_suffix}",
                          "eval_year": 2025, "scope": "all"},
                    headers=headers)
    return r.json()["id"]


def _upload(client, headers, task_id, fn, content=b"x"):
    files = {"file": (fn, io.BytesIO(content), "text/plain")}
    r = client.post(f"/api/tasks/{task_id}/materials",
                    files=files, headers=headers)
    return r.json()


def test_batch_delete_removes_multiple(auth_headers):
    """创建 3 个材料，删 2 个 → DB 剩 1，deleted=2。"""
    from app.main import app
    with TestClient(app) as c:
        t = _setup_task(c, auth_headers, "1")
        m1 = _upload(c, auth_headers, t, "f1.txt", b"alpha")
        m2 = _upload(c, auth_headers, t, "f2.txt", b"beta")
        m3 = _upload(c, auth_headers, t, "f3.txt", b"gamma")
        r = c.post("/api/materials/batch-delete",
                   headers=auth_headers,
                   json={"material_ids": [m1["id"], m2["id"]]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["deleted"] == 2
        from app.models import SessionLocal, Material
        with SessionLocal() as s:
            assert s.get(Material, m3["id"]) is not None
            assert s.get(Material, m1["id"]) is None


def test_batch_delete_keeps_referenced_physical(auth_headers):
    """A、B 任务上传同份内容 → 批量删 A 的 Material → 物理文件还在。"""
    from app.main import app
    from pathlib import Path
    with TestClient(app) as c:
        t1 = _setup_task(c, auth_headers, "2A")
        t2 = _setup_task(c, auth_headers, "2B")
        content = b"shared physical content " + b"s" * 200
        m1 = _upload(c, auth_headers, t1, "x.txt", content)
        m2 = _upload(c, auth_headers, t2, "x.txt", content)
        from app.models import SessionLocal, Material
        with SessionLocal() as s:
            path = s.get(Material, m1["id"]).storage_path
        r = c.post("/api/materials/batch-delete",
                   headers=auth_headers,
                   json={"material_ids": [m1["id"]]})
        assert r.status_code == 200
        body = r.json()
        assert body["deleted"] == 1
        assert body["kept_physical"] == 1
        assert Path(path).exists()


def test_batch_delete_empty_list_returns_zero(auth_headers):
    """传空 list → deleted=0，不报错。"""
    from app.main import app
    with TestClient(app) as c:
        r = c.post("/api/materials/batch-delete",
                   headers=auth_headers, json={"material_ids": []})
        assert r.status_code == 200
        body = r.json()
        assert body["deleted"] == 0
