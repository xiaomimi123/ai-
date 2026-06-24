"""v1.5 上传后自动形式审查 → Finding 测试。"""
import io
import json
from unittest.mock import patch

from fastapi.testclient import TestClient


def _make_task(c, headers, suffix=""):
    r = c.post("/api/units", json={"name": f"FR-{suffix}", "code": "FR"},
               headers=headers)
    unit_id = r.json()["id"]
    r = c.post("/api/tasks",
               json={"unit_id": unit_id, "name": f"fr {suffix}",
                     "eval_year": 2025, "scope": "all"},
               headers=headers)
    return r.json()["id"]


def _seed_one_indicator(client, headers, code="I-44", subcategory="（六）合同控制",
                        name="合同制度", keywords=("合同管理制度",)):
    """通过 /api/indicators/import 接口塞一个指标（避免直接动 DB）。"""
    items = [{
        "indicator_code": code, "name": name,
        "category": "经济活动", "subcategory": subcategory,
        "max_score": 2,
        "required_materials": list(keywords),
    }]
    files = {"file": ("seed.json",
                      io.BytesIO(json.dumps(items).encode("utf-8")),
                      "application/json")}
    r = client.post("/api/indicators/import", files=files, headers=headers)
    assert r.status_code in (200, 201), r.text


def test_auto_finding_created_when_seal_missing(auth_headers):
    """has_official_seal=False → 创建 finding_type=形式性 severity=中。"""
    from app.main import app
    from app.services.audit_service import _create_form_review_findings
    from app.models import SessionLocal, Material, AuditTask, Finding
    with TestClient(app) as c:
        _seed_one_indicator(c, auth_headers, "I-FR-1", "（六）合同控制",
                            "合同制度FR1", ("FR1合同管理制度",))
        t = _make_task(c, auth_headers, "1")
        files = {"file": ("FR1合同管理制度.txt", io.BytesIO(b"x"), "text/plain")}
        r = c.post(f"/api/tasks/{t}/materials",
                   files=files, headers=auth_headers)
        mid = r.json()["id"]
    with SessionLocal() as s:
        m = s.get(Material, mid)
        task = s.get(AuditTask, m.task_id)
        ke = {"has_official_seal": False, "issue_date": "2025-01-01",
              "document_number": "X〔2025〕1号", "is_draft": False}
        n_created = _create_form_review_findings(s, task, m, ke)
        s.commit()
    assert n_created >= 1
    with SessionLocal() as s2:
        findings = (s2.query(Finding)
                      .filter(Finding.material_id == mid)
                      .all())
    seal_findings = [f for f in findings if "公章" in f.description]
    assert len(seal_findings) == 1
    assert seal_findings[0].finding_type == "形式性"
    assert seal_findings[0].severity == "中"
    assert seal_findings[0].source == "rule"


def test_auto_finding_skipped_when_disabled(auth_headers):
    """AppSetting auto_form_review_enabled=false → upload 后不创建 finding。"""
    from app.main import app
    from app.services.settings_service import set_auto_form_review_enabled
    from app.models import SessionLocal, Material, Finding
    with TestClient(app) as c:
        with SessionLocal() as s:
            set_auto_form_review_enabled(s, False)
        _seed_one_indicator(c, auth_headers, "I-FR-2", "（六）合同控制",
                            "合同制度FR2", ("FR2合同管理制度",))
        t = _make_task(c, auth_headers, "2")
        files = {"file": ("FR2合同管理制度.txt", io.BytesIO(b"y"), "text/plain")}
        r = c.post(f"/api/tasks/{t}/materials", files=files, headers=auth_headers)
        mid = r.json()["id"]
    with SessionLocal() as s2:
        fs = s2.query(Finding).filter(Finding.material_id == mid).all()
        set_auto_form_review_enabled(s2, True)
    assert len(fs) == 0


def test_auto_finding_no_create_when_no_indicator(auth_headers):
    """材料未绑定 indicator → 不创建 finding（避免孤儿）。"""
    from app.services.audit_service import _create_form_review_findings
    from app.models import SessionLocal, Material, AuditTask, Finding
    from app.main import app
    with TestClient(app) as c:
        t = _make_task(c, auth_headers, "3")
        files = {"file": ("无关键词杂项.txt", io.BytesIO(b"z"), "text/plain")}
        r = c.post(f"/api/tasks/{t}/materials", files=files, headers=auth_headers)
        mid = r.json()["id"]
    with SessionLocal() as s:
        m = s.get(Material, mid)
        task = s.get(AuditTask, m.task_id)
        m.indicator_id = None
        s.commit()
        ke = {"has_official_seal": False}
        n = _create_form_review_findings(s, task, m, ke)
    assert n == 0


def test_auto_finding_draft_severity_high(auth_headers):
    """is_draft=True → severity=高。"""
    from app.services.audit_service import _create_form_review_findings
    from app.models import SessionLocal, Material, AuditTask, Finding
    from app.main import app
    with TestClient(app) as c:
        _seed_one_indicator(c, auth_headers, "I-FR-4", "（六）合同控制",
                            "合同制度FR4", ("FR4合同管理制度",))
        t = _make_task(c, auth_headers, "4")
        files = {"file": ("FR4合同管理制度.txt", io.BytesIO(b"w"), "text/plain")}
        r = c.post(f"/api/tasks/{t}/materials", files=files, headers=auth_headers)
        mid = r.json()["id"]
    with SessionLocal() as s:
        m = s.get(Material, mid)
        task = s.get(AuditTask, m.task_id)
        ke = {"has_official_seal": True, "issue_date": "2025-01-01",
              "document_number": "X〔2025〕1号", "is_draft": True}
        _create_form_review_findings(s, task, m, ke)
        s.commit()
        fs = s.query(Finding).filter(Finding.material_id == mid,
                                     Finding.description.like("%草稿%")).all()
    assert len(fs) == 1
    assert fs[0].severity == "高"


def test_auto_finding_does_not_break_upload_on_exception(auth_headers):
    """_create_form_review_findings 抛异常 → upload_material 不抛错。"""
    from app.main import app
    from unittest.mock import patch
    with TestClient(app) as c:
        _seed_one_indicator(c, auth_headers, "I-FR-5", "（六）合同控制",
                            "合同制度FR5", ("FR5合同管理制度",))
        t = _make_task(c, auth_headers, "5")
        with patch("app.services.audit_service._create_form_review_findings",
                   side_effect=RuntimeError("simulated")):
            files = {"file": ("FR5合同管理制度.txt", io.BytesIO(b"v"), "text/plain")}
            r = c.post(f"/api/tasks/{t}/materials",
                       files=files, headers=auth_headers)
            assert r.status_code == 200, r.text
