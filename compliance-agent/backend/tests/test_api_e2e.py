"""端到端：上传 → 检查 → 台账 → 报告下载，全流程离线跑通。"""
import io

import pytest

from tests.samples import BAD_CONTRACT, BAD_INSTITUTION, GOOD_CONTRACT, GOOD_INSTITUTION


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.models import init_db

    init_db()
    with TestClient(app) as c:
        yield c


def _upload(client, text, name):
    files = {"file": (name, io.BytesIO(text.encode("utf-8")), "text/plain")}
    resp = client.post("/api/documents", files=files, data={"category": "合同"})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_templates_lists_contract_and_institution(client):
    r = client.get("/api/templates")
    templates = {t["key"]: t for t in r.json()}
    assert "contract" in templates
    assert templates["contract"]["ready"] is True
    assert templates["contract"]["rigid_rules"] >= 5
    # Phase 2：内部制度模板已就绪
    assert templates["institution"]["ready"] is True
    assert templates["institution"]["rigid_rules"] >= 6


def test_institution_check_flags_and_passes(client):
    bad_id = _upload(client, BAD_INSTITUTION, "bad_inst.txt")
    r = client.post("/api/checks", json={"document_id": bad_id, "template_key": "institution"})
    assert r.status_code == 200, r.text
    rule_ids = {i["rule_id"] for i in r.json()["issues"]}
    assert "institution.doc_number" in rule_ids
    assert "institution.effective_date" in rule_ids
    assert "institution.required_sections" in rule_ids

    good_id = _upload(client, GOOD_INSTITUTION, "good_inst.txt")
    r2 = client.post("/api/checks", json={"document_id": good_id, "template_key": "institution"})
    good_rigid = [i for i in r2.json()["issues"] if i["source"] == "rigid"]
    assert good_rigid == [], [i["description"] for i in good_rigid]


def test_bad_contract_flags_issues(client):
    doc_id = _upload(client, BAD_CONTRACT, "bad.txt")
    r = client.post("/api/checks", json={"document_id": doc_id, "template_key": "contract"})
    assert r.status_code == 200, r.text
    task = r.json()
    assert task["status"] == "done"

    rule_ids = {i["rule_id"] for i in task["issues"]}
    # 金额不一致、缺编号、缺违约/期限条款、缺签章 应被检出
    assert "contract.amount_consistency" in rule_ids
    assert "contract.number" in rule_ids
    assert "contract.seal" in rule_ids
    assert "contract.required_clauses" in rule_ids


def test_good_contract_fewer_issues_and_report(client):
    doc_id = _upload(client, GOOD_CONTRACT, "good.txt")
    r = client.post("/api/checks", json={"document_id": doc_id, "template_key": "contract"})
    task = r.json()
    rule_ids = {i["rule_id"] for i in task["issues"]}
    # 合规合同不应出现金额不一致与缺签章
    assert "contract.amount_consistency" not in rule_ids
    assert "contract.seal" not in rule_ids

    # 报告导出
    rep = client.get(f"/api/checks/{task['id']}/report")
    assert rep.status_code == 200
    assert rep.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert len(rep.content) > 0
