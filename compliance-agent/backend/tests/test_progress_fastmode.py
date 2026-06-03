"""进度跟踪 + 快速模式 持久化与运行时验证。"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(auth_headers):
    from app.main import app
    from app.seeds.load_indicators_55 import load
    load(replace=True)
    with TestClient(app, headers=auth_headers) as c:
        yield c


def _create_unit(client, name):
    r = client.post("/api/units", json={"name": name, "code": "T"})
    assert r.status_code == 200
    return r.json()["id"]


def test_create_task_with_fast_mode(client):
    """fast_mode=True 应持久化，AuditTaskOut 应回显字段。"""
    uid = _create_unit(client, "FAST-A")
    r = client.post("/api/tasks", json={
        "unit_id": uid, "name": "fast", "eval_year": 2025,
        "scope": "all", "fast_mode": True,
    })
    assert r.status_code == 200, r.text
    task = r.json()
    assert task["fast_mode"] is True
    assert task["progress_current"] == 0
    assert task["progress_total"] == 0


def test_create_task_default_precise(client):
    """不传 fast_mode 默认为 false（精确模式）。"""
    uid = _create_unit(client, "FAST-B")
    r = client.post("/api/tasks", json={
        "unit_id": uid, "name": "precise", "eval_year": 2025, "scope": "all",
    })
    task = r.json()
    assert task["fast_mode"] is False


def test_progress_filled_after_run(client):
    """跑完一个任务，progress_current == progress_total（覆盖全部目标指标）。"""
    uid = _create_unit(client, "PROG-X")
    inds = client.get("/api/indicators").json()
    ids = [inds[0]["id"], inds[1]["id"]]

    task_id = client.post("/api/tasks", json={
        "unit_id": uid, "name": "p", "eval_year": 2025,
        "scope": "selected",
        "selected_indicator_ids": ids,
    }).json()["id"]

    # 上传一份材料 + 触发核查（eager 模式同步跑完）
    client.post(f"/api/tasks/{task_id}/materials",
                files={"file": ("x.txt", b"hello", "text/plain")})
    r = client.post(f"/api/tasks/{task_id}/run")
    assert r.json()["status"] == "ai_done"

    detail = client.get(f"/api/tasks/{task_id}").json()
    task = detail["task"]
    # 选了 2 个指标 → progress_total == 2，progress_current == 2
    assert task["progress_total"] == 2
    assert task["progress_current"] == 2
    assert task["progress_text"] in ("完成", "底稿生成中…")


def test_deepseek_thinking_mode_setter(monkeypatch):
    """DeepSeek client thinking_mode setter 支持 fast 别名（不依赖 openai 包）。"""
    import sys, types
    # 注入 fake openai 让导入通过
    fake_openai = types.ModuleType("openai")
    class FakeOpenAI:
        def __init__(self, **kw): pass
    fake_openai.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    from app.llm.deepseek import DeepSeekClient
    c = DeepSeekClient(api_key="x", model="m", thinking_mode="think_high")
    assert c.thinking_mode == "think_high"
    c.thinking_mode = "off"
    assert c.thinking_mode == "non_think"
    c.thinking_mode = "fast"
    assert c.thinking_mode == "non_think"
    c.thinking_mode = "think_max"
    assert c.thinking_mode == "think_max"
