"""端到端：上传 → 检查 → 台账 → 报告下载，全流程离线跑通。"""
import io

import pytest

from tests.samples import (
    BAD_BID, BAD_CONTRACT, BAD_EVAL, BAD_INSTITUTION, BAD_TENDER,
    BAD_INTERNAL_CONTROL, BAD_FINANCE_FINAL, BAD_ASSET, BAD_PERFORMANCE,
    CHAIN_BAD_BID, CHAIN_BAD_CONTRACT, CHAIN_BAD_EVAL,
    CHAIN_GOOD_BID, CHAIN_GOOD_CONTRACT, CHAIN_GOOD_EVAL, CHAIN_GOOD_TENDER,
    GOOD_BID, GOOD_CONTRACT, GOOD_EVAL, GOOD_INSTITUTION, GOOD_TENDER,
    GOOD_INTERNAL_CONTROL, GOOD_FINANCE_FINAL, GOOD_ASSET, GOOD_PERFORMANCE,
)


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.models import init_db

    init_db()
    with TestClient(app) as c:
        yield c


def _upload(client, text, name, category="合同", subcategory=""):
    files = {"file": (name, io.BytesIO(text.encode("utf-8")), "text/plain")}
    data = {"category": category, "subcategory": subcategory}
    resp = client.post("/api/documents", files=files, data=data)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_templates_lists_all_phase2(client):
    r = client.get("/api/templates")
    templates = {t["key"]: t for t in r.json()}
    assert "contract" in templates
    assert templates["contract"]["ready"] is True
    assert templates["contract"]["rigid_rules"] >= 5
    # Phase 2：内部制度 + 招采模板已就绪
    assert templates["institution"]["ready"] is True
    assert templates["institution"]["rigid_rules"] >= 6
    assert templates["procurement"]["ready"] is True
    assert templates["procurement"]["rigid_rules"] >= 13
    # 全部 7 套模板已就绪
    for key in ("internal_control", "finance_final", "asset", "performance"):
        assert templates[key]["ready"] is True, key
        assert templates[key]["rigid_rules"] >= 5, key


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


def test_procurement_tender_flags_and_passes(client):
    # 问题招标：缺编号/预算/截止时间/资格要求/评标办法
    bad_id = _upload(client, BAD_TENDER, "bad_tender.txt", category="采购招标", subcategory="招标")
    r = client.post("/api/checks", json={"document_id": bad_id, "template_key": "procurement"})
    assert r.status_code == 200, r.text
    rule_ids = {i["rule_id"] for i in r.json()["issues"]}
    assert "proc.tender.number" in rule_ids
    assert "proc.tender.budget" in rule_ids
    assert "proc.tender.deadline" in rule_ids

    # 合规招标：无刚性问题
    good_id = _upload(client, GOOD_TENDER, "good_tender.txt", category="采购招标", subcategory="招标")
    r2 = client.post("/api/checks", json={"document_id": good_id, "template_key": "procurement"})
    rigid = [i for i in r2.json()["issues"] if i["source"] == "rigid"]
    assert rigid == [], [i["description"] for i in rigid]


def test_procurement_bid_flags(client):
    bad_id = _upload(client, BAD_BID, "bad_bid.txt", category="采购招标", subcategory="投标")
    r = client.post("/api/checks", json={"document_id": bad_id, "template_key": "procurement"})
    rule_ids = {i["rule_id"] for i in r.json()["issues"]}
    assert "proc.bid.price" in rule_ids
    assert "proc.bid.validity" in rule_ids
    assert "proc.bid.signature" in rule_ids


def test_procurement_eval_flags(client):
    bad_id = _upload(client, BAD_EVAL, "bad_eval.txt", category="采购招标", subcategory="评标")
    r = client.post("/api/checks", json={"document_id": bad_id, "template_key": "procurement"})
    rule_ids = {i["rule_id"] for i in r.json()["issues"]}
    assert "proc.eval.committee" in rule_ids
    assert "proc.eval.result" in rule_ids
    assert "proc.eval.signature" in rule_ids


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


@pytest.mark.parametrize("template_key,good_text,bad_text,category", [
    ("internal_control", GOOD_INTERNAL_CONTROL, BAD_INTERNAL_CONTROL, "内控报告"),
    ("finance_final", GOOD_FINANCE_FINAL, BAD_FINANCE_FINAL, "财务报告"),
    ("asset", GOOD_ASSET, BAD_ASSET, "国有资产报告"),
    ("performance", GOOD_PERFORMANCE, BAD_PERFORMANCE, "绩效评价报告"),
])
def test_report_templates_end_to_end(client, template_key, good_text, bad_text, category):
    # bad → 多条疑点
    bad_id = _upload(client, bad_text, f"bad_{template_key}.txt", category=category)
    r = client.post("/api/checks", json={"document_id": bad_id, "template_key": template_key})
    assert r.status_code == 200, r.text
    bad_rigid = [i for i in r.json()["issues"] if i["source"] == "rigid"]
    assert len(bad_rigid) >= 3

    # good → 0 条刚性疑点
    good_id = _upload(client, good_text, f"good_{template_key}.txt", category=category)
    r2 = client.post("/api/checks", json={"document_id": good_id, "template_key": template_key})
    good_rigid = [i for i in r2.json()["issues"] if i["source"] == "rigid"]
    assert good_rigid == [], (template_key, [i["description"] for i in good_rigid])


def test_procurement_chain_flags_cross_file_issues(client):
    """Phase 3 端到端：上传 4 份招采链文档 → 跨文件比对。"""
    tender_id = _upload(client, CHAIN_GOOD_TENDER, "t.txt", category="采购招标", subcategory="招标")
    bid_id = _upload(client, CHAIN_BAD_BID, "b.txt", category="采购招标", subcategory="投标")
    eval_id = _upload(client, CHAIN_BAD_EVAL, "e.txt", category="采购招标", subcategory="评标")
    contract_id = _upload(client, CHAIN_BAD_CONTRACT, "c.txt", category="合同")

    r = client.post("/api/chain-checks", json={
        "tender_doc_id": tender_id,
        "bid_doc_id": bid_id,
        "eval_doc_id": eval_id,
        "contract_doc_id": contract_id,
    })
    assert r.status_code == 200, r.text
    task = r.json()
    assert task["status"] == "done"
    rule_ids = {i["rule_id"] for i in task["issues"]}
    assert "chain.price_over_budget" in rule_ids
    assert "chain.contract_party_vs_winner" in rule_ids
    assert "chain.contract_amount_vs_bid" in rule_ids
    assert "chain.committee_size" in rule_ids


def test_procurement_chain_consistent_no_inconsistency(client):
    tender_id = _upload(client, CHAIN_GOOD_TENDER, "t2.txt", category="采购招标", subcategory="招标")
    bid_id = _upload(client, CHAIN_GOOD_BID, "b2.txt", category="采购招标", subcategory="投标")
    eval_id = _upload(client, CHAIN_GOOD_EVAL, "e2.txt", category="采购招标", subcategory="评标")
    contract_id = _upload(client, CHAIN_GOOD_CONTRACT, "c2.txt", category="合同")

    r = client.post("/api/chain-checks", json={
        "tender_doc_id": tender_id,
        "bid_doc_id": bid_id,
        "eval_doc_id": eval_id,
        "contract_doc_id": contract_id,
    })
    task = r.json()
    inconsistency = [i for i in task["issues"] if i["rule_id"] != "chain.completeness"]
    assert inconsistency == [], [i["description"] for i in inconsistency]


def test_chain_check_rejects_empty_input(client):
    r = client.post("/api/chain-checks", json={})
    assert r.status_code == 400


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
