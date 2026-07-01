# 核查任务列表搜索框（v2.1）

**日期**：2026-07-01
**范围**：前端单文件改动，无后端 API 变更
**决策**：方案 B（前端 filter + 重渲染），不含拼音首字母匹配

## 目标

在「核查任务」页面（`index.html:229` 起的 `<section id="tasks">`）头部右上角新建任务按钮左侧，加一个搜索输入框，让审查员能通过任务名 / 被检查单位名 / 任务编号快速定位一条任务。

## 动机

- 系统累积任务数会持续增长，任务列表按 `id DESC` 排序，老任务翻页找很低效
- 项目已在评价指标（`app.js:2853`）、法规（`app.js:2194`）页实现同类搜索，交互一致降低认知成本
- 后端 `GET /api/tasks`（`audit_routes.py:117`）一次性拉全部到 `State.tasks`，纯前端 filter 无网络开销

## 非目标（YAGNI）

- 不搜索"结论摘要 / summary"字段
- 不搜索任务下的材料 / findings / 指标（属于全局搜索的范畴，后续版本）
- 不加拼音首字母匹配（用户拒绝该扩展）
- 不做匹配文字高亮
- 不改后端 `list_tasks` API
- 不做搜索历史 / localStorage 持久化

## UI

**位置**：`index.html:229-249` `<section id="tasks">` 头部。当前 `<h1>核查任务</h1>` 和 `<button id="open-create-task">新建任务</button>` 之间加一个 `<div class="search-input">` 包裹的 input，风格复用 `#reg-search` / `#ind-search`。

```
┌─────────────────────────────────────────────────────────────────┐
│ 核查任务                        [🔍 输入任务名/单位/编号] [+ 新建任务] │
│ 一个任务对应一个被检查单位的一次内控评价复核。                          │
└─────────────────────────────────────────────────────────────────┘
```

**元素**：
- `<input id="task-search" placeholder="搜索任务名 / 单位 / 编号">`
- `<span id="task-search-count" class="text-xs text-muted">`：显示 `匹配 X / Y 条`，无输入时空
- 输入框右侧 `×` 清空按钮（跟 `#reg-search` 保持一致的 UI 结构）

## 匹配规则

输入 `q` 经过 `String(q).trim().toLowerCase()` 归一化后，任一命中即算命中：

| 字段 | 匹配方式 |
|------|---------|
| `task.name` | `.toLowerCase().includes(q)` |
| `unit.name` | 从 `State.units` 里按 `unit_id` 查到 unit，`.toLowerCase().includes(q)` |
| `String(task.id)` | 支持 `48018` 直接命中；也兼容用户粘贴带前缀的 `#48018`（匹配前把 `#` 去掉） |

**归一化**：
- 输入 `.trim().toLowerCase()`
- 匹配任务 id 前先剥掉输入里的 `#` 前缀（如 `#48018` → `48018`）
- 中文本身无大小写概念，`toLowerCase()` 主要为了兼容英文任务名（如 "Q1"）

## 交互

- 输入触发 `oninput` → 200ms debounce → `applyTaskSearch()`
- `applyTaskSearch()`：从 `State.tasks` 上 `.filter(matchFn)` 得到 matched → `renderTasksBody(matched)` → 更新计数 span
- 无输入（空字符串或全空白）→ 展示 `State.tasks` 完整列表，计数 span 清空
- 无匹配 → tbody 显示 `<tr><td colspan="7" class="empty-state">未匹配到任务，请调整关键词</td></tr>`
- `×` 清空按钮 → 输入框 `value = ""` + 触发 `applyTaskSearch()` 立即恢复全量

## 数据流

```
input.oninput
  → clearTimeout / setTimeout 200ms
  → State.taskSearchQuery = input.value.trim()
  → applyTaskSearch()
      → matched = State.tasks.filter(matchFn)
      → renderTasksBody(matched)   # 抽出 loadTasks 里的 tbody 渲染逻辑
      → updateCount(matched.length, State.tasks.length)
```

**新增全局状态**：`State.taskSearchQuery` 初始 `""`。用于二次 `loadTasks()` 后（比如新建任务返回列表）保留搜索词。

## 涉及文件

只改前端 1 个文件 + HTML 结构：

| 文件 | 改动 |
|------|------|
| `compliance-agent/frontend/index.html:229-249` 头部 | 加 `<input id="task-search">` + 清空 `×` + `<span id="task-search-count">` |
| `compliance-agent/frontend/app.js` `State` 对象 | 加 `taskSearchQuery: ""` |
| `compliance-agent/frontend/app.js:320` `loadTasks()` | 抽出 tbody 渲染部分为 `renderTasksBody(tasks)`；`loadTasks` 尾部调 `applyTaskSearch()` 以尊重现有搜索词 |
| `compliance-agent/frontend/app.js` 新增 `applyTaskSearch()` / `renderTasksBody()` / debounce 绑定 | ~40 行 |

## 测试计划

前端无自动测试框架，本次以**手动 verify** 为主，同时补一个 pytest 层的最小校验，避免 spec 与实现漂移：

**手动 verify 清单**（部署完在浏览器跑一遍）：
1. 输入完整任务名前 2 字 → 表格只剩命中行，计数显示 `匹配 X / Y`
2. 输入单位名前 3 字 → 命中该单位所有任务
3. 输入 5 位数字 `48018` → 命中该编号任务
4. 输入 `#48018` → 同上（去 `#` 前缀）
5. 输入含空白 `  会计  ` → 归一化后正确匹配
6. 输入 `xxx不存在的字` → 显示"未匹配到任务"
7. 点 `×` → 输入框清空、表格恢复全量、计数 span 清空
8. 切到其它页面再切回来 → 搜索词保留（`State.taskSearchQuery` 未清）

**自动化最小校验**（一条 pytest，保证 UI 元素被加进去，不测行为）：
- `tests/test_v21_task_search.py`：读 `index.html`，断言 `id="task-search"` 与 `id="task-search-count"` 存在

## 部署

前端是 `bind mount` 到容器（`docker-compose.yml` backend volume `./frontend:/frontend:ro`），本地 scp 或 git pull 后**浏览器硬刷新即生效**，无需 docker restart 无需 rebuild。

## 回滚

删掉 `#task-search` 相关三段 JS + HTML 输入框元素，回到原状。0 副作用，因为 `renderTasksBody` 抽取只是把 loadTasks 里已有的 map 移出来，逻辑等价。
