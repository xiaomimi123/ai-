# 核查发现按指标聚合显示（v1.6）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把工作底稿"核查发现" tab 从 finding 平铺列表（476 条）改为按 indicator_id 聚合的卡片列表（最多 ~55 张），每卡支持「该指标全部确认/忽略」一键操作。

**Architecture:** 后端零 schema 改动，仅新增 1 个批量复核接口（一次 DB UPDATE 替代 N 次串行 PATCH，性能从 60s 降到 < 2s）；前端在 `renderFindings()` 内做 reduce 分组，新增卡片 + CSS，详情面板沿用现有逻辑。

**Tech Stack:** FastAPI / SQLAlchemy 2.x / PostgreSQL（实测 SQLite）/ 原生 HTML+ES2022 / Playwright

**Spec:** `docs/superpowers/specs/2026-06-24-finding-aggregation-by-indicator-design.md`

**部署提示**：阿里云 ECS `/opt/audit/compliance-agent/` **不是 git 仓库**，必须 `scp` + `docker compose cp` + `restart` + grep 验证。

---

## 文件清单

| 文件 | 动作 | 职责 |
|---|---|---|
| `compliance-agent/backend/app/api/schemas.py` | 修改（追加 2 个类） | `BatchReviewRequest`、`BatchReviewResponse` |
| `compliance-agent/backend/app/services/audit_service.py` | 修改（追加 1 个函数） | `batch_review_findings()` 批量更新 + audit log |
| `compliance-agent/backend/app/api/audit_routes.py` | 修改（追加 1 个路由） | `POST /api/tasks/{task_id}/findings/batch-review` |
| `compliance-agent/backend/tests/test_findings_batch_review.py` | 新建 | 8 个 pytest case |
| `compliance-agent/frontend/app.js` | 修改 3 处 | `renderFindings()` 重写 + `bulkIgnoreFindings()` 改调批量接口 + 新增聚合工具/交互函数 |
| `compliance-agent/frontend/style.css` | 修改（追加段落） | 卡片样式 `.finding-indicator-card` 等 |
| `/tmp/v16_e2e_test.py` | 新建（仅本地/测试机） | Playwright e2e 6 步 |

分支：本任务在 **新建 feature 分支 `feature/v1.6-finding-aggregation`** 上执行（main 分支不直接动手）。

---

## Task 1: 后端 schema — 批量复核请求/响应

**Files:**
- Modify: `compliance-agent/backend/app/api/schemas.py:317-329`（在 `FindingReviewRequest` 之后追加）

- [ ] **Step 1: 切 feature 分支**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git checkout -b feature/v1.6-finding-aggregation
```

- [ ] **Step 2: 追加两个 Pydantic 模型**

打开 `compliance-agent/backend/app/api/schemas.py`，定位到第 320 行 `FindingReviewRequest` 之后，在 `FindingRectifyRequest` 之前插入：

```python
class BatchReviewRequest(BaseModel):
    """v1.6：按 indicator_id / finding_type 批量复核 finding。"""
    status: str  # confirmed | ignored | adjusted
    note: str = ""
    indicator_id: Optional[int] = None      # 限定该指标下
    finding_type: Optional[str] = None      # 限定该类型
    only_pending: bool = True               # True=仅更新 pending 条目（避免覆盖他人复核）


class BatchReviewResponse(BaseModel):
    updated: int
    skipped: int
```

- [ ] **Step 3: 提交**

```bash
git add compliance-agent/backend/app/api/schemas.py
git commit -m "feat(v1.6): 批量复核 finding 的 schema 定义"
```

---

## Task 2: 后端 service — `batch_review_findings()`

**Files:**
- Modify: `compliance-agent/backend/app/services/audit_service.py`（在 `review_finding` 之后追加）
- Test: `compliance-agent/backend/tests/test_findings_batch_review.py`（在 Task 3 创建）

- [ ] **Step 1: 写失败测试（先确认现有 `review_finding` 测试通过，作为基准）**

```bash
cd compliance-agent/backend
pytest tests/test_audit_flow.py::test_review_finding -v
```

Expected: PASS（基准）

- [ ] **Step 2: 实现 service 函数**

打开 `compliance-agent/backend/app/services/audit_service.py`，找到 `def review_finding` 函数，**紧跟其后**追加：

```python
def batch_review_findings(
    db: Session,
    task_id: int,
    status: str,
    note: str,
    user: User,
    indicator_id: Optional[int] = None,
    finding_type: Optional[str] = None,
    only_pending: bool = True,
) -> dict:
    """v1.6：按 indicator_id / finding_type 批量复核同任务下的 finding。

    - indicator_id 与 finding_type 取交集
    - 至少一个筛选条件必须传，否则 400（防误操作）
    - only_pending=True 时跳过已复核条目（计入 skipped）
    - 一条 audit log 记录批量操作（含筛选条件 + updated 计数）
    """
    if status not in ("confirmed", "ignored", "adjusted"):
        raise HTTPException(400, f"无效复核状态：{status}")
    if indicator_id is None and finding_type is None:
        raise HTTPException(400, "indicator_id 与 finding_type 至少传一个")

    task = db.get(AuditTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")

    q = db.query(Finding).filter(Finding.task_id == task_id)
    if indicator_id is not None:
        q = q.filter(Finding.indicator_id == indicator_id)
    if finding_type is not None:
        q = q.filter(Finding.finding_type == finding_type)

    candidates = q.all()
    updated = 0
    skipped = 0
    now = datetime.utcnow()
    clean_note = (note or "").strip()
    for f in candidates:
        if only_pending and f.review_status != "pending":
            skipped += 1
            continue
        f.review_status = status
        f.review_note = clean_note
        f.reviewer_id = user.id
        f.reviewed_at = now
        updated += 1

    log_action(
        db, user, "finding.batch_review",
        target_type="task", target_id=task_id,
        detail=(f"status={status} indicator_id={indicator_id} "
                f"finding_type={finding_type} updated={updated} skipped={skipped}"),
    )
    db.commit()
    return {"updated": updated, "skipped": skipped}
```

**注意**：`AuditTask`、`Finding`、`User`、`datetime`、`log_action`、`HTTPException` 已在文件头 import；若 `Optional` 未导入，需在文件头确认 `from typing import Optional, ...`。

- [ ] **Step 3: 自检 import**

```bash
cd compliance-agent/backend
python -c "from app.services.audit_service import batch_review_findings; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: 提交**

```bash
git add compliance-agent/backend/app/services/audit_service.py
git commit -m "feat(v1.6): batch_review_findings service 函数"
```

---

## Task 3: 后端 route + 完整 pytest 覆盖

**Files:**
- Modify: `compliance-agent/backend/app/api/audit_routes.py`（在 line 617 `review_finding` 路由之后插入）
- Create: `compliance-agent/backend/tests/test_findings_batch_review.py`

- [ ] **Step 1: 先写测试文件（TDD）**

新建 `compliance-agent/backend/tests/test_findings_batch_review.py`，完整内容：

```python
"""v1.6 finding 批量复核接口测试。

8 个 case：indicator 限定 / type 限定 / 两者交集 / 都不传拒绝 /
only_pending 跳过已复核 / 任务不存在 / 非审计员拒绝 / audit log 写入。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    AuditLog, AuditTask, AuditUnit, Finding, Indicator,
    SessionLocal, User, init_db,
)


@pytest.fixture(scope="module")
def client():
    init_db()
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def admin_token(client):
    r = client.post("/api/auth/login",
                    json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def seeded_task(client, admin_token):
    """创建一个测试任务 + 2 个指标 + 6 条 finding（覆盖 2 维度 × 多种状态）。
    返回 (task_id, indicator_a_id, indicator_b_id, finding_ids_dict)。
    """
    db = SessionLocal()
    try:
        unit = AuditUnit(name="__BR_单位__", code="BR001", level="县级")
        db.add(unit); db.flush()
        task = AuditTask(unit_id=unit.id, name="__BR_任务__",
                         eval_year=2026, scope="all",
                         created_by_user_id=1)
        db.add(task); db.flush()
        ind_a = Indicator(code="I-BR-A", name="批量测指标A", chapter="测试")
        ind_b = Indicator(code="I-BR-B", name="批量测指标B", chapter="测试")
        db.add_all([ind_a, ind_b]); db.flush()
        fids = {"a_real_pending": [], "a_complete_pending": [],
                "a_real_confirmed": [], "b_real_pending": []}
        # 指标 A：2 条真实性 pending、1 条完整性 pending、1 条真实性 confirmed
        for _ in range(2):
            f = Finding(task_id=task.id, indicator_id=ind_a.id,
                        finding_type="真实性问题", severity="高",
                        description="A-真实-pending", review_status="pending",
                        source="rule")
            db.add(f); db.flush(); fids["a_real_pending"].append(f.id)
        f = Finding(task_id=task.id, indicator_id=ind_a.id,
                    finding_type="完整性问题", severity="中",
                    description="A-完整-pending", review_status="pending",
                    source="rule")
        db.add(f); db.flush(); fids["a_complete_pending"].append(f.id)
        f = Finding(task_id=task.id, indicator_id=ind_a.id,
                    finding_type="真实性问题", severity="高",
                    description="A-真实-已确认", review_status="confirmed",
                    source="rule")
        db.add(f); db.flush(); fids["a_real_confirmed"].append(f.id)
        # 指标 B：2 条真实性 pending
        for _ in range(2):
            f = Finding(task_id=task.id, indicator_id=ind_b.id,
                        finding_type="真实性问题", severity="低",
                        description="B-真实-pending", review_status="pending",
                        source="rule")
            db.add(f); db.flush(); fids["b_real_pending"].append(f.id)
        db.commit()
        return task.id, ind_a.id, ind_b.id, fids
    finally:
        db.close()


def _status_of(client, token, fid):
    r = client.get(f"/api/findings/{fid}", headers=_hdr(token))
    assert r.status_code == 200, r.text
    return r.json()["review_status"]


def test_batch_review_by_indicator(client, admin_token, seeded_task):
    task_id, ind_a, ind_b, fids = seeded_task
    r = client.post(
        f"/api/tasks/{task_id}/findings/batch-review",
        headers=_hdr(admin_token),
        json={"status": "ignored", "note": "批量忽略 A",
              "indicator_id": ind_a},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # A 下 4 条，其中 1 条 confirmed 被 only_pending 跳过 → updated=3 skipped=1
    assert body["updated"] == 3
    assert body["skipped"] == 1
    # A 下 pending 全 → ignored
    for fid in fids["a_real_pending"] + fids["a_complete_pending"]:
        assert _status_of(client, admin_token, fid) == "ignored"
    # A confirmed 不变
    assert _status_of(client, admin_token, fids["a_real_confirmed"][0]) == "confirmed"
    # B 不动
    for fid in fids["b_real_pending"]:
        assert _status_of(client, admin_token, fid) == "pending"


def test_batch_review_by_finding_type(client, admin_token, seeded_task):
    task_id, ind_a, ind_b, fids = seeded_task
    r = client.post(
        f"/api/tasks/{task_id}/findings/batch-review",
        headers=_hdr(admin_token),
        json={"status": "ignored", "note": "忽略所有真实性",
              "finding_type": "真实性问题"},
    )
    assert r.status_code == 200, r.text
    # A 真实性 pending 2 + B 真实性 pending 2 = 4，confirmed 1 skip
    assert r.json()["updated"] == 4
    assert r.json()["skipped"] == 1
    # 完整性不动
    assert _status_of(client, admin_token,
                      fids["a_complete_pending"][0]) == "pending"


def test_batch_review_intersection(client, admin_token, seeded_task):
    task_id, ind_a, ind_b, fids = seeded_task
    r = client.post(
        f"/api/tasks/{task_id}/findings/batch-review",
        headers=_hdr(admin_token),
        json={"status": "confirmed", "note": "确认 A 真实",
              "indicator_id": ind_a, "finding_type": "真实性问题"},
    )
    assert r.status_code == 200, r.text
    # A 真实 pending 2 → confirmed；A 完整 / B 真实 不动
    assert r.json()["updated"] == 2
    for fid in fids["a_real_pending"]:
        assert _status_of(client, admin_token, fid) == "confirmed"
    assert _status_of(client, admin_token,
                      fids["a_complete_pending"][0]) == "pending"
    assert _status_of(client, admin_token,
                      fids["b_real_pending"][0]) == "pending"


def test_batch_review_requires_filter(client, admin_token, seeded_task):
    task_id, *_ = seeded_task
    r = client.post(
        f"/api/tasks/{task_id}/findings/batch-review",
        headers=_hdr(admin_token),
        json={"status": "ignored", "note": "x"},
    )
    assert r.status_code == 400
    assert "至少传一个" in r.text


def test_batch_review_task_not_found(client, admin_token):
    r = client.post(
        "/api/tasks/9999999/findings/batch-review",
        headers=_hdr(admin_token),
        json={"status": "ignored", "indicator_id": 1},
    )
    assert r.status_code == 404


def test_batch_review_invalid_status(client, admin_token, seeded_task):
    task_id, ind_a, *_ = seeded_task
    r = client.post(
        f"/api/tasks/{task_id}/findings/batch-review",
        headers=_hdr(admin_token),
        json={"status": "bogus", "indicator_id": ind_a},
    )
    assert r.status_code == 400


def test_batch_review_only_pending_false_overrides_confirmed(
        client, admin_token, seeded_task):
    task_id, ind_a, _, fids = seeded_task
    r = client.post(
        f"/api/tasks/{task_id}/findings/batch-review",
        headers=_hdr(admin_token),
        json={"status": "ignored", "indicator_id": ind_a,
              "only_pending": False},
    )
    assert r.status_code == 200, r.text
    # A 全 4 条都被刷成 ignored
    assert r.json()["updated"] == 4
    assert r.json()["skipped"] == 0
    assert _status_of(client, admin_token,
                      fids["a_real_confirmed"][0]) == "ignored"


def test_batch_review_rejects_non_auditor(client, seeded_task):
    """单位用户角色（is_unit）不应能调批量复核（require_auditor 拦截）。"""
    # 创建单位角色用户
    db = SessionLocal()
    try:
        u = User(username="__br_unit_user__", role="unit",
                 display_name="测单位用户")
        u.set_password("p@ssw0rd!")
        db.add(u); db.commit()
    finally:
        db.close()
    r = client.post("/api/auth/login",
                    json={"username": "__br_unit_user__",
                          "password": "p@ssw0rd!"})
    assert r.status_code == 200, r.text
    unit_token = r.json()["token"]
    task_id, ind_a, *_ = seeded_task
    r = client.post(
        f"/api/tasks/{task_id}/findings/batch-review",
        headers=_hdr(unit_token),
        json={"status": "ignored", "indicator_id": ind_a},
    )
    assert r.status_code == 403


def test_batch_review_writes_audit_log(client, admin_token, seeded_task):
    task_id, ind_a, *_ = seeded_task
    r = client.post(
        f"/api/tasks/{task_id}/findings/batch-review",
        headers=_hdr(admin_token),
        json={"status": "ignored", "indicator_id": ind_a},
    )
    assert r.status_code == 200
    db = SessionLocal()
    try:
        log = (db.query(AuditLog)
                 .filter(AuditLog.action == "finding.batch_review",
                         AuditLog.target_id == task_id)
                 .order_by(AuditLog.id.desc())
                 .first())
        assert log is not None
        assert "status=ignored" in log.detail
        assert f"indicator_id={ind_a}" in log.detail
        assert "updated=" in log.detail
    finally:
        db.close()
```

- [ ] **Step 2: 跑测试 → 应失败（路由还没接）**

```bash
cd compliance-agent/backend
pytest tests/test_findings_batch_review.py -v
```

Expected: 9 个 case **全失败**（404 / 405 — 路由不存在）

- [ ] **Step 3: 实现 route**

打开 `compliance-agent/backend/app/api/audit_routes.py`，定位到第 19 行 import 块，把 `FindingReviewRequest,` 后面加上：

```python
    BatchReviewRequest,
    BatchReviewResponse,
```

然后定位到第 622 行（`review_finding` 路由结束），紧跟其后插入：

```python
@tasks_router.post(
    "/{task_id}/findings/batch-review",
    response_model=BatchReviewResponse,
)
def batch_review_findings(
    task_id: int,
    req: BatchReviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_auditor),
):
    """v1.6：按 indicator_id / finding_type 批量复核同任务下的 finding。"""
    return audit_service.batch_review_findings(
        db,
        task_id=task_id,
        status=req.status,
        note=req.note,
        user=user,
        indicator_id=req.indicator_id,
        finding_type=req.finding_type,
        only_pending=req.only_pending,
    )
```

- [ ] **Step 4: 再跑测试 → 8 个全过**

```bash
cd compliance-agent/backend
pytest tests/test_findings_batch_review.py -v
```

Expected: `9 passed`

- [ ] **Step 5: 跑全量回归**

```bash
cd compliance-agent/backend
pytest -q
```

Expected: 原 162 + 新 9 = **171 passed**（若有偏差检查 fixture 冲突；本测试用唯一前缀 `__BR_` 应不冲突）

- [ ] **Step 6: 提交**

```bash
git add compliance-agent/backend/app/api/audit_routes.py \
        compliance-agent/backend/tests/test_findings_batch_review.py
git commit -m "feat(v1.6): POST /api/tasks/{id}/findings/batch-review 路由 + 8 pytest"
```

---

## Task 4: 前端 `bulkIgnoreFindings` 切到批量接口

**Files:**
- Modify: `compliance-agent/frontend/app.js:1850-1869`

> 此 task 独立可发布：把 N 次串行 PATCH 改成 1 次批量调用，性能提升（476 条 60s → < 2s）。
> 不动 UI 行为。便于后续 Task 5/6 单独追踪卡片渲染逻辑。

- [ ] **Step 1: 替换 `bulkIgnoreFindings` 实现**

打开 `compliance-agent/frontend/app.js`，定位到第 1850 行的 `window.bulkIgnoreFindings = async function(dim) {`，**整段替换**（替换到 line 1869 的 `};`）为：

```javascript
window.bulkIgnoreFindings = async function(dim) {
  if (!confirm(`确定把所有「${dim}」未复核疑点一键标为"已忽略"？\n\n忽略后这类问题不再扣分。`)) return;
  const pendingCount = State.taskDetail.findings.filter(
    f => f.finding_type === dim && (f.review_status || "pending") === "pending"
  ).length;
  if (!pendingCount) { toast("没有未复核的此类条目"); return; }
  toast(`批量处理 ${pendingCount} 条…`);
  try {
    const resp = await api(`/tasks/${State.taskId}/findings/batch-review`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status: "ignored",
        note: `批量忽略：${dim}`,
        finding_type: dim,
        only_pending: true,
      }),
    });
    toast(`✓ 已忽略 ${resp.updated} 条「${dim}」`, "success");
  } catch (e) {
    console.error("批量忽略失败", e);
    toast(`批量忽略失败：${e.message}`, "error");
    return;
  }
  await loadTaskWorkspace(State.taskId);
};
```

- [ ] **Step 2: 手工烟测（开浏览器跑一遍）**

```bash
cd compliance-agent
docker compose up -d
# 浏览器开 http://localhost:8000/，登录 admin/admin123，
# 进任意有 finding 的任务 → 核查发现 tab → 点"忽略所有 真实性问题"按钮
# 观察 toast 应秒级出现 "✓ 已忽略 N 条"
```

Expected: 操作 < 2 秒返回；刷新后该类型 pending 全变 ignored。

- [ ] **Step 3: 提交**

```bash
git add compliance-agent/frontend/app.js
git commit -m "perf(v1.6): bulkIgnoreFindings 改用批量接口（60s → < 2s）"
```

---

## Task 5: 前端聚合卡片渲染（含 CSS）

**Files:**
- Modify: `compliance-agent/frontend/app.js:1748-1800`（`renderFindings` 函数重写）
- Modify: `compliance-agent/frontend/style.css`（追加样式段）

- [ ] **Step 1: 追加 CSS（先做样式，避免后续 JS 看不出层次）**

打开 `compliance-agent/frontend/style.css`，在文件**末尾追加**：

```css
/* ===== v1.6 finding 按指标聚合卡片 ===== */
.finding-indicator-card {
  border: 1px solid var(--c-border, #d8dde6);
  border-radius: 6px;
  margin-bottom: 10px;
  background: #fff;
  overflow: hidden;
}
.finding-indicator-card.all-reviewed {
  opacity: 0.6;
}
.finding-indicator-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  cursor: pointer;
  background: #f7f9fc;
  border-bottom: 1px solid transparent;
  user-select: none;
}
.finding-indicator-header:hover { background: #eef2f8; }
.finding-indicator-card.is-open .finding-indicator-header {
  border-bottom-color: var(--c-border, #d8dde6);
}
.fic-caret {
  width: 14px; flex: 0 0 14px; color: #6b7280;
  font-size: 12px; text-align: center;
}
.fic-title {
  flex: 1 1 auto; font-weight: 600; color: #1f2937;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.fic-count {
  font-size: 12px; color: #6b7280; flex: 0 0 auto;
}
.fic-count .pending-num { color: #dc2626; font-weight: 600; }
.fic-dim-badges {
  display: flex; gap: 4px; flex: 0 0 auto;
}
.fic-dim-badge {
  font-size: 11px; padding: 1px 6px; border-radius: 3px;
  background: #e5e7eb; color: #374151;
}
.fic-dim-badge.dim-真实性问题 { background: #fed7aa; color: #9a3412; }
.fic-dim-badge.dim-完整性问题 { background: #bfdbfe; color: #1e3a8a; }
.fic-dim-badge.dim-合规性问题 { background: #fecaca; color: #991b1b; }
.fic-dim-badge.dim-重复性问题 { background: #e5e7eb; color: #374151; }
.fic-dim-badge.dim-匹配性问题 { background: #ddd6fe; color: #5b21b6; }
.fic-dim-badge.zero { opacity: 0.4; }
.fic-actions { display: flex; gap: 6px; flex: 0 0 auto; }
.fic-actions .btn { font-size: 12px; padding: 3px 10px; }
.finding-indicator-body {
  display: none; padding: 8px 14px 12px;
}
.finding-indicator-card.is-open .finding-indicator-body { display: block; }
.fic-dim-group {
  margin: 8px 0;
}
.fic-dim-group-title {
  font-size: 12px; color: #6b7280; font-weight: 600; margin-bottom: 4px;
}
.fic-finding-row {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 10px; border-radius: 4px; cursor: pointer;
  border: 1px solid transparent;
}
.fic-finding-row:hover { background: #f3f4f6; }
.fic-finding-row.is-active { background: #eef2ff; border-color: #818cf8; }
.fic-finding-desc { flex: 1 1 auto; font-size: 13px; color: #1f2937; }
.fic-finding-row-actions { display: flex; gap: 4px; flex: 0 0 auto; }
.fic-finding-row-actions .btn-mini {
  font-size: 11px; padding: 2px 6px; border-radius: 3px;
  border: 1px solid #d1d5db; background: #fff; cursor: pointer;
}
.fic-finding-row-actions .btn-mini:hover { background: #f3f4f6; }
```

- [ ] **Step 2: 重写 `renderFindings`**

打开 `compliance-agent/frontend/app.js`，找到 `function renderFindings()`（约 line 1748）。**整段替换**（从 `function renderFindings() {` 到 line 1800 该函数闭合的 `}`）为：

```javascript
const _FIC_DIMS = ["真实性问题", "完整性问题", "合规性问题", "重复性问题", "匹配性问题"];
const _FIC_DIM_SHORT = {
  "真实性问题": "真实",
  "完整性问题": "完整",
  "合规性问题": "合规",
  "重复性问题": "重复",
  "匹配性问题": "匹配",
};

function _groupFindingsByIndicator(findings, indicators) {
  // indicators: [{id, code, name}, ...]
  const indMap = new Map();
  for (const ind of (indicators || [])) indMap.set(ind.id, ind);
  const groups = new Map();
  for (const f of findings) {
    const k = f.indicator_id == null ? "__unbound__" : f.indicator_id;
    if (!groups.has(k)) {
      const ind = (k === "__unbound__") ? null : indMap.get(f.indicator_id);
      groups.set(k, {
        key: k,
        indicator: ind,
        sort_code: ind ? ind.code : "ZZ",
        findings: [],
      });
    }
    groups.get(k).findings.push(f);
  }
  return Array.from(groups.values()).sort((a, b) => {
    if (a.key === "__unbound__") return 1;
    if (b.key === "__unbound__") return -1;
    return a.sort_code.localeCompare(b.sort_code);
  });
}

function renderFindings() {
  const d = State.taskDetail;
  const findings = d.findings;

  // 顶部维度横切按钮（保留）
  renderFindingBulkActions(findings);

  const filtered = findings.filter(f => {
    const v = State.findingFilter;
    if (v === "all") return true;
    if (["高","中","低"].includes(v)) return f.severity === v;
    if (v === "pending") return f.review_status === "pending";
    if (v === "confirmed") return f.review_status === "confirmed";
    return true;
  });

  const listBox = document.getElementById("finding-list");
  if (!filtered.length) {
    listBox.innerHTML = `<div class="empty-state">
      <div class="empty-state-glyph">▦</div>
      ${findings.length === 0 ? '尚无核查发现，请先触发 AI 核查' : '当前筛选下无结果'}
    </div>`;
    renderFindingDetail(null);
    return;
  }

  const groups = _groupFindingsByIndicator(filtered, d.indicators || []);
  listBox.innerHTML = groups.map(g => _renderIndicatorCard(g)).join("");

  // 卡 header 点击展开/折叠（按钮自身阻止冒泡）
  listBox.querySelectorAll(".finding-indicator-header").forEach(h => {
    h.addEventListener("click", e => {
      if (e.target.closest(".fic-actions")) return;
      h.parentElement.classList.toggle("is-open");
    });
  });

  // 卡内单条 finding 行点击 → 显示详情
  listBox.querySelectorAll(".fic-finding-row").forEach(row => {
    row.addEventListener("click", e => {
      if (e.target.closest(".fic-finding-row-actions")) return;
      const id = parseInt(row.dataset.id);
      State.activeFindingId = id;
      // 不全量重渲染，只高亮当前行
      listBox.querySelectorAll(".fic-finding-row.is-active")
             .forEach(r => r.classList.remove("is-active"));
      row.classList.add("is-active");
      const f = findings.find(x => x.id === id);
      renderFindingDetail(f);
    });
  });

  // 默认选中第一张卡的第一条
  if (!State.activeFindingId || !filtered.find(f => f.id === State.activeFindingId)) {
    State.activeFindingId = filtered[0].id;
  }
  renderFindingDetail(filtered.find(f => f.id === State.activeFindingId));
}

function _renderIndicatorCard(group) {
  const ind = group.indicator;
  const fs = group.findings;
  const title = ind
    ? `${esc(ind.code)} ${esc(ind.name)}`
    : `未绑指标`;
  const total = fs.length;
  const pending = fs.filter(f => (f.review_status || "pending") === "pending").length;
  const allReviewed = pending === 0;

  const dimCounts = {};
  for (const t of _FIC_DIMS) dimCounts[t] = 0;
  for (const f of fs) {
    if (dimCounts[f.finding_type] !== undefined) dimCounts[f.finding_type]++;
  }
  const badges = _FIC_DIMS.map(t => {
    const n = dimCounts[t];
    const short = _FIC_DIM_SHORT[t];
    return `<span class="fic-dim-badge dim-${t} ${n === 0 ? 'zero' : ''}">${short} ${n}</span>`;
  }).join("");

  const indId = ind ? ind.id : null;
  const actions = pending > 0 ? `
    <button class="btn btn-ghost"
            onclick="bulkReviewIndicator(${indId === null ? 'null' : indId}, 'confirmed')"
            title="把该指标下 ${pending} 条未复核全部确认">✓ 全部确认</button>
    <button class="btn btn-ghost"
            onclick="bulkReviewIndicator(${indId === null ? 'null' : indId}, 'ignored')"
            title="把该指标下 ${pending} 条未复核全部忽略">✗ 全部忽略</button>
  ` : `<span class="text-muted" style="font-size:12px">✓ 已全部复核</span>`;

  // 卡 body：5 维度分组
  const body = _FIC_DIMS.map(dim => {
    const rows = fs.filter(f => f.finding_type === dim);
    if (!rows.length) return "";
    return `<div class="fic-dim-group">
      <div class="fic-dim-group-title">${dim}（${rows.length}）</div>
      ${rows.map(f => _renderFindingRow(f)).join("")}
    </div>`;
  }).join("");

  return `<div class="finding-indicator-card ${allReviewed ? 'all-reviewed' : ''}"
                data-indicator-id="${indId === null ? '' : indId}">
    <div class="finding-indicator-header">
      <span class="fic-caret">▶</span>
      <span class="fic-title">${title}</span>
      <span class="fic-count">共 ${total} 条 · 待复核 <span class="pending-num">${pending}</span></span>
      <span class="fic-dim-badges">${badges}</span>
      <span class="fic-actions">${actions}</span>
    </div>
    <div class="finding-indicator-body">${body}</div>
  </div>`;
}

function _renderFindingRow(f) {
  const isActive = f.id === State.activeFindingId;
  const desc = esc(f.description.slice(0, 100)) + (f.description.length > 100 ? '…' : '');
  const reviewed = (f.review_status || "pending") !== "pending";
  return `<div class="fic-finding-row ${isActive ? 'is-active' : ''}" data-id="${f.id}">
    <span class="chip-risk chip-risk-${f.severity}">${f.severity}</span>
    <span class="fic-finding-desc">${desc}</span>
    ${reviewBadge(f.review_status)}
    <span class="fic-finding-row-actions">
      ${reviewed ? '' : `
        <button class="btn-mini" onclick="event.stopPropagation(); reviewFindingInline(${f.id}, 'confirmed')" title="确认">✓</button>
        <button class="btn-mini" onclick="event.stopPropagation(); reviewFindingInline(${f.id}, 'ignored')" title="忽略">✗</button>
      `}
    </span>
  </div>`;
}
```

更新「卡 header 切换图标」效果用纯 CSS 选择器（避免 JS 切图标），追加到 `style.css` 末尾：

```css
.finding-indicator-card.is-open .fic-caret::before { content: "▼"; }
.finding-indicator-card.is-open .fic-caret { font-size: 12px; }
.finding-indicator-card .fic-caret { font-size: 0; }
.finding-indicator-card .fic-caret::before { content: "▶"; font-size: 12px; }
```

（这样卡片展开时 caret 自动切到 ▼，不需要 JS）

- [ ] **Step 3: 手工烟测：渲染层**

```bash
cd compliance-agent
docker compose restart api  # 静态文件挂载即时生效，无需 restart；这一步保险
# 浏览器开 http://localhost:8000/ → 任意有 finding 任务 → 核查发现
```

Expected:
- 看到一组卡片（每个指标一张），header 显示 code/name/总数/5 类 badge
- 点 header → 卡片展开 → 看到 5 类二级分组 + 每条 finding 行
- 单条行点击右侧详情面板显示完整内容
- 右上两个按钮 [✓ 全部确认] [✗ 全部忽略]（pending=0 时显示"已全部复核"）

- [ ] **Step 4: 提交**

```bash
git add compliance-agent/frontend/app.js compliance-agent/frontend/style.css
git commit -m "feat(v1.6): 核查发现按指标聚合卡片渲染 + 5 类二级分组"
```

---

## Task 6: 卡片批量按钮 + 单条按钮交互

**Files:**
- Modify: `compliance-agent/frontend/app.js`（追加到 `bulkIgnoreFindings` 函数末尾之后）

- [ ] **Step 1: 追加 2 个全局函数**

打开 `compliance-agent/frontend/app.js`，定位到 `bulkIgnoreFindings` 函数末尾（约 line 1870 的 `};`），**紧跟其后**追加：

```javascript
// v1.6：指标级批量复核（卡 header 上的 [全部确认 / 全部忽略] 按钮）
window.bulkReviewIndicator = async function(indicatorId, status) {
  const verb = status === "confirmed" ? "确认" : "忽略";
  const findings = State.taskDetail.findings.filter(f => {
    const sameInd = indicatorId === null
      ? (f.indicator_id == null)
      : (f.indicator_id === indicatorId);
    return sameInd && (f.review_status || "pending") === "pending";
  });
  if (!findings.length) { toast("该指标已无未复核条目"); return; }
  const indLabel = indicatorId === null ? "未绑指标" : `指标 ${indicatorId}`;
  if (!confirm(`确定把「${indLabel}」下 ${findings.length} 条未复核疑点一键${verb}？`)) return;
  toast(`批量${verb} ${findings.length} 条…`);
  try {
    if (indicatorId === null) {
      // 后端 batch-review 必须传 indicator_id 或 finding_type 之一
      // 未绑指标的批量：退化为 N 次串行 PATCH（罕见场景）
      let ok = 0;
      for (const f of findings) {
        try {
          await api(`/findings/${f.id}/review`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status, note: `批量${verb}：未绑指标` }),
          });
          ok++;
        } catch (e) { console.warn("review fail", f.id, e.message); }
      }
      toast(`✓ 已${verb} ${ok} 条`, "success");
    } else {
      const resp = await api(`/tasks/${State.taskId}/findings/batch-review`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          status, note: `批量${verb}：指标级`,
          indicator_id: indicatorId, only_pending: true,
        }),
      });
      toast(`✓ 已${verb} ${resp.updated} 条`, "success");
    }
  } catch (e) {
    console.error("批量复核失败", e);
    toast(`批量复核失败：${e.message}`, "error");
    return;
  }
  await loadTaskWorkspace(State.taskId);
};

// v1.6：单条 finding 行内确认/忽略（卡片二级分组里的小按钮）
window.reviewFindingInline = async function(findingId, status) {
  const verb = status === "confirmed" ? "确认" : "忽略";
  try {
    await api(`/findings/${findingId}/review`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, note: `行内${verb}` }),
    });
    toast(`✓ 已${verb}`, "success");
  } catch (e) {
    console.error("review failed", e);
    toast(`${verb}失败：${e.message}`, "error");
    return;
  }
  await loadTaskWorkspace(State.taskId);
};
```

- [ ] **Step 2: 手工烟测交互**

浏览器再开 http://localhost:8000/，进任务 → 核查发现 tab：
1. 点某卡的 [全部忽略] → 确认对话框 → 等 toast → 该卡条目全变"已忽略"badge
2. 点单条 [✓] → toast "已确认" → 该行 badge 变绿
3. 点其他卡的 [全部确认] → 仅影响该卡（不动其他卡）

- [ ] **Step 3: 提交**

```bash
git add compliance-agent/frontend/app.js
git commit -m "feat(v1.6): 卡片级 + 行内级批量复核交互函数"
```

---

## Task 7: Playwright e2e + 部署冒烟

**Files:**
- Create: `/tmp/v16_e2e_test.py`

- [ ] **Step 1: 写 e2e 脚本**

新建 `/tmp/v16_e2e_test.py`，完整内容：

```python
"""v1.6 端到端：finding 按指标聚合卡片 + 批量复核。

策略：API 准备数据 → Playwright 验 UI → API 验状态 → 清理。
环境：本地 docker compose（http://localhost:8000）或生产 ECS。
"""
import json, time, urllib.request, urllib.error
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
TEST_PREFIX = "__E2E_v16__"
ADMIN_USER, ADMIN_PASS = "admin", "admin123"


def api(method, path, token=None, body=None):
    headers = {"Content-Type": "application/json"} if body else {}
    if token: headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            try: return r.status, json.loads(raw)
            except: return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try: return e.code, json.loads(raw)
        except: return e.code, raw


# 1. 登录
status, resp = api("POST", "/api/auth/login",
                   body={"username": ADMIN_USER, "password": ADMIN_PASS})
assert status == 200, f"登录失败 {status} {resp}"
TOKEN = resp["token"]
print(">>> 1. 登录 ✓")

# 2. 准备单位 + 任务
status, unit = api("POST", "/api/units", token=TOKEN,
                   body={"name": f"{TEST_PREFIX}单位", "code": "E2E16"})
assert status == 200, f"建单位失败 {unit}"
unit_id = unit["id"]
status, task = api("POST", "/api/tasks", token=TOKEN,
                   body={"unit_id": unit_id, "name": f"{TEST_PREFIX}任务",
                         "eval_year": 2026, "scope": "all"})
assert status == 200, f"建任务失败 {task}"
task_id = task["id"]
print(f">>> 2. 任务 id={task_id} ✓")

# 3. 直接 API 灌 finding（避免依赖 LLM）
# 用 SQL 注入是不行的，我们走「触发 AI 核查」让 stub LLM 自动出 finding；
# 或者直接调上传 + 自动形式审查触发。
# 简化：上传 3 个不同关键词材料触发自动形式审查 → 出 finding
def upload(filename, content):
    import urllib.request
    boundary = "----E2E16"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: text/plain\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        BASE + f"/api/tasks/{task_id}/materials",
        data=body, method="POST",
        headers={"Authorization": f"Bearer {TOKEN}",
                 "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

m1 = upload("合同管理制度征求意见稿.txt", ("草稿 " * 50).encode())
m2 = upload("岗位说明书.txt", ("test " * 50).encode())
print(f">>> 3. 材料 m1={m1['id']} m2={m2['id']} ✓")
time.sleep(2)

# 4. 验证 finding 已生成
status, detail = api("GET", f"/api/tasks/{task_id}", token=TOKEN)
findings = detail.get("findings", [])
assert len(findings) >= 2, f"finding 太少：{len(findings)}"
print(f">>> 4. 任务下 finding={len(findings)} ✓")

# 5. Playwright 验 UI
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto(BASE + "/")
    page.wait_for_load_state("networkidle")
    page.fill('input[name="username"]', ADMIN_USER)
    page.fill('input[name="password"]', ADMIN_PASS)
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")
    page.goto(BASE + f"/#/tasks/{task_id}")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)
    # 切到核查发现 tab
    page.click('button[data-subtab="findings"]')
    page.wait_for_timeout(1500)
    # 5.1 卡片存在
    cards = page.locator(".finding-indicator-card").count()
    print(f"    卡片数 = {cards}")
    assert cards >= 1, "没有卡片"
    page.screenshot(path="/tmp/v16_cards_collapsed.png", full_page=True)
    # 5.2 默认折叠：is-open class 应该不存在
    open_cards = page.locator(".finding-indicator-card.is-open").count()
    assert open_cards == 0, f"默认应全部折叠，实际开了 {open_cards}"
    print("    默认全部折叠 ✓")
    # 5.3 点第一张卡 header → 展开
    page.locator(".finding-indicator-header").first.click()
    page.wait_for_timeout(500)
    assert page.locator(".finding-indicator-card.is-open").count() == 1
    page.screenshot(path="/tmp/v16_cards_expanded.png", full_page=True)
    print("    第 1 张卡可展开 ✓")
    # 5.4 5 类分组存在
    groups = page.locator(".fic-dim-group").count()
    assert groups >= 1, "至少应有 1 个维度分组"
    print(f"    展开后维度分组 = {groups} ✓")
    # 5.5 点「全部忽略」按钮
    page.on("dialog", lambda d: d.accept())
    btn = page.locator(".fic-actions .btn").nth(1)  # 第二个是「全部忽略」
    if btn.count():
        btn.click()
        page.wait_for_timeout(2500)
        # 验证：该卡 header 变成"已全部复核"
        first_card = page.locator(".finding-indicator-card").first
        assert "all-reviewed" in (first_card.get_attribute("class") or ""), \
            "全部忽略后第一张卡应有 all-reviewed class"
        print("    [全部忽略] 成功 ✓")
    browser.close()

# 6. 清理
api("DELETE", f"/api/tasks/{task_id}", token=TOKEN)
api("DELETE", f"/api/units/{unit_id}", token=TOKEN)
print(">>> 6. 清理完成 ✓")
print("\n=== v1.6 e2e 全通过 ===")
```

- [ ] **Step 2: 本地跑 e2e**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
# 确认本地容器在跑
docker compose -f compliance-agent/docker-compose.yml ps | grep api
# 跑 e2e
python3 /tmp/v16_e2e_test.py
```

Expected: 全部 `✓` 输出，最后 `=== v1.6 e2e 全通过 ===`。两张截图 `/tmp/v16_cards_collapsed.png` 和 `/tmp/v16_cards_expanded.png` 生成。

- [ ] **Step 3: 提交（e2e 脚本不入仓库，仅本任务记录路径）**

跳过 git add（/tmp 不在仓库内）。

- [ ] **Step 4: 部署到生产 ECS（用户先确认）**

**用户确认开始部署后**，执行：

```bash
# 1. 推后端改动
scp compliance-agent/backend/app/api/schemas.py \
    compliance-agent/backend/app/api/audit_routes.py \
    compliance-agent/backend/app/services/audit_service.py \
    root@8.163.75.9:/opt/audit/compliance-agent/backend/app/api/  # ⚠ 路径分两组
# 上面命令 schemas.py / audit_routes.py 是 api/，audit_service.py 是 services/
# 必须分两次 scp：
scp compliance-agent/backend/app/api/schemas.py \
    compliance-agent/backend/app/api/audit_routes.py \
    root@8.163.75.9:/opt/audit/compliance-agent/backend/app/api/
scp compliance-agent/backend/app/services/audit_service.py \
    root@8.163.75.9:/opt/audit/compliance-agent/backend/app/services/

# 2. 推 pytest（验证用）
scp compliance-agent/backend/tests/test_findings_batch_review.py \
    root@8.163.75.9:/opt/audit/compliance-agent/backend/tests/

# 3. 推前端
scp compliance-agent/frontend/app.js compliance-agent/frontend/style.css \
    root@8.163.75.9:/opt/audit/compliance-agent/frontend/

# 4. SSH 进 ECS 重启 + 验证
ssh root@8.163.75.9 << 'EOF'
cd /opt/audit/compliance-agent
docker compose restart api worker
sleep 5
# 验证容器内代码到位
docker compose exec -T api grep -c "batch_review_findings" /app/app/services/audit_service.py
docker compose exec -T api grep -c "batch-review" /app/app/api/audit_routes.py
# 跑 pytest 验证
docker compose exec -T api pytest tests/test_findings_batch_review.py -v
EOF
```

Expected:
- grep 应返回 ≥ 1
- pytest 输出 `8 passed`

- [ ] **Step 5: 生产烟测**

浏览器开生产地址 `http://8.163.75.9:8000/` → 登录 → 找一个 finding 多的任务 → 核查发现 tab → 验证卡片渲染 + 批量按钮可用。

- [ ] **Step 6: 合 main**

```bash
git checkout main
git merge --no-ff feature/v1.6-finding-aggregation -m "feat(v1.6): 核查发现按指标聚合显示 + 批量复核接口"
git log --oneline -5
```

- [ ] **Step 7: 更新内存（重要业务变化）**

如果 v1.6 引入新 API，写入 `project_architecture.md` 的"v1.6 新增"一节，让未来对话感知到批量复核接口的存在。

---

## 自查清单（执行完成后用户核对）

- [ ] pytest 全绿（基线 162 + 新增 8 = 170+）
- [ ] 本地 Playwright e2e 全通过
- [ ] 生产 ECS 上线 + 真实任务卡片渲染正常
- [ ] 「全部确认/忽略」批量按钮响应 < 2s（476 条规模）
- [ ] 旧的「忽略所有 真实性问题」按钮仍可用且性能提升
- [ ] 详情面板内容、整改流程、评分公式无变化
- [ ] feature 分支合 main + 推送（如需要）

---

## 回滚方案

如生产出现严重问题：

```bash
ssh root@8.163.75.9
cd /opt/audit/compliance-agent
# 从本地推回 main 的旧版本
# 在本地：
cd /Users/lizhishaoniange/Documents/ai审计智能体
git checkout main
git revert <merge-commit-sha>  # 或直接 reset 到 v1.5 commit
# 再 scp 旧文件回 ECS + restart
```

由于后端 batch-review 接口是**新增**而非修改，前端旧逻辑也兼容（因为 `bulkIgnoreFindings` 改动只是性能优化，行为不变），实际回滚只需要：
- 把 `frontend/app.js` 和 `frontend/style.css` 回滚到 v1.5 版本 + scp 上去 → UI 立即恢复平铺
- 后端批量接口可以留着不动（向后兼容，无害）
