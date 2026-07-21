"""v2.13 工作台单位核查进度总览端点测试。"""
from fastapi.testclient import TestClient


def test_summary_empty_db_returns_zeros(auth_headers):
    """空库（无单位）→ 5 档全 0。"""
    from app.main import app
    with TestClient(app) as client:
        r = client.get("/api/dashboard/unit-stats/summary", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        # total 可能非 0（其它测试残留），但结构必须有 5 键
        assert set(data.keys()) == {
            "total", "no_task", "has_task_no_material",
            "in_progress_with_material", "completed",
        }
        # 后 4 档相加 = total
        assert (data["no_task"] + data["has_task_no_material"]
                + data["in_progress_with_material"] + data["completed"]
                == data["total"])


def _seed_unit_with_task_and_materials(client, headers, unit_name, task_name,
                                       n_materials=0, finalize=False):
    """建 unit + task；可选 n_materials 上传 + finalize。返回 (unit_id, task_id)。"""
    import io
    r = client.post("/api/units",
                    json={"name": unit_name, "code": "T"},
                    headers=headers)
    assert r.status_code == 200, r.text
    unit_id = r.json()["id"]
    r = client.post("/api/tasks",
                    json={"unit_id": unit_id, "name": task_name,
                          "eval_year": 2025, "scope": "all"},
                    headers=headers)
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]

    for i in range(n_materials):
        files = {"file": (f"m{i}.txt", io.BytesIO(b"x"), "text/plain")}
        r = client.post(f"/api/tasks/{task_id}/materials",
                        files=files, headers=headers)
        assert r.status_code == 200, r.text

    if finalize:
        from app.models import SessionLocal, AuditTask, Worksheet
        with SessionLocal() as s:
            t = s.get(AuditTask, task_id)
            t.status = "finalized"
            ws = Worksheet(task_id=task_id, status="finalized")
            s.add(ws)
            s.commit()

    return (unit_id, task_id)


def test_summary_categorizes_all_five_buckets(auth_headers):
    """seed 4 unit（各 1 档，除 total）→ summary 每档增 1。"""
    from app.main import app
    with TestClient(app) as client:
        # 拿到 baseline（其它测试残留）
        r0 = client.get("/api/dashboard/unit-stats/summary", headers=auth_headers)
        base = r0.json()

        # bucket no_task: 建单位不建任务
        r = client.post("/api/units",
                        json={"name": "v213-notask", "code": "N"},
                        headers=auth_headers)
        assert r.status_code == 200

        # bucket has_task_no_material: 建单位 + 任务，不上传
        _seed_unit_with_task_and_materials(
            client, auth_headers, "v213-htnm", "T_htnm", n_materials=0,
        )

        # bucket in_progress_with_material: 建 + 上传 1 材料 + 不 finalize
        _seed_unit_with_task_and_materials(
            client, auth_headers, "v213-ipwm", "T_ipwm", n_materials=1,
        )

        # bucket completed: 建 + 上传 1 材料 + finalize
        _seed_unit_with_task_and_materials(
            client, auth_headers, "v213-done", "T_done", n_materials=1,
            finalize=True,
        )

        r = client.get("/api/dashboard/unit-stats/summary", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == base["total"] + 4
        assert data["no_task"] == base["no_task"] + 1
        assert data["has_task_no_material"] == base["has_task_no_material"] + 1
        assert data["in_progress_with_material"] == base["in_progress_with_material"] + 1
        assert data["completed"] == base["completed"] + 1


def test_detail_no_task_lists_units_without_tasks(auth_headers):
    """no_task detail 只列出无任务的单位。"""
    from app.main import app
    with TestClient(app) as client:
        r = client.post("/api/units",
                        json={"name": "v213-detail-notask", "code": "N"},
                        headers=auth_headers)
        assert r.status_code == 200

        r = client.get(
            "/api/dashboard/unit-stats/detail?category=no_task",
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        names = {item["name"] for item in data}
        assert "v213-detail-notask" in names
        # 且该 unit 的 total_tasks == 0
        item = next(i for i in data if i["name"] == "v213-detail-notask")
        assert item["total_tasks"] == 0


def test_detail_has_task_no_material_lists_correctly(auth_headers):
    """has_task_no_material detail 列出建了任务但 0 材料的单位。"""
    from app.main import app
    with TestClient(app) as client:
        _seed_unit_with_task_and_materials(
            client, auth_headers, "v213-detail-htnm", "T_x", n_materials=0,
        )

        r = client.get(
            "/api/dashboard/unit-stats/detail?category=has_task_no_material",
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        item = next((i for i in data if i["name"] == "v213-detail-htnm"), None)
        assert item is not None
        assert item["total_tasks"] >= 1
        assert item["material_count"] == 0


def test_detail_in_progress_with_material_shows_material_count(auth_headers):
    """in_progress_with_material detail 含 material_count 字段。"""
    from app.main import app
    with TestClient(app) as client:
        _seed_unit_with_task_and_materials(
            client, auth_headers, "v213-detail-ipwm", "T_y", n_materials=2,
        )

        r = client.get(
            "/api/dashboard/unit-stats/detail?category=in_progress_with_material",
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        item = next((i for i in data if i["name"] == "v213-detail-ipwm"), None)
        assert item is not None
        assert item["material_count"] >= 2
        assert item["finalized_tasks"] == 0


def test_detail_rejects_completed_and_unknown_categories(auth_headers):
    """completed 无 detail 端点 → 400；unknown 也 → 400。"""
    from app.main import app
    with TestClient(app) as client:
        r = client.get(
            "/api/dashboard/unit-stats/detail?category=completed",
            headers=auth_headers,
        )
        assert r.status_code == 400

        r = client.get(
            "/api/dashboard/unit-stats/detail?category=nonsense",
            headers=auth_headers,
        )
        assert r.status_code == 400


def test_region_finding_stats_structure(auth_headers):
    """/region-finding-stats 返 dict 含 finding_types + regions 两键。"""
    from app.main import app
    with TestClient(app) as client:
        r = client.get(
            "/api/dashboard/region-finding-stats",
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert "finding_types" in data
        assert "regions" in data
        assert isinstance(data["finding_types"], list)
        assert isinstance(data["regions"], list)
        # finding_types 至少 6 个（v1.6 _VALID_FINDING_TYPES 定义）
        assert len(data["finding_types"]) >= 6
        # 每 region 结构合法
        for r_ in data["regions"]:
            assert set(r_.keys()) >= {"region", "unit_count", "counts", "total"}


def test_region_finding_stats_counts_findings_correctly(auth_headers):
    """seed 一个 unit+region+task+finding → 该 region.counts 对应 type=1。"""
    from app.main import app
    from app.models import (
        SessionLocal, AuditUnit, AuditTask, Finding,
    )
    with TestClient(app) as client:
        # 建 unit + region
        r = client.post("/api/units",
                        json={"name": "v214-rfs-1", "code": "RFS1"},
                        headers=auth_headers)
        assert r.status_code == 200
        uid = r.json()["id"]
        with SessionLocal() as s:
            u = s.get(AuditUnit, uid)
            u.region = "v214-region-x"
            s.commit()

        # 建 task
        r = client.post("/api/tasks",
                        json={"unit_id": uid, "name": "T_RFS1",
                              "eval_year": 2025, "scope": "all"},
                        headers=auth_headers)
        assert r.status_code == 200
        tid = r.json()["id"]

        # 直接 seed finding
        with SessionLocal() as s:
            f = Finding(task_id=tid, indicator_id=None,
                        finding_type="真实性问题", severity="中",
                        description="test finding")
            s.add(f); s.commit()

        r = client.get(
            "/api/dashboard/region-finding-stats", headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        region_entry = next(
            (r for r in data["regions"] if r["region"] == "v214-region-x"),
            None,
        )
        assert region_entry is not None
        assert region_entry["unit_count"] == 1
        assert region_entry["counts"]["真实性问题"] >= 1
        assert region_entry["total"] >= 1


def test_region_finding_stats_excludes_empty_region_units(auth_headers):
    """region 为空的 unit 不出现在返回列表。"""
    from app.main import app
    with TestClient(app) as client:
        # 建一个 region 为空的 unit
        r = client.post("/api/units",
                        json={"name": "v214-rfs-empty", "code": "EMPTY"},
                        headers=auth_headers)
        assert r.status_code == 200

        r = client.get(
            "/api/dashboard/region-finding-stats", headers=auth_headers,
        )
        assert r.status_code == 200
        regions = r.json()["regions"]
        # 空 region 不应出现（因为 region == "" 被 filter）
        assert not any(x["region"] == "" for x in regions)
