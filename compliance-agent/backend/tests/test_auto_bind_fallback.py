"""auto_bind_materials 第 3 阶段（subcategory 兜底）测试。

测试使用 stub LLM（conftest 已设环境变量）→ ai_classify 直接返回 {}，
因此能纯净地测「关键词 + 兜底」两条路径，验证 still_unbound == 0。
"""
import io
import json

import pytest
from fastapi.testclient import TestClient


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _seed_indicators(client, headers):
    """导入 I-13（预算）、I-44（合同）、I-55（补充）三条种子指标。"""
    data = [
        {
            "indicator_code": "I-13",
            "level": "单位",
            "category": "预算业务控制",
            "name": "预算管理",
            "max_score": 4,
            "deduct_rules": "",
            "common_deductions": "",
            "required_materials": ["预算制度", "预算方案"],
        },
        {
            "indicator_code": "I-44",
            "level": "单位",
            "category": "合同控制",
            "name": "合同管理制度",
            "max_score": 4,
            "deduct_rules": "",
            "common_deductions": "",
            "required_materials": ["合同管理制度"],
        },
        {
            "indicator_code": "I-55",
            "level": "单位",
            "category": "补充指标",
            "name": "补充指标",
            "max_score": 0,
            "deduct_rules": "",
            "common_deductions": "",
            "required_materials": [],
        },
    ]
    r = client.post(
        "/api/indicators/import",
        files={"file": ("indicators.json",
                        io.BytesIO(json.dumps(data).encode()),
                        "application/json")},
        headers=headers,
    )
    assert r.status_code == 200, f"seed indicators failed: {r.text}"


def _make_task(client, headers, unit_name="测试单位 A"):
    r = client.post("/api/units", json={"name": unit_name, "code": "T-001"},
                    headers=headers)
    assert r.status_code == 200, r.text
    unit_id = r.json()["id"]
    r = client.post("/api/tasks",
                    json={"unit_id": unit_id, "name": "fallback 测试任务", "scope": "all"},
                    headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _upload(client, headers, task_id, filename, content=b"test content"):
    # 使用 .txt 避免 pymupdf 解析真实 PDF — 解析器对 txt 直接读文本
    fname = filename.replace(".pdf", ".txt")
    files = {"file": (fname, io.BytesIO(content), "text/plain")}
    r = client.post(f"/api/tasks/{task_id}/materials", files=files, headers=headers)
    assert r.status_code == 200, r.text


# ── 测试 ─────────────────────────────────────────────────────────────────────

def test_auto_bind_fallback_zero_unbound(auth_headers):
    """端到端：上传一批文件名不含任何指标关键词的材料，
    经过关键词 + AI(stub返回空) + subcategory 兜底后 still_unbound 必须为 0。"""
    from app.main import app
    with TestClient(app) as client:
        _seed_indicators(client, auth_headers)
        task_id = _make_task(client, auth_headers, unit_name="兜底测试单位 1")
        # 子类关键词命中 但 indicator 关键词不命中 → 走第 3 阶段
        for fn in [
            "（一）预算公开报告 2025.pdf",
            "（六）合同签订记录 2025.pdf",
            "完全不带关键词的材料 abc.pdf",  # 这条连子类都没 → 应落到 I-55
        ]:
            _upload(client, auth_headers, task_id, fn)

        r = client.post(f"/api/tasks/{task_id}/materials/auto-bind",
                        headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["still_unbound"] == 0, body
        assert body["fallback_bound"] >= 1


def test_auto_bind_result_has_fallback_field(auth_headers):
    """返回 JSON 必须包含 fallback_bound 字段（向后兼容前端读取）。"""
    from app.main import app
    with TestClient(app) as client:
        _seed_indicators(client, auth_headers)
        task_id = _make_task(client, auth_headers, unit_name="兜底测试单位 2")
        _upload(client, auth_headers, task_id, "随便起的名.txt")
        r = client.post(f"/api/tasks/{task_id}/materials/auto-bind",
                        headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        for k in ("checked", "keyword_bound", "ai_bound", "fallback_bound", "still_unbound"):
            assert k in body, f"缺字段 {k}: {body}"
