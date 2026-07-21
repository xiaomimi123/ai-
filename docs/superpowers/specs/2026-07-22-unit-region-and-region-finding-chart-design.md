# 单位地区落库 + 地区×问题维度可视化（v2.14）

**日期**：2026-07-22
**范围**：backend migration + import 脚本 + 修 export_routes + 新可视化端点 + frontend 工作台加 card
**动机**：客户提供 5264 单位带标准地区分类（22 类：省级 + 21 市/州）的 Excel。当前 v2.11 从 `unit.name` 正则解析（"巴中生态环境监测中心站"这类简写归"未分类"）不准。同时客户想看各市 finding 6 维分布可视化辅助决策。

## 目标

**Sub-A：地区字段落库**
- `AuditUnit` 加 `region` 字段（String(32)），加索引
- import 脚本读 Excel（`/Users/lizhishaoniange/Desktop/评价单位5267(带地区）.xlsx`）→ 先 code 匹再 name 匹 → 写 `unit.region`
- v2.11 `export_routes.py` 改用 `unit.region` 替代 `parse_region(unit.name)`，"未分类"桶只剩真实未匹配上的
- 一次性 pg_dump audit_units 备份

**Sub-B：地区×问题维度可视化**
- 后端新端点 `/api/dashboard/region-finding-stats` 聚合 (region, finding_type) → 返 22 × 6 矩阵
- 前端工作台新 card：22 行 × 8 列表格（地区 + 单位数 + 6 维度"个数 (%)"，每格含 mini bar）
- 分母 = 该市所有 findings 之和；6 维相加 = 100%

## 非目标（YAGNI）

- 不做 finding_type 白名单可配置（用现有 `_VALID_FINDING_TYPES` 6 项定义）
- 不做 review_status 过滤（含 pending / confirmed / ignored / adjusted 全部）
- 不引 Chart.js（纯 HTML+CSS mini bar 够看）
- 不做后台"单位管理"页 region 手工编辑（先 import 覆盖，后续需要再加编辑 UI）
- 不做地区下钻到具体单位（可视化只到"市"级；想看单位用 v2.13 unit-progress card）
- 不做全库自动 rebind（region 只影响导出分组和统计，不影响 finding 生成或指标绑定）
- 不做二级区县字段（本次只到市/州级别，Excel 也只有一级 region 列）

## 数据分析

**Excel `评价单位5267(带地区）.xlsx`**：5264 行 × 3 列 (`代码 / 单位名称 / 地区`)。22 个地区值分布：
- 省级 (870)
- 成都市(403) / 达州市(308) / 甘孜州(243) / 乐山市(238) / 内江市(234) / 南充市(231) / 绵阳市(230) / 凉山州(214) / 自贡市(207) / 广元市(204) / 德阳市(192) / 阿坝州(191) / 巴中市(188) / 遂宁市(187) / 攀枝花市(184) / 广安市(177) / 泸州市(176) / 宜宾市(161) / 眉山市(159) / 雅安市(134) / 资阳市(133)

**Finding 6 维**（`audit_service._VALID_FINDING_TYPES`）：`真实性问题 / 完整性问题 / 合规性问题 / 重复性问题 / 匹配性问题 / 形式性`

## 设计

### Sub-A：region 字段 + import 脚本 + 修 export

#### A1. Migration `AuditUnit.region`

`compliance-agent/backend/app/models/entities.py`（第 162 行 `class AuditUnit`）加：

```python
class AuditUnit(Base):
    ...
    level: Mapped[str] = mapped_column(String(32), default="单位")
    region: Mapped[str] = mapped_column(String(32), default="", index=True)  # v2.14
    description: Mapped[str] = mapped_column(Text, default="")
    ...
```

`ALTER TABLE` SQL 手动执行（跟本项目其它 model 演进一致，不用 alembic）：

```sql
ALTER TABLE audit_units ADD COLUMN IF NOT EXISTS region VARCHAR(32) NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS ix_audit_units_region ON audit_units(region);
```

生产直接跑一次；测试 SQLite 自动 `Base.metadata.create_all()` 建。

#### A2. Import 脚本 `app/scripts/import_unit_regions_v214.py`

```python
"""v2.14: 从 Excel 导入单位地区字段。

用法：
    docker compose exec -T backend python -m app.scripts.import_unit_regions_v214 --xlsx /app/data/units.xlsx --dry-run
    docker compose exec -T backend python -m app.scripts.import_unit_regions_v214 --xlsx /app/data/units.xlsx --apply
"""
from __future__ import annotations
import argparse
from openpyxl import load_workbook
from app.models import SessionLocal, AuditUnit


def _load_excel_rows(xlsx_path: str) -> list[dict]:
    """读 Excel 返 [{code, name, region}]（跳过表头 + 空行）。"""
    wb = load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.active
    rows = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        if r[0] is None and r[1] is None:
            continue
        rows.append({
            "code": str(r[0]).strip() if r[0] else "",
            "name": str(r[1]).strip() if r[1] else "",
            "region": str(r[2]).strip() if r[2] else "",
        })
    return rows


def _match_and_update(db, excel_rows, dry_run: bool) -> dict:
    """按 code 优先、name fallback 匹配写 region；已有 region 跳过。返回统计。"""
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--xlsx", required=True, help="Excel 路径")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--dry-run", action="store_true")
    grp.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    rows = _load_excel_rows(args.xlsx)
    print(f"Excel 行数（含 region 空）: {len(rows)}")

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

#### A3. 修 `export_routes.py` 用 `unit.region`

`_list_finalized_by_city()` 和 `download_city_zip()` 里都用 `unit.region` 替代 `parse_region(unit_name)`：

```python
def _list_finalized_by_city(db: Session) -> list[dict]:
    rows = (
        db.query(AuditTask, AuditUnit.name, AuditUnit.region)  # v2.14: 加 region
        .join(AuditUnit, AuditTask.unit_id == AuditUnit.id)
        .filter(AuditTask.status == "finalized")
        .all()
    )
    grouped: dict[str, dict] = defaultdict(...)
    for task, unit_name, region in rows:
        key = region or UNCLASSIFIED  # v2.14: 直接用 region 字段
        ...
```

类似改 `download_city_zip`。删掉 `from app.services.region_parser import parse_region` import（保留 `region_parser.py` 文件本身供旧代码兼容或删除，按需）。

**兼容性**：如果 `unit.region == ""`（未 import 的），仍归"未分类"桶。

#### A4. 部署备份

跑 import 前 pg_dump audit_units 一次：

```bash
docker compose exec -T postgres pg_dump -U compliance -d compliance -t audit_units \
    > /opt/audit/backup_v2.14_units_before_$(date +%Y%m%d_%H%M%S).sql
```

### Sub-B：地区 × Finding 维度可视化

#### B1. 后端端点 `/api/dashboard/region-finding-stats`

在 v2.13 `dashboard_routes.py` 里加：

```python
from app.models import Finding
from app.services.audit_service import _VALID_FINDING_TYPES


@dashboard_router.get("/region-finding-stats")
def region_finding_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """每地区 × 每 finding_type 的 count 矩阵 + 每地区单位数。

    返回结构：
    {
      "finding_types": ["真实性问题", "完整性问题", ...],
      "regions": [
        {
          "region": "成都市",
          "unit_count": 403,
          "counts": {"真实性问题": 120, "完整性问题": 80, ...},
          "total": 300  # sum of counts
        },
        ...
      ]
    }
    """
    # 1. 每地区单位数
    unit_rows = (
        db.query(AuditUnit.region, func.count(AuditUnit.id))
        .filter(AuditUnit.region != "")
        .group_by(AuditUnit.region)
        .all()
    )
    unit_counts = {r: n for r, n in unit_rows}

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
    # 按 unit_count desc 排（大市在前）
    regions_out.sort(key=lambda x: -x["unit_count"])

    return {
        "finding_types": list(_VALID_FINDING_TYPES),
        "regions": regions_out,
    }
```

**性能**：2 条 SQL；第 2 条含 2 层 join + GROUP BY (region, finding_type)，几十万 findings + 有 `unit_id/task_id` 索引 + 加 `region` 索引后 <1s 可期望。若慢加 `finding.finding_type` 索引。

#### B2. 前端工作台新 card

`index.html` 里，v2.13 "单位核查进度总览" card 之后、"批量导出" card 之前：

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

`app.js` 加 `renderRegionFindingStatsCard()`：

```javascript
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

在 `loadDashboard()` 末尾（跟 `renderUnitProgressCard();` 并列）调 `renderRegionFindingStatsCard();`。

#### B3. cache-buster

`?v=2.13` → `?v=2.14`（3 处）。

## 涉及文件

| 文件 | 变更 | 状态 |
|---|---|---|
| `backend/app/models/entities.py` | AuditUnit 加 `region` 字段（3 行） | 修改 |
| `backend/app/scripts/import_unit_regions_v214.py` | 新建 —— Excel import 脚本 | 新建 |
| `backend/tests/test_import_unit_regions_v214.py` | 3 pytest：code 匹 / name fallback / 已有 region 跳过 | 新建 |
| `backend/app/api/export_routes.py` | `_list_finalized_by_city` + `download_city_zip` 用 `unit.region` 替代 `parse_region()` | 修改 |
| `backend/tests/test_export_region.py` | 更新 seed helper 加 `region` 字段 + 断言用 region 值 | 修改 |
| `backend/app/api/dashboard_routes.py` | 加 `region_finding_stats` 端点 | 修改 |
| `backend/tests/test_dashboard_unit_stats.py` | 加 3 pytest：region_finding_stats 结构 / counts 正确 / 空地区排除 | 修改 |
| `frontend/index.html` | 加 card + `?v=2.13` → `?v=2.14` | 修改 |
| `frontend/app.js` | `renderRegionFindingStatsCard` + loadDashboard 调用 | 修改 |
| `README.md` | v2.14 更新日志 | 修改 |

## 部署顺序

1. 本地 code + tests 通过
2. push origin
3. Workbench 上传 Excel 到 ECS `/opt/audit/compliance-agent/backend/data/units_regions_v214.xlsx`
4. Workbench 上传所有改动文件
5. **备份 pg_dump audit_units 表**
6. ssh ECS 上跑：
   ```bash
   cd /opt/audit/compliance-agent
   # 后端文件 cp 到 3 容器
   for c in backend worker enrich_worker; do
     docker compose cp backend/app/models/entities.py $c:/app/app/models/entities.py
     docker compose cp backend/app/scripts/import_unit_regions_v214.py $c:/app/app/scripts/import_unit_regions_v214.py
     docker compose cp backend/app/api/export_routes.py $c:/app/app/api/export_routes.py
     docker compose cp backend/app/api/dashboard_routes.py $c:/app/app/api/dashboard_routes.py
   done
   docker compose cp backend/data/units_regions_v214.xlsx backend:/app/data/units_regions_v214.xlsx
   # DB migration（一次）
   docker compose exec -T postgres psql -U compliance -d compliance -c "ALTER TABLE audit_units ADD COLUMN IF NOT EXISTS region VARCHAR(32) NOT NULL DEFAULT ''; CREATE INDEX IF NOT EXISTS ix_audit_units_region ON audit_units(region);"
   # restart
   docker compose restart backend worker enrich_worker
   # dry-run import 看统计
   docker compose exec -T backend python -m app.scripts.import_unit_regions_v214 --xlsx /app/data/units_regions_v214.xlsx --dry-run
   # 确认后 apply
   docker compose exec -T backend python -m app.scripts.import_unit_regions_v214 --xlsx /app/data/units_regions_v214.xlsx --apply
   ```
7. 前端 Workbench 传 index.html + app.js → 硬刷验证

## 手工验证 checklist

- [ ] Migration 跑完 `\d audit_units` 有 `region` 列
- [ ] Import dry-run 输出统计合理（matched_by_code + matched_by_name ≈ 5264）
- [ ] Import apply 后 `SELECT COUNT(*) FROM audit_units WHERE region != '';` 大约 5264
- [ ] 工作台"批量导出" card 里"未分类"桶显著缩减（从上次 1 → 0 或 << 1）
- [ ] 工作台"批量导出"card 里成都市 / 达州市等出现，任务数合理
- [ ] 工作台新 card "地区 × 问题维度分布"显示 22 行 × 8 列
- [ ] 每行 6 维度百分比相加 ≈ 100%
- [ ] mini bar 宽度按百分比渲染
- [ ] 前端硬刷加载 `?v=2.14`
- [ ] 401 时 card 显示"加载失败"

## 风险 & 缓解

| 风险 | 概率 | 缓解 |
|---|---|---|
| Migration 阻塞（audit_units 5000+ 行加索引锁表）| 低 | `CREATE INDEX IF NOT EXISTS` + 加 `CONCURRENTLY`（Postgres）；本次数据量不大 <1s 完成 |
| Excel 里 `代码` 有 unit 库里没有的 → not_matched | 中 | Import 输出 not_matched 计数，dry-run 先看，apply 后 warn 单位名可导出手工核对 |
| 已 import 的 region 后来被覆盖 | 低 | 脚本"已有 region 跳过"，重复跑安全 |
| Finding 表 GROUP BY 慢 | 中 | 加 `region` 索引后 <1s；若>3s 再加 `finding.finding_type` 索引 |
| 6 维数字看不清（字太小） | 低 | mini bar 用色块提示；数字保留 |
| 部分单位在 excel 里但库里没建 | 低 | Import 只更新已有 unit，不新增（未来需要再加 `--create-missing` flag） |

## 回滚

1. 前端 `git revert` + Workbench 重传老 index.html/app.js + F5
2. 后端 `git revert` + docker cp 老 3 py 文件 + restart
3. Region 字段回滚：`ALTER TABLE audit_units DROP COLUMN region;`（数据丢失，若需要保留可只 revert 前后端不 drop 列）
4. 数据完整回滚：`psql -f /opt/audit/backup_v2.14_units_before_<ts>.sql`（覆盖 audit_units）
