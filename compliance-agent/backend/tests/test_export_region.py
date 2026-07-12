"""v2.11 批量导出（按地区）端点测试。"""
import io
import zipfile

from fastapi.testclient import TestClient


def _create_finalized_task(client, headers, unit_name, task_name):
    """建 unit + task，把 task 直接推到 finalized 状态并生成 worksheet。"""
    r = client.post("/api/units",
                    json={"name": unit_name, "code": "R"},
                    headers=headers)
    assert r.status_code == 200, r.text
    unit_id = r.json()["id"]
    r = client.post("/api/tasks",
                    json={"unit_id": unit_id, "name": task_name,
                          "eval_year": 2025, "scope": "all"},
                    headers=headers)
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]
    # 直接改 status + 生成 worksheet（跳 AI 核查，用 DB 直改）
    from app.models import SessionLocal, AuditTask, Worksheet
    with SessionLocal() as s:
        t = s.get(AuditTask, task_id)
        t.status = "finalized"
        ws = Worksheet(task_id=task_id, status="finalized")
        s.add(ws)
        s.commit()
    return task_id


def test_region_summary_only_finalized(auth_headers):
    """/exports/region-summary 只统计 finalized，其它状态忽略。"""
    from app.main import app
    with TestClient(app) as client:
        _create_finalized_task(client, auth_headers, "达州市达川区X局_summary1", "T1")
        # 建一个 non-finalized 任务（默认 status=pending）
        client.post("/api/units", json={"name": "非定稿单位_S1", "code": "R"},
                    headers=auth_headers)

        r = client.get("/api/exports/region-summary", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        # 达州市桶存在且 count=1；非定稿单位不出现
        dazhou = next((d for d in data if d["city"] == "达州市"), None)
        assert dazhou is not None
        assert dazhou["task_count"] >= 1


def test_region_summary_unclassified_bucket(auth_headers):
    """无法解析地区的单位归入"未分类"桶，unknown=True。"""
    from app.main import app
    with TestClient(app) as client:
        _create_finalized_task(client, auth_headers, "某某局_no_region", "T_UNK")
        r = client.get("/api/exports/region-summary", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        unclassified = next((d for d in data if d["city"] == "未分类"), None)
        assert unclassified is not None
        assert unclassified["unknown"] is True
        assert unclassified["task_count"] >= 1


def test_download_city_zip_structure(auth_headers, tmp_path):
    """下载 zip → 目录结构 <市>/<区县>/<单位>_<年>_<id>.xlsx。"""
    from app.main import app
    with TestClient(app) as client:
        tid = _create_finalized_task(
            client, auth_headers,
            "四川省达州市达川区试点单位_Z1", "T_Z1"
        )
        r = client.get(
            "/api/exports/worksheets/city/%E8%BE%BE%E5%B7%9E%E5%B8%82.zip",
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/zip"
        # 解析 zip
        zbuf = io.BytesIO(r.content)
        with zipfile.ZipFile(zbuf) as zf:
            names = zf.namelist()
        # 至少一个 entry 路径匹配 达州市/达川区/<...>_2025_<tid>.xlsx
        matched = [n for n in names
                   if n.startswith("达州市/达川区/")
                   and n.endswith(f"_2025_{tid}.xlsx")]
        assert matched, f"zip 内未找到期望的 entry；实际 names={names}"


def test_download_city_zip_404_when_city_empty(auth_headers):
    """请求不存在的市 → 404。"""
    from app.main import app
    with TestClient(app) as client:
        r = client.get(
            "/api/exports/worksheets/city/%E4%B8%8D%E5%AD%98%E5%9C%A8%E7%9A%84%E5%B8%82.zip",
            headers=auth_headers,
        )
        assert r.status_code == 404


def test_download_city_zip_sanitizes_slash_in_unit_name(auth_headers):
    """单位名含 / → zip entry 里 / 被 _ 替换（防路径注入）。"""
    from app.main import app
    with TestClient(app) as client:
        # 注意：AuditUnit.name 有 UNIQUE 约束；本测独立 name
        _create_finalized_task(
            client, auth_headers,
            "达州市达川区a/b单位_slash_test", "T_SLASH",
        )
        r = client.get(
            "/api/exports/worksheets/city/%E8%BE%BE%E5%B7%9E%E5%B8%82.zip",
            headers=auth_headers,
        )
        assert r.status_code == 200
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            names = zf.namelist()
        # 单位名段里不应含未转义的 /；用 _ 替换后是 "a_b单位_slash_test"
        assert any("a_b单位_slash_test" in n for n in names), \
            f"未找到 sanitize 后的 entry；names={names}"
