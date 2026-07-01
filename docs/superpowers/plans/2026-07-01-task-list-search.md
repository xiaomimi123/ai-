# 核查任务列表搜索框 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在「核查任务」页面头部加一个搜索输入框，支持按任务名 / 单位名 / 任务编号即时筛选任务列表。

**Architecture:** 纯前端 filter（后端 `GET /api/tasks` 已一次拉全部，`State.tasks` 在内存），沿用项目已有的"输入 debounce → 重渲染"模式（跟 `#reg-search` / `#ind-search` 一致）。

**Tech Stack:** vanilla JS + HTML（无框架）；pytest 一条断言 HTML 元素存在的最小校验。

## Global Constraints

- 无后端 API 改动，`GET /api/tasks` 保持不变
- 匹配范围：任务名 `task.name` + 单位名 `unit.name`（从 `State.units` 映射） + 任务编号 `task.id`（含去 `#` 前缀）
- 不加拼音首字母匹配（用户明确拒绝）
- 不做匹配文字高亮，不做后端搜索，不做搜索历史持久化
- Debounce 200ms（跟项目现有搜索一致）
- 复用现有 CSS 类（`search-input` / `text-xs text-muted` / `empty-state`），不新加样式
- 前端是 bind mount，浏览器硬刷新即生效，无需 docker rebuild

---

## File Structure

| 文件 | 变更类型 | 责任 |
|------|---------|------|
| `compliance-agent/frontend/index.html` | Modify (~239-249 段) | 加搜索 input + 计数 span + `×` 清空按钮 到 `<section id="tasks">` 头部 |
| `compliance-agent/frontend/app.js` | Modify | 加 `State.taskSearchQuery` 字段、抽出 `renderTasksBody()`、加 `applyTaskSearch()`、绑定 input 事件 + debounce |
| `compliance-agent/backend/tests/test_v21_task_search.py` | Create | 一条 pytest 断言 HTML 里存在 `#task-search` 输入框元素（防止 spec 与代码漂移） |

---

## Task 1：pytest 最小校验（RED → GREEN 前置守卫）

**Files:**
- Create: `compliance-agent/backend/tests/test_v21_task_search.py`

**Interfaces:**
- Consumes: 无（读文件）
- Produces: `tests/test_v21_task_search.py::test_task_search_input_present` — 断言 `compliance-agent/frontend/index.html` 里存在 `id="task-search"` 与 `id="task-search-count"`

**目的**：让"HTML 里加了搜索框"这个改动被自动化验证覆盖住，避免后续别人 refactor 移除元素时前端功能静默丢失。

- [ ] **Step 1: 写 failing test**

创建文件 `compliance-agent/backend/tests/test_v21_task_search.py`：

```python
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
```

- [ ] **Step 2: 跑 test 确认 FAIL**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/backend
.venv/bin/python -m pytest tests/test_v21_task_search.py -v
```

期望：3 条 assert 至少 1 条 fail，消息形如 `未看到 id="task-search"`。

- [ ] **Step 3: Commit RED**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/backend/tests/test_v21_task_search.py
git commit -m "test(v2.1): task search input assertions (RED)"
```

---

## Task 2：index.html 加搜索 UI 元素（Task 1 变 GREEN）

**Files:**
- Modify: `compliance-agent/frontend/index.html`（`<section id="tasks">` 头部，约 229-249 行）

**Interfaces:**
- Consumes: Task 1 定义的 3 个 DOM id
- Produces:
  - DOM 元素 `#task-search`（`<input type="text">`）
  - DOM 元素 `#task-search-count`（`<span>` 显示匹配数）
  - DOM 元素 `#task-search-clear`（`<button>` 清空按钮）
  - 布局：在 `<h1 class="page-title">核查任务</h1>` 和 `<button id="open-create-task">` 之间

- [ ] **Step 1: 读 index.html 找到目标段**

先看 229-249 行确认现有结构：

```bash
sed -n '229,249p' /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/frontend/index.html
```

现有大概是（结构对照）：

```html
<section id="tasks" class="hidden">
  <div class="page-header">
    <div>
      <h1 class="page-title">核查任务</h1>
      <p class="page-sub">一个任务对应一个被检查单位的一次内控评价复核。</p>
    </div>
    <button class="btn btn-primary" id="open-create-task"><span data-icon="plus"></span><span>新建任务</span></button>
  </div>
  ...
```

- [ ] **Step 2: 用 Edit 把搜索元素插进去**

在 `<button class="btn btn-primary" id="open-create-task">` 前插入搜索控件。用 Edit 找到那行 button，往前插一个 `<div class="task-search-wrap">` 包裹的 input + × + count span。

改成：

```html
<section id="tasks" class="hidden">
  <div class="page-header">
    <div>
      <h1 class="page-title">核查任务</h1>
      <p class="page-sub">一个任务对应一个被检查单位的一次内控评价复核。</p>
    </div>
    <div class="task-search-wrap" style="display:flex;align-items:center;gap:8px;margin-left:auto">
      <div class="search-input" style="position:relative;display:inline-flex;align-items:center">
        <input id="task-search" type="text" placeholder="搜索任务名 / 单位 / 编号"
               style="min-width:240px;padding:6px 28px 6px 10px;border:1px solid #d0d7de;border-radius:6px;font-size:13px">
        <button id="task-search-clear" type="button" title="清空"
                style="position:absolute;right:4px;top:50%;transform:translateY(-50%);
                       background:none;border:none;cursor:pointer;color:#999;
                       padding:2px 6px;line-height:1;display:none;font-size:14px">×</button>
      </div>
      <span id="task-search-count" class="text-xs text-muted" style="min-width:80px"></span>
      <button class="btn btn-primary" id="open-create-task"><span data-icon="plus"></span><span>新建任务</span></button>
    </div>
  </div>
```

关键点：
- 把原本的 button 移进新 wrap 里保持在**同一行右侧**（wrap `margin-left:auto` 撑到右边）
- `#task-search-clear` 默认 `display:none`，只有 input 有值时才显示（Task 3 里的 JS 控制）
- style 内联少量样式避免动 CSS 文件；如果项目有约定 CSS 类可以复用

- [ ] **Step 3: 跑 pytest 确认 Task 1 变 GREEN**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/backend
.venv/bin/python -m pytest tests/test_v21_task_search.py -v
```

期望：`1 passed`。

- [ ] **Step 4: Commit**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/frontend/index.html
git commit -m "feat(v2.1): task list search input in page header (GREEN)"
```

---

## Task 3：app.js 加搜索状态 + `renderTasksBody` 抽取

**Files:**
- Modify: `compliance-agent/frontend/app.js`

**Interfaces:**
- Consumes: `State.tasks`（现有）、`State.units`（现有）
- Produces:
  - `State.taskSearchQuery: string`（新增字段）
  - `renderTasksBody(tasks, units)` 函数（从 `loadTasks` 里抽出的 tbody 渲染逻辑）
  - `loadTasks()` 修改：拉数据后调 `applyTaskSearch()` 而非直接写 innerHTML

- [ ] **Step 1: 找到 State 定义 + loadTasks**

```bash
grep -n "^const State\|^let State\|^var State\|State = {" /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/frontend/app.js | head -3
grep -n "async function loadTasks" /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/frontend/app.js
```

`loadTasks` 在 `app.js:320`（已确认）。找到 `State = {...}` 起始处。

- [ ] **Step 2: State 加字段**

用 Edit 在 State 对象里加 `taskSearchQuery: ""`。示例（找到 State 对象定义那段，加一行）：

如果 State 定义类似：

```javascript
const State = {
  user: null,
  taskId: null,
  tasks: [],
  units: [],
  indicators: [],
  worksheet: null,
  // ...
};
```

改成：

```javascript
const State = {
  user: null,
  taskId: null,
  tasks: [],
  units: [],
  indicators: [],
  worksheet: null,
  taskSearchQuery: "",   // v2.1：任务列表搜索关键词（trim + toLowerCase）
  // ...
};
```

- [ ] **Step 3: 抽出 renderTasksBody**

原 `loadTasks`（app.js:320-354）主体是 `tbody.innerHTML = tasks.map(...).join("")`。把这段逻辑抽成 `renderTasksBody(tasks, units)`。

用 Edit 替换 loadTasks 整个函数为：

```javascript
async function loadTasks() {
  try {
    const [units, tasks] = await Promise.all([api("/units"), api("/tasks")]);
    State.units = units; State.tasks = tasks;
    applyTaskSearch();   // v2.1：应用当前搜索词，等价于全量渲染（空 query）
  } catch (e) { console.error(e); }
}

function renderTasksBody(tasks, units) {
  const tbody = document.getElementById("tasks-tbody");
  if (!tbody) return;
  if (!tasks.length) {
    const empty = State.taskSearchQuery
      ? `<tr><td colspan="7" class="empty-state">未匹配到任务，请调整关键词。</td></tr>`
      : `<tr><td colspan="7" class="empty-state">
           <div class="empty-state-glyph">⊕</div>暂无任务，点击右上角「+ 新建任务」开始。
         </td></tr>`;
    tbody.innerHTML = empty;
    return;
  }
  tbody.innerHTML = tasks.map(t => {
    const unit = units.find(u => u.id === t.unit_id);
    return `
      <tr class="is-row-button">
        <td onclick="navigate('#/tasks/${t.id}')"><span class="code-id">#${pad(t.id)}</span></td>
        <td onclick="navigate('#/tasks/${t.id}')" style="font-weight:500">${esc(unit ? unit.name : "—")}</td>
        <td onclick="navigate('#/tasks/${t.id}')">${esc(t.name)}</td>
        <td onclick="navigate('#/tasks/${t.id}')" class="table-mono">${t.eval_year}</td>
        <td onclick="navigate('#/tasks/${t.id}')">
          ${statusBadge(t.status)}
          ${t.status === "running" && t.progress_total > 0
            ? `<span class="text-xs text-muted" style="margin-left:6px">${t.progress_current}/${t.progress_total}</span>`
            : ""}
          ${t.fast_mode ? `<span class="text-xs" style="margin-left:6px;color:#856404">[快速]</span>` : ""}
        </td>
        <td onclick="navigate('#/tasks/${t.id}')" class="text-sm text-muted">${esc(t.summary || "—")}</td>
        <td class="text-right" style="white-space:nowrap">
          <button class="btn btn-ghost btn-sm" onclick="navigate('#/tasks/${t.id}')" title="查看">${icon("arrow")}</button>
          <button class="btn btn-danger-ghost btn-sm" onclick="deleteTaskFromList(${t.id}, event)" title="删除任务">${icon("delete")}</button>
        </td>
      </tr>`;
  }).join("");
}
```

**关键**：这段是 Task 4 的前置基础，`applyTaskSearch()` Task 4 才定义 —— 但为了避免 loadTasks 引用未定义函数，Task 4 会紧接着加。

- [ ] **Step 4: 语法检查（node --check）**

```bash
node --check /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/frontend/app.js
```

期望：无输出（exit 0）。**注意**：这一步会检查出 `applyTaskSearch is not defined` 是 runtime 错误，不是语法错误，node --check 依然 pass。真正的运行时 broken 在 Task 4 完成前不 commit。

- [ ] **Step 5: 暂不 commit（要跟 Task 4 一起 commit）**

Task 3 单独 commit 会让 `loadTasks` 引用未定义的 `applyTaskSearch`，运行时报错。所以合并到 Task 4 一起 commit。

---

## Task 4：app.js 加 `applyTaskSearch` + debounce + 事件绑定

**Files:**
- Modify: `compliance-agent/frontend/app.js`

**Interfaces:**
- Consumes: `State.tasks`、`State.units`、`State.taskSearchQuery`、`renderTasksBody` (from Task 3)
- Produces:
  - `applyTaskSearch()`：读取 `State.taskSearchQuery`，filter `State.tasks`，调 `renderTasksBody`，更新 count + clear 按钮显隐
  - `matchTask(task, unitById, q)`：单条任务是否命中的判断函数
  - input 事件绑定 + debounce
  - clear 按钮 click 绑定

- [ ] **Step 1: 加 matchTask 与 applyTaskSearch 函数**

在 `renderTasksBody` 后追加：

```javascript
// v2.1：单条任务是否命中搜索词的判断
// q 必须已经 trim + toLowerCase，unitById 是 id → unit 的 Map
function matchTask(task, unitById, q) {
  if (!q) return true;
  // 数字字段：去掉输入里可能的 # 前缀
  const qNum = q.replace(/^#/, "");
  const idStr = String(task.id).toLowerCase();
  if (idStr.includes(qNum)) return true;
  // 任务名
  if ((task.name || "").toLowerCase().includes(q)) return true;
  // 单位名
  const unit = unitById.get(task.unit_id);
  if (unit && (unit.name || "").toLowerCase().includes(q)) return true;
  return false;
}

// v2.1：应用当前 State.taskSearchQuery 到列表 + 更新 UI
function applyTaskSearch() {
  const q = (State.taskSearchQuery || "").trim().toLowerCase();
  const unitById = new Map((State.units || []).map(u => [u.id, u]));
  const tasks = State.tasks || [];
  const matched = q ? tasks.filter(t => matchTask(t, unitById, q)) : tasks;
  renderTasksBody(matched, State.units || []);
  // 计数提示
  const countEl = document.getElementById("task-search-count");
  if (countEl) {
    countEl.textContent = q ? `匹配 ${matched.length} / ${tasks.length} 条` : "";
  }
  // 清空按钮显隐
  const clearBtn = document.getElementById("task-search-clear");
  if (clearBtn) {
    clearBtn.style.display = q ? "block" : "none";
  }
}
```

- [ ] **Step 2: 绑定 input + debounce + clear 按钮**

在文件末尾（其它 event listener 集中处，比如 `document.getElementById("open-create-task").addEventListener` 附近 `app.js:356`）追加：

```javascript
// v2.1：任务列表搜索框事件绑定
let _taskSearchTimer;
(function bindTaskSearch() {
  const input = document.getElementById("task-search");
  const clearBtn = document.getElementById("task-search-clear");
  if (!input || input._bound) return;
  input._bound = true;
  input.addEventListener("input", () => {
    clearTimeout(_taskSearchTimer);
    _taskSearchTimer = setTimeout(() => {
      State.taskSearchQuery = input.value;
      applyTaskSearch();
    }, 200);
  });
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      input.value = "";
      State.taskSearchQuery = "";
      applyTaskSearch();
      input.focus();
    });
  }
})();
```

**关键**：函数外自调 IIFE 保证脚本加载时立即绑定（此时 `#tasks` section 是 hidden 但 DOM 已存在）。绑定用 `input._bound` 防重（跟 `reg-search` 一致模式）。

- [ ] **Step 3: 语法检查**

```bash
node --check /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/frontend/app.js
```

期望：exit 0。

- [ ] **Step 4: 跑 Task 1 的 pytest（应该继续 pass）**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/backend
.venv/bin/python -m pytest tests/test_v21_task_search.py -v
```

期望：`1 passed`。

- [ ] **Step 5: 跑全量回归确认没破**

```bash
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```

期望：`210 passed`（原 209 + 新 1）。

- [ ] **Step 6: Commit（含 Task 3 的改动）**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/frontend/app.js
git commit -m "feat(v2.1): task list search filter with debounce"
```

---

## Task 5：手动 verify + push + 服务器部署

**Files:** 无代码改动

**Interfaces:** 无

- [ ] **Step 1: 本地起服务或直接看现网**

前端是纯静态文件，本地不需要起服务。可以：
1. 直接用浏览器打开 `file:///Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/frontend/index.html`（但会 CORS 报错拉不到 API — 只能验证 UI 布局）
2. 或者直接部署到服务器验证真实场景

推荐做法 2（部署后一次实测）。

- [ ] **Step 2: Push**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git push origin main
```

期望：推送成功，看到 `main -> main` 更新。

- [ ] **Step 3: 服务器拉文件（前端 bind mount 无需 rebuild）**

打 tar 到本地 scratchpad，用户 scp：

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent
tar -czf /private/tmp/claude-501/-Users-lizhishaoniange-Documents-ai-----/cd58db16-3297-4435-b223-ced9268d3256/scratchpad/v2.1.tar.gz \
  frontend/index.html \
  frontend/app.js \
  backend/tests/test_v21_task_search.py
ls -la /private/tmp/claude-501/-Users-lizhishaoniange-Documents-ai-----/cd58db16-3297-4435-b223-ced9268d3256/scratchpad/v2.1.tar.gz
```

告诉用户跑：

```bash
# 本地 mac
scp /private/tmp/claude-501/.../v2.1.tar.gz root@8.163.75.9:/opt/audit/compliance-agent/v2.1.tar.gz

# 服务器
cd /opt/audit/compliance-agent
tar -xzf v2.1.tar.gz
# 前端 bind mount 直接生效，不需要 restart
# 测试同步进 backend 容器
docker compose cp backend/tests/test_v21_task_search.py backend:/app/tests/test_v21_task_search.py
docker compose exec backend python -m pytest tests/test_v21_task_search.py -v
rm v2.1.tar.gz
```

- [ ] **Step 4: 浏览器硬刷新 + 手动 verify 清单**

浏览器 `Cmd+Shift+R` 刷新 `http://8.163.75.9:8000/`，进"核查任务"页，跑以下 8 条：

1. **UI 位置**：搜索框在头部右侧，"新建任务"按钮左边，同一行
2. **输入任务名**：输入前 2 字 → 表格只剩命中行 + 顶部 span 显示 `匹配 X / Y 条`
3. **输入单位名**：输入单位名前 3 字 → 命中该单位所有任务
4. **输入数字编号**：输入 `48018` → 命中该编号任务
5. **输入 `#` 前缀**：输入 `#48018` → 命中同一任务
6. **含空白**：输入 `  会计  ` → 归一化后仍命中
7. **无匹配**：输入 `xxx不存在的字` → tbody 显示"未匹配到任务，请调整关键词"，count span 显示 `匹配 0 / Y`
8. **× 清空**：点右侧 × → 输入清空、表格恢复全量、count span 清空、× 隐藏

- [ ] **Step 5: 报告结果**

- 若 8 条全过：v2.1 上线，任务闭合
- 若某条不符：贴截图 / 具体现象，我针对性修

---

## Self-Review

**Spec coverage 核对**：

| Spec 章节 | 对应任务 |
|-----------|---------|
| UI 位置（`index.html:229-249`，按钮左侧同一行） | Task 2 |
| 匹配任务名 | Task 4 `matchTask` |
| 匹配单位名 | Task 4 `matchTask`（通过 `unitById` 反查） |
| 匹配任务编号，去 `#` 前缀 | Task 4 `matchTask`（`qNum = q.replace(/^#/, "")`） |
| trim + toLowerCase 归一化 | Task 4 `applyTaskSearch` 首行 |
| debounce 200ms | Task 4 IIFE 里 `setTimeout 200` |
| 匹配计数 span | Task 4 `applyTaskSearch` 尾部更新 |
| `×` 清空按钮 | Task 2 HTML + Task 4 click 绑定 |
| 无匹配空态 | Task 3 `renderTasksBody` 分支 |
| `State.taskSearchQuery` 保留搜索词 | Task 3 State 字段 + Task 4 IIFE 写入 |
| 部署 bind mount，浏览器硬刷新即可 | Task 5 |
| pytest 断言 HTML 元素存在 | Task 1 |

无遗漏。

**Placeholder scan**：无 TBD / TODO / "add error handling"。所有代码块都是可直接粘贴的完整实现。

**Type consistency**：`matchTask(task, unitById, q)`、`applyTaskSearch()`、`renderTasksBody(tasks, units)` — 参数命名与调用点一致；`State.taskSearchQuery` 命名前后一致。
