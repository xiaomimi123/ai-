# 核查触发即时 status + 运行按钮刷新（v2.3）

**日期**：2026-07-02
**范围**：backend `audit_routes.py` + frontend `app.js`；无 DB schema / API contract 变更

## 目标

修两个用户报的 bug（同根因）：
1. 前端页面每次都需要 F5 刷新才能显示 AI 核查进度
2. 上次因 402 失败的任务，充值后点"运行核查"按钮无反应（按钮 stuck 在"核查中…"）

修完后：用户点核查后**不 F5 也能立刻看到进度推进**；任务状态从 running 变 failed/ai_done 后按钮自动切换到"重新核查"或"触发 AI 核查"，可正常点击。

## 根因（诊断清楚）

**Backend 时序**：
- `POST /api/tasks/{id}/run`（`audit_routes.py:253-283`）先 `log_action` + `commit` 后调 `run_audit_task.delay(task.id)`，**没有主动把 task.status 改成 "running"**
- `task.status = "running"` 的赋值在 `orchestrator.run_audit`（`orchestrator.py:148`）里 —— 这是 celery worker 异步跑到那时才生效
- 因此 `POST /run` 立即返回给前端时，`task.status` 仍是**旧值**（failed/ai_done/pending）

**Frontend 时序**：
- 用户点核查按钮 → click handler（`app.js:1804-1822`）POST 后立即 `loadTaskWorkspace` → 拿到 stale status
- `maybeStartProgressPolling(task)`（`app.js:742-763`）检查 `if (task.status !== "running") return;` → **不启动轮询**
- 几秒后 celery worker 才真正把 status 改成 running，但前端已经不 polling，进度栏永不更新
- **运行按钮的 render 逻辑**（`app.js:1586-1606`）只在 `renderMaterials()` 内被调 —— 而 `renderMaterials` 只在用户切"材料"tab 时才跑。轮询回调 `loadTaskWorkspace` 后不重渲 `tw-run-btn`
- 按钮永远显示上次的"核查中…"文案 + disabled → 用户以为"点不动"

## 修法（三处）

### 修法 A：backend 立即设 status="running"（`audit_routes.py:281`）

`POST /api/tasks/{task_id}/run` 在 enqueue celery 之前主动设置 status：

```python
# 原有：
log_action(db, user, "task.run", ...)
db.commit()
run_audit_task.delay(task.id)
db.refresh(task)
return task

# 改成：
task.status = "running"
task.progress_text = "已提交，等待 worker 拾取…"
task.progress_current = 0
task.progress_total = 0
log_action(db, user, "task.run", ...)
db.commit()
run_audit_task.delay(task.id)
db.refresh(task)
return task
```

这样 API 响应给前端时 status 已经是 running，前端 polling 会立即启动。

**幂等性**：即便用户在 celery worker 真跑到 orchestrator.run_audit 之前再点一次，backend 现有的 `if task.status == "running": raise 400` 检查会拦下（`audit_routes.py:270`），不会重复 enqueue。

### 修法 B：抽出 `renderRunButton` 独立函数

`app.js` 里把 `renderMaterials()` 里的 line 1586-1606 按钮渲染段抽成独立函数：

```javascript
function renderRunButton(task, materials) {
  const runBtn = document.getElementById("tw-run-btn");
  if (!runBtn) return;
  const total = materials.length;
  const bound = materials.filter(m => m.indicator_id).length;
  const allBound = total > 0 && bound === total;
  const status = task.status;
  if (status === "running") {
    runBtn.disabled = true;
    runBtn.innerHTML = `<span class="tw-progress-spinner" style="border-color:#cfdcf5;border-top-color:#fff;width:12px;height:12px"></span> <span>核查中…</span>`;
    runBtn.title = "任务正在核查中，请等待完成";
  } else if (["ai_done", "reviewing", "finalized", "archived"].includes(status)) {
    runBtn.disabled = !allBound;
    runBtn.innerHTML = `${icon("refresh")} <span>重新核查</span>`;
    runBtn.title = allBound ? "重新核查将清空已有疑点与底稿" : `仍有 ${total - bound} 份材料未绑定指标`;
  } else {
    // 包含 failed / pending / 其它初始状态
    runBtn.disabled = !allBound;
    runBtn.innerHTML = `${icon("play")} <span>${status === "failed" ? "重新核查" : "触发 AI 核查"}</span>`;
    runBtn.title = allBound ? "" : `仍有 ${total - bound} 份材料未绑定指标`;
  }
  runBtn.style.opacity = runBtn.disabled ? "0.5" : "";
  runBtn.style.cursor = runBtn.disabled ? "not-allowed" : "";
}
```

`renderMaterials()` 里删掉那段（1586-1606），改调 `renderRunButton(d.task, d.materials)`。

### 修法 C：三个入口都调 `renderRunButton`

保证 button 状态跟着 task.status 走：

1. `loadTaskWorkspace(taskId)` 结尾（`app.js:717` 附近）加：
   ```javascript
   renderRunButton(detail.task, detail.materials);
   ```
2. `maybeStartProgressPolling` 的轮询回调（`app.js:750-757`）加：
   ```javascript
   renderRunButton(detail.task, detail.materials);
   ```
3. `renderMaterials()` 结尾保留调用（作为向后兼容 —— 切材料 tab 时也会跑）

### 修法 D：failed 状态也走 force 路径（一致性）

click handler（`app.js:1804-1822`）改成 failed 状态也带 `?force=true`：

```javascript
if (["ai_done", "reviewing", "finalized", "archived", "failed"].includes(status)) {
  if (status !== "failed") {   // failed 无 finding 可清，不弹确认
    if (!confirm("重新核查将清空已有疑点和工作底稿。\n\n确定继续吗？")) return;
  }
  url += "?force=true";
}
```

**为什么**：backend `audit_routes.py:271` 的 blacklist 是 `("ai_done", "reviewing", "finalized", "archived")`，`failed` 不在里面，不用 force 也能过。但如果哪天扩展了 blacklist，`failed` 显式带 force 更稳。且 failed 没有可清的数据（v2.2 已让 orchestrator 走到 except 后没写 finding），不弹确认更符合用户预期。

## 非目标（YAGNI）

- 不改 celery task 的实现
- 不新增 API endpoint
- 不改 DB schema（`AuditTask.status` 沿用现有值域）
- 不做 SSE / WebSocket（3s 轮询已经够，YAGNI）
- 不加"重试次数"计数

## 涉及文件

| 文件 | 变更 | 责任 |
|------|-----|------|
| `compliance-agent/backend/app/api/audit_routes.py` | Modify（`:253-283` 段） | POST /run 立即设 status="running" + progress 字段 |
| `compliance-agent/backend/tests/test_v23_run_status_immediate.py` | Create | 2 条 case：POST /run 后 task.status="running"；task 已 running 时二次 POST 拒绝 |
| `compliance-agent/frontend/app.js` | Modify | 抽 `renderRunButton`；loadTaskWorkspace / 轮询回调 / renderMaterials 三处调；failed 状态走 force 路径 |
| `compliance-agent/frontend/index.html` | Modify | `?v=2.1` → `?v=2.3` 刷缓存 |

## 测试计划

### 单元/集成（backend）

1. `test_run_task_sets_status_running_immediately`：
   - 建 unit + task + 1 material（绑定 I-13）
   - POST /api/tasks/{id}/run
   - 立即拉 GET /api/tasks/{id} 断言 task.status == "running"

2. `test_run_task_rejects_when_already_running`：
   - 手动把 task.status 设为 "running"
   - POST /api/tasks/{id}/run 应 400 "任务正在核查中"

### 手动验证（前端）

浏览器（硬刷 `Cmd+Shift+R` 或换 `?v=2.3` 确保新代码生效）：

1. 找一个 status=failed 的任务进入详情页
2. 观察 `tw-run-btn` 应显示 **"重新核查"** 且**可点**（非 disabled）
3. 点按钮 → 立即（<1 秒）能看到：
   - 按钮变"核查中…"
   - 进度条出现，显示"已提交，等待 worker 拾取…"或后续 orchestrator 内推进
4. 3 秒后进度条应有更新（轮询生效）
5. 任务跑完（成功/失败）后 <3 秒 button 自动切回"重新核查"，可再次点击

## 部署

标准 cp + restart 流程：

```bash
# mac
scp compliance-agent/backend/app/api/audit_routes.py root@8.163.75.9:/opt/audit/compliance-agent/backend/app/api/audit_routes.py
scp compliance-agent/backend/tests/test_v23_run_status_immediate.py root@8.163.75.9:/opt/audit/compliance-agent/backend/tests/test_v23_run_status_immediate.py
scp compliance-agent/frontend/app.js root@8.163.75.9:/opt/audit/compliance-agent/frontend/app.js
scp compliance-agent/frontend/index.html root@8.163.75.9:/opt/audit/compliance-agent/frontend/index.html
```

或者打 tar 包一次传，同 v2.1/v2.2 做法。

## 回滚

单个 commit revert；或者手动改回原来的 `audit_routes.py:281` 段 + 恢复 `renderMaterials` 里 1586-1606 那段。
