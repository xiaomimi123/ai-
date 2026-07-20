# v2.13 工作台单位核查进度总览 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 工作台加"单位核查进度总览"card，展示 5 档互斥单位统计（总数/未建任务/建任务未上传材料/有材料未完成/已完成核查），中间 3 档可点击展开单位列表。

**Architecture:** 后端一次 outerjoin 聚合 SQL 出 (task_count, material_count, finalized_count) per unit → Python 分档；summary 端点直接返 5 数字，detail 端点按 category 过滤懒加载。前端工作台新 card，5 大数字 + 3 个可点▼展开表格；State 缓存 detail 秒回。

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy + pytest（backend）; Vanilla JS + fetch/api helper（frontend）.

## Global Constraints

- 5 档互斥判定优先级：`no_task > completed > has_task_no_material > in_progress_with_material`
  - `no_task`: task_count == 0
  - `completed`: finalized_count == task_count（即使 material_count == 0 也算完成）
  - `has_task_no_material`: material_count == 0（未完成前提下）
  - `in_progress_with_material`: 剩余
- Router prefix `/api/dashboard`，tags `["dashboard"]`
- 2 端点：`GET /unit-stats/summary` 返 dict of 5 int；`GET /unit-stats/detail?category=<name>` 返 list of dict
- `completed` category 不提供 detail —— detail 端点 400 if category not in {no_task, has_task_no_material, in_progress_with_material}
- 详情表 row 结构：`{id, name, total_tasks, finalized_tasks, material_count}` 全 category 一致，前端按 category 选列显示
- 前端 card 位置：dashboard `grid-2` 关闭 `</div>` 之后、`<div class="card mt-6 fade-in fade-in-4">` "五维核查范式"或"批量导出" card 之前
- Detail 表按 `name` 升序返回
- `esc()` on 所有 user data（单位名可能含特殊字符）
- Cache buster `?v=2.11` → `?v=2.13`（跳过 v2.12 无前端）
- `State.unitStatsDetailCache = {}` 缓存懒加载结果
- 后端改动 cp 到 backend + worker + enrich_worker 三容器（worker 不用 dashboard 端点但保持代码一致）
- 中文注释 + commit 消息

---

## File Structure

| 文件 | 责任 | 状态 |
|---|---|---|
| `compliance-agent/backend/app/api/dashboard_routes.py` | 新 router：`_base_subquery` 聚合 SQL + `_categorize` 分档 + summary + detail 端点 | 新建 |
| `compliance-agent/backend/app/main.py` | import + `include_router(dashboard_router)` 一行 | 修改 |
| `compliance-agent/backend/tests/test_dashboard_unit_stats.py` | 6 条 pytest：summary 五档准确 / no_task detail / has_task_no_material detail / in_progress detail / completed 无 detail 返 400 / 空库返 0 | 新建 |
| `compliance-agent/frontend/index.html` | 加 card + `?v=2.11` → `?v=2.13` | 修改 |
| `compliance-agent/frontend/app.js` | `renderUnitProgressCard` + `_upStatBox` + `_toggleUnitProgressDetail` + State 缓存字段 + loadDashboard 末尾调用 | 修改 |
| `compliance-agent/README.md` | v2.13 更新日志 | 修改 |

---

## Task 1: 后端 dashboard_routes + main.py 注册 + 6 pytest

**Files:**
- Create: `compliance-agent/backend/app/api/dashboard_routes.py`
- Modify: `compliance-agent/backend/app/main.py`（import + include_router 一行）
- Test: `compliance-agent/backend/tests/test_dashboard_unit_stats.py`

**Interfaces:**
- Consumes: `AuditUnit, AuditTask, Material, User, get_db` from `app.models`; `get_current_user` from `app.core.auth`
- Produces:
  - `dashboard_router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])`
  - `GET /api/dashboard/unit-stats/summary` → `dict` with keys `{total, no_task, has_task_no_material, in_progress_with_material, completed}` all int
  - `GET /api/dashboard/unit-stats/detail?category=<name>` → `list[dict]` each `{id, name, total_tasks, finalized_tasks, material_count}`
  - 模块常量 `_VALID_DETAIL_CATEGORIES: set[str]`
  - 内部函数 `_base_subquery(db) -> subquery` 和 `_categorize(row) -> str`

- [ ] **Step 1: 写首条失败测试 —— summary 空库返 0**

新建 `compliance-agent/backend/tests/test_dashboard_unit_stats.py`：

```python
"""v2.13 工作台单位核查进度总览端点测试。"""
from fastapi.testclient import TestClient


def test_summary_empty_db_returns_zeros(auth_headers):
    """空库（无单位）→ 5 档全 0。"""
    from app.main import app
    with TestClient(app) as client:
        r = client.get("/api/dashboard/unit-stats/summary", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        # total 可能非 0（其它测试残留），但结构必须有 5 键
        assert set(data.keys()) == {
            "total", "no_task", "has_task_no_material",
            "in_progress_with_material", "completed",
        }
        # 后 4 档相加 = total
        assert (data["no_task"] + data["has_task_no_material"]
                + data["in_progress_with_material"] + data["completed"]
                == data["total"])
```

- [ ] **Step 2: 跑测试 —— verify RED**

```bash
cd compliance-agent/backend && python -m pytest tests/test_dashboard_unit_stats.py::test_summary_empty_db_returns_zeros -v
```

Expected: `404 Not Found`（端点尚未注册）→ 断言失败或状态码 != 200

- [ ] **Step 3: 写 dashboard_routes.py**

新建 `compliance-agent/backend/app/api/dashboard_routes.py`：

```python
"""v2.13: 工作台"单位核查进度总览"端点。

5 档互斥统计：
- no_task: task_count == 0
- completed: finalized_count == task_count（含 0 材料也算完成）
- has_task_no_material: material_count == 0（未完成前提下）
- in_progress_with_material: 其它

判定优先级：no_task > completed > has_task_no_material > in_progress_with_material。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, distinct, func
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.models import AuditTask, AuditUnit, Material, User, get_db

dashboard_router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _base_subquery(db: Session):
    """每单位聚合 (task_count, material_count, finalized_count) 子查询。"""
    return (
        db.query(
            AuditUnit.id.label("unit_id"),
            AuditUnit.name.label("unit_name"),
            func.count(distinct(AuditTask.id)).label("task_count"),
            func.count(Material.id).label("material_count"),
            func.count(distinct(case(
                (AuditTask.status == "finalized", AuditTask.id),
            ))).label("finalized_count"),
        )
        .outerjoin(AuditTask, AuditTask.unit_id == AuditUnit.id)
        .outerjoin(Material, Material.task_id == AuditTask.id)
        .group_by(AuditUnit.id, AuditUnit.name)
    ).subquery()


def _categorize(row) -> str:
    """按判定优先级返分档字符串。"""
    if row.task_count == 0:
        return "no_task"
    if row.finalized_count == row.task_count:
        return "completed"
    if row.material_count == 0:
        return "has_task_no_material"
    return "in_progress_with_material"


_VALID_DETAIL_CATEGORIES = {
    "no_task", "has_task_no_material", "in_progress_with_material",
}


@dashboard_router.get("/unit-stats/summary")
def unit_stats_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """5 档单位数统计，一次 SQL 聚合。"""
    sub = _base_subquery(db)
    rows = db.query(sub).all()
    counts = {
        "total": 0,
        "no_task": 0,
        "has_task_no_material": 0,
        "in_progress_with_material": 0,
        "completed": 0,
    }
    for r in rows:
        counts["total"] += 1
        counts[_categorize(r)] += 1
    return counts


@dashboard_router.get("/unit-stats/detail")
def unit_stats_detail(
    category: str = Query(
        ..., description="no_task / has_task_no_material / in_progress_with_material",
    ),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """按 category 返单位列表。completed 不提供 detail。"""
    if category not in _VALID_DETAIL_CATEGORIES:
        raise HTTPException(400, f"unknown category: {category}")

    sub = _base_subquery(db)
    rows = db.query(sub).all()

    out: list[dict] = []
    for r in rows:
        if _categorize(r) != category:
            continue
        out.append({
            "id": r.unit_id,
            "name": r.unit_name,
            "total_tasks": int(r.task_count),
            "finalized_tasks": int(r.finalized_count),
            "material_count": int(r.material_count),
        })
    out.sort(key=lambda x: x["name"])
    return out
```

- [ ] **Step 4: 注册 router 到 main.py**

Edit `compliance-agent/backend/app/main.py`。找到 import 区（约 line 15-20，紧跟 `from app.api.export_routes import exports_router` 之后）加：

```python
from app.api.dashboard_routes import dashboard_router
```

然后在 `app.include_router(exports_router)` 之后加：

```python
app.include_router(dashboard_router)
```

- [ ] **Step 5: 跑首条测试 —— verify GREEN**

```bash
cd compliance-agent/backend && python -m pytest tests/test_dashboard_unit_stats.py::test_summary_empty_db_returns_zeros -v
```

Expected: PASS

- [ ] **Step 6: 加剩余 5 条测试**

在 `tests/test_dashboard_unit_stats.py` 追加：

```python
def _seed_unit_with_task_and_materials(client, headers, unit_name, task_name,
                                       n_materials=0, finalize=False):
    """建 unit + task；可选 n_materials 上传 + finalize。返回 (unit_id, task_id)。"""
    import io
    r = client.post("/api/units",
                    json={"name": unit_name, "code": "T"},
                    headers=headers)
    assert r.status_code == 200, r.text
    unit_id = r.json()["id"]
    r = client.post("/api/tasks",
                    json={"unit_id": unit_id, "name": task_name,
                          "eval_year": 2025, "scope": "all"},
                    headers=headers)
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]

    for i in range(n_materials):
        files = {"file": (f"m{i}.txt", io.BytesIO(b"x"), "text/plain")}
        r = client.post(f"/api/tasks/{task_id}/materials",
                        files=files, headers=headers)
        assert r.status_code == 200, r.text

    if finalize:
        from app.models import SessionLocal, AuditTask, Worksheet
        with SessionLocal() as s:
            t = s.get(AuditTask, task_id)
            t.status = "finalized"
            ws = Worksheet(task_id=task_id, status="finalized")
            s.add(ws)
            s.commit()

    return (unit_id, task_id)


def test_summary_categorizes_all_five_buckets(auth_headers):
    """seed 4 unit（各 1 档，除 total）→ summary 每档增 1。"""
    from app.main import app
    with TestClient(app) as client:
        # 拿到 baseline（其它测试残留）
        r0 = client.get("/api/dashboard/unit-stats/summary", headers=auth_headers)
        base = r0.json()

        # bucket no_task: 建单位不建任务
        r = client.post("/api/units",
                        json={"name": "v213-notask", "code": "N"},
                        headers=auth_headers)
        assert r.status_code == 200

        # bucket has_task_no_material: 建单位 + 任务，不上传
        _seed_unit_with_task_and_materials(
            client, auth_headers, "v213-htnm", "T_htnm", n_materials=0,
        )

        # bucket in_progress_with_material: 建 + 上传 1 材料 + 不 finalize
        _seed_unit_with_task_and_materials(
            client, auth_headers, "v213-ipwm", "T_ipwm", n_materials=1,
        )

        # bucket completed: 建 + 上传 1 材料 + finalize
        _seed_unit_with_task_and_materials(
            client, auth_headers, "v213-done", "T_done", n_materials=1,
            finalize=True,
        )

        r = client.get("/api/dashboard/unit-stats/summary", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == base["total"] + 4
        assert data["no_task"] == base["no_task"] + 1
        assert data["has_task_no_material"] == base["has_task_no_material"] + 1
        assert data["in_progress_with_material"] == base["in_progress_with_material"] + 1
        assert data["completed"] == base["completed"] + 1


def test_detail_no_task_lists_units_without_tasks(auth_headers):
    """no_task detail 只列出无任务的单位。"""
    from app.main import app
    with TestClient(app) as client:
        r = client.post("/api/units",
                        json={"name": "v213-detail-notask", "code": "N"},
                        headers=auth_headers)
        assert r.status_code == 200

        r = client.get(
            "/api/dashboard/unit-stats/detail?category=no_task",
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        names = {item["name"] for item in data}
        assert "v213-detail-notask" in names
        # 且该 unit 的 total_tasks == 0
        item = next(i for i in data if i["name"] == "v213-detail-notask")
        assert item["total_tasks"] == 0


def test_detail_has_task_no_material_lists_correctly(auth_headers):
    """has_task_no_material detail 列出建了任务但 0 材料的单位。"""
    from app.main import app
    with TestClient(app) as client:
        _seed_unit_with_task_and_materials(
            client, auth_headers, "v213-detail-htnm", "T_x", n_materials=0,
        )

        r = client.get(
            "/api/dashboard/unit-stats/detail?category=has_task_no_material",
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        item = next((i for i in data if i["name"] == "v213-detail-htnm"), None)
        assert item is not None
        assert item["total_tasks"] >= 1
        assert item["material_count"] == 0


def test_detail_in_progress_with_material_shows_material_count(auth_headers):
    """in_progress_with_material detail 含 material_count 字段。"""
    from app.main import app
    with TestClient(app) as client:
        _seed_unit_with_task_and_materials(
            client, auth_headers, "v213-detail-ipwm", "T_y", n_materials=2,
        )

        r = client.get(
            "/api/dashboard/unit-stats/detail?category=in_progress_with_material",
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        item = next((i for i in data if i["name"] == "v213-detail-ipwm"), None)
        assert item is not None
        assert item["material_count"] >= 2
        assert item["finalized_tasks"] == 0


def test_detail_rejects_completed_and_unknown_categories(auth_headers):
    """completed 无 detail 端点 → 400；unknown 也 → 400。"""
    from app.main import app
    with TestClient(app) as client:
        r = client.get(
            "/api/dashboard/unit-stats/detail?category=completed",
            headers=auth_headers,
        )
        assert r.status_code == 400

        r = client.get(
            "/api/dashboard/unit-stats/detail?category=nonsense",
            headers=auth_headers,
        )
        assert r.status_code == 400
```

- [ ] **Step 7: 跑全部 6 条测试**

```bash
cd compliance-agent/backend && python -m pytest tests/test_dashboard_unit_stats.py -v
```

Expected: 6 PASS

- [ ] **Step 8: Commit**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/backend/app/api/dashboard_routes.py \
        compliance-agent/backend/app/main.py \
        compliance-agent/backend/tests/test_dashboard_unit_stats.py
git commit -m "$(cat <<'EOF'
feat(v2.13): dashboard_routes 单位核查进度总览端点

- GET /api/dashboard/unit-stats/summary：一次 outerjoin 聚合 SQL
  返 5 档互斥统计（total / no_task / has_task_no_material /
  in_progress_with_material / completed）
- GET /api/dashboard/unit-stats/detail?category=X：按 category 返
  单位列表（completed 无 detail 返 400）
- 判定优先级：no_task > completed > has_task_no_material > in_progress
- 6 条 pytest 覆盖 5 档 + detail 校验 + 400

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 前端 index.html card + app.js render + cache-buster

**Files:**
- Modify: `compliance-agent/frontend/index.html`（加 card + `?v=2.11` → `?v=2.13`）
- Modify: `compliance-agent/frontend/app.js`（`renderUnitProgressCard` + `_upStatBox` + `_toggleUnitProgressDetail` + State + loadDashboard 末尾调用）

**Interfaces:**
- Consumes:
  - `api(path)` helper（`/api` 前缀 + Bearer token 自动）
  - `esc(s)` helper
  - `State` global object（新增字段 `State.unitStatsDetailCache`）
  - 后端 `/api/dashboard/unit-stats/summary` + `/detail?category=X`（Task 1）
- Produces:
  - JS 函数 `renderUnitProgressCard()`（无参，读 `#dash-unit-progress`）
  - JS 函数 `_upStatBox(category, count, label, clickable) -> html string`
  - JS 函数 `_toggleUnitProgressDetail(category)` 
  - DOM ids：`dash-unit-progress`（card 内 container）+ `dash-unit-progress-detail`（展开表格容器）

- [ ] **Step 1: index.html 加 card**

打开 `compliance-agent/frontend/index.html`。找到 `page-dashboard` 里 `grid-2` 的 `</div>` 关闭（"最近任务" card 之后），跟着的是"批量导出已定稿工作底稿" `<div class="card mt-6 fade-in fade-in-4">`。在这两者之间插入新 card：

```html

        <!-- v2.13: 单位核查进度总览 -->
        <div class="card mt-6 fade-in fade-in-4">
          <div class="section-title">单位核查进度总览</div>
          <div class="text-sm text-muted mb-3">
            5 档互斥统计（后 4 档相加 = 单位总数）。点数字下方箭头展开对应类别的单位列表。
          </div>
          <div id="dash-unit-progress" class="text-sm">
            <div class="empty-state" style="padding:16px">加载中…</div>
          </div>
        </div>
```

- [ ] **Step 2: bump cache-buster**

在 `compliance-agent/frontend/index.html` 里所有 `?v=2.11` → `?v=2.13`：

```bash
grep -n "?v=2\." compliance-agent/frontend/index.html
```

用 Edit 工具 `replace_all=true` 改。

- [ ] **Step 3: app.js 加 3 个新函数**

打开 `compliance-agent/frontend/app.js`。在 `renderExportRegion` 函数（或类似 v2.11 dashboard 相关函数）之前或之后插入新代码块。为保持相邻，可放在 `renderExportRegion` **之后**：

```javascript

// v2.13: 单位核查进度总览 —— summary + 懒加载 detail
async function renderUnitProgressCard() {
  const box = document.getElementById("dash-unit-progress");
  if (!box) return;
  try {
    const s = await api("/dashboard/unit-stats/summary");
    box.innerHTML = `
      <div class="unit-progress-stats" style="display:flex;gap:16px;align-items:stretch">
        ${_upStatBox("total",                     s.total,                     "单位总数",         false)}
        ${_upStatBox("no_task",                   s.no_task,                   "未建任务",         true)}
        ${_upStatBox("has_task_no_material",      s.has_task_no_material,      "建任务未上传材料", true)}
        ${_upStatBox("in_progress_with_material", s.in_progress_with_material, "有材料未完成",     true)}
        ${_upStatBox("completed",                 s.completed,                 "已完成核查",       false)}
      </div>
      <div id="dash-unit-progress-detail" style="margin-top:12px"></div>
    `;
    box.querySelectorAll(".unit-progress-toggle").forEach(el => {
      el.addEventListener("click", () => _toggleUnitProgressDetail(el.dataset.category));
    });
  } catch (e) {
    box.innerHTML = `<div class="empty-state" style="padding:16px;color:#b8262b">加载失败：${esc(e.message)}</div>`;
  }
}

function _upStatBox(category, count, label, clickable) {
  const arrow = clickable
    ? `<span class="unit-progress-toggle" data-category="${esc(category)}" style="cursor:pointer;color:#0071e3;font-size:13px" title="展开单位列表">▼</span>`
    : "";
  return `
    <div style="flex:1;text-align:center;padding:12px;background:#fafafa;border-radius:8px">
      <div style="font-size:28px;font-weight:600;color:#1d1d1f">${count}</div>
      <div style="font-size:12px;color:#6e6e73;margin-top:4px">${esc(label)}</div>
      <div style="margin-top:4px;min-height:18px">${arrow}</div>
    </div>
  `;
}

async function _toggleUnitProgressDetail(category) {
  const box = document.getElementById("dash-unit-progress-detail");
  if (!box) return;
  // 如果当前已展开的就是这个 → 收起
  if (box.dataset.openCategory === category) {
    box.innerHTML = "";
    box.dataset.openCategory = "";
    return;
  }
  box.dataset.openCategory = category;
  box.innerHTML = `<div class="empty-state" style="padding:8px">加载中…</div>`;
  try {
    if (!State.unitStatsDetailCache) State.unitStatsDetailCache = {};
    let rows = State.unitStatsDetailCache[category];
    if (!rows) {
      rows = await api(`/dashboard/unit-stats/detail?category=${encodeURIComponent(category)}`);
      State.unitStatsDetailCache[category] = rows;
    }
    if (!rows.length) {
      box.innerHTML = `<div class="empty-state" style="padding:8px">该类别下无单位</div>`;
      return;
    }
    const showProgress = category !== "no_task";
    const showMaterial = category === "in_progress_with_material";
    box.innerHTML = `
      <table class="table table-compact">
        <thead>
          <tr>
            <th style="width:60px">编号</th>
            <th>单位名称</th>
            ${showProgress ? '<th style="width:120px">任务进度</th>' : ''}
            ${showMaterial ? '<th style="width:100px">材料数</th>' : ''}
          </tr>
        </thead>
        <tbody>
          ${rows.map(r => `
            <tr>
              <td><span class="code-id">#${r.id}</span></td>
              <td>${esc(r.name)}</td>
              ${showProgress ? `<td>${r.finalized_tasks} / ${r.total_tasks}</td>` : ''}
              ${showMaterial ? `<td>${r.material_count}</td>` : ''}
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;
  } catch (e) {
    box.innerHTML = `<div class="empty-state" style="padding:8px;color:#b8262b">加载失败：${esc(e.message)}</div>`;
  }
}
```

- [ ] **Step 4: 在 loadDashboard 末尾调用**

定位到 `loadDashboard()` 函数末尾。找到 `renderExportRegion();`（v2.11 加的）。在它**之后**加：

```javascript
    // v2.13: 单位核查进度总览
    renderUnitProgressCard();
```

- [ ] **Step 5: 语法 + grep 验证**

```bash
cd compliance-agent/frontend && node --check app.js && echo "SYNTAX OK"
grep -c "renderUnitProgressCard" app.js
grep -c "_toggleUnitProgressDetail" app.js
grep -c "dash-unit-progress" index.html
grep -c "?v=2.13" index.html
```

Expected:
- `SYNTAX OK`
- `renderUnitProgressCard` count: `>=2`（定义 + 调用）
- `_toggleUnitProgressDetail` count: `>=2`（定义 + 事件绑定）
- `dash-unit-progress` count: `1`（card 里的 div id）
- `?v=2.13` count: `3`（styles.css + pinyin_initials.js + app.js）

- [ ] **Step 6: Commit**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/frontend/index.html compliance-agent/frontend/app.js
git commit -m "$(cat <<'EOF'
feat(v2.13): 工作台"单位核查进度总览"card

- index.html: 加 card，5 stat box + detail 展开容器
- app.js: renderUnitProgressCard (summary) + _upStatBox + 
  _toggleUnitProgressDetail (懒加载 detail，State 缓存)
- 中间 3 档可点▼展开单位列表，第二次点收起
- 已完成核查/单位总数不可点
- cache-buster 2.11 → 2.13（跳过 v2.12 无前端）

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 部署 + 浏览器 checklist + README

**Files:**
- 无代码改动，部署 Task 1 + Task 2 产出的 4 文件
- Modify: `compliance-agent/README.md`（v2.13 更新日志）

**Interfaces:** 无

- [ ] **Step 1: Push origin/main**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git push origin main 2>&1 | tail -3
```

Expected: `main -> main` 推送成功。

- [ ] **Step 2: Workbench 上传 4 文件到 ECS**

用户操作：Workbench 上传到 `/opt/audit/compliance-agent/` 对应路径：
- `backend/app/api/dashboard_routes.py` → 新文件
- `backend/app/main.py` → 覆盖
- `frontend/index.html` → 覆盖
- `frontend/app.js` → 覆盖

- [ ] **Step 3: 服务器 docker cp 后端 + restart**

用户在 ECS 上跑：

```bash
cd /opt/audit/compliance-agent
for c in backend worker enrich_worker; do
  docker compose cp backend/app/api/dashboard_routes.py $c:/app/app/api/dashboard_routes.py
  docker compose cp backend/app/main.py $c:/app/app/main.py
done
docker compose restart backend worker enrich_worker
docker compose logs backend --tail=10 | grep -Ei "error|startup complete"
```

Expected: `Application startup complete.` 无 ImportError。

前端 bind mount，无需 cp，无需 restart nginx。

- [ ] **Step 4: 后端冒烟测试**

```bash
# 用管理员账号拿 token（把 <密码> 换成实际密码）
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"<密码>"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")

# summary
curl -s http://localhost:8000/api/dashboard/unit-stats/summary \
    -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Expected: 返 JSON 5 键 int；后 4 键相加 = total。

若不方便拿 token，跳过 curl，直接 Step 5 浏览器验证。

- [ ] **Step 5: 浏览器 checklist**

打开 `http://8.163.75.9/`，Cmd+Shift+R 硬刷（F12 Network 看 `app.js?v=2.13`）。进"工作台"页。

- [ ] card 出现在"最近任务"下方、"批量导出已定稿工作底稿"上方
- [ ] 5 数字加起来（后 4 档）= 单位总数（数学一致）
- [ ] 点"未建任务 X"下方 ▼ → 展开表格显示单位列表（编号 + 单位名，无进度列）
- [ ] 点同一个 ▼ 再点 → 表格收起
- [ ] 点"建任务未上传材料"▼ → 表格含"任务进度"列（如 0/3）
- [ ] 点"有材料未完成"▼ → 表格含"任务进度" + "材料数"两列
- [ ] 点另一个 ▼ → 上一个收起 + 新的展开（同一时刻只展开一个）
- [ ] "单位总数"和"已完成核查"下方无 ▼ 箭头（不可点）
- [ ] 401 失效时 card 显示"加载失败"（不是 crash）

任意 checklist 项失败 → 报现象给我 → 修 → 重新部署 → 重跑。

- [ ] **Step 6: 更新 README**

Edit `compliance-agent/README.md`。找到"## 更新日志（部分）"段，在 v2.12 之前插入：

```markdown
- **v2.13（2026-07-20）**：工作台加"单位核查进度总览"card，5 档互斥统计（单位总数 / 未建任务 / 建任务未上传材料 / 有材料未完成 / 已完成核查）。点中间 3 档 ▼ 展开单位列表懒加载 + State 缓存。新端点 `/api/dashboard/unit-stats/summary` 和 `/detail?category=X`。详见 `docs/superpowers/plans/2026-07-20-dashboard-unit-progress-overview.md`
```

- [ ] **Step 7: Commit + push README**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/README.md
git commit -m "$(cat <<'EOF'
docs(v2.13): README 加更新日志

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push origin main 2>&1 | tail -3
```

---

## Self-Review

**Spec coverage:**
- ✅ 5 档互斥定义 + 判定优先级 → Task 1 Step 3（`_categorize`）
- ✅ `GET /unit-stats/summary` → Task 1 Step 3
- ✅ `GET /unit-stats/detail?category=X` → Task 1 Step 3
- ✅ `completed` 不给 detail → Task 1 Step 3（`_VALID_DETAIL_CATEGORIES` 排除）
- ✅ 详情表 row `{id, name, total_tasks, finalized_tasks, material_count}` → Task 1 Step 3
- ✅ 按 name 升序 → Task 1 Step 3（`out.sort(key=lambda x: x["name"])`）
- ✅ 前端 card 位置 → Task 2 Step 1
- ✅ 5 stat box + 中间 3 个可点 ▼ → Task 2 Step 3 (`_upStatBox` clickable 参数)
- ✅ 展开表格按 category 选列 → Task 2 Step 3（`showProgress` + `showMaterial`）
- ✅ 再点收起 → Task 2 Step 3（`box.dataset.openCategory`）
- ✅ State 缓存 → Task 2 Step 3
- ✅ `esc()` on user data → Task 2 Step 3（单位名 / label / category attr）
- ✅ Cache buster 2.11 → 2.13 → Task 2 Step 2
- ✅ 部署 cp 3 容器 → Task 3 Step 3
- ✅ 浏览器 checklist → Task 3 Step 5
- ✅ README → Task 3 Step 6

**Placeholder scan:**
- 无 TODO/TBD
- 所有代码块完整
- 所有命令带 Expected

**Type consistency:**
- Router prefix `/api/dashboard` 一致
- Summary 5 键名 `total/no_task/has_task_no_material/in_progress_with_material/completed` 前后端一致
- Detail row 键名 `id/name/total_tasks/finalized_tasks/material_count` 前后端一致
- `_categorize(row) -> str` 返值只有 4 种（no_task/completed/has_task_no_material/in_progress_with_material）与 `_VALID_DETAIL_CATEGORIES` 减去 completed 一致
- 前端函数名 `renderUnitProgressCard` / `_upStatBox` / `_toggleUnitProgressDetail` 前后引用一致
- DOM ids `dash-unit-progress` / `dash-unit-progress-detail` 一致

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-20-dashboard-unit-progress-overview.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — Task 1/2 派 fresh subagent + review；Task 3 部署 + checklist 交给用户浏览器

**2. Inline Execution** — 本会话直接跑 Task 1/2，Task 3 hand-off 给用户

Which approach?
