# 工作台"单位核查进度总览"卡片（v2.13）

**日期**：2026-07-20
**范围**：backend 新 router + frontend 工作台加 card
**动机**：客户需要在工作台看被检查单位档案的核查覆盖情况——多少单位未建任务、建了任务未上传材料、有材料未完成、已完成，用于组织补充上传与推进进度。

## 目标

- 工作台加"单位核查进度总览"card，5 档互斥统计
- summary 端点一次返回 5 数字（快，dashboard 加载并行请求）
- detail 端点按 category 懒加载（点击展开时才请求）
- 前端展开表格展示对应类别的单位列表，再点收起

## 非目标（YAGNI）

- 不提供 `completed` 档 detail（数量大 + v2.11 "批量导出已定稿"已可见完成的单位）
- 详情表里单位名不做跳转（v2.13 只展示；未来需要跳转到该单位任务详情再加）
- 不做 CSV 导出（浏览器全选复制够用；实操中列表几百上千行）
- 不加分页（几千行内表格 scroll 可接受）
- 不做实时刷新（用户手动 F5 或切 tab 触发重取）
- 不改 4 个 stat 头卡（顶部保持不变）

## 5 档定义（互斥）

| 档 | 定义 | detail 端点 |
|---|---|---|
| 1. `total` 单位总数 | 所有 audit_units | ❌ |
| 2. `no_task` 未建任务 | 该单位下 0 个 audit_tasks | ✅ |
| 3. `has_task_no_material` 建了任务但0材料 | 有任务，所有任务下 0 materials，未全 finalized | ✅ |
| 4. `in_progress_with_material` 有材料但未完成 | 有材料，未全部 finalized | ✅ |
| 5. `completed` 已完成核查 | 所有任务 finalized（且 finalized 数 = task_count） | ❌ |

后 4 档相加 = 单位总数（互斥不重叠）。

**判定优先级**（避免歧义）：`no_task` > `completed` > `has_task_no_material` > `in_progress_with_material`。理由：finalized 优先兜底（即使 0 材料也算完成核查），保证已完成不被误分。

## 设计

### 后端

新文件 `backend/app/api/dashboard_routes.py`（跟 v2.11 `export_routes.py` 平级）：

```python
"""v2.13: 工作台"单位核查进度总览"端点。"""
from __future__ import annotations

from typing import Optional

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
    """五档判定；调用侧保证 row 有 task_count/material_count/finalized_count。"""
    if row.task_count == 0:
        return "no_task"
    if row.finalized_count == row.task_count:
        return "completed"
    if row.material_count == 0:
        return "has_task_no_material"
    return "in_progress_with_material"


@dashboard_router.get("/unit-stats/summary")
def unit_stats_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """5 档单位数统计，一次 SQL。"""
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


_VALID_DETAIL_CATEGORIES = {
    "no_task", "has_task_no_material", "in_progress_with_material",
}


@dashboard_router.get("/unit-stats/detail")
def unit_stats_detail(
    category: str = Query(..., description="no_task / has_task_no_material / in_progress_with_material"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """按 category 返回单位列表，供前端展开表格用。

    completed 不提供 detail（数量大 + 已在批量导出 card 可见）。
    """
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

**注册**：在 `backend/app/main.py` 顶部 import + `app.include_router(dashboard_router)`。

**性能**：`_base_subquery` 是一次 SQL 聚合，返 4000+ 单位约 200KB JSON。summary 处理 in Python 遍历一次；detail 遍历一次 + 过滤。<200ms 可接受。

### 前端

#### `index.html` 加 card

位置：`grid-2` "待处理/最近任务"关闭 `</div>` 之后、"批量导出已定稿工作底稿" card `<div class="card mt-6 fade-in fade-in-4">` 之前。

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

#### `app.js` 新增函数

```javascript
// v2.13: 单位核查进度总览 —— summary + 懒加载 detail
State.unitStatsDetailCache = {};  // { category: [rows] }

async function renderUnitProgressCard() {
  const box = document.getElementById("dash-unit-progress");
  if (!box) return;
  try {
    const s = await api("/dashboard/unit-stats/summary");
    box.innerHTML = `
      <div class="unit-progress-stats" style="display:flex;gap:16px;align-items:stretch">
        ${_upStatBox("total",                       s.total,                       "单位总数",         false)}
        ${_upStatBox("no_task",                     s.no_task,                     "未建任务",         true)}
        ${_upStatBox("has_task_no_material",        s.has_task_no_material,        "建任务未上传材料", true)}
        ${_upStatBox("in_progress_with_material",   s.in_progress_with_material,   "有材料未完成",     true)}
        ${_upStatBox("completed",                   s.completed,                   "已完成核查",       false)}
      </div>
      <div id="dash-unit-progress-detail" style="margin-top:12px"></div>
    `;
    // 绑点击事件
    box.querySelectorAll(".unit-progress-toggle").forEach(el => {
      el.addEventListener("click", () => _toggleUnitProgressDetail(el.dataset.category));
    });
  } catch (e) {
    box.innerHTML = `<div class="empty-state" style="padding:16px;color:#b8262b">加载失败：${esc(e.message)}</div>`;
  }
}

function _upStatBox(category, count, label, clickable) {
  const arrow = clickable
    ? `<span class="unit-progress-toggle" data-category="${category}" style="cursor:pointer;color:#0071e3;font-size:13px" title="展开单位列表">▼</span>`
    : "";
  return `
    <div style="flex:1;text-align:center;padding:12px;background:#fafafa;border-radius:8px">
      <div style="font-size:28px;font-weight:600;color:#1d1d1f">${count}</div>
      <div style="font-size:12px;color:#6e6e73;margin-top:4px">${label}</div>
      <div style="margin-top:4px">${arrow}</div>
    </div>
  `;
}

async function _toggleUnitProgressDetail(category) {
  const box = document.getElementById("dash-unit-progress-detail");
  if (!box) return;
  // 如果当前已展开的就是这个 category → 收起
  if (box.dataset.openCategory === category) {
    box.innerHTML = "";
    box.dataset.openCategory = "";
    return;
  }
  // 展开新 category
  box.dataset.openCategory = category;
  box.innerHTML = `<div class="empty-state" style="padding:8px">加载中…</div>`;
  try {
    let rows = State.unitStatsDetailCache[category];
    if (!rows) {
      rows = await api(`/dashboard/unit-stats/detail?category=${encodeURIComponent(category)}`);
      State.unitStatsDetailCache[category] = rows;
    }
    if (!rows.length) {
      box.innerHTML = `<div class="empty-state" style="padding:8px">该类别下无单位</div>`;
      return;
    }
    const showProgress = category !== "no_task";  // no_task 不需要进度列
    box.innerHTML = `
      <table class="table table-compact">
        <thead>
          <tr>
            <th style="width:60px">编号</th>
            <th>单位名称</th>
            ${showProgress ? '<th style="width:120px">任务进度</th>' : ''}
            ${category === "in_progress_with_material" ? '<th style="width:100px">材料数</th>' : ''}
          </tr>
        </thead>
        <tbody>
          ${rows.map(r => `
            <tr>
              <td><span class="code-id">#${r.id}</span></td>
              <td>${esc(r.name)}</td>
              ${showProgress ? `<td>${r.finalized_tasks} / ${r.total_tasks}</td>` : ''}
              ${category === "in_progress_with_material" ? `<td>${r.material_count}</td>` : ''}
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

在 `loadDashboard()` 末尾加 `renderUnitProgressCard();`（跟 `renderExportRegion();` 并排）。

**缓存策略**：detail 首次点开后缓存到 `State.unitStatsDetailCache`；同 category 再点直接从缓存读（秒回）。切页面（F5 或路由变更）后 State 清空自然刷新。

#### 缓存版本号

`?v=2.11` → `?v=2.13`（跳过 v2.12 因为纯脚本无前端）。

## 涉及文件

| 文件 | 变更 |
|---|---|
| `backend/app/api/dashboard_routes.py` | 新建，2 端点 + 3 helpers |
| `backend/app/main.py` | import + `include_router(dashboard_router)` 一行 |
| `backend/tests/test_dashboard_unit_stats.py` | 6 条 pytest：summary 五档准确 / no_task detail / has_task_no_material detail / in_progress detail / completed 无 detail 返 400 / 空库返 0 |
| `frontend/index.html` | 加 card + `?v=2.11` → `?v=2.13` |
| `frontend/app.js` | `renderUnitProgressCard` + `_upStatBox` + `_toggleUnitProgressDetail` + State 缓存 + loadDashboard 末尾调用 |
| `README.md` | v2.13 更新日志 |

## 部署

跟 v2.11 同一套：
1. Workbench 上传 4 文件（backend/dashboard_routes.py + main.py + frontend/index.html + frontend/app.js）
2. `docker compose cp` 后端到 3 容器 + restart backend + worker + enrich_worker
3. Frontend bind mount，Cmd+Shift+R 刷新即可
4. 无 pg_dump / 无预算问题（纯 SELECT，无写入）

## 手工验证 checklist

- [ ] 硬刷后进"工作台"页
- [ ] card 出现在"最近任务"下方、"批量导出已定稿工作底稿"上方
- [ ] 5 数字加起来（后 4 档）= 单位总数（数学一致）
- [ ] 点"未建任务 X"下方 ▼ → 展开表格显示单位列表
- [ ] 点同一个 ▼ 再点 → 表格收起
- [ ] 点另一个类别 ▼ → 上一个收起 + 新的展开
- [ ] 展开"建任务未上传材料"表格含 `任务进度` 列（如 0 / 3）
- [ ] 展开"有材料未完成"表格含 `任务进度` + `材料数` 列
- [ ] "单位总数"和"已完成核查"无 ▼ 箭头（不可点）
- [ ] 401 时 toast "请重新登录"
- [ ] 网络失败时 card 显示"加载失败：…"

## 风险 & 缓解

| 风险 | 概率 | 缓解 |
|---|---|---|
| SQL 聚合慢（4600 单位 + 5000 任务 + N 万材料）| 低 | outerjoin + GROUP BY 有索引（unit_id / task_id 都是 FK 有 index）。<200ms 期望 |
| detail 返回 JSON 太大（未完成单位可能几千）| 中 | 4000 单位约 200KB JSON，浏览器渲染 <100ms 可接受。若客户后续报慢再加分页 |
| 缓存陈旧：新建任务/上传材料后仍看旧数字 | 低 | dashboard load 时重取 summary；detail 缓存在 State，F5 后清空。文案里加"截至加载时刻" |
| 前端 XSS：单位名含特殊字符 | 低 | 所有插值用 `esc()` |

## 回滚

`git revert` 一个 commit → cp 老 main.py/frontend 回容器 → restart backend + F5。detail 端点 404 时前端 fetch 抛错，card 显示 "加载失败" 不影响别的功能。
