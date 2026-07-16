# v2.12 全量任务重跑 + 自动定稿 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 遍历系统所有含材料的任务，重新跑 AI 核查 + 生成底稿 + 直接定稿（跳过人工复核），累计费用达 ¥500 停止。

**Architecture:** DeepSeek 客户端加 usage 埋点（append jsonl）+ 独立批量脚本 orchestrate（分批 20 enqueue Celery `run_audit_task` → 轮询 status → auto-finalize SQL 写 status=finalized）+ checkpoint jsonl 支持断点续跑。用系统当前配的模型（不切换），worker=2 不改。

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy + Celery + DeepSeek v4-flash（当前配置）+ pytest.

## Global Constraints

- 用系统当前配置的模型（`app_setting.llm_model`，当前 v4-flash）；脚本不改模型
- 累计费用达 ¥500 停止 enqueue 新任务；在飞的可能超几批（最多 20 任务份费用）
- 只处理 `status != "running"` 且有材料的任务（避开正在跑的，避免踢重复）
- 处理顺序：清 findings + worksheet + status→pending → enqueue → poll ai_done/failed → auto-finalize
- Checkpoint jsonl 路径 `/app/data/v2.12_rerun_checkpoint.jsonl`；LLM usage 路径 `/app/data/llm_usage.jsonl`
- `/app/data` 是 host `./backend/data` bind mount，host 上可读
- pg_dump 备份 4 张表（`audit_tasks / findings / worksheets / worksheet_rows`）到 `/opt/audit/backup_v2.12_before_<ts>.sql`
- Auto-finalize 通过直接 SQL 改 status（不走 HTTP），audit_log detail 明确标记 "v2.12 batch auto-finalize (no human review)"
- 后端改动需 cp 到 backend + worker + enrich_worker 三容器（worker 也调 deepseek）
- 中文注释 + commit 消息

---

## File Structure

| 文件 | 责任 | 状态 |
|---|---|---|
| `compliance-agent/backend/app/llm/deepseek.py` | 加价格常量表 + `_log_usage()` + `sum_usage_cost()` + 两个方法调用埋点 | 修改 |
| `compliance-agent/backend/tests/test_deepseek_usage_log.py` | 3 条 pytest：文件写入 + sum 计算 + 缺 usage 不崩 | 新建 |
| `compliance-agent/backend/app/scripts/rerun_all_tasks_v212.py` | 批量脚本：dry-run / pilot / run 三模式 + checkpoint + 预算守卫 | 新建 |
| `compliance-agent/backend/tests/test_rerun_all_tasks_v212.py` | 4 条 pytest：checkpoint 读写 + reset 清 findings/worksheet + auto_finalize 状态转移 + budget 触发 | 新建 |
| `compliance-agent/README.md` | v2.12 更新日志 | 修改 |

---

## Task 1: LLM usage 埋点（deepseek.py）+ 3 条 pytest

**Files:**
- Modify: `compliance-agent/backend/app/llm/deepseek.py`（加常量 + 2 helper + 2 处调用）
- Test: `compliance-agent/backend/tests/test_deepseek_usage_log.py`（新建）

**Interfaces:**
- Consumes: 现有 `DeepSeekClient.complete()` / `extract_json()` 里 `resp.usage`（openai SDK 的 CompletionUsage 对象）
- Produces:
  - 模块常量 `_PRICE_PER_M_INPUT: dict[str, float]`、`_PRICE_PER_M_OUTPUT: dict[str, float]`、`_USAGE_LOG_PATH: str`
  - `_log_usage(model: str, usage) -> None` — 追加一条到 jsonl，异常不抛
  - `sum_usage_cost(path: str = _USAGE_LOG_PATH) -> tuple[int, int, float]` — 返回 `(prompt_tokens_total, completion_tokens_total, cost_yuan)`

- [ ] **Step 1: 写第一条失败测试 —— sum_usage_cost 空文件返回 0**

新建 `compliance-agent/backend/tests/test_deepseek_usage_log.py`：

```python
"""v2.12 DeepSeek usage 埋点测试。"""
import json
import tempfile


def test_sum_usage_cost_missing_file_returns_zero():
    """文件不存在 → (0, 0, 0.0)。"""
    from app.llm.deepseek import sum_usage_cost
    tp, tc, cost = sum_usage_cost("/tmp/nonexistent_v2.12_usage.jsonl")
    assert tp == 0
    assert tc == 0
    assert cost == 0.0
```

- [ ] **Step 2: 跑测试 —— verify RED**

```bash
cd compliance-agent/backend && python -m pytest tests/test_deepseek_usage_log.py::test_sum_usage_cost_missing_file_returns_zero -v
```

Expected: FAIL `ImportError: cannot import name 'sum_usage_cost'`

- [ ] **Step 3: 修改 deepseek.py 加常量 + helpers**

打开 `compliance-agent/backend/app/llm/deepseek.py`。在文件顶部（`from app.llm.base import LLMClient` 之后）加：

```python
import json
import os
from datetime import datetime, timezone


# ============================================================
# v2.12：LLM usage 埋点（供批量脚本读，估算成本）
# ============================================================
# 单价：元 / 1M tokens（DeepSeek 官方 2026-01 价格；缓存未命中价）
_PRICE_PER_M_INPUT = {
    "deepseek-v4-flash":  0.10,
    "deepseek-v4-pro":    0.50,
    "deepseek-chat":      0.10,   # 兼容别名
    "deepseek-reasoner":  0.50,
}
_PRICE_PER_M_OUTPUT = {
    "deepseek-v4-flash":  0.50,
    "deepseek-v4-pro":    2.00,
    "deepseek-chat":      0.50,
    "deepseek-reasoner":  2.00,
}
_USAGE_LOG_PATH = "/app/data/llm_usage.jsonl"


def _log_usage(model: str, usage) -> None:
    """把一次调用的 usage 追加到 jsonl；异常吞掉不影响主流程。"""
    if usage is None:
        return
    try:
        pt = int(getattr(usage, "prompt_tokens", 0) or 0)
        ct = int(getattr(usage, "completion_tokens", 0) or 0)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "prompt_tokens": pt,
            "completion_tokens": ct,
        }
        path = _USAGE_LOG_PATH
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except OSError:
            path = "/tmp/llm_usage.jsonl"
        with open(path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 埋点不能影响主流程


def sum_usage_cost(path: str = _USAGE_LOG_PATH) -> tuple[int, int, float]:
    """扫描 jsonl，返回 (prompt_tokens_total, completion_tokens_total, cost_yuan)。

    未知模型按贵档 (0.5/2.0) 兜底，防止低估。
    """
    if not os.path.exists(path):
        return (0, 0, 0.0)
    tp = tc = 0
    cost = 0.0
    with open(path) as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            model = e.get("model", "")
            pt = int(e.get("prompt_tokens", 0) or 0)
            ct = int(e.get("completion_tokens", 0) or 0)
            in_rate = _PRICE_PER_M_INPUT.get(model, 0.5)
            out_rate = _PRICE_PER_M_OUTPUT.get(model, 2.0)
            tp += pt
            tc += ct
            cost += (pt / 1_000_000 * in_rate) + (ct / 1_000_000 * out_rate)
    return (tp, tc, cost)
```

- [ ] **Step 4: 跑测试 —— verify GREEN**

```bash
cd compliance-agent/backend && python -m pytest tests/test_deepseek_usage_log.py::test_sum_usage_cost_missing_file_returns_zero -v
```

Expected: PASS

- [ ] **Step 5: 在 `complete()` 和 `extract_json()` 末尾加埋点调用**

修改 `complete()` 方法。找到：

```python
        resp = self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""
```

改成：

```python
        resp = self._client.chat.completions.create(**kwargs)
        _log_usage(self._model, resp.usage)  # v2.12: 埋点
        return resp.choices[0].message.content or ""
```

对 `extract_json()` 做同样改动。找到：

```python
        resp = self._client.chat.completions.create(**kwargs)
        raw = resp.choices[0].message.content or ""
        return _loads_lenient(raw)
```

改成：

```python
        resp = self._client.chat.completions.create(**kwargs)
        _log_usage(self._model, resp.usage)  # v2.12: 埋点
        raw = resp.choices[0].message.content or ""
        return _loads_lenient(raw)
```

- [ ] **Step 6: 加剩余 2 条测试**

Append to `compliance-agent/backend/tests/test_deepseek_usage_log.py`：

```python
def test_log_and_sum_roundtrip(tmp_path, monkeypatch):
    """写 3 条不同模型的 usage，sum 返回正确的 token 和 cost。"""
    import app.llm.deepseek as ds
    log_file = tmp_path / "usage.jsonl"
    monkeypatch.setattr(ds, "_USAGE_LOG_PATH", str(log_file))

    class FakeUsage:
        def __init__(self, p, c):
            self.prompt_tokens = p
            self.completion_tokens = c

    ds._log_usage("deepseek-v4-flash", FakeUsage(1_000_000, 500_000))
    ds._log_usage("deepseek-v4-flash", FakeUsage(2_000_000, 1_000_000))
    ds._log_usage("deepseek-v4-pro", FakeUsage(100_000, 50_000))

    tp, tc, cost = ds.sum_usage_cost(str(log_file))
    # v4-flash: (1+2)M in × 0.10 + (0.5+1)M out × 0.50 = 0.30 + 0.75 = 1.05
    # v4-pro:   0.1M in × 0.50 + 0.05M out × 2.00     = 0.05 + 0.10 = 0.15
    # total: 1.20
    assert tp == 3_100_000
    assert tc == 1_550_000
    assert abs(cost - 1.20) < 0.001


def test_log_usage_with_none_does_not_crash(tmp_path, monkeypatch):
    """usage=None 不写文件也不抛（openai SDK 有时返回 None）。"""
    import app.llm.deepseek as ds
    log_file = tmp_path / "usage.jsonl"
    monkeypatch.setattr(ds, "_USAGE_LOG_PATH", str(log_file))

    ds._log_usage("deepseek-v4-flash", None)  # 不应抛
    assert not log_file.exists()  # 也不应创建文件
```

- [ ] **Step 7: 跑全部 3 条测试**

```bash
cd compliance-agent/backend && python -m pytest tests/test_deepseek_usage_log.py -v
```

Expected: 3 PASS

- [ ] **Step 8: Commit**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/backend/app/llm/deepseek.py \
        compliance-agent/backend/tests/test_deepseek_usage_log.py
git commit -m "$(cat <<'EOF'
feat(v2.12): DeepSeek 客户端加 LLM usage 埋点

- 加价格常量表（v4-flash 0.1/0.5，v4-pro 0.5/2.0 元/M tokens）
- _log_usage() 追加一条到 /app/data/llm_usage.jsonl；异常不影响主流程
- sum_usage_cost() 扫描 jsonl 返回 (prompt_total, completion_total, cost_yuan)
- 未知模型按贵档兜底防低估
- complete() 和 extract_json() 末尾插入埋点
- 3 条 pytest：空文件 / roundtrip 3 条不同模型 / None usage 不崩

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 批量脚本 `rerun_all_tasks_v212.py` + 4 条 pytest

**Files:**
- Create: `compliance-agent/backend/app/scripts/rerun_all_tasks_v212.py`
- Test: `compliance-agent/backend/tests/test_rerun_all_tasks_v212.py`

**Interfaces:**
- Consumes:
  - `sum_usage_cost(path) -> tuple[int, int, float]` from `app.llm.deepseek`（Task 1）
  - `run_audit_task.delay(task_id)` from `app.tasks`（现有 Celery task）
  - `AuditTask, Material, Finding, Worksheet, WorksheetRow, SessionLocal` from `app.models`
- Produces:
  - `_load_checkpoint(path: str) -> set[int]`
  - `_append_checkpoint(path: str, task_id: int, status: str) -> None`
  - `_reset_task_for_rerun(db: Session, task_id: int) -> None`
  - `_auto_finalize(db: Session, task: AuditTask) -> None`
  - `_discover_candidate_tasks(db: Session, done_ids: set[int]) -> list[int]`
  - CLI: `python -m app.scripts.rerun_all_tasks_v212 --dry-run|--pilot N|--run [--budget YUAN]`

- [ ] **Step 1: 写第一条失败测试 —— checkpoint 读写 roundtrip**

新建 `compliance-agent/backend/tests/test_rerun_all_tasks_v212.py`：

```python
"""v2.12 全量重跑 + 自动定稿脚本测试。"""
import json

import pytest

from app.models import (
    AuditTask,
    AuditUnit,
    Base,
    Finding,
    Indicator,
    Material,
    SessionLocal,
    Worksheet,
    WorksheetRow,
    engine,
)


@pytest.fixture
def db_session():
    """每测独立 session；清空所有相关表避免跨测污染。"""
    Base.metadata.create_all(engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.query(WorksheetRow).delete()
        s.query(Worksheet).delete()
        s.query(Finding).delete()
        s.query(Material).delete()
        s.query(AuditTask).delete()
        s.query(AuditUnit).delete()
        s.query(Indicator).delete()
        s.commit()
        s.close()


def test_load_checkpoint_returns_done_ids(tmp_path):
    """写 3 条 checkpoint，_load_checkpoint 读回 3 个 task_id。"""
    from app.scripts.rerun_all_tasks_v212 import _load_checkpoint, _append_checkpoint
    cp = tmp_path / "cp.jsonl"
    _append_checkpoint(str(cp), 101, "finalized")
    _append_checkpoint(str(cp), 202, "finalized")
    _append_checkpoint(str(cp), 303, "skipped:failed")
    done = _load_checkpoint(str(cp))
    assert done == {101, 202, 303}
```

- [ ] **Step 2: 跑测试 —— verify RED**

```bash
cd compliance-agent/backend && python -m pytest tests/test_rerun_all_tasks_v212.py::test_load_checkpoint_returns_done_ids -v
```

Expected: FAIL `ModuleNotFoundError: No module named 'app.scripts.rerun_all_tasks_v212'`

- [ ] **Step 3: 写脚本骨架 —— checkpoint helpers**

新建 `compliance-agent/backend/app/scripts/rerun_all_tasks_v212.py`：

```python
"""v2.12：全量任务重跑 + 自动定稿。

支持：
- --dry-run: 列出候选任务数 + 当前累计费用，不 enqueue
- --pilot N: 只跑前 N 个（默认 10），完成后打印统计校准 avg cost
- --run --budget 500: 全量跑，累计费用达 ¥500 停止

断点续跑：checkpoint jsonl 每完成一任务写一行，重启后跳过已完成 task_id
Auto-finalize：AI 完成后直接 SQL 改 status=finalized（跳过人工复核）
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.auth import log_action
from app.llm.deepseek import sum_usage_cost
from app.models import (
    AuditTask,
    Finding,
    Material,
    SessionLocal,
    Worksheet,
    WorksheetRow,
    get_db,
)

DEFAULT_CHECKPOINT = "/app/data/v2.12_rerun_checkpoint.jsonl"


def _load_checkpoint(path: str) -> set[int]:
    """读 checkpoint jsonl，返回已完成 task_id 集合。"""
    if not os.path.exists(path):
        return set()
    ids: set[int] = set()
    with open(path) as f:
        for line in f:
            try:
                e = json.loads(line)
                ids.add(int(e["task_id"]))
            except Exception:
                continue
    return ids


def _append_checkpoint(path: str, task_id: int, status: str) -> None:
    """追加一行 checkpoint（task_id + 最终状态 + 时间戳）。"""
    entry = {
        "task_id": task_id,
        "status": status,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except OSError:
        pass
    with open(path, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
```

- [ ] **Step 4: 跑测试 —— verify GREEN**

```bash
cd compliance-agent/backend && python -m pytest tests/test_rerun_all_tasks_v212.py::test_load_checkpoint_returns_done_ids -v
```

Expected: PASS

- [ ] **Step 5: 加 _reset_task_for_rerun 和它的测试**

在 `rerun_all_tasks_v212.py` 里追加：

```python
def _reset_task_for_rerun(db: Session, task_id: int) -> None:
    """v2.12: 重跑前清空 findings + worksheet + 状态回 pending。

    幂等：重复调用只是把状态从 pending 重置为 pending，无副作用。
    """
    task = db.get(AuditTask, task_id)
    if not task:
        return
    # 删 findings（cascade 不一定配好，显式删）
    db.query(Finding).filter(Finding.task_id == task_id).delete()
    # 删 worksheet + rows
    ws = db.query(Worksheet).filter(Worksheet.task_id == task_id).first()
    if ws:
        db.query(WorksheetRow).filter(WorksheetRow.worksheet_id == ws.id).delete()
        db.delete(ws)
    # 重置任务字段
    task.status = "pending"
    task.progress_current = 0
    task.progress_total = 0
    task.progress_text = ""
    task.summary = ""
    task.stats = ""
    task.completed_at = None
    db.commit()
```

在 `test_rerun_all_tasks_v212.py` 里追加：

```python
def test_reset_task_for_rerun_clears_findings_and_worksheet(db_session):
    """已有 findings + worksheet 的任务被 reset → 表清空 + status=pending。"""
    from app.scripts.rerun_all_tasks_v212 import _reset_task_for_rerun
    # seed
    u = AuditUnit(name="RESET-U", code="R")
    db_session.add(u); db_session.commit()
    t = AuditTask(unit_id=u.id, name="reset test", eval_year=2025,
                  scope="all", status="finalized",
                  summary="旧摘要", stats='{"a":1}',
                  progress_current=100, progress_total=100,
                  progress_text="完成")
    db_session.add(t); db_session.commit()
    ws = Worksheet(task_id=t.id, status="finalized")
    db_session.add(ws); db_session.commit()
    ws_row = WorksheetRow(worksheet_id=ws.id, indicator_id=1,
                          original_score=10.0, audited_score=8.0)
    db_session.add(ws_row); db_session.commit()
    f = Finding(task_id=t.id, indicator_id=1,
                finding_type="完整性", severity="中",
                description="旧疑点")
    db_session.add(f); db_session.commit()

    _reset_task_for_rerun(db_session, t.id)
    db_session.refresh(t)

    assert t.status == "pending"
    assert t.progress_current == 0
    assert t.summary == ""
    assert db_session.query(Finding).filter(Finding.task_id == t.id).count() == 0
    assert db_session.query(Worksheet).filter(Worksheet.task_id == t.id).count() == 0
    assert db_session.query(WorksheetRow).filter(WorksheetRow.worksheet_id == ws.id).count() == 0
```

- [ ] **Step 6: 跑 2 条测试**

```bash
cd compliance-agent/backend && python -m pytest tests/test_rerun_all_tasks_v212.py -v
```

Expected: 2 PASS

- [ ] **Step 7: 加 _auto_finalize 和它的测试**

在 `rerun_all_tasks_v212.py` 追加：

```python
def _auto_finalize(db: Session, task: AuditTask) -> None:
    """v2.12: 跳过人工复核，AI 完成后直接设 finalized。

    - task.status = "finalized"
    - worksheet.status = "finalized"
    - completed_at 更新
    - 无 audit_log 用户（脚本运行不带 user 上下文），仅打印
    """
    ws = db.query(Worksheet).filter(Worksheet.task_id == task.id).first()
    if ws:
        ws.status = "finalized"
    task.status = "finalized"
    task.completed_at = datetime.now(timezone.utc)
    db.commit()
```

在 `test_rerun_all_tasks_v212.py` 追加：

```python
def test_auto_finalize_sets_task_and_worksheet_status(db_session):
    """ai_done 任务 + worksheet → 跑 _auto_finalize → 两者都 finalized。"""
    from app.scripts.rerun_all_tasks_v212 import _auto_finalize
    u = AuditUnit(name="FIN-U", code="F")
    db_session.add(u); db_session.commit()
    t = AuditTask(unit_id=u.id, name="finalize test", eval_year=2025,
                  scope="all", status="ai_done")
    db_session.add(t); db_session.commit()
    ws = Worksheet(task_id=t.id, status="draft")
    db_session.add(ws); db_session.commit()

    _auto_finalize(db_session, t)
    db_session.refresh(t)
    db_session.refresh(ws)

    assert t.status == "finalized"
    assert ws.status == "finalized"
    assert t.completed_at is not None
```

- [ ] **Step 8: 加 _discover_candidate_tasks 和它的测试**

在 `rerun_all_tasks_v212.py` 追加：

```python
def _discover_candidate_tasks(db: Session, done_ids: set[int]) -> list[int]:
    """列出所有候选 task_id：有材料 + 不在 done_ids + status != running。

    避开 running 是防误踢正在跑的任务（避免与其它用户竞争）。
    按 id asc 排序保证跨批次的确定性。
    """
    q = (
        db.query(AuditTask.id)
        .join(Material, Material.task_id == AuditTask.id)
        .filter(AuditTask.status != "running")
    )
    if done_ids:
        q = q.filter(AuditTask.id.notin_(done_ids))
    rows = q.distinct().order_by(AuditTask.id.asc()).all()
    return [r[0] for r in rows]
```

在 `test_rerun_all_tasks_v212.py` 追加：

```python
def test_discover_candidate_tasks_filters_correctly(db_session):
    """候选任务：有材料 + status!=running + 不在 done_ids。"""
    from app.scripts.rerun_all_tasks_v212 import _discover_candidate_tasks
    u = AuditUnit(name="DISC-U", code="D")
    db_session.add(u); db_session.commit()
    # A: 有材料 + finalized → 应命中
    tA = AuditTask(unit_id=u.id, name="A", eval_year=2025,
                   scope="all", status="finalized")
    # B: 有材料 + running → 应过滤（避开在跑）
    tB = AuditTask(unit_id=u.id, name="B", eval_year=2025,
                   scope="all", status="running")
    # C: 无材料 → 应过滤（没材料没意义）
    tC = AuditTask(unit_id=u.id, name="C", eval_year=2025,
                   scope="all", status="pending")
    # D: 有材料 + pending，但已在 done_ids → 应过滤（断点续跑）
    tD = AuditTask(unit_id=u.id, name="D", eval_year=2025,
                   scope="all", status="pending")
    db_session.add_all([tA, tB, tC, tD]); db_session.commit()
    for t in [tA, tB, tD]:
        m = Material(task_id=t.id, indicator_id=None,
                     file_name=f"m_{t.name}.pdf", storage_path="/tmp/x.pdf")
        db_session.add(m)
    db_session.commit()

    candidates = _discover_candidate_tasks(db_session, done_ids={tD.id})
    assert set(candidates) == {tA.id}
```

- [ ] **Step 9: 加 CLI + 主流程**

在 `rerun_all_tasks_v212.py` 末尾追加：

```python
def _process_batches(db: Session, task_ids: list[int], args) -> None:
    """按 batch_size 分批 enqueue + 轮询完成 + auto-finalize。"""
    from app.tasks import run_audit_task

    tp_start, tc_start, cost_start = sum_usage_cost()
    total_processed = 0

    for i in range(0, len(task_ids), args.batch_size):
        # 每批前查累计（仅 --run 模式检查预算）
        _, _, cost_now = sum_usage_cost()
        delta = cost_now - cost_start
        if args.run and delta >= args.budget:
            print(f"⚠️ 达到预算 ¥{args.budget}（本次累计 ¥{delta:.2f}），停止 enqueue 新任务")
            break

        batch = task_ids[i:i + args.batch_size]
        print(f"批次 {i // args.batch_size + 1}：enqueue {len(batch)} 个任务")
        for tid in batch:
            _reset_task_for_rerun(db, tid)
            run_audit_task.delay(tid)

        # 等这批全部跑完
        pending = set(batch)
        while pending:
            time.sleep(args.poll_interval)
            db.expire_all()
            still = set()
            for tid in pending:
                t = db.get(AuditTask, tid)
                if not t:
                    _append_checkpoint(args.checkpoint, tid, "missing")
                    total_processed += 1
                    continue
                if t.status == "ai_done":
                    _auto_finalize(db, t)
                    _append_checkpoint(args.checkpoint, tid, "finalized")
                    total_processed += 1
                elif t.status in ("running", "pending"):
                    still.add(tid)
                else:
                    # failed / archived / 其它异常终态
                    _append_checkpoint(args.checkpoint, tid, f"skipped:{t.status}")
                    total_processed += 1
            pending = still

        _, _, cost_now = sum_usage_cost()
        print(f"进度 {total_processed}/{len(task_ids)}，本次累计 ¥{cost_now - cost_start:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="v2.12 全量任务重跑 + 自动定稿"
    )
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--dry-run", action="store_true", help="只列任务不 enqueue")
    grp.add_argument("--pilot", type=int, metavar="N",
                     help="只跑前 N 个（默认 10）")
    grp.add_argument("--run", action="store_true", help="全量跑")

    parser.add_argument("--budget", type=float, default=500.0,
                        help="预算上限（元），仅 --run 生效")
    parser.add_argument("--checkpoint", default=DEFAULT_CHECKPOINT)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--poll-interval", type=int, default=5,
                        help="轮询 task.status 的间隔秒数")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        done_ids = _load_checkpoint(args.checkpoint)
        candidates = _discover_candidate_tasks(db, done_ids)
        print(f"候选任务: {len(candidates)}（已完成 checkpoint: {len(done_ids)}）")

        tp, tc, cost = sum_usage_cost()
        print(f"当前累计 LLM 费用: ¥{cost:.2f}"
              f" (prompt {tp:,}, completion {tc:,})")

        if args.dry_run:
            print("--dry-run: 不 enqueue，退出。")
            return

        if args.pilot is not None:
            n = args.pilot if args.pilot > 0 else 10
            candidates = candidates[:n]
            print(f"pilot 模式：只跑前 {len(candidates)} 个")

        _process_batches(db, candidates, args)

        # summary
        _, _, cost_end = sum_usage_cost()
        print()
        print(f"完成。本次累计 LLM 费用: ¥{cost_end - cost:.2f}")
        print(f"总累计: ¥{cost_end:.2f}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 10: 跑全部 4 条测试 + regression**

```bash
cd compliance-agent/backend && python -m pytest tests/test_rerun_all_tasks_v212.py tests/test_deepseek_usage_log.py -v
```

Expected: 3 (deepseek usage) + 4 (rerun) = 7 PASS

- [ ] **Step 11: Commit**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/backend/app/scripts/rerun_all_tasks_v212.py \
        compliance-agent/backend/tests/test_rerun_all_tasks_v212.py
git commit -m "$(cat <<'EOF'
feat(v2.12): rerun_all_tasks_v212 批量重跑 + 自动定稿脚本

- 三模式 CLI：--dry-run / --pilot N / --run --budget YUAN
- _load/_append_checkpoint：jsonl 断点续跑
- _reset_task_for_rerun：清 findings + worksheet + status=pending
- _auto_finalize：直接 SQL 改 task/ws status=finalized（跳过人工）
- _discover_candidate_tasks：过滤有材料 + status!=running + 不在 done_ids
- _process_batches：分批 20 enqueue，poll status 到 ai_done/failed，
  每批前查预算，超即停 enqueue
- 4 条 pytest：checkpoint / reset / auto_finalize / discover 过滤

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 部署 + pg_dump + dry-run + pilot 10

**Files:** 无代码改动（部署 Task 1+2 产出的文件）

**Interfaces:** 无

- [ ] **Step 1: Push 到 GitHub**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git push origin main 2>&1 | tail -3
```

Expected: `main -> main` 推送成功。

- [ ] **Step 2: Workbench 上传 2 个后端文件到 ECS**

用户操作：Workbench 拖两个文件到 `/opt/audit/compliance-agent/backend/` 对应路径：
- `backend/app/llm/deepseek.py` → 覆盖
- `backend/app/scripts/rerun_all_tasks_v212.py` → 新文件

- [ ] **Step 3: docker cp + restart 三容器**

用户在 ECS 上跑：

```bash
cd /opt/audit/compliance-agent
for c in backend worker enrich_worker; do
  docker compose cp backend/app/llm/deepseek.py $c:/app/app/llm/deepseek.py
  docker compose cp backend/app/scripts/rerun_all_tasks_v212.py $c:/app/app/scripts/rerun_all_tasks_v212.py
done
docker compose restart backend worker enrich_worker
docker compose logs backend --tail=10 | grep -Ei "error|startup complete"
```

Expected: `Application startup complete.`，无 ImportError。

- [ ] **Step 4: pg_dump 备份 4 张表**

```bash
docker compose exec -T postgres pg_dump -U compliance -d compliance \
    -t audit_tasks -t findings -t worksheets -t worksheet_rows \
    > /opt/audit/backup_v2.12_before_$(date +%Y%m%d_%H%M%S).sql
ls -lh /opt/audit/backup_v2.12_before_*.sql | tail -1
```

Expected: 输出文件 > 100MB（4000+ 任务 + 若干万 findings）。

- [ ] **Step 5: --dry-run 看候选任务数**

```bash
docker compose exec -T backend python -m app.scripts.rerun_all_tasks_v212 --dry-run
```

Expected：
```
候选任务: ~4000 (已完成 checkpoint: 0)
当前累计 LLM 费用: ¥0.00 (prompt 0, completion 0)
--dry-run: 不 enqueue，退出。
```

**记录候选任务数**（后面预算估算要用）。

- [ ] **Step 6: --pilot 10 跑 10 个任务校准**

```bash
docker compose exec -T backend python -m app.scripts.rerun_all_tasks_v212 --pilot 10
```

Expected：
- 阻塞输出，约 15-40 分钟（10 任务 × 2-4 min/任务，worker=2 并发）
- 每完成一批打印 "进度 N/10，本次累计 ¥X.XX"
- 结束打印 "完成。本次累计 LLM 费用: ¥X.XX"

**用户查看**：
- `avg_cost_per_task = cost_total / 10`
- 估算全量费用 = `avg_cost_per_task × 候选任务数`
- 判断 ¥500 预算能覆盖多少百分比

- [ ] **Step 7: 前端 spot check pilot 结果**

用户浏览器打开 `http://8.163.75.9/`，进任意 pilot 处理过的任务（在 audit_tasks 表里 status=finalized 且 completed_at 是最近几分钟）：
- 材料 tab：材料仍在，指标绑定合理
- 核查发现 tab：AI 生成的 findings 显示合理
- 工作底稿 tab：有底稿，status=finalized（只读）

如有明显质量问题，中断此步骤，用户看结果决定是否调整或放弃。

- [ ] **Step 8: 报告 pilot 结果**

**用户把 pilot 结果贴出来给 controller review** —— 至少包含：
- 平均 avg cost/task
- 估算全量总费用
- 抽查的 finalized 任务前端显示是否正常

Controller 根据这个决定是否进 Task 4 全量跑，或者调整预算 / 修脚本。

---

## Task 4: 全量 --run --budget 500 + 观测 + README

**Files:**
- Modify: `compliance-agent/README.md`

**Interfaces:** 无

- [ ] **Step 1: Pilot 结果确认（前置门槛）**

**必须** 用户已确认：
- Pilot 10 跑完，前端抽查 finalized 任务正常
- Avg cost/task 已知，¥500 预算能覆盖预期任务数
- 用户明确说 "跑全量"

未确认则不进后续步骤。

- [ ] **Step 2: 全量 --run 后台执行**

用户在 ECS 上跑（`nohup` 后台，输出到 log 文件，避免终端断连）：

```bash
cd /opt/audit/compliance-agent
nohup docker compose exec -T backend \
    python -m app.scripts.rerun_all_tasks_v212 --run --budget 500 \
    > /opt/audit/v2.12_rerun.log 2>&1 &
echo "PID: $!"
```

Expected: 打印一个 PID（后台运行中）。

- [ ] **Step 3: 观测进度**

用户随时可跑：

```bash
# 看 stdout 日志（进度 / 累计费用 / 错误）
tail -f /opt/audit/v2.12_rerun.log

# 看 checkpoint（已完成任务数）
docker compose exec backend cat /app/data/v2.12_rerun_checkpoint.jsonl | wc -l

# 或从宿主机看（bind mount）
wc -l /opt/audit/compliance-agent/backend/data/v2.12_rerun_checkpoint.jsonl
```

Expected: log 里每批打印一条进度，checkpoint 每完成一任务加一行。

- [ ] **Step 4: 中断（如需）**

如需中途停：

```bash
# 找脚本 PID
pgrep -f rerun_all_tasks_v212

# 或从 backend 容器里 kill
docker compose exec backend pkill -f rerun_all_tasks_v212
```

在飞的最后一批可能会继续跑完（Celery worker 已经拿走了）。Checkpoint 保留，续跑用同样命令。

- [ ] **Step 5: 全量完成后 —— 用户报告**

Log 尾部应有：
```
完成。本次累计 LLM 费用: ¥X.XX
总累计: ¥X.XX
```

用户把最终数字 + 完成任务数（`wc -l checkpoint`）贴给 controller。

- [ ] **Step 6: 后置验证（用户浏览器 3 项）**

- [ ] 工作台"批量导出已定稿工作底稿"card 里各市的 task_count 大幅增加
- [ ] 随机进 3-5 个原本 pending 的任务 → 现在都是 finalized，findings + 底稿正常
- [ ] 后台 audit_tasks 表 finalized 数：`docker compose exec -T postgres psql -U compliance -d compliance -c "SELECT status, COUNT(*) FROM audit_tasks GROUP BY status;"`

- [ ] **Step 7: 更新 README**

Edit `compliance-agent/README.md`。在 `## 更新日志（部分）` 段落里，v2.11 之前插入：

```markdown
- **v2.12（2026-07-16）**：全量任务重跑 + 自动定稿脚本 `app/scripts/rerun_all_tasks_v212.py`。DeepSeek 客户端加 LLM usage 埋点（`_log_usage()` 追加 `/app/data/llm_usage.jsonl`），脚本按 ¥500 预算跑，超即停 enqueue。断点续跑（checkpoint jsonl）。**跳过人工复核直接 finalize** —— 已定稿不再等同人工看过。详见 `docs/superpowers/plans/2026-07-16-batch-rerun-all-tasks-auto-finalize.md`
```

- [ ] **Step 8: Commit README**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/README.md
git commit -m "$(cat <<'EOF'
docs(v2.12): README 加更新日志

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec coverage:**
- ✅ LLM usage 埋点 → Task 1
- ✅ 批量脚本 3 模式（dry-run/pilot/run）→ Task 2 Step 9
- ✅ Checkpoint 断点续跑 → Task 2 Step 3 + Step 4
- ✅ 重跑清 findings + worksheet + status=pending → Task 2 Step 5
- ✅ Auto-finalize 直接 SQL 改 status → Task 2 Step 7
- ✅ 分批 20 enqueue + poll → Task 2 Step 9 (`_process_batches`)
- ✅ 预算守卫每批前查 → Task 2 Step 9
- ✅ 候选任务过滤 (有材料 + status!=running + 不在 done_ids) → Task 2 Step 8
- ✅ pg_dump 备份 4 表 → Task 3 Step 4
- ✅ dry-run → Task 3 Step 5
- ✅ pilot 10 校准 → Task 3 Step 6
- ✅ 用户 pilot 结果 review 门槛 → Task 4 Step 1
- ✅ 全量后台跑 + observability → Task 4 Step 2/3
- ✅ 完成后 3 项验证 → Task 4 Step 6
- ✅ README → Task 4 Step 7
- ⚠️ Spec 提到 audit_log detail 明确标记 "v2.12 batch auto-finalize (no human review)" —— 但脚本无 user 上下文，跳过 log_action。**决策**：不写 audit_log（脚本外的 SQL 也不写 log）。REQUEST: 如果 controller 觉得必需要写，改用系统 admin user id 传 log_action

**Placeholder scan:**
- 无 TODO/TBD
- 所有代码块完整
- 所有命令带 Expected

**Type consistency:**
- `_load_checkpoint(path: str) -> set[int]` 一致
- `_append_checkpoint(path: str, task_id: int, status: str) -> None` 一致
- `_reset_task_for_rerun(db, task_id: int) -> None` 一致
- `_auto_finalize(db, task: AuditTask) -> None` 一致
- `_discover_candidate_tasks(db, done_ids: set[int]) -> list[int]` 一致
- `sum_usage_cost(path) -> tuple[int, int, float]` 一致（Task 1 + Task 2 都用）
- Args attributes 一致：`args.dry_run / pilot / run / budget / checkpoint / batch_size / poll_interval`

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-16-batch-rerun-all-tasks-auto-finalize.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — Task 1/2 派 fresh subagent + review；Task 3/4 用户手动跑 + 关键 checkpoint 停下确认

**2. Inline Execution** — 本会话直接跑 Task 1/2，Task 3/4 hand-off 给用户

Which approach?
