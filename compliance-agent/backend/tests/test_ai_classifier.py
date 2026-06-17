"""AI 阅读材料 → 自动分类 测试。"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(auth_headers):
    from app.main import app
    from app.seeds.load_indicators_55 import load
    load(replace=True)
    with TestClient(app, headers=auth_headers) as c:
        yield c


def test_stub_llm_returns_empty_mapping(client):
    """stub 模式下 ai_classify_materials 应优雅返回空字典，不抛异常。"""
    from app.llm.stub import StubLLMClient
    from app.services.ai_material_classifier import ai_classify_materials
    from app.models import SessionLocal, AuditTask, Indicator, Material
    db = SessionLocal()
    indicators = db.query(Indicator).all()

    # 准备一份假材料（无须落任务）
    fake_mat = Material(task_id=0, indicator_id=None,
                        file_name="random.pdf", storage_path="/tmp/x",
                        file_type="pdf", parsed_text="hello world")
    res = ai_classify_materials(db, None, StubLLMClient(), [fake_mat], indicators)
    assert res == {}
    db.close()


def test_ai_classify_writes_mapping_to_db(client, monkeypatch):
    """mock LLM 返回固定 mapping → auto_bind 应把 indicator_id 写回。"""
    # 1) 准备任务 + 1 份未绑定材料
    r = client.post("/api/units", json={"name": "AI-CLS-1", "code": ""})
    unit_id = r.json()["id"]
    task_id = client.post("/api/tasks", json={
        "unit_id": unit_id, "name": "ai", "eval_year": 2025, "scope": "all",
    }).json()["id"]
    m = client.post(f"/api/tasks/{task_id}/materials",
                    files={"file": ("杂项.txt", b"x", "text/plain")}).json()
    mid = m["id"]
    # 文件名无关键词 → 不应被 keyword 绑定

    # 2) 让 get_llm_client 返回一个 mock，extract_json 给定 mapping
    class FakeLLM:
        thinking_mode = "off"
        def complete(self, *a, **kw): return ""
        def extract_json(self, prompt, system="", max_tokens=2048):
            return {"mappings": [{"material_id": mid, "indicator_code": "I-13",
                                  "reason": "fake test"}]}
    from app.llm import factory
    monkeypatch.setattr(factory, "get_llm_client", lambda db=None: FakeLLM())

    # 3) 调 auto-bind 接口
    r = client.post(f"/api/tasks/{task_id}/materials/auto-bind")
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["ai_used"] is True
    assert res["ai_bound"] == 1
    assert res["still_unbound"] == 0

    # 4) 验证材料 indicator_id 确实写回
    inds = client.get("/api/indicators").json()
    i13_id = next(i["id"] for i in inds if i["indicator_code"] == "I-13")
    materials = client.get(f"/api/tasks/{task_id}").json()["materials"]
    bound = [m for m in materials if m["id"] == mid][0]
    assert bound["indicator_id"] == i13_id


def test_keyword_first_then_ai(client, monkeypatch):
    """关键词能命中的不走 AI；剩余的才发给 LLM。"""
    r = client.post("/api/units", json={"name": "AI-CLS-2", "code": ""})
    unit_id = r.json()["id"]
    task_id = client.post("/api/tasks", json={
        "unit_id": unit_id, "name": "kw+ai", "eval_year": 2025, "scope": "all",
    }).json()["id"]
    # 上传 2 份：一份关键词能命中（I-01 三重一大），一份不能
    m1 = client.post(f"/api/tasks/{task_id}/materials",
                     files={"file": ("三重一大决策制度.txt", b"x", "text/plain")}).json()
    m2 = client.post(f"/api/tasks/{task_id}/materials",
                     files={"file": ("某份杂项材料.txt", b"x", "text/plain")}).json()
    # 第一份应已自动绑定（上传时关键词命中）
    assert m1["indicator_id"] is not None
    assert m2["indicator_id"] is None

    received_materials = []

    class FakeLLM:
        thinking_mode = "off"
        def complete(self, *a, **kw): return ""
        def extract_json(self, prompt, system="", max_tokens=2048):
            # 记录被 LLM 处理的材料 id
            import re
            for m in re.findall(r"材料 ID=(\d+)", prompt):
                received_materials.append(int(m))
            return {"mappings": [{"material_id": m2["id"], "indicator_code": "I-22",
                                  "reason": "fake"}]}
    from app.llm import factory
    monkeypatch.setattr(factory, "get_llm_client", lambda db=None: FakeLLM())

    r = client.post(f"/api/tasks/{task_id}/materials/auto-bind")
    res = r.json()
    # 没未绑定材料 m1 是已绑定的（上传时关键词绑定），auto-bind 只处理 m2
    assert res["checked"] == 1
    assert res["ai_bound"] == 1
    # LLM 只应该看到 m2（不应该看到 m1）
    assert m1["id"] not in received_materials
    assert m2["id"] in received_materials


def test_system_prompt_forbids_skipping():
    from app.services.ai_material_classifier import SYSTEM_PROMPT, _build_prompt

    # 系统提示词必须强制 LLM 给每份材料返回结果
    assert "禁止省略" in SYSTEM_PROMPT or "必须为每份材料" in SYSTEM_PROMPT
    assert "省略该材料" not in SYSTEM_PROMPT  # 旧的"实在判断不出来就省略"已删

    # 用户提示词同样强制全覆盖
    class FakeMat:
        def __init__(self, mid):
            self.id = mid
            self.file_name = f"f{mid}.pdf"
            self.parsed_text = "x"
    class FakeInd:
        def __init__(self, c):
            self.indicator_code = c
            self.subcategory = ""
            self.category = ""
            self.name = c
    p = _build_prompt([FakeMat(1), FakeMat(2)], [FakeInd("I-13"), FakeInd("I-55")])
    assert "必须覆盖所有传入的 material_id" in p
    assert "禁止遗漏" in p
    assert "省略" not in p


def test_ai_classify_retries_missing_materials():
    """LLM 第一次只返回部分映射 → 触发对漏的材料单独补问一次。"""
    from app.services.ai_material_classifier import ai_classify_materials
    from app.llm.base import LLMClient

    class FakeMat:
        def __init__(self, mid):
            self.id = mid
            self.file_name = f"f{mid}.pdf"
            self.parsed_text = "内容"

    class FakeInd:
        def __init__(self, c):
            self.indicator_code = c
            self.id = int(c.split("-")[1])
            self.subcategory = ""
            self.category = ""
            self.name = c

    inds = [FakeInd("I-01"), FakeInd("I-13"), FakeInd("I-55")]

    calls = []

    class FakeLLM(LLMClient):
        thinking_mode = "off"
        def complete(self, *a, **k): raise NotImplementedError
        def extract_json(self, prompt, system=None, max_tokens=8192):
            calls.append(prompt)
            # 第一次只返回 1/3 → 漏 2 个 → 应触发补单
            if len(calls) == 1:
                return {"mappings": [{"material_id": 1, "indicator_code": "I-01"}]}
            # 补单：把剩下的也给出来 + 一个不在 missing 里的 alien id（应被丢弃）
            return {"mappings": [
                {"material_id": 2, "indicator_code": "I-13"},
                {"material_id": 3, "indicator_code": "I-55"},
                {"material_id": 999, "indicator_code": "I-01"},
            ]}

    mats = [FakeMat(1), FakeMat(2), FakeMat(3)]
    result = ai_classify_materials(db=None, task=None, llm=FakeLLM(),
                                   materials=mats, indicators=inds)
    assert result == {1: 1, 2: 13, 3: 55}
    assert 999 not in result  # alien id 必须被 sub_batch 成员资格过滤掉
    assert len(calls) == 2  # 1 次批量 + 1 次补单
