# 前端数据缓存 + 后端 defer stats（v2.6）

**日期**：2026-07-03
**范围**：frontend `app.js` + `index.html` + backend `audit_routes.py`（+ pytest）
**动机**：用户反馈"页面切换需要 3-5 秒才刷新出来"，用 chrome-in-chrome 采样确认根因

## 根因（诊断数据）

用 `performance.getEntriesByType('resource')` 采样 5 次页面切换（工作台/核查任务/法规库/评价指标/问题清单），观察到：

**慢的 endpoint**：
| Endpoint | 最慢单次 | 数据量 | 调用次数 |
|---|---|---|---|
| `/api/tasks` | **28 秒** | 686 KB | 1 |
| `/api/units` | **17 秒**（最慢）/ 2.5-7s（其它）| 93 KB | **4 次** |
| `/api/indicators` | 4 秒 | 8 KB | **3 次** |
| `/api/check-items` | 1.3 秒 | 1 KB | 2 次 |
| `/api/regulations` | 1.5 秒 | 6 KB | 1 |

**三个问题叠加**：

1. **重复拉取**：切页面时 units 拉 4 次、indicators 拉 3 次 —— 已经在 State 里的数据被反复重拉
2. **后端 uvicorn workers=1 + 前端并发发 5 个请求**：单进程排队叠加。看 units 4 次耗时 `2.5s → 3.8s → 7.4s → 17s` —— 前面每个花几秒，后面等着累加
3. **`/api/tasks` 单次 28 秒**：1739 条 × pydantic model_validate 序列化 CPU 密集，加上排队

## 目标

改完后：
- **首次进任务列表**：`/api/tasks` 从 28s **降到 1-3s**（B1 后端 defer stats）
- **切换其它页面**：< 100ms（A 前端 State 缓存，不发 API）
- **总网络请求次数**：从 5 次切换发 14 个 API 减到 5 次切换发 **~6 个 API**
- **CPU 排队叠加消失**（不再同时发 5 个大请求）
- **API contract 完全不变**：`AuditTaskOut` schema 一字段不删；前端调用完全兼容；DB 也不动

## 非目标（YAGNI）

- 不做 SWR / react-query 之类的缓存库（vanilla JS 简单判空足够）
- 不做后端分页（会破坏 v2.1 前端搜索）
- 不做 IndexedDB 持久化缓存（页面 F5 后从零拉一次可接受）
- 不做 background refresh（数据变化通过显式 invalidate）
- 不改 API schema（`AuditTaskOut` 字段完全不变）
- 不改 DB schema
- 不改 uvicorn workers 数（v2.0 试过 OOM，保守起见不动，如果 B1 效果好就不需要 B3）
- 不加索引（问题不在 SQL，而在 pydantic 序列化）

## 缓存策略

用 `State` 里的现有字段做"拉过一次就复用"缓存：

```
State.tasks       — 首次为 [], 拉过后长度 > 0
State.units       — 同上
State.indicators  — 同上
State.checkItems  — 需要新增（现在存在 State 之外）
State.regulations — 需要新增
```

判空逻辑：`if (State.tasks.length === 0) { fetch + set }`；否则跳过。

## Invalidate 时机（保证数据新鲜）

| 用户动作 | 需要 invalidate 的 State |
|---|---|
| 新建任务 | 追加到 `State.tasks[0]`（optimistic），或简单粗暴 `State.tasks = []` 让下次重拉 |
| 删除任务 | 从 `State.tasks` 里 splice 掉 |
| 触发 AI 核查 | 不用 invalidate 列表，只更新单条 task 的 status（`loadTaskWorkspace` 会拉最新 detail）|
| 新建/编辑单位 | `State.units = []` |
| 上传/删除材料 | 不影响 tasks 列表（进详情页时才拉最新 materials）|
| 上传法规 | `State.regulations = []` |
| 上传指标 | `State.indicators = []` |

**简单粗暴策略**：**任何 write 操作后清空对应 State 数组**，下次访问自然重拉。避免 optimistic 更新的复杂 sync bug。

## B1：后端 `list_tasks` 用 `defer('stats')` 延后加载大字段

`AuditTask.stats` 是 JSON 字符串（entities.py 里定义为 `stats: Mapped[str]`），存整个任务的统计数据（各维度 finding 分布 / 评分明细 / 覆盖率 / 各种 breakdown）。1739 条任务，每条 stats 大小几 KB → 序列化占大头，是 28s 的主凶。

**列表页压根不显示 stats**（前端 renderTasksBody 只用 id/unit_id/name/eval_year/status/summary，不用 stats）。**任务详情页**才用（进任务工作台后 `GET /api/tasks/{id}` 拉的 detail 里才需要）。

**改法**：在 `list_tasks` 里显式 defer：

```python
# 原有 audit_routes.py:117-123
@tasks_router.get("", response_model=List[AuditTaskOut])
def list_tasks(db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    q = db.query(AuditTask).order_by(AuditTask.id.desc())
    if is_unit(user.role) and user.unit_id:
        q = q.filter(AuditTask.unit_id == user.unit_id)
    return q.all()

# 改成：
from sqlalchemy.orm import defer

@tasks_router.get("", response_model=List[AuditTaskOut])
def list_tasks(db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    # v2.6：defer stats 大 JSON 字段（前端列表页不用）
    # 单条任务 stats 可能几 KB，1000+ 条累积几 MB 序列化开销
    # 任务详情 GET /api/tasks/{id} 仍会读 stats（那里是 db.get(...) 全列）
    q = db.query(AuditTask).options(defer(AuditTask.stats))\
        .order_by(AuditTask.id.desc())
    if is_unit(user.role) and user.unit_id:
        q = q.filter(AuditTask.unit_id == user.unit_id)
    return q.all()
```

**关键**：`AuditTaskOut` schema 里 `stats: str` 字段**保留**。SQLAlchemy 用 defer 后，从数据库没取 stats 列，但 ORM 层 access `task.stats` 时会 lazy load（**只 access 的时候才加载**）。

- `list_tasks` return `q.all()` → FastAPI 用 `AuditTaskOut.model_validate(each)` 序列化
- pydantic v2 `from_attributes=True` 会 access schema 里声明的每个字段 → **会 access `task.stats`** → **触发 lazy load** → **失去 defer 收益**！

**修正**：需要让 pydantic **不 access stats**。两种做法：

**做法 A**：schema 里 stats 改为 `Optional[str] = None`，然后手动 map（不用 pydantic 自动 from_attributes）：

```python
# schemas.py:255 stats 改成 Optional
stats: str = ""   # 已经有 default ""
```

用手动映射避免 pydantic access stats：

```python
def list_tasks(...):
    q = db.query(AuditTask).options(defer(AuditTask.stats))...
    tasks = q.all()
    # 手动映射，不 access stats
    return [
        AuditTaskOut(
            id=t.id, unit_id=t.unit_id, name=t.name, eval_year=t.eval_year,
            scope=t.scope, selected_indicator_ids=t.selected_indicator_ids,
            status=t.status, summary=t.summary,
            stats="",   # 显式给空，绕过 defer 触发 lazy load
            progress_current=t.progress_current, progress_total=t.progress_total,
            progress_text=t.progress_text, fast_mode=t.fast_mode,
            created_at=t.created_at, completed_at=t.completed_at,
        )
        for t in tasks
    ]
```

**做法 B**：给 schema 加一个 `List` 变体 `AuditTaskListItem`（不含 stats）：

```python
# schemas.py 加
class AuditTaskListItem(BaseModel):
    id: int
    unit_id: int
    name: str
    eval_year: int
    scope: str = "all"
    selected_indicator_ids: str = "[]"
    status: str
    summary: str
    progress_current: int = 0
    progress_total: int = 0
    progress_text: str = ""
    fast_mode: bool = False
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    class Config:
        from_attributes = True

# audit_routes.py:117
@tasks_router.get("", response_model=List[AuditTaskListItem])
def list_tasks(...):
    ...
```

**选做法 A** —— 前端 `renderTasksBody` 里没用 `t.stats`（我 grep 过），schema 保持 `stats: str = ""`（有默认值）不破坏 API 契约。

## 涉及文件

| 文件 | 变更 |
|------|-----|
| `frontend/app.js` | ~40 行：判空缓存 + 5 处 invalidate 时机 |
| `frontend/index.html` | `?v=2.5` → `?v=2.6` 刷缓存 |
| `backend/app/api/audit_routes.py` | ~15 行：list_tasks 用 defer + 手动映射 |
| `backend/tests/test_v26_perf_cache.py` | 3 条 case：defer 后 stats 为空字符串、API 契约不变、tasks 数量正确 |

## 具体改动位置（app.js）

### 1. State 加两个字段

```javascript
const State = {
  ...
  taskSearchQuery: "",
  // v2.6：拉过一次的数据缓存到 State，切页面复用不重拉
  checkItems: [],
  regulations: [],
};
```

### 2. loadTasks（`app.js:320`）加判空

```javascript
async function loadTasks(force = false) {
  try {
    if (!force && State.tasks.length && State.units.length) {
      // 缓存命中，直接渲染
      applyTaskSearch();
      return;
    }
    const [units, tasks] = await Promise.all([api("/units"), api("/tasks")]);
    State.units = units; State.tasks = tasks;
    applyTaskSearch();
  } catch (e) { console.error(e); }
}
```

### 3. loadRegulations / loadIndicators / loadCheckItems 同理

（需要找到各自的 load 函数位置，加判空。示例 loadRegulations 略去，模式相同。）

### 4. loadLLMConfig / loadVisionConfig / loadAutoFormReviewConfig 三个后台配置**不加缓存**

（用户可能主动切换 provider / model，每次进后台管理都要拿最新配置。这三个都是小接口 <100ms）

### 5. write 操作后清空对应 State（invalidate）

以创建任务为例：

```javascript
// 之前（假设 create task 成功后）
await api("/tasks", { method: "POST", body: ... });
// 需要在成功回调加一行：
State.tasks = [];   // v2.6：清空 State 让下次进任务列表重拉
```

具体位置：
- 新建任务成功回调 → `State.tasks = []`
- `deleteTaskFromList` 删除后 → `State.tasks = []`（简单粗暴）
- 新建单位成功回调 → `State.units = []`
- 上传法规成功 → `State.regulations = []`
- 上传指标成功 → `State.indicators = []`

## 测试计划

### Backend pytest 3 条

1. `test_list_tasks_response_omits_stats_content`：GET /api/tasks 响应里每条 task 的 `stats` 字段 == `""`（defer 生效，手动映射填空）
2. `test_task_detail_still_returns_stats`：GET /api/tasks/{id} 详情里 `stats` 仍有真实 JSON 内容（不被 defer 影响）
3. `test_list_tasks_count_matches_db`：GET /api/tasks 数量 == `db.query(AuditTask).count()`（不漏任务）

### 前端手动 verify

浏览器硬刷 `?v=2.6` 后：

1. 打开工作台 → 记录耗时（应比现在快 5-10 倍，B1 生效）
2. 切到核查任务 → **1-3 秒**（首次，B1 效果）；如果之前已进过则 **< 100ms**（A 缓存）
3. 切到法规库 → 首次 <1.5 秒
4. 切到评价指标 → **< 100ms**（首次访问已缓存）
5. 切到问题清单 → 首次 <1 秒
6. **再切回核查任务** → **< 50ms**（缓存）
7. **新建一个任务** → 保存成功后切到任务列表，看到新任务在列表里（不是老缓存）
8. **删除一个任务** → 任务列表刷新
9. Network 面板：5 次切换的 API 总数从 14 降到 ~6

### 浏览器 Network 采样对比

跑 chrome-in-chrome 同样的 5 次切换：
- **B1 前**：`/api/tasks` 28s
- **B1 后**：`/api/tasks` 1-3s
- **A + B1 后**：`/api/tasks` 只调用 1 次（首次），后续切页面直接用 State 缓存

## 部署

后端 audit_routes.py cp 到 3 容器（backend / worker / enrich_worker 保持代码一致），需 restart backend；前端 bind mount 自动生效。

```bash
# mac
scp v2.6.tar.gz root@8.163.75.9:/opt/audit/compliance-agent/

# 服务器
cd /opt/audit/compliance-agent
tar -xzf v2.6.tar.gz

for c in backend worker enrich_worker; do
  docker compose cp backend/app/api/audit_routes.py $c:/app/app/api/audit_routes.py
done
docker compose cp backend/tests/test_v26_perf_cache.py backend:/app/tests/test_v26_perf_cache.py

docker compose restart backend
sleep 5

docker compose exec -T backend python -m pytest tests/test_v26_perf_cache.py -v
# 期望 3 passed

rm v2.6.tar.gz
```

前端硬刷（`?v=2.6`）拉新版。

## 回滚

- **仅后端出问题**：`git checkout HEAD~1 -- compliance-agent/backend/app/api/audit_routes.py` 恢复老版本 + docker cp + restart backend（<3 分钟）
- **仅前端**：降 `?v=2.6` → `?v=2.5` 让浏览器拉老版本
- **全撤**：`git revert <v2.6 commit>` + 重新 cp 全套

## 安全保证清单

| 保证 | 具体做法 |
|---|---|
| **不改 API contract** | `AuditTaskOut` schema 字段一个不删；stats 保留（值改为 ""），前端调用 100% 兼容 |
| **不改 DB schema** | 只改 SELECT，不动列 |
| **不改数据** | 只 SELECT 优化，UPDATE / DELETE 逻辑不变 |
| **详情页仍有 stats** | 只 list 层 defer，详情端点 `GET /tasks/{id}` 仍 select 全列 |
| **回归测试** | 全量 pytest 214+ 全过 + 新增 3 条 v2.6 pytest |
| **灰度部署** | 客户下班后（晚 22:00+）部署 |
| **回滚 <3 分钟** | 单 commit，git revert + docker cp 一步恢复 |
