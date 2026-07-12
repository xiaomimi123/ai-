# v2.8 二级文件夹语义识别 + 修复错绑 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `material_matcher.match_indicator_by_path_and_content` 识别"XX业务/岗位职责说明书"这类二级文件夹语义，并一次性 rebind 生产上 52003 份错绑材料（+同步 finding 归属）。

**Architecture:** 在现有 `match_indicator_by_path_and_content` 的候选关键词匹配失败后、`protocol_fallback` 前插入一层"二级路径 → 语义类别 → 该子类特定指标"识别。历史错绑用独立脚本一次性 rebind，事务分批 + SQL 备份可回滚，`--dry-run`/`--apply` 二选一。

**Tech Stack:** Python 3.11, SQLAlchemy ORM, pytest, Docker Compose（backend/worker/enrich_worker 三容器 cp 部署，不 rebuild 镜像）

## Global Constraints

- 生产代码路径 `/opt/audit/compliance-agent/` 不是 git 仓库，只能 scp（[[project-deployment]]）
- 后端代码改动必须 `docker compose cp` 到 backend / worker / enrich_worker 三个容器
- 改后端后 restart backend + worker + enrich_worker（`docker compose restart nginx` 只有 rebuild 时才需要）
- 无 rebuild：cp 补丁 + restart 即可（本次改动纯 Python）
- 关键词识别顺序敏感：更具体的 keyword 放前面（"岗位职责说明" 前于 "岗位分离"）
- 脚本必须支持 `--dry-run`/`--apply` 二选一，无 default 行为
- 每个改动配自动化 pytest，无 pytest 覆盖的代码禁止上生产

---

## File Structure

| 文件 | 责任 | 状态 |
|---|---|---|
| `compliance-agent/backend/app/services/material_matcher.py` | 加 SUBCATEGORY_INDICATOR_MAP + SECOND_LEVEL_KEYWORDS + `_match_second_level` + 修改 `match_indicator_by_path_and_content` | 修改 |
| `compliance-agent/backend/tests/test_v28_second_level_binding.py` | v2.8 二级识别的 4 条 pytest | 新建 |
| `compliance-agent/backend/app/scripts/rebind_wrong_bindings_v28.py` | 一次性 rebind 脚本（--dry-run / --apply） | 新建 |
| `compliance-agent/backend/tests/test_rebind_v28.py` | rebind 脚本单测（含 finding 同步 + 幂等） | 新建 |

---

## Task 1: material_matcher 加二级识别（TDD）

**Files:**
- Modify: `compliance-agent/backend/app/services/material_matcher.py`（加常量 + `_match_second_level` + 改 `match_indicator_by_path_and_content`）
- Test: `compliance-agent/backend/tests/test_v28_second_level_binding.py`（新建）

**Interfaces:**
- Consumes: 现有 `_normalize(s: str) -> str`、`match_subcategory(file_name: str) -> Optional[str]`、`Indicator` 模型（`indicator_code`、`subcategory`、`category`、`required_materials` 字段）
- Produces:
  - 常量 `SUBCATEGORY_INDICATOR_MAP: dict[str, dict[str, str]]`
  - 常量 `SECOND_LEVEL_KEYWORDS: list[tuple[str, str]]`
  - 函数 `_match_second_level(dir_part: str, subcategory: str, indicators: list) -> Optional[Indicator]`
  - `match_indicator_by_path_and_content` 现有签名不变，新增 source 取值 `"path+second_level"`（保留 `"path+keyword"` / `"path+protocol_fallback"` / `"keyword_global"` / `"none"`）

- [ ] **Step 1: Write failing test — 岗位识别到合同岗位分离 I-45**

Append to `compliance-agent/backend/tests/test_v28_second_level_binding.py`（新建文件）：

```python
"""v2.8 二级文件夹语义识别测试。

背景：v1.5 后生产 52003 份材料错绑，二级文件夹 "XX业务/岗位职责说明书"
被 match_indicator_by_path_and_content 只识别到一级子类，走 protocol_fallback
绑到 "XX制度"（I-13/20/25/32/37/44）而非 "XX岗位分离"（I-14/21/26/33/38/45）。
"""
import json as _json


def _fake_ind(code, sub, materials, name=None):
    """轻量 Indicator 替身（与 test_path_binding.py 保持一致）。"""
    class FakeInd:
        pass
    f = FakeInd()
    f.id = int(code.split("-")[1]) if "-" in code else 0
    f.indicator_code = code
    f.subcategory = sub
    f.category = sub
    f.name = name or code
    f.required_materials = _json.dumps(materials, ensure_ascii=False)
    return f


def test_second_level_gangwei_binding_contract():
    """路径 "（六）合同控制/合同管理的岗位职责说明书/" → I-45 岗位分离，high。"""
    from app.services.material_matcher import match_indicator_by_path_and_content
    inds = [
        _fake_ind("I-44", "（六）合同控制", ["合同管理制度"], "合同制度"),
        _fake_ind("I-45", "（六）合同控制", [], "合同岗位分离"),
    ]
    ind, conf, src = match_indicator_by_path_and_content(
        "某单位/（六）合同控制/合同管理的岗位职责说明书/xx.pdf",
        "xx.pdf",
        "",
        inds,
    )
    assert ind is not None and ind.indicator_code == "I-45"
    assert conf == "high"
    assert src == "path+second_level"
```

- [ ] **Step 2: Run test — verify RED**

```bash
cd compliance-agent/backend && python -m pytest tests/test_v28_second_level_binding.py::test_second_level_gangwei_binding_contract -v
```

Expected: `FAIL` — 断言 `ind.indicator_code == "I-45"` 失败（当前会返回 I-44 或 conf/src 不对）

- [ ] **Step 3: 在 material_matcher.py 加常量和 `_match_second_level`**

在 `compliance-agent/backend/app/services/material_matcher.py` 文件末尾（现有 `SUBCATEGORY_TO_PROTOCOL_INDICATOR` 定义之后、`match_indicator_by_path_and_content` 之前）插入：

```python
# ============================================================
# v2.8：每个业务子类内"语义类别 → 具体指标 code"的映射
# 用于在二级文件夹名（如"合同管理的岗位职责说明书"）识别到
# 更具体的指标（岗位分离 vs 制度），修复 52003 份错绑
# ============================================================
SUBCATEGORY_INDICATOR_MAP: dict[str, dict[str, str]] = {
    "（一）预算业务控制":         {"zhidu": "I-13", "gangwei": "I-14"},
    "（二）收支业务控制":         {"zhidu": "I-20", "gangwei": "I-21"},
    "（三）政府采购业务控制":     {"zhidu": "I-25", "gangwei": "I-26"},
    "（四）资产控制":             {"zhidu": "I-32", "gangwei": "I-33"},
    "（五）建设项目控制":         {"zhidu": "I-37", "gangwei": "I-38"},
    "（六）合同控制":             {"zhidu": "I-44", "gangwei": "I-45"},
}

# v2.8：二级文件夹名里的关键词 → 语义类别
# 顺序敏感：更具体的 keyword 放前面
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


def _match_second_level(
    dir_part: str,
    subcategory: str,
    indicators: list,
) -> Optional[Indicator]:
    """v2.8：从 dir_part 里识别二级语义（岗位分离 / 制度）→ 该子类特定指标。

    dir_part 结构典型："某单位/（六）合同控制/合同管理的岗位职责说明书"
    做法：对整个 dir_part 做 keyword contains（一级子类里通常不含 gangwei/zhidu 字样）。
    命中后查 SUBCATEGORY_INDICATOR_MAP[subcategory][semantic] → 具体 indicator_code。
    """
    if not subcategory or not dir_part:
        return None
    ind_map = SUBCATEGORY_INDICATOR_MAP.get(_normalize(subcategory))
    if not ind_map:
        return None
    normalized = _normalize(dir_part)
    for keyword, semantic in SECOND_LEVEL_KEYWORDS:
        if keyword in normalized:
            target_code = ind_map.get(semantic)
            if not target_code:
                continue
            target_ind = next(
                (ind for ind in indicators if ind.indicator_code == target_code),
                None,
            )
            if target_ind:
                return target_ind
    return None
```

- [ ] **Step 4: 改 `match_indicator_by_path_and_content` 插入二级识别**

在 `compliance-agent/backend/app/services/material_matcher.py` 定位到现有函数 `match_indicator_by_path_and_content`（约 line 265-309）。找到：

```python
    if subcategory:
        candidates = [
            ind for ind in indicators
            if _normalize(ind.subcategory or ind.category or "") == _normalize(subcategory)
        ]
        if candidates:
            hit = match_indicator_by_content(file_name, parsed_text, candidates)
            if hit:
                return (hit, "high", "path+keyword")
        # v1.8：子类识别成功 → 即使 candidates 为空（如 v1.5 子类的 subcategory
        # 字段在指标库里是空字符串），也通过 protocol_fallback 兜底到对应制度类指标
        protocol_code = SUBCATEGORY_TO_PROTOCOL_INDICATOR.get(_normalize(subcategory))
```

替换为（在 candidate 匹配后、protocol_fallback 前插入 v2.8 二级识别）：

```python
    if subcategory:
        candidates = [
            ind for ind in indicators
            if _normalize(ind.subcategory or ind.category or "") == _normalize(subcategory)
        ]
        if candidates:
            hit = match_indicator_by_content(file_name, parsed_text, candidates)
            if hit:
                return (hit, "high", "path+keyword")
        # v2.8：二级文件夹语义识别（如"XX业务/岗位职责说明书"→ 岗位分离指标）
        # 必须放在 protocol_fallback 前，否则会被默认制度指标先抢
        second_hit = _match_second_level(dir_part, subcategory, indicators)
        if second_hit:
            return (second_hit, "high", "path+second_level")
        # v1.8：子类识别成功 → 即使 candidates 为空（如 v1.5 子类的 subcategory
        # 字段在指标库里是空字符串），也通过 protocol_fallback 兜底到对应制度类指标
        protocol_code = SUBCATEGORY_TO_PROTOCOL_INDICATOR.get(_normalize(subcategory))
```

- [ ] **Step 5: Run test — verify GREEN**

```bash
cd compliance-agent/backend && python -m pytest tests/test_v28_second_level_binding.py::test_second_level_gangwei_binding_contract -v
```

Expected: `PASS`

- [ ] **Step 6: 加剩余 3 条测试**

在 `compliance-agent/backend/tests/test_v28_second_level_binding.py` 追加：

```python
def test_second_level_gangwei_budget():
    """预算子类 + 岗位职责说明 → I-14 预算岗位分离。"""
    from app.services.material_matcher import match_indicator_by_path_and_content
    inds = [
        _fake_ind("I-13", "（一）预算业务控制", ["预算管理制度"], "预算制度"),
        _fake_ind("I-14", "（一）预算业务控制", [], "预算岗位分离"),
    ]
    ind, conf, src = match_indicator_by_path_and_content(
        "某单位/（一）预算业务控制/预算业务的岗位职责说明书/yy.pdf",
        "yy.pdf",
        "",
        inds,
    )
    assert ind is not None and ind.indicator_code == "I-14"
    assert conf == "high"
    assert src == "path+second_level"


def test_second_level_zhidu_still_works():
    """路径含"内部控制制度"→ 走 zhidu semantic → I-44 合同制度。"""
    from app.services.material_matcher import match_indicator_by_path_and_content
    inds = [
        _fake_ind("I-44", "（六）合同控制", ["合同管理制度"], "合同制度"),
        _fake_ind("I-45", "（六）合同控制", [], "合同岗位分离"),
    ]
    ind, conf, src = match_indicator_by_path_and_content(
        "某单位/（六）合同控制/合同管理的内部控制制度/zz.pdf",
        "zz.pdf",
        "",
        inds,
    )
    assert ind is not None and ind.indicator_code == "I-44"
    assert conf == "high"
    assert src == "path+second_level"


def test_second_level_unknown_falls_back_to_protocol():
    """二级文件夹名不含任何关键词 → 走原 protocol_fallback → I-44。"""
    from app.services.material_matcher import match_indicator_by_path_and_content
    inds = [
        _fake_ind("I-44", "（六）合同控制", ["合同管理制度"], "合同制度"),
        _fake_ind("I-45", "（六）合同控制", [], "合同岗位分离"),
    ]
    ind, conf, src = match_indicator_by_path_and_content(
        "某单位/（六）合同控制/某未知子文件夹/qq.pdf",
        "qq.pdf",
        "",
        inds,
    )
    assert ind is not None and ind.indicator_code == "I-44"
    assert conf == "medium"
    assert src == "path+protocol_fallback"
```

- [ ] **Step 7: Run all 4 tests + 全 material_matcher 回归**

```bash
cd compliance-agent/backend && python -m pytest tests/test_v28_second_level_binding.py tests/test_path_binding.py tests/test_material_matcher.py -v
```

Expected: 全部 PASS（新增 4 条 + 原 test_path_binding 4 条 + test_material_matcher 若干条都 pass，二级识别不破坏 v1.5/v1.8 老逻辑）

- [ ] **Step 8: Commit**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/backend/app/services/material_matcher.py \
        compliance-agent/backend/tests/test_v28_second_level_binding.py
git commit -m "$(cat <<'EOF'
feat(v2.8): material_matcher 二级文件夹语义识别

新增 SUBCATEGORY_INDICATOR_MAP + SECOND_LEVEL_KEYWORDS + _match_second_level，
在 candidate 关键词匹配失败后、protocol_fallback 前识别"XX业务/岗位职责说明书"
这类二级路径 → 岗位分离指标（I-14/21/26/33/38/45），修复 v1.8 fallback
默认到制度指标的错绑。

新增 test_v28_second_level_binding.py 4 条测试覆盖岗位/制度/未知路径三种场景。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 编写 rebind 脚本 + 单测

**Files:**
- Create: `compliance-agent/backend/app/scripts/rebind_wrong_bindings_v28.py`
- Test: `compliance-agent/backend/tests/test_rebind_v28.py`

**Interfaces:**
- Consumes: `app.models.Material`（`indicator_id`、`file_name`）、`app.models.Finding`（`material_id`、`indicator_id`）、`app.models.Indicator`（`id`、`indicator_code`、`name`）、`app.models.SessionLocal`
- Produces:
  - 函数 `find_wrong_bindings(db) -> list[tuple[Material, Indicator]]`
  - 函数 `dump_backup(to_fix: list, path: str) -> None`
  - 函数 `report_impact(to_fix: list, db) -> None`（stdout print）
  - 函数 `run(db, dry_run: bool, batch: int = 500) -> dict`（返回 `{"matched": N, "updated_materials": M, "updated_findings": K}`）
  - CLI 入口：`python -m app.scripts.rebind_wrong_bindings_v28 --dry-run|--apply`

- [ ] **Step 1: Write failing test — dry-run 只统计不改**

新建 `compliance-agent/backend/tests/test_rebind_v28.py`：

```python
"""v2.8 rebind_wrong_bindings 脚本单测。

用 conftest 的临时 SQLite DB fixture，避免动生产 postgres。
覆盖：
- dry-run 只统计不改
- --apply 实际改 material.indicator_id
- --apply 同步改 finding.indicator_id
- 幂等：跑两次第二次 updated=0
- 非目标材料不动
"""
import pytest

from app.models import Material, Finding, Indicator


def _seed_indicators(db):
    """建 I-44 合同制度 + I-45 合同岗位分离两条。"""
    from app.scripts.rebind_wrong_bindings_v28 import find_wrong_bindings  # noqa
    i44 = Indicator(indicator_code="I-44", name="合同制度",
                    category="（六）合同控制", subcategory="（六）合同控制",
                    required_materials="[]")
    i45 = Indicator(indicator_code="I-45", name="合同岗位分离",
                    category="（六）合同控制", subcategory="（六）合同控制",
                    required_materials="[]")
    db.add_all([i44, i45])
    db.commit()
    return i44, i45


def test_dry_run_does_not_modify(db_session):
    """dry-run 只报告不改 material.indicator_id。"""
    from app.scripts.rebind_wrong_bindings_v28 import run
    i44, i45 = _seed_indicators(db_session)
    m = Material(
        task_id=1, unit_id=1, indicator_id=i44.id,
        file_name="（六）合同控制/合同管理的岗位职责说明书/xx.pdf",
        file_path="/tmp/xx.pdf",
    )
    db_session.add(m)
    db_session.commit()
    original_id = m.indicator_id

    result = run(db_session, dry_run=True)
    db_session.refresh(m)
    assert result["matched"] == 1
    assert result["updated_materials"] == 0
    assert m.indicator_id == original_id  # 没改
```

- [ ] **Step 2: Run test — verify RED**

```bash
cd compliance-agent/backend && python -m pytest tests/test_rebind_v28.py::test_dry_run_does_not_modify -v
```

Expected: `FAIL` — `ModuleNotFoundError: No module named 'app.scripts.rebind_wrong_bindings_v28'`

- [ ] **Step 3: 写 rebind 脚本骨架（find + dry-run 报告）**

新建 `compliance-agent/backend/app/scripts/rebind_wrong_bindings_v28.py`：

```python
"""v2.8：修复历史错绑 —— file_name 里含"（X）XX业务控制/*岗位*"但绑到"制度"类指标。

生产实测：52003 份材料错绑，占含"岗位"字样材料的 71%。
根因：v1.8 material_matcher 只按一级子类走 protocol_fallback 到"制度"类指标，
不识别二级文件夹语义。v2.8 matcher 已修，此脚本清理历史存量。

支持：
- --dry-run：只报告不改（默认必须显式加 --apply 才真改）
- 幂等：跑第二次影响 0 行
- 事务保护：分批 500 条 commit，失败自动回滚该批
- 备份：--apply 时先 dump 原 indicator_id 到 /app/data/v28_rebind_backup.sql

用法：
    docker compose exec -T backend python -m app.scripts.rebind_wrong_bindings_v28 --dry-run
    docker compose exec -T backend python -m app.scripts.rebind_wrong_bindings_v28 --apply
"""
from __future__ import annotations

import argparse
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Finding, Indicator, Material


# 匹配 file_name 里"（一）预算业务控制" 到 "（六）合同控制"前缀 → 目标 gangwei 指标 code
SUBCATEGORY_TO_GANGWEI: list[tuple[str, str]] = [
    (r"（一）\s*预算业务控制",       "I-14"),
    (r"（二）\s*收支业务控制",       "I-21"),
    (r"（三）\s*政府采购业务控制",   "I-26"),
    (r"（四）\s*资产控制",           "I-33"),
    (r"（五）\s*建设项目控制",       "I-38"),
    (r"（六）\s*合同控制",           "I-45"),
]

GANGWEI_KEYWORD = re.compile(r"岗位职责说明|岗位分离|岗位职责分工")


def find_wrong_bindings(db: Session) -> list[tuple[Material, Indicator]]:
    """返回 [(material, target_indicator), ...] 需要 rebind 的列表。"""
    zhidu_inds = db.query(Indicator).filter(Indicator.name.contains("制度")).all()
    zhidu_ids = {i.id for i in zhidu_inds}
    code2ind = {i.indicator_code: i for i in db.query(Indicator).all()}

    if not zhidu_ids:
        return []

    candidates = db.query(Material).filter(
        Material.indicator_id.in_(zhidu_ids),
        Material.file_name.contains("岗位"),
    ).all()

    to_fix: list[tuple[Material, Indicator]] = []
    for m in candidates:
        if not GANGWEI_KEYWORD.search(m.file_name or ""):
            continue
        target_code: Optional[str] = None
        for pattern, code in SUBCATEGORY_TO_GANGWEI:
            if re.search(pattern, m.file_name or ""):
                target_code = code
                break
        if not target_code:
            continue
        target_ind = code2ind.get(target_code)
        if target_ind and target_ind.id != m.indicator_id:
            to_fix.append((m, target_ind))
    return to_fix


def dump_backup(to_fix: list[tuple[Material, Indicator]], path: str) -> None:
    """把当前 material.id + 原 indicator_id 备份成可回滚 SQL。"""
    with open(path, "w") as f:
        f.write(f"-- v2.8 rebind backup {datetime.now(timezone.utc).isoformat()}\n")
        f.write(f"-- 共 {len(to_fix)} 条\n\n")
        for m, _ in to_fix:
            f.write(f"UPDATE material SET indicator_id = {m.indicator_id} WHERE id = {m.id};\n")


def report_impact(to_fix: list[tuple[Material, Indicator]], db: Session) -> None:
    """dry-run 报告：material 数 / finding 数 / 任务数 / 分布。"""
    mat_ids = [m.id for m, _ in to_fix]
    finding_count = (
        db.query(Finding).filter(Finding.material_id.in_(mat_ids)).count()
        if mat_ids else 0
    )
    task_ids = {m.task_id for m, _ in to_fix}
    by_target: Counter = Counter(target.indicator_code for _, target in to_fix)

    print(f"待改绑 material 数: {len(to_fix)}")
    print(f"关联 finding 数:    {finding_count}")
    print(f"涉及任务数:         {len(task_ids)}")
    print()
    print("按目标指标分布:")
    for code, n in sorted(by_target.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {code}: {n}")


def run(db: Session, dry_run: bool, batch: int = 500) -> dict:
    """核心执行函数。返回 {"matched": N, "updated_materials": M, "updated_findings": K}。"""
    to_fix = find_wrong_bindings(db)
    report_impact(to_fix, db)
    print()
    if dry_run:
        print("--dry-run: 不实际修改。加 --apply 真改。")
        return {"matched": len(to_fix), "updated_materials": 0, "updated_findings": 0}

    backup_path = "/app/data/v28_rebind_backup.sql"
    try:
        dump_backup(to_fix, backup_path)
        print(f"✓ 原绑定已备份到 {backup_path}")
    except OSError as e:
        # 单测/本地跑 /app/data 不存在，退化到 /tmp
        backup_path = "/tmp/v28_rebind_backup.sql"
        dump_backup(to_fix, backup_path)
        print(f"✓ 原绑定已备份到 {backup_path}（fallback）: {e!s}")

    updated_mats = 0
    updated_findings = 0
    for i in range(0, len(to_fix), batch):
        chunk = to_fix[i:i + batch]
        for m, target in chunk:
            old_ind_id = m.indicator_id
            f_updated = (
                db.query(Finding)
                .filter(Finding.material_id == m.id,
                        Finding.indicator_id == old_ind_id)
                .update({Finding.indicator_id: target.id},
                        synchronize_session=False)
            )
            updated_findings += f_updated
            m.indicator_id = target.id
            updated_mats += 1
        db.commit()
        print(f"  已处理 {i + len(chunk)}/{len(to_fix)}")

    print()
    print(f"✓ 完成：改绑 material {updated_mats} 条，同步 finding {updated_findings} 条")
    print(f"  回滚：psql -f {backup_path}")
    return {
        "matched": len(to_fix),
        "updated_materials": updated_mats,
        "updated_findings": updated_findings,
    }


if __name__ == "__main__":
    from app.models import SessionLocal

    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="只报告不改")
    group.add_argument("--apply",   action="store_true", help="真改")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        run(db, dry_run=args.dry_run)
    finally:
        db.close()
```

- [ ] **Step 4: Run test — verify GREEN**

```bash
cd compliance-agent/backend && python -m pytest tests/test_rebind_v28.py::test_dry_run_does_not_modify -v
```

Expected: `PASS`

- [ ] **Step 5: 加剩余 4 条测试（apply / finding 同步 / 幂等 / 非目标不动）**

在 `compliance-agent/backend/tests/test_rebind_v28.py` 追加：

```python
def test_apply_updates_material_indicator(db_session, tmp_path, monkeypatch):
    """--apply 实际改 material.indicator_id。"""
    from app.scripts.rebind_wrong_bindings_v28 import run
    i44, i45 = _seed_indicators(db_session)
    m = Material(
        task_id=1, unit_id=1, indicator_id=i44.id,
        file_name="（六）合同控制/合同管理的岗位职责说明书/xx.pdf",
        file_path="/tmp/xx.pdf",
    )
    db_session.add(m)
    db_session.commit()

    result = run(db_session, dry_run=False)
    db_session.refresh(m)
    assert result["updated_materials"] == 1
    assert m.indicator_id == i45.id


def test_apply_syncs_finding_indicator(db_session):
    """--apply 同步改 finding.indicator_id 到新的岗位分离指标。"""
    from app.scripts.rebind_wrong_bindings_v28 import run
    i44, i45 = _seed_indicators(db_session)
    m = Material(
        task_id=1, unit_id=1, indicator_id=i44.id,
        file_name="（六）合同控制/合同管理的岗位职责说明书/xx.pdf",
        file_path="/tmp/xx.pdf",
    )
    db_session.add(m)
    db_session.commit()
    f = Finding(
        task_id=1, unit_id=1, indicator_id=i44.id, material_id=m.id,
        finding_type="dummy", severity="low", description="test",
    )
    db_session.add(f)
    db_session.commit()

    result = run(db_session, dry_run=False)
    db_session.refresh(f)
    assert result["updated_findings"] == 1
    assert f.indicator_id == i45.id


def test_idempotent_second_run_zero(db_session):
    """跑第二遍 matched=0 updated=0。"""
    from app.scripts.rebind_wrong_bindings_v28 import run
    i44, i45 = _seed_indicators(db_session)
    m = Material(
        task_id=1, unit_id=1, indicator_id=i44.id,
        file_name="（六）合同控制/合同管理的岗位职责说明书/xx.pdf",
        file_path="/tmp/xx.pdf",
    )
    db_session.add(m)
    db_session.commit()
    run(db_session, dry_run=False)

    result2 = run(db_session, dry_run=False)
    assert result2["matched"] == 0
    assert result2["updated_materials"] == 0


def test_non_target_material_untouched(db_session):
    """file_name 不含"岗位" or 不含子类前缀的材料不动。"""
    from app.scripts.rebind_wrong_bindings_v28 import run
    i44, _ = _seed_indicators(db_session)
    # 场景 A：不含"岗位"
    m1 = Material(task_id=1, unit_id=1, indicator_id=i44.id,
                  file_name="（六）合同控制/合同管理制度.pdf",
                  file_path="/tmp/m1.pdf")
    # 场景 B：含"岗位"但不含子类前缀
    m2 = Material(task_id=1, unit_id=1, indicator_id=i44.id,
                  file_name="别的目录/岗位职责说明.pdf",
                  file_path="/tmp/m2.pdf")
    db_session.add_all([m1, m2])
    db_session.commit()

    result = run(db_session, dry_run=False)
    db_session.refresh(m1)
    db_session.refresh(m2)
    assert result["updated_materials"] == 0
    assert m1.indicator_id == i44.id
    assert m2.indicator_id == i44.id
```

- [ ] **Step 6: Run all 5 rebind tests**

```bash
cd compliance-agent/backend && python -m pytest tests/test_rebind_v28.py -v
```

Expected: 全部 PASS

- [ ] **Step 7: Full test suite regression**

```bash
cd compliance-agent/backend && python -m pytest -x
```

Expected: 全 pass。若 `test_rebind_v28.py` 里的 `db_session` fixture 不存在，先看 `conftest.py` fixture 名（通常是 `db` 或 `session`），把 `db_session` 全量改为实际名。如果 conftest 里没有 SQLite 内存 fixture，需要在 `test_rebind_v28.py` 头部加：

```python
import pytest
from app.models import SessionLocal, Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
```

- [ ] **Step 8: Commit**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/backend/app/scripts/rebind_wrong_bindings_v28.py \
        compliance-agent/backend/tests/test_rebind_v28.py
git commit -m "$(cat <<'EOF'
feat(v2.8): rebind_wrong_bindings_v28 一次性修复错绑脚本

- --dry-run/--apply 二选一，无默认行为
- 分批 500 条 commit，失败自动回滚该批
- 备份原 indicator_id 到 /app/data/v28_rebind_backup.sql（fallback /tmp）
- 同步 finding.indicator_id 让 stats 自然对应新指标
- 5 条 pytest 覆盖：dry-run / apply / finding 同步 / 幂等 / 非目标不动

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 部署到生产（cp + restart + dry-run）

**Files:** 无（scp + docker cp）

**Interfaces:** 无

- [ ] **Step 1: scp 两个文件到生产**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
scp compliance-agent/backend/app/services/material_matcher.py \
    root@8.163.75.9:/opt/audit/compliance-agent/backend/app/services/material_matcher.py
scp compliance-agent/backend/app/scripts/rebind_wrong_bindings_v28.py \
    root@8.163.75.9:/opt/audit/compliance-agent/backend/app/scripts/rebind_wrong_bindings_v28.py
```

Expected: `material_matcher.py 100%  xxx KB` × 2

- [ ] **Step 2: cp 到 backend / worker / enrich_worker 三容器**

给用户以下命令让他在服务器上跑（本地无法 ssh 到生产 docker）：

```bash
cd /opt/audit/compliance-agent
docker compose cp backend/app/services/material_matcher.py backend:/app/app/services/material_matcher.py
docker compose cp backend/app/services/material_matcher.py worker:/app/app/services/material_matcher.py
docker compose cp backend/app/services/material_matcher.py enrich_worker:/app/app/services/material_matcher.py

docker compose cp backend/app/scripts/rebind_wrong_bindings_v28.py backend:/app/app/scripts/rebind_wrong_bindings_v28.py
docker compose cp backend/app/scripts/rebind_wrong_bindings_v28.py worker:/app/app/scripts/rebind_wrong_bindings_v28.py
docker compose cp backend/app/scripts/rebind_wrong_bindings_v28.py enrich_worker:/app/app/scripts/rebind_wrong_bindings_v28.py
```

Expected: 6 次 `Successfully copied` 输出

- [ ] **Step 3: restart 后端三容器**

```bash
docker compose restart backend worker enrich_worker
```

Expected: `Container compliance-agent-backend-1  Started` × 3

- [ ] **Step 4: 验证 matcher 已生效（新绑逻辑上线）**

```bash
docker compose exec backend grep -c "SUBCATEGORY_INDICATOR_MAP" /app/app/services/material_matcher.py
docker compose exec backend grep -c "_match_second_level" /app/app/services/material_matcher.py
docker compose exec worker grep -c "SUBCATEGORY_INDICATOR_MAP" /app/app/services/material_matcher.py
docker compose exec enrich_worker grep -c "SUBCATEGORY_INDICATOR_MAP" /app/app/services/material_matcher.py
```

Expected: 每条至少输出 `1`

- [ ] **Step 5: 跑 dry-run 看影响范围**

```bash
docker compose exec -T backend python -m app.scripts.rebind_wrong_bindings_v28 --dry-run
```

Expected: 输出类似：
```
待改绑 material 数: ~52003
关联 finding 数:    ~数万
涉及任务数:         XX
按目标指标分布:
  I-14: 15269
  I-21: 8536
  I-32: 7281
  I-25: 7244
  I-45: 7176
  I-37: 6295
--dry-run: 不实际修改。加 --apply 真改。
```

- [ ] **Step 6: 把 dry-run 输出贴给用户确认**

告诉用户 dry-run 结果（材料数 / finding 数 / 任务数 / 分布），等待用户明确说"改"或"apply"再进入下一步。**未获用户明确批准前不得进入 Step 7。**

---

## Task 4: 执行真改 + 抽查验证

**Files:** 无

**Interfaces:** 无

- [ ] **Step 1: 备份 material 表（防脚本自身 bug）**

```bash
docker compose exec postgres pg_dump -U compliance -d compliance -t material -t finding \
    > /opt/audit/backup_v28_before_$(date +%Y%m%d_%H%M%S).sql
ls -lh /opt/audit/backup_v28_before_*.sql | tail -1
```

Expected: 输出文件 > 10MB

- [ ] **Step 2: 跑 --apply 真改**

```bash
docker compose exec -T backend python -m app.scripts.rebind_wrong_bindings_v28 --apply
```

Expected: 每 500 条打印一次进度，最终：
```
✓ 完成：改绑 material 52003 条，同步 finding XXX 条
  回滚：psql -f /app/data/v28_rebind_backup.sql
```

- [ ] **Step 3: 幂等验证**

```bash
docker compose exec -T backend python -m app.scripts.rebind_wrong_bindings_v28 --dry-run
```

Expected: `待改绑 material 数: 0`

- [ ] **Step 4: 抽查 5 份材料**

```bash
docker compose exec -T backend python -c "
from app.models import SessionLocal, Material, Indicator
db = SessionLocal()
sample = db.query(Material).filter(Material.file_name.contains('岗位职责说明')).limit(5).all()
for m in sample:
    ind = db.query(Indicator).get(m.indicator_id)
    print(f'mat #{m.id} → {ind.indicator_code} {ind.name}  file={m.file_name[:80]}')
"
```

Expected: 5 条全部输出 `I-14/21/26/33/38/45` 之一（岗位分离），不再是 `I-13/20/25/32/37/44` 制度类

- [ ] **Step 5: 前端 F5 抽查一个任务**

给用户："请浏览器打开 http://8.163.75.9/ 找一个已知有岗位职责说明书材料的任务，进任务详情 → 材料列表，确认这些材料现在挂在"岗位分离"指标下（例如 I-45 合同岗位分离），而不是"合同制度"（I-44）。"

Expected: 用户确认前端显示正确

- [ ] **Step 6: 备份 backup SQL 到宿主机**

```bash
docker compose exec backend cat /app/data/v28_rebind_backup.sql > /opt/audit/v28_rebind_backup_$(date +%Y%m%d).sql
ls -lh /opt/audit/v28_rebind_backup_*.sql | tail -1
```

Expected: 输出文件 > 1MB（52003 条 UPDATE 大约 3-4MB）

- [ ] **Step 7: 更新 README + 项目文档**

在 `README.md` 或 `compliance-agent/CHANGELOG.md`（找已有的）加一行：

```markdown
### v2.8 (2026-07-12)

- **feat**: `material_matcher` 识别二级文件夹语义（如"XX业务/岗位职责说明书"→ 岗位分离指标），修复 v1.5 后 fallback 到"制度"指标的错绑
- **data**: 一次性 rebind 脚本 `rebind_wrong_bindings_v28.py`，修复生产 52003 份错绑材料
```

- [ ] **Step 8: Commit + 收工**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add README.md compliance-agent/CHANGELOG.md 2>/dev/null || git add README.md
git commit -m "$(cat <<'EOF'
docs(v2.8): CHANGELOG 记录二级文件夹绑定修复

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec coverage:**
- ✅ SUBCATEGORY_INDICATOR_MAP + SECOND_LEVEL_KEYWORDS → Task 1 Step 3
- ✅ `_match_second_level` → Task 1 Step 3
- ✅ `match_indicator_by_path_and_content` 改造 → Task 1 Step 4
- ✅ 4 条 pytest → Task 1 Step 1 + Step 6
- ✅ rebind 脚本 --dry-run / --apply → Task 2 Step 3
- ✅ finding 同步 → Task 2 Step 3 + 测试 Step 5
- ✅ SQL 备份 → Task 2 Step 3（`dump_backup`）
- ✅ 部署（cp 3 容器 + restart backend） → Task 3
- ✅ dry-run 先看影响再 apply → Task 3 Step 5 + Task 4 Step 2
- ✅ 回滚方案：git revert + `psql -f v28_rebind_backup.sql` → Task 3/4 都提到
- ⚠️ 关键词表可扩展性：靠 SUBCATEGORY_INDICATOR_MAP + SECOND_LEVEL_KEYWORDS 结构，未来加行即可，spec 中已注明"未来发现新错绑模式只需在映射表加一行"

**Placeholder scan:**
- 无 "TODO"/"TBD"/"实现细节略"
- 所有代码块完整
- 所有命令带 Expected 输出

**Type consistency:**
- `Optional[Indicator]` 一致（Task 1 Step 3）
- `list[tuple[Material, Indicator]]` 一致（Task 2 Step 3）
- `run(db, dry_run, batch=500) -> dict{"matched", "updated_materials", "updated_findings"}` 一致（Task 2 Step 3 + 测试 Step 1/5）
- `SUBCATEGORY_TO_GANGWEI` 是 `list[tuple[str, str]]`（顺序敏感）— 一致
- 测试里 `_fake_ind` 与 test_path_binding.py 保持同一签名

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-12-second-level-folder-binding.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — 每个 Task 派一个 fresh subagent，Task 间我 review，快速迭代

**2. Inline Execution** — 本会话内跑，Task 1/2 之后 checkpoint 给你看

**Which approach?**
