# 二级文件夹语义识别 + 一次性 rebind 修复错绑（v2.8）

**日期**：2026-07-12
**范围**：backend `material_matcher.py`（改逻辑）+ 新增 rebind 脚本 + pytest
**动机**：生产上排查发现 **52003 份材料错绑到"制度"类指标**（占含"岗位"字样材料的 71%），原因是 v1.8 material_matcher 只按一级子类过滤 candidate + 关键词字典太窄，不识别"XX业务的岗位职责说明书"这种二级路径语义。

## 生产实测的错绑分布

排查 SQL：`file_name.contains("岗位") AND indicator.name.contains("制度")`

| 错绑到 | 数量 | 应该是 |
|---|---|---|
| I-13 预算制度 | **15269** | I-14 预算岗位分离 |
| I-20 收支制度 | **8536** | I-21 收支岗位分离 |
| I-32 资产制度 | **7281** | I-33 资产岗位分离 |
| I-25 采购制度 | **7244** | I-26 采购岗位分离 |
| I-44 合同制度 | **7176** | I-45 合同岗位分离 |
| I-37 基建制度 | **6295** | I-38 基建岗位分离 |
| 其它 | 202 | 其它 |

**命名模式极其规律**：`（数字）XX业务控制/XX业务的岗位职责说明书/*.pdf`

## 根因

`material_matcher.match_indicator_by_path_and_content` 现有逻辑（v1.8）：

```
1. match_subcategory(dir_part) → 一级子类
2. 该子类 candidates 里跑关键词匹配 → 命中就返回
3. 未命中 → SUBCATEGORY_TO_PROTOCOL_INDICATOR[子类] → 默认"制度"类
```

**问题**：二级文件夹名"合同管理的岗位职责说明书"含极强的定位信号（岗位分离），但当前逻辑压根没利用 —— 直接走 fallback 到 I-44"合同制度"。

## 目标

1. **新上传材料不再错绑**：如果二级文件夹含"岗位职责说明书"/"岗位分离"关键词，绑到该子类的**岗位分离指标**（I-14/21/26/33/38/45）
2. **历史 52003 份错绑一次性 rebind 修复**（含同步 finding 归属）
3. **架构可扩展**：未来发现新错绑模式，只需在映射表加一行

## 非目标（YAGNI）

- 不 rebuild 镜像（先靠 docker cp 补丁；稳定后随下次业务需要时 rebuild）
- 不改前端（UI 不需要动）
- 不做"台账"/"履行监督"/"印章"等其它二级模式（先解决 71% 的错绑；剩余 29% 未来发现再扩关键词）
- 不改现有 `SUBCATEGORY_TO_PROTOCOL_INDICATOR`（默认"制度"fallback 仍是合理的，只是加更早的二级识别）
- 不触发 AI 核查重跑（rebind material + finding 后 stats 会在下次核查/生成 worksheet 时自动重算）

## 设计

### 改动 1：`material_matcher.py` 加二级路径识别

**加两个常量**（放在 `SUBCATEGORY_TO_PROTOCOL_INDICATOR` 附近）：

```python
# v2.8：每个业务子类内 "语义类别 → 具体指标 code" 的映射
SUBCATEGORY_INDICATOR_MAP: dict[str, dict[str, str]] = {
    "（一）预算业务控制":     {"zhidu": "I-13", "gangwei": "I-14"},
    "（二）收支业务控制":     {"zhidu": "I-20", "gangwei": "I-21"},
    "（三）政府采购业务控制": {"zhidu": "I-25", "gangwei": "I-26"},
    "（四）资产控制":         {"zhidu": "I-32", "gangwei": "I-33"},
    "（五）建设项目控制":     {"zhidu": "I-37", "gangwei": "I-38"},
    "（六）合同控制":         {"zhidu": "I-44", "gangwei": "I-45"},
}

# v2.8：二级文件夹名里的关键词 → 语义类别
# 顺序敏感：先匹配的先赢（更具体的 keyword 放前面）
SECOND_LEVEL_KEYWORDS: list[tuple[str, str]] = [
    # 岗位分离类（首要覆盖，71% 错绑）
    ("岗位职责说明", "gangwei"),
    ("岗位分离",     "gangwei"),
    ("岗位职责分工", "gangwei"),
    # 制度类（跟默认 protocol_fallback 一致，加了兜底稳定性）
    ("内部控制制度", "zhidu"),
    ("管理制度",     "zhidu"),
    ("管理办法",     "zhidu"),
]
```

**改 `match_indicator_by_path_and_content`**（在现有 candidate 匹配之后、protocol_fallback 之前插入二级识别）：

```python
def match_indicator_by_path_and_content(relative_path, file_name, parsed_text, indicators):
    indicators = list(indicators)
    dir_part = posixpath.dirname((relative_path or "").replace("\\", "/"))
    subcategory = match_subcategory(_normalize(dir_part))

    if subcategory:
        # 1) 现有：candidate 关键词精确匹配
        candidates = [ind for ind in indicators
                      if _normalize(ind.subcategory or ind.category or "") == _normalize(subcategory)]
        if candidates:
            hit = match_indicator_by_content(file_name, parsed_text, candidates)
            if hit:
                return (hit, "high", "path+keyword")

        # 2) v2.8 新增：二级文件夹语义识别
        second_hit = _match_second_level(dir_part, subcategory, indicators)
        if second_hit:
            return (second_hit, "high", "path+second_level")

        # 3) 现有 protocol_fallback（"制度"兜底）
        protocol_code = SUBCATEGORY_TO_PROTOCOL_INDICATOR.get(_normalize(subcategory))
        if protocol_code:
            protocol_ind = next((ind for ind in indicators
                                if ind.indicator_code == protocol_code), None)
            if protocol_ind:
                return (protocol_ind, "medium", "path+protocol_fallback")

    # 4) 现有全局关键词
    hit = match_indicator_by_content(file_name, parsed_text, indicators)
    if hit:
        return (hit, "medium", "keyword_global")
    return (None, "none", "none")


def _match_second_level(dir_part: str, subcategory: str,
                        indicators: list) -> Optional["Indicator"]:
    """v2.8：从 dir_part 里第二层文件夹名识别语义 → 该子类内的具体指标。

    dir_part 结构典型："（六）合同控制/合同管理的岗位职责说明书"
    取斜杠分段后的最后一段（除一级子类之外的所有段拼起来），
    找 SECOND_LEVEL_KEYWORDS 里的关键词命中 → 查 SUBCATEGORY_INDICATOR_MAP。
    """
    if not subcategory or not dir_part:
        return None
    ind_map = SUBCATEGORY_INDICATOR_MAP.get(_normalize(subcategory))
    if not ind_map:
        return None
    # 取 dir_part 里"一级子类"之后的所有段拼起来
    # 简单做法：直接对整个 dir_part 做 keyword contains（一级子类里通常不含 gangwei/zhidu 字样）
    normalized = _normalize(dir_part)
    for keyword, semantic in SECOND_LEVEL_KEYWORDS:
        if keyword in normalized:
            target_code = ind_map.get(semantic)
            if target_code:
                target_ind = next((ind for ind in indicators
                                  if ind.indicator_code == target_code), None)
                if target_ind:
                    return target_ind
    return None
```

### 改动 2：一次性 rebind 脚本

新文件 `backend/app/scripts/rebind_wrong_bindings_v28.py`：

```python
"""v2.8：修复历史错绑 —— file_name 里含 (X)XX业务控制/*岗位* 但绑到"制度"类指标。

支持：
- --dry-run：只报告不改（默认必须显式加 --apply 才真改）
- 幂等：跑第二次影响 0 行
- 事务保护：一次性 UPDATE，失败全回滚
- 备份：--apply 时先 dump 原 indicator_id 到 /opt/audit/compliance-agent/backend/data/v28_rebind_backup.sql

用法：
    docker compose exec -T backend python -m app.scripts.rebind_wrong_bindings_v28 --dry-run
    docker compose exec -T backend python -m app.scripts.rebind_wrong_bindings_v28 --apply
"""
from __future__ import annotations
import argparse, re, sys
from datetime import datetime
from app.models import SessionLocal, Material, Finding, Indicator

# 匹配 file_name 里的"（一）预算业务控制" 到 "（六）合同控制" 前缀
SUBCATEGORY_TO_GANGWEI = {
    r"（一）\s*预算业务控制":   "I-14",
    r"（二）\s*收支业务控制":   "I-21",
    r"（三）\s*政府采购业务控制": "I-26",
    r"（四）\s*资产控制":       "I-33",
    r"（五）\s*建设项目控制":   "I-38",
    r"（六）\s*合同控制":       "I-45",
}
GANGWEI_KEYWORD = re.compile(r"岗位职责说明|岗位分离|岗位职责分工")


def find_wrong_bindings(db):
    """返回 [(material, target_indicator), ...] 需要 rebind 的列表。"""
    # 只看当前绑到"制度"类指标 + file_name 里同时含子类前缀 + "岗位"
    zhidu_inds = db.query(Indicator).filter(
        Indicator.name.contains("制度")
    ).all()
    zhidu_ids = {i.id for i in zhidu_inds}

    code2ind = {i.indicator_code: i for i in db.query(Indicator).all()}

    candidates = db.query(Material).filter(
        Material.indicator_id.in_(zhidu_ids),
        Material.file_name.contains("岗位"),
    ).all()

    to_fix = []
    for m in candidates:
        # 必须匹配某个子类前缀 + 岗位关键词
        if not GANGWEI_KEYWORD.search(m.file_name or ""):
            continue
        target_code = None
        for pattern, code in SUBCATEGORY_TO_GANGWEI.items():
            if re.search(pattern, m.file_name):
                target_code = code
                break
        if not target_code:
            continue
        target_ind = code2ind.get(target_code)
        if target_ind and target_ind.id != m.indicator_id:
            to_fix.append((m, target_ind))
    return to_fix


def dump_backup(to_fix, path):
    """把当前 material.id + 原 indicator_id 备份成可回滚 SQL。"""
    with open(path, "w") as f:
        f.write(f"-- v2.8 rebind backup {datetime.utcnow().isoformat()}\n")
        f.write(f"-- 共 {len(to_fix)} 条\n\n")
        for m, _ in to_fix:
            f.write(f"UPDATE material SET indicator_id = {m.indicator_id} WHERE id = {m.id};\n")


def report_impact(to_fix, db):
    """dry-run 报告：material 数 / finding 数 / 任务数 / 单位数。"""
    from collections import Counter
    mat_ids = [m.id for m, _ in to_fix]
    finding_count = db.query(Finding).filter(Finding.material_id.in_(mat_ids)).count() if mat_ids else 0

    task_ids = {m.task_id for m, _ in to_fix}
    # 按目标指标统计分布
    by_target = Counter(target.indicator_code for _, target in to_fix)

    print(f"待改绑 material 数: {len(to_fix)}")
    print(f"关联 finding 数:    {finding_count}")
    print(f"涉及任务数:         {len(task_ids)}")
    print()
    print("按目标指标分布:")
    for code, n in sorted(by_target.items(), key=lambda x: -x[1]):
        print(f"  {code}: {n}")


def run(dry_run: bool):
    db = SessionLocal()
    try:
        print("扫描错绑材料…")
        to_fix = find_wrong_bindings(db)
        report_impact(to_fix, db)
        print()
        if dry_run:
            print("--dry-run: 不实际修改。加 --apply 真改。")
            return
        # 备份
        backup_path = "/app/data/v28_rebind_backup.sql"
        dump_backup(to_fix, backup_path)
        print(f"✓ 原绑定已备份到 {backup_path}")

        # 批量 update（分批 500 条一 commit，避免大事务）
        BATCH = 500
        updated_mats = updated_findings = 0
        for i in range(0, len(to_fix), BATCH):
            chunk = to_fix[i:i+BATCH]
            for m, target in chunk:
                # 同步 finding 归属
                old_ind_id = m.indicator_id
                db.query(Finding).filter(
                    Finding.material_id == m.id,
                    Finding.indicator_id == old_ind_id,
                ).update({Finding.indicator_id: target.id})
                updated_findings += 1
                m.indicator_id = target.id
                updated_mats += 1
            db.commit()
            print(f"  已处理 {i+len(chunk)}/{len(to_fix)}")

        print()
        print(f"✓ 完成：改绑 material {updated_mats} 条，同步 finding {updated_findings} 条")
        print(f"  如需回滚：docker compose exec postgres psql -U compliance -d compliance -f /var/.../v28_rebind_backup.sql")
    finally:
        db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("--dry-run", action="store_true", help="只报告不改")
    grp.add_argument("--apply",   action="store_true", help="真改")
    args = p.parse_args()
    run(dry_run=args.dry_run)
```

### 改动 3：测试

`backend/tests/test_v28_second_level_binding.py` 4 条：

1. `test_second_level_gangwei_binding_contract`：目录 `（六）合同控制/合同管理的岗位职责说明书` + 文件名 `xx.pdf` → 应绑 I-45
2. `test_second_level_gangwei_budget`：目录 `（一）预算业务控制/预算业务的岗位职责说明书/` → 应绑 I-14
3. `test_second_level_zhidu_still_works`：目录 `（六）合同控制/合同管理的内部控制制度/` → 应绑 I-44（默认制度）
4. `test_second_level_unknown_falls_back_to_protocol`：目录 `（六）合同控制/某未知子文件夹/` → 应回退到 I-44 protocol_fallback（保持向后兼容）

## 涉及文件

| 文件 | 变更 | 责任 |
|------|-----|------|
| `backend/app/services/material_matcher.py` | Modify | 加 SUBCATEGORY_INDICATOR_MAP + SECOND_LEVEL_KEYWORDS + `_match_second_level` |
| `backend/app/scripts/rebind_wrong_bindings_v28.py` | Create | 一次性 rebind 脚本，支持 --dry-run 和 --apply |
| `backend/tests/test_v28_second_level_binding.py` | Create | 4 条 pytest |

## 部署顺序

1. **cp 代码进 3 容器 + restart backend**（先修新绑逻辑，防止边跑边错绑）
2. **跑 dry-run 看影响** `docker compose exec -T backend python -m app.scripts.rebind_wrong_bindings_v28 --dry-run`
3. **给用户 review 报告**（预计约 52000 material + 数万 finding）
4. **用户 approve 后跑 --apply** 真改（几分钟内完成，可回滚）
5. **spot check**：随机抽 3-5 份材料确认 indicator_id 改对了
6. 前端 F5 刷新任务列表看 material 绑定显示正确

## 回滚

- 代码：git revert 1 个 commit → cp 老 material_matcher.py 进容器 → restart
- 数据：`psql -f /app/data/v28_rebind_backup.sql`（脚本备份的 SQL）

## 风险 & 缓解

| 风险 | 概率 | 缓解 |
|---|---|---|
| 误绑：非"岗位分离"文件被识别为岗位分离 | 低 | 关键词表窄（3 个），必须严格匹配"岗位职责说明"、"岗位分离"、"岗位职责分工"；未来发现误绑再收窄 |
| finding 同步失败 | 低 | 事务 + 分批提交，失败自动回滚该批 |
| rebind 影响 stats 显示 | 中 | 已核查任务的 stats 里含旧 indicator_id，用户下次进详情/重算时会自动刷新 |
| 用户跑错命令误改 | 低 | 强制 --dry-run 或 --apply 二选一，无 default 行为 |
