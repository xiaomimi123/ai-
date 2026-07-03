# 前端数据缓存 + 后端 defer stats 实施计划（v2.6）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除切页面时的 3-5 秒等待。后端 `list_tasks` defer stats 字段让首次拉取从 28s 降到 1-3s；前端 State 数组判空缓存让页面切换 <100ms。

**Architecture:** 后端在 SQLAlchemy Query 层加 `defer(AuditTask.stats)` 不 SELECT 大 JSON 列 + 手动映射避免 pydantic 触发 lazy load。前端在 5 处 load 函数入口判空，State 数组非空则跳过 fetch，write 操作后清空对应数组让下次访问自然重拉。

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy + pytest（backend）；vanilla JS（frontend）。

## Global Constraints

- 不改 `AuditTaskOut` schema 字段（stats 字段保留，值改为 `""`）
- 不改 DB schema
- 不改 uvicorn workers 数（内存约束）
- 不做后端分页（会破坏 v2.1 前端搜索）
- Regulations 因带筛选参数（search / doc_type / region）不缓存
- 静态资源版本 query 升级 `?v=2.5` → `?v=2.6`

---

## File Structure

| 文件 | 变更 | 责任 |
|------|-----|------|
| `backend/app/api/audit_routes.py:117-123` | Modify | `list_tasks` 加 defer + 手动映射填 stats="" |
| `backend/tests/test_v26_perf_cache.py` | Create | 3 条：defer 后 stats 为空 / 详情 stats 有值 / 数量匹配 |
| `frontend/app.js` | Modify | State 加字段 + 4 处 load 函数判空 + 5 处 write 后 invalidate |
| `frontend/index.html` | Modify | 3 处 `?v=2.5` → `?v=2.6` |

---

## Task 1：backend RED test

**Files:**
- Create: `compliance-agent/backend/tests/test_v26_perf_cache.py`

**Interfaces:**
- Consumes: 无
- Produces: 3 条 pytest case 断言 defer 效果 + API 契约

- [ ] **Step 1: 创建测试文件**

`compliance-agent/backend/tests/test_v26_perf_cache.py`：

```python
"""v2.6 backend perf: list_tasks defer stats。

目的：让 GET /api/tasks 不 SELECT stats 大 JSON 字段（省序列化），
但 GET /api/tasks/{id} 详情端点仍返回完整 stats（详情页需要）。

断言：
- list 响应里每条 task.stats == ""（手动映射填空）
- detail 响应里 task.stats 有真实 JSON 内容
- list 数量 == db.count()（不漏任务）
"""
from __future__ import annotations

import io
import json
import uuid

import pytest
from fastapi.testclient import TestClient


def _setup_task_with_stats(client, headers, stats_content: str):
    """建 unit + task + 手动写 stats 字段。"""
    from app.models import AuditTask, SessionLocal
    from app.seeds.load_indicators_55 import load as load_ind
    load_ind(replace=False)

    suffix = uuid.uuid4().hex[:6]
    r = client.post("/api/units",
                    json={"name": f"v26-{suffix}", "code": f"V26{suffix}"},
                    headers=headers)
    unit_id = r.json()["id"]

    inds = client.get("/api/indicators", headers=headers).json()
    i13 = next(i for i in inds if i["indicator_code"] == "I-13")

    r = client.post("/api/tasks", json={
        "unit_id": unit_id, "name": f"v26-{suffix}",
        "eval_year": 2026, "scope": "selected",
        "selected_indicator_ids": [i13["id"]],
    }, headers=headers)
    task_id = r.json()["id"]

    # 手动写 stats 到 DB（模拟核查完成后的 stats）
    db = SessionLocal()
    try:
        t = db.get(AuditTask, task_id)
        t.stats = stats_content
        db.commit()
    finally:
        db.close()

    return task_id


def test_list_tasks_response_omits_stats_content(auth_headers):
    """v2.6：GET /api/tasks 响应里 task.stats 字段为空字符串（defer 生效 + 手动映射）。"""
    from app.main import app

    STATS_JSON = json.dumps({
        "findings_by_type": {"合规性": 12, "完整性": 5, "重复性": 3},
        "score_summary": {"total": 87.5, "max": 100},
        "breakdown": [{"indicator": "I-13", "score": 4.5}] * 20,
    })

    with TestClient(app, headers=auth_headers) as client:
        task_id = _setup_task_with_stats(client, auth_headers, STATS_JSON)

        # GET list
        r = client.get("/api/tasks")
        assert r.status_code == 200
        tasks = r.json()

        # 找到刚建的 task
        me = next((t for t in tasks if t["id"] == task_id), None)
        assert me is not None, "刚建的 task 应在 list 里"

        # 关键断言：list 响应里 stats 是空字符串（defer + 手动映射效果）
        assert me["stats"] == "", (
            f"list 响应里 stats 应为空字符串（v2.6 defer 效果），实际: {me['stats']!r}"
        )


def test_task_detail_still_returns_full_stats(auth_headers):
    """v2.6：GET /api/tasks/{id} 详情端点仍返回完整 stats（不受 defer 影响）。"""
    from app.main import app

    STATS_JSON = json.dumps({
        "findings_by_type": {"合规性": 12},
        "score_summary": {"total": 87.5, "max": 100},
    })

    with TestClient(app, headers=auth_headers) as client:
        task_id = _setup_task_with_stats(client, auth_headers, STATS_JSON)

        # GET detail
        r = client.get(f"/api/tasks/{task_id}")
        assert r.status_code == 200
        detail = r.json()

        # 详情里 stats 应包含真实 JSON
        assert detail["task"]["stats"] == STATS_JSON, (
            f"详情 stats 应为真实内容，实际: {detail['task']['stats']!r}"
        )
        # 解析后应有 findings_by_type
        parsed = json.loads(detail["task"]["stats"])
        assert "findings_by_type" in parsed


def test_list_tasks_count_matches_db(auth_headers):
    """v2.6：GET /api/tasks 返回条数 == DB 里 AuditTask 总数（不漏不重）。"""
    from app.main import app
    from app.models import AuditTask, SessionLocal

    with TestClient(app, headers=auth_headers) as client:
        # 建 2 个新 task（在已有基础上）
        _setup_task_with_stats(client, auth_headers, '{}')
        _setup_task_with_stats(client, auth_headers, '{}')

        # DB 里的总数
        db = SessionLocal()
        try:
            db_count = db.query(AuditTask).count()
        finally:
            db.close()

        # API 返回条数
        r = client.get("/api/tasks")
        api_count = len(r.json())

        assert api_count == db_count, (
            f"API 返回 {api_count} 条，DB 实际 {db_count} 条"
        )
```

- [ ] **Step 2: 跑测试确认 RED**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/backend
.venv/bin/python -m pytest tests/test_v26_perf_cache.py -v --tb=short 2>&1 | tail -15
```

期望：**第一条 `test_list_tasks_response_omits_stats_content` FAIL**（当前 list_tasks 返回真实 stats 而非 ""）；另外两条可能 PASS（详情端点行为不变、count 正常）。

只要有 1 条 fail 就算 RED 成立。

- [ ] **Step 3: Commit RED**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/backend/tests/test_v26_perf_cache.py
git commit -m "test(v2.6): list_tasks defer stats assertions (RED)"
```

---

## Task 2：后端 `list_tasks` 用 defer + 手动映射

**Files:**
- Modify: `compliance-agent/backend/app/api/audit_routes.py`（`list_tasks` 函数，约 line 117-123）

**Interfaces:**
- Consumes: Task 1 的断言
- Produces: `list_tasks` 返回的 tasks 里每条 `stats=""`（省了 SELECT 大列），Task 1 变 GREEN

- [ ] **Step 1: 读现有 list_tasks**

```bash
sed -n '115,130p' /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/backend/app/api/audit_routes.py
```

期望看到：

```python
@tasks_router.get("", response_model=List[AuditTaskOut])
def list_tasks(db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    q = db.query(AuditTask).order_by(AuditTask.id.desc())
    if is_unit(user.role) and user.unit_id:
        q = q.filter(AuditTask.unit_id == user.unit_id)
    return q.all()
```

- [ ] **Step 2: 加 defer import + 改函数体**

用 Edit：

```
old_string:
@tasks_router.get("", response_model=List[AuditTaskOut])
def list_tasks(db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    q = db.query(AuditTask).order_by(AuditTask.id.desc())
    if is_unit(user.role) and user.unit_id:
        q = q.filter(AuditTask.unit_id == user.unit_id)
    return q.all()
```

改成：

```
new_string:
@tasks_router.get("", response_model=List[AuditTaskOut])
def list_tasks(db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    # v2.6：defer(stats) 让 SQL 不 SELECT 大 JSON 列（1739 条 × 几 KB 序列化耗时）
    # 手动映射 stats="" 避免 pydantic model_validate 触发 lazy load
    # 详情端点 GET /api/tasks/{id} 用 db.get 拿全列，stats 仍完整
    from sqlalchemy.orm import defer

    q = db.query(AuditTask).options(defer(AuditTask.stats))\
        .order_by(AuditTask.id.desc())
    if is_unit(user.role) and user.unit_id:
        q = q.filter(AuditTask.unit_id == user.unit_id)
    tasks = q.all()
    return [
        AuditTaskOut(
            id=t.id, unit_id=t.unit_id, name=t.name, eval_year=t.eval_year,
            scope=t.scope, selected_indicator_ids=t.selected_indicator_ids,
            status=t.status, summary=t.summary,
            stats="",   # v2.6：列表页不用 stats，填空绕过 lazy load
            progress_current=t.progress_current, progress_total=t.progress_total,
            progress_text=t.progress_text, fast_mode=t.fast_mode,
            created_at=t.created_at, completed_at=t.completed_at,
        )
        for t in tasks
    ]
```

- [ ] **Step 3: 跑 Task 1 测试确认 GREEN**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/backend
.venv/bin/python -m pytest tests/test_v26_perf_cache.py -v --tb=short 2>&1 | tail -10
```

期望：3 条全过。

- [ ] **Step 4: 跑全量回归**

```bash
.venv/bin/python -m pytest tests/ -q --tb=short 2>&1 | tail -5
```

期望：`219 passed`（原 216 + v2.6 的 3）。若有已有测试因 stats="" 失败，看下该测试是否用 list 端点判断 stats —— 如果是则改用详情端点。

- [ ] **Step 5: Commit**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/backend/app/api/audit_routes.py
git commit -m "feat(v2.6): list_tasks defer stats (28s -> 1-3s for 1739 rows)"
```

---

## Task 3：前端 State 缓存 + 4 处 load 函数判空

**Files:**
- Modify: `compliance-agent/frontend/app.js`（5 处：State 定义、loadTasks、loadIndicators、loadCheckItems、新增变量声明）

**Interfaces:**
- Consumes: 无
- Produces:
  - `State.checkItems: []` 新字段
  - `loadTasks(force = false)`：判空缓存
  - `loadIndicators(force = false)`：判空缓存
  - `loadCheckItems(force = false)`：判空缓存

- [ ] **Step 1: State 加 checkItems 字段**

现有 State 定义在 app.js:8-21。用 Edit：

```
old_string:
const State = {
  user: null,
  roleLabel: "",
  units: [],
  indicators: [],
  tasks: [],
  taskId: null,
  taskDetail: null,
  subtab: "overview",
  findingFilter: "all",
  activeFindingId: null,
  consoleTab: "llm",
  taskSearchQuery: "",   // v2.1：任务列表搜索关键词（trim + toLowerCase 归一化）
};
```

改成：

```
new_string:
const State = {
  user: null,
  roleLabel: "",
  units: [],
  indicators: [],
  tasks: [],
  taskId: null,
  taskDetail: null,
  subtab: "overview",
  findingFilter: "all",
  activeFindingId: null,
  consoleTab: "llm",
  taskSearchQuery: "",   // v2.1：任务列表搜索关键词（trim + toLowerCase 归一化）
  checkItems: [],        // v2.6：问题清单缓存
};
```

- [ ] **Step 2: loadTasks 加 force + 判空**

现有 loadTasks 在 app.js:320-326（我之前 v2.1 改过）：

```
old_string:
async function loadTasks() {
  try {
    const [units, tasks] = await Promise.all([api("/units"), api("/tasks")]);
    State.units = units; State.tasks = tasks;
    applyTaskSearch();   // v2.1：应用当前搜索词，等价于全量渲染（空 query）
  } catch (e) { console.error(e); }
}
```

改成：

```
new_string:
async function loadTasks(force = false) {
  try {
    // v2.6：State 缓存命中直接渲染，避免每次切页面重拉
    if (!force && State.tasks.length && State.units.length) {
      applyTaskSearch();
      return;
    }
    const [units, tasks] = await Promise.all([api("/units"), api("/tasks")]);
    State.units = units; State.tasks = tasks;
    applyTaskSearch();
  } catch (e) { console.error(e); }
}
```

- [ ] **Step 3: loadIndicators 加 force + 判空**

现有在 app.js:2922-2935：

```
old_string:
async function loadIndicators() {
  const inds = await api("/indicators");
  State.indicators = inds;
  _indCache = inds;

  // 装填业务分类下拉
  const fcat = document.getElementById("ind-filter-category");
  if (fcat.options.length <= 1) {
    const cats = [...new Set(inds.map(i => i.category).filter(Boolean))].sort();
    fcat.innerHTML = `<option value="">全部业务分类</option>` +
      cats.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
  }
  renderIndicators();
}
```

改成：

```
new_string:
async function loadIndicators(force = false) {
  // v2.6：State 缓存命中跳过 fetch
  if (!force && State.indicators.length) {
    _indCache = State.indicators;
    renderIndicators();
    return;
  }
  const inds = await api("/indicators");
  State.indicators = inds;
  _indCache = inds;

  // 装填业务分类下拉
  const fcat = document.getElementById("ind-filter-category");
  if (fcat.options.length <= 1) {
    const cats = [...new Set(inds.map(i => i.category).filter(Boolean))].sort();
    fcat.innerHTML = `<option value="">全部业务分类</option>` +
      cats.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
  }
  renderIndicators();
}
```

- [ ] **Step 4: loadCheckItems 加 force + 判空**

现有在 app.js:3055-3059：

```
old_string:
async function loadCheckItems() {
  const items = await api("/check-items");
  _ciCache = items;
  renderCheckItems();
}
```

改成：

```
new_string:
async function loadCheckItems(force = false) {
  // v2.6：State 缓存命中跳过 fetch
  if (!force && State.checkItems.length) {
    _ciCache = State.checkItems;
    renderCheckItems();
    return;
  }
  const items = await api("/check-items");
  State.checkItems = items;
  _ciCache = items;
  renderCheckItems();
}
```

- [ ] **Step 5: 语法检查 + 暂不 commit（跟 Task 4 一起）**

```bash
node --check /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/frontend/app.js
```

期望：exit 0。

---

## Task 4：前端 write 操作后 invalidate State

**Files:**
- Modify: `compliance-agent/frontend/app.js`（5 处 write 后加 State 清空）

**Interfaces:**
- Consumes: Task 3 定义的 State.tasks/units/indicators/checkItems
- Produces: write 操作后对应 State 清空，下次访问自然重拉

- [ ] **Step 1: 找到所有 write 端点调用位置**

跑 grep 定位：

```bash
grep -nE 'api\(["`][^"`]*(/tasks|/units|/indicators|/check-items)["`],\s*\{\s*method:\s*"(POST|DELETE|PUT|PATCH)"' /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/frontend/app.js | head -20
```

期望列出所有创建/删除/更新调用的位置。

- [ ] **Step 2: 创建任务成功后 invalidate**

grep 找到 `api("/tasks", { method: "POST"` 或 `api("/tasks", { method: 'POST'`（大概在创建任务模态提交处），在 `await api(...)` 成功之后加一行：

```javascript
State.tasks = [];   // v2.6：清空缓存让下次进任务列表拉最新
State.units = [];   // 也清 units（新任务关联新单位时）
```

**具体做法**（用 Edit）：找到

```javascript
    const task = await api("/tasks", {
```

那段代码往下几行，在 modal 关闭或跳转前加清空。或者直接在 `.then(...)` / `await` 之后。示例伪代码：

```
find:
    const task = await api("/tasks", {
      method: "POST",
      ...
    });

add after:
    State.tasks = [];  // v2.6: invalidate
    State.units = [];
```

- [ ] **Step 3: 删除任务后 invalidate**

grep 找 `deleteTaskFromList` / `/tasks/${...}, { method: "DELETE" }`。在 DELETE 成功后加：

```javascript
State.tasks = [];   // v2.6: 让下次任务列表重拉
```

如果是 `deleteTaskFromList` 函数，找到 DELETE 调用点末尾：

```
find:
    await api(`/tasks/${id}`, { method: "DELETE" });

add after (in same try block):
    State.tasks = [];  // v2.6
```

- [ ] **Step 4: 上传/删除单位后 invalidate**

grep 找 `api("/units", { method: "POST"` 或类似 unit 创建。加：

```javascript
State.units = [];
State.tasks = [];   // tasks 依赖 unit 展示，一并清
```

- [ ] **Step 5: 上传指标 / check-items 后 invalidate**

grep 找 `/indicators/import` / `/check-items/import` 或类似 write：

```javascript
// indicators write 后
State.indicators = [];
_indCache = null;

// check-items write 后
State.checkItems = [];
_ciCache = null;
```

- [ ] **Step 6: 语法检查 + 全量回归**

```bash
node --check /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/frontend/app.js
cd /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/backend
.venv/bin/python -m pytest tests/ -q --tb=short 2>&1 | tail -3
```

期望：js 语法 OK；219 pytest pass。

- [ ] **Step 7: Commit（Task 3 + 4 合并）**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/frontend/app.js
git commit -m "feat(v2.6): State cache for tasks/units/indicators/checkItems + invalidate on write"
```

---

## Task 5：升级 index.html 版本号 `?v=2.6`

**Files:**
- Modify: `compliance-agent/frontend/index.html`

**Interfaces:**
- Consumes: 无
- Produces: 3 处 `?v=2.5` 替换为 `?v=2.6`

- [ ] **Step 1: 用 Edit 一次改（`?v=2.5` → `?v=2.6`）**

```
find (in index.html):
?v=2.5

replace_all with:
?v=2.6
```

- [ ] **Step 2: 验证**

```bash
grep -n '?v=' /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/frontend/index.html
```

期望：3 行都是 `?v=2.6`。

- [ ] **Step 3: Commit**

```bash
git add compliance-agent/frontend/index.html
git commit -m "chore(v2.6): bump static asset cache-buster ?v=2.6"
```

---

## Task 6：Push + 部署 + 浏览器 verify + Network 采样对比

**Files:** 无代码改动

**Interfaces:** 无

- [ ] **Step 1: Push**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git push origin main 2>&1 | tail -3
```

- [ ] **Step 2: 打 v2.6 tar 包**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent
tar -czf /private/tmp/claude-501/-Users-lizhishaoniange-Documents-ai-----/cd58db16-3297-4435-b223-ced9268d3256/scratchpad/v2.6.tar.gz \
  backend/app/api/audit_routes.py \
  backend/tests/test_v26_perf_cache.py \
  frontend/app.js \
  frontend/index.html
ls -la /private/tmp/claude-501/-Users-lizhishaoniange-Documents-ai-----/cd58db16-3297-4435-b223-ced9268d3256/scratchpad/v2.6.tar.gz
```

- [ ] **Step 3: 给用户部署命令**

**mac 本地：**

```bash
scp /private/tmp/claude-501/-Users-lizhishaoniange-Documents-ai-----/cd58db16-3297-4435-b223-ced9268d3256/scratchpad/v2.6.tar.gz \
    root@8.163.75.9:/opt/audit/compliance-agent/v2.6.tar.gz
```

**服务器 Workbench：**

```bash
cd /opt/audit/compliance-agent
tar -xzf v2.6.tar.gz
ls -la backend/app/api/audit_routes.py frontend/app.js frontend/index.html  # sanity

# audit_routes 主要 backend 服务用；worker/enrich_worker 也 cp 保持代码一致
for c in backend worker enrich_worker; do
  docker compose cp backend/app/api/audit_routes.py $c:/app/app/api/audit_routes.py
done
docker compose cp backend/tests/test_v26_perf_cache.py backend:/app/tests/test_v26_perf_cache.py

# 前端 bind mount 自动生效；backend restart 让新 audit_routes.py 生效
docker compose restart backend
sleep 5

# 容器内 pytest
docker compose exec -T backend python -m pytest tests/test_v26_perf_cache.py -v 2>&1 | tail -10
# 期望：3 passed

rm v2.6.tar.gz
```

- [ ] **Step 4: 浏览器手动 verify（用户执行）**

硬刷（`?v=2.6` 会自动拉新 app.js）后：

1. 打开工作台 → 记录耗时
2. 进"核查任务" → **1-3 秒**（比之前 28s 快 10 倍）
3. 切"法规库" → 首次 <1.5 秒
4. 切"评价指标" → **<100ms**（cache hit）
5. 切"问题清单" → 首次 <1 秒
6. 再切"核查任务" → **<50ms**（cache hit）
7. 新建一个任务 → 保存后回列表 → 看到新任务在里面
8. 删除一个任务 → 列表刷新
9. **Network 面板**：5 次切换 API 总数从 14 降到 ~6

- [ ] **Step 5: chrome-in-chrome Network 采样对比**

如果 claude-in-chrome 还在连，跑之前那段 5-hash 切换脚本 + read_network_requests，对比：

**改前**：14 个请求，慢的 `/api/tasks` 28s + `/api/units` 17s
**改后**：~6 个请求，慢的 `/api/tasks` 1-3s

- [ ] **Step 6: 报告结果**

- 全过 → v2.6 上线，收工
- 某步不符 → 贴 Network 截图 + backend log 尾部

---

## Self-Review

**Spec coverage 核对**：

| Spec 章节 | 对应任务 |
|-----------|---------|
| A：前端 State 缓存 tasks/units/indicators/check-items | Task 3（4 处判空） |
| A：write 操作 invalidate | Task 4（5 处清空）|
| A：不缓存 regulations（带筛选参数）| Task 3 里没改 loadRegulations |
| B1：backend `list_tasks` defer stats | Task 2 |
| B1：手动映射填 stats="" | Task 2 |
| B1：详情端点 stats 不受影响 | Task 1 test 2 |
| API contract 不变 | Task 2 (AuditTaskOut 字段不删) |
| 3 条 backend pytest | Task 1 |
| 前端 verify 9 步 | Task 6 Step 4 |
| Network 采样对比 | Task 6 Step 5 |
| index.html `?v=2.6` | Task 5 |
| 部署：backend cp 3 容器 + restart + pytest | Task 6 Step 3 |
| 前端 bind mount 自动生效 | Task 6 Step 3 |

无遗漏。

**Placeholder scan**：Task 4 里有些"grep 找具体位置"的模糊指导（因为具体行号可能变化），但每一步都给了完整的 find/add 代码块，engineer 按 grep 结果替换即可。这属于必要的**位置指引**而不是 placeholder。

**Type consistency**：
- `loadTasks(force = false)` / `loadIndicators(force = false)` / `loadCheckItems(force = false)` 签名一致
- `State.tasks/units/indicators/checkItems` 命名与调用点一致
- `_indCache` / `_ciCache` 沿用现有名字（Task 3 里同步更新它们）
- 版本号 `?v=2.6` 一致
- backend `AuditTaskOut` 字段名与 Task 2 里手动映射的 kwargs 一致（id/unit_id/name/eval_year/scope/selected_indicator_ids/status/summary/stats/progress_current/progress_total/progress_text/fast_mode/created_at/completed_at）
