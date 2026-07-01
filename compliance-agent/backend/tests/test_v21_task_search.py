"""v2.1 任务列表搜索框：验证 HTML 里搜索元素存在。

前端行为的单元测试项目当前无对应框架，本条测试锁住 spec 中约定的
DOM id，避免后续误删或改名导致 app.js 里绑定的事件失效。
"""
from __future__ import annotations

from pathlib import Path


INDEX_HTML = (
    Path(__file__).resolve().parents[2] / "frontend" / "index.html"
)


def test_task_search_input_present():
    """index.html 必须包含 v2.1 搜索输入框元素。"""
    assert INDEX_HTML.exists(), f"未找到 {INDEX_HTML}"
    text = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="task-search"' in text, (
        "index.html 未看到 id=\"task-search\" 搜索输入框"
    )
    assert 'id="task-search-count"' in text, (
        "index.html 未看到 id=\"task-search-count\" 计数提示元素"
    )
    assert 'id="task-search-clear"' in text, (
        "index.html 未看到 id=\"task-search-clear\" 清空按钮"
    )
