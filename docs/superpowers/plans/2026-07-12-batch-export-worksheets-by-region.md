# v2.11 工作台批量导出已定稿工作底稿（按地区）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 工作台加"批量导出已定稿工作底稿"card，按市分组一键下载 zip（内含 `市/区县/单位_年_id.xlsx` 分层）。

**Architecture:** 后端从 `unit.name` 用正则解析行政区划（无 DB 迁移），新 `export_routes.py` 提供 `region-summary` JSON + `worksheets/city/{city}.zip` 流式打包端点，复用现有 `build_worksheet_xlsx(db, task, ws)`。前端工作台加 card + 表格 + 走 v2.9 建立的 fetch+blob+a[download] 模式（Bearer token）。

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy + zipfile stdlib（backend）; Vanilla JS + fetch+blob（frontend）; pytest.

## Global Constraints

- 无 DB 迁移：地区从 `unit.name` 派生（`region_parser.parse_region`），解析失败归"未分类"桶
- 只导出 `AuditTask.status == "finalized"` 的任务
- Zip 内目录结构：`<市>/<区县>/<单位名>_<年度>_<任务id>.xlsx`；区县缺失时用 `_未分类` 目录
- 直辖市（北京/上海/天津/重庆）跳省级，直接匹配区
- 端点 URL 用中文时必须 URL-encode（`encodeURIComponent` on frontend, `quote` on backend Content-Disposition）
- 前端下载必须走 fetch+blob（携带 Bearer token），不用 `<a href>` 直连（否则 401，见 v2.9 [[project-architecture]]）
- 后端 py 文件改后 `docker compose cp` 到 backend + worker + enrich_worker 三容器
- Zip entry 名里 `/` `\` 替换为 `_`（防路径注入）
- 中文注释 + commit 消息

---

## File Structure

| 文件 | 责任 | 状态 |
|---|---|---|
| `compliance-agent/backend/app/services/region_parser.py` | `parse_region(unit_name) -> tuple[Optional[str], Optional[str]]` 纯函数，正则匹配行政区划 | 新建 |
| `compliance-agent/backend/tests/test_region_parser.py` | 6 条 pytest，覆盖直辖市 / 省+市+区 / 只有市 / 自治州 / 空 / 解析失败 | 新建 |
| `compliance-agent/backend/app/api/export_routes.py` | `exports_router`：region-summary + city zip 端点 | 新建 |
| `compliance-agent/backend/app/main.py` | `include_router(exports_router)` 一行 + import | 修改 |
| `compliance-agent/backend/tests/test_export_region.py` | 5 条 pytest：summary 结构 / finalized only / zip 目录结构 / city 404 / 单位名 sanitize | 新建 |
| `compliance-agent/frontend/index.html` | 工作台加"批量导出"card；`?v=2.10` → `?v=2.11` | 修改 |
| `compliance-agent/frontend/app.js` | `loadDashboard` 末加 `renderExportRegion()`；新增 `renderExportRegion` + `_downloadCityZip` 函数 | 修改 |
| `compliance-agent/README.md` | v2.11 更新日志 | 修改 |

---

## Task 1: region_parser 纯函数 + 单测（TDD）

**Files:**
- Create: `compliance-agent/backend/app/services/region_parser.py`
- Test: `compliance-agent/backend/tests/test_region_parser.py`

**Interfaces:**
- Consumes: 无（Python stdlib）
- Produces: `parse_region(unit_name: str) -> tuple[Optional[str], Optional[str]]`

- [ ] **Step 1: Write first failing test**

新建 `compliance-agent/backend/tests/test_region_parser.py`：

```python
"""v2.11 region_parser 单测。"""


def test_parse_normal_city_district():
    """省+市+区县 → (市, 区县)。"""
    from app.services.region_parser import parse_region
    assert parse_region("四川省达州市达川区幺塘乡人民政府") == ("达州市", "达川区")
```

- [ ] **Step 2: Run test — verify RED**

```bash
cd compliance-agent/backend && python -m pytest tests/test_region_parser.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.services.region_parser'`

- [ ] **Step 3: 写 region_parser.py**

新建 `compliance-agent/backend/app/services/region_parser.py`：

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

# 直辖市（跳过省级匹配）
MUNICIPALITIES = {"北京市", "上海市", "天津市", "重庆市"}

# 省级前缀（省 / 自治区）—— 剥离后再匹配市，避免非贪婪 _CITY_RE
# 在 "四川省达州市..." 上把整段 "四川省达州市" 吞成 city 的 bug
_PROVINCE_RE = re.compile(r"^[一-龥]{2,10}?(?:省|自治区)")
# 市匹配：XX市 / XX自治州 / XX地区 / XX盟；限 2-6 字防过匹配
_CITY_RE = re.compile(r"([一-龥]{2,6}?(?:市|自治州|地区|盟))")
# 区县匹配：XX区 / XX县 / XX自治县 / XX旗
_DISTRICT_RE = re.compile(r"([一-龥]{2,6}?(?:区|县|自治县|旗))")


def parse_region(unit_name: str) -> tuple[Optional[str], Optional[str]]:
    """从单位名提取 (市, 区县)。"""
    if not unit_name:
        return (None, None)
    # 直辖市优先
    for muni in MUNICIPALITIES:
        if muni in unit_name:
            after_muni = unit_name.split(muni, 1)[-1]
            m = _DISTRICT_RE.search(after_muni)
            return (muni, m.group(1) if m else None)
    # 剥离省级前缀（如"四川省"、"内蒙古自治区"），再匹配市
    remaining = _PROVINCE_RE.sub("", unit_name)
    city_m = _CITY_RE.search(remaining)
    if not city_m:
        return (None, None)
    city = city_m.group(1)
    after_city = remaining[city_m.end():]
    dist_m = _DISTRICT_RE.search(after_city)
    return (city, dist_m.group(1) if dist_m else None)
```

- [ ] **Step 4: Run test — verify GREEN**

```bash
cd compliance-agent/backend && python -m pytest tests/test_region_parser.py -v
```

Expected: 1 PASS

- [ ] **Step 5: 加剩余 5 条测试**

Append to `compliance-agent/backend/tests/test_region_parser.py`：

```python
def test_parse_municipality_beijing():
    """直辖市：北京市海淀区 → (北京市, 海淀区)。"""
    from app.services.region_parser import parse_region
    assert parse_region("北京市海淀区某单位") == ("北京市", "海淀区")


def test_parse_only_city_no_district():
    """只有市：达州市财政局 → (达州市, None)。"""
    from app.services.region_parser import parse_region
    assert parse_region("达州市财政局") == ("达州市", None)


def test_parse_autonomous_prefecture():
    """自治州：凉山彝族自治州西昌市 → (凉山彝族自治州, None)。

    注意：正则贪婪匹配到"自治州"就停；"西昌市"作为县级市不作为区县。
    """
    from app.services.region_parser import parse_region
    city, district = parse_region("凉山彝族自治州西昌市某单位")
    assert city == "凉山彝族自治州"
    # 区县可能为 None（西昌市是县级市，不匹配 区|县|自治县|旗）
    assert district is None


def test_parse_empty_returns_none_none():
    """空字符串 / None → (None, None)。"""
    from app.services.region_parser import parse_region
    assert parse_region("") == (None, None)
    assert parse_region(None) == (None, None)


def test_parse_no_city_pattern():
    """无市字样：某某局 → (None, None)。"""
    from app.services.region_parser import parse_region
    assert parse_region("某某局") == (None, None)
```

- [ ] **Step 6: Run all 6 tests**

```bash
cd compliance-agent/backend && python -m pytest tests/test_region_parser.py -v
```

Expected: 6 PASS

- [ ] **Step 7: Commit**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/backend/app/services/region_parser.py \
        compliance-agent/backend/tests/test_region_parser.py
git commit -m "$(cat <<'EOF'
feat(v2.11): region_parser 从 unit.name 提取 (市, 区县)

- 直辖市（北京/上海/天津/重庆）跳省级
- 普通市 + 自治州 / 地区 / 盟 均识别
- 区县：区 / 县 / 自治县 / 旗
- 解析失败返回 (None, None)，归入"未分类"桶
- 6 条 pytest 覆盖典型场景

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: export_routes.py + main.py 注册 + 端点测试

**Files:**
- Create: `compliance-agent/backend/app/api/export_routes.py`
- Modify: `compliance-agent/backend/app/main.py`（import + include_router 一行）
- Test: `compliance-agent/backend/tests/test_export_region.py`

**Interfaces:**
- Consumes:
  - `parse_region(unit_name)` from `app.services.region_parser`（Task 1）
  - `get_worksheet(db, task_id) -> Optional[Worksheet]` from `app.services.worksheet_service`
  - `build_worksheet_xlsx(db, task, ws) -> bytes` from `app.services.worksheet_export`
  - `get_current_user`, `get_db`, `AuditTask`, `AuditUnit`, `Worksheet`, `User` from existing
- Produces:
  - `exports_router = APIRouter(prefix="/api/exports", tags=["exports"])`
  - `GET /api/exports/region-summary` → `list[dict]`，每项 `{"city", "task_count", "unit_count", "unknown"}`
  - `GET /api/exports/worksheets/city/{city}.zip` → `StreamingResponse` (media_type=`application/zip`)
  - 模块常量 `UNCLASSIFIED = "未分类"`

- [ ] **Step 1: Write first failing test — summary 只列 finalized**

新建 `compliance-agent/backend/tests/test_export_region.py`：

```python
"""v2.11 批量导出（按地区）端点测试。"""
import io
import zipfile

from fastapi.testclient import TestClient


def _create_finalized_task(client, headers, unit_name, task_name):
    """建 unit + task，把 task 直接推到 finalized 状态并生成 worksheet。"""
    r = client.post("/api/units",
                    json={"name": unit_name, "code": "R"},
                    headers=headers)
    assert r.status_code == 200, r.text
    unit_id = r.json()["id"]
    r = client.post("/api/tasks",
                    json={"unit_id": unit_id, "name": task_name,
                          "eval_year": 2025, "scope": "all"},
                    headers=headers)
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]
    # 直接改 status + 生成 worksheet（跳 AI 核查，用 DB 直改）
    from app.models import SessionLocal, AuditTask, Worksheet
    with SessionLocal() as s:
        t = s.get(AuditTask, task_id)
        t.status = "finalized"
        ws = Worksheet(task_id=task_id, status="finalized", version=1)
        s.add(ws)
        s.commit()
    return task_id


def test_region_summary_only_finalized(auth_headers):
    """/exports/region-summary 只统计 finalized，其它状态忽略。"""
    from app.main import app
    with TestClient(app) as client:
        _create_finalized_task(client, auth_headers, "达州市达川区X局_summary1", "T1")
        # 建一个 non-finalized 任务（默认 status=pending）
        client.post("/api/units", json={"name": "非定稿单位_S1", "code": "R"},
                    headers=auth_headers)

        r = client.get("/api/exports/region-summary", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        # 达州市桶存在且 count=1；非定稿单位不出现
        dazhou = next((d for d in data if d["city"] == "达州市"), None)
        assert dazhou is not None
        assert dazhou["task_count"] >= 1
```

- [ ] **Step 2: Run test — verify RED**

```bash
cd compliance-agent/backend && python -m pytest tests/test_export_region.py::test_region_summary_only_finalized -v
```

Expected: `404 Not Found` on `/api/exports/region-summary`（端点尚未注册）

- [ ] **Step 3: 写 export_routes.py**

新建 `compliance-agent/backend/app/api/export_routes.py`：

```python
"""v2.11：批量导出已定稿工作底稿（按地区）。

端点：
- GET /api/exports/region-summary   → 按市聚合的 finalized 任务统计
- GET /api/exports/worksheets/city/{city}.zip → 该市所有已定稿底稿 zip
"""
from __future__ import annotations

import io
import zipfile
from collections import defaultdict
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.models import AuditTask, AuditUnit, User, get_db
from app.services.region_parser import parse_region
from app.services.worksheet_export import build_worksheet_xlsx
from app.services.worksheet_service import get_worksheet

exports_router = APIRouter(prefix="/api/exports", tags=["exports"])

# "未分类"桶标识（前后端共用）
UNCLASSIFIED = "未分类"


def _list_finalized_by_city(db: Session) -> list[dict]:
    """按市聚合 finalized 任务。"""
    rows = (
        db.query(AuditTask, AuditUnit.name)
        .join(AuditUnit, AuditTask.unit_id == AuditUnit.id)
        .filter(AuditTask.status == "finalized")
        .all()
    )
    grouped: dict[str, dict] = defaultdict(
        lambda: {"task_count": 0, "unit_ids": set(), "unknown": False}
    )
    for task, unit_name in rows:
        city, _ = parse_region(unit_name)
        key = city or UNCLASSIFIED
        grouped[key]["task_count"] += 1
        grouped[key]["unit_ids"].add(task.unit_id)
        if not city:
            grouped[key]["unknown"] = True
    return [
        {"city": k, "task_count": v["task_count"],
         "unit_count": len(v["unit_ids"]), "unknown": v["unknown"]}
        for k, v in sorted(
            grouped.items(),
            key=lambda kv: (kv[1]["unknown"], -kv[1]["task_count"]),
        )
    ]


@exports_router.get("/region-summary")
def region_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """列出已定稿任务按市分组的统计。"""
    return _list_finalized_by_city(db)


@exports_router.get("/worksheets/city/{city}.zip")
def download_city_zip(
    city: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """下载某市所有已定稿任务的工作底稿 zip。

    Zip 内目录：<市>/<区县>/<单位名>_<年度>_<任务id>.xlsx；
    区县缺失时归 <市>/_未分类/。
    """
    if not city:
        raise HTTPException(400, "city 参数必填")

    all_rows = (
        db.query(AuditTask, AuditUnit.name)
        .join(AuditUnit, AuditTask.unit_id == AuditUnit.id)
        .filter(AuditTask.status == "finalized")
        .all()
    )
    match_rows = []
    for task, unit_name in all_rows:
        parsed_city, district = parse_region(unit_name)
        actual_city = parsed_city or UNCLASSIFIED
        if actual_city == city:
            match_rows.append((task, unit_name, district))
    if not match_rows:
        raise HTTPException(404, f"'{city}' 下无已定稿任务")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for task, unit_name, district in match_rows:
            ws = get_worksheet(db, task.id)
            if not ws:
                continue  # 定稿但 worksheet 缺失（异常状态），跳过
            xlsx_bytes = build_worksheet_xlsx(db, task, ws)
            dist_dir = district or "_未分类"
            # 路径注入防御：sanitize 单位名
            safe_unit = unit_name.replace("/", "_").replace("\\", "_")
            entry = f"{city}/{dist_dir}/{safe_unit}_{task.eval_year}_{task.id}.xlsx"
            zf.writestr(entry, xlsx_bytes)
    buf.seek(0)
    filename = f"{city}_已定稿工作底稿_{len(match_rows)}份.zip"
    filename_quoted = quote(filename)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition":
                f'attachment; filename="worksheets_{quote(city)}.zip"; '
                f"filename*=UTF-8''{filename_quoted}",
        },
    )
```

- [ ] **Step 4: 注册 router 到 main.py**

修改 `compliance-agent/backend/app/main.py`。找到 `app.include_router(materials_router)`（约 line 46），在其**之后**插入：

```python
from app.api.export_routes import exports_router
app.include_router(exports_router)
```

**验证 import 顺序**：`from app.api.export_routes` 应该也在文件顶部 import 区，跟 audit_routes/knowledge_routes 一起。为了简洁本任务允许把 import 就近放在 include_router 处（跟随现有模式；如果 lint 抱怨，移到顶部）。

- [ ] **Step 5: Run first test — verify GREEN**

```bash
cd compliance-agent/backend && python -m pytest tests/test_export_region.py::test_region_summary_only_finalized -v
```

Expected: PASS

- [ ] **Step 6: 加剩余 4 条测试**

Append to `compliance-agent/backend/tests/test_export_region.py`：

```python
def test_region_summary_unclassified_bucket(auth_headers):
    """无法解析地区的单位归入"未分类"桶，unknown=True。"""
    from app.main import app
    with TestClient(app) as client:
        _create_finalized_task(client, auth_headers, "某某局_no_region", "T_UNK")
        r = client.get("/api/exports/region-summary", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        unclassified = next((d for d in data if d["city"] == "未分类"), None)
        assert unclassified is not None
        assert unclassified["unknown"] is True
        assert unclassified["task_count"] >= 1


def test_download_city_zip_structure(auth_headers, tmp_path):
    """下载 zip → 目录结构 <市>/<区县>/<单位>_<年>_<id>.xlsx。"""
    from app.main import app
    with TestClient(app) as client:
        tid = _create_finalized_task(
            client, auth_headers,
            "四川省达州市达川区试点单位_Z1", "T_Z1"
        )
        r = client.get(
            "/api/exports/worksheets/city/%E8%BE%BE%E5%B7%9E%E5%B8%82.zip",
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/zip"
        # 解析 zip
        zbuf = io.BytesIO(r.content)
        with zipfile.ZipFile(zbuf) as zf:
            names = zf.namelist()
        # 至少一个 entry 路径匹配 达州市/达川区/<...>_2025_<tid>.xlsx
        matched = [n for n in names
                   if n.startswith("达州市/达川区/")
                   and n.endswith(f"_2025_{tid}.xlsx")]
        assert matched, f"zip 内未找到期望的 entry；实际 names={names}"


def test_download_city_zip_404_when_city_empty(auth_headers):
    """请求不存在的市 → 404。"""
    from app.main import app
    with TestClient(app) as client:
        r = client.get(
            "/api/exports/worksheets/city/%E4%B8%8D%E5%AD%98%E5%9C%A8%E7%9A%84%E5%B8%82.zip",
            headers=auth_headers,
        )
        assert r.status_code == 404


def test_download_city_zip_sanitizes_slash_in_unit_name(auth_headers):
    """单位名含 / → zip entry 里 / 被 _ 替换（防路径注入）。"""
    from app.main import app
    with TestClient(app) as client:
        # 注意：AuditUnit.name 有 UNIQUE 约束；本测独立 name
        _create_finalized_task(
            client, auth_headers,
            "达州市达川区a/b单位_slash_test", "T_SLASH",
        )
        r = client.get(
            "/api/exports/worksheets/city/%E8%BE%BE%E5%B7%9E%E5%B8%82.zip",
            headers=auth_headers,
        )
        assert r.status_code == 200
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            names = zf.namelist()
        # 单位名段里不应含未转义的 /；用 _ 替换后是 "a_b单位_slash_test"
        assert any("a_b单位_slash_test" in n for n in names), \
            f"未找到 sanitize 后的 entry；names={names}"
```

- [ ] **Step 7: Run all export tests + regression**

```bash
cd compliance-agent/backend && python -m pytest tests/test_export_region.py tests/test_region_parser.py -v
```

Expected: 6 (region_parser) + 4 (export) = 10 PASS

- [ ] **Step 8: Commit**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/backend/app/api/export_routes.py \
        compliance-agent/backend/app/main.py \
        compliance-agent/backend/tests/test_export_region.py
git commit -m "$(cat <<'EOF'
feat(v2.11): export_routes 批量导出已定稿工作底稿

- GET /api/exports/region-summary：按市聚合 finalized 任务统计
- GET /api/exports/worksheets/city/{city}.zip：流式打包 xlsx
- Zip 目录 <市>/<区县>/<单位>_<年>_<id>.xlsx，未分类桶兜底
- 单位名 / \ 替换为 _ 防路径注入
- 4 条 pytest 覆盖 summary 过滤 / zip 结构 / 404 / sanitize

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 前端工作台加 card + JS 渲染 + 下载

**Files:**
- Modify: `compliance-agent/frontend/index.html`（工作台加 card；`?v=2.10` → `?v=2.11`）
- Modify: `compliance-agent/frontend/app.js`（`loadDashboard` 末加调用；新增 `renderExportRegion` + `_downloadCityZip`）

**Interfaces:**
- Consumes:
  - `api(path)` helper（`app.js:30`，`/api` 前缀 + Bearer token 自动）
  - `esc(s)` helper
  - `toast(msg, level?)` helper
  - `localStorage.getItem("audit.token")` — Bearer token
  - 后端端点 `GET /api/exports/region-summary` 和 `GET /api/exports/worksheets/city/{city}.zip`（Task 2）
- Produces:
  - JS 函数 `renderExportRegion()` — 无参，读取 DOM `#dash-export-region`
  - JS 函数 `_downloadCityZip(city, btn)` — 带 fetch+blob 下载
  - DOM 结构：`<div id="dash-export-region">` + 内部动态 table

- [ ] **Step 1: 在 index.html 加 card**

打开 `compliance-agent/frontend/index.html`，定位到工作台 `<section id="page-dashboard">` 里的"最近任务" grid-2 之后、"五维核查范式" card 之前（现在结构是 grid-2 后直接接 `<div class="card mt-6 fade-in fade-in-4">` 五维范式）。

找到：

```html
        <div class="grid-2">
          <div class="card fade-in fade-in-2">
            <div class="section-title">待我处理</div>
            <div id="dash-pending"></div>
          </div>
          <div class="card fade-in fade-in-3">
            <div class="section-title">最近任务</div>
            <div id="dash-recent"></div>
          </div>
        </div>

        <div class="card mt-6 fade-in fade-in-4">
          <div class="section-title">五维核查范式</div>
```

在 `</div>`（grid-2 结束）和 `<div class="card mt-6 fade-in fade-in-4">`（五维范式开始）之间插入：

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

**注意**：新 card 和五维范式 card 都用了 `fade-in-4` — 视觉上无害（都在同一动画帧）。如果视觉审查后觉得需要，把新 card 的 class 改为 `fade-in fade-in-4`，五维范式那个改成 `fade-in fade-in-5`（如果 CSS 定义了）。**本步骤不改五维范式的 class**。

- [ ] **Step 2: bump cache-buster**

```bash
grep -n "?v=2\." compliance-agent/frontend/index.html
```

用 Edit 工具把每处 `?v=2.10` 改成 `?v=2.11`（`replace_all=true`）。

- [ ] **Step 3: 在 app.js 加 renderExportRegion 和 _downloadCityZip**

定位到 `compliance-agent/frontend/app.js:218 loadDashboard()` 函数。找到 loadDashboard 里当前的最后一行（约 line 260-280 后的 `}`，`loadDashboard` 函数关闭的花括号之前的最后一句）。

在函数结尾（return / 关闭花括号之前）添加：

```javascript
    // v2.11: 工作台批量导出按市分组
    renderExportRegion();
```

然后在 `loadDashboard` 函数**之后**新增两个函数：

```javascript

// v2.11: 工作台批量导出已定稿工作底稿（按市分组）
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
          <tr>
            <th>市</th>
            <th style="width:100px">任务数</th>
            <th style="width:100px">单位数</th>
            <th style="width:160px">操作</th>
          </tr>
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
                  下载 zip
                </button>
              </td>
            </tr>`;
          }).join("")}
        </tbody>
      </table>
    `;
    // 事件绑定
    box.querySelectorAll(".dash-export-btn").forEach(btn => {
      btn.addEventListener("click", () => _downloadCityZip(btn.dataset.city, btn));
    });
  } catch (e) {
    box.innerHTML = `<div class="empty-state" style="padding:16px;color:#b8262b">加载失败：${esc(e.message)}</div>`;
  }
}

// v2.11: 下载某市的 zip（fetch+blob 携带 Bearer token，避 <a href> 401）
async function _downloadCityZip(city, btn) {
  const origHtml = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="tw-progress-spinner" style="border-color:#ccc;border-top-color:#0071e3"></span> 打包中…`;
  try {
    const token = localStorage.getItem("audit.token") || "";
    const url = `/api/exports/worksheets/city/${encodeURIComponent(city)}.zip`;
    const r = await fetch(url, {
      headers: { "Authorization": `Bearer ${token}` },
    });
    if (!r.ok) {
      const msg = r.status === 401
        ? "请重新登录"
        : `下载失败 (${r.status}): ${await r.text()}`;
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

- [ ] **Step 4: 语法检查**

```bash
cd compliance-agent/frontend && node --check app.js && echo "SYNTAX OK"
grep -c "renderExportRegion" app.js
grep -c "_downloadCityZip" app.js
grep -c "dash-export-region" index.html
grep -c "?v=2.11" index.html
```

Expected:
- `SYNTAX OK`
- `renderExportRegion`: `>=2`（定义 + loadDashboard 调用）
- `_downloadCityZip`: `>=2`（定义 + 事件绑定内调用）
- `dash-export-region`: `1`（新 card 里的 div id）
- `?v=2.11`: `3`（styles.css + pinyin_initials.js + app.js）

- [ ] **Step 5: Commit**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/frontend/index.html compliance-agent/frontend/app.js
git commit -m "$(cat <<'EOF'
feat(v2.11): 工作台"批量导出已定稿工作底稿"card

- index.html: 加 card，按市分组表格 + 下载 zip 按钮
- app.js: renderExportRegion + _downloadCityZip（fetch+blob 携带
  Bearer token，复用 v2.9 建立的 SPA 下载模式）
- cache-buster 2.10 → 2.11

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 部署 + 手工验证 + README

**Files:**
- 无代码改动
- Modify: `compliance-agent/README.md`（v2.11 更新日志）

**Interfaces:** 无

- [ ] **Step 1: 用户 Workbench 上传 3+2 个文件到 ECS**

给用户以下清单（Workbench 拖拽或 scp）：

后端 3 个新/改文件（去到 `/opt/audit/compliance-agent/backend/` 对应路径）：
- `backend/app/services/region_parser.py` → 新文件
- `backend/app/api/export_routes.py` → 新文件
- `backend/app/main.py` → 覆盖

前端 2 个（去到 `/opt/audit/compliance-agent/frontend/`）：
- `frontend/index.html`
- `frontend/app.js`

- [ ] **Step 2: 服务器 docker cp + restart**

```bash
cd /opt/audit/compliance-agent

# 后端 3 文件 cp 到 backend / worker / enrich_worker
for c in backend worker enrich_worker; do
  docker compose cp backend/app/services/region_parser.py $c:/app/app/services/region_parser.py
  docker compose cp backend/app/api/export_routes.py $c:/app/app/api/export_routes.py
  docker compose cp backend/app/main.py $c:/app/app/main.py
done

# 重启后端三容器
docker compose restart backend worker enrich_worker

# 验证：backend 启动无 import 报错，log 里能看到 exports router 挂载
docker compose logs backend --tail=20
```

Expected: log 里无 `ImportError` / `ModuleNotFoundError`；`Application startup complete.` 出现。

前端 bind mount，无需 cp，无需 restart nginx。

- [ ] **Step 3: 后端冒烟测试**

```bash
# 拿 token（假设 admin/admin123 或用户已改的强密码）
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"<你的密码>"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")

# summary 端点
curl -s http://localhost:8000/api/exports/region-summary \
    -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Expected: 返回 JSON 数组，每项含 city / task_count / unit_count / unknown 四字段；已定稿任务被按市分组。若无 finalized 任务返回 `[]`。

**注意**：如果 admin 密码不确定，可跳过 curl 测试直接进 Step 4 浏览器验证。

- [ ] **Step 4: 浏览器手工验证 checklist**

打开 `http://8.163.75.9/`，Cmd+Shift+R 硬刷（F12 Network 看 `app.js?v=2.11`）。进"工作台"页。

- [ ] "批量导出已定稿工作底稿" card 出现在"最近任务"下方、"五维核查范式"上方
- [ ] 若无 finalized 任务 → 显示"暂无已定稿任务可导出"
- [ ] 有 finalized 任务 → 表格展示：市 / 任务数 / 单位数 / 下载按钮
- [ ] 未分类桶带橙色"解析失败"badge，排在正常市后面
- [ ] 点某市"下载 zip"按钮 → 按钮变"打包中…"，几秒后浏览器触发下载
- [ ] 下载的文件名含中文市名和份数（如"达州市_已定稿工作底稿_12份.zip"）
- [ ] 解压 zip → 结构为 `<市>/<区县>/<单位>_<年>_<id>.xlsx`
- [ ] 未分类的桶 zip 内是 `<市>/_未分类/<单位>_...`
- [ ] 打开一个 xlsx → 内容与从任务详情"下载 Excel 底稿"一致
- [ ] 点击时未登录（如 token 过期）→ toast "请重新登录"，不是 JSON tab

**任意 checklist 项失败** → 回退到 Task 1/2/3 修 → 重新部署 → 重跑 checklist。

- [ ] **Step 5: 更新 README**

Edit `compliance-agent/README.md`。找到"## 更新日志（部分）"段，在 v2.10 之前插入：

```markdown
- **v2.11（2026-07-12）**：工作台加"批量导出已定稿工作底稿"card。后端 `region_parser` 从 `unit.name` 解析（市, 区县），新端点 `/api/exports/region-summary` + `/api/exports/worksheets/city/{city}.zip` 流式打包 xlsx。前端复用 v2.9 fetch+blob 下载模式（携带 Bearer token）。zip 内目录 `<市>/<区县>/<单位>_<年>_<id>.xlsx`；解析失败归"未分类"桶。详见 `docs/superpowers/plans/2026-07-12-batch-export-worksheets-by-region.md`
```

- [ ] **Step 6: Commit README**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/README.md
git commit -m "$(cat <<'EOF'
docs(v2.11): README 加更新日志

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec coverage:**
- ✅ `region_parser.parse_region` 从 unit.name 提取 (市, 区县) → Task 1
- ✅ 直辖市特判 → Task 1（MUNICIPALITIES + 优先分支）
- ✅ 解析失败 (None, None) → Task 1（Step 5 中 `test_parse_no_city_pattern`）
- ✅ `GET /api/exports/region-summary` → Task 2 Step 3
- ✅ `GET /api/exports/worksheets/city/{city}.zip` → Task 2 Step 3
- ✅ Zip 内 `<市>/<区县>/<单位>_<年>_<id>.xlsx` → Task 2 Step 3 + test Step 6
- ✅ `_未分类` 目录 → Task 2 Step 3（`dist_dir = district or "_未分类"`）
- ✅ 单位名 `/` `\` sanitize → Task 2 Step 3 + test Step 6
- ✅ 只导出 finalized → Task 2 Step 3 filter + test Step 1
- ✅ router 注册 → Task 2 Step 4
- ✅ 前端工作台 card → Task 3 Step 1
- ✅ 表格 + 下载按钮 → Task 3 Step 3
- ✅ 未分类橙色 badge → Task 3 Step 3（cityLabel 三元）
- ✅ fetch+blob 下载模式 → Task 3 Step 3 (`_downloadCityZip`)
- ✅ 401 toast → Task 3 Step 3
- ✅ cache-buster ?v=2.10 → ?v=2.11 → Task 3 Step 2
- ✅ 部署 cp 3 容器 + restart → Task 4 Step 2
- ✅ 手工 verification checklist → Task 4 Step 4（10 条）
- ✅ README → Task 4 Step 5
- ✅ 回滚方案（git revert + Workbench 重传老文件）→ spec 已注明

**Placeholder scan:**
- 无 TODO/TBD
- 每个代码块完整
- 所有命令有 Expected 输出
- Task 4 Step 3 curl 密码占位符 `<你的密码>` 是合理的用户交互输入，不是代码占位符

**Type consistency:**
- `parse_region(unit_name: str) -> tuple[Optional[str], Optional[str]]` — 一致（Task 1 Step 3 + Task 2 用到）
- `_list_finalized_by_city(db) -> list[dict]` — 一致
- Router prefix `/api/exports` — 一致（Task 2 Step 3 + 前端 Task 3 Step 3 调用 `/exports/region-summary` → `api()` 自动补 `/api`）
- `city` 参数在 URL 中 URL-encode → Task 3 用 `encodeURIComponent`；Task 2 后端拿 raw 中文（FastAPI 自动 decode）
- Dict key `"city" / "task_count" / "unit_count" / "unknown"` 全流程一致
- `UNCLASSIFIED = "未分类"` 常量 + 前端 `r.city === "未分类"` 隐式匹配（不需要 export 常量到前端；前端只判 `r.unknown` bool）

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-12-batch-export-worksheets-by-region.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — Task 1/2/3 每个派 fresh subagent + review；Task 4 部署 checklist 交给用户浏览器

**2. Inline Execution** — 本会话直接跑 Task 1/2/3，Task 4 hand-off checklist 给用户

Which approach?
