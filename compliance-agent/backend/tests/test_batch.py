"""批量上传 + 批次管理测试。"""
import io

import pytest

from app.services.classifier import classify
from app.parsers.txt_parser import parse_text_content
from tests.samples import (
    BAD_CONTRACT,
    CHAIN_GOOD_BID,
    CHAIN_GOOD_CONTRACT,
    CHAIN_GOOD_EVAL,
    CHAIN_GOOD_TENDER,
    GOOD_FINANCE_FINAL,
    GOOD_INSTITUTION,
    GOOD_INTERNAL_CONTROL,
    GOOD_PERFORMANCE,
)


@pytest.fixture(scope="module")
def client(auth_headers):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models import init_db
    init_db()
    with TestClient(app, headers=auth_headers) as c:
        yield c


# ─── 自动分类器单元测试 ──────────────────────────────
def test_classify_by_filename():
    c = classify("XX项目招标文件.docx", None)
    assert c.category == "采购招标"
    assert c.subcategory == "招标"
    assert c.method == "filename"


def test_classify_by_filename_contract():
    c = classify("采购合同.docx", None)
    assert c.category == "合同"


def test_classify_by_filename_institution():
    c = classify("财务管理办法.docx", None)
    assert c.category == "内部制度"


def test_classify_by_content_when_filename_neutral():
    parsed = parse_text_content(BAD_CONTRACT, "unnamed.txt")
    c = classify("unnamed.txt", parsed)
    assert c.category == "合同"
    assert c.method == "content"


def test_classify_content_internal_control():
    parsed = parse_text_content(GOOD_INTERNAL_CONTROL, "x.txt")
    c = classify("x.txt", parsed)
    assert c.category == "内控报告"


def test_classify_fallback_to_other():
    parsed = parse_text_content("一些与任何分类都无关的随机文字。", "x.txt")
    c = classify("x.txt", parsed)
    assert c.category == "其他佐证资料"
    assert c.method == "fallback"


# ─── 批次 CRUD ────────────────────────────────────────
def test_create_batch_and_list(client):
    r = client.post("/api/batches", json={
        "name": "2026年度迎检批次",
        "project_id": "Q1-2026",
        "year": "2026",
        "department": "某某局",
    })
    assert r.status_code == 200, r.text
    batch = r.json()
    assert batch["name"] == "2026年度迎检批次"

    r2 = client.get("/api/batches")
    assert r2.status_code == 200
    assert any(b["id"] == batch["id"] for b in r2.json())


def test_unauth_cannot_create_batch():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        r = c.post("/api/batches", json={"name": "x"})
        assert r.status_code == 401


# ─── 批量上传 + 自动分类 + 自动检查 ───────────────────
def _make_files(samples):
    """samples: list of (filename, text) → multipart files."""
    return [("files", (name, io.BytesIO(text.encode("utf-8")), "text/plain"))
            for name, text in samples]


def test_batch_upload_classifies_and_runs_checks(client):
    # 创建批次
    batch = client.post("/api/batches",
                        json={"name": "合规项目-2026"}).json()
    bid = batch["id"]

    # 一次性上传 3 份不同分类的文档
    files = _make_files([
        ("制度-财务管理办法.txt", GOOD_INSTITUTION),
        ("问题合同.txt", BAD_CONTRACT),
        ("某某项目招标文件.txt", CHAIN_GOOD_TENDER),
    ])
    r = client.post(f"/api/batches/{bid}/upload", files=files)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 3

    by_name = {i["file_name"]: i for i in body["items"]}
    assert by_name["制度-财务管理办法.txt"]["category"] == "内部制度"
    assert by_name["问题合同.txt"]["category"] == "合同"
    assert by_name["某某项目招标文件.txt"]["category"] == "采购招标"
    # 招标子类应被识别
    assert by_name["某某项目招标文件.txt"]["subcategory"] == "招标"

    # 全部应自动触发了检查任务（eager 模式下立即完成）
    for it in body["items"]:
        assert it["check_task_id"] is not None
        # 验证任务确实存在且已 done
        task = client.get(f"/api/checks/{it['check_task_id']}").json()
        assert task["status"] == "done"


def test_batch_upload_unsupported_format_recorded_in_item_error(client):
    batch = client.post("/api/batches", json={"name": "格式测试"}).json()
    files = [("files", ("readme.xyz", io.BytesIO(b"x"), "text/plain"))]
    r = client.post(f"/api/batches/{batch['id']}/upload", files=files)
    assert r.status_code == 200
    assert "不支持" in r.json()["items"][0]["error"]


def test_batch_upload_rejects_empty(client):
    batch = client.post("/api/batches", json={"name": "空"}).json()
    r = client.post(f"/api/batches/{batch['id']}/upload", files=[])
    # FastAPI 校验：File(...) 至少一个 → 422
    assert r.status_code in (400, 422)


# ─── 联动链自动触发 ───────────────────────────────────
def test_batch_triggers_procurement_chain_when_link_complete(client):
    batch = client.post("/api/batches", json={"name": "招采链批次"}).json()
    bid = batch["id"]
    # 上传招标 + 投标 + 评标 + 合同 凑齐招采链
    r = client.post(f"/api/batches/{bid}/upload", files=_make_files([
        ("招标文件.txt", CHAIN_GOOD_TENDER),
        ("投标文件.txt", CHAIN_GOOD_BID),
        ("评标报告.txt", CHAIN_GOOD_EVAL),
        ("采购合同.txt", CHAIN_GOOD_CONTRACT),
    ]))
    body = r.json()
    assert "procurement" in body["triggered_chains"]
    chain_id = body["triggered_chains"]["procurement"]

    chain_task = client.get(f"/api/chain-checks/{chain_id}").json()
    assert chain_task["chain_type"] == "procurement"
    assert chain_task["status"] == "done"


def test_batch_triggers_finance_chain(client):
    batch = client.post("/api/batches", json={"name": "财务链批次"}).json()
    bid = batch["id"]
    # 财务 + 决算 凑齐财务链（>=2 个环节）
    r = client.post(f"/api/batches/{bid}/upload", files=_make_files([
        ("财务报告.txt", GOOD_FINANCE_FINAL),
        ("部门决算报告.txt", GOOD_FINANCE_FINAL.replace("财务报告", "部门决算")),
    ]))
    body = r.json()
    assert "finance" in body["triggered_chains"]


def test_batch_triggers_report_chain(client):
    batch = client.post("/api/batches", json={"name": "报告链批次"}).json()
    bid = batch["id"]
    r = client.post(f"/api/batches/{bid}/upload", files=_make_files([
        ("内控报告.txt", GOOD_INTERNAL_CONTROL),
        ("绩效评价报告.txt", GOOD_PERFORMANCE),
    ]))
    body = r.json()
    assert "report" in body["triggered_chains"]


def test_batch_does_not_trigger_chain_with_single_doc(client):
    batch = client.post("/api/batches", json={"name": "单文档"}).json()
    bid = batch["id"]
    r = client.post(f"/api/batches/{bid}/upload", files=_make_files([
        ("仅招标.txt", CHAIN_GOOD_TENDER),
    ]))
    # 只有一个环节，不应触发任何链
    assert r.json()["triggered_chains"] == {}


# ─── 批次详情 + 汇总 ──────────────────────────────────
def test_batch_detail_summary(client):
    batch = client.post("/api/batches", json={"name": "详情测试"}).json()
    bid = batch["id"]
    client.post(f"/api/batches/{bid}/upload", files=_make_files([
        ("合同.txt", BAD_CONTRACT),
        ("制度.txt", GOOD_INSTITUTION),
    ]))
    r = client.get(f"/api/batches/{bid}")
    assert r.status_code == 200
    detail = r.json()
    s = detail["summary"]
    assert s["documents_total"] == 2
    assert "合同" in s["documents_by_category"]
    assert "内部制度" in s["documents_by_category"]
    assert len(s["check_tasks"]) == 2
    # BAD_CONTRACT 应贡献疑点
    assert s["issues_total"] >= 5


# ─── 重新触发链路 ─────────────────────────────────────
def test_manual_retrigger(client):
    batch = client.post("/api/batches", json={"name": "重新触发"}).json()
    bid = batch["id"]
    client.post(f"/api/batches/{bid}/upload", files=_make_files([
        ("招标.txt", CHAIN_GOOD_TENDER),
        ("合同.txt", CHAIN_GOOD_CONTRACT),
    ]))
    r = client.post(f"/api/batches/{bid}/retrigger")
    assert r.status_code == 200
    assert "procurement" in r.json()["triggered"]


# ─── 审计日志：批次操作均被记录 ───────────────────────
def test_batch_operations_logged(client):
    # 创建一个批次并上传，看审计日志
    batch = client.post("/api/batches", json={"name": "审计批次"}).json()
    client.post(f"/api/batches/{batch['id']}/upload", files=_make_files([
        ("合同.txt", BAD_CONTRACT),
    ]))
    logs = client.get("/api/audit-logs").json()
    actions = {l["action"] for l in logs}
    assert "batch.create" in actions
    assert "batch.enqueue_check" in actions
