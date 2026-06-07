"""材料预览 / 下载端点测试。"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(auth_headers):
    from app.main import app
    from app.seeds.load_indicators_55 import load
    load(replace=True)
    with TestClient(app, headers=auth_headers) as c:
        yield c


def _setup_task(client, name):
    uid = client.post("/api/units", json={"name": name, "code": ""}).json()["id"]
    inds = client.get("/api/indicators").json()
    tid = client.post("/api/tasks", json={
        "unit_id": uid, "name": name, "eval_year": 2025,
        "scope": "selected", "selected_indicator_ids": [inds[0]["id"]],
    }).json()["id"]
    return tid


def _upload(client, task_id, fname, content, ctype="text/plain"):
    r = client.post(
        f"/api/tasks/{task_id}/materials",
        files={"file": (fname, content, ctype)},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _make_material_direct(task_id, fname, content):
    """绕过上传流程直接造一个 Material 记录（用于测试非 txt 类型而不触发解析）。"""
    import os, uuid
    from pathlib import Path
    from app.models import SessionLocal, Material
    from app.core.config import settings as app_settings
    Path(app_settings.storage_dir).mkdir(parents=True, exist_ok=True)
    ext = Path(fname).suffix.lstrip(".")
    safe = f"{uuid.uuid4().hex}.{ext}"
    p = Path(app_settings.storage_dir) / safe
    p.write_bytes(content)
    db = SessionLocal()
    try:
        m = Material(
            task_id=task_id, indicator_id=None,
            file_name=fname, storage_path=str(p), file_type=ext,
            is_scanned=False, key_elements="{}", parsed_text="",
        )
        db.add(m); db.commit(); db.refresh(m)
        return m.id
    finally:
        db.close()


def test_preview_txt_inline(client):
    """txt 文件应 inline 返回 text/plain。"""
    task_id = _setup_task(client, "PREVIEW-TXT")
    payload = "Hello World 你好世界".encode("utf-8")
    mid = _upload(client, task_id, "note.txt", payload)
    r = client.get(f"/api/materials/{mid}/preview")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    cd = r.headers.get("content-disposition", "").lower()
    assert cd.startswith("inline"), f"应 inline，实际 {cd}"
    assert r.content == payload


def test_preview_docx_attachment(client):
    """docx 文件应 attachment（强制下载）。"""
    task_id = _setup_task(client, "PREVIEW-DOCX")
    mid = _make_material_direct(task_id, "制度.docx", b"FAKE_DOCX_BYTES")
    r = client.get(f"/api/materials/{mid}/preview")
    assert r.status_code == 200
    cd = r.headers.get("content-disposition", "").lower()
    assert cd.startswith("attachment"), f"应 attachment，实际 {cd}"
    assert "wordprocessingml" in r.headers["content-type"]


def test_preview_pdf_inline(client):
    """PDF 应 inline 让浏览器内嵌预览。"""
    task_id = _setup_task(client, "PREVIEW-PDF")
    mid = _make_material_direct(task_id, "report.pdf", b"%PDF-1.4\n%fake but valid header")
    r = client.get(f"/api/materials/{mid}/preview")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].lower().startswith("inline")


def test_preview_404_when_missing(client):
    r = client.get("/api/materials/999999/preview")
    assert r.status_code == 404


def test_preview_includes_chinese_filename(client):
    """文件名含中文 → Content-Disposition 用 RFC 5987 编码。"""
    task_id = _setup_task(client, "PREVIEW-CN")
    mid = _upload(client, task_id, "财务报告.txt", b"x")
    r = client.get(f"/api/materials/{mid}/preview")
    assert r.status_code == 200
    assert "filename*=UTF-8''" in r.headers["content-disposition"]
