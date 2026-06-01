"""端到端 v3 核查流程测试。

覆盖：单位 → 任务 → 上传材料 → 触发核查 → AI 检出 Finding →
审查员复核 → 单位整改 → 销号。
"""
import io
import json

import pytest

from app.parsers.element_extractor import extract_key_elements


# ============================================================
# key_elements 抽取
# ============================================================
class TestKeyElementsExtractor:
    def test_seal_and_signature(self):
        text = "本通知由办公会议决定，加盖单位公章。\n负责人签字：张三"
        ke = extract_key_elements(text)
        assert ke.has_official_seal
        assert ke.has_signature

    def test_year_consistency(self):
        text = "本制度自2025年3月15日起施行。"
        ke = extract_key_elements(text)
        assert ke.issue_date == "2025-03-15"
        assert ke.issue_year == 2025

    def test_document_number(self):
        text = "财办发〔2025〕12号  关于印发XX管理办法的通知"
        ke = extract_key_elements(text)
        assert "财办发" in ke.document_number
        assert "2025" in ke.document_number
        assert ke.issue_year == 2025

    def test_draft_detection(self):
        text = "（征求意见稿）\n关于内部控制评价的实施细则"
        ke = extract_key_elements(text)
        assert ke.is_draft

    def test_missing_everything(self):
        text = "这是一段没有任何关键要素的文字。"
        ke = extract_key_elements(text)
        assert not ke.has_official_seal
        assert not ke.has_signature
        assert ke.issue_date == ""


# ============================================================
# 端到端：单位 → 任务 → 上传 → 核查 → Finding → 复核 → 整改
# ============================================================
@pytest.fixture(scope="module")
def admin_client(auth_headers):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models import init_db
    init_db()
    with TestClient(app, headers=auth_headers) as c:
        # 灌入种子知识库
        _seed_indicators(c)
        _seed_check_items(c)
        yield c


def _seed_indicators(c):
    data = [
        {"indicator_code": "1-1-1", "level": "单位", "category": "组织层面",
         "name": "三重一大决策制度建立与执行", "max_score": 4,
         "deduct_rules": "无制度扣4分", "common_deductions": "缺制度文件",
         "required_materials": ["三重一大制度", "会议纪要"]},
    ]
    c.post("/api/indicators/import",
           files={"file": ("ind.json", io.BytesIO(json.dumps(data).encode()), "application/json")})


def _seed_check_items(c):
    data = [
        {"item_code": "TZ-001", "dimension": "总体合规性", "subcategory": "真实性",
         "description": "材料应加盖公章签字齐全", "check_method": "rule",
         "keywords": ["盖章", "签字"], "risk_level": "高"},
        {"item_code": "WZ-001", "dimension": "相关性核查", "subcategory": "组织层面",
         "description": "三重一大材料应明确决策事项范围", "check_method": "llm",
         "applicable_indicators": ["1-1-1"], "risk_level": "高"},
    ]
    c.post("/api/check-items/import",
           files={"file": ("ci.json", io.BytesIO(json.dumps(data).encode()), "application/json")})


# ============================================================
# 单位 + 任务
# ============================================================
def test_create_unit(admin_client):
    r = admin_client.post("/api/units", json={
        "name": "XX市卫生健康委员会", "code": "WJW", "level": "单位"
    })
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "XX市卫生健康委员会"


def test_create_task(admin_client):
    units = admin_client.get("/api/units").json()
    unit_id = units[0]["id"]
    r = admin_client.post("/api/tasks", json={
        "unit_id": unit_id, "name": "2025 年度核查", "eval_year": 2025,
    })
    assert r.status_code == 200, r.text
    task = r.json()
    assert task["status"] == "pending"
    assert task["eval_year"] == 2025


# ============================================================
# 上传 + 核查
# ============================================================
GOOD_MATERIAL = """关于印发XX单位三重一大决策制度的通知
财办发〔2025〕5号

第一章 总则
第一条 为规范本单位重大决策、重要干部任免、重要项目安排和大额资金使用的集体研究决策，
特制定本制度。
第二条 本制度适用于本单位重大事项决策。

第二章 决策事项范围
第三条 三重一大事项包括：
（一）重大决策事项；
（二）重要人事任免；
（三）重大项目安排；
（四）大额资金使用。

第三章 决策程序
第四条 会议召开前应提供书面材料。
第五条 会议应有过半数成员到会。

附则
本制度经办公会议审议通过，自2025年3月15日起施行。
负责人签字：张三  （单位公章）
"""

BAD_MATERIAL = """三重一大说明
本单位执行三重一大有关要求。
（征求意见稿）
"""


def test_upload_good_material_and_run(admin_client):
    """上传合规材料 → 核查 → AI 应较少检出（仅 LLM 不可用时跑刚性）。"""
    tasks = admin_client.get("/api/tasks").json()
    task_id = tasks[0]["id"]
    inds = admin_client.get("/api/indicators").json()
    indicator_id = next(i["id"] for i in inds if i["indicator_code"] == "1-1-1")

    files = {"file": ("三重一大制度.txt", io.BytesIO(GOOD_MATERIAL.encode("utf-8")), "text/plain")}
    r = admin_client.post(
        f"/api/tasks/{task_id}/materials",
        files=files,
        data={"indicator_id": str(indicator_id)},
    )
    assert r.status_code == 200, r.text
    m = r.json()
    # key_elements 应被自动抽取
    ke = json.loads(m["key_elements"])
    assert ke["has_official_seal"]  # 含「公章」关键词
    assert ke["has_signature"]
    assert ke["issue_year"] == 2025

    # 触发核查
    run = admin_client.post(f"/api/tasks/{task_id}/run")
    assert run.status_code == 200, run.text

    # 查看详情
    detail = admin_client.get(f"/api/tasks/{task_id}").json()
    assert detail["task"]["status"] in ("ai_done", "running")
    # 合规材料应无真实性问题
    real_issues = [f for f in detail["findings"]
                   if f["finding_type"] in ("真实性问题",)]
    assert real_issues == [], [f["description"] for f in real_issues]


def test_upload_bad_material_detects_issues(admin_client):
    """上传问题材料 → AI 应检出真实性 + 年度 + 草稿等问题。"""
    units = admin_client.get("/api/units").json()
    unit_id = units[0]["id"]
    task = admin_client.post("/api/tasks", json={
        "unit_id": unit_id, "name": "问题材料测试", "eval_year": 2025,
    }).json()
    task_id = task["id"]
    inds = admin_client.get("/api/indicators").json()
    indicator_id = inds[0]["id"]

    files = {"file": ("问题材料.txt", io.BytesIO(BAD_MATERIAL.encode("utf-8")), "text/plain")}
    admin_client.post(f"/api/tasks/{task_id}/materials",
                      files=files, data={"indicator_id": str(indicator_id)})
    admin_client.post(f"/api/tasks/{task_id}/run")

    detail = admin_client.get(f"/api/tasks/{task_id}").json()
    findings = detail["findings"]
    types = {f["finding_type"] for f in findings}
    # 应检出多类问题
    assert "真实性问题" in types or "正式性问题" in types or "年度一致性问题" in types
    assert len(findings) >= 3


# ============================================================
# 复核标注 + 整改闭环
# ============================================================
def test_review_finding(admin_client):
    """审查员对 finding 标注 confirmed/ignored/adjusted。"""
    # 找到任意一条 finding
    tasks = admin_client.get("/api/tasks").json()
    for t in tasks:
        detail = admin_client.get(f"/api/tasks/{t['id']}").json()
        if detail["findings"]:
            finding_id = detail["findings"][0]["id"]
            break
    else:
        pytest.skip("尚无 finding 可测试")
        return

    r = admin_client.post(f"/api/findings/{finding_id}/review", json={
        "status": "confirmed", "note": "已确认问题成立"
    })
    assert r.status_code == 200, r.text
    assert r.json()["review_status"] == "confirmed"
    assert "已确认" in r.json()["review_note"]


def test_rectification_workflow(admin_client):
    """提交整改 → 销号闭环。"""
    tasks = admin_client.get("/api/tasks").json()
    for t in tasks:
        detail = admin_client.get(f"/api/tasks/{t['id']}").json()
        if detail["findings"]:
            finding_id = detail["findings"][0]["id"]
            break
    else:
        pytest.skip("尚无 finding")
        return

    # 提交整改
    r1 = admin_client.post(f"/api/findings/{finding_id}/rectify",
                           json={"note": "已补盖公章并重新归档"})
    assert r1.status_code == 200, r1.text
    assert r1.json()["rectification_status"] == "submitted"

    # 销号
    r2 = admin_client.post(f"/api/findings/{finding_id}/resolve",
                           json={"note": "复核通过"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["rectification_status"] == "resolved"


def test_invalid_review_status_rejected(admin_client):
    tasks = admin_client.get("/api/tasks").json()
    detail = admin_client.get(f"/api/tasks/{tasks[0]['id']}").json()
    if not detail["findings"]:
        pytest.skip("尚无 finding")
        return
    fid = detail["findings"][0]["id"]
    r = admin_client.post(f"/api/findings/{fid}/review",
                          json={"status": "bogus", "note": "x"})
    assert r.status_code == 400


# ============================================================
# 任务定稿
# ============================================================
def test_finalize_task(admin_client):
    tasks = admin_client.get("/api/tasks").json()
    # 找一个 ai_done 状态的任务
    ai_done = [t for t in tasks if t["status"] == "ai_done"]
    if not ai_done:
        pytest.skip("尚无 ai_done 任务")
        return
    task_id = ai_done[0]["id"]
    r = admin_client.post(f"/api/tasks/{task_id}/finalize")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "finalized"
