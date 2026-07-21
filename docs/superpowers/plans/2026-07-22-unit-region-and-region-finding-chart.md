# v2.14 单位地区落库 + 地区×问题维度可视化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AuditUnit 加 `region` 字段并从 Excel import 22 类地区值 → 修 v2.11 export 用 `unit.region` 替代正则解析 → 工作台加"地区×问题维度分布"card。

**Architecture:** DB schema 加 `region` 列（一次 ALTER TABLE + `Base.metadata.create_all()` 自动兼容测试）。Import 脚本用 openpyxl 读 Excel，按 code 优先/name fallback 匹配。Export 端点直接读 `unit.region`。新 dashboard 端点用 2 条聚合 SQL（unit_count + finding_count by region/type）返矩阵。前端加大表格 22 行 × 8 列，每格数字+mini bar+百分比。

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy + openpyxl 3.1.2（已在 requirements）+ pytest（backend）; Vanilla JS（frontend）.

## Global Constraints

- `AuditUnit.region` = `String(32)`, `default=""`, `index=True`
- Import 匹配策略：code 优先 → name fallback；两都不中 → warn 记入统计；已有 region 值的 unit **跳过**（保护人工修正 + 幂等）
- Import CLI：`--xlsx <path>` 必填 + `--dry-run | --apply` 二选一（互斥必填）
- Export 端点 v2.11 `_list_finalized_by_city` + `download_city_zip` 都改用 `unit.region` 替代 `parse_region(unit.name)`；`region=""` 归 UNCLASSIFIED
- 新端点 `GET /api/dashboard/region-finding-stats` → dict `{finding_types: [...], regions: [{region, unit_count, counts: {type:int}, total}]}`
- Finding 6 类：从 `app.services.audit_service._VALID_FINDING_TYPES` 取（不重复定义）
- 按 unit_count 降序排（大市在前）；`region == ""` 的 unit 完全排除
- 6 维度百分比 = counts[type] / total × 100%；`total == 0` 时百分比全 0
- 前端 card 位置：工作台 v2.13 "单位核查进度总览" card 之后、v2.11 "批量导出已定稿" card 之前
- 前端渲染：mini bar 用 `<div style="height:4px;background:#eee">` 内嵌 `<div style="width:X%;background:#0071e3">`
- Cache-buster `?v=2.13 → ?v=2.14`（3 处）
- 后端改动 cp 到 backend + worker + enrich_worker 三容器
- 部署前 pg_dump audit_units 备份 → `/opt/audit/backup_v2.14_units_before_<ts>.sql`
- 中文注释 + commit 消息

---

## File Structure

| 文件 | 责任 | 状态 |
|---|---|---|
| `compliance-agent/backend/app/models/entities.py:162-173` | AuditUnit 加 `region` 字段 | 修改 |
| `compliance-agent/backend/app/scripts/import_unit_regions_v214.py` | 新建 —— Excel import 脚本，含 `_load_excel_rows` + `_match_and_update` + CLI | 新建 |
| `compliance-agent/backend/tests/test_import_unit_regions_v214.py` | 3 pytest：code 匹 / name fallback / 已有 region 跳过 | 新建 |
| `compliance-agent/backend/app/api/export_routes.py` | `_list_finalized_by_city` + `download_city_zip` 用 `unit.region` 替代 `parse_region()` | 修改 |
| `compliance-agent/backend/tests/test_export_region.py` | 更新 seed helper 加 `region` 字段 | 修改 |
| `compliance-agent/backend/app/api/dashboard_routes.py` | 加 `region_finding_stats` 端点 | 修改 |
| `compliance-agent/backend/tests/test_dashboard_unit_stats.py` | 加 3 pytest 覆盖 region_finding_stats | 修改 |
| `compliance-agent/frontend/index.html` | 加 card + `?v=2.13` → `?v=2.14` | 修改 |
| `compliance-agent/frontend/app.js` | `renderRegionFindingStatsCard` + loadDashboard 调用 | 修改 |
| `compliance-agent/README.md` | v2.14 更新日志 | 修改 |

---

## Task 1: AuditUnit region 字段 + Import 脚本 + 3 pytest

**Files:**
- Modify: `compliance-agent/backend/app/models/entities.py:162-173`（AuditUnit 加 region 字段）
- Create: `compliance-agent/backend/app/scripts/import_unit_regions_v214.py`
- Test: `compliance-agent/backend/tests/test_import_unit_regions_v214.py`

**Interfaces:**
- Consumes: `openpyxl.load_workbook`；`app.models.AuditUnit, SessionLocal`
- Produces:
  - `AuditUnit.region: Mapped[str]` — String(32), default="", index=True
  - `_load_excel_rows(xlsx_path: str) -> list[dict]` — 返 `[{code, name, region}]`（跳表头 + 空行）
  - `_match_and_update(db, excel_rows: list[dict], dry_run: bool) -> dict` — 返统计 `{excel_rows, matched_by_code, matched_by_name, not_matched, already_had_region, updated}`
  - CLI: `python -m app.scripts.import_unit_regions_v214 --xlsx <path> --dry-run|--apply`

- [ ] **Step 1: 改 AuditUnit 加 region 字段**

打开 `compliance-agent/backend/app/models/entities.py`。找到 `class AuditUnit`（约 line 162）：

```python
class AuditUnit(Base):
    """被检查单位（v3 §3.7 一个独立角色范畴）。"""
    __tablename__ = "audit_units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    code: Mapped[str] = mapped_column(String(64), default="")
    level: Mapped[str] = mapped_column(String(32), default="单位")  # 单位 | 部门
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

在 `level` 与 `description` 之间加：

```python
    level: Mapped[str] = mapped_column(String(32), default="单位")  # 单位 | 部门
    region: Mapped[str] = mapped_column(String(32), default="", index=True)  # v2.14 地区
    description: Mapped[str] = mapped_column(Text, default="")
```

- [ ] **Step 2: 写首条失败测试 —— code 匹**

新建 `compliance-agent/backend/tests/test_import_unit_regions_v214.py`：

```python
"""v2.14 unit region import 脚本测试。"""
import pytest
from openpyxl import Workbook

from app.models import (
    AuditUnit,
    Base,
    SessionLocal,
    engine,
)


@pytest.fixture
def db_session():
    Base.metadata.create_all(engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.query(AuditUnit).delete()
        s.commit()
        s.close()


def _make_excel(tmp_path, rows):
    """rows = [(code, name, region), ...]；返 xlsx 路径。"""
    p = tmp_path / "units.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["代码", "单位名称", "地区"])
    for r in rows:
        ws.append(r)
    wb.save(p)
    return str(p)


def test_match_by_code_updates_region(db_session, tmp_path):
    """按 code 匹到 → region 写入。"""
    from app.scripts.import_unit_regions_v214 import (
        _load_excel_rows, _match_and_update,
    )
    u = AuditUnit(name="v214-code-match", code="C001", region="")
    db_session.add(u); db_session.commit()

    xlsx = _make_excel(tmp_path, [("C001", "任意名字（不用来匹）", "成都市")])
    rows = _load_excel_rows(xlsx)
    stats = _match_and_update(db_session, rows, dry_run=False)

    db_session.refresh(u)
    assert u.region == "成都市"
    assert stats["matched_by_code"] == 1
    assert stats["matched_by_name"] == 0
    assert stats["updated"] == 1
```

- [ ] **Step 3: 跑测试 —— verify RED**

```bash
cd compliance-agent/backend && python -m pytest tests/test_import_unit_regions_v214.py::test_match_by_code_updates_region -v
```

Expected: FAIL `ModuleNotFoundError: No module named 'app.scripts.import_unit_regions_v214'`（或 AuditUnit 无 region 属性）

- [ ] **Step 4: 写 import 脚本**

新建 `compliance-agent/backend/app/scripts/import_unit_regions_v214.py`：

```python
"""v2.14: 从 Excel 导入单位地区字段。

匹配策略：code 优先 → name fallback → 都不中记 not_matched。
已有 region 的 unit 跳过（保护人工修正 + 幂等重复跑安全）。

用法：
    docker compose exec -T backend python -m app.scripts.import_unit_regions_v214 \
        --xlsx /app/data/units.xlsx --dry-run
    docker compose exec -T backend python -m app.scripts.import_unit_regions_v214 \
        --xlsx /app/data/units.xlsx --apply
"""
from __future__ import annotations

import argparse

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app.models import AuditUnit, SessionLocal


def _load_excel_rows(xlsx_path: str) -> list[dict]:
    """读 Excel 返 [{code, name, region}]；跳表头 + 空行。"""
    wb = load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.active
    rows = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        # 需要至少 3 列
        if not r or len(r) < 3:
            continue
        if r[0] is None and r[1] is None:
            continue
        rows.append({
            "code": str(r[0]).strip() if r[0] is not None else "",
            "name": str(r[1]).strip() if r[1] is not None else "",
            "region": str(r[2]).strip() if r[2] is not None else "",
        })
    return rows


def _match_and_update(
    db: Session, excel_rows: list[dict], dry_run: bool,
) -> dict:
    """按 code 优先 name fallback 匹配写 region；已有 region 跳过。"""
    stats = {
        "excel_rows": len(excel_rows),
        "matched_by_code": 0,
        "matched_by_name": 0,
        "not_matched": 0,
        "already_had_region": 0,
        "updated": 0,
    }
    for row in excel_rows:
        if not row["region"]:
            # 该行 region 为空，跳过（不算 not_matched）
            continue
        unit = None
        if row["code"]:
            unit = db.query(AuditUnit).filter(
                AuditUnit.code == row["code"]
            ).first()
            if unit:
                stats["matched_by_code"] += 1
        if unit is None and row["name"]:
            unit = db.query(AuditUnit).filter(
                AuditUnit.name == row["name"]
            ).first()
            if unit:
                stats["matched_by_name"] += 1
        if unit is None:
            stats["not_matched"] += 1
            continue
        if unit.region:
            stats["already_had_region"] += 1
            continue
        if not dry_run:
            unit.region = row["region"]
        stats["updated"] += 1
    if not dry_run:
        db.commit()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="v2.14 从 Excel 导入单位地区字段"
    )
    parser.add_argument("--xlsx", required=True, help="Excel 路径")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--dry-run", action="store_true", help="只统计不改")
    grp.add_argument("--apply", action="store_true", help="真改")
    args = parser.parse_args()

    rows = _load_excel_rows(args.xlsx)
    print(f"Excel 数据行（含 region 空）: {len(rows)}")

    db = SessionLocal()
    try:
        stats = _match_and_update(db, rows, dry_run=args.dry_run)
        print("统计:")
        for k, v in stats.items():
            print(f"  {k}: {v}")
        if args.dry_run:
            print("(dry-run) 未写入 DB")
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 跑首测 —— verify GREEN**

```bash
cd compliance-agent/backend && python -m pytest tests/test_import_unit_regions_v214.py::test_match_by_code_updates_region -v
```

Expected: PASS

- [ ] **Step 6: 加剩余 2 测**

Append to `compliance-agent/backend/tests/test_import_unit_regions_v214.py`：

```python
def test_match_by_name_fallback_when_code_missing(db_session, tmp_path):
    """code 匹不到 → fallback 按 name 匹。"""
    from app.scripts.import_unit_regions_v214 import (
        _load_excel_rows, _match_and_update,
    )
    u = AuditUnit(name="v214-name-only-unit", code="", region="")
    db_session.add(u); db_session.commit()

    # Excel 里 code 是新的，name 一致
    xlsx = _make_excel(tmp_path, [
        ("C_NEW_9999", "v214-name-only-unit", "达州市")
    ])
    rows = _load_excel_rows(xlsx)
    stats = _match_and_update(db_session, rows, dry_run=False)

    db_session.refresh(u)
    assert u.region == "达州市"
    assert stats["matched_by_code"] == 0
    assert stats["matched_by_name"] == 1
    assert stats["updated"] == 1


def test_already_has_region_is_skipped(db_session, tmp_path):
    """已有 region 值的 unit 不被覆盖；stats.already_had_region+=1。"""
    from app.scripts.import_unit_regions_v214 import (
        _load_excel_rows, _match_and_update,
    )
    u = AuditUnit(name="v214-preserved-region", code="C_PRE",
                  region="省级")  # 已有
    db_session.add(u); db_session.commit()

    xlsx = _make_excel(tmp_path, [("C_PRE", "v214-preserved-region", "成都市")])
    rows = _load_excel_rows(xlsx)
    stats = _match_and_update(db_session, rows, dry_run=False)

    db_session.refresh(u)
    assert u.region == "省级"  # 未被覆盖
    assert stats["already_had_region"] == 1
    assert stats["updated"] == 0
```

- [ ] **Step 7: 跑全 3 测**

```bash
cd compliance-agent/backend && python -m pytest tests/test_import_unit_regions_v214.py -v
```

Expected: 3 PASS

- [ ] **Step 8: Commit**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/backend/app/models/entities.py \
        compliance-agent/backend/app/scripts/import_unit_regions_v214.py \
        compliance-agent/backend/tests/test_import_unit_regions_v214.py
git commit -m "$(cat <<'EOF'
feat(v2.14): AuditUnit 加 region + 从 Excel import 脚本

- AuditUnit 加 region: String(32) default="" indexed
- import_unit_regions_v214.py: openpyxl 读 xlsx，code 优先 name fallback
  匹配写入 region；已有 region 跳过（幂等 + 保护人工修正）
- --dry-run/--apply 二选一互斥
- 3 pytest 覆盖：code 匹 / name fallback / 已有 region 跳过

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 修 export_routes 用 `unit.region` 替代正则

**Files:**
- Modify: `compliance-agent/backend/app/api/export_routes.py`（`_list_finalized_by_city` + `download_city_zip`）
- Modify: `compliance-agent/backend/tests/test_export_region.py`（`_create_finalized_task` helper 加 `region` 参数）

**Interfaces:**
- Consumes: `AuditUnit.region`（Task 1）
- Produces: 无新签名；行为改变但保持函数签名不变

- [ ] **Step 1: 修改 export_routes.py 用 unit.region**

打开 `compliance-agent/backend/app/api/export_routes.py`。找到 `_list_finalized_by_city`（约 line 47-65），当前是：

```python
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
        ...
```

改为：

```python
def _list_finalized_by_city(db: Session) -> list[dict]:
    """按市聚合 finalized 任务（v2.14: 直接用 unit.region）。"""
    rows = (
        db.query(AuditTask, AuditUnit.name, AuditUnit.region)
        .join(AuditUnit, AuditTask.unit_id == AuditUnit.id)
        .filter(AuditTask.status == "finalized")
        .all()
    )
    grouped: dict[str, dict] = defaultdict(
        lambda: {"task_count": 0, "unit_ids": set(), "unknown": False}
    )
    for task, unit_name, region in rows:
        key = region if region else UNCLASSIFIED
        grouped[key]["task_count"] += 1
        grouped[key]["unit_ids"].add(task.unit_id)
        if not region:
            grouped[key]["unknown"] = True
    return [
        {"city": k, "task_count": v["task_count"],
         "unit_count": len(v["unit_ids"]), "unknown": v["unknown"]}
        for k, v in sorted(
            grouped.items(),
            key=lambda kv: (kv[1]["unknown"], -kv[1]["task_count"]),
        )
    ]
```

- [ ] **Step 2: 同样改 download_city_zip**

在同一文件找到 `download_city_zip`（约 line 90+），有段：

```python
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
```

改为：

```python
all_rows = (
    db.query(AuditTask, AuditUnit.name, AuditUnit.region)
    .join(AuditUnit, AuditTask.unit_id == AuditUnit.id)
    .filter(AuditTask.status == "finalized")
    .all()
)
match_rows = []
for task, unit_name, region in all_rows:
    actual_city = region if region else UNCLASSIFIED
    if actual_city == city:
        # v2.14: 不再有区县概念，district 传 None（zip 内会归 "_未分类"/ 子目录）
        match_rows.append((task, unit_name, None))
```

- [ ] **Step 3: 删除未使用的 parse_region import**

在 `export_routes.py` 顶部删除：

```python
from app.services.region_parser import parse_region
```

（保留 `region_parser.py` 文件本身不删，历史兼容）

- [ ] **Step 4: 改测试 helper 加 region 参数**

打开 `compliance-agent/backend/tests/test_export_region.py`。找到 `_create_finalized_task`。当前 signature 大概是：

```python
def _create_finalized_task(client, headers, unit_name, task_name):
    r = client.post("/api/units",
                    json={"name": unit_name, "code": "R"},
                    headers=headers)
    ...
```

改为让 helper 直接 seed region（因 v2.14 后不再靠 name 正则）：

```python
def _create_finalized_task(client, headers, unit_name, task_name,
                          region="达州市"):
    """v2.14: 加 region 参数（v2.11 靠 name 正则的时代结束）。"""
    r = client.post("/api/units",
                    json={"name": unit_name, "code": "R"},
                    headers=headers)
    assert r.status_code == 200, r.text
    unit_id = r.json()["id"]

    # v2.14: 直接 SQL 设 region（API create 尚不支持 region 字段）
    from app.models import SessionLocal, AuditUnit
    with SessionLocal() as s:
        u = s.get(AuditUnit, unit_id)
        u.region = region
        s.commit()

    r = client.post("/api/tasks",
                    json={"unit_id": unit_id, "name": task_name,
                          "eval_year": 2025, "scope": "all"},
                    headers=headers)
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]

    from app.models import AuditTask, Worksheet
    with SessionLocal() as s:
        t = s.get(AuditTask, task_id)
        t.status = "finalized"
        ws = Worksheet(task_id=task_id, status="finalized")
        s.add(ws)
        s.commit()
    return task_id
```

现有测试如 `test_download_city_zip_structure` 用的默认参数是 `unit_name="四川省达州市达川区试点单位_Z1"`，靠正则解析得"达州市"。改后传 `region="达州市"` 显式指定。

**注意**：找现有测试里其它调用 `_create_finalized_task(...)` 的地方，如果测试断言"未分类"桶或特定市，可能需要相应传 region 参数。查看当前测试文件：

```bash
grep -n "_create_finalized_task" compliance-agent/backend/tests/test_export_region.py
```

按调用逐个检查：unit_name 里含中文市名的传对应 region；测"未分类"的传 `region=""`。

- [ ] **Step 5: 跑 export 测试确认通过**

```bash
cd compliance-agent/backend && python -m pytest tests/test_export_region.py -v
```

Expected: 全 PASS。若失败，看失败测试对应的 seed 是否传对了 region。

- [ ] **Step 6: 跑 region_parser 现有测试确认没坏**

（region_parser 文件本身还在，unit tests 仍应 pass）

```bash
cd compliance-agent/backend && python -m pytest tests/test_region_parser.py -v
```

Expected: 全 PASS（我们没改 region_parser.py）

- [ ] **Step 7: Commit**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/backend/app/api/export_routes.py \
        compliance-agent/backend/tests/test_export_region.py
git commit -m "$(cat <<'EOF'
feat(v2.14): export_routes 用 unit.region 替代 parse_region()

- _list_finalized_by_city + download_city_zip 直接读 AuditUnit.region
- 删掉 from app.services.region_parser import parse_region
- test_export_region helper _create_finalized_task 加 region 参数，
  显式指定该 unit 的 region（不再靠 name 正则）
- Zip 内目录 <市>/_未分类/单位.xlsx（v2.14 起不细分区县）
- region == "" 归 UNCLASSIFIED 桶保持向后兼容

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 新 dashboard 端点 `region_finding_stats` + 3 pytest

**Files:**
- Modify: `compliance-agent/backend/app/api/dashboard_routes.py`（加端点 + 相关 import）
- Modify: `compliance-agent/backend/tests/test_dashboard_unit_stats.py`（加 3 pytest）

**Interfaces:**
- Consumes: `AuditUnit.region`（Task 1）; `Finding, AuditTask, AuditUnit`; `_VALID_FINDING_TYPES` from `app.services.audit_service`
- Produces: `GET /api/dashboard/region-finding-stats` → dict `{finding_types: list[str], regions: list[{region, unit_count, counts, total}]}`

- [ ] **Step 1: 写首条失败测试**

在 `compliance-agent/backend/tests/test_dashboard_unit_stats.py` 末尾追加：

```python
def test_region_finding_stats_structure(auth_headers):
    """/region-finding-stats 返 dict 含 finding_types + regions 两键。"""
    from app.main import app
    with TestClient(app) as client:
        r = client.get(
            "/api/dashboard/region-finding-stats",
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert "finding_types" in data
        assert "regions" in data
        assert isinstance(data["finding_types"], list)
        assert isinstance(data["regions"], list)
        # finding_types 至少 6 个（v1.6 _VALID_FINDING_TYPES 定义）
        assert len(data["finding_types"]) >= 6
        # 每 region 结构合法
        for r_ in data["regions"]:
            assert set(r_.keys()) >= {"region", "unit_count", "counts", "total"}
```

- [ ] **Step 2: 跑 —— verify RED**

```bash
cd compliance-agent/backend && python -m pytest tests/test_dashboard_unit_stats.py::test_region_finding_stats_structure -v
```

Expected: FAIL `404 Not Found`

- [ ] **Step 3: 在 dashboard_routes.py 加端点**

打开 `compliance-agent/backend/app/api/dashboard_routes.py`。顶部 import 区加：

```python
from app.models import Finding
from app.services.audit_service import _VALID_FINDING_TYPES
```

在文件末尾（现有 `unit_stats_detail` 之后）加：

```python
@dashboard_router.get("/region-finding-stats")
def region_finding_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """每地区 × 每 finding_type 的 count 矩阵 + 每地区单位数。

    返回：
    {
      "finding_types": ["真实性问题", ...],
      "regions": [
        {"region": "成都市", "unit_count": 403, "counts": {...}, "total": N},
        ...
      ]
    }
    region == "" 的单位完全排除。按 unit_count 降序排。
    """
    # 1. 每地区单位数
    unit_rows = (
        db.query(AuditUnit.region, func.count(AuditUnit.id))
        .filter(AuditUnit.region != "")
        .group_by(AuditUnit.region)
        .all()
    )
    unit_counts = {r: int(n) for r, n in unit_rows}

    # 2. 每地区 × finding_type finding 数
    finding_rows = (
        db.query(
            AuditUnit.region,
            Finding.finding_type,
            func.count(Finding.id),
        )
        .join(AuditTask, AuditTask.unit_id == AuditUnit.id)
        .join(Finding, Finding.task_id == AuditTask.id)
        .filter(AuditUnit.region != "")
        .filter(Finding.finding_type.in_(_VALID_FINDING_TYPES))
        .group_by(AuditUnit.region, Finding.finding_type)
        .all()
    )
    per_region: dict[str, dict[str, int]] = {}
    for region, ftype, n in finding_rows:
        per_region.setdefault(region, {})[ftype] = int(n)

    regions_out = []
    for region, unit_count in unit_counts.items():
        counts = per_region.get(region, {})
        # 补齐所有 6 维（缺的填 0）
        counts_full = {ft: counts.get(ft, 0) for ft in _VALID_FINDING_TYPES}
        total = sum(counts_full.values())
        regions_out.append({
            "region": region,
            "unit_count": unit_count,
            "counts": counts_full,
            "total": total,
        })
    # 按 unit_count 降序（大市在前）
    regions_out.sort(key=lambda x: -x["unit_count"])

    return {
        "finding_types": list(_VALID_FINDING_TYPES),
        "regions": regions_out,
    }
```

- [ ] **Step 4: 跑首测 —— verify GREEN**

```bash
cd compliance-agent/backend && python -m pytest tests/test_dashboard_unit_stats.py::test_region_finding_stats_structure -v
```

Expected: PASS

- [ ] **Step 5: 加剩余 2 测**

追加到 `test_dashboard_unit_stats.py`：

```python
def test_region_finding_stats_counts_findings_correctly(auth_headers):
    """seed 一个 unit+region+task+finding → 该 region.counts 对应 type=1。"""
    from app.main import app
    from app.models import (
        SessionLocal, AuditUnit, AuditTask, Finding,
    )
    with TestClient(app) as client:
        # 建 unit + region
        r = client.post("/api/units",
                        json={"name": "v214-rfs-1", "code": "RFS1"},
                        headers=auth_headers)
        assert r.status_code == 200
        uid = r.json()["id"]
        with SessionLocal() as s:
            u = s.get(AuditUnit, uid)
            u.region = "v214-region-x"
            s.commit()

        # 建 task
        r = client.post("/api/tasks",
                        json={"unit_id": uid, "name": "T_RFS1",
                              "eval_year": 2025, "scope": "all"},
                        headers=auth_headers)
        assert r.status_code == 200
        tid = r.json()["id"]

        # 直接 seed finding
        with SessionLocal() as s:
            f = Finding(task_id=tid, indicator_id=None,
                        finding_type="真实性问题", severity="中",
                        description="test finding")
            s.add(f); s.commit()

        r = client.get(
            "/api/dashboard/region-finding-stats", headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        region_entry = next(
            (r for r in data["regions"] if r["region"] == "v214-region-x"),
            None,
        )
        assert region_entry is not None
        assert region_entry["unit_count"] == 1
        assert region_entry["counts"]["真实性问题"] >= 1
        assert region_entry["total"] >= 1


def test_region_finding_stats_excludes_empty_region_units(auth_headers):
    """region 为空的 unit 不出现在返回列表。"""
    from app.main import app
    with TestClient(app) as client:
        # 建一个 region 为空的 unit
        r = client.post("/api/units",
                        json={"name": "v214-rfs-empty", "code": "EMPTY"},
                        headers=auth_headers)
        assert r.status_code == 200

        r = client.get(
            "/api/dashboard/region-finding-stats", headers=auth_headers,
        )
        assert r.status_code == 200
        regions = r.json()["regions"]
        # 空 region 不应出现（因为 region == "" 被 filter）
        assert not any(x["region"] == "" for x in regions)
```

- [ ] **Step 6: 跑 3 测（新的）+ 全 dashboard 测试**

```bash
cd compliance-agent/backend && python -m pytest tests/test_dashboard_unit_stats.py -v
```

Expected: 全 PASS（原有 6 + 新的 3 = 9）

- [ ] **Step 7: Commit**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/backend/app/api/dashboard_routes.py \
        compliance-agent/backend/tests/test_dashboard_unit_stats.py
git commit -m "$(cat <<'EOF'
feat(v2.14): dashboard 加 region_finding_stats 端点

- GET /api/dashboard/region-finding-stats 聚合 (region, finding_type)
  返 {finding_types, regions: [{region, unit_count, counts, total}]}
- 2 条 SQL：per-region unit_count + per-region×finding_type finding_count
- region == "" 完全排除；按 unit_count 降序排
- 6 维度用 _VALID_FINDING_TYPES 常量（v1.6）
- 3 pytest 覆盖：结构 / counts 准确 / 排除空 region

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 前端工作台加 card + cache-buster

**Files:**
- Modify: `compliance-agent/frontend/index.html`（加 card + `?v=2.13` → `?v=2.14`）
- Modify: `compliance-agent/frontend/app.js`（`renderRegionFindingStatsCard` + `loadDashboard` 末尾调用）

**Interfaces:**
- Consumes:
  - `api(path)` helper（`/api` 前缀 + Bearer token）
  - `esc(s)` helper
  - 后端 `/api/dashboard/region-finding-stats`（Task 3）
- Produces:
  - JS 函数 `renderRegionFindingStatsCard()` — 无参
  - DOM id：`dash-region-finding-stats`

- [ ] **Step 1: index.html 加 card**

打开 `compliance-agent/frontend/index.html`。定位到 v2.13 "单位核查进度总览" card（含 `id="dash-unit-progress"`）。在它**关闭 `</div>` 之后**、下一个 v2.11 "批量导出" card `<div class="card mt-6 fade-in fade-in-4">` **之前**插入：

```html

        <!-- v2.14: 地区 × 问题维度分布 -->
        <div class="card mt-6 fade-in fade-in-4">
          <div class="section-title">地区 × 问题维度分布</div>
          <div class="text-sm text-muted mb-3">
            每地区的 finding 按 6 维分类；百分比 = 该地区该维度 / 该地区总 finding × 100%。
          </div>
          <div id="dash-region-finding-stats" class="text-sm">
            <div class="empty-state" style="padding:16px">加载中…</div>
          </div>
        </div>
```

- [ ] **Step 2: bump cache-buster**

```bash
grep -n "?v=2\." compliance-agent/frontend/index.html
```

用 Edit `replace_all=true` 把 `?v=2.13` → `?v=2.14`。

- [ ] **Step 3: app.js 加 renderRegionFindingStatsCard**

打开 `compliance-agent/frontend/app.js`。定位到 `renderUnitProgressCard`（v2.13 加的）**之后**，加：

```javascript

// v2.14: 地区 × 问题维度分布 card
async function renderRegionFindingStatsCard() {
  const box = document.getElementById("dash-region-finding-stats");
  if (!box) return;
  try {
    const data = await api("/dashboard/region-finding-stats");
    const ftypes = data.finding_types;
    const regions = data.regions;
    if (!regions.length) {
      box.innerHTML = `<div class="empty-state" style="padding:16px">暂无地区数据（需先 import unit region）</div>`;
      return;
    }
    box.innerHTML = `
      <div style="overflow-x:auto">
        <table class="table table-compact">
          <thead>
            <tr>
              <th style="width:100px">地区</th>
              <th style="width:80px">单位数</th>
              <th style="width:80px">总findings</th>
              ${ftypes.map(ft => `<th>${esc(ft)}</th>`).join("")}
            </tr>
          </thead>
          <tbody>
            ${regions.map(r => `
              <tr>
                <td><strong>${esc(r.region)}</strong></td>
                <td>${r.unit_count}</td>
                <td>${r.total}</td>
                ${ftypes.map(ft => {
                  const n = r.counts[ft] || 0;
                  const pct = r.total > 0 ? (n / r.total * 100) : 0;
                  return `<td>
                    <div style="font-weight:600">${n}</div>
                    <div style="height:4px;background:#eee;border-radius:2px;margin-top:2px">
                      <div style="height:100%;width:${pct.toFixed(1)}%;background:#0071e3;border-radius:2px"></div>
                    </div>
                    <div style="font-size:11px;color:#6e6e73;margin-top:1px">${pct.toFixed(1)}%</div>
                  </td>`;
                }).join("")}
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;
  } catch (e) {
    box.innerHTML = `<div class="empty-state" style="padding:16px;color:#b8262b">加载失败：${esc(e.message)}</div>`;
  }
}
```

- [ ] **Step 4: 在 loadDashboard 末尾调用**

定位到 `loadDashboard()` 函数末尾（找 `renderUnitProgressCard();` 那行）。在它**之后**加：

```javascript
    // v2.14: 地区 × 问题维度分布
    renderRegionFindingStatsCard();
```

- [ ] **Step 5: 语法 + grep 验证**

```bash
cd compliance-agent/frontend && node --check app.js && echo "SYNTAX OK"
grep -c "renderRegionFindingStatsCard" app.js
grep -c "dash-region-finding-stats" index.html
grep -c "?v=2.14" index.html
```

Expected:
- SYNTAX OK
- `renderRegionFindingStatsCard`: `>=2`（定义 + 调用）
- `dash-region-finding-stats`: `1`
- `?v=2.14`: `3`

- [ ] **Step 6: Commit**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/frontend/index.html compliance-agent/frontend/app.js
git commit -m "$(cat <<'EOF'
feat(v2.14): 工作台"地区 × 问题维度分布"card

- index.html: 加 card 放"单位核查进度总览"之后、"批量导出"之前
- app.js: renderRegionFindingStatsCard 请求 region-finding-stats 端点，
  渲染大表格 22 行 × 8 列（地区 + 单位数 + 总findings + 6 维度）
- 每格 3 层：数字 + mini bar（横条按百分比宽度）+ 百分比文本
- 分母 = 该地区总 findings；6 维相加 = 100%
- cache-buster 2.13 → 2.14

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: 部署 + Excel 上传 + Migration + Import + 浏览器 checklist + README

**Files:**
- 无代码改动，部署 Task 1-4 产出的文件 + Excel
- Modify: `compliance-agent/README.md`（v2.14 更新日志）

**Interfaces:** 无

- [ ] **Step 1: Push origin/main**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git push origin main 2>&1 | tail -3
```

Expected: `main -> main` 推送成功。若网络失败，稍后重试。

- [ ] **Step 2: Workbench 上传 6 个文件到 ECS**

后端 4 个：
- `compliance-agent/backend/app/models/entities.py` → 覆盖
- `compliance-agent/backend/app/scripts/import_unit_regions_v214.py` → 新
- `compliance-agent/backend/app/api/export_routes.py` → 覆盖
- `compliance-agent/backend/app/api/dashboard_routes.py` → 覆盖

前端 2 个：
- `compliance-agent/frontend/index.html` → 覆盖
- `compliance-agent/frontend/app.js` → 覆盖

Excel（放宿主机 bind mount 位置）：
- 本地 `/Users/lizhishaoniange/Desktop/评价单位5267（带地区）.xlsx` → ECS `/opt/audit/compliance-agent/backend/data/units_regions_v214.xlsx`

- [ ] **Step 3: 备份 audit_units 表**

用户在 ECS：

```bash
cd /opt/audit/compliance-agent
docker compose exec -T postgres pg_dump -U compliance -d compliance -t audit_units \
    > /opt/audit/backup_v2.14_units_before_$(date +%Y%m%d_%H%M%S).sql
ls -lh /opt/audit/backup_v2.14_units_before_*.sql | tail -1
```

Expected: 输出文件 > 500KB（5000+ unit 数据）。

- [ ] **Step 4: 加 region 列 + 索引（一次 ALTER TABLE）**

```bash
docker compose exec -T postgres psql -U compliance -d compliance -c "ALTER TABLE audit_units ADD COLUMN IF NOT EXISTS region VARCHAR(32) NOT NULL DEFAULT ''; CREATE INDEX IF NOT EXISTS ix_audit_units_region ON audit_units(region);"
```

Expected: `ALTER TABLE` + `CREATE INDEX` 无报错。

验证：
```bash
docker compose exec -T postgres psql -U compliance -d compliance -c "\d audit_units" | grep region
```

Expected: 看到 `region character varying(32) ...`

- [ ] **Step 5: cp 4 后端文件到 3 容器 + restart**

```bash
cd /opt/audit/compliance-agent
for c in backend worker enrich_worker; do
  docker compose cp backend/app/models/entities.py $c:/app/app/models/entities.py
  docker compose cp backend/app/scripts/import_unit_regions_v214.py $c:/app/app/scripts/import_unit_regions_v214.py
  docker compose cp backend/app/api/export_routes.py $c:/app/app/api/export_routes.py
  docker compose cp backend/app/api/dashboard_routes.py $c:/app/app/api/dashboard_routes.py
done
docker compose restart backend worker enrich_worker
docker compose logs backend --tail=15 | grep -Ei "error|startup complete"
```

Expected: `Application startup complete.` 无 ImportError。

- [ ] **Step 6: Import dry-run 看统计**

```bash
docker compose exec -T backend python -m app.scripts.import_unit_regions_v214 \
    --xlsx /app/data/units_regions_v214.xlsx --dry-run
```

Expected 输出类似：
```
Excel 数据行（含 region 空）: 5264
统计:
  excel_rows: 5264
  matched_by_code: 5100
  matched_by_name: 100
  not_matched: 64
  already_had_region: 0
  updated: 5200
(dry-run) 未写入 DB
```

**看 not_matched 数量**：如果几十~上百可接受（Excel 里可能有系统里未建的单位）；如果 3000+ 说明匹配策略有问题，停下告诉我。

- [ ] **Step 7: Import apply 真写入**

```bash
docker compose exec -T backend python -m app.scripts.import_unit_regions_v214 \
    --xlsx /app/data/units_regions_v214.xlsx --apply
```

Expected: 输出 updated N 条，无 error。

验证：
```bash
docker compose exec -T postgres psql -U compliance -d compliance -c "SELECT region, COUNT(*) FROM audit_units WHERE region != '' GROUP BY region ORDER BY COUNT(*) DESC LIMIT 25;"
```

Expected: 22 行左右，"省级"最多 + 21 市/州分布跟 Excel 一致。

- [ ] **Step 8: 浏览器 checklist**

`http://8.163.75.9/` → Cmd+Shift+R 硬刷（F12 Network 看 `app.js?v=2.14`）→ 工作台页。

- [ ] "批量导出已定稿工作底稿" card 里 "未分类"桶显著缩减（从 1 → 0 或 << 1）
- [ ] 表格里显式出现"成都市 / 达州市 / …"等标准地区名（不再是从 name 反推的形如"XX市"）
- [ ] "单位核查进度总览" card 正常显示（v2.13 不受影响）
- [ ] **新 card "地区 × 问题维度分布"** 出现在"单位核查进度总览"和"批量导出"之间
- [ ] 新 card 里表格有 22 行左右（"省级" + 21 市/州）
- [ ] 每格显示 数字 + 横条 bar + 百分比
- [ ] 6 维百分比相加 ≈ 100%（各行独立）
- [ ] 表格按单位数降序（省级 870 或成都 403 在前）
- [ ] 401 时 card 显示"加载失败"（不 crash）

**任意失败** → 停下报现象。

- [ ] **Step 9: 更新 README**

Edit `compliance-agent/README.md`。找到"## 更新日志（部分）"段，在 v2.13 之前插入：

```markdown
- **v2.14（2026-07-22）**：AuditUnit 加 `region` 字段并从 Excel(5264 单位带地区) import；v2.11 export 改用 `unit.region` 替代正则解析（"未分类"桶显著缩减）；工作台加"地区 × 问题维度分布" card，22 行 × 8 列大表格（地区 + 单位数 + 总findings + 6 维数字/mini bar/百分比）。新端点 `/api/dashboard/region-finding-stats`。详见 `docs/superpowers/plans/2026-07-22-unit-region-and-region-finding-chart.md`
```

- [ ] **Step 10: Commit + push README**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/README.md
git commit -m "$(cat <<'EOF'
docs(v2.14): README 加更新日志

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push origin main 2>&1 | tail -3
```

---

## Self-Review

**Spec coverage:**
- ✅ Sub-A/A1 `AuditUnit.region` 字段 + index → Task 1 Step 1
- ✅ Sub-A/A2 Import 脚本 + code/name 匹配 + 幂等跳过 → Task 1 Step 4-6
- ✅ Sub-A/A3 export_routes 用 unit.region → Task 2 Step 1-3
- ✅ Sub-A/A4 pg_dump 备份 → Task 5 Step 3
- ✅ Sub-B/B1 后端 region_finding_stats 端点 → Task 3 Step 3
- ✅ Sub-B/B2 前端 card + mini bar 表格 → Task 4 Step 1+3
- ✅ Sub-B/B3 cache-buster 2.13→2.14 → Task 4 Step 2
- ✅ Migration ALTER TABLE + CREATE INDEX → Task 5 Step 4
- ✅ Dry-run 校准 → Task 5 Step 6
- ✅ Apply → Task 5 Step 7
- ✅ 浏览器 checklist → Task 5 Step 8
- ✅ README → Task 5 Step 9

**Placeholder scan:**
- 无 TODO/TBD
- 所有代码块完整
- 所有命令带 Expected

**Type consistency:**
- `AuditUnit.region: Mapped[str]` String(32) 一致
- `_load_excel_rows(xlsx: str) -> list[dict[str, str]]` 一致
- `_match_and_update(db, excel_rows, dry_run: bool) -> dict` 返 6 键 stats 一致
- CLI flags `--xlsx / --dry-run / --apply` 一致
- 后端 return dict 键 `finding_types / regions / region / unit_count / counts / total` 前后一致
- 前端 fetch key 名跟后端一致
- `_create_finalized_task(client, headers, unit_name, task_name, region="达州市")` 一致

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-22-unit-region-and-region-finding-chart.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — Task 1/2/3/4 派 fresh subagent + review；Task 5 部署 + checklist 交给用户手动

**2. Inline Execution** — 本会话直接跑 Task 1-4，Task 5 hand-off 给用户

Which approach?
