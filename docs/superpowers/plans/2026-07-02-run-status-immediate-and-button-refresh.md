# 核查触发即时 status + 运行按钮刷新 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修两个用户报的 bug（同根因）：核查进度需 F5 才显示 + failed 任务点核查按钮无反应。改法：backend `POST /run` 立即设 `task.status="running"`；frontend 抽 `renderRunButton` 独立函数并在 loadTaskWorkspace / polling 回调里都调用。

**Architecture:** 后端 `audit_routes.py:run_task` 端点在 enqueue celery 之前 3 行代码写入 running 状态，避免"celery 异步 → 前端拿 stale status → polling 不启动"。前端把嵌在 `renderMaterials` 里的 tw-run-btn 渲染逻辑抽独立函数，3 个入口都调它保证按钮跟着 status 走。

**Tech Stack:** Python 3.11 + FastAPI + pytest（backend）；vanilla JS + HTML（frontend）。

## Global Constraints

- 后端只改 `audit_routes.py` POST /run 端点前 5 行 + 加 pytest 文件；不改 DB schema / API 响应 schema
- 前端只改 `app.js`（抽函数、3 处调用）+ `index.html` 版本号
- Button 文案与现有一致：`"核查中…"` / `"重新核查"` / `"触发 AI 核查"`
- 静态资源版本 query 升级 `?v=2.1` → `?v=2.3`
- failed 状态改用 `?force=true` 请求，不弹 confirm 对话框（failed 无 finding/底稿可清）
- 3 秒轮询频率保持不变

---

## File Structure

| 文件 | 变更 | 责任 |
|------|-----|------|
| `compliance-agent/backend/app/api/audit_routes.py:280` 附近 | Modify | run_task 端点在 `run_audit_task.delay` 前设 task.status="running" + progress 字段 |
| `compliance-agent/backend/tests/test_v23_run_status_immediate.py` | Create | 2 条 pytest：POST /run 后立即 status=running；已 running 时二次 POST 拒绝 |
| `compliance-agent/frontend/app.js` | Modify | 抽 `renderRunButton(task, materials)`；`loadTaskWorkspace` 结尾调；轮询回调里调；`renderMaterials` 里改成调新函数；click handler 加 failed→force 分支 |
| `compliance-agent/frontend/index.html` | Modify | 3 处 `?v=2.1` → `?v=2.3` |

---

## Task 1：写 backend RED test

**Files:**
- Create: `compliance-agent/backend/tests/test_v23_run_status_immediate.py`

**Interfaces:**
- Consumes: 无（Task 2 才改 audit_routes.py）
- Produces: 2 条 pytest case，覆盖"POST /run 后立即 status=running"和"已 running 时二次 POST 拒绝 400"

- [ ] **Step 1: 创建测试文件**

`compliance-agent/backend/tests/test_v23_run_status_immediate.py`：

```python
"""v2.3 POST /api/tasks/{id}/run 立即设 task.status=running。

修复"celery 异步 → 前端拿 stale status → polling 不启动"的时序 bug。
"""
from __future__ import annotations

import io
import json
import uuid

import pytest
from fastapi.testclient import TestClient


def _setup_task(client, headers):
    """建 unit + task（scope=selected 只含 I-13）+ 1 份绑到 I-13 的材料。

    返回 task_id。
    """
    suffix = uuid.uuid4().hex[:6]
    r = client.post("/api/units",
                    json={"name": f"v23-{suffix}", "code": f"V23{suffix}"},
                    headers=headers)
    assert r.status_code == 200, r.text
    unit_id = r.json()["id"]

    inds = client.get("/api/indicators", headers=headers).json()
    i13 = next(i for i in inds if i["indicator_code"] == "I-13")

    r = client.post("/api/tasks", json={
        "unit_id": unit_id, "name": f"v23-{suffix}",
        "eval_year": 2026, "scope": "selected",
        "selected_indicator_ids": [i13["id"]],
    }, headers=headers)
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]

    # 上传一份材料绑到 I-13
    files = {"file": (f"v23-{suffix}.txt",
                      io.BytesIO(b"v23 test content 32bytes padding padding"),
                      "text/plain")}
    data = {"indicator_id": str(i13["id"])}
    r = client.post(f"/api/tasks/{task_id}/materials",
                    files=files, data=data, headers=headers)
    assert r.status_code == 200, r.text

    return task_id


def test_run_task_sets_status_running_immediately(auth_headers):
    """v2.3：POST /run 应立即把 task.status 设为 running，
    不必等 celery worker 跑到 orchestrator.run_audit 才生效。"""
    from app.main import app
    # 确保种子指标存在
    from app.seeds.load_indicators_55 import load as load_indicators
    load_indicators(replace=False)

    with TestClient(app, headers=auth_headers) as client:
        task_id = _setup_task(client, auth_headers)

        # POST /run（eager celery 模式下 delay 也同步执行，但接口层的 status
        # 设置必须**先于** delay 调用完成）
        r = client.post(f"/api/tasks/{task_id}/run")
        assert r.status_code == 200, r.text
        body = r.json()
        # POST 响应体里的 task 应已经是 running（或 celery eager 跑完到 ai_done）
        assert body["status"] in ("running", "ai_done"), (
            f"POST /run 响应体 status={body['status']!r}，"
            "至少应先经过 running（非 pending / failed）"
        )

        # 独立 GET 一次也应该看到 running 或 ai_done（celery eager 下可能秒完）
        r = client.get(f"/api/tasks/{task_id}")
        assert r.status_code == 200
        detail = r.json()
        assert detail["task"]["status"] in ("running", "ai_done", "failed"), (
            f"GET status={detail['task']['status']!r}"
        )
        # 关键：不应停留在 pending / 原始状态
        assert detail["task"]["status"] != "pending"


def test_run_task_rejects_when_already_running(auth_headers):
    """v2.3：如果任务已在 running 状态，二次 POST /run 应 400，
    避免用户重复点击导致并发 orchestrator。"""
    from app.main import app
    from app.models import AuditTask, SessionLocal
    from app.seeds.load_indicators_55 import load as load_indicators
    load_indicators(replace=False)

    with TestClient(app, headers=auth_headers) as client:
        task_id = _setup_task(client, auth_headers)

        # 手动把 task.status 设 running 模拟"正在跑"场景
        db = SessionLocal()
        try:
            task = db.get(AuditTask, task_id)
            task.status = "running"
            db.commit()
        finally:
            db.close()

        # 二次 POST /run 应 400
        r = client.post(f"/api/tasks/{task_id}/run")
        assert r.status_code == 400, r.text
        assert "正在核查中" in r.json().get("detail", "")
```

- [ ] **Step 2: 跑测试确认 RED**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/backend
.venv/bin/python -m pytest tests/test_v23_run_status_immediate.py -v --tb=short 2>&1 | tail -15
```

期望：`test_run_task_sets_status_running_immediately` FAIL（当前 audit_routes.py 没主动设 running），另一条 test_run_task_rejects_when_already_running 可能 PASS（现有代码已经拒绝二次 running）。至少 1 条 fail 就算 RED 成立。

- [ ] **Step 3: Commit RED**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/backend/tests/test_v23_run_status_immediate.py
git commit -m "test(v2.3): run endpoint status=running assertions (RED)"
```

---

## Task 2：改 audit_routes.run_task 立即设 status

**Files:**
- Modify: `compliance-agent/backend/app/api/audit_routes.py`（`run_task` 函数，约 line 253-283）

**Interfaces:**
- Consumes: Task 1 的 pytest 断言
- Produces: `POST /api/tasks/{id}/run` 端点在 `log_action` 之前 3 行给 task 设 running/progress，Task 1 变 GREEN

- [ ] **Step 1: 读现有 run_task**

```bash
sed -n '253,290p' /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/compliance-agent/backend/app/api/audit_routes.py 2>/dev/null
# 或
sed -n '253,290p' /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/backend/app/api/audit_routes.py
```

期望看到：

```python
@tasks_router.post("/{task_id}/run", response_model=AuditTaskOut)
def run_task(task_id: int,
             force: bool = Query(False, ...),
             db: Session = Depends(get_db),
             user: User = Depends(require_auditor)):
    task = db.get(AuditTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if not task.materials:
        raise HTTPException(400, "任务下尚无材料，请先上传")
    if task.status == "running":
        raise HTTPException(400, "任务正在核查中，请等待完成后再操作")
    if task.status in ("ai_done", "reviewing", "finalized", "archived") and not force:
        raise HTTPException(400, "任务已完成核查...")
    log_action(db, user, "task.run", ...)
    db.commit()
    run_audit_task.delay(task.id)
    db.refresh(task)
    return task
```

- [ ] **Step 2: 用 Edit 在 log_action 之前插入 status 设置**

```
old_string:
    log_action(db, user, "task.run",
               target_type="task", target_id=task.id,
               detail=f"触发 AI 核查（{len(task.materials)} 份材料"
                      f"{'，强制重跑' if force else ''}）")
    db.commit()
    run_audit_task.delay(task.id)
    db.refresh(task)
    return task
```

改成：

```
new_string:
    # v2.3：立即设 running 状态，让前端 loadTaskWorkspace 拿到新 status 后
    # maybeStartProgressPolling 能立即启动轮询（避免用户看不到进度需 F5）
    task.status = "running"
    task.progress_text = "已提交，等待 worker 拾取…"
    task.progress_current = 0
    task.progress_total = 0
    log_action(db, user, "task.run",
               target_type="task", target_id=task.id,
               detail=f"触发 AI 核查（{len(task.materials)} 份材料"
                      f"{'，强制重跑' if force else ''}）")
    db.commit()
    run_audit_task.delay(task.id)
    db.refresh(task)
    return task
```

- [ ] **Step 3: 跑 Task 1 测试确认 GREEN**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/backend
.venv/bin/python -m pytest tests/test_v23_run_status_immediate.py -v --tb=short 2>&1 | tail -10
```

期望：`2 passed`。

- [ ] **Step 4: 跑全量回归**

```bash
.venv/bin/python -m pytest tests/ -q --tb=short 2>&1 | tail -5
```

期望：`216 passed`（原 214 + v2.3 的 2）。若有已有测试因 status="running" 变化而挂，看错误信息判断是否需 patch。

- [ ] **Step 5: Commit**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/backend/app/api/audit_routes.py
git commit -m "feat(v2.3): run endpoint sets status=running before enqueue"
```

---

## Task 3：前端抽 renderRunButton 独立函数

**Files:**
- Modify: `compliance-agent/frontend/app.js`（renderMaterials 里 line 1587-1606 段抽出）

**Interfaces:**
- Consumes: Task 2 的 backend（POST /run 后 task.status="running"）
- Produces: 全局函数 `renderRunButton(task, materials)` — 读 task.status + materials.length + 已绑数量，更新 `#tw-run-btn` 的 disabled/innerHTML/title/style

- [ ] **Step 1: 定位现有 renderMaterials 里的 button 段**

```bash
sed -n '1585,1610p' /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/compliance-agent/frontend/app.js 2>/dev/null
# 或直接路径
sed -n '1585,1610p' /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/frontend/app.js
```

- [ ] **Step 2: 在 renderMaterials 函数之前（约 app.js:1506 后、renderMaterials 定义前）插入 renderRunButton 函数**

用 Edit 精确定位到 `function renderMaterials()` 起始处，在它上方加：

```
old_string:
function renderMaterials() {
  const d = State.taskDetail;
```

改成：

```
new_string:
// v2.3：抽出的运行按钮渲染逻辑。task.status 变化时任何入口都能刷新按钮
function renderRunButton(task, materials) {
  const runBtn = document.getElementById("tw-run-btn");
  if (!runBtn || !task) return;
  const list = materials || [];
  const total = list.length;
  const bound = list.filter(m => m.indicator_id).length;
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
    const label = status === "failed" ? "重新核查" : "触发 AI 核查";
    runBtn.innerHTML = `${icon("play")} <span>${label}</span>`;
    runBtn.title = allBound ? "" : `仍有 ${total - bound} 份材料未绑定指标`;
  }
  runBtn.style.opacity = runBtn.disabled ? "0.5" : "";
  runBtn.style.cursor = runBtn.disabled ? "not-allowed" : "";
}

function renderMaterials() {
  const d = State.taskDetail;
```

- [ ] **Step 3: 替换 renderMaterials 里 line 1586-1606 段为一行调用**

```
old_string:
  // 触发核查按钮：按任务状态 + 绑定情况 动态切换
  const runBtn = document.getElementById("tw-run-btn");
  if (runBtn) {
    const allBound = total > 0 && bound === total;
    const status = d.task.status;
    if (status === "running") {
      runBtn.disabled = true;
      runBtn.innerHTML = `<span class="tw-progress-spinner" style="border-color:#cfdcf5;border-top-color:#fff;width:12px;height:12px"></span> <span>核查中…</span>`;
      runBtn.title = "任务正在核查中，请等待完成";
    } else if (["ai_done", "reviewing", "finalized", "archived"].includes(status)) {
      runBtn.disabled = !allBound;
      runBtn.innerHTML = `${icon("refresh")} <span>重新核查</span>`;
      runBtn.title = allBound ? "重新核查将清空已有疑点与底稿" : `仍有 ${total - bound} 份材料未绑定指标`;
    } else {
      runBtn.disabled = !allBound;
      runBtn.innerHTML = `${icon("play")} <span>触发 AI 核查</span>`;
      runBtn.title = allBound ? "" : `仍有 ${total - bound} 份材料未绑定指标`;
    }
    runBtn.style.opacity = runBtn.disabled ? "0.5" : "";
    runBtn.style.cursor = runBtn.disabled ? "not-allowed" : "";
  }
}
```

改成：

```
new_string:
  // v2.3：抽独立函数，让 loadTaskWorkspace + 轮询回调都能刷按钮
  renderRunButton(d.task, d.materials);
}
```

- [ ] **Step 4: 语法检查**

```bash
node --check /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/frontend/app.js
```

期望：exit 0（无输出）。

- [ ] **Step 5: 暂不 commit（合并到 Task 4 一起 commit，让前端在中间态可用）**

---

## Task 4：loadTaskWorkspace 和 polling 回调调 renderRunButton；click handler 加 failed→force

**Files:**
- Modify: `compliance-agent/frontend/app.js`（3 处）

**Interfaces:**
- Consumes: Task 3 的 `renderRunButton(task, materials)`
- Produces: 3 处调用 + click handler 里 failed 走 force 分支

- [ ] **Step 1: loadTaskWorkspace 结尾加 renderRunButton 调用**

app.js 大约 line 714-717 现有：

```javascript
    renderTaskActions(detail.task);
    renderProgress(detail.task);
    renderSubtab();
    maybeStartProgressPolling(detail.task);
```

用 Edit 精确替换：

```
old_string:
    renderTaskActions(detail.task);
    renderProgress(detail.task);
    renderSubtab();
    maybeStartProgressPolling(detail.task);
  } catch (e) { toast(e.message, "error"); }
}
```

改成：

```
new_string:
    renderTaskActions(detail.task);
    renderProgress(detail.task);
    renderRunButton(detail.task, detail.materials);   // v2.3
    renderSubtab();
    maybeStartProgressPolling(detail.task);
  } catch (e) { toast(e.message, "error"); }
}
```

- [ ] **Step 2: 轮询回调也调 renderRunButton**

app.js 大约 line 748-757 现有：

```javascript
    try {
      const detail = await api(`/tasks/${taskId}`);
      State.taskDetail = detail;
      renderProgress(detail.task);
      document.getElementById("tw-meta").innerHTML =
        `${esc(detail.unit.name)} · ${detail.task.eval_year} 年度 · ${statusBadge(detail.task.status)}`;
      if (detail.task.status !== "running") {
        stopProgressPolling();
        // 状态变了 → 重渲整个工作台拿底稿、findings 等
        loadTaskWorkspace(taskId);
      }
    } catch (e) {
```

用 Edit：

```
old_string:
      const detail = await api(`/tasks/${taskId}`);
      State.taskDetail = detail;
      renderProgress(detail.task);
      document.getElementById("tw-meta").innerHTML =
        `${esc(detail.unit.name)} · ${detail.task.eval_year} 年度 · ${statusBadge(detail.task.status)}`;
      if (detail.task.status !== "running") {
```

改成：

```
new_string:
      const detail = await api(`/tasks/${taskId}`);
      State.taskDetail = detail;
      renderProgress(detail.task);
      renderRunButton(detail.task, detail.materials);   // v2.3
      document.getElementById("tw-meta").innerHTML =
        `${esc(detail.unit.name)} · ${detail.task.eval_year} 年度 · ${statusBadge(detail.task.status)}`;
      if (detail.task.status !== "running") {
```

- [ ] **Step 3: click handler 加 failed→force 分支**

app.js 大约 line 1804-1822 现有：

```javascript
document.getElementById("tw-run-btn").addEventListener("click", async () => {
  if (!State.taskDetail.materials.length) { toast("请先上传材料", "error"); return; }
  const status = State.taskDetail?.task?.status;
  if (status === "running") {
    toast("任务正在核查中，请等待完成", "warn");
    return;
  }
  let url = `/tasks/${State.taskId}/run`;
  if (["ai_done", "reviewing", "finalized", "archived"].includes(status)) {
    if (!confirm("重新核查将清空已有疑点和工作底稿。\n\n确定继续吗？")) return;
    url += "?force=true";
  }
```

用 Edit：

```
old_string:
  let url = `/tasks/${State.taskId}/run`;
  if (["ai_done", "reviewing", "finalized", "archived"].includes(status)) {
    if (!confirm("重新核查将清空已有疑点和工作底稿。\n\n确定继续吗？")) return;
    url += "?force=true";
  }
```

改成：

```
new_string:
  let url = `/tasks/${State.taskId}/run`;
  if (["ai_done", "reviewing", "finalized", "archived"].includes(status)) {
    if (!confirm("重新核查将清空已有疑点和工作底稿。\n\n确定继续吗？")) return;
    url += "?force=true";
  } else if (status === "failed") {
    // v2.3：failed 无 finding/底稿可清，直接带 force 重跑，不弹确认
    url += "?force=true";
  }
```

- [ ] **Step 4: 语法检查**

```bash
node --check /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/frontend/app.js
```

期望：exit 0。

- [ ] **Step 5: 全量 pytest 再跑一遍确认后端没被前端改动影响**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/backend
.venv/bin/python -m pytest tests/ -q --tb=short 2>&1 | tail -5
```

期望：`216 passed`。

- [ ] **Step 6: Commit Task 3 + 4 一起**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/frontend/app.js
git commit -m "feat(v2.3): extract renderRunButton + wire to loadTaskWorkspace/polling; failed→force"
```

---

## Task 5：升级 index.html 静态资源版本号 ?v=2.3

**Files:**
- Modify: `compliance-agent/frontend/index.html`

**Interfaces:**
- Consumes: 无
- Produces: 强制浏览器重新拉 app.js / styles.css / pinyin_initials.js（避开 disk cache）

- [ ] **Step 1: 用 Edit 一次改 3 处**

替换 styles.css 版本：

```
old_string:
  <link rel="stylesheet" href="/static/styles.css?v=2.1" />
```

改成：

```
new_string:
  <link rel="stylesheet" href="/static/styles.css?v=2.3" />
```

替换 pinyin_initials.js 和 app.js（这两行相邻）：

```
old_string:
<script src="/static/pinyin_initials.js?v=2.1"></script>
<script src="/static/app.js?v=2.1"></script>
```

改成：

```
new_string:
<script src="/static/pinyin_initials.js?v=2.3"></script>
<script src="/static/app.js?v=2.3"></script>
```

- [ ] **Step 2: 验证 3 处都改成 v=2.3**

```bash
grep -n '?v=' /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/frontend/index.html
```

期望 3 行都是 `?v=2.3`：

```
7: <link rel="stylesheet" href="/static/styles.css?v=2.3" />
1295: <script src="/static/pinyin_initials.js?v=2.3"></script>
1296: <script src="/static/app.js?v=2.3"></script>
```

- [ ] **Step 3: Commit**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/frontend/index.html
git commit -m "chore(v2.3): bump static asset cache-buster ?v=2.3"
```

---

## Task 6：Push + 服务器部署 + 浏览器手动 verify

**Files:** 无代码改动

**Interfaces:** 无

- [ ] **Step 1: Push**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git push origin main 2>&1 | tail -3
```

- [ ] **Step 2: 打 v2.3 tar 包**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent
tar -czf /private/tmp/claude-501/-Users-lizhishaoniange-Documents-ai-----/cd58db16-3297-4435-b223-ced9268d3256/scratchpad/v2.3.tar.gz \
  backend/app/api/audit_routes.py \
  backend/tests/test_v23_run_status_immediate.py \
  frontend/app.js \
  frontend/index.html
ls -la /private/tmp/claude-501/-Users-lizhishaoniange-Documents-ai-----/cd58db16-3297-4435-b223-ced9268d3256/scratchpad/v2.3.tar.gz
```

- [ ] **Step 3: 给用户部署命令**

告诉用户在 mac + Workbench 依次跑：

**mac 本地：**

```bash
scp /private/tmp/claude-501/-Users-lizhishaoniange-Documents-ai-----/cd58db16-3297-4435-b223-ced9268d3256/scratchpad/v2.3.tar.gz \
    root@8.163.75.9:/opt/audit/compliance-agent/v2.3.tar.gz
```

**服务器 Workbench：**

```bash
cd /opt/audit/compliance-agent
tar -xzf v2.3.tar.gz
ls -la backend/app/api/audit_routes.py frontend/app.js  # sanity check 文件已到位

# audit_routes 只 backend 服务；worker/enrich_worker 也 cp 保持代码一致
for c in backend worker enrich_worker; do
  docker compose cp backend/app/api/audit_routes.py $c:/app/app/api/audit_routes.py
done
docker compose cp backend/tests/test_v23_run_status_immediate.py \
  backend:/app/tests/test_v23_run_status_immediate.py

# frontend 是 bind mount 到宿主机路径，tar 解包已经到位，无需 cp 进容器
# 但 backend 服务在 restart 时会重启 uvicorn，让新代码生效
docker compose restart backend
sleep 5

# 容器内单测
docker compose exec -T backend python -m pytest tests/test_v23_run_status_immediate.py -v 2>&1 | tail -10
# 期望：2 passed

# 收尾
rm v2.3.tar.gz
```

- [ ] **Step 4: 浏览器手动验证**

**因为 index.html 换了 `?v=2.3`，硬刷 Cmd+Shift+R 或普通刷新都能拿到新 app.js**。

依次做：

1. 打开任意一个 status=failed 的任务详情页
2. 观察 `#tw-run-btn` 应显示 **"重新核查"** 且非 disabled、cursor 可点
3. 点按钮 → 立即（<1 秒）观察：
   - 按钮变 **"核查中…"** + spinner
   - `#tw-progress` 进度栏出现，显示 "已提交，等待 worker 拾取…" 或后续文案
4. 等待 3 秒 → 进度栏文字应更新（轮询启动，`docker compose logs -f worker` 里也应见 `Task audit.run received`）
5. 任务跑完（成功或失败）后 3 秒内 → 按钮自动切回 **"重新核查"** 且可点

**若 step 5 后按钮没自动切**：说明轮询回调里 renderRunButton 没调到，检查 app.js 里 line 751 附近

- [ ] **Step 5: 报告**

- 5 条全过 → v2.3 上线，收工
- 某条不符 → 贴截图 + backend log 尾部

---

## Self-Review

**Spec coverage 核对**：

| Spec 章节 | 对应任务 |
|-----------|---------|
| 目标：F5 才显示进度 → 自动更新 | Task 2（backend 立即 status=running）+ Task 4（轮询回调调 renderRunButton） |
| 目标：failed 按钮 stuck → 自动切换 | Task 3（renderRunButton 单一职责）+ Task 4（loadTaskWorkspace 结尾也调） |
| 修法 A：backend 立即 status="running" + progress 字段 | Task 2 |
| 修法 B：抽 renderRunButton | Task 3 |
| 修法 C：三个入口调 renderRunButton | Task 4（loadTaskWorkspace + polling 回调 + renderMaterials 里改成调新函数） |
| 修法 D：failed 走 force 路径 | Task 4 Step 3 |
| Backend 2 条 pytest | Task 1 |
| 前端手动 verify 5 步 | Task 6 Step 4 |
| index.html 版本号 ?v=2.3 | Task 5 |
| 部署：3 容器 cp audit_routes | Task 6 Step 3 |
| 部署：前端 bind mount 无需 cp | Task 6 Step 3 注释 |

无遗漏。

**Placeholder scan**：无 TBD / TODO / "add error handling"。每一步都是可直接粘贴的完整代码。

**Type consistency**：
- `renderRunButton(task, materials)` — Task 3 定义、Task 4 三处调用签名一致
- 版本号 `?v=2.3` — Task 5 三处 sed 一致
- Task 2 里 `task.status = "running"` / `task.progress_current = 0` / `task.progress_total = 0` — 与 Task 1 断言的 `status in ("running", "ai_done", "failed")` 一致（celery eager 下可能秒完到 ai_done/failed，断言留了灵活性）
