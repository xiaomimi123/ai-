"""材料 → 指标 智能匹配测试。"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(auth_headers):
    from app.main import app
    from app.seeds.load_indicators_55 import load
    load(replace=True)
    # v1.2: 给关键 indicator 加 required_materials 让新 matcher 能匹配
    from app.models import SessionLocal, Indicator
    import json as _json
    _hints = {
        "I-01": ["三重一大决策制度", "三重一大议事规则"],
        "I-23": ["票据管理台账", "票据管理"],
        "I-41": ["工程变更审批单", "工程变更"],
    }
    with SessionLocal() as _db:
        for code, kws in _hints.items():
            ind = _db.query(Indicator).filter_by(indicator_code=code).first()
            if ind:
                ind.required_materials = _json.dumps(kws, ensure_ascii=False)
        _db.commit()
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
def test_patch_material_bind(client):
    """PATCH /tasks/{id}/materials/{mid} 改绑材料指标。"""
    r = client.post("/api/units", json={"name": "PATCH-A", "code": ""})
    unit_id = r.json()["id"]
    task_id = client.post("/api/tasks", json={
        "unit_id": unit_id, "name": "patch", "eval_year": 2025, "scope": "all",
    }).json()["id"]

    # 上传一份无关键词的材料 → 不会自动绑定
    m = client.post(f"/api/tasks/{task_id}/materials",
                    files={"file": ("杂项.txt", b"x", "text/plain")}).json()
    assert m["indicator_id"] in (None,)

    inds = client.get("/api/indicators").json()
    target = next(i for i in inds if i["indicator_code"] == "I-13")

    # 改绑到 I-13
    r = client.patch(f"/api/tasks/{task_id}/materials/{m['id']}",
                     json={"indicator_id": target["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["indicator_id"] == target["id"]

    # 解绑
    r = client.patch(f"/api/tasks/{task_id}/materials/{m['id']}",
                     json={"indicator_id": None})
    assert r.status_code == 200
    assert r.json()["indicator_id"] is None

    # 改到不存在的指标 → 400
    r = client.patch(f"/api/tasks/{task_id}/materials/{m['id']}",
                     json={"indicator_id": 999999})
    assert r.status_code == 400


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


def test_fallback_indicator_for_subcategory_returns_canonical_code():
    from app.services.material_matcher import fallback_indicator_for_subcategory

    class FakeInd:
        def __init__(self, code, sub):
            self.indicator_code = code
            self.subcategory = sub
            self.category = sub
            self.name = code

    inds = [
        FakeInd("I-13", "（一）预算业务控制"),
        FakeInd("I-15", "（一）预算业务控制"),
        FakeInd("I-44", "（六）合同控制"),
        FakeInd("I-55", "补充指标"),
    ]
    assert fallback_indicator_for_subcategory("（一）预算业务控制", inds).indicator_code == "I-13"
    assert fallback_indicator_for_subcategory("（六）合同控制", inds).indicator_code == "I-44"
    # 子类不在 fallback 表 → 退到 I-55
    assert fallback_indicator_for_subcategory("（七）某未知子类", inds).indicator_code == "I-55"
    # 连 I-55 都没有 → None
    no_i55 = [FakeInd("I-13", "（一）预算业务控制")]
    assert fallback_indicator_for_subcategory("（七）某未知子类", no_i55) is None


def test_fallback_falls_through_to_i55_when_target_code_missing():
    """子类在 SUBCATEGORY_FALLBACK 表里，但其 code 在 indicators 集合中不存在 → 退到 I-55。

    生产环境最可能命中的路径：法规/指标库部分加载，I-13 缺失但 I-55 在。
    """
    from app.services.material_matcher import fallback_indicator_for_subcategory

    class FakeInd:
        def __init__(self, code, sub):
            self.indicator_code = code
            self.subcategory = sub
            self.category = sub
            self.name = code

    # "内部监督" 在 SUBCATEGORY_FALLBACK 表 → I-53；但 indicators 只有 I-55
    partial = [FakeInd("I-55", "补充指标")]
    result = fallback_indicator_for_subcategory("内部监督", partial)
    assert result is not None and result.indicator_code == "I-55"


def test_fallback_returns_none_for_empty_subcategory():
    """空字符串 / None 输入应直接返回 None，而不是兜底到 I-55。

    防止 caller 传空 subcategory 时误绑材料到补充指标。
    """
    from app.services.material_matcher import fallback_indicator_for_subcategory

    class FakeInd:
        def __init__(self, code, sub):
            self.indicator_code = code
            self.subcategory = sub
            self.category = sub
            self.name = code

    inds = [FakeInd("I-55", "补充指标")]
    assert fallback_indicator_for_subcategory("", inds) is None
    assert fallback_indicator_for_subcategory(None, inds) is None


import json as _json


def _fake_ind(code, sub, materials):
    """轻量 Indicator 替身（带 required_materials JSON）。"""
    class FakeInd:
        pass
    f = FakeInd()
    f.id = int(code.split("-")[1]) if "-" in code else 0
    f.indicator_code = code
    f.subcategory = sub
    f.category = sub
    f.name = code
    f.required_materials = _json.dumps(materials, ensure_ascii=False)
    return f


def test_match_indicator_by_content_matches_file_name():
    from app.services.material_matcher import match_indicator_by_content
    inds = [
        _fake_ind("I-04", "组织层面", ["岗位职责", "岗位说明书"]),
        _fake_ind("I-13", "（一）预算业务控制", ["预算管理办法", "预算编制"]),
    ]
    hit = match_indicator_by_content("岗位说明书 2025.docx", "", inds)
    assert hit is not None and hit.indicator_code == "I-04"


def test_match_indicator_by_content_matches_parsed_text():
    """文件名无关键词，但 parsed_text 前 1000 字含关键词 → 命中。"""
    from app.services.material_matcher import match_indicator_by_content
    inds = [
        _fake_ind("I-13", "（一）预算业务控制", ["预算编制说明"]),
    ]
    hit = match_indicator_by_content(
        "untitled.pdf",
        "本制度规定预算编制说明的格式...",
        inds,
    )
    assert hit is not None and hit.indicator_code == "I-13"


def test_match_indicator_by_content_picks_highest_score():
    """多指标都命中 → 取关键词命中数最多的。"""
    from app.services.material_matcher import match_indicator_by_content
    inds = [
        _fake_ind("I-04", "组织层面", ["岗位"]),
        _fake_ind("I-13", "（一）预算业务控制", ["预算", "预算编制", "预算公开"]),
    ]
    # haystack 命中 I-04 1 次，I-13 3 次
    hit = match_indicator_by_content(
        "岗位预算编制说明.pdf",
        "预算编制 + 预算公开",
        inds,
    )
    assert hit.indicator_code == "I-13"


def test_match_indicator_by_content_returns_none_when_no_match():
    from app.services.material_matcher import match_indicator_by_content
    inds = [
        _fake_ind("I-04", "组织层面", ["岗位职责"]),
    ]
    hit = match_indicator_by_content("一份完全无关的文件.txt", "内容也无关", inds)
    assert hit is None


def test_match_indicator_by_content_truncates_text_to_1000_chars():
    """parsed_text 超 1000 字时 → 1000 字之后的关键词不参与匹配。"""
    from app.services.material_matcher import match_indicator_by_content
    inds = [_fake_ind("I-04", "组织层面", ["岗位职责"])]
    pad = "x" * 1500
    # 关键词在 1500 字符之后 → 不该命中
    hit = match_indicator_by_content("无关.pdf", pad + "岗位职责", inds)
    assert hit is None


def test_match_indicator_legacy_wrapper_delegates_to_by_content():
    """老 match_indicator(file_name, indicators) 调用仍能用，内部 delegate 到 by_content。"""
    from app.services.material_matcher import match_indicator
    inds = [_fake_ind("I-04", "组织层面", ["岗位说明书"])]
    hit = match_indicator("某某岗位说明书.docx", inds)
    assert hit is not None and hit.indicator_code == "I-04"
