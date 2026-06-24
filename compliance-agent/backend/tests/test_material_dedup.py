"""跨任务文件去重测试（v1.4）。"""
import io
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


def _setup_task(client, headers, name_suffix=""):
    """建一个单位 + 任务，返回 task_id。"""
    r = client.post("/api/units",
                    json={"name": f"DEDUP-{name_suffix}", "code": "D"},
                    headers=headers)
    assert r.status_code == 200, r.text
    unit_id = r.json()["id"]
    r = client.post("/api/tasks",
                    json={"unit_id": unit_id, "name": f"dedup task {name_suffix}",
                          "eval_year": 2025, "scope": "all"},
                    headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _upload(client, headers, task_id, file_name, content):
    """上传材料，返回 response.json()。"""
    files = {"file": (file_name, io.BytesIO(content), "text/plain")}
    r = client.post(f"/api/tasks/{task_id}/materials",
                    files=files, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _material_path(db, material_id: int) -> str:
    """从 DB 直接取 storage_path（绕过 API）。"""
    from app.models import SessionLocal, Material
    with SessionLocal() as s:
        m = s.get(Material, material_id)
        return m.storage_path


def test_upload_dedup_reuses_storage_path(auth_headers):
    """同字节内容上传两次（不同任务）→ Material.storage_path 相同。"""
    from app.main import app
    with TestClient(app) as c:
        t1 = _setup_task(c, auth_headers, "1A")
        t2 = _setup_task(c, auth_headers, "1B")
        content = b"identical content for dedup test " + b"x" * 100
        m1 = _upload(c, auth_headers, t1, "doc.txt", content)
        m2 = _upload(c, auth_headers, t2, "doc.txt", content)
        # 不同 Material id 但相同 storage_path
        assert m1["id"] != m2["id"]
        from app.models import SessionLocal, Material
        with SessionLocal() as s:
            mat1 = s.get(Material, m1["id"])
            mat2 = s.get(Material, m2["id"])
            assert mat1.storage_path == mat2.storage_path


def test_upload_dedup_first_time_writes_normally(auth_headers, tmp_path):
    """首次上传走原流程：写新文件，storage_path 是新 uuid 命名。"""
    from app.main import app
    with TestClient(app) as c:
        t1 = _setup_task(c, auth_headers, "2A")
        unique = b"unique content " + str(id(object())).encode()
        m1 = _upload(c, auth_headers, t1, "fresh.txt", unique)
        from app.models import SessionLocal, Material
        with SessionLocal() as s:
            mat = s.get(Material, m1["id"])
            from pathlib import Path
            assert Path(mat.storage_path).exists()
        assert m1.get("reused") is False or m1.get("reused") is None


def test_upload_dedup_skips_disk_write_on_second_upload(auth_headers, monkeypatch):
    """第二次上传同内容 → 不写盘（监控 Path.write_bytes 调用次数）。"""
    from app.main import app
    from pathlib import Path
    real_write = Path.write_bytes
    call_count = {"n": 0}
    def counting_write(self, data):
        call_count["n"] += 1
        return real_write(self, data)
    monkeypatch.setattr(Path, "write_bytes", counting_write)
    with TestClient(app) as c:
        t1 = _setup_task(c, auth_headers, "3A")
        t2 = _setup_task(c, auth_headers, "3B")
        content = b"counting writes " + b"y" * 200
        _upload(c, auth_headers, t1, "a.txt", content)
        n_after_first = call_count["n"]
        _upload(c, auth_headers, t2, "b.txt", content)
        # 第二次不该多调 write_bytes
        assert call_count["n"] == n_after_first, (
            f"第二次上传应复用 storage 不写盘，但 write_bytes 调用从 "
            f"{n_after_first} 变为 {call_count['n']}"
        )


def test_upload_reused_flag_in_response(auth_headers):
    """API 响应应含 reused 字段，第二次为 True 且 reused_size_mb > 0。"""
    from app.main import app
    with TestClient(app) as c:
        t1 = _setup_task(c, auth_headers, "4A")
        t2 = _setup_task(c, auth_headers, "4B")
        content = b"flag test content " + b"z" * 1024 * 50  # ~50KB
        m1 = _upload(c, auth_headers, t1, "x.txt", content)
        m2 = _upload(c, auth_headers, t2, "x.txt", content)
        assert m1.get("reused", False) is False
        assert m2.get("reused") is True
        assert m2.get("reused_size_mb", 0) > 0


def test_upload_dedup_handles_missing_physical_file(auth_headers):
    """DB 有 hash 但物理文件被外部删除 → 第二次上传重新落盘。"""
    from app.main import app
    from pathlib import Path
    with TestClient(app) as c:
        t1 = _setup_task(c, auth_headers, "5A")
        t2 = _setup_task(c, auth_headers, "5B")
        content = b"missing file test " + b"m" * 100
        m1 = _upload(c, auth_headers, t1, "m.txt", content)
        # 手动 rm 物理文件
        path1 = _material_path(None, m1["id"])
        Path(path1).unlink()
        assert not Path(path1).exists()
        # 再传 → 应当不复用（已不存在），重新落盘
        m2 = _upload(c, auth_headers, t2, "m.txt", content)
        assert m2.get("reused", False) is False
        path2 = _material_path(None, m2["id"])
        assert Path(path2).exists()
