"""材料 → 指标 智能匹配测试。"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(auth_headers):
    from app.main import app
    from app.seeds.load_indicators_55 import load
    load(replace=True)
    with TestClient(app, headers=auth_headers) as c:
        yield c


# ============================================================
# 单元：纯匹配函数
# ============================================================
def test_match_subcategory_by_prefix():
    from app.services.material_matcher import match_subcategory
    assert match_subcategory("204511346220/单位内部评价/（一）预算业务控制/预算管理办法.pdf") \
        == "（一）预算业务控制"
    assert match_subcategory("（四）资产控制/资产盘点表.xlsx") == "（四）资产控制"
    assert match_subcategory("(六)合同控制/合同登记台账.docx") == "（六）合同控制"  # 半角括号也兼容
    assert match_subcategory("合同管理制度.docx") == "（六）合同控制"
    assert match_subcategory("一份随便的文件.txt") is None


def test_match_indicator_unique(client):
    """指标级关键词精准匹配应返回唯一指标。"""
    from app.models import SessionLocal, Indicator
    from app.services.material_matcher import match_indicator
    db = SessionLocal()
    inds = db.query(Indicator).all()

    # 三重一大制度 → 应只命中 I-01
    hit = match_indicator(
        "204511346220/组织层面/三重一大决策制度.pdf", inds,
    )
    assert hit is not None
    assert hit.indicator_code == "I-01"

    # 票据 → I-23
    hit = match_indicator("（二）收支业务控制/票据管理台账.xlsx", inds)
    assert hit and hit.indicator_code == "I-23"

    # 工程变更 → I-41
    hit = match_indicator("（五）建设项目控制/工程变更审批单.docx", inds)
    assert hit and hit.indicator_code == "I-41"

    # 文件名只含子类，没有具体指标关键词 → 不绑定（返回 None）
    hit = match_indicator("（一）预算业务控制/不适用情况佐证材料.docx", inds)
    assert hit is None

    db.close()


# ============================================================
# 集成：upload_material 应自动绑定
# ============================================================
def test_upload_auto_bind(client):
    H = {}  # client 已经 prebound auth headers
    r = client.post("/api/units", json={"name": "MATCHER-A", "code": "M"})
    unit_id = r.json()["id"]
    t = client.post("/api/tasks", json={
        "unit_id": unit_id, "name": "auto-bind", "eval_year": 2025, "scope": "all",
    }).json()
    task_id = t["id"]

    # 文件名含三重一大制度 → 应自动绑定 I-01
    r = client.post(f"/api/tasks/{task_id}/materials",
                    files={"file": ("三重一大决策制度.txt", b"x", "text/plain")})
    assert r.status_code == 200
    m = r.json()
    # 拉指标库找出 I-01 的 id
    inds = client.get("/api/indicators").json()
    i01 = next(i for i in inds if i["indicator_code"] == "I-01")
    assert m["indicator_id"] == i01["id"]


def test_batch_auto_bind_existing(client):
    """已上传的未绑定材料用 batch auto-bind 接口能补绑。"""
    r = client.post("/api/units", json={"name": "MATCHER-BATCH", "code": "MB"})
    unit_id = r.json()["id"]
    task_id = client.post("/api/tasks", json={
        "unit_id": unit_id, "name": "batch", "eval_year": 2025, "scope": "all",
    }).json()["id"]

    # 先手动直接插入未绑定材料（绕过 upload 的自动绑定）
    from app.models import SessionLocal, Material
    db = SessionLocal()
    db.add_all([
        Material(task_id=task_id, indicator_id=None,
                 file_name="（一）预算业务控制/预算编制说明.docx",
                 storage_path="/tmp/x1", file_type="docx"),
        Material(task_id=task_id, indicator_id=None,
                 file_name="（六）合同控制/合同台账 2025.xlsx",
                 storage_path="/tmp/x2", file_type="xlsx"),
        Material(task_id=task_id, indicator_id=None,
                 file_name="一份说不出主题的杂项.txt",
                 storage_path="/tmp/x3", file_type="txt"),
    ])
    db.commit(); db.close()

    r = client.post(f"/api/tasks/{task_id}/materials/auto-bind")
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["checked"] == 3
    assert res["bound_now"] == 2     # 前两个能命中具体指标
    assert res["still_unbound"] == 1  # 杂项的不绑


# ============================================================
# orchestrator：共享池场景下应只挑相关材料
# ============================================================
def test_orchestrator_filters_unbound_by_subcategory():
    from app.models import SessionLocal, Indicator, Material
    from app.engine.orchestrator import _materials_for_indicator
    db = SessionLocal()
    inds = db.query(Indicator).all()
    indicator_predit = next(i for i in inds if i.indicator_code == "I-13")  # 预算制度建立

    # 模拟 3 份未绑定材料：1 份预算相关，2 份资产相关
    fake_mats = [
        Material(task_id=0, indicator_id=None,
                 file_name="（一）预算业务控制/制度.pdf", storage_path="", file_type="pdf"),
        Material(task_id=0, indicator_id=None,
                 file_name="（四）资产控制/盘点表.xlsx", storage_path="", file_type="xlsx"),
        Material(task_id=0, indicator_id=None,
                 file_name="（四）资产控制/印章登记.docx", storage_path="", file_type="docx"),
    ]
    out = _materials_for_indicator(fake_mats, indicator_predit)
    assert len(out) == 1
    assert "预算" in out[0].file_name
    db.close()
