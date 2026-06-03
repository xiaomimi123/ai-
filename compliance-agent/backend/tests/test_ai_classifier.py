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
