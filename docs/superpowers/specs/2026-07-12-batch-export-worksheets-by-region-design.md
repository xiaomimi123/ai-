# 工作台批量导出已定稿工作底稿（按地区）v2.11

**日期**：2026-07-12
**范围**：backend（region 解析 + 2 端点）+ frontend（工作台加一个 card + 下载）
**动机**：核查员现场把已定稿的工作底稿分市归档，当前只能一个一个进任务详情点"下载 Excel 底稿"。上百个定稿任务时极其繁琐。

## 目标

- 工作台加一个"批量导出已定稿工作底稿"卡片
- 按市（+区县）分组显示已定稿任务数
- 一键下载某市的所有底稿 zip；zip 内按 `市/区县/单位_年_任务id.xlsx` 分层
- 地区从 `unit.name` 自动提取（无数据迁移）

## 非目标（YAGNI）

- 不加 `AuditUnit.region` 数据库字段（自动解析够用，人工修正未来再说）
- 不做全省一次性 zip（每市一个 zip，避免几 GB 大包超时）
- 不导出 finding 明细 / 报告 Word（本次只 worksheet.xlsx）
- 不做导出历史 / 进度轮询（zip 是同步流式生成，一般几秒到几十秒完成）
- 不做前端多市 checkbox 批量下载（每次一市，简单可靠）
- 不改现有 `GET /api/tasks/{id}/worksheet.xlsx` 单任务下载端点

## 设计

### 后端

#### 1. `app/services/region_parser.py`（新建）

```python
"""从单位名解析行政区划（市 + 区县）。

覆盖模式：
- 省级 + 市 + 区县：如"四川省达州市达川区幺塘乡..." → ("达州市", "达川区")
- 直辖市 + 区：如"北京市海淀区..." → ("北京市", "海淀区")
- 只有市 + 区县：如"达州市达川区..." → ("达州市", "达川区")
- 只有市：如"达州市财政局" → ("达州市", None)
- 解析不出：→ (None, None)

匹配失败的单位在导出时归入"未分类"桶。
"""
from __future__ import annotations
import re
from typing import Optional

# 直辖市（跳过省级）
MUNICIPALITIES = {"北京市", "上海市", "天津市", "重庆市"}

# 市匹配：XX市 / XX自治州 / XX地区 / XX盟
_CITY_RE = re.compile(
    r"([一-龥]{1,10}?(?:市|自治州|地区|盟))"
)
# 区县匹配：XX区 / XX县 / XX自治县 / XX旗 / XX县级市（如"简阳市"作为区县时另行处理）
_DISTRICT_RE = re.compile(
    r"([一-龥]{1,10}?(?:区|县|自治县|旗))"
)


def parse_region(unit_name: str) -> tuple[Optional[str], Optional[str]]:
    """从单位名提取 (市, 区县)。"""
    if not unit_name:
        return (None, None)
    # 直辖市优先
    for muni in MUNICIPALITIES:
        if muni in unit_name:
            m = _DISTRICT_RE.search(unit_name.split(muni, 1)[-1])
            return (muni, m.group(1) if m else None)
    # 普通市
    city_m = _CITY_RE.search(unit_name)
    if not city_m:
        return (None, None)
    city = city_m.group(1)
    # 市之后的部分找区县
    after_city = unit_name[city_m.end():]
    dist_m = _DISTRICT_RE.search(after_city)
    return (city, dist_m.group(1) if dist_m else None)
```

**测试**（`backend/tests/test_region_parser.py`）覆盖：
- 省 + 市 + 区县 → 正确 (市, 区县)
- 直辖市 + 区 → (北京市, 海淀区)
- 只有市 → (市, None)
- 空 / None → (None, None)
- 只有省无市 → (None, None)
- 自治州 / 自治县 → 正确识别

#### 2. `app/api/export_routes.py`（新建，独立于 audit_routes）

```python
"""v2.11：批量导出已定稿工作底稿（按地区）。"""
from __future__ import annotations
import io
import zipfile
from collections import defaultdict
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.models import AuditTask, AuditUnit, User, Worksheet, get_db
from app.services.region_parser import parse_region
from app.services.worksheet_export import build_worksheet_xlsx
from app.services.worksheet_service import get_worksheet

exports_router = APIRouter(prefix="/api/exports", tags=["exports"])

# "未分类"桶的显示名（前端也用同名标识）
UNCLASSIFIED = "未分类"


def _list_finalized_task_regions(db: Session, user: User) -> list[dict]:
    """按 (市) 聚合当前用户可见的已定稿任务数。

    返回结构：
    [
      {"city": "达州市", "task_count": 12, "unit_count": 8, "unknown": False},
      {"city": "未分类", "task_count": 3, "unit_count": 3, "unknown": True},
      ...
    ]
    """
    # 简化：单角色用户看全部；多租户/权限系统未来再加过滤
    tasks = (
        db.query(AuditTask, AuditUnit.name)
        .join(AuditUnit, AuditTask.unit_id == AuditUnit.id)
        .filter(AuditTask.status == "finalized")
        .all()
    )
    grouped: dict[str, dict] = defaultdict(
        lambda: {"task_count": 0, "unit_ids": set(), "unknown": False}
    )
    for task, unit_name in tasks:
        city, _ = parse_region(unit_name)
        key = city or UNCLASSIFIED
        grouped[key]["task_count"] += 1
        grouped[key]["unit_ids"].add(task.unit_id)
        if not city:
            grouped[key]["unknown"] = True
    return [
        {"city": k, "task_count": v["task_count"],
         "unit_count": len(v["unit_ids"]), "unknown": v["unknown"]}
        for k, v in sorted(grouped.items(),
                           key=lambda kv: (kv[1]["unknown"], -kv[1]["task_count"]))
    ]


@exports_router.get("/region-summary")
def region_summary(db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)) -> list[dict]:
    """列出已定稿任务按市分组的统计（工作台"批量导出"card 用）。"""
    return _list_finalized_task_regions(db, user)


@exports_router.get("/worksheets/city/{city}.zip")
def download_city_zip(city: str,
                      db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    """下载某市所有已定稿任务的工作底稿 zip。"""
    if not city:
        raise HTTPException(400, "city 参数必填")
    # 收集该市所有已定稿任务
    all_tasks = (
        db.query(AuditTask, AuditUnit.name)
        .join(AuditUnit, AuditTask.unit_id == AuditUnit.id)
        .filter(AuditTask.status == "finalized")
        .all()
    )
    match_tasks = []
    for task, unit_name in all_tasks:
        parsed_city, district = parse_region(unit_name)
        actual_city = parsed_city or UNCLASSIFIED
        if actual_city == city:
            match_tasks.append((task, unit_name, district))
    if not match_tasks:
        raise HTTPException(404, f"'{city}' 下无已定稿任务")

    # 生成 zip 到内存
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for task, unit_name, district in match_tasks:
            ws = get_worksheet(db, task.id)
            if not ws:
                continue  # 定稿了但 worksheet 缺失（不应发生），跳过
            xlsx_bytes = build_worksheet_xlsx(db, task, ws)
            # 目录：市/区县/单位_年_任务id.xlsx；未分类 → 市/_未分类/
            dist_dir = district or "_未分类"
            safe_unit = unit_name.replace("/", "_").replace("\\", "_")
            entry = f"{city}/{dist_dir}/{safe_unit}_{task.eval_year}_{task.id}.xlsx"
            zf.writestr(entry, xlsx_bytes)
    buf.seek(0)
    filename = f"{city}_已定稿工作底稿_{len(match_tasks)}份.zip"
    filename_quoted = quote(filename)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition":
                f'attachment; filename="worksheets_{city}.zip"; '
                f"filename*=UTF-8''{filename_quoted}",
        },
    )
```

#### 3. 注册 router

在 `app/main.py` 或 `app/api/__init__.py` 里 `app.include_router(exports_router)`。

#### 4. 测试

`backend/tests/test_export_region.py` 覆盖：
- summary 返回 finalized 任务，其它状态不计
- summary 未分类桶正确聚合 + `unknown=True`
- zip 下载返回正确 media_type + Content-Disposition
- zip 内目录结构 `<市>/<区县>/<单位>_<年>_<id>.xlsx`
- 城市不存在返回 404
- 单位名含 `/` 被 sanitize

### 前端

#### 1. `index.html` 工作台加 card

在 `<section id="page-dashboard">` 的 `<div class="page-body">` 里，"最近任务"grid-2 下方（现有"五维核查范式"card 之前）加：

```html
<!-- v2.11: 批量导出已定稿工作底稿（按市分组） -->
<div class="card mt-6 fade-in fade-in-4">
  <div class="section-title">批量导出已定稿工作底稿</div>
  <div class="text-sm text-muted mb-3">
    只导出「已定稿（finalized）」状态的任务。按市分组下载 zip，zip 内目录结构 <code>市/区县/单位_年_任务id.xlsx</code>。
  </div>
  <div id="dash-export-region" class="text-sm">
    <div class="empty-state" style="padding:16px">加载中…</div>
  </div>
</div>
```

#### 2. `app.js` 新增 `renderExportRegion()` + 调用

在 dashboard render 流程里加：

```javascript
async function renderExportRegion() {
  const box = document.getElementById("dash-export-region");
  if (!box) return;
  try {
    const rows = await api("/exports/region-summary");
    if (!rows.length) {
      box.innerHTML = `<div class="empty-state" style="padding:16px">暂无已定稿任务可导出</div>`;
      return;
    }
    box.innerHTML = `
      <table class="table table-compact">
        <thead>
          <tr><th>市</th><th style="width:100px">任务数</th><th style="width:100px">单位数</th><th style="width:160px">操作</th></tr>
        </thead>
        <tbody>
          ${rows.map(r => {
            const cityLabel = r.unknown
              ? `<span class="text-muted">${esc(r.city)}</span> <span class="badge badge-orange" style="font-size:10px">解析失败</span>`
              : `<strong>${esc(r.city)}</strong>`;
            return `<tr>
              <td>${cityLabel}</td>
              <td>${r.task_count}</td>
              <td>${r.unit_count}</td>
              <td>
                <button class="btn btn-secondary btn-sm dash-export-btn"
                        data-city="${esc(r.city)}"
                        title="下载 ${esc(r.city)} 的 ${r.task_count} 份底稿 zip">
                  📥 下载 zip
                </button>
              </td>
            </tr>`;
          }).join("")}
        </tbody>
      </table>
    `;
    // 事件委托：点击下载
    box.querySelectorAll(".dash-export-btn").forEach(btn => {
      btn.addEventListener("click", () => _downloadCityZip(btn.dataset.city, btn));
    });
  } catch (e) {
    box.innerHTML = `<div class="empty-state" style="padding:16px;color:#b8262b">加载失败：${esc(e.message)}</div>`;
  }
}

async function _downloadCityZip(city, btn) {
  const origHtml = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="tw-progress-spinner" style="border-color:#ccc;border-top-color:#0071e3"></span> 打包中…`;
  try {
    const token = localStorage.getItem("audit.token") || "";
    const url = `/api/exports/worksheets/city/${encodeURIComponent(city)}.zip`;
    const r = await fetch(url, { headers: { "Authorization": `Bearer ${token}` } });
    if (!r.ok) {
      const msg = r.status === 401 ? "请重新登录" : `下载失败 (${r.status}): ${await r.text()}`;
      toast(msg, "error");
      return;
    }
    const blob = await r.blob();
    const objUrl = URL.createObjectURL(blob);
    const cd = r.headers.get("Content-Disposition") || "";
    const m = cd.match(/filename\*=UTF-8''([^;]+)/);
    const name = m ? decodeURIComponent(m[1]) : `${city}_已定稿工作底稿.zip`;
    const a = document.createElement("a");
    a.href = objUrl;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(objUrl), 60000);
    toast(`${city} 下载完成`);
  } catch (e) {
    toast(`下载出错：${e.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = origHtml;
  }
}
```

在 dashboard 初始化处（如 `loadDashboard()`）加 `renderExportRegion();`。

#### 3. cache-buster

`?v=2.10` → `?v=2.11`

### README

```markdown
- **v2.11（2026-07-12）**：工作台加"批量导出已定稿工作底稿"card。按市分组显示 finalized 任务数，一键下载该市 zip（内含 `市/区县/单位_年_id.xlsx` 分层）。市从 unit.name 自动解析（无 DB 字段迁移）；解析失败归入"未分类"桶
```

## 涉及文件

| 文件 | 变更 |
|---|---|
| `backend/app/services/region_parser.py` | 新建 |
| `backend/tests/test_region_parser.py` | 新建（6 条 pytest）|
| `backend/app/api/export_routes.py` | 新建 |
| `backend/app/main.py` | include_router(exports_router) 一行 |
| `backend/tests/test_export_region.py` | 新建（5-6 条 pytest）|
| `frontend/index.html` | 工作台加 card + `?v=2.10` → `?v=2.11` |
| `frontend/app.js` | `renderExportRegion` + `_downloadCityZip` |
| `README.md` | v2.11 更新日志 |

## 部署

1. 后端 scp 3 个新 py 文件 + main.py 到 ECS
2. `docker compose cp` 到 backend / worker / enrich_worker（虽然 worker 不用 export 端点，保持一致）
3. `docker compose restart backend worker enrich_worker`
4. Workbench 上传 index.html + app.js
5. 浏览器 Cmd+Shift+R

## 手工验证

- [ ] 工作台加载后能看到"批量导出已定稿工作底稿"card
- [ ] 若无 finalized 任务 → 显示"暂无已定稿任务可导出"
- [ ] 有 finalized 任务 → 表格按市分组，任务数/单位数正确
- [ ] 点某市"下载 zip" → 按钮变"打包中…"，几秒后浏览器触发下载
- [ ] 下载的 zip 文件名含中文市名 + 份数
- [ ] 解压 zip 后目录结构 `<市>/<区县>/<单位>_<年>_<id>.xlsx`
- [ ] 单位名解析不了的行显示"未分类"+橙色 badge，也可下载
- [ ] 打开一个 xlsx 内容与从任务详情"下载 Excel 底稿"一致
- [ ] 未登录时点下载 → toast "请重新登录"（不是 JSON tab）

## 风险 & 缓解

| 风险 | 概率 | 缓解 |
|---|---|---|
| 单市任务多（如上百个）zip 生成慢 | 中 | 服务端流式打包（`zipfile` 边写边流），前端按钮 disabled + spinner |
| 内存爆：每 xlsx 数百 KB，100 份 = 数十 MB | 低 | `io.BytesIO` 单市可控；如未来一市 >1000 任务再改成 disk-backed |
| 单位名恶意 `/` 或路径注入 | 低 | zip entry 里 replace `/` `\\` 为 `_` |
| region_parser 解析错（如"XX县级市"名字里带"市"）| 中 | 提供"未分类"桶兜底 + 单测覆盖典型误分类模式 |
| 权限漏洞：普通用户下载全库定稿数据 | 中 | 用现有 `get_current_user`，未来加租户过滤（YAGNI） |

## 回滚

git revert 一个 commit → cp 老文件回容器 → restart backend；前端也 revert 后 Workbench 重传。
